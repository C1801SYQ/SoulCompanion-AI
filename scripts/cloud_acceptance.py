"""Explicit real-cloud acceptance; generated credentials stay in process memory.

The default is a public plan. --apply creates exactly two synthetic development
users, or --reuse-fixtures privately resets the two existing owned test users.
Runs leave archived metadata for an auditable, non-destructive acceptance.
No production user, collection, environment, or existing record is deleted.
"""

import argparse
from dataclasses import dataclass, field
import json
import math
import re
import secrets
import string
import subprocess
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from cloud_admin import AdminError, CLI_ENTRY, CloudAdmin, ENV_ID, REGION, ROOT, parse_response


API_BASE = (
    f"https://{ENV_ID}-1501181209.ap-shanghai.app.tcloudbase.com/api/v2"
)
CLOUDBASE_BASE = f"https://{ENV_ID}.api.tcloudbasegateway.com"
DATABASE_DENIAL_PATH = (
    "/v1/database/instances/(default)/databases/(default)"
    "/collections/sc_v2_users/documents"
)
PRIVATE_CLI_BOOTSTRAP = (
    "const fs=require('node:fs');const p=JSON.parse(fs.readFileSync(0,'utf8'));"
    "process.argv=[process.execPath,p.entry,...p.args];"
    "require('node:module').runMain();"
)
NAME_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{5,63}\Z")
FIXTURE_NAME_PATTERN = re.compile(r"scphase04_[a-f0-9]{20}\Z")
UID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,512}\Z")


class AcceptanceError(RuntimeError):
    """Fixed codes only; never construct these from private upstream messages."""


@dataclass(repr=False)
class SyntheticAccount:
    username: str
    password: str = field(repr=False)
    uid: str = field(default="", repr=False)
    token: str = field(default="", repr=False)


def new_account() -> SyntheticAccount:
    username = "scphase04_" + secrets.token_hex(10)
    # The official internal-user password policy is 8..32 characters, starts
    # with a letter, and requires at least three character categories.
    password = (
        "A" + "".join(secrets.choice(string.ascii_uppercase) for _ in range(8))
        + "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
        + "".join(secrets.choice(string.digits) for _ in range(8)) + "!"
    )
    return SyntheticAccount(username, password)


def validate_target(url: str) -> None:
    """Credentials can reach only the two owner-confirmed HTTPS destinations."""
    if any(character.isspace() for character in url):
        raise AcceptanceError("UNAPPROVED_TARGET")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise AcceptanceError("UNAPPROVED_TARGET") from None
    api = urlsplit(API_BASE)
    cloudbase = urlsplit(CLOUDBASE_BASE)
    if (
        parsed.scheme != "https" or parsed.username or parsed.password
        or parsed.fragment or port not in (None, 443)
    ):
        raise AcceptanceError("UNAPPROVED_TARGET")
    if parsed.hostname == api.hostname:
        if parsed.path == "/api/v2" or parsed.path.startswith("/api/v2/"):
            return
    if parsed.hostname == cloudbase.hostname:
        if parsed.path in {
            "/auth/v1/signin", "/auth/v1/token/introspect",
            "/auth/v1/user/signout", DATABASE_DENIAL_PATH,
        }:
            return
    raise AcceptanceError("UNAPPROVED_TARGET")


