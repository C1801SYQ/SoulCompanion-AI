"""PC04 offline plan and separately authorized code-only update, with PC03 rollback.

Reuses the audited deployment transport and ownership/configuration guards.
No schema, gateway, identity, role or fee setting can be changed by this tool.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import zipfile

import httpx

try:
    from scripts import cloud_community_deploy as deploy
except ModuleNotFoundError:
    import cloud_community_deploy as deploy

PC03_SHA256 = "835348e8c775cade98a6a263cce8990088c76c37019f61ebab2eecd2574246fe"
PC03_PACKAGE = deploy.ROOT / ".test-artifacts/cloudbase-pc03/sc-v2-api.zip"
PACKAGE = deploy.ROOT / ".test-artifacts/cloudbase-pc04/sc-v2-api.zip"


def plan(candidate: Path = PACKAGE, historical: Path = PC03_PACKAGE, *, rollback: bool = False) -> dict:
    if rollback:
        desired, members = deploy.historical_package(historical, baseline_sha256=PC03_SHA256)
    else:
        desired, _, members, _ = deploy.packages(candidate, historical, baseline_sha256=PC03_SHA256)
    return {
        "status": "plan", "real_calls": False, "env_id": deploy.ENV_ID, "region": deploy.REGION,
        "database_id": deploy.DATABASE_ID, "function": deploy.FUNCTION,
        "operation": "restore_pc03_code" if rollback else "update_pc04_read_compatibility",
        "zip_sha256": deploy.digest(desired), "pc03_baseline_sha256": PC03_SHA256,
        "package_bytes": len(desired), "package_files": len(members), "bootstrap_mode": "0755",
        "new_resources": [], "schema_changes": [], "gateway_changes": [], "identity_changes": [],
        "configuration_changes": [], "paid_upgrade": False,
        "billing_guards": {"package_id": "baas_trial", "overrun": False, "auto_renew": False},
        "cost": "Existing trial quota for bounded upload/download and verification; stop if quota or fees are unclear.",
        "authorization_required": "Independent PC04 approval AND --apply --cloud-write-authorized; no inherited PC03 approval.",
        "rollback": "Restore checksum-pinned PC03 code; retain all old and new community data, markers, indexes and audit.",
        "health_acceptance": "NOT TESTED; code identity does not replace browser/API acceptance.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cloud-write-authorized", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--pc03-package", type=Path, default=PC03_PACKAGE)
    args = parser.parse_args(argv)
    try:
        if args.apply and not args.cloud_write_authorized:
            raise deploy.AdminError("PC04_CLOUD_WRITE_AUTHORIZATION_REQUIRED")
        if not args.apply:
            result = plan(args.package, args.pc03_package, rollback=args.rollback)
        else:
            admin = deploy.CloudAdmin()
            with httpx.Client(follow_redirects=False, trust_env=False, timeout=deploy.HTTP_TIMEOUT) as client:
                result = deploy.apply_deployment(admin, deploy.ZipTransport(admin, client), args.package,
                                                 args.pc03_package, cloud_write_authorized=True,
                                                 rollback=args.rollback, baseline_sha256=PC03_SHA256)
        print(json.dumps(result, sort_keys=True))
    except deploy.AdminError as error:
        code = str(error)
        print(json.dumps({"status": "blocked", "code": code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", code) else "PC04_CODE_UPDATE_FAILED"}))
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, httpx.HTTPError, zipfile.BadZipFile):
        print(json.dumps({"status": "blocked", "code": "PC04_CODE_UPDATE_FAILED"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
