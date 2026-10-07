"""Provisioning refuses cost uncertainty, foreign resources and partial indexes."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cloud_admin import AdminError, CloudAdmin, ENV_ID, parse_response
from cloud_schema import SchemaProvisioner, load_manifest


class FakeAdmin:
    def __init__(self):
        self.tables = {}
        self.acls = {}
        self.writes = []
        self.reject_index = False

    def preflight(self):
        return {"env_id": ENV_ID, "database_id": "test-db", "package_id": "baas_trial"}

    def api(self, action, body, write=False):
        assert body["EnvId"] == ENV_ID
        if write:
            self.writes.append((action, deepcopy(body)))
        name = body.get("TableName", body.get("CollectionName"))
        if action == "ListTables":
            return {"Tables": [{"TableName": item} for item in self.tables], "Pager": {"TotalPager": 1}}
        if action == "CreateTable":
            assert body["PermissionInfo"]["AclTag"] == "ADMINONLY"
            self.tables[name] = []
        elif action == "ModifyDatabaseACL":
            self.acls[name] = body["AclTag"]
        elif action == "DescribeDatabaseACL":
            return {"AclTag": self.acls[name]}
        elif action == "DescribeTable":
            return {"Indexes": self.tables[name]}
        elif action == "UpdateTable" and not self.reject_index:
            for index in body["CreateIndexes"]:
                self.tables[name].append({"Name": index["IndexName"], "Keys": index["MgoKeySchema"]["MgoIndexKeys"], "Unique": index["MgoKeySchema"]["MgoIsUnique"]})
        return {}


def database_client(marker_box):
    def handler(request):
        assert request.headers["authorization"] == "Bearer synthetic-server-test-key"
        if request.method == "GET":
            if marker_box[0] is None:
                return httpx.Response(404)
            # The official API returns Strict EJSON for numeric metadata.
            doc = {**marker_box[0], "version": {"$numberInt": str(marker_box[0]["version"])}}
            return httpx.Response(200, json=doc)
        body = json.loads(request.content)
        if request.method == "POST":
            marker_box[0] = body["data"][0]
            return httpx.Response(201, json={"insertedIds": ["phase04"]})
        marker_box[0].update(body["data"]["$set"])
        return httpx.Response(200, json={"matched": 1, "updated": 1})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_additive_provision_and_rerun_preserve_data_and_indexes():
    admin, marker, manifest = FakeAdmin(), [None], load_manifest()
    admin.tables["owner_other_app"] = []
    with database_client(marker) as client:
        provisioner = SchemaProvisioner(admin, client, "synthetic-server-test-key")
        result = provisioner.provision(manifest)
        assert len(result["collections_created"]) == 7
        assert len(result["indexes_created"]) == 13
        assert marker[0]["version"] == 1
        before = deepcopy(admin.tables)
        assert provisioner.provision(manifest)["collections_created"] == []
        assert admin.tables == before
        assert "owner_other_app" not in admin.acls
        assert all(action not in {"DeleteTable", "DropIndex", "CreateEnv"} for action, _ in admin.writes)


def test_foreign_namespace_collision_refuses_all_writes():
    admin, marker = FakeAdmin(), [None]
    admin.tables["sc_v2_users"] = []
    with database_client(marker) as client:
        with pytest.raises(AdminError, match="EXISTING_SCHEMA_NOT_OWNED"):
            SchemaProvisioner(admin, client, "synthetic-server-test-key").provision(load_manifest())
    assert admin.writes == []


def test_partial_index_failure_does_not_publish_ready_marker():
    admin, marker = FakeAdmin(), [None]
    admin.reject_index = True
    with database_client(marker) as client:
        with pytest.raises(AdminError, match="INDEX_BUILD_NOT_VERIFIED"):
            SchemaProvisioner(admin, client, "synthetic-server-test-key").provision(load_manifest())
    assert marker[0]["version"] == 0


@pytest.mark.parametrize("version", [2, True, None, "1"])
def test_unknown_schema_version_refuses_all_writes(version):
    admin, manifest = FakeAdmin(), load_manifest()
    marker = [{"owner": manifest["owner"], "checksum": manifest["checksum"], "version": version}]
    admin.tables["sc_v2_app_schema"] = []
    before = deepcopy(marker)
    # Exercise domain values directly because EJSON numeric decoding deliberately
    # rejects representations that the database cannot produce.
    provisioner = SchemaProvisioner(admin, None, "synthetic-server-test-key")
    provisioner.data_request = lambda *args: marker[0]
    with pytest.raises(AdminError, match="SCHEMA_MARKER_VERSION_UNSUPPORTED"):
        provisioner.provision(manifest)
    assert admin.writes == [] and marker == before


def test_matching_index_name_with_wrong_keys_cannot_pass():
    admin, manifest = FakeAdmin(), load_manifest()
    marker = [{"owner": manifest["owner"], "checksum": manifest["checksum"], "version": 0}]
    admin.tables = {item["name"]: [] for item in manifest["collections"]}
    admin.tables["sc_v2_identities"] = [{"Name": "phase04_identity_unique", "Unique": False, "Keys": [{"Name": "wrong", "Direction": "1"}]}]
    with database_client(marker) as client:
        with pytest.raises(AdminError, match="INDEX_DEFINITION_MISMATCH"):
            SchemaProvisioner(admin, client, "synthetic-server-test-key").provision(manifest)
    assert marker[0]["version"] == 0


@pytest.mark.parametrize("field,value", [("PackageId", "baas_personal"), ("EnableOverrun", True), ("EnableOverrun", None), ("IsAutoRenew", True)])
def test_paid_or_unverified_preflight_refused(field, value):
    admin = CloudAdmin()
    bill = {"EnvId": ENV_ID, "PackageId": "baas_trial", "EnableOverrun": False, "IsAutoRenew": False}
    bill[field] = value
    admin.api = lambda action, body: {"EnvInfo": {"EnvBaseInfo": {"EnvId": ENV_ID, "Status": "NORMAL"}}} if action == "DescribeEnvInfo" else {"EnvBillingInfoList": [bill]}
    with pytest.raises(AdminError, match="PAID_RESOURCE_REQUIRED_OR_BILLING_UNVERIFIED"):
        admin.preflight()


def test_structured_error_does_not_include_private_upstream_message():
    with pytest.raises(AdminError) as error:
        parse_response(json.dumps({"data": {"Error": {"Code": "UnauthorizedOperation", "Message": "synthetic-private-material"}}}))
    assert str(error.value) == "UnauthorizedOperation"


def test_credentials_cannot_enter_cli_body_argument():
    with pytest.raises(AdminError, match="SECRET_ARGUMENT_FORBIDDEN"):
        CloudAdmin().api("CreateTable", {"EnvId": ENV_ID, "password": "synthetic-private-material"}, write=True)


def test_foreign_environment_is_rejected_before_cli():
    with pytest.raises(AdminError, match="WRONG_ENVIRONMENT"):
        CloudAdmin().api("DescribeEnvInfo", {"EnvId": "other-project"})