def create_account(admin: CloudAdmin, account: SyntheticAccount) -> None:
    admin.preflight()
    if not NAME_PATTERN.fullmatch(account.username):
        raise AcceptanceError("SYNTHETIC_USERNAME_INVALID")
    if not admin.cli_entry.is_file():
        raise AcceptanceError("CLI_NOT_INSTALLED")
    args = [
        "user", "create", account.username, "--env-id", ENV_ID,
        "--type", "internalUser", "--status", "ACTIVE",
        "--password", account.password, "--json",
    ]
    private_input = json.dumps({"entry": str(admin.cli_entry), "args": args})
    try:
        captured = subprocess.run(
            ["node", "-e", PRIVATE_CLI_BOOTSTRAP], input=private_input,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=ROOT,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AcceptanceError("SYNTHETIC_USER_CREATE_UNAVAILABLE") from None
    # Whole output remains private, including on failure. CLI main() sees the
    # password in its memory argv, never in the operating system's process argv.
    try:
        data = parse_response(captured.stdout + "\n" + captured.stderr)
    except AdminError:
        raise AcceptanceError("SYNTHETIC_USER_CREATE_REJECTED") from None
    uid = data.get("Data", {}).get("Uid")
    if captured.returncode or not isinstance(uid, str) or not 1 <= len(uid) <= 512:
        raise AcceptanceError("SYNTHETIC_USER_CREATE_INVALID")
    account.uid = uid


def existing_fixture_accounts(admin: CloudAdmin) -> list[SyntheticAccount]:
    """Select the exact two owned fixtures; the full user list stays private."""
    admin.preflight()
    try:
        output = admin.capture([
            "user", "list", "--env-id", ENV_ID, "--region", REGION,
            "--limit", "100", "--offset", "0", "--json",
        ])
    except AdminError:
        raise AcceptanceError("SYNTHETIC_FIXTURE_LIST_UNAVAILABLE") from None
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    try:
        start, end = clean.index("{"), clean.rindex("}")
        result = json.loads(clean[start:end + 1])
        records, meta = result["data"], result["meta"]
        if not isinstance(records, list) or not isinstance(meta, dict):
            raise ValueError
        if (type(meta.get("total")) is not int or meta["total"] != len(records)
                or len(records) > 100 or type(meta.get("limit")) is not int
                or meta["limit"] != 100
                or type(meta.get("offset")) is not int or meta["offset"] != 0):
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AcceptanceError("SYNTHETIC_FIXTURE_LIST_INVALID") from None
    selected, seen_uids, seen_names = [], set(), set()
    for record in records:
        if not isinstance(record, dict):
            raise AcceptanceError("SYNTHETIC_FIXTURE_LIST_INVALID")
        uid, name = record.get("Uid"), record.get("Name")
        if (not isinstance(uid, str) or not UID_PATTERN.fullmatch(uid)
                or uid in seen_uids or not isinstance(name, str)):
            raise AcceptanceError("SYNTHETIC_FIXTURE_LIST_INVALID")
        seen_uids.add(uid)
        if not name.startswith("scphase04_"):
            continue
        if not FIXTURE_NAME_PATTERN.fullmatch(name) or name in seen_names:
            raise AcceptanceError("SYNTHETIC_FIXTURE_LIST_INVALID")
        seen_names.add(name)
        selected.append((name, uid))
    if len(selected) != 2:
        raise AcceptanceError("SYNTHETIC_FIXTURE_COUNT_INVALID")
    accounts = []
    # A retains archived metadata while B must remain empty across repeated runs.
    # Provider listing order must never swap those acceptance roles.
    for name, uid in sorted(selected):
        account = new_account()
        account.username, account.uid = name, uid
        accounts.append(account)
    return accounts


def reset_fixture_password(admin: CloudAdmin, account: SyntheticAccount) -> None:
    admin.preflight()
    if (not FIXTURE_NAME_PATTERN.fullmatch(account.username)
            or not UID_PATTERN.fullmatch(account.uid)):
        raise AcceptanceError("SYNTHETIC_FIXTURE_INVALID")
    if not admin.cli_entry.is_file():
        raise AcceptanceError("CLI_NOT_INSTALLED")
    args = [
        "user", "update", account.uid, "--env-id", ENV_ID, "--region", REGION,
        "--password", account.password, "--json",
    ]
    try:
        captured = subprocess.run(
            ["node", "-e", PRIVATE_CLI_BOOTSTRAP],
            input=json.dumps({"entry": str(admin.cli_entry), "args": args}),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=ROOT,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AcceptanceError("SYNTHETIC_FIXTURE_RESET_UNAVAILABLE") from None
    try:
        parse_response(captured.stdout + "\n" + captured.stderr)
    except AdminError:
        raise AcceptanceError("SYNTHETIC_FIXTURE_RESET_REJECTED") from None
    if captured.returncode:
        raise AcceptanceError("SYNTHETIC_FIXTURE_RESET_INVALID")


class PrivateHttp:
    def __init__(self, client, *, sleep=time.sleep, clock=time.monotonic):
        self.client, self.sleep, self.clock = client, sleep, clock
        self.requests = 0
        self.rate_retries = 0
        self.max_latency_ms = 0

    def request(self, method, url, *, token="", body=None, params=None):
        validate_target(url)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        deadline = self.clock() + 180
        for attempt in range(5):
            started = self.clock()
            try:
                response = self.client.request(
                    method, url, headers=headers, json=body, params=params,
                    timeout=12, follow_redirects=False,
                )
            except httpx.HTTPError:
                raise AcceptanceError("HTTP_UNAVAILABLE") from None
            self.requests += 1
            self.max_latency_ms = max(
                self.max_latency_ms, math.ceil((self.clock() - started) * 1000)
            )
            if response.status_code != 429:
                # Never replay an ambiguous mutating timeout or 5xx response.
                return response
            value = response.headers.get("retry-after", "")
            wait = float(value) if re.fullmatch(r"\d+(?:\.\d+)?", value) else 2 ** attempt
            wait = min(60, max(0.1, wait))
            if attempt == 4 or self.clock() + wait >= deadline:
                raise AcceptanceError("RATE_LIMIT_RETRY_EXHAUSTED")
            self.rate_retries += 1
            self.sleep(wait)
        raise AcceptanceError("RATE_LIMIT_RETRY_EXHAUSTED")


def require_status(response, *statuses):
    if response.status_code not in statuses:
        raise AcceptanceError("UNEXPECTED_HTTP_STATUS")
    return response


def payload(response):
    try:
        result = response.json()
    except ValueError:
        raise AcceptanceError("INVALID_HTTP_RESPONSE") from None
    if not isinstance(result, dict):
        raise AcceptanceError("INVALID_HTTP_RESPONSE")
    return result


def require(condition, code="ACCEPTANCE_ASSERTION_FAILED"):
    if not condition:
        raise AcceptanceError(code)


def login(http: PrivateHttp, account: SyntheticAccount):
    response = require_status(http.request(
        "POST", CLOUDBASE_BASE + "/auth/v1/signin",
        body={"username": account.username, "password": account.password},
    ), 200)
    data = payload(response)
    token = data.get("access_token")
    if not token and isinstance(data.get("session"), dict):
        token = data["session"].get("access_token")
    if not isinstance(token, str) or not token or len(token) > 16384 or re.search(r"\s", token):
        raise AcceptanceError("AUTH_RESPONSE_INVALID")
    # Keep an issued token reachable for cleanup even if introspection fails.
    account.token = token
    try:
        verified = payload(require_status(http.request(
            "GET", CLOUDBASE_BASE + "/auth/v1/token/introspect", token=token,
        ), 200))
        require(verified.get("sub") == account.uid and verified.get("client_id") == ENV_ID
                and verified.get("token_type") == "Bearer", "AUTH_PRINCIPAL_MISMATCH")
    except Exception:
        try:
            revoke(http, account)
        except Exception:
            # Acceptance.run() makes another bounded cleanup attempt and reports
            # a failed cleanup without exposing this private provider response.
            pass
        raise


def revoke(http: PrivateHttp, account: SyntheticAccount):
    require_status(http.request(
        "POST", CLOUDBASE_BASE + "/auth/v1/user/signout", token=account.token, body={},
    ), 200, 204)
    require_status(http.request("GET", API_BASE + "/me", token=account.token), 401)
    account.token = ""


def run_browser(account: SyntheticAccount) -> dict:
    try:
        captured = subprocess.run(
            ["node", str(ROOT / "scripts/cloud_browser.cjs"), "--apply"],
            input=json.dumps({"username": account.username, "password": account.password}),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=240, cwd=ROOT,
        )
        result = json.loads(captured.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise AcceptanceError("BROWSER_ACCEPTANCE_UNAVAILABLE") from None
    # Never echo a child response or stderr. Reconstruct an allowlisted result.
    checks = result.get("checks", {})
    expected = {
        "guest_private_requests_absent", "official_sdk_login", "me_ui_loaded",
        "profile_created", "profile_renamed", "profile_selected",
        "profile_archived", "logout_hides_private_data", "token_revoked",
        "auth_storage_absent", "automatic_device_acquisition_absent",
        "raw_media_requests_absent",
    }
    if captured.returncode or result.get("status") != "pass" or set(checks) != expected:
        raise AcceptanceError("BROWSER_ACCEPTANCE_FAILED")
    if any(checks[name] is not True for name in expected):
        raise AcceptanceError("BROWSER_ACCEPTANCE_FAILED")
    return {"status": "pass", "checks": {name: True for name in sorted(expected)}}


class Acceptance:
    def __init__(self, admin, http: PrivateHttp):
        self.admin, self.http = admin, http
        self.stage = "preflight"
        self.checks = {}
        self.accounts = []
        self.cleanup_failures = 0

    def mark(self, name):
        self.checks[name] = True

    def api(self, method, path, account=None, *, body=None, params=None, status=200):
        return require_status(self.http.request(
            method, API_BASE + path, token=account.token if account else "",
            body=body, params=params,
        ), status)

    def run(self, *, browser=False, reuse_fixtures=False):
        try:
            return self._run(browser=browser, reuse_fixtures=reuse_fixtures)
        finally:
            for account in self.accounts:
                if account.token:
                    try:
                        revoke(self.http, account)
                    except Exception:
                        # Preserve the failed acceptance stage and still try the
                        # other account. Only the boolean cleanup result is public.
                        self.cleanup_failures += 1

    def _run(self, *, browser=False, reuse_fixtures=False):
        self.admin.preflight()
        self.stage = "health_and_anonymous"
        require(payload(self.api("GET", "/healthz")).get("status") == "ok")
        require(payload(self.api("GET", "/readyz")).get("status") == "healthy")
        self.api("GET", "/me", status=401)
        self.mark("health_ready_anonymous_denial")
        self.stage = "synthetic_authentication"
        self.accounts = (existing_fixture_accounts(self.admin) if reuse_fixtures
                         else sorted([new_account(), new_account()],
                                     key=lambda account: account.username))
        a, b = self.accounts
        prepare_account = reset_fixture_password if reuse_fixtures else create_account
        prepare_account(self.admin, a)
        prepare_account(self.admin, b)
        login(self.http, a)
        login(self.http, b)
        self.mark("two_official_cloudbase_principals_verified")
        self.stage = "profile_and_session_metadata"
        me_a, me_b = payload(self.api("GET", "/me", a)), payload(self.api("GET", "/me", b))
        require(me_a["id"] != me_b["id"])
        require(payload(self.api("GET", "/me", a))["id"] == me_a["id"])
        display_name = "Synthetic Phase04 fixture"
        updated_me = payload(self.api("PATCH", "/me", a, body={"display_name": display_name}))
        require(updated_me["display_name"] == display_name)
        require(payload(self.api("GET", "/me", a))["display_name"] == display_name)
        self.mark("application_users_distinct_and_stable")
        child = payload(self.api("POST", "/children", a, body={"nickname": "Synthetic API fixture"}, status=201))
        child_id = child["id"]
        require(child["status"] == "active")
        renamed = payload(self.api("PATCH", f"/children/{child_id}", a, body={"nickname": "Synthetic renamed fixture"}))
        require(renamed["nickname"] == "Synthetic renamed fixture")
        require(payload(self.api("GET", f"/children/{child_id}", a))["nickname"] == renamed["nickname"])
        listing = payload(self.api("GET", "/children", a))
        require(any(item["id"] == child_id for item in listing["items"]))
        self.mark("profile_create_read_update_list")
        session = payload(self.api("POST", "/sessions", a, body={"child_profile_id": child_id, "source_platform": "web"}, status=201))
        session_id = session["id"]
        require(session["status"] == "active" and session["ended_at"] is None)
        require(payload(self.api("GET", f"/sessions/{session_id}", a))["id"] == session_id)
        require(any(item["id"] == session_id for item in payload(self.api("GET", "/sessions", a, params={"child_profile_id": child_id}))["items"]))
        ended = payload(self.api("POST", f"/sessions/{session_id}/end", a, body={}))
        again = payload(self.api("POST", f"/sessions/{session_id}/end", a, body={}))
        require(ended["status"] == "ended" and ended["ended_at"] and again["ended_at"] == ended["ended_at"])
        self.mark("session_create_read_list_end_idempotent")
        self.stage = "ownership_and_input_boundaries"
        for path in ("/children", "/sessions"):
            require(payload(self.api("GET", path, b))["items"] == [])
        unknown = str(uuid4())
        for method, foreign, missing, body in [
            ("GET", f"/children/{child_id}", f"/children/{unknown}", None),
            ("PATCH", f"/children/{child_id}", f"/children/{unknown}", {"nickname": "Synthetic forbidden"}),
            ("DELETE", f"/children/{child_id}", f"/children/{unknown}", None),
            ("GET", f"/sessions/{session_id}", f"/sessions/{unknown}", None),
            ("POST", f"/sessions/{session_id}/end", f"/sessions/{unknown}/end", {}),
        ]:
            found = payload(self.api(method, foreign, b, body=body, status=404))
            absent = payload(self.api(method, missing, b, body=body, status=404))
            require(found["error"]["code"] == absent["error"]["code"]
                    and found["error"]["message"] == absent["error"]["message"])
        for path in ("/sessions", "/emotions", "/reports", "/reports/current"):
            found = payload(self.api("GET", path, b, params={"child_profile_id": child_id}, status=404))
            absent = payload(self.api("GET", path, b, params={"child_profile_id": unknown}, status=404))
            require(found["error"]["code"] == absent["error"]["code"]
                    and found["error"]["message"] == absent["error"]["message"])
        self.api("POST", "/sessions", b, body={"child_profile_id": child_id, "source_platform": "web"}, status=404)
        self.mark("foreign_and_unknown_resources_uniform_404")
        for forbidden in (
            {"owner_user_id": me_a["id"]}, {"uid": a.uid}, {"openid": "synthetic"},
            {"camera_frame": "synthetic"}, {"audio_chunk": "synthetic"},
            {"device_id": "synthetic"}, {"$where": "synthetic"},
        ):
            self.api("POST", "/children", a, body={"nickname": "Synthetic rejected", **forbidden}, status=422)
        self.mark("owner_raw_media_and_operator_fields_rejected")
        denied = self.http.request("GET", CLOUDBASE_BASE + DATABASE_DENIAL_PATH, token=a.token, params={"count": "true"})
        require_status(denied, 401, 403)
        self.mark("direct_client_database_access_denied")
        for path in ("/emotions", "/reports"):
            require(payload(self.api("GET", path, a, params={"child_profile_id": child_id}))["items"] == [])
        report = payload(self.api("GET", "/reports/current", a, params={"child_profile_id": child_id}))
        require(report == {"status": "empty", "report": None})
        self.mark("no_fabricated_emotions_or_reports")
        self.stage = "archive_and_revocation"
        self.api("DELETE", f"/children/{child_id}", a, status=204)
        self.api("DELETE", f"/children/{child_id}", a, status=204)
        require(payload(self.api("GET", f"/children/{child_id}", a))["status"] == "archived")
        require(all(item["id"] != child_id for item in payload(self.api("GET", "/children", a))["items"]))
        self.api("POST", "/sessions", a, body={"child_profile_id": child_id, "source_platform": "web"}, status=409)
        self.mark("profile_archive_idempotent_and_new_sessions_rejected")
        revoke(self.http, a)
        revoke(self.http, b)
        self.mark("signed_out_access_tokens_rejected")
        browser_result = None
        if browser:
            self.stage = "official_sdk_browser"
            browser_result = run_browser(a)
        self.stage = "complete"
        return {
            "status": "pass", "env_id": ENV_ID, "api_base_url": API_BASE,
            "checks": self.checks, "browser": browser_result,
            "requests": self.http.requests, "rate_limit_retries": self.http.rate_retries,
            "max_request_latency_ms": self.http.max_latency_ms,
            "fixture_mode": "reuse" if reuse_fixtures else "create",
            "fixture": "Two synthetic development users; no real personal or media data",
            "retained": "Synthetic users and application identities; archived profile and ended session metadata",
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--reuse-fixtures", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"status": "plan", "env_id": ENV_ID, "api_base_url": API_BASE,
                          "synthetic_users": 2, "real_calls": False,
                          "fixture_mode": "reuse" if args.reuse_fixtures else "create",
                          "browser_requested": args.browser, "destructive_operations": []}))
        return 0
    acceptance = None
    try:
        with httpx.Client(follow_redirects=False, trust_env=False) as client:
            acceptance = Acceptance(CloudAdmin(CLI_ENTRY), PrivateHttp(client))
            result = acceptance.run(browser=args.browser, reuse_fixtures=args.reuse_fixtures)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # Exception text and chained contexts may contain request credentials.
        # A fixed stage code is enough to locate a failing acceptance check.
        failure = {"status": "failed", "code": "CLOUD_ACCEPTANCE_FAILED",
                   "stage": acceptance.stage if acceptance else "initialization",
                   "checks": acceptance.checks if acceptance else {}}
        if acceptance and acceptance.accounts:
            failure["api_token_cleanup_verified"] = (
                acceptance.cleanup_failures == 0
                and all(not account.token for account in acceptance.accounts)
            )
        print(json.dumps(failure))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
