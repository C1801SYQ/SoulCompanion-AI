"""Offline plan and explicitly authorized PC02 code-only ZIP deployment.

The official CLI 3.8.5 SCF managed temporary COS upload is reproduced without
its Windows directory repacking: GetTempCosInfo, PUT the original ZIP bytes,
then UpdateFunctionCode. No application bucket or other resource is created.
Signed download URLs and the temporary authorization stay in process memory.
"""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import date
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
from typing import Callable
from urllib.parse import urlsplit
import zipfile

import httpx

try:
    from scripts.cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION, ROOT, parse_response
    from scripts.cloud_deploy import FUNCTION, OWNER_MARKER, inspect_resources, validate_package
    from scripts.cloud_package import MAX_EXPANDED_BYTES, MAX_PACKAGE_BYTES
except ModuleNotFoundError:
    from cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION, ROOT, parse_response
    from cloud_deploy import FUNCTION, OWNER_MARKER, inspect_resources, validate_package
    from cloud_package import MAX_EXPANDED_BYTES, MAX_PACKAGE_BYTES


ARTIFACTS = ROOT / ".test-artifacts/cloudbase-pc02"
BACKUPS = ARTIFACTS / "function-backups"
PACKAGE = ARTIFACTS / f"{FUNCTION}.zip"
PHASE04_PACKAGE = ROOT / ".test-artifacts/cloudbase-phase04" / f"{FUNCTION}.zip"
PHASE04_SHA256 = "d1fda1c05f2a52daf6ae49d49141b4421d1a955c9eb916645ab952af9b240745"
DATABASE_ID = "tnt-28wj48qn2"
DOWNLOAD_HOST = "scf-v2-sh-1253665819.cos.ap-shanghai.myqcloud.com"
# Official @cloudbase/cli 3.8.5 bundled SDK SCF_TEMP_COS (cli.js:193435)
# and uploadFunctionZipToCos (cli.js:204473). This is the platform's bucket.
UPLOAD_HOST = "shtempcos-1253665819.cos.ap-shanghai.myqcloud.com"
REQUEST_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
VOLATILE_DETAIL_FIELDS = {
    "RequestId", "Status", "StatusDesc", "CodeInfo", "CodeSize", "CodeSha256",
    "ModTime", "LastModifiedTime", "LastUpdateTime", "LastUpdateStatus", "LastUpdateStatusReason",
}
HTTP_TIMEOUT = httpx.Timeout(connect=5, read=20, write=30, pool=5)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_members(data: bytes) -> dict[str, str]:
    """Bound expansion and compare every file, allowing service recompression."""
    try:
        if not data or len(data) > MAX_PACKAGE_BYTES:
            raise ValueError
        result = {}
        seen, directories = set(), set()
        expanded = 0
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if not 1 <= len(archive.infolist()) <= 10000:
                raise ValueError
            for entry in archive.infolist():
                member = PurePosixPath(entry.filename)
                mode = entry.external_attr >> 16
                directory = entry.is_dir()
                normalized = str(member)
                if (
                    normalized in seen or entry.filename != entry.orig_filename
                    or normalized in {".", "/"} or member.is_absolute()
                    or normalized + ("/" if directory else "") != entry.filename
                    or ".." in member.parts or "\\" in entry.filename
                    or any(":" in part or part in {".env", ".git", "tests", "__pycache__"}
                           or any(ord(c) < 32 for c in part) for part in member.parts)
                    or stat.S_IFMT(mode) not in {0, stat.S_IFDIR if directory else stat.S_IFREG}
                    or entry.flag_bits & 1 or (directory and entry.file_size != 0)
                ):
                    raise ValueError
                seen.add(normalized)
                expanded += entry.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise ValueError
                if directory:
                    if archive.read(entry) != b"":
                        raise ValueError
                    directories.add(normalized)
                    continue
                result[entry.filename] = digest(archive.read(entry))
            prefixes = {str(parent) for name in result for parent in PurePosixPath(name).parents if str(parent) != "."}
            if not directories <= prefixes:
                raise ValueError
            bootstrap = archive.getinfo("scf_bootstrap")
            if stat.S_IMODE(bootstrap.external_attr >> 16) not in {0o755, 0o777}:
                raise ValueError
        return result
    except (OSError, ValueError, KeyError, RuntimeError, NotImplementedError, zipfile.BadZipFile):
        raise AdminError("ZIP_CONTENT_UNVERIFIED") from None


