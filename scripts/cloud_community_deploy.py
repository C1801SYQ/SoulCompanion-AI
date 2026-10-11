"""Offline plan and independently authorized PC03 code-only deployment.

Reuses the audited PC02 SCF managed temporary COS transport. The only cloud
write is UpdateFunctionCode on the existing owned function; schema, identity,
gateway and billing mutations require separate tools and authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Callable
import zipfile

import httpx

try:
    from scripts.cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION, ROOT, parse_response
    from scripts.cloud_deploy import FUNCTION, validate_package
    from scripts.cloud_family_deploy import HTTP_TIMEOUT, ZipTransport, read_zip, target_state, zip_members
except ModuleNotFoundError:
    from cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION, ROOT, parse_response
    from cloud_deploy import FUNCTION, validate_package
    from cloud_family_deploy import HTTP_TIMEOUT, ZipTransport, read_zip, target_state, zip_members


ARTIFACTS = ROOT / ".test-artifacts/cloudbase-pc03"
BACKUPS = ARTIFACTS / "function-backups"
APPROVED_PACKAGES = ARTIFACTS / "approved-packages"
MAX_APPROVED_PACKAGES = 32
PACKAGE = ARTIFACTS / f"{FUNCTION}.zip"
PC02_PACKAGE = ROOT / ".test-artifacts/cloudbase-pc02" / f"{FUNCTION}.zip"
PC02_SHA256 = "81726829c4384d2474509cf382a5b38abd26c0ee0a265a32bcdf0df00956b6b6"
DATABASE_ID = "tnt-28wj48qn2"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def historical_package(historical: Path) -> tuple[bytes, dict[str, str]]:
    previous = read_zip(historical)
    if not hmac.compare_digest(digest(previous), PC02_SHA256):
        raise AdminError("PC02_PACKAGE_CHECKSUM_MISMATCH")
    members = zip_members(previous)
    with zipfile.ZipFile(io.BytesIO(previous)) as archive:
        if stat.S_IMODE(archive.getinfo("scf_bootstrap").external_attr >> 16) != 0o755:
            raise AdminError("LOCAL_BOOTSTRAP_MODE_UNVERIFIED")
    return previous, members


def packages(candidate: Path, historical: Path) -> tuple[bytes, bytes, dict[str, str], dict[str, str]]:
    """Pin PC02 bytes and require the candidate to match all current API source."""
    if candidate.resolve() == historical.resolve():
        raise AdminError("CANDIDATE_AND_HISTORY_MUST_DIFFER")
    evidence = validate_package(candidate)
    forward = read_zip(candidate)
    if digest(forward) != evidence.get("zip_sha256"):
        raise AdminError("PACKAGE_CHANGED_AFTER_VALIDATION")
    previous, previous_members = historical_package(historical)
    forward_members = zip_members(forward)
    with zipfile.ZipFile(io.BytesIO(forward)) as archive:
        if stat.S_IMODE(archive.getinfo("scf_bootstrap").external_attr >> 16) != 0o755:
            raise AdminError("LOCAL_BOOTSTRAP_MODE_UNVERIFIED")
    if forward_members == previous_members:
        raise AdminError("CANDIDATE_EQUALS_PC02_BASELINE")
    return forward, previous, forward_members, previous_members


def plan(candidate: Path = PACKAGE, historical: Path = PC02_PACKAGE, *, rollback: bool = False) -> dict:
    if rollback:
        target, target_members = historical_package(historical)
    else:
        target, _, target_members, _ = packages(candidate, historical)
    return {
        "status": "plan", "real_calls": False, "env_id": ENV_ID, "region": REGION,
        "database_id": DATABASE_ID, "function": FUNCTION,
        "operation": "restore_pc02_code" if rollback else "update_pc03_code",
        "zip_sha256": digest(target), "pc02_baseline_sha256": PC02_SHA256,
        "package_bytes": len(target), "package_files": len(target_members), "bootstrap_mode": "0755",
        "upload": "SCF managed temporary COS; original ZIP bytes",
        "new_resources": 0, "configuration_changes": [], "identity_changes": [],
        "gateway_changes": [], "schema_marker_changes": [], "paid_upgrade": False, "backfill": False,
        "cost": "Uses existing trial quota for code upload, package storage and verification requests; not a lifetime-free guarantee.",
        "billing_guards": {"package_id": "baas_trial", "overrun": False, "auto_renew": False},
        "rollback": "Explicit --rollback restores checksum-pinned PC02 code and retains all community data and schema.",
        "rollback_ownership": "Verify PC03 against locally frozen, source-approved ZIP members; current source or candidate may be stale or missing.",
        "marker_disabling": "Not performed. Disabling the PC03 marker requires a separately authorized schema operation.",
        "authorization_required": "PC03 authorization and --apply --cloud-write-authorized; PC02 authorization does not carry over.",
        "cloud_verification": "Fresh environment/region/database/trial/owner/config/route; downloaded bytes and all ZIP members before/after update.",
        "health_acceptance": "NOT TESTED; separate API and official SDK acceptance required after code verification.",
    }


def verified_target(admin: CloudAdmin) -> tuple[dict, dict]:
    """Retain the complete private function configuration only in memory."""
    audit, configuration = target_state(admin)
    info = admin.api("DescribeEnvInfo", {"EnvId": ENV_ID})
    environment = info.get("EnvInfo") if isinstance(info, dict) else None
    base = environment.get("EnvBaseInfo") if isinstance(environment, dict) else None
    if not isinstance(base, dict):
        raise AdminError("COMMUNITY_DEPLOY_TARGET_UNVERIFIED")
    databases = base.get("Databases")
    if not isinstance(databases, list) or any(not isinstance(item, dict) for item in databases):
        raise AdminError("COMMUNITY_DEPLOY_TARGET_UNVERIFIED")
    running = [item for item in databases if item.get("Status") == "RUNNING"]
    if (base.get("EnvId") != ENV_ID or base.get("Region") != REGION or base.get("Status") != "NORMAL"
            or len(running) != 1 or running[0].get("InstanceId") != DATABASE_ID):
        raise AdminError("COMMUNITY_DEPLOY_TARGET_UNVERIFIED")
    return audit, configuration


def retain_zip(directory: Path, data: bytes, code_hash: str) -> None:
    """Retain a verified private ZIP without overwriting any existing file."""
    private_root = ROOT / ".test-artifacts"
    try:
        if not re.fullmatch(r"[0-9a-f]{64}", code_hash) or not hmac.compare_digest(digest(data), code_hash):
            raise ValueError
        if directory.is_symlink() or private_root.resolve() not in directory.resolve().parents:
            raise ValueError
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{code_hash}.zip"
        if path.is_symlink():
            raise ValueError
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError
            return
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        if digest(path.read_bytes()) != code_hash:
            raise ValueError
    except (OSError, ValueError):
        raise AdminError("PRIVATE_BACKUP_NOT_RETAINED") from None


def retain_backup(data: bytes, code_hash: str) -> None:
    retain_zip(BACKUPS, data, code_hash)


def approved_snapshots() -> list[tuple[bytes, dict[str, str]]]:
    """Bounded local ownership evidence; none of these ZIPs is cloud acceptance."""
    private_root = ROOT / ".test-artifacts"
    if APPROVED_PACKAGES.is_symlink() or private_root.resolve() not in APPROVED_PACKAGES.resolve().parents:
        raise AdminError("APPROVED_PACKAGE_UNVERIFIED")
    if not APPROVED_PACKAGES.exists():
        return []
    try:
        paths = list(APPROVED_PACKAGES.iterdir())
        if len(paths) > MAX_APPROVED_PACKAGES:
            raise ValueError
        result = []
        for path in paths:
            if re.fullmatch(r"[0-9a-f]{64}\.zip", path.name) is None:
                raise ValueError
            data = read_zip(path)
            if digest(data) != path.stem:
                raise ValueError
            members = zip_members(data)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if stat.S_IMODE(archive.getinfo("scf_bootstrap").external_attr >> 16) != 0o755:
                    raise ValueError
            result.append((data, members))
        return result
    except (OSError, ValueError, AdminError):
        raise AdminError("APPROVED_PACKAGE_UNVERIFIED") from None


def freeze_approved_package(data: bytes) -> None:
    snapshots = approved_snapshots()
    if any(existing == data for existing, _ in snapshots):
        return
    if len(snapshots) >= MAX_APPROVED_PACKAGES:
        raise AdminError("APPROVED_PACKAGE_CAPACITY_EXCEEDED")
    retain_zip(APPROVED_PACKAGES, data, digest(data))


def verify_rollback_owner(current_members: dict, candidate: Path, historical: Path) -> None:
    if any(current_members == members for _, members in approved_snapshots()):
        return
    # A current source-valid candidate is also allowed, for a verified manual
    # code upload. This is only a fallback; rollback never requires its presence.
    try:
        forward, _, forward_members, _ = packages(candidate, historical)
    except AdminError:
        raise AdminError("ROLLBACK_OWNERSHIP_PROOF_UNAVAILABLE") from None
    if current_members != forward_members:
        raise AdminError("CURRENT_CODE_NOT_OWNED")
    freeze_approved_package(forward)


def apply_deployment(admin: CloudAdmin, transport: ZipTransport, candidate: Path, historical: Path,
                     *, cloud_write_authorized: bool = False, rollback: bool = False,
                     now: Callable[[], float] = time.monotonic,
                     sleep: Callable[[float], None] = time.sleep) -> dict:
    if cloud_write_authorized is not True:
        raise AdminError("CLOUD_WRITE_AUTHORIZATION_REQUIRED")
    if transport.admin is not admin:
        raise AdminError("DEPLOYMENT_TRANSPORT_MISMATCH")
    if rollback:
        desired, desired_members = historical_package(historical)
        forward = None
        forward_members = None
        previous_members = desired_members
    else:
        forward, previous, forward_members, previous_members = packages(candidate, historical)
        desired, desired_members = forward, forward_members
    baseline = verified_target(admin)
    current, current_hash = transport.download()
    current_members = zip_members(current)
    if rollback and current_members != previous_members:
        verify_rollback_owner(current_members, candidate, historical)
    elif not rollback and current_members not in (forward_members, previous_members):
        if not any(current_members == members for _, members in approved_snapshots()):
            raise AdminError("CURRENT_CODE_NOT_OWNED")
    if verified_target(admin) != baseline:
        raise AdminError("FUNCTION_CONFIGURATION_CHANGED")
    result = {
        "env_id": ENV_ID, "region": REGION, "database_id": DATABASE_ID, "function": FUNCTION,
        "new_resources": 0, "zip_sha256": digest(desired), "package_bytes": len(desired),
        "configuration_unchanged": True, "rollback": rollback, "schema_marker_changes": [],
        "health_acceptance": "pending_separate_acceptance", "real_cloud_api_acceptance": "NOT TESTED",
    }
    if current_members == desired_members:
        if not rollback:
            freeze_approved_package(forward)
        return {**result, "status": "already_verified", "remote_code_sha256": current_hash, "backup_retained": False}
    retain_backup(current, current_hash)
    if not rollback:
        if validate_package(candidate).get("zip_sha256") != digest(forward):
            raise AdminError("PACKAGE_CHANGED_AFTER_VALIDATION")
        freeze_approved_package(forward)
    _, latest_hash = transport.address()
    if latest_hash != current_hash:
        raise AdminError("CURRENT_CODE_CHANGED")
    key = transport.upload(desired)
    if verified_target(admin) != baseline:
        raise AdminError("FUNCTION_CONFIGURATION_CHANGED")
    _, latest_hash = transport.address()
    if latest_hash != current_hash:
        raise AdminError("CURRENT_CODE_CHANGED")
    transport.update(key)
    # RequestId confirms submission only. Never repeat an uncertain code write.
    deadline = now() + 150
    for attempt in range(5):
        detail = parse_response(admin.capture([
            "fn", "detail", FUNCTION, "--env-id", ENV_ID, "--region", REGION, "--json",
        ], timeout=30))
        if detail.get("Status") == "Active":
            if verified_target(admin) != baseline:
                raise AdminError("FUNCTION_CONFIGURATION_CHANGED")
            confirmed, confirmed_hash = transport.download()
            if zip_members(confirmed) == desired_members:
                if verified_target(admin) != baseline:
                    raise AdminError("FUNCTION_CONFIGURATION_CHANGED")
                return {**result, "status": "code_verified", "remote_code_sha256": confirmed_hash, "backup_retained": True}
        elif detail.get("Status") not in {"Updating", "Creating"}:
            raise AdminError("UPDATED_FUNCTION_NOT_ACTIVE")
        if attempt == 4 or now() >= deadline:
            break
        sleep(3)
    raise AdminError("UPDATED_CODE_NOT_VERIFIED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Print the offline plan (default).")
    mode.add_argument("--apply", action="store_true", help="Update only existing function code after PC03 authorization.")
    parser.add_argument("--cloud-write-authorized", action="store_true")
    parser.add_argument("--rollback", action="store_true", help="Restore pinned PC02 code; do not disable schema or delete data.")
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--pc02-package", type=Path, default=PC02_PACKAGE)
    args = parser.parse_args(argv)
    try:
        if args.apply and not args.cloud_write_authorized:
            raise AdminError("CLOUD_WRITE_AUTHORIZATION_REQUIRED")
        if not args.apply:
            result = plan(args.package, args.pc02_package, rollback=args.rollback)
        else:
            admin = CloudAdmin()
            with httpx.Client(follow_redirects=False, trust_env=False, timeout=HTTP_TIMEOUT) as client:
                result = apply_deployment(admin, ZipTransport(admin, client), args.package, args.pc02_package,
                                          cloud_write_authorized=True, rollback=args.rollback)
        print(json.dumps(result, sort_keys=True))
    except AdminError as error:
        code = str(error)
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", code) is None:
            code = "COMMUNITY_CODE_DEPLOYMENT_FAILED"
        print(json.dumps({"status": "blocked", "code": code}))
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, httpx.HTTPError, zipfile.BadZipFile):
        print(json.dumps({"status": "blocked", "code": "COMMUNITY_CODE_DEPLOYMENT_FAILED"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
