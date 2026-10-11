"""Loopback-only PC04 browser fixture; no credentials or real cloud resources.

The production application, repositories, validators, authentication dependency
and moderation ownership checks run unchanged. Only the verifier and storage
adapters are synthetic. The sole moderator is seeded directly before serving;
there is deliberately no role-grant, reset or other test-control HTTP route.
"""

import argparse
import asyncio
from copy import deepcopy
import logging
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from cloud.api.soulcompanion_cloud.app import create_app  # noqa: E402
from cloud.api.soulcompanion_cloud.auth import AppPrincipal  # noqa: E402
from cloud.api.soulcompanion_cloud.community.repository import (  # noqa: E402
    InMemoryCommunityRepository,
)
from cloud.api.soulcompanion_cloud.community.service import (  # noqa: E402
    normalized_hash,
    role_binding_id,
    validate_role,
)
from cloud.api.soulcompanion_cloud.config import Settings  # noqa: E402
from cloud.api.soulcompanion_cloud.errors import CloudError  # noqa: E402
from cloud.api.soulcompanion_cloud.repository import InMemoryRepository  # noqa: E402


class SyntheticVerifier:
    async def verify(self, token: str) -> AppPrincipal:
        if token not in {
            "community-account-a", "community-account-b", "community-account-c"
        }:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        return AppPrincipal(token, "synthetic-community-environment")

    async def ready(self) -> bool:
        return True


async def seed_operator(
    family: InMemoryRepository, community: InMemoryCommunityRepository,
) -> None:
    user = await family.resolve_user(
        AppPrincipal("community-account-c", "synthetic-community-environment")
    )
    principal = user["id"]
    identifier = role_binding_id(principal)
    at = "2026-10-10T00:00:00.000000Z"
    reason = "合成本地浏览器测试运营授权"
    record = {
        "_id": identifier, "id": identifier, "principal_id": principal,
        "role": "moderator", "status": "active", "row_version": 1,
        "created_at": at, "updated_at": at, "granted_at": at,
        "granted_by": "cloud-admin-cli",
        "audit": [{
            "action_id": str(uuid4()), "actor_id": "cloud-admin-cli",
            "action": "grant", "target_revision": 1, "from_status": None,
            "to_status": "active", "reason": reason, "at": at,
            "payload_hash": normalized_hash({
                "principal_id": principal, "action": "grant", "reason": reason,
            }),
        }],
    }
    validate_role(record)
    community.records["role_bindings"][identifier] = deepcopy(record)


def local_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or not parsed.port or parsed.path or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise argparse.ArgumentTypeError("An exact loopback HTTP origin is required")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--origin", required=True, type=local_origin)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port is out of range")
    family = InMemoryRepository(family_identity_enabled=True)
    community = InMemoryCommunityRepository()
    asyncio.run(seed_operator(family, community))
    config = Settings(
        allowed_origins=(args.origin,), health_rate_limit=10000,
        private_rate_limit=10000, preauth_rate_limit=10000,
    )
    application = create_app(config, family, SyntheticVerifier(), community)
    logging.getLogger("soulcompanion.cloud.access").disabled = True
    uvicorn.run(application, host="127.0.0.1", port=args.port,
                access_log=False, log_level="error", lifespan="on")


if __name__ == "__main__":
    main()