def read_zip(path: Path) -> bytes:
    try:
        if path.suffix != ".zip" or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError
        return path.read_bytes()
    except (OSError, ValueError):
        raise AdminError("LOCAL_ZIP_UNVERIFIED") from None


def packages(candidate: Path, historical: Path) -> tuple[bytes, bytes, dict[str, str], dict[str, str]]:
    evidence = validate_package(candidate)
    forward = read_zip(candidate)
    if digest(forward) != evidence["zip_sha256"]:
        raise AdminError("PACKAGE_CHANGED_AFTER_VALIDATION")
    previous = read_zip(historical)
    if not hmac.compare_digest(digest(previous), PHASE04_SHA256):
        raise AdminError("PHASE04_PACKAGE_CHECKSUM_MISMATCH")
    forward_members, previous_members = zip_members(forward), zip_members(previous)
    with zipfile.ZipFile(io.BytesIO(forward)) as archive:
        if stat.S_IMODE(archive.getinfo("scf_bootstrap").external_attr >> 16) != 0o755:
            raise AdminError("FORWARD_BOOTSTRAP_MODE_UNVERIFIED")
    return forward, previous, forward_members, previous_members


def plan(candidate: Path = PACKAGE, historical: Path = PHASE04_PACKAGE, *, rollback: bool = False) -> dict:
    forward, previous, _, _ = packages(candidate, historical)
    target = previous if rollback else forward
    return {
        "status": "plan", "real_calls": False, "env_id": ENV_ID, "region": REGION,
        "function": FUNCTION, "operation": "restore_phase04_code" if rollback else "update_pc02_code",
        "zip_sha256": digest(target), "package_bytes": len(target), "bootstrap_mode": "0755",
        "upload": "SCF managed temporary COS; original ZIP bytes",
        "new_resources": 0, "configuration_changes": [], "identity_changes": [],
        "gateway_changes": [], "paid_upgrade": False, "backfill": False,
        "rollback": "Explicit --rollback restores the checksum-pinned Phase04 ZIP; retain database data and schema.",
        "authorization_required": "--apply --cloud-write-authorized",
        "cloud_verification": "Fresh trial/owner/config/route, downloaded checksum and all ZIP members before and after update.",
    }


