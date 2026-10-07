"""Plan or apply one bounded deployment in the owner-confirmed trial environment.

This does not create an environment, a database, a key, a paid service, or a
prewarmed instance. The ignored private environment file is configured separately.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from urllib.parse import urlsplit
import zipfile

try:
    from scripts.cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION, ROOT, load_private_environment, parse_response
    from scripts.cloud_package import DEPENDENCIES, MAX_EXPANDED_BYTES, MAX_PACKAGE_BYTES, collect_source, sha256
except ModuleNotFoundError:
    from cloud_admin import AdminError, CloudAdmin, ENV_ID, REGION, ROOT, load_private_environment, parse_response
    from cloud_package import DEPENDENCIES, MAX_EXPANDED_BYTES, MAX_PACKAGE_BYTES, collect_source, sha256

FUNCTION = "sc-v2-api"
OWNER_MARKER = "SoulCompanion-AI phase04 HTTP API; owner=phase04"
ARTIFACTS = ROOT / ".test-artifacts/cloudbase-phase04"
ROUTE = {
    "path": "/", "upstreamResourceType": "WEB_SCF", "upstreamResourceName": FUNCTION,
    "enable": True, "enableAuth": False, "enableSafeDomain": False,
    "enablePathTransmission": True,
    "qpsPolicy": {"qpsTotal": 20, "qpsPerClient": {"limitBy": "ClientIP", "limitValue": 5}},
}


def function_config(variables: dict[str, str]) -> dict:
    return {
        "name": FUNCTION, "type": "HTTP", "runtime": "Python3.11",
        "timeout": 3, "memorySize": 256, "description": OWNER_MARKER,
        "installDependency": False, "envVariables": variables,
    }


def validate_variables(variables: dict[str, str]) -> dict[str, str]:
    key = variables.get("CLOUDBASE_APIKEY", "")
    if not key or len(key) > 16384 or any(character.isspace() for character in key):
        raise AdminError("SERVER_APIKEY_REQUIRED")
    if variables.get("CLOUDBASE_ENV_ID", ENV_ID) != ENV_ID:
        raise AdminError("WRONG_ENVIRONMENT")
    origins = []
    for origin in filter(None, (value.strip() for value in variables.get("CLOUD_ALLOWED_ORIGINS", "").split(","))):
        parsed = urlsplit(origin)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme not in ({"http", "https"} if local else {"https"}) or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or "*" in origin or any(character.isspace() for character in origin):
            raise AdminError("EXACT_CORS_ORIGINS_REQUIRED")
        origins.append(origin)
    return {"CLOUDBASE_ENV_ID": ENV_ID, "CLOUDBASE_APIKEY": key, "CLOUD_ALLOWED_ORIGINS": ",".join(origins)}


def inspect_resources(admin: CloudAdmin) -> tuple[dict, bool, bool]:
    """Return only public planning fields; function Environment is never returned."""
    free = admin.preflight()
    functions = []
    offset = 0
    while True:
        response = parse_response(admin.capture(["fn", "list", "--env-id", ENV_ID, "--region", REGION, "--limit", "100", "--offset", str(offset), "--json"]))
        page = response.get("Functions")
        if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
            raise AdminError("FUNCTION_LIST_UNVERIFIED")
        functions.extend(page)
        if len(page) < 100:
            if response.get("TotalCount", len(functions)) != len(functions):
                raise AdminError("FUNCTION_LIST_UNVERIFIED")
            break
        offset += len(page)
        if offset >= 10000:
            raise AdminError("FUNCTION_LIST_TOO_LARGE")
    matches = [item for item in functions if item.get("FunctionName") == FUNCTION]
    if len(matches) > 1:
        raise AdminError("FUNCTION_COLLISION")
    existing = bool(matches)
    if existing:
        detail = parse_response(admin.capture(["fn", "detail", FUNCTION, "--env-id", ENV_ID, "--region", REGION, "--json"]))
        if detail.get("Description") != OWNER_MARKER or detail.get("Namespace") != ENV_ID or detail.get("Type") != "HTTP":
            raise AdminError("FUNCTION_COLLISION")
        if detail.get("Runtime") != "Python3.11" or detail.get("MemorySize") != 256 or detail.get("Timeout") != 3:
            raise AdminError("OWNED_FUNCTION_CONFIG_UNVERIFIED")
    route_data = admin.api("DescribeHTTPServiceRoute", {"EnvId": ENV_ID, "Offset": 0, "Limit": 100, "Filters": [{"Name": "DomainType", "Values": ["HTTPSERVICE"]}]})
    domains = route_data.get("Domains")
    if not isinstance(domains, list) or len(domains) != 1:
        raise AdminError("DEFAULT_GATEWAY_UNVERIFIED")
    domain_info = domains[0]
    domain = domain_info.get("Domain", "")
    if not re.fullmatch(re.escape(ENV_ID) + r"-[0-9]+\.ap-shanghai\.app\.tcloudbase\.com", domain):
        raise AdminError("DEFAULT_GATEWAY_UNVERIFIED")
    routes = domain_info.get("Routes") or []
    if not isinstance(routes, list) or len(routes) > 1:
        raise AdminError("GATEWAY_ROUTE_COLLISION")
    route_exists = bool(routes)
    if route_exists:
        route = routes[0]
        if not existing or route.get("Path") != "/" or route.get("UpstreamResourceName") != FUNCTION or route.get("UpstreamResourceType") != "WEB_SCF":
            raise AdminError("GATEWAY_ROUTE_COLLISION")
        if route.get("Enable") is not True or route.get("EnableAuth") is not False or route.get("EnableSafeDomain") is not False or route.get("EnablePathTransmission") is not True:
            raise AdminError("OWNED_ROUTE_CONFIG_UNVERIFIED")
        policy = route.get("QPSPolicy") or {}
        if policy.get("QPSTotal") != 20 or policy.get("QPSPerClient") != {"LimitBy": "ClientIP", "LimitValue": 5}:
            raise AdminError("OWNED_ROUTE_RATE_LIMIT_UNVERIFIED")
    return {
        **free, "function": FUNCTION, "runtime": "Python3.11", "memory_mb": 256,
        "timeout_seconds": 3, "prewarm": False, "gateway_domain": domain,
        "gateway_path": "/", "api_base_url": f"https://{domain}",
        "function_action": "update_owned" if existing else "create",
        "route_action": "retain_owned" if route_exists else "create",
        "gateway_qps_total": 20, "gateway_qps_per_ip": 5,
    }, existing, route_exists


def validate_package(path: Path) -> dict:
    try:
        manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError
        if manifest.get("deployable") is not True or manifest.get("dependencies_included") is not True or manifest.get("runtime") != "Python3.11" or manifest.get("zip_sha256") != sha256(path.read_bytes()):
            raise ValueError
        versions = {item["name"]: item["version"] for item in manifest["packages"]}
        if versions != DEPENDENCIES:
            raise ValueError
        source = collect_source(ROOT / "cloud/api")
        with zipfile.ZipFile(path) as archive:
            total = 0
            names = set()
            for info in archive.infolist():
                member = PurePosixPath(info.filename)
                if info.filename in names or "\\" in info.orig_filename or member.is_absolute() or ".." in member.parts or any(":" in part for part in member.parts) or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError
                names.add(info.filename)
                total += info.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise ValueError
                if info.filename not in source and not info.filename.startswith("third_party/"):
                    raise ValueError
                if any(part in {".env", "tests", "__pycache__"} for part in member.parts):
                    raise ValueError
            if not set(source).issubset(names) or any(archive.read(name) != content for name, content in source.items()):
                raise ValueError
            if stat.S_IMODE(archive.getinfo("scf_bootstrap").external_attr >> 16) != 0o755:
                raise ValueError
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        raise AdminError("PACKAGE_NOT_DEPLOYABLE_OR_STALE") from None
    return {"zip_sha256": manifest["zip_sha256"], "package_bytes": path.stat().st_size}


@contextmanager
def private_config(directory: Path, code: Path, variables: dict[str, str]):
    """Keep secrets outside the uploaded code folder and erase them in finally."""
    handle, filename = tempfile.mkstemp(prefix="private-config-", suffix=".json", dir=directory)
    path = Path(filename)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump({"envId": ENV_ID, "functionRoot": str(code.parent), "functions": [{**function_config(variables), "dir": str(code)}]}, stream)
        os.chmod(path, 0o600)
        yield path
    finally:
        path.unlink(missing_ok=True)


def extract_package(package: Path, destination: Path) -> None:
    # validate_package already rejects unsafe members and bounds expansion.
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            target = destination.joinpath(*PurePosixPath(info.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            os.chmod(target, 0o755 if info.filename == "scf_bootstrap" else 0o644)


def apply_deployment(admin: CloudAdmin, package: Path, plan: dict, existing: bool, route_exists: bool) -> dict:
    package_evidence = validate_package(package)
    fresh, fresh_existing, fresh_route_exists = inspect_resources(admin)
    if fresh != plan or (fresh_existing, fresh_route_exists) != (existing, route_exists):
        raise AdminError("RESOURCE_STATE_CHANGED")
    variables = validate_variables(load_private_environment())
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deploy-", dir=ARTIFACTS) as temporary:
        directory = Path(temporary)
        code = directory / "code"
        code.mkdir()
        extract_package(package, code)
        with private_config(directory, code, variables) as config:
            # The pinned Linux dependencies exceed SCF's 1.5 MB inline ZipFile
            # limit. COS here is the official SCF managed temporary upload,
            # not an application bucket or a newly provisioned storage service.
            command = ["fn", "deploy", FUNCTION, "--config-file", str(config), "--env-id", ENV_ID, "--region", REGION, "--httpFn", "--dir", str(code), "--deployMode", "cos", "--install-dependency", "false", "--json"]
            if existing:
                command.append("--force")
            # No --yes or interactive stdin: payment, upgrades, and unknown
            # confirmation flows must never be automatically accepted.
            result = parse_response(admin.capture(command, timeout=180))
            outcomes = result.get("results", [])
            if result.get("success") is not True or len(outcomes) != 1 or outcomes[0].get("name") != FUNCTION or outcomes[0].get("status") != "success":
                raise AdminError("FUNCTION_DEPLOY_NOT_CONFIRMED")
        if not route_exists:
            data = json.dumps({"domain": plan["gateway_domain"], "routes": [ROUTE]}, separators=(",", ":"))
            parse_response(admin.capture(["routes", "add", "--env-id", ENV_ID, "--region", REGION, "--data", data, "--json"]))
    verified, _, _ = inspect_resources(admin)
    evidence = {**verified, **package_evidence, "status": "deployed_configuration_verified", "health_acceptance": "pending_separate_acceptance"}
    (ARTIFACTS / "deployment-public.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create/update only verified project-owned resources after local acceptance")
    parser.add_argument("--package", type=Path, default=ARTIFACTS / "sc-v2-api.zip")
    arguments = parser.parse_args(argv)
    try:
        admin = CloudAdmin()
        plan, existing, route_exists = inspect_resources(admin)
        result = apply_deployment(admin, arguments.package, plan, existing, route_exists) if arguments.apply else {**plan, "status": "plan_only_no_writes"}
        print(json.dumps(result, sort_keys=True))
    except AdminError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        return 1
    except (OSError, ValueError, zipfile.BadZipFile):
        print(json.dumps({"status": "blocked", "code": "LOCAL_DEPLOYMENT_IO_FAILED"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
