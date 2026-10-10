"""Offline PC02 plan and explicitly authorized, additive family schema apply.

Only the new parent collection/index and its separate marker may be written.
Phase04 resources, documents and the original marker are never modified.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import get_args

import httpx

# Existing Phase04 tools use direct sibling imports. Support both script execution
# and package/test imports without importing or reading any private configuration.
ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION
from cloud_schema import SchemaProvisioner, verify_index
from cloud.api.soulcompanion_cloud.family_identity import (
    ChildAgeBand,
    FAMILY_MARKER_ID,
    FAMILY_SCHEMA_CHECKSUM,
    FAMILY_SCHEMA_OWNER,
    FAMILY_SCHEMA_VERSION,
    PHASE04_SCHEMA_CHECKSUM,
)


MANIFEST = ROOT / "cloud/schema/002_family_identity.json"
BASE_MANIFEST = ROOT / "cloud/schema/001_metadata.json"
SCHEMA_COLLECTION = "sc_v2_app_schema"
PARENT_COLLECTION = "sc_v2_parent_profiles"
OWNER_INDEX = {"name": "pc02_parent_owner_unique", "unique": True, "keys": [["owner_user_id", "1"]]}
SYSTEM_INDEX_NAMES = {"_id_", "_openid_1"}


def canonical_checksum(data: dict) -> str:
    return sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AdminError("SCHEMA_MANIFEST_INVALID") from None
    if not isinstance(data, dict):
        raise AdminError("SCHEMA_MANIFEST_INVALID")
    return data


def validate_manifest(data: dict, *, base_path: Path = BASE_MANIFEST) -> dict:
    if not isinstance(data, dict):
        raise AdminError("SCHEMA_MANIFEST_INVALID")
    manifest = deepcopy(data)
    provided_checksum = manifest.pop("checksum", FAMILY_SCHEMA_CHECKSUM)
    checksum = canonical_checksum(manifest)
    if checksum != FAMILY_SCHEMA_CHECKSUM or provided_checksum != checksum:
        raise AdminError("FAMILY_MANIFEST_CHECKSUM_MISMATCH")
    base = read_json(base_path)
    if canonical_checksum(base) != PHASE04_SCHEMA_CHECKSUM:
        raise AdminError("BASE_MANIFEST_CHECKSUM_MISMATCH")
    expected_base = {
        "marker_id": "phase04", "owner": "SoulCompanion-AI/phase04",
        "version": 1, "checksum": PHASE04_SCHEMA_CHECKSUM,
    }
    extension = {
        "collection": "sc_v2_child_profiles", "field": "age_band", "optional": True,
        "nullable": True, "values": list(get_args(ChildAgeBand)), "backfill": False, "indexes": [],
    }
    collections = manifest.get("collections")
    if (
        manifest.get("env_id") != ENV_ID
        or manifest.get("region") != REGION
        or type(manifest.get("version")) is not int
        or manifest["version"] != FAMILY_SCHEMA_VERSION
        or manifest.get("owner") != FAMILY_SCHEMA_OWNER
        or manifest.get("marker_id") != FAMILY_MARKER_ID
        or manifest.get("acl") != "ADMINONLY"
        or manifest.get("base_schema") != expected_base
        or manifest.get("child_profile_extension") != extension
        or not isinstance(collections, list)
        or len(collections) != 1
        or collections[0].get("name") != PARENT_COLLECTION
        or collections[0].get("indexes") != [OWNER_INDEX]
        or any(base.get(field) != expected_base[field] for field in ("marker_id", "owner", "version"))
        or base.get("env_id") != ENV_ID
        or base.get("region") != REGION
        or base.get("acl") != "ADMINONLY"
    ):
        raise AdminError("FAMILY_SCHEMA_TARGET_INVALID")
    manifest["checksum"] = checksum
    return manifest


def load_manifest(path: Path = MANIFEST, *, base_path: Path = BASE_MANIFEST) -> dict:
    return validate_manifest(read_json(path), base_path=base_path)


def plan(manifest: dict) -> dict:
    manifest = validate_manifest(manifest)
    return {
        "status": "plan", "env_id": ENV_ID, "region": REGION, "version": FAMILY_SCHEMA_VERSION,
        "checksum": manifest["checksum"], "base_checksum": PHASE04_SCHEMA_CHECKSUM,
        "collections": [PARENT_COLLECTION], "indexes": [f"{PARENT_COLLECTION}/{OWNER_INDEX['name']}"],
        "new_collections": 1, "new_indexes": 1, "marker_id": FAMILY_MARKER_ID,
        "client_acl": "ADMINONLY", "backfill": False, "paid_upgrade": False,
        "destructive_operations": [],
        "cost_boundary": "Existing trial environment only; overrun and auto-renew must remain disabled.",
        "rollback": "Restore the previous application; retain the new collection and marker. No automatic deletion.",
        "authorization_required": "--apply --cloud-write-authorized after approval of this bounded change",
    }


def verify_marker(marker: object, *, marker_id: str, owner: str, checksum: str, versions: set[int], error: str) -> None:
    if (
        not isinstance(marker, dict)
        or marker.get("_id") != marker_id
        or marker.get("owner") != owner
        or marker.get("checksum") != checksum
    ):
        raise AdminError(error)
    if type(marker.get("version")) is not int or marker["version"] not in versions:
        raise AdminError("FAMILY_MARKER_VERSION_UNSUPPORTED" if marker_id == FAMILY_MARKER_ID else error)


class FamilySchemaProvisioner(SchemaProvisioner):
    """Reuse the authenticated data transport, never the Phase04 write procedure."""

    def _parent_indexes(self, body: dict, *, allow_missing: bool) -> bool:
        acl = self.admin.api("DescribeDatabaseACL", {"EnvId": ENV_ID, "CollectionName": PARENT_COLLECTION})
        if acl.get("AclTag") != "ADMINONLY":
            raise AdminError("COLLECTION_ACL_NOT_VERIFIED")
        description = self.admin.api("DescribeTable", body)
        indexes = description.get("Indexes")
        if not isinstance(indexes, list) or any(not isinstance(index, dict) or not isinstance(index.get("Name"), str) for index in indexes):
            raise AdminError("INDEX_BUILD_NOT_VERIFIED")
        present = {index["Name"]: index for index in indexes}
        if len(present) != len(indexes) or set(present) - SYSTEM_INDEX_NAMES - {OWNER_INDEX["name"]}:
            raise AdminError("UNEXPECTED_PARENT_INDEX")
        if OWNER_INDEX["name"] in present:
            verify_index(present[OWNER_INDEX["name"]], OWNER_INDEX)
            return True
        if not allow_missing:
            raise AdminError("INDEX_BUILD_NOT_VERIFIED")
        return False

    def provision(self, manifest: dict, *, cloud_write_authorized: bool = False) -> dict:
        if cloud_write_authorized is not True:
            raise AdminError("CLOUD_WRITE_AUTHORIZATION_REQUIRED")
        manifest = validate_manifest(manifest)
        # A fresh check is mandatory on every apply, including a completed rerun.
        audit = self.admin.preflight()
        if (
            not isinstance(audit, dict)
            or audit.get("env_id") != ENV_ID
            or audit.get("region") != REGION
            or audit.get("package_id") != "baas_trial"
            or audit.get("overrun") is not False
            or audit.get("auto_renew") is not False
            or not isinstance(audit.get("database_id"), str)
            or not audit["database_id"]
        ):
            raise AdminError("FAMILY_PREFLIGHT_NOT_VERIFIED")
        connector = {"DatabaseName": audit["database_id"], "InstanceId": "flexdb"}
        parent_body = {"EnvId": ENV_ID, "MongoConnector": connector, "TableName": PARENT_COLLECTION}
        listing = self.admin.api("ListTables", {
            "EnvId": ENV_ID, "MongoConnector": connector, "MgoLimit": 100, "MgoOffset": 0,
        })
        tables = listing.get("Tables")
        pager = listing.get("Pager")
        if (
            not isinstance(tables, list) or len(tables) >= 100
            or not isinstance(pager, dict)
            or type(pager.get("Limit")) is not int or pager["Limit"] != 100
            or type(pager.get("Offset")) is not int or pager["Offset"] != 0
            or type(pager.get("Total")) is not int or pager["Total"] != len(tables)
            or any(not isinstance(table, dict) or not isinstance(table.get("TableName"), str) for table in tables)
        ):
            raise AdminError("COLLECTION_AUDIT_INCOMPLETE")
        existing = {table["TableName"] for table in tables}
        if len(existing) != len(tables):
            raise AdminError("COLLECTION_AUDIT_INCOMPLETE")
        base_names = {collection["name"] for collection in read_json(BASE_MANIFEST)["collections"]}
        if not base_names <= existing:
            raise AdminError("BASE_SCHEMA_NOT_READY")
        schema_acl = self.admin.api("DescribeDatabaseACL", {"EnvId": ENV_ID, "CollectionName": SCHEMA_COLLECTION})
        if schema_acl.get("AclTag") != "ADMINONLY":
            raise AdminError("BASE_SCHEMA_NOT_READY")
        base_path = f"collections/{SCHEMA_COLLECTION}/documents/phase04"
        marker_path = f"collections/{SCHEMA_COLLECTION}/documents/{FAMILY_MARKER_ID}"
        base_marker = self.data_request("GET", base_path)
        verify_marker(base_marker, marker_id="phase04", owner=manifest["base_schema"]["owner"],
                      checksum=PHASE04_SCHEMA_CHECKSUM, versions={1}, error="BASE_SCHEMA_NOT_READY")
        base_snapshot = deepcopy(base_marker)
        marker = self.data_request("GET", marker_path)
        if marker is not None:
            verify_marker(marker, marker_id=FAMILY_MARKER_ID, owner=FAMILY_SCHEMA_OWNER,
                          checksum=FAMILY_SCHEMA_CHECKSUM, versions={0, 2}, error="FAMILY_SCHEMA_NOT_OWNED")
        elif PARENT_COLLECTION in existing:
            raise AdminError("FAMILY_SCHEMA_NOT_OWNED")
        completed = marker is not None and marker["version"] == FAMILY_SCHEMA_VERSION
        if completed and PARENT_COLLECTION not in existing:
            raise AdminError("READY_FAMILY_SCHEMA_INCOMPLETE")
        index_present = False
        if PARENT_COLLECTION in existing:
            index_present = self._parent_indexes(parent_body, allow_missing=True)
            if completed and not index_present:
                raise AdminError("READY_FAMILY_SCHEMA_INCOMPLETE")

        created, indexes = [], []
        if marker is None:
            # Reserve the new document only. No existing Phase04 document is updated.
            reservation = {"_id": FAMILY_MARKER_ID, "owner": FAMILY_SCHEMA_OWNER,
                           "checksum": FAMILY_SCHEMA_CHECKSUM, "version": 0}
            acknowledgement = self.data_request("POST", f"collections/{SCHEMA_COLLECTION}/documents", {"data": [reservation]})
            if not isinstance(acknowledgement, dict) or acknowledgement.get("insertedIds") != [FAMILY_MARKER_ID]:
                raise AdminError("FAMILY_MARKER_NOT_VERIFIED")
            verify_marker(self.data_request("GET", marker_path), marker_id=FAMILY_MARKER_ID,
                          owner=FAMILY_SCHEMA_OWNER, checksum=FAMILY_SCHEMA_CHECKSUM,
                          versions={0}, error="FAMILY_MARKER_NOT_VERIFIED")
        if PARENT_COLLECTION not in existing:
            self.admin.api("CreateTable", {**parent_body, "PermissionInfo": {"AclTag": "ADMINONLY", "EnvId": ENV_ID}}, write=True)
            created.append(PARENT_COLLECTION)
            index_present = self._parent_indexes(parent_body, allow_missing=True)
        if not index_present:
            schema = {"MgoIndexKeys": [{"Name": name, "Direction": direction} for name, direction in OWNER_INDEX["keys"]],
                      "MgoIsUnique": OWNER_INDEX["unique"]}
            self.admin.api("UpdateTable", {**parent_body, "CreateIndexes": [{"IndexName": OWNER_INDEX["name"], "MgoKeySchema": schema}]}, write=True)
            indexes.append(f"{PARENT_COLLECTION}/{OWNER_INDEX['name']}")
        # Publish readiness only after all additive resources and the unchanged
        # Phase04 dependency have been read back. Failed builds retain version0.
        self._parent_indexes(parent_body, allow_missing=False)
        if self.data_request("GET", base_path) != base_snapshot:
            raise AdminError("BASE_SCHEMA_NOT_READY")
        verify_marker(self.data_request("GET", marker_path), marker_id=FAMILY_MARKER_ID,
                      owner=FAMILY_SCHEMA_OWNER, checksum=FAMILY_SCHEMA_CHECKSUM,
                      versions={FAMILY_SCHEMA_VERSION if completed else 0}, error="FAMILY_MARKER_NOT_VERIFIED")
        if not completed:
            acknowledgement = self.data_request("PATCH", f"collections/{SCHEMA_COLLECTION}/documents", {
                "query": {"_id": FAMILY_MARKER_ID, "owner": FAMILY_SCHEMA_OWNER,
                          "checksum": FAMILY_SCHEMA_CHECKSUM, "version": 0},
                "data": {"$set": {"version": FAMILY_SCHEMA_VERSION}},
                "multi": False, "upsert": False, "replaceMode": False,
            })
            if not isinstance(acknowledgement, dict) or type(acknowledgement.get("matched")) is not int or acknowledgement["matched"] != 1:
                raise AdminError("FAMILY_MARKER_NOT_VERIFIED")
            verify_marker(self.data_request("GET", marker_path), marker_id=FAMILY_MARKER_ID,
                          owner=FAMILY_SCHEMA_OWNER, checksum=FAMILY_SCHEMA_CHECKSUM,
                          versions={FAMILY_SCHEMA_VERSION}, error="FAMILY_MARKER_NOT_VERIFIED")
        return {
            "status": "pass", "env_id": ENV_ID, "region": REGION,
            "database_id": audit["database_id"], "package_id": "baas_trial",
            "overrun": False, "auto_renew": False, "schema_version": FAMILY_SCHEMA_VERSION,
            "collections_created": created, "indexes_created": indexes,
            "collections_verified": [PARENT_COLLECTION], "client_acl": "ADMINONLY", "backfill": False,
        }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Print the offline plan (default).")
    mode.add_argument("--apply", action="store_true", help="Apply only after explicit cloud-write authorization.")
    parser.add_argument("--cloud-write-authorized", action="store_true", help="Confirm approval of the bounded PC02 cloud change.")
    args = parser.parse_args(argv)
    if args.apply and not args.cloud_write_authorized:
        raise AdminError("CLOUD_WRITE_AUTHORIZATION_REQUIRED")
    manifest = load_manifest()
    if not args.apply:
        print(json.dumps(plan(manifest), sort_keys=True))
        return
    # The ignored secret is loaded internally only after both write gates. It is
    # never placed in a command, public CLI body, plan, result or error message.
    from cloud_admin import load_private_environment

    key = load_private_environment().get("CLOUDBASE_APIKEY")
    if not key:
        raise AdminError("SERVER_API_KEY_REQUIRED")
    with httpx.Client(follow_redirects=False, trust_env=False) as client:
        result = FamilySchemaProvisioner(CloudAdmin(), client, key).provision(manifest, cloud_write_authorized=True)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except AdminError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        raise SystemExit(1) from None
    except (KeyError, ValueError, TypeError, AttributeError, OSError):
        print(json.dumps({"status": "blocked", "code": "FAMILY_SCHEMA_PROVISIONING_FAILED"}))
        raise SystemExit(1) from None
