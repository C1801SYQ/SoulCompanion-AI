"""PC03 schema provisioning uses synthetic resources and Fake HTTP only."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cloud_admin
import cloud_community_schema as community
from cloud_admin import AdminError, ENV_ID, REGION


KEY = "synthetic-pc03-key"
SYSTEM_INDEXES = [
    {"Name": "_id_", "Keys": [{"Name": "_id", "Direction": "1"}], "Unique": False},
    {"Name": "_openid_1", "Keys": [{"Name": "_openid", "Direction": "1"}], "Unique": False},
]


def actual_index(expected):
    return {
        "Name": expected["name"], "Keys": [{"Name": field, "Direction": direction} for field, direction in expected["keys"]],
        "Unique": expected["unique"], "Sparse": False, "PartialFilterExpression": "",
    }


class FakeAdmin:
    def __init__(self):
        self.legacy = [
            collection for manifest in community.dependency_manifests(community.BASE_MANIFEST, community.FAMILY_MANIFEST)
            for collection in manifest["collections"]
        ]
        self.tables = {
            item["name"]: [*deepcopy(SYSTEM_INDEXES), *[actual_index(index) for index in item["indexes"]]]
            for item in self.legacy
        }
        self.acls = {name: "ADMINONLY" for name in self.tables}
        self.audit = {
            "env_id": ENV_ID, "region": REGION, "database_id": community.DATABASE_ID,
            "package_id": "baas_trial", "overrun": False, "auto_renew": False,
        }
        self.environment_info = {"EnvInfo": {"EnvBaseInfo": {
            "EnvId": ENV_ID, "Region": REGION, "Status": "NORMAL",
            "Databases": [{"InstanceId": community.DATABASE_ID, "Status": "RUNNING"}],
        }}}
        self.environment_reads = 0
        self.writes = []
        self.preflights = 0
        self.pager = {}
        self.fail_create = False
        self.reject_indexes = False
        self.before_write = None
        self.duplicate_table = False

    def preflight(self):
        self.preflights += 1
        return deepcopy(self.audit)

    def api(self, action, body, write=False):
        assert body["EnvId"] == ENV_ID
        if action == "DescribeEnvInfo":
            assert write is False
            self.environment_reads += 1
            return deepcopy(self.environment_info)
        name = body.get("TableName", body.get("CollectionName"))
        if write:
            assert action in {"CreateTable", "UpdateTable"}
            assert name in community.COMMUNITY_COLLECTIONS.values()
            self.writes.append((action, deepcopy(body)))
            if self.before_write:
                self.before_write(action, body)
        if action == "ListTables":
            tables = [{"TableName": name} for name in self.tables]
            if self.duplicate_table:
                tables.append(deepcopy(tables[0]))
            pager = {"Limit": 100, "Offset": 0, "Total": len(tables), **self.pager} if isinstance(self.pager, dict) else self.pager
            return {"Tables": tables, "Pager": pager}
        if action == "DescribeDatabaseACL":
            return {"AclTag": self.acls[name]}
        if action == "DescribeTable":
            return {"IndexNum": len(self.tables[name]), "Indexes": deepcopy(self.tables[name])}
        if action == "CreateTable":
            if self.fail_create:
                raise AdminError("SYNTHETIC_CREATE_FAILURE")
            assert name not in self.tables
            assert body["PermissionInfo"] == {"AclTag": "ADMINONLY", "EnvId": ENV_ID}
            self.tables[name] = deepcopy(SYSTEM_INDEXES)
            self.acls[name] = "ADMINONLY"
        elif action == "UpdateTable" and not self.reject_indexes:
            for index in body["CreateIndexes"]:
                self.tables[name].append({
                    "Name": index["IndexName"], "Keys": index["MgoKeySchema"]["MgoIndexKeys"],
                    "Unique": index["MgoKeySchema"]["MgoIsUnique"], "Sparse": False, "PartialFilterExpression": "",
                })
        return {}


class FakeDocuments:
    def __init__(self):
        self.records = {
            marker_id: {"_id": marker_id, "owner": owner, "checksum": checksum, "version": version}
            for marker_id, owner, checksum, version in community.COMMUNITY_BASE_MARKERS
        }
        # A separate synthetic private record must never be read or changed.
        self.records["synthetic-private-user"] = {"_id": "synthetic-private-user", "private": "untouched"}
        self.writes = []
        self.before_promotion = None
        self.post_ack = None
        self.patch_ack = None
        self.requests = []

    def seed(self, version=0):
        self.records[community.COMMUNITY_MARKER_ID] = {
            "_id": community.COMMUNITY_MARKER_ID, "owner": community.COMMUNITY_SCHEMA_OWNER,
            "checksum": community.COMMUNITY_SCHEMA_CHECKSUM, "version": version,
            "reservation_id": str(uuid4()),
        }

    def __call__(self, request):
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert f"/collections/{community.SCHEMA_COLLECTION}/documents" in request.url.path
        marker_id = request.url.path.rsplit("/", 1)[-1]
        self.requests.append((request.method, marker_id))
        if request.method == "GET":
            if marker_id not in self.records:
                return httpx.Response(404)
            document = deepcopy(self.records[marker_id])
            if type(document.get("version")) is int:
                document["version"] = {"$numberInt": str(document["version"])}
            return httpx.Response(200, json=document)
        body = json.loads(request.content)
        self.writes.append((request.method, deepcopy(body)))
        if request.method == "POST":
            record = body["data"][0]
            assert record["_id"] == community.COMMUNITY_MARKER_ID
            if record["_id"] in self.records:
                return httpx.Response(409)
            self.records[record["_id"]] = record
            return httpx.Response(201, json=self.post_ack if self.post_ack is not None else {"insertedIds": [record["_id"]]})
        assert request.method == "PATCH" and marker_id == "documents"
        query = body["query"]
        assert set(query) == {"_id", "owner", "checksum", "version", "reservation_id"}
        assert query["_id"] == community.COMMUNITY_MARKER_ID
        assert body["data"] == {"$set": {"version": 3}}
        assert body["multi"] is False and body["upsert"] is False and body["replaceMode"] is False
        if self.before_promotion:
            self.before_promotion()
        record = self.records[query["_id"]]
        if any(type(record.get(field)) is not type(value) or record.get(field) != value for field, value in query.items()):
            return httpx.Response(200, json={"matched": 0, "updated": 0})
        if self.patch_ack is not None:
            return httpx.Response(200, json=self.patch_ack)
        record.update(body["data"]["$set"])
        return httpx.Response(200, json={"matched": 1, "updated": 1})


@pytest.fixture
def resources():
    return FakeAdmin(), FakeDocuments(), community.load_manifest()


def apply(admin, documents, manifest, *, authorized=True):
    with httpx.Client(transport=httpx.MockTransport(documents)) as client:
        return community.CommunitySchemaProvisioner(admin, client, KEY).provision(
            manifest, cloud_write_authorized=authorized,
        )


def seed_resources(admin, documents, manifest, *, version=0, indexes=True):
    documents.seed(version)
    for collection in manifest["collections"]:
        admin.tables[collection["name"]] = deepcopy(SYSTEM_INDEXES)
        admin.acls[collection["name"]] = "ADMINONLY"
        if indexes:
            admin.tables[collection["name"]].extend(actual_index(index) for index in collection["indexes"])


def assert_no_writes(admin, documents):
    assert admin.writes == [] and documents.writes == []


def test_manifest_runtime_binding_and_legacy_hashes():
    manifest = community.load_manifest()
    assert manifest["checksum"] == community.COMMUNITY_SCHEMA_CHECKSUM
    assert manifest["marker_id"] == "pc03-parent-community"
    assert manifest["owner"] == "SoulCompanion-AI/pc03" and manifest["version"] == 3
    assert len(manifest["collections"]) == 5
    assert sum(len(item["indexes"]) for item in manifest["collections"]) == 14
    assert {item["name"] for item in manifest["collections"]} == set(community.COMMUNITY_COLLECTIONS.values())
    assert community.canonical_checksum(community.read_json(community.BASE_MANIFEST)) == community.COMMUNITY_BASE_MARKERS[0][2]
    assert community.canonical_checksum(community.read_json(community.FAMILY_MANIFEST)) == community.COMMUNITY_BASE_MARKERS[1][2]


@pytest.mark.parametrize("source", ["new", "phase04", "pc02"])
def test_changed_manifest_is_rejected_before_network(resources, tmp_path, source):
    admin, documents, manifest = resources
    if source == "new":
        manifest["collections"][0]["indexes"][0]["keys"][0][0] = "foreign"
        with pytest.raises(AdminError, match="COMMUNITY_MANIFEST_CHECKSUM_MISMATCH"):
            apply(admin, documents, manifest)
    else:
        path = community.BASE_MANIFEST if source == "phase04" else community.FAMILY_MANIFEST
        altered = community.read_json(path)
        altered["owner"] = "foreign"
        changed = tmp_path / "schema.json"
        changed.write_text(json.dumps(altered), encoding="utf-8")
        keyword = {"base_path" if source == "phase04" else "family_path": changed}
        with pytest.raises(AdminError, match="DEPENDENCY_MANIFEST_CHECKSUM_MISMATCH"):
            community.load_manifest(**keyword)
    assert admin.preflights == 0
    assert_no_writes(admin, documents)


def test_additive_apply_and_completed_rerun_preserve_every_legacy_resource(resources):
    admin, documents, manifest = resources
    old_tables, old_acls, old_records = deepcopy(admin.tables), deepcopy(admin.acls), deepcopy(documents.records)
    result = apply(admin, documents, manifest)
    assert result["status"] == "pass" and result["schema_version"] == 3
    assert len(result["collections_created"]) == 5 and len(result["indexes_created"]) == 14
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == 3
    assert {name: admin.tables[name] for name in old_tables} == old_tables
    assert {name: admin.acls[name] for name in old_acls} == old_acls
    assert {key: documents.records[key] for key in old_records} == old_records
    writes = deepcopy((admin.writes, documents.writes))
    repeated = apply(admin, documents, manifest)
    assert repeated["collections_created"] == [] and repeated["indexes_created"] == []
    assert (admin.writes, documents.writes) == writes and admin.preflights == 2
    assert not any(marker == "synthetic-private-user" for _, marker in documents.requests)


@pytest.mark.parametrize("field,value", [
    ("env_id", "foreign"), ("region", "ap-guangzhou"), ("package_id", "paid"),
    ("overrun", True), ("overrun", None), ("auto_renew", True), ("auto_renew", None),
    ("database_id", ""), ("database_id", None), ("database_id", "foreign-db"),
])
def test_exact_environment_and_billing_are_required(resources, field, value):
    admin, documents, manifest = resources
    admin.audit[field] = value
    with pytest.raises(AdminError, match="COMMUNITY_PREFLIGHT_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("field,value", [
    ("EnvId", "foreign-environment"), ("EnvId", None),
    ("Region", "ap-guangzhou"), ("Region", None),
    ("Status", "SUSPENDED"), ("Status", None),
    ("Databases", None), ("Databases", {}), ("Databases", []),
    ("Databases", [None]), ("Databases", [{}]),
    ("Databases", [{"InstanceId": community.DATABASE_ID}]),
    ("Databases", [{"InstanceId": "foreign-db", "Status": "RUNNING"}]),
    ("Databases", [{"InstanceId": community.DATABASE_ID, "Status": "STOPPED"}]),
    ("Databases", [{"InstanceId": community.DATABASE_ID, "Status": "RUNNING"}] * 2),
])
def test_actual_environment_response_must_match_before_any_schema_write(resources, field, value):
    admin, documents, manifest = resources
    # Configured legacy preflight still says the correct region/database: only
    # the independently returned actual target is changed in this regression.
    admin.environment_info["EnvInfo"]["EnvBaseInfo"][field] = value
    with pytest.raises(AdminError, match="COMMUNITY_PREFLIGHT_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert admin.environment_reads == 1
    assert documents.requests == []
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("response", [None, [], {}, {"EnvInfo": None}, {"EnvInfo": []},
    {"EnvInfo": {}}, {"EnvInfo": {"EnvBaseInfo": None}}, {"EnvInfo": {"EnvBaseInfo": []}}])
def test_missing_actual_target_structure_cannot_reserve_schema_marker(resources, response):
    admin, documents, manifest = resources
    admin.environment_info = response
    with pytest.raises(AdminError, match="COMMUNITY_PREFLIGHT_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert documents.requests == []
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("pager", [
    None, 1, {"Limit": True}, {"Limit": 99}, {"Offset": False}, {"Offset": 1},
    {"Total": True}, {"Total": "8"}, {"Total": 7}, {"Total": 9}, {"Total": None},
])
def test_listing_requires_complete_strict_integer_pager(resources, pager):
    admin, documents, manifest = resources
    admin.pager = pager
    with pytest.raises(AdminError, match="COLLECTION_AUDIT_INCOMPLETE"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


def test_duplicate_table_listing_is_rejected(resources):
    admin, documents, manifest = resources
    admin.duplicate_table = True
    with pytest.raises(AdminError, match="COLLECTION_AUDIT_INCOMPLETE"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


def test_missing_legacy_collection_blocks_marker_reservation(resources):
    admin, documents, manifest = resources
    del admin.tables["sc_v2_parent_profiles"]
    with pytest.raises(AdminError, match="DEPENDENCY_SCHEMA_NOT_READY"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("reported_count", [True, "3", -1, 100])
def test_describe_table_index_count_must_prove_complete_list(resources, reported_count):
    admin, documents, manifest = resources
    original = admin.api

    def altered(action, body, write=False):
        response = original(action, body, write)
        if action == "DescribeTable":
            response["IndexNum"] = reported_count
        return response

    admin.api = altered
    with pytest.raises(AdminError, match="INDEX_BUILD_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("name", [
    "sc_v2_users", "sc_v2_identities", "sc_v2_child_profiles", "sc_v2_sessions",
    "sc_v2_emotion_records", "sc_v2_reports", "sc_v2_app_schema", "sc_v2_parent_profiles",
])
def test_each_legacy_collection_acl_is_checked_before_any_write(resources, name):
    admin, documents, manifest = resources
    admin.acls[name] = "READONLY"
    with pytest.raises(AdminError, match="COLLECTION_ACL_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("name", [
    "sc_v2_identities", "sc_v2_child_profiles", "sc_v2_sessions",
    "sc_v2_emotion_records", "sc_v2_reports", "sc_v2_parent_profiles",
])
@pytest.mark.parametrize("corruption", ["missing", "keys", "unique", "partial", "sparse"])
def test_each_legacy_index_definition_is_protected(resources, name, corruption):
    admin, documents, manifest = resources
    index = admin.tables[name][-1]
    if corruption == "missing":
        admin.tables[name].pop()
    elif corruption == "keys":
        index["Keys"] = [{"Name": "foreign", "Direction": "1"}]
    elif corruption == "unique":
        index["Unique"] = not index["Unique"]
    elif corruption == "partial":
        index["PartialFilterExpression"] = '{"active":true}'
    else:
        index["Sparse"] = True
    with pytest.raises(AdminError, match="INDEX_DEFINITION_MISMATCH|INDEX_BUILD_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("marker_id", ["phase04", "pc02-family-identity"])
@pytest.mark.parametrize("field,value", [("owner", "foreign"), ("checksum", "foreign"), ("version", 0), ("version", True)])
def test_both_dependency_markers_must_match(resources, marker_id, field, value):
    admin, documents, manifest = resources
    documents.records[marker_id][field] = value
    with pytest.raises(AdminError, match="DEPENDENCY_SCHEMA_NOT_READY"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("version", [1, 2, 4, True, None, "3"])
def test_unknown_pc03_marker_version_is_not_adopted(resources, version):
    admin, documents, manifest = resources
    documents.seed(version)
    with pytest.raises(AdminError, match="COMMUNITY_SCHEMA_NOT_OWNED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("reservation", [None, "invalid", "ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB"])
def test_reservation_identity_is_required(resources, reservation):
    admin, documents, manifest = resources
    documents.seed()
    documents.records[community.COMMUNITY_MARKER_ID]["reservation_id"] = reservation
    with pytest.raises(AdminError, match="COMMUNITY_RESERVATION_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("owned", [False, True])
def test_foreign_resource_or_marker_never_adopted(resources, owned):
    admin, documents, manifest = resources
    name = manifest["collections"][0]["name"]
    admin.tables[name] = deepcopy(SYSTEM_INDEXES)
    admin.acls[name] = "READONLY"
    if owned:
        documents.seed()
        documents.records[community.COMMUNITY_MARKER_ID]["owner"] = "foreign"
    with pytest.raises(AdminError, match="COMMUNITY_SCHEMA_NOT_OWNED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("missing", ["table", "index"])
def test_completed_schema_with_missing_resource_is_readonly_failure(resources, missing):
    admin, documents, manifest = resources
    seed_resources(admin, documents, manifest, version=3)
    name = manifest["collections"][0]["name"]
    if missing == "table":
        del admin.tables[name]
    else:
        admin.tables[name].pop()
    with pytest.raises(AdminError, match="READY_COMMUNITY_SCHEMA_INCOMPLETE"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("failure", ["create", "index"])
def test_partial_failure_leaves_version_zero_and_can_resume(resources, failure):
    admin, documents, manifest = resources
    admin.fail_create = failure == "create"
    admin.reject_indexes = failure == "index"
    old_tables = deepcopy(admin.tables)
    with pytest.raises(AdminError, match="SYNTHETIC_CREATE_FAILURE|INDEX_BUILD_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == 0
    assert not any(method == "PATCH" for method, _ in documents.writes)
    admin.fail_create = admin.reject_indexes = False
    apply(admin, documents, manifest)
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == 3
    assert sum(method == "POST" for method, _ in documents.writes) == 1
    assert {name: admin.tables[name] for name in old_tables} == old_tables


def test_partial_owned_indexes_only_add_missing_definitions(resources):
    admin, documents, manifest = resources
    seed_resources(admin, documents, manifest, indexes=False)
    collection = manifest["collections"][0]
    retained = actual_index(collection["indexes"][0])
    admin.tables[collection["name"]].append(retained)
    result = apply(admin, documents, manifest)
    assert result["collections_created"] == [] and len(result["indexes_created"]) == 13
    assert f"{collection['name']}/{retained['Name']}" not in result["indexes_created"]


@pytest.mark.parametrize("corruption", ["keys", "unique", "sparse", "partial", "duplicate", "foreign", "state"])
def test_owned_new_resource_mismatch_is_not_silently_repaired(resources, corruption):
    admin, documents, manifest = resources
    seed_resources(admin, documents, manifest)
    name = manifest["collections"][0]["name"]
    index = admin.tables[name][-1]
    if corruption == "keys":
        index["Keys"] = [{"Name": "foreign", "Direction": "1"}]
    elif corruption == "unique":
        index["Unique"] = not index["Unique"]
    elif corruption == "sparse":
        index["Sparse"] = True
    elif corruption == "partial":
        index["PartialFilterExpression"] = "unexpected"
    elif corruption == "duplicate":
        admin.tables[name].append(deepcopy(index))
    elif corruption == "foreign":
        admin.tables[name].append({"Name": "foreign-index"})
    else:
        index["Status"] = "BUILDING"
    with pytest.raises(AdminError, match="INDEX_DEFINITION_MISMATCH|UNEXPECTED_COLLECTION_INDEX|INDEX_STATE_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


def test_owned_new_acl_mismatch_is_not_repaired(resources):
    admin, documents, manifest = resources
    seed_resources(admin, documents, manifest)
    admin.acls[manifest["collections"][0]["name"]] = "READONLY"
    with pytest.raises(AdminError, match="COLLECTION_ACL_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("field,value", [("owner", "concurrent-owner"), ("reservation_id", "replace")])
def test_marker_competition_blocks_compare_and_swap_promotion(resources, field, value):
    admin, documents, manifest = resources

    def mutate():
        documents.records[community.COMMUNITY_MARKER_ID][field] = value

    documents.before_promotion = mutate
    with pytest.raises(AdminError, match="COMMUNITY_MARKER_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == 0
    assert documents.records["phase04"]["version"] == 1
    assert documents.records["pc02-family-identity"]["version"] == 2


def test_marker_change_stops_further_resource_writes(resources):
    admin, documents, manifest = resources

    def mutate(action, body):
        documents.records[community.COMMUNITY_MARKER_ID]["owner"] = "concurrent-owner"

    admin.before_write = mutate
    with pytest.raises(AdminError, match="COMMUNITY_MARKER_CHANGED"):
        apply(admin, documents, manifest)
    assert len(admin.writes) == 1
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == 0


def test_dependency_change_prevents_readiness(resources):
    admin, documents, manifest = resources

    def mutate(action, body):
        documents.records["pc02-family-identity"]["checksum"] = "concurrent-change"

    admin.before_write = mutate
    with pytest.raises(AdminError, match="DEPENDENCY_SCHEMA_CHANGED"):
        apply(admin, documents, manifest)
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == 0
    assert not any(method == "PATCH" for method, _ in documents.writes)


@pytest.mark.parametrize("ack", [{}, {"insertedIds": []}, {"insertedIds": ["foreign"]}])
def test_unconfirmed_reservation_never_creates_resources(resources, ack):
    admin, documents, manifest = resources
    documents.post_ack = ack
    with pytest.raises(AdminError, match="COMMUNITY_MARKER_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert admin.writes == [] and documents.records[community.COMMUNITY_MARKER_ID]["version"] == 0


@pytest.mark.parametrize("ack", [
    {}, {"matched": 1}, {"matched": True, "updated": 1}, {"matched": 1, "updated": True},
    {"matched": 0, "updated": 0}, {"matched": 1, "updated": 0}, {"matched": 2, "updated": 1},
])
def test_marker_ack_requires_strict_one_matched_and_updated(resources, ack):
    admin, documents, manifest = resources
    documents.patch_ack = ack
    with pytest.raises(AdminError, match="COMMUNITY_MARKER_NOT_VERIFIED"):
        apply(admin, documents, manifest)
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == 0


@pytest.mark.parametrize("lost_at", ["POST", "PATCH"])
def test_confirmation_lost_after_atomic_commit_is_not_reported_as_pass(resources, lost_at):
    admin, documents, manifest = resources

    def lost_confirmation(request):
        response = documents(request)
        if request.method == lost_at:
            raise httpx.ReadTimeout("synthetic response may contain a credential", request=request)
        return response

    with httpx.Client(transport=httpx.MockTransport(lost_confirmation)) as client:
        with pytest.raises(AdminError, match="^SCHEMA_DATA_UNAVAILABLE$"):
            community.CommunitySchemaProvisioner(admin, client, KEY).provision(
                manifest, cloud_write_authorized=True,
            )
    # A lost promotion acknowledgment cannot prove no write; the tool fails
    # rather than pretending either success or an unchanged version0 marker.
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == (0 if lost_at == "POST" else 3)
    if lost_at == "POST":
        assert admin.writes == []
    previous_writes = deepcopy((admin.writes, documents.writes))
    recovered = apply(admin, documents, manifest)
    assert recovered["status"] == "pass"
    if lost_at == "PATCH":
        assert (admin.writes, documents.writes) == previous_writes


def test_competing_reservation_conflict_is_not_adopted(resources):
    admin, documents, manifest = resources

    def competing_reservation(request):
        if request.method == "POST":
            documents.seed()
            documents.records[community.COMMUNITY_MARKER_ID]["owner"] = "competing-owner"
        return documents(request)

    with httpx.Client(transport=httpx.MockTransport(competing_reservation)) as client:
        with pytest.raises(AdminError, match="SCHEMA_DATA_REJECTED"):
            community.CommunitySchemaProvisioner(admin, client, KEY).provision(
                manifest, cloud_write_authorized=True,
            )
    assert admin.writes == []
    assert documents.records[community.COMMUNITY_MARKER_ID]["owner"] == "competing-owner"
    assert documents.records[community.COMMUNITY_MARKER_ID]["version"] == 0


def test_authorization_is_checked_before_any_network(resources):
    admin, documents, manifest = resources
    with pytest.raises(AdminError, match="CLOUD_WRITE_AUTHORIZATION_REQUIRED"):
        apply(admin, documents, manifest, authorized=False)
    assert admin.preflights == 0
    assert admin.environment_reads == 0
    assert_no_writes(admin, documents)


@pytest.mark.parametrize("args", [[], ["--plan"], ["--cloud-write-authorized"]])
def test_plan_never_reads_credentials_or_invokes_cloud(monkeypatch, capsys, args):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline plan cannot read private environment or invoke network/CLI")

    monkeypatch.setattr(community, "CloudAdmin", forbidden)
    monkeypatch.setattr(cloud_admin, "load_private_environment", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    community.main(args)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "plan"
    assert result["new_collections"] == 5 and result["new_indexes"] == 14
    assert result["paid_upgrade"] is False and result["backfill"] is False
    assert result["legacy_writes"] == result["role_grants"] == result["destructive_operations"] == []
    assert KEY not in json.dumps(result)


def test_apply_cli_requires_second_explicit_gate_before_secret_access(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized apply cannot access private environment")

    monkeypatch.setattr(community, "CloudAdmin", forbidden)
    monkeypatch.setattr(cloud_admin, "load_private_environment", forbidden)
    with pytest.raises(AdminError, match="CLOUD_WRITE_AUTHORIZATION_REQUIRED"):
        community.main(["--apply"])


def test_plan_and_apply_cannot_be_combined():
    with pytest.raises(SystemExit) as error:
        community.main(["--plan", "--apply", "--cloud-write-authorized"])
    assert error.value.code == 2
