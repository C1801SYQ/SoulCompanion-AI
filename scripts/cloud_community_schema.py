"""Offline PC03 plan and explicitly authorized additive community schema apply.

Only five new ADMINONLY collections, fourteen indexes and the independent PC03
marker may be written. Existing schemas, identities and business data are read
and verified, never altered. PC02 authorization does not authorize this tool.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import UUID, uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION
from cloud_community_target import DATABASE_ID, verify_target
from cloud_schema import SchemaProvisioner, verify_index
from cloud.api.soulcompanion_cloud.community.schema import (
    COMMUNITY_BASE_MARKERS,
    COMMUNITY_COLLECTIONS,
    COMMUNITY_MARKER_ID,
    COMMUNITY_SCHEMA_CHECKSUM,
    COMMUNITY_SCHEMA_OWNER,
    COMMUNITY_SCHEMA_VERSION,
    SCHEMA_COLLECTION,
)


MANIFEST = ROOT / "cloud/schema/003_parent_community.json"
BASE_MANIFEST = ROOT / "cloud/schema/001_metadata.json"
FAMILY_MANIFEST = ROOT / "cloud/schema/002_family_identity.json"
SYSTEM_INDEX_NAMES = {"_id_", "_openid_1"}
UNVERIFIED_STATE_FIELDS = {"Status", "IndexStatus", "BuildState", "BuildStatus"}


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


def dependency_manifests(base_path: Path, family_path: Path) -> tuple[dict, dict]:
    documents = (read_json(base_path), read_json(family_path))
    for document, (marker_id, owner, checksum, version) in zip(documents, COMMUNITY_BASE_MARKERS, strict=True):
        if canonical_checksum(document) != checksum:
            raise AdminError("DEPENDENCY_MANIFEST_CHECKSUM_MISMATCH")
        if (
            document.get("marker_id") != marker_id or document.get("owner") != owner
            or type(document.get("version")) is not int or document["version"] != version
            or document.get("env_id") != ENV_ID or document.get("region") != REGION
            or document.get("acl") != "ADMINONLY"
        ):
            raise AdminError("DEPENDENCY_SCHEMA_TARGET_INVALID")
    return documents


def validate_manifest(
    data: dict, *, base_path: Path = BASE_MANIFEST, family_path: Path = FAMILY_MANIFEST,
) -> dict:
    if not isinstance(data, dict):
        raise AdminError("SCHEMA_MANIFEST_INVALID")
    manifest = deepcopy(data)
    supplied = manifest.pop("checksum", COMMUNITY_SCHEMA_CHECKSUM)
    checksum = canonical_checksum(manifest)
    if checksum != COMMUNITY_SCHEMA_CHECKSUM or supplied != checksum:
        raise AdminError("COMMUNITY_MANIFEST_CHECKSUM_MISMATCH")
    dependency_manifests(base_path, family_path)
    expected_dependencies = [
        {"marker_id": marker_id, "owner": owner, "checksum": fingerprint, "version": version}
        for marker_id, owner, fingerprint, version in COMMUNITY_BASE_MARKERS
    ]
    collections = manifest.get("collections")
    if (
        manifest.get("env_id") != ENV_ID or manifest.get("region") != REGION
        or type(manifest.get("version")) is not int or manifest["version"] != COMMUNITY_SCHEMA_VERSION
        or manifest.get("owner") != COMMUNITY_SCHEMA_OWNER
        or manifest.get("marker_id") != COMMUNITY_MARKER_ID or manifest.get("acl") != "ADMINONLY"
        or manifest.get("base_schemas") != expected_dependencies
        or not isinstance(collections, list) or len(collections) != 5
        or {item["name"] for item in collections} != set(COMMUNITY_COLLECTIONS.values())
        or sum(len(item["indexes"]) for item in collections) != 14
    ):
        raise AdminError("COMMUNITY_SCHEMA_TARGET_INVALID")
    manifest["checksum"] = checksum
    return manifest


def load_manifest(
    path: Path = MANIFEST, *, base_path: Path = BASE_MANIFEST, family_path: Path = FAMILY_MANIFEST,
) -> dict:
    return validate_manifest(read_json(path), base_path=base_path, family_path=family_path)


def plan(manifest: dict) -> dict:
    manifest = validate_manifest(manifest)
    return {
        "status": "plan", "env_id": ENV_ID, "region": REGION, "version": COMMUNITY_SCHEMA_VERSION,
        "database_id": DATABASE_ID,
        "checksum": manifest["checksum"], "base_schemas": manifest["base_schemas"],
        "collections": [item["name"] for item in manifest["collections"]],
        "indexes": [f"{item['name']}/{index['name']}" for item in manifest["collections"] for index in item["indexes"]],
        "new_collections": 5, "new_indexes": 14, "marker_id": COMMUNITY_MARKER_ID,
        "client_acl": "ADMINONLY", "backfill": False, "paid_upgrade": False,
        "destructive_operations": [], "legacy_writes": [], "role_grants": [],
        "cost_boundary": "Existing trial database; index/storage/read/write costs apply. No free-forever claim.",
        "billing_required": {"package_id": "baas_trial", "overrun": False, "auto_renew": False},
        "rollback": "Disable community capability and restore verified prior API; retain new data, indexes and marker.",
        "authorization_required": "Independent PC03 approval, then --apply --cloud-write-authorized",
    }


def verify_marker(
    marker: object, *, marker_id: str, owner: str, checksum: str, versions: set[int], error: str,
) -> None:
    if (
        not isinstance(marker, dict) or marker.get("_id") != marker_id or marker.get("owner") != owner
        or marker.get("checksum") != checksum or type(marker.get("version")) is not int
        or marker["version"] not in versions
    ):
        raise AdminError(error)
    if marker_id == COMMUNITY_MARKER_ID:
        reservation = marker.get("reservation_id")
        try:
            valid = isinstance(reservation, str) and str(UUID(reservation)) == reservation
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            raise AdminError("COMMUNITY_RESERVATION_NOT_VERIFIED")


class CommunitySchemaProvisioner(SchemaProvisioner):
    """Use the established transport without invoking legacy provisioning writes."""

    def __init__(self, admin: CloudAdmin, client: httpx.Client, api_key: str) -> None:
        super().__init__(admin, client, api_key)

    def _indexes(self, collection: dict, connector: dict, *, allow_missing: bool) -> set[str]:
        name = collection["name"]
        acl = self.admin.api("DescribeDatabaseACL", {"EnvId": ENV_ID, "CollectionName": name})
        if acl.get("AclTag") != "ADMINONLY":
            raise AdminError("COLLECTION_ACL_NOT_VERIFIED")
        description = self.admin.api("DescribeTable", {
            "EnvId": ENV_ID, "MongoConnector": connector, "TableName": name,
        })
        indexes = description.get("Indexes")
        if (
            not isinstance(indexes, list)
            or any(not isinstance(index, dict) or not isinstance(index.get("Name"), str) for index in indexes)
            or ("IndexNum" in description and (
                type(description["IndexNum"]) is not int or description["IndexNum"] != len(indexes)
            ))
        ):
            raise AdminError("INDEX_BUILD_NOT_VERIFIED")
        present = {index["Name"]: index for index in indexes}
        expected = {index["name"]: index for index in collection["indexes"]}
        if len(present) != len(indexes) or set(present) - SYSTEM_INDEX_NAMES - set(expected):
            raise AdminError("UNEXPECTED_COLLECTION_INDEX")
        for index in indexes:
            # Actual DescribeTable has no build-state field. Never invent a
            # ready status; unknown added state fields need protocol review.
            if UNVERIFIED_STATE_FIELDS & index.keys():
                raise AdminError("INDEX_STATE_NOT_VERIFIED")
        for index_name in set(present) & set(expected):
            actual = present[index_name]
            if (
                not isinstance(actual.get("Keys"), list)
                or any(not isinstance(key, dict) for key in actual["Keys"])
                or ("Sparse" in actual and actual["Sparse"] is not False)
                or ("PartialFilterExpression" in actual and actual["PartialFilterExpression"] != "")
            ):
                raise AdminError("INDEX_DEFINITION_MISMATCH")
            verify_index(actual, expected[index_name])
        missing = set(expected) - set(present)
        if missing and not allow_missing:
            raise AdminError("INDEX_BUILD_NOT_VERIFIED")
        return missing

    def _marker_matches(self, path: str, expected: dict) -> None:
        if self.data_request("GET", path) != expected:
            raise AdminError("COMMUNITY_MARKER_CHANGED")

    def provision(self, manifest: dict, *, cloud_write_authorized: bool = False) -> dict:
        if cloud_write_authorized is not True:
            raise AdminError("CLOUD_WRITE_AUTHORIZATION_REQUIRED")
        manifest = validate_manifest(manifest)
        audit = verify_target(
            self.admin.preflight,
            lambda: self.admin.api("DescribeEnvInfo", {"EnvId": ENV_ID}),
            error="COMMUNITY_PREFLIGHT_NOT_VERIFIED",
        )
        connector = {"DatabaseName": audit["database_id"], "InstanceId": "flexdb"}
        listing = self.admin.api("ListTables", {
            "EnvId": ENV_ID, "MongoConnector": connector, "MgoLimit": 100, "MgoOffset": 0,
        })
        tables, pager = listing.get("Tables"), listing.get("Pager")
        if (
            not isinstance(tables, list) or len(tables) >= 100 or not isinstance(pager, dict)
            or type(pager.get("Limit")) is not int or pager["Limit"] != 100
            or type(pager.get("Offset")) is not int or pager["Offset"] != 0
            or type(pager.get("Total")) is not int or pager["Total"] != len(tables)
            or any(not isinstance(table, dict) or not isinstance(table.get("TableName"), str) for table in tables)
        ):
            raise AdminError("COLLECTION_AUDIT_INCOMPLETE")
        existing = {table["TableName"] for table in tables}
        if len(existing) != len(tables):
            raise AdminError("COLLECTION_AUDIT_INCOMPLETE")
        legacy = [
            collection for dependency in dependency_manifests(BASE_MANIFEST, FAMILY_MANIFEST)
            for collection in dependency["collections"]
        ]
        if not {item["name"] for item in legacy} <= existing:
            raise AdminError("DEPENDENCY_SCHEMA_NOT_READY")
        # All legacy ACLs and index definitions, not only their markers, must
        # match before reserving ownership or creating any additive resource.
        for collection in legacy:
            self._indexes(collection, connector, allow_missing=False)
        base_snapshots = {}
        for marker_id, owner, checksum, version in COMMUNITY_BASE_MARKERS:
            path = f"collections/{SCHEMA_COLLECTION}/documents/{marker_id}"
            marker = self.data_request("GET", path)
            verify_marker(marker, marker_id=marker_id, owner=owner, checksum=checksum,
                          versions={version}, error="DEPENDENCY_SCHEMA_NOT_READY")
            base_snapshots[path] = deepcopy(marker)

        marker_path = f"collections/{SCHEMA_COLLECTION}/documents/{COMMUNITY_MARKER_ID}"
        marker = self.data_request("GET", marker_path)
        new_names = set(COMMUNITY_COLLECTIONS.values())
        if marker is not None:
            verify_marker(marker, marker_id=COMMUNITY_MARKER_ID, owner=COMMUNITY_SCHEMA_OWNER,
                          checksum=COMMUNITY_SCHEMA_CHECKSUM, versions={0, COMMUNITY_SCHEMA_VERSION},
                          error="COMMUNITY_SCHEMA_NOT_OWNED")
        elif existing & new_names:
            raise AdminError("COMMUNITY_SCHEMA_NOT_OWNED")
        completed = marker is not None and marker["version"] == COMMUNITY_SCHEMA_VERSION
        if completed and not new_names <= existing:
            raise AdminError("READY_COMMUNITY_SCHEMA_INCOMPLETE")
        missing_indexes = {}
        for collection in manifest["collections"]:
            if collection["name"] in existing:
                missing = self._indexes(collection, connector, allow_missing=True)
                if completed and missing:
                    raise AdminError("READY_COMMUNITY_SCHEMA_INCOMPLETE")
                missing_indexes[collection["name"]] = missing

        created, indexes_created = [], []
        if marker is None:
            # A unique reservation also binds promotion to this exact pending
            # marker; an independently replaced same-owner marker is refused.
            reservation = {
                "_id": COMMUNITY_MARKER_ID, "owner": COMMUNITY_SCHEMA_OWNER,
                "checksum": COMMUNITY_SCHEMA_CHECKSUM, "version": 0,
                "reservation_id": str(uuid4()),
            }
            acknowledgement = self.data_request("POST", f"collections/{SCHEMA_COLLECTION}/documents", {
                "data": [reservation],
            })
            if not isinstance(acknowledgement, dict) or acknowledgement.get("insertedIds") != [COMMUNITY_MARKER_ID]:
                raise AdminError("COMMUNITY_MARKER_NOT_VERIFIED")
            self._marker_matches(marker_path, reservation)
            marker = reservation
        for collection in manifest["collections"]:
            name = collection["name"]
            body = {"EnvId": ENV_ID, "MongoConnector": connector, "TableName": name}
            if name not in existing:
                self._marker_matches(marker_path, marker)
                self.admin.api("CreateTable", {
                    **body, "PermissionInfo": {"AclTag": "ADMINONLY", "EnvId": ENV_ID},
                }, write=True)
                created.append(name)
                missing_indexes[name] = self._indexes(collection, connector, allow_missing=True)
            missing = missing_indexes[name]
            if missing:
                self._marker_matches(marker_path, marker)
                index_definitions = []
                for index in collection["indexes"]:
                    if index["name"] not in missing:
                        continue
                    index_definitions.append({
                        "IndexName": index["name"],
                        "MgoKeySchema": {
                            "MgoIndexKeys": [{"Name": field, "Direction": direction} for field, direction in index["keys"]],
                            "MgoIsUnique": index["unique"],
                        },
                    })
                self.admin.api("UpdateTable", {**body, "CreateIndexes": index_definitions}, write=True)
                indexes_created.extend(f"{name}/{index['IndexName']}" for index in index_definitions)
            self._indexes(collection, connector, allow_missing=False)
        # Read back every resource/dependency before readiness; failures leave
        # version0 and cannot modify the original 001/002 markers or records.
        for collection in [*legacy, *manifest["collections"]]:
            self._indexes(collection, connector, allow_missing=False)
        for path, snapshot in base_snapshots.items():
            if self.data_request("GET", path) != snapshot:
                raise AdminError("DEPENDENCY_SCHEMA_CHANGED")
        self._marker_matches(marker_path, marker)
        if not completed:
            acknowledgement = self.data_request("PATCH", f"collections/{SCHEMA_COLLECTION}/documents", {
                "query": {
                    "_id": COMMUNITY_MARKER_ID, "owner": COMMUNITY_SCHEMA_OWNER,
                    "checksum": COMMUNITY_SCHEMA_CHECKSUM, "version": 0,
                    "reservation_id": marker["reservation_id"],
                },
                "data": {"$set": {"version": COMMUNITY_SCHEMA_VERSION}},
                "multi": False, "upsert": False, "replaceMode": False,
            })
            if (
                not isinstance(acknowledgement, dict)
                or type(acknowledgement.get("matched")) is not int or acknowledgement["matched"] != 1
                or type(acknowledgement.get("updated")) is not int or acknowledgement["updated"] != 1
            ):
                raise AdminError("COMMUNITY_MARKER_NOT_VERIFIED")
            promoted = {**marker, "version": COMMUNITY_SCHEMA_VERSION}
            self._marker_matches(marker_path, promoted)
        return {
            "status": "pass", "env_id": ENV_ID, "region": REGION,
            "database_id": audit["database_id"], "package_id": "baas_trial",
            "overrun": False, "auto_renew": False, "schema_version": COMMUNITY_SCHEMA_VERSION,
            "collections_created": created, "indexes_created": indexes_created,
            "collections_verified": [item["name"] for item in manifest["collections"]],
            "client_acl": "ADMINONLY", "backfill": False, "legacy_writes": [],
            "index_evidence": "Read-back definitions; DescribeTable exposes no independent build-state field.",
        }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Print offline bounded plan (default).")
    mode.add_argument("--apply", action="store_true", help="Apply only after independent PC03 approval.")
    parser.add_argument("--cloud-write-authorized", action="store_true", help="Confirm explicit PC03 approval.")
    args = parser.parse_args(argv)
    if args.apply and not args.cloud_write_authorized:
        raise AdminError("CLOUD_WRITE_AUTHORIZATION_REQUIRED")
    manifest = load_manifest()
    if not args.apply:
        print(json.dumps(plan(manifest), sort_keys=True))
        return
    # Secrets are loaded only after both gates; never placed in a command,
    # printed plan, result, public request body or exception context.
    from cloud_admin import load_private_environment

    key = load_private_environment().get("CLOUDBASE_APIKEY")
    if not key:
        raise AdminError("SERVER_API_KEY_REQUIRED")
    with httpx.Client(follow_redirects=False, trust_env=False) as client:
        result = CommunitySchemaProvisioner(CloudAdmin(), client, key).provision(
            manifest, cloud_write_authorized=True,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except AdminError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        raise SystemExit(1) from None
    except (KeyError, ValueError, TypeError, AttributeError, OSError):
        print(json.dumps({"status": "blocked", "code": "COMMUNITY_SCHEMA_PROVISIONING_FAILED"}))
        raise SystemExit(1) from None
