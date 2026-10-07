"""Additive, owner-marked Phase04 schema provisioning; no destructive operation."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

import httpx

from cloud_admin import AdminError, CloudAdmin, ENV_ID, PRIVATE_ENV, ROOT, load_private_environment


MANIFEST = ROOT / "cloud/schema/001_metadata.json"


def decode_numbers(value):
    if isinstance(value, dict):
        if len(value) == 1 and next(iter(value)) in {"$numberInt", "$numberLong"}:
            return int(next(iter(value.values())))
        return {key: decode_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_numbers(item) for item in value]
    return value


def verify_index(actual: dict, expected: dict):
    keys = [[item.get("Name"), item.get("Direction")] for item in actual.get("Keys", [])]
    if keys != expected["keys"] or actual.get("Unique") is not expected["unique"]:
        raise AdminError("INDEX_DEFINITION_MISMATCH")


def load_manifest(path: Path = MANIFEST) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["env_id"] != ENV_ID or data["version"] != 1 or data["acl"] != "ADMINONLY":
        raise AdminError("SCHEMA_TARGET_INVALID")
    names = [item["name"] for item in data["collections"]]
    if len(names) != len(set(names)) or any(not re.fullmatch(r"sc_v2_[a-z_]+", name) for name in names):
        raise AdminError("SCHEMA_COLLECTION_INVALID")
    data["checksum"] = sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return data


class SchemaProvisioner:
    def __init__(self, admin, client, api_key: str):
        self.admin, self.client, self._api_key = admin, client, api_key
        self.base = f"https://{ENV_ID}.api.tcloudbasegateway.com/v1/database/instances/(default)/databases/(default)"

    def data_request(self, method: str, path: str, body: dict | None = None):
        try:
            response = self.client.request(method, f"{self.base}/{path}", json=body,
                                           headers={"Authorization": f"Bearer {self._api_key}"}, timeout=10)
        except httpx.HTTPError:
            raise AdminError("SCHEMA_DATA_UNAVAILABLE") from None
        if response.status_code == 404 and method == "GET":
            return None
        if response.status_code not in (200, 201):
            raise AdminError("SCHEMA_DATA_REJECTED")
        try:
            return decode_numbers(response.json())
        except ValueError:
            raise AdminError("SCHEMA_DATA_INVALID") from None

    def provision(self, manifest: dict) -> dict:
        audit = self.admin.preflight()
        connector = {"DatabaseName": audit["database_id"], "InstanceId": "flexdb"}
        def body(name):
            return {"EnvId": ENV_ID, "MongoConnector": connector, "TableName": name}
        listing = self.admin.api("ListTables", {"EnvId": ENV_ID, "MongoConnector": connector, "MgoLimit": 100, "MgoOffset": 0})
        if len(listing.get("Tables", [])) >= 100 or listing.get("Pager", {}).get("TotalPager", 0) > 1:
            raise AdminError("COLLECTION_AUDIT_INCOMPLETE")
        existing = {table["TableName"] for table in listing.get("Tables", [])}
        names = {item["name"] for item in manifest["collections"]}
        marker_path = "collections/sc_v2_app_schema/documents/phase04"
        marker = self.data_request("GET", marker_path) if "sc_v2_app_schema" in existing else None
        if existing & names:
            if not isinstance(marker, dict) or marker.get("owner") != manifest["owner"] or marker.get("checksum") != manifest["checksum"]:
                raise AdminError("EXISTING_SCHEMA_NOT_OWNED")
            if type(marker.get("version")) is not int or marker["version"] not in {0, 1}:
                raise AdminError("SCHEMA_MARKER_VERSION_UNSUPPORTED")
        created, indexes = [], []
        # Reserve ownership before additional collections. An interrupted run can
        # resume only through this exact owner/checksum, and version0 isn't ready.
        if marker is None:
            self.admin.api("CreateTable", {**body("sc_v2_app_schema"), "PermissionInfo": {"AclTag": "ADMINONLY", "EnvId": ENV_ID}}, write=True)
            existing.add("sc_v2_app_schema")
            created.append("sc_v2_app_schema")
            self.admin.api("ModifyDatabaseACL", {"EnvId": ENV_ID, "CollectionName": "sc_v2_app_schema", "AclTag": "ADMINONLY"}, write=True)
            self.data_request("POST", "collections/sc_v2_app_schema/documents", {"data": [{"_id": "phase04", "owner": manifest["owner"], "checksum": manifest["checksum"], "version": 0}]})
        for collection in manifest["collections"]:
            name = collection["name"]
            if name not in existing:
                self.admin.api("CreateTable", {**body(name), "PermissionInfo": {"AclTag": "ADMINONLY", "EnvId": ENV_ID}}, write=True)
                created.append(name)
            self.admin.api("ModifyDatabaseACL", {"EnvId": ENV_ID, "CollectionName": name, "AclTag": "ADMINONLY"}, write=True)
            acl = self.admin.api("DescribeDatabaseACL", {"EnvId": ENV_ID, "CollectionName": name})
            if acl.get("AclTag") != "ADMINONLY":
                raise AdminError("COLLECTION_ACL_NOT_VERIFIED")
            description = self.admin.api("DescribeTable", body(name))
            present = {item["Name"]: item for item in description.get("Indexes", [])}
            for index in collection["indexes"]:
                if index["name"] in present:
                    verify_index(present[index["name"]], index)
                    continue
                key_schema = {"MgoIndexKeys": [{"Name": field, "Direction": direction} for field, direction in index["keys"]], "MgoIsUnique": index["unique"]}
                self.admin.api("UpdateTable", {**body(name), "CreateIndexes": [{"IndexName": index["name"], "MgoKeySchema": key_schema}]}, write=True)
                indexes.append(f"{name}/{index['name']}")
            verified = self.admin.api("DescribeTable", body(name))
            verified_names = {item["Name"]: item for item in verified.get("Indexes", [])}
            if any(index["name"] not in verified_names for index in collection["indexes"]):
                raise AdminError("INDEX_BUILD_NOT_VERIFIED")
            for index in collection["indexes"]:
                verify_index(verified_names[index["name"]], index)
        result = self.data_request("PATCH", marker_path, {"data": {"$set": {"version": 1}}, "upsert": False, "replaceMode": False})
        if result.get("matched") != 1 or self.data_request("GET", marker_path).get("version") != 1:
            raise AdminError("SCHEMA_MARKER_NOT_VERIFIED")
        return {"status": "pass", **audit, "schema_version": 1, "collections_created": created, "indexes_created": indexes, "collections_verified": sorted(names), "client_acl": "ADMINONLY"}


def create_server_key(admin: CloudAdmin):
    admin.preflight()
    if PRIVATE_ENV.exists():
        raise AdminError("LOCAL_SECRET_FILE_ALREADY_EXISTS")
    data = admin.api("CreateApiKey", {"EnvId": ENV_ID, "KeyType": "api_key", "KeyName": "SoulCompanion-Phase04-Server", "ExpireIn": 2592000}, write=True)
    key = data.get("ApiKey")
    if not isinstance(key, str) or not key or any(char in key for char in "\r\n"):
        raise AdminError("API_KEY_RESPONSE_INVALID")
    PRIVATE_ENV.parent.mkdir(parents=True, exist_ok=True)
    # Server key is held only in an ignored local file and managed function env.
    with PRIVATE_ENV.open("x", encoding="utf-8") as handle:
        handle.write(f"CLOUDBASE_ENV_ID={ENV_ID}\nCLOUDBASE_APIKEY={key}\nCLOUD_ALLOWED_ORIGINS=http://127.0.0.1:18404\n")
    PRIVATE_ENV.chmod(0o600)
    return {"status": "created", "server_key_stored": "ignored local environment file", "expires_in_seconds": 2592000}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--create-server-key", action="store_true")
    args = parser.parse_args()
    manifest = load_manifest()
    admin = CloudAdmin()
    if not args.apply:
        print(json.dumps({"status": "plan", "env_id": ENV_ID, "version": 1, "collections": [item["name"] for item in manifest["collections"]], "client_acl": "ADMINONLY", "destructive_operations": []}))
        return
    if args.create_server_key:
        print(json.dumps(create_server_key(admin)))
        return
    key = load_private_environment().get("CLOUDBASE_APIKEY")
    if not key:
        raise AdminError("SERVER_API_KEY_REQUIRED")
    with httpx.Client(follow_redirects=False, trust_env=False) as client:
        result = SchemaProvisioner(admin, client, key).provision(manifest)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except AdminError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        raise SystemExit(1) from None
    except (KeyError, ValueError, OSError):
        # All credential-bearing responses and traceback contexts stay private.
        print(json.dumps({"status": "blocked", "code": "SCHEMA_PROVISIONING_FAILED"}))
        raise SystemExit(1) from None