class ZipTransport:
    """Existing CLI administrator credentials; private HTTP never logs bodies."""

    def __init__(self, admin: CloudAdmin, client: httpx.Client,
                 *, now: Callable[[], float] = time.monotonic):
        self.admin = admin
        self.client = client
        self.now = now

    def _scf(self, action: str, body: dict) -> dict:
        # Each caller supplies fixed public parameters, never URL/sign/env vars.
        if action not in {"GetFunctionAddress", "GetTempCosInfo", "UpdateFunctionCode"}:
            raise AdminError("SCF_ACTION_NOT_ALLOWED")
        try:
            return parse_response(self.admin.capture([
                "api", "scf", action, "--region", REGION, "--api-version", "2018-04-16",
                "--body", json.dumps(body, separators=(",", ":")), "--json",
            ], timeout=30))
        except (AdminError, OSError, ValueError, TypeError):
            raise AdminError("CODE_UPDATE_FAILED" if action == "UpdateFunctionCode" else "PRIVATE_SCF_READ_FAILED") from None

    def address(self) -> tuple[str, str]:
        response = self._scf("GetFunctionAddress", {
            "FunctionName": FUNCTION, "Namespace": ENV_ID, "Qualifier": "$LATEST",
        })
        url = response.get("Url")
        try:
            parsed = urlsplit(url)
            if (
                not isinstance(url, str) or not url or len(url) > 16384
                or any(c.isspace() or ord(c) < 32 for c in url)
                or parsed.scheme != "https" or parsed.hostname != DOWNLOAD_HOST
                or parsed.netloc != DOWNLOAD_HOST or parsed.port is not None
                or parsed.username or parsed.password or parsed.fragment or not parsed.path
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise AdminError("UNAPPROVED_DOWNLOAD_TARGET") from None
        code_hash = response.get("CodeSha256")
        try:
            if not isinstance(code_hash, str):
                raise ValueError
            if re.fullmatch(r"[0-9a-fA-F]{64}", code_hash):
                code_hash = code_hash.lower()
            else:
                raw = base64.b64decode(code_hash, validate=True)
                if len(raw) != 32:
                    raise ValueError
                code_hash = raw.hex()
        except (ValueError, TypeError):
            raise AdminError("REMOTE_CODE_CHECKSUM_UNVERIFIED") from None
        return url, code_hash

    def download(self) -> tuple[bytes, str]:
        url, expected = self.address()
        request = httpx.Request("GET", url, headers={"Accept-Encoding": "identity"},
                                extensions={"timeout": HTTP_TIMEOUT.as_dict()})
        response = None
        try:
            started = self.now()
            # Construct Request directly: no client default auth, headers or cookies.
            response = self.client.send(request, stream=True, auth=None, follow_redirects=False)
            length = response.headers.get("content-length")
            if response.status_code != 200 or (length is not None and (not length.isdecimal() or int(length) > MAX_PACKAGE_BYTES)):
                raise AdminError("PRIVATE_DOWNLOAD_FAILED")
            chunks, size = [], 0
            for chunk in response.iter_raw():
                size += len(chunk)
                if size > MAX_PACKAGE_BYTES or self.now() - started > 60:
                    raise AdminError("PRIVATE_DOWNLOAD_LIMIT_EXCEEDED")
                chunks.append(chunk)
            data = b"".join(chunks)
        except (httpx.HTTPError, OSError, ValueError):
            raise AdminError("PRIVATE_DOWNLOAD_FAILED") from None
        finally:
            if response is not None:
                response.close()
        if not hmac.compare_digest(digest(data), expected):
            raise AdminError("REMOTE_CODE_CHECKSUM_MISMATCH")
        return data, expected

    def upload(self, data: bytes) -> str:
        if not data or len(data) > MAX_PACKAGE_BYTES:
            raise AdminError("UPLOAD_PACKAGE_UNVERIFIED")
        info = self.admin.api("DescribeEnvInfo", {"EnvId": ENV_ID})
        base = info.get("EnvInfo", {}).get("EnvBaseInfo", {})
        app_id = info.get("EnvInfo", {}).get("UserInfo", {}).get("AppId")
        if (base.get("EnvId") != ENV_ID or base.get("Region") != REGION or base.get("Status") != "NORMAL"
                or type(app_id) not in {int, str} or not re.fullmatch(r"[0-9]{6,20}", str(app_id))):
            raise AdminError("UPLOAD_ENVIRONMENT_UNVERIFIED")
        object_path = f"{app_id}/{ENV_ID}/{FUNCTION}.zip"
        response = self._scf("GetTempCosInfo", {"ObjectPath": object_path})
        cos_date, signature = response.get("Date"), response.get("Sign")
        try:
            if not isinstance(cos_date, str) or date.fromisoformat(cos_date).isoformat() != cos_date:
                raise ValueError
            if (not isinstance(signature, str) or not 1 <= len(signature) <= 8192
                    or any(ord(c) < 33 or ord(c) > 126 for c in signature)):
                raise ValueError
        except (ValueError, TypeError):
            raise AdminError("TEMP_UPLOAD_AUTH_UNVERIFIED") from None
        key = f"/{cos_date}/{object_path}"
        md5 = hashlib.md5(data, usedforsecurity=False).digest()
        request = httpx.Request("PUT", f"https://{UPLOAD_HOST}{key}", content=data, headers={
            "Authorization": signature, "Content-Type": "application/zip",
            "Content-MD5": base64.b64encode(md5).decode("ascii"),
        }, extensions={"timeout": HTTP_TIMEOUT.as_dict()})
        uploaded = None
        try:
            started = self.now()
            uploaded = self.client.send(request, stream=True, auth=None, follow_redirects=False)
            if (uploaded.status_code != 200 or self.now() - started > 60
                    or uploaded.headers.get("ETag", "").strip('"').lower() != md5.hex()):
                raise AdminError("PRIVATE_UPLOAD_NOT_CONFIRMED")
        except (httpx.HTTPError, OSError, ValueError):
            raise AdminError("PRIVATE_UPLOAD_FAILED") from None
        finally:
            if uploaded is not None:
                uploaded.close()
        return key

    def update(self, key: str) -> None:
        if not re.fullmatch(r"/[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]{6,20}/" + re.escape(ENV_ID)
                            + "/" + re.escape(FUNCTION) + r"\.zip", key):
            raise AdminError("TEMP_OBJECT_TARGET_UNVERIFIED")
        response = self._scf("UpdateFunctionCode", {
            "FunctionName": FUNCTION, "Namespace": ENV_ID, "InstallDependency": "FALSE", "Publish": "FALSE",
            "Code": {"CosBucketRegion": REGION, "TempCosObjectName": key},
        })
        if not isinstance(response.get("RequestId"), str) or not REQUEST_ID.fullmatch(response["RequestId"]):
            raise AdminError("CODE_UPDATE_NOT_CONFIRMED")


def target_state(admin: CloudAdmin) -> tuple[dict, dict]:
    audit, existing, route = inspect_resources(admin)
    if (
        not existing or not route or audit.get("env_id") != ENV_ID or audit.get("region") != REGION
        or audit.get("package_id") != "baas_trial" or audit.get("overrun") is not False
        or audit.get("auto_renew") is not False or audit.get("database_id") != DATABASE_ID
    ):
        raise AdminError("FAMILY_DEPLOY_TARGET_UNVERIFIED")
    detail = parse_response(admin.capture([
        "fn", "detail", FUNCTION, "--env-id", ENV_ID, "--region", REGION, "--json",
    ], timeout=30))
    if (detail.get("FunctionName") != FUNCTION or detail.get("Namespace") != ENV_ID
            or detail.get("Description") != OWNER_MARKER or detail.get("Type") != "HTTP"
            or detail.get("Runtime") != "Python3.11" or detail.get("MemorySize") != 256
            or detail.get("Timeout") != 3 or detail.get("Status") != "Active"):
        raise AdminError("FUNCTION_NOT_ACTIVE_OR_OWNED")
    # Includes Environment and every unrecognized field, retained only in memory.
    configuration = {name: deepcopy(value) for name, value in detail.items() if name not in VOLATILE_DETAIL_FIELDS}
    return audit, configuration


def retain_backup(data: bytes, code_hash: str) -> None:
    private_root = ROOT / ".test-artifacts"
    try:
        if not re.fullmatch(r"[0-9a-f]{64}", code_hash) or not hmac.compare_digest(digest(data), code_hash):
            raise ValueError
        if BACKUPS.is_symlink() or private_root.resolve() not in BACKUPS.resolve().parents:
            raise ValueError
        BACKUPS.mkdir(parents=True, exist_ok=True)
        path = BACKUPS / f"{code_hash}.zip"
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


def apply_deployment(admin: CloudAdmin, transport: ZipTransport, candidate: Path, historical: Path,
                     *, cloud_write_authorized: bool = False, rollback: bool = False,
                     now: Callable[[], float] = time.monotonic,
                     sleep: Callable[[float], None] = time.sleep) -> dict:
    if cloud_write_authorized is not True:
        raise AdminError("CLOUD_WRITE_AUTHORIZATION_REQUIRED")
    if transport.admin is not admin:
        raise AdminError("DEPLOYMENT_TRANSPORT_MISMATCH")
    forward, previous, forward_members, previous_members = packages(candidate, historical)
    desired, desired_members = (previous, previous_members) if rollback else (forward, forward_members)
    baseline = target_state(admin)
    current, current_hash = transport.download()
    current_members = zip_members(current)
    if current_members not in (forward_members, previous_members):
        raise AdminError("CURRENT_CODE_NOT_OWNED")
    if target_state(admin) != baseline:
        raise AdminError("FUNCTION_CONFIGURATION_CHANGED")
    result = {
        "env_id": ENV_ID, "region": REGION, "function": FUNCTION, "new_resources": 0,
        "zip_sha256": digest(desired), "package_bytes": len(desired), "configuration_unchanged": True,
        "rollback": rollback, "health_acceptance": "pending_separate_acceptance",
    }
    if current_members == desired_members:
        return {**result, "status": "already_verified", "backup_retained": False}
    retain_backup(current, current_hash)
    # Check local source/package and remote code again immediately before upload.
    if validate_package(candidate).get("zip_sha256") != digest(forward):
        raise AdminError("PACKAGE_CHANGED_AFTER_VALIDATION")
    _, latest_hash = transport.address()
    if latest_hash != current_hash:
        raise AdminError("CURRENT_CODE_CHANGED")
    key = transport.upload(desired)
    if target_state(admin) != baseline:
        raise AdminError("FUNCTION_CONFIGURATION_CHANGED")
    _, latest_hash = transport.address()
    if latest_hash != current_hash:
        raise AdminError("CURRENT_CODE_CHANGED")
    transport.update(key)
    # A successful API RequestId is submission evidence only. Bound completion
    # checks; failed verification retains the backup and does not add writes.
    deadline = now() + 150
    for attempt in range(5):
        detail = parse_response(admin.capture([
            "fn", "detail", FUNCTION, "--env-id", ENV_ID, "--region", REGION, "--json",
        ], timeout=30))
        if detail.get("Status") == "Active":
            if target_state(admin) != baseline:
                raise AdminError("FUNCTION_CONFIGURATION_CHANGED")
            confirmed, confirmed_hash = transport.download()
            if zip_members(confirmed) == desired_members:
                if target_state(admin) != baseline:
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
    mode.add_argument("--apply", action="store_true", help="Apply only the bounded code update after authorization.")
    parser.add_argument("--cloud-write-authorized", action="store_true")
    parser.add_argument("--rollback", action="store_true", help="Restore only checksum-pinned Phase04 code; retain all data.")
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--phase04-package", type=Path, default=PHASE04_PACKAGE)
    args = parser.parse_args(argv)
    try:
        if args.apply and not args.cloud_write_authorized:
            raise AdminError("CLOUD_WRITE_AUTHORIZATION_REQUIRED")
        if not args.apply:
            result = plan(args.package, args.phase04_package, rollback=args.rollback)
        else:
            admin = CloudAdmin()
            with httpx.Client(follow_redirects=False, trust_env=False, timeout=HTTP_TIMEOUT) as client:
                result = apply_deployment(admin, ZipTransport(admin, client), args.package, args.phase04_package,
                                          cloud_write_authorized=True, rollback=args.rollback)
        print(json.dumps(result, sort_keys=True))
    except AdminError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, httpx.HTTPError, zipfile.BadZipFile):
        print(json.dumps({"status": "blocked", "code": "FAMILY_CODE_DEPLOYMENT_FAILED"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
