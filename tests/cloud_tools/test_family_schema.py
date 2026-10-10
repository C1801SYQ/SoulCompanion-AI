"""PC02 provisioning uses synthetic metadata and never calls a real cloud."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cloud_admin
import cloud_family_schema as family
from cloud_admin import AdminError, ENV_ID, REGION
from cloud_schema import load_manifest as load_base_manifest


KEY = "synthetic-family-server-key"
SCHEMA = "sc_v2_app_schema"
PARENTS = "sc_v2_parent_profiles"
SYSTEM_INDEXES = [
    {"Name": "_id_", "Keys": [{"Name": "_id", "Direction": "1"}], "Unique": True},
    {"Name": "_openid_1", "Keys": [{"Name": "_openid", "Direction": "1"}], "Unique": False},
]


class FakeAdmin:
    def __init__(self):
        base = load_base_manifest()
        self.tables = {item["name"]: deepcopy(SYSTEM_INDEXES) for item in base["collections"]}
        self.acls = {name: "ADMINONLY" for name in self.tables}
        self.writes = []
        self.preflights = 0
        self.audit = {
            "env_id": ENV_ID, "region": REGION, "database_id": "synthetic-existing-db",
            "package_id": "baas_trial", "overrun": False, "auto_renew": False,
        }
        self.reject_index = False
        self.fail_create = False
        self.pager = {}

    def preflight(self):
        self.preflights += 1
        return deepcopy(self.audit)

    def api(self, action, body, write=False):
        assert body["EnvId"] == ENV_ID
        name = body.get("TableName", body.get("CollectionName"))
        if write:
            assert action in {"CreateTable", "UpdateTable"}
            assert name == PARENTS
            self.writes.append((action, deepcopy(body)))
        if action == "ListTables":
            pager = {"Limit": 100, "Offset": 0, "Total": len(self.tables), **self.pager} if isinstance(self.pager, dict) else self.pager
            return {"Tables": [{"TableName": item} for item in self.tables], "Pager": pager}
        if action == "CreateTable":
            if self.fail_create:
                raise AdminError("SYNTHETIC_CREATE_REJECTED")
            assert name not in self.tables
            self.tables[name] = deepcopy(SYSTEM_INDEXES)
            self.acls[name] = body["PermissionInfo"]["AclTag"]
        elif action == "DescribeDatabaseACL":
            return {"AclTag": self.acls[name]}
        elif action == "DescribeTable":
            return {"Indexes": deepcopy(self.tables[name])}
        elif action == "UpdateTable" and not self.reject_index:
            for index in body["CreateIndexes"]:
                self.tables[name].append({
                    "Name": index["IndexName"], "Keys": index["MgoKeySchema"]["MgoIndexKeys"],
                    "Unique": index["MgoKeySchema"]["MgoIsUnique"],
                })
        return {}


class FakeDocuments:
    def __init__(self, manifest):
        base = manifest["base_schema"]
        self.records = {
            "phase04": {"_id": "phase04", "owner": base["owner"], "checksum": base["checksum"], "version": 1},
        }
        self.writes = []
        self.before_promotion = None

    def seed_family(self, manifest, version=0):
        self.records[manifest["marker_id"]] = {
            "_id": manifest["marker_id"], "owner": manifest["owner"],
            "checksum": manifest["checksum"], "version": version,
        }

    def __call__(self, request):
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert f"/collections/{SCHEMA}/documents" in request.url.path
        marker_id = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            if marker_id not in self.records:
                return httpx.Response(404)
            document = deepcopy(self.records[marker_id])
            if type(document.get("version")) is int:
                document["version"] = {"$numberInt": str(document["version"])}
            return httpx.Response(200, json=document)
        body = json.loads(request.content)
        self.writes.append((request.method, marker_id, deepcopy(body)))
        if request.method == "POST":
            document = body["data"][0]
            assert document["_id"] == family.FAMILY_MARKER_ID
            assert document["_id"] not in self.records
            self.records[document["_id"]] = document
            return httpx.Response(201, json={"insertedIds": [document["_id"]]})
        assert request.method == "PATCH" and marker_id == "documents"
        assert body == {
            "query": {"_id": family.FAMILY_MARKER_ID, "owner": family.FAMILY_SCHEMA_OWNER,
                      "checksum": family.FAMILY_SCHEMA_CHECKSUM, "version": 0},
            "data": {"$set": {"version": 2}}, "multi": False, "upsert": False, "replaceMode": False,
        }
        if self.before_promotion:
            self.before_promotion()
        marker_id = body["query"]["_id"]
        if any(self.records[marker_id].get(field) != value for field, value in body["query"].items()):
            return httpx.Response(200, json={"matched": 0, "updated": 0})
        self.records[marker_id].update(body["data"]["$set"])
        return httpx.Response(200, json={"matched": 1, "updated": 1})


@pytest.fixture
def resources():
    manifest = family.load_manifest()
    return FakeAdmin(), FakeDocuments(manifest), manifest


def apply(admin, documents, manifest, *, authorized=True):
    with httpx.Client(transport=httpx.MockTransport(documents)) as client:
        return family.FamilySchemaProvisioner(admin, client, KEY).provision(
            manifest, cloud_write_authorized=authorized,
        )


def owned_table(admin, documents, manifest, *, version=0, index=True):
    documents.seed_family(manifest, version)
    admin.tables[PARENTS] = deepcopy(SYSTEM_INDEXES)
    admin.acls[PARENTS] = "ADMINONLY"
    if index:
        expected = manifest["collections"][0]["indexes"][0]
        admin.tables[PARENTS].append({
            "Name": expected["name"], "Keys": [{"Name": key, "Direction": direction} for key, direction in expected["keys"]],
            "Unique": expected["unique"],
        })


def assert_no_writes(admin, documents):
    assert admin.writes == []
    assert documents.writes == []


def test_manifest_binds_runtime_and_unchanged_base():
    manifest = family.load_manifest()
    assert manifest["checksum"] == family.FAMILY_SCHEMA_CHECKSUM
    assert manifest["base_schema"]["checksum"] == family.PHASE04_SCHEMA_CHECKSUM
    assert manifest["owner"] == family.FAMILY_SCHEMA_OWNER
    assert manifest["marker_id"] == family.FAMILY_MARKER_ID
    assert manifest["version"] == family.FAMILY_SCHEMA_VERSION


def test_changed_manifest_or_base_checksum_is_rejected(tmp_path):
    original = json.loads(family.MANIFEST.read_text(encoding="utf-8"))
    original["collections"][0]["indexes"][0]["unique"] = False
    changed = tmp_path / "002.json"
    changed.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(AdminError, match="FAMILY_MANIFEST_CHECKSUM_MISMATCH"):
        family.load_manifest(changed)
    base = json.loads(family.BASE_MANIFEST.read_text(encoding="utf-8"))
    base["owner"] = "foreign-base-owner"
    changed_base = tmp_path / "001.json"
    changed_base.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(AdminError, match="BASE_MANIFEST_CHECKSUM_MISMATCH"):
        family.load_manifest(base_path=changed_base)


def test_additive_apply_and_rerun_preserve_all_base_resources(resources):
    admin, documents, manifest = resources
    old_tables, old_acls, old_marker = deepcopy(admin.tables), deepcopy(admin.acls), deepcopy(documents.records["phase04"])
    result = apply(admin, documents, manifest)
    assert result["collections_created"] == [PARENTS]
    assert result["indexes_created"] == [f"{PARENTS}/pc02_parent_owner_unique"]
    assert result["schema_version"] == 2
    assert documents.records[family.FAMILY_MARKER_ID]["version"] == 2
    assert {key: admin.tables[key] for key in old_tables} == old_tables
    assert {key: admin.acls[key] for key in old_acls} == old_acls
    assert documents.records["phase04"] == old_marker
    writes = deepcopy((admin.writes, documents.writes))
    repeated = apply(admin, documents, manifest)
    assert repeated["collections_created"] == [] and repeated["indexes_created"] == []
    assert (admin.writes, documents.writes) == writes
    assert admin.preflights == 2


@pytest.mark.parametrize("marker", [None, {"_id": family.FAMILY_MARKER_ID, "owner": "foreign", "checksum": "foreign", "version": 0}])
def test_foreign_collection_collision_never_adopts_or_changes_acl(resources, marker):
    admin, documents, manifest = resources
    admin.tables[PARENTS] = []
    admin.acls[PARENTS] = "READONLY"
    if marker is not None:
        documents.records[family.FAMILY_MARKER_ID] = marker
    with pytest.raises(AdminError, match="FAMILY_SCHEMA_NOT_OWNED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("version", [1, 3, True, None, "2"])
def test_unknown_owned_marker_version_is_refused(resources, version):
    admin, documents, manifest = resources
    documents.seed_family(manifest, version)
    with pytest.raises(AdminError, match="FAMILY_MARKER_VERSION_UNSUPPORTED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("field,value", [("_id", "other"), ("owner", "foreign"), ("checksum", "different"), ("version", 0), ("version", True)])
def test_phase04_marker_mismatch_refuses_every_write(resources, field, value):
    admin, documents, manifest = resources
    documents.records["phase04"][field] = value
    with pytest.raises(AdminError, match="BASE_SCHEMA_NOT_READY"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("field,value", [
    ("env_id", "other-environment"), ("region", "ap-guangzhou"), ("package_id", "baas_personal"),
    ("overrun", True), ("overrun", None), ("auto_renew", True), ("auto_renew", None), ("database_id", ""),
])
def test_fresh_wrong_environment_region_or_paid_flags_refuse_writes(resources, field, value):
    admin, documents, manifest = resources
    admin.audit[field] = value
    with pytest.raises(AdminError, match="FAMILY_PREFLIGHT_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("table_exists", [False, True])
def test_partial_owned_marker_can_resume_without_touching_old_resources(resources, table_exists):
    admin, documents, manifest = resources
    documents.seed_family(manifest)
    if table_exists:
        owned_table(admin, documents, manifest, index=False)
    apply(admin, documents, manifest)
    assert documents.records[family.FAMILY_MARKER_ID]["version"] == 2
    assert not any(method == "POST" for method, _, _ in documents.writes)
    assert len(admin.writes) == (1 if table_exists else 2)


@pytest.mark.parametrize("mismatch", ["acl", "keys", "unique", "foreign_index"])
def test_owned_parent_acl_or_index_mismatch_is_not_silently_overwritten(resources, mismatch):
    admin, documents, manifest = resources
    owned_table(admin, documents, manifest)
    if mismatch == "acl":
        admin.acls[PARENTS] = "READONLY"
    elif mismatch == "keys":
        admin.tables[PARENTS][-1]["Keys"] = [{"Name": "wrong_owner", "Direction": "1"}]
    elif mismatch == "unique":
        admin.tables[PARENTS][-1]["Unique"] = False
    else:
        admin.tables[PARENTS].append({"Name": "foreign_index", "Keys": [], "Unique": False})
    with pytest.raises(AdminError, match="COLLECTION_ACL_NOT_VERIFIED|INDEX_DEFINITION_MISMATCH|UNEXPECTED_PARENT_INDEX"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("failure", ["create", "index"])
def test_failure_keeps_owned_pending_marker_and_can_resume(resources, failure):
    admin, documents, manifest = resources
    admin.fail_create = failure == "create"
    admin.reject_index = failure == "index"
    with pytest.raises(AdminError, match="SYNTHETIC_CREATE_REJECTED|INDEX_BUILD_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert documents.records[family.FAMILY_MARKER_ID]["version"] == 0
    assert not any(method == "PATCH" for method, _, _ in documents.writes)
    admin.fail_create = admin.reject_index = False
    apply(admin, documents, manifest)
    assert documents.records[family.FAMILY_MARKER_ID]["version"] == 2


@pytest.mark.parametrize("missing", ["table", "index"])
def test_completed_marker_with_missing_resource_is_refused_without_repair(resources, missing):
    admin, documents, manifest = resources
    owned_table(admin, documents, manifest, version=2, index=missing != "index")
    if missing == "table":
        del admin.tables[PARENTS]
    with pytest.raises(AdminError, match="READY_FAMILY_SCHEMA_INCOMPLETE"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


def test_incomplete_listing_and_missing_base_collection_refuse_writes(resources):
    admin, documents, manifest = resources
    admin.pager = {"Total": len(admin.tables) + 1}
    with pytest.raises(AdminError, match="COLLECTION_AUDIT_INCOMPLETE"):
        apply(admin, documents, manifest)
    admin.pager = {}
    del admin.tables["sc_v2_users"]
    with pytest.raises(AdminError, match="BASE_SCHEMA_NOT_READY"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("pager", [
    None, 1, {"Limit": None}, {"Limit": 99}, {"Limit": True},
    {"Offset": None}, {"Offset": 1}, {"Offset": False},
    {"Total": None}, {"Total": "7"}, {"Total": True},
    {"Total": -1}, {"Total": 6}, {"Total": 8},
])
def test_real_list_tables_pagination_must_prove_complete_first_page(resources, pager):
    admin, documents, manifest = resources
    admin.pager = pager
    with pytest.raises(AdminError, match="COLLECTION_AUDIT_INCOMPLETE"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


def test_mutated_loaded_manifest_cannot_bypass_binding(resources):
    admin, documents, manifest = resources
    manifest["collections"][0]["name"] = "sc_v2_other"
    with pytest.raises(AdminError, match="FAMILY_MANIFEST_CHECKSUM_MISMATCH"):
        apply(admin, documents, manifest)
    assert admin.preflights == 0
    assert_no_writes(admin, documents)


def test_provision_requires_explicit_authorization_before_network(resources):
    admin, documents, manifest = resources
    with pytest.raises(AdminError, match="CLOUD_WRITE_AUTHORIZATION_REQUIRED"):
        apply(admin, documents, manifest, authorized=False)
    assert admin.preflights == 0
    assert_no_writes(admin, documents)


def test_marker_changed_after_audit_cannot_be_promoted(resources):
    admin, documents, manifest = resources

    def change_owner():
        documents.records[family.FAMILY_MARKER_ID]["owner"] = "concurrent-foreign-owner"

    documents.before_promotion = change_owner
    with pytest.raises(AdminError, match="FAMILY_MARKER_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert documents.records[family.FAMILY_MARKER_ID]["owner"] == "concurrent-foreign-owner"
    assert documents.records[family.FAMILY_MARKER_ID]["version"] == 0
    assert documents.records["phase04"]["version"] == 1


@pytest.mark.parametrize("args", [[], ["--plan"], ["--cloud-write-authorized"]])
def test_default_and_explicit_plan_are_offline_and_never_load_private_environment(monkeypatch, capsys, args):
    def forbidden(*args, **kwargs):
        pytest.fail("An offline plan cannot access CLI, network or private environment")
    monkeypatch.setattr(family, "CloudAdmin", forbidden)
    monkeypatch.setattr(cloud_admin, "load_private_environment", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    family.main(args)
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "plan"
    assert output["new_collections"] == 1 and output["new_indexes"] == 1
    assert output["backfill"] is False and output["paid_upgrade"] is False
    assert output["destructive_operations"] == []


def test_apply_without_explicit_authorization_never_loads_private_environment(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Authorization must be checked before cloud or secret access")
    monkeypatch.setattr(family, "CloudAdmin", forbidden)
    monkeypatch.setattr(cloud_admin, "load_private_environment", forbidden)
    with pytest.raises(AdminError, match="CLOUD_WRITE_AUTHORIZATION_REQUIRED"):
        family.main(["--apply"])


def test_plan_and_apply_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit) as error:
        family.main(["--plan", "--apply", "--cloud-write-authorized"])
    assert error.value.code == 2
