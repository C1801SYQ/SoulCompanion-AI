"""Captured official CLI calls; only sanitized summaries may leave this module."""

import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ENV_ID = "soulcompanion-dev-d0dzo6f2a24211"
REGION = "ap-shanghai"
PRIVATE_ENV = ROOT / ".test-artifacts/cloudbase-phase04/.env"
CLI_ENTRY = ROOT / ".test-artifacts/cloudbase-cli/node_modules/@cloudbase/cli/dist/standalone/cli.js"
READ_ACTIONS = {"DescribeEnvInfo", "DescribeBillingInfo", "ListTables", "DescribeTable", "DescribeDatabaseACL", "GetProviders", "DescribeHTTPServiceRoute", "DescribeEnvAccountCircle", "DescribeCreditsUsageDetail"}
WRITE_ACTIONS = {"CreateTable", "UpdateTable", "ModifyDatabaseACL", "CreateApiKey"}


class AdminError(RuntimeError):
    """Contains an operation and a sanitized code, never an upstream message."""


def parse_response(output: str) -> dict:
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end < start:
        raise AdminError("CLI_INVALID_RESPONSE")
    try:
        data = json.loads(clean[start:end + 1])
        data = data.get("data", data)
        data = data.get("Response", data)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, AttributeError):
        raise AdminError("CLI_INVALID_RESPONSE") from None
    error = data.get("Error") or data.get("error")
    if error:
        code = (error.get("Code") or error.get("code") or "CLOUD_API_ERROR") if isinstance(error, dict) else "CLOUD_API_ERROR"
        safe_code = code if re.fullmatch(r"[A-Za-z0-9_.]{1,100}", str(code)) else "CLOUD_API_ERROR"
        raise AdminError(safe_code)
    return data


class CloudAdmin:
    def __init__(self, cli_entry: Path = CLI_ENTRY):
        self.cli_entry = cli_entry

    def capture(self, args: list[str], *, timeout: int = 60) -> str:
        if not self.cli_entry.is_file():
            raise AdminError("CLI_NOT_INSTALLED")
        try:
            result = subprocess.run(["node", str(self.cli_entry), *args], input="", capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=ROOT)
        except (OSError, subprocess.TimeoutExpired):
            raise AdminError("CLI_UNAVAILABLE") from None
        output = result.stdout + "\n" + result.stderr
        if result.returncode:
            # Parse only the structured error code. Never include captured text.
            try:
                parse_response(output)
            except AdminError:
                raise
            raise AdminError("CLI_OPERATION_FAILED")
        return output

    def api(self, action: str, body: dict, *, write: bool = False) -> dict:
        if action not in (READ_ACTIONS | WRITE_ACTIONS if write else READ_ACTIONS):
            raise AdminError("ACTION_NOT_ALLOWED")
        if body.get("EnvId") != ENV_ID:
            raise AdminError("WRONG_ENVIRONMENT")
        # This public-parameter path cannot put credentials in a process argument.
        encoded = json.dumps(body, separators=(",", ":"))
        if re.search(r'"(?:password|secret|secretid|secretkey|clientsecret|apikey|access_token|refresh_token)"\s*:', encoded, re.I):
            raise AdminError("SECRET_ARGUMENT_FORBIDDEN")
        return parse_response(self.capture(["api", "tcb", action, "--region", REGION,
                                           "--api-version", "2018-06-08", "--body", encoded, "--json"]))

    def preflight(self) -> dict:
        info = self.api("DescribeEnvInfo", {"EnvId": ENV_ID})
        env = info.get("EnvInfo", {}).get("EnvBaseInfo", {})
        if env.get("EnvId") != ENV_ID or env.get("Status") != "NORMAL":
            raise AdminError("ENVIRONMENT_NOT_READY")
        billing = self.api("DescribeBillingInfo", {"EnvId": ENV_ID})
        matches = [item for item in billing.get("EnvBillingInfoList", []) if item.get("EnvId") == ENV_ID]
        if len(matches) != 1:
            raise AdminError("BILLING_NOT_VERIFIED")
        bill = matches[0]
        if bill.get("PackageId") != "baas_trial" or bill.get("EnableOverrun") is not False or bill.get("IsAutoRenew") is not False:
            raise AdminError("PAID_RESOURCE_REQUIRED_OR_BILLING_UNVERIFIED")
        databases = env.get("Databases", [])
        running = [db for db in databases if db.get("Status") == "RUNNING"]
        if len(running) != 1 or not running[0].get("InstanceId"):
            raise AdminError("EXISTING_DATABASE_NOT_READY")
        return {"env_id": ENV_ID, "region": REGION, "package_id": "baas_trial", "overrun": False,
                "auto_renew": False, "database_id": running[0]["InstanceId"]}


def load_private_environment(path: Path = PRIVATE_ENV) -> dict[str, str]:
    """Ignored local file, read without interpolating values into commands/logs."""
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name in {"CLOUDBASE_APIKEY", "CLOUDBASE_ENV_ID", "CLOUD_ALLOWED_ORIGINS"}:
                values[name] = value
    for name in ("CLOUDBASE_APIKEY", "CLOUDBASE_ENV_ID", "CLOUD_ALLOWED_ORIGINS"):
        if os.environ.get(name):
            values[name] = os.environ[name]
    if values.get("CLOUDBASE_ENV_ID", ENV_ID) != ENV_ID:
        raise AdminError("WRONG_ENVIRONMENT")
    return values


if __name__ == "__main__":
    try:
        print(json.dumps(CloudAdmin().preflight(), sort_keys=True))
    except AdminError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        raise SystemExit(1) from None
