"""Offline role plan; protected, audited PC03 moderator grant/revoke.

This server-key-only CLI has no equivalent HTTP endpoint. It cannot create
users, collections, indexes, authentication providers or paid resources.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION
from cloud_community_target import DATABASE_ID, TargetReader, verify_target
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError
from cloud.api.soulcompanion_cloud.repository import CloudBaseDocumentRepository
from cloud.api.soulcompanion_cloud.community.models import canonical_id, plain_text
from cloud.api.soulcompanion_cloud.community.repository import CommunityDocumentRepository, CommunityRepository
from cloud.api.soulcompanion_cloud.community.service import (
    deterministic_id, idempotency_key, normalized_hash, role_binding_id, utc_now, validate_role,
)


def plan() -> dict:
    return {"status": "plan", "env_id": ENV_ID, "region": REGION, "database_id": DATABASE_ID,
            "role": "moderator",
            "collection": "sc_v2_community_role_bindings", "new_resources": [], "paid_upgrade": False,
            "principal_source": "Existing active application-user UUID verified server-side; never OpenID or email.",
            "audit_actor": "cloud-admin-cli", "rollback": "Audited revoke; retain all role history.",
            "authorization_required": "PC03 approval, then --apply --cloud-write-authorized",
            "cloud_writes": False}


class RoleManager:
    def __init__(
        self, storage: CommunityRepository, user_lookup: Callable[[str], Awaitable[dict | None]],
        preflight: TargetReader, environment_info: TargetReader,
    ) -> None:
        self.storage, self.user_lookup, self.preflight = storage, user_lookup, preflight
        self.environment_info = environment_info

    async def change(self, principal: str, action: str, reason: str, key: str,
                     *, cloud_write_authorized: bool = False) -> dict:
        if cloud_write_authorized is not True:
            raise AdminError("PC03_CLOUD_WRITE_AUTHORIZATION_REQUIRED")
        try:
            principal = canonical_id(principal)
            reason = plain_text(reason, 200)
            key = idempotency_key(key)
        except (ValueError, TypeError, CloudError):
            raise AdminError("ROLE_INPUT_INVALID") from None
        if action not in {"grant", "revoke"}:
            raise AdminError("ROLE_INPUT_INVALID")
        verify_target(self.preflight, self.environment_info, error="ROLE_PREFLIGHT_NOT_VERIFIED")
        if await self.storage.ready() is not True:
            raise AdminError("COMMUNITY_SCHEMA_NOT_READY")
        if action == "grant":
            user = await self.user_lookup(principal)
            if not isinstance(user, dict) or user.get("_id") != principal or user.get("id") != principal or user.get("status") != "active":
                raise AdminError("ACTIVE_APPLICATION_USER_REQUIRED")
        identifier = role_binding_id(principal)
        current = await self.storage.get("role_bindings", identifier)
        payload = {"principal_id": principal, "action": action, "reason": reason}
        payload_hash = normalized_hash(payload)
        action_id = deterministic_id("role_action", principal, sha256(f"{action}:{key}".encode()).hexdigest())
        destination = "active" if action == "grant" else "revoked"
        if current is not None:
            validate_role(current)
            if current["principal_id"] != principal:
                raise AdminError("ROLE_RECORD_NOT_OWNED")
            replay = next((entry for entry in current["audit"] if entry["action_id"] == action_id), None)
            if replay is not None:
                if replay["payload_hash"] != payload_hash:
                    raise AdminError("ROLE_ACTION_INPUT_CONFLICT")
                return self.result(current, changed=False, action_applied=True)
            if current["status"] == destination:
                return self.result(current, changed=False, action_applied=False)
        elif action == "revoke":
            return {"status": "pass", "role_status": "absent", "changed": False, "action_applied": False}
        maximum = 31 if action == "grant" else 32
        if current is not None and len(current["audit"]) >= maximum:
            raise AdminError("ROLE_AUDIT_CAPACITY_EXCEEDED")
        at = utc_now(current["updated_at"] if current else None)
        prior = current["status"] if current else None
        version = current["row_version"] + 1 if current else 1
        event = {"action_id": action_id, "actor_id": "cloud-admin-cli", "action": action,
                 "target_revision": version, "from_status": prior, "to_status": destination,
                 "reason": reason, "at": at, "payload_hash": payload_hash}
        candidate = {**(deepcopy(current) if current else {}), "_id": identifier, "id": identifier,
                     "principal_id": principal, "role": "moderator", "status": destination,
                     "row_version": version, "created_at": current["created_at"] if current else at,
                     "updated_at": at, "audit": [*(current["audit"] if current else []), event]}
        if action == "grant":
            candidate.update(granted_at=at, granted_by="cloud-admin-cli")
        validate_role(candidate)
        if current is None:
            canonical, created = await self.storage.insert("role_bindings", candidate,
                {"_id": identifier, "id": identifier, "principal_id": principal, "role": "moderator"})
            validate_role(canonical)
            confirmed = next((entry for entry in canonical["audit"] if entry["action_id"] == action_id), None)
            if confirmed is None or confirmed["payload_hash"] != payload_hash:
                raise AdminError("ROLE_ACTION_CONFLICT")
            return self.result(canonical, changed=created, action_applied=True)
        expected = {field: current[field] for field in ("_id", "id", "principal_id", "role", "status", "row_version")}
        changes = {field: value for field, value in candidate.items() if field not in {"_id", "id", "principal_id", "role", "created_at"}}
        if await self.storage.cas("role_bindings", identifier, expected, changes) is not True:
            raise AdminError("ROLE_ACTION_CONFLICT")
        # Confirm the immutable action, while reporting the current state if a
        # later authorized action already changed the role.
        canonical = await self.storage.get("role_bindings", identifier)
        if canonical is None:
            raise AdminError("ROLE_ACTION_UNCONFIRMED")
        validate_role(canonical)
        if not any(entry["action_id"] == action_id and entry["payload_hash"] == payload_hash for entry in canonical["audit"]):
            raise AdminError("ROLE_ACTION_UNCONFIRMED")
        return self.result(canonical, changed=True, action_applied=True)

    @staticmethod
    def result(record: dict, *, changed: bool, action_applied: bool) -> dict:
        return {"status": "pass", "role_status": record["status"], "row_version": record["row_version"],
                "changed": changed, "action_applied": action_applied}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument("--cloud-write-authorized", action="store_true")
    parser.add_argument("--principal", help="Application-user UUID: grant requires active user; revoke verifies the owned role.")
    parser.add_argument("--action", choices=("grant", "revoke"))
    parser.add_argument("--reason")
    parser.add_argument("--key", help="Non-secret operation idempotency key.")
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps(plan(), sort_keys=True))
        return 0
    if not args.cloud_write_authorized:
        raise AdminError("PC03_CLOUD_WRITE_AUTHORIZATION_REQUIRED")
    if not all((args.principal, args.action, args.reason, args.key)):
        raise AdminError("ROLE_INPUT_INVALID")
    from cloud_admin import load_private_environment
    key = load_private_environment().get("CLOUDBASE_APIKEY")
    if not key:
        raise AdminError("SERVER_API_KEY_REQUIRED")
    async def execute() -> dict:
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            family = CloudBaseDocumentRepository(Settings(env_id=ENV_ID, api_key=key), client)
            async def lookup(principal: str) -> dict | None:
                return await family._find_one("users", {"_id": principal, "id": principal, "status": "active"})
            admin = CloudAdmin()
            manager = RoleManager(
                CommunityDocumentRepository(family), lookup, admin.preflight,
                lambda: admin.api("DescribeEnvInfo", {"EnvId": ENV_ID}),
            )
            return await manager.change(args.principal, args.action, args.reason, args.key, cloud_write_authorized=True)
    print(json.dumps(asyncio.run(execute()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AdminError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        raise SystemExit(1) from None
    except (CloudError, ValueError, TypeError, KeyError, OSError):
        print(json.dumps({"status": "blocked", "code": "ROLE_ACTION_UNCONFIRMED"}))
        raise SystemExit(1) from None
