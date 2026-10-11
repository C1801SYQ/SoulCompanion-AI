"""PC04 official-SDK UI acceptance; offline until independently authorized.

Only the two existing owned synthetic accounts are eligible. Browser action
attempts are acknowledged over private pipes before writes, so cleanup retains
deterministic targets even after lost replies, browser failure or timeout.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cloud_acceptance import (
    API_BASE, CLOUDBASE_BASE, AcceptanceError, SyntheticAccount,
    existing_fixture_accounts, login, payload, require, require_status,
    reset_fixture_password, revoke,
)
from cloud_admin import CloudAdmin, ENV_ID, REGION
from cloud_community_acceptance import CommunityHttp, RoleChange, real_role_change
from cloud_community_target import DATABASE_ID, verify_target
from cloud.api.soulcompanion_cloud.auth import AppPrincipal
from cloud.api.soulcompanion_cloud.community.models import canonical_id
from cloud.api.soulcompanion_cloud.community.service import content_report_id, deterministic_id, idempotency_key
from cloud.api.soulcompanion_cloud.repository import identity_records


BROWSER_CHECKS = {
    "official_sdk_two_account_login", "guest_private_and_device_boundary",
    "parent_public_nickname_ui", "post_pending_not_public", "operator_post_approval_ui",
    "public_post_and_filter_ui", "comment_pending_then_approved_ui",
    "confirmed_like_bookmark_ui", "report_and_independent_resolution_ui",
    "own_withdrawal_and_public_unavailable_ui", "logout_clears_private_ui",
    "auth_storage_absent", "no_external_family_or_media_requests",
}
CHECKS = BROWSER_CHECKS | {
    "actual_target_billing_verified", "existing_synthetic_mapping_verified",
    "temporary_moderator_revoked", "synthetic_content_withdrawn",
    "synthetic_report_resolved_or_absent", "relations_inactive_or_nonpublic",
    "synthetic_nicknames_restored", "issued_tokens_revoked",
}
EventHandler = Callable[[dict[str, Any]], None]
BrowserRunner = Callable[[list[SyntheticAccount], list[str], str, EventHandler], dict[str, Any]]
SYNTHETIC_POST = {"title": "PC04 合成验收：晚饭后的聊天",
    "body": "PC04 合成验收内容：完全虚构，不含真实儿童、学校或家庭信息。", "age_band": "6-8", "topic": "parent-child"}
SYNTHETIC_COMMENT = {"body": "PC04 合成验收评论：仅用于软件验证，无真实儿童信息。"}
SYNTHETIC_REPORT_DETAIL = "PC04 合成验收举报，不代表真实内容风险。"


def plan() -> dict[str, Any]:
    return {
        "status": "plan", "real_calls": False, "env_id": ENV_ID, "region": REGION,
        "database_id": DATABASE_ID, "requires": ["--apply", "--cloud-write-authorized"],
        "existing_synthetic_users": 2, "synthetic_users_created": 0,
        "maximum_new_posts": 1, "maximum_new_comments": 1, "maximum_new_reports": 1,
        "temporary_moderators": 1, "official_sdk": True, "new_resources": [],
        "schema_changes": [], "paid_upgrade": False, "destructive_operations": [],
        "private_input": "acknowledged stdin/stdout pipes only; no artifacts or credentials printed",
        "ambiguous_create_settlement": "exact original synthetic input and key; at most one deterministic object per kind",
        "cleanup": ["resolve own synthetic report", "own synthetic soft withdrawal",
                    "deactivate own synthetic relations or confirm hidden parent", "restore synthetic nicknames",
                    "audited temporary-role revoke", "all observed issued-token revoke"],
    }


def validate_browser_build() -> None:
    """Reject a missing/stale official snapshot before loading cloud credentials."""
    try:
        result = subprocess.run(["node", str(ROOT / "scripts/cloud_community_browser.cjs"), "--verify-build"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, cwd=ROOT)
        require(result.returncode == 0 and json.loads(result.stdout) == {
            "status": "ready", "real_calls": False, "official_sdk": True}, "OFFICIAL_H5_BUILD_REQUIRED")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise AcceptanceError("OFFICIAL_H5_BUILD_REQUIRED") from None


def run_browser(accounts: list[SyntheticAccount], users: list[str], nonce: str, event: EventHandler) -> dict[str, Any]:
    """Never echo child output; ACK a validated ledger entry before network continuation."""
    env = {key: value for key, value in os.environ.items()
           if not re.search(r"SECRET|TOKEN|APIKEY|API_KEY|PASSWORD|TENCENTCLOUD|TENCENT_SECRET", key, re.I)}
    env["PC04_PRIVATE_PROTOCOL"] = "1"
    child = subprocess.Popen(
        ["node", str(ROOT / "scripts/cloud_community_browser.cjs"), "--apply", "--cloud-write-authorized", "--private-protocol"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", cwd=ROOT, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    require(child.stdin is not None and child.stdout is not None and child.stderr is not None, "PRIVATE_PIPE_UNAVAILABLE")
    lines: queue.Queue[str | None] = queue.Queue(maxsize=128)

    def read_stdout() -> None:
        for line in child.stdout:
            lines.put(line)
        lines.put(None)

    def discard_stderr() -> None:
        # Playwright/library errors can contain credentials. Discard, do not log.
        for _ in child.stderr:
            pass

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=discard_stderr, daemon=True).start()
    result = None
    try:
        child.stdin.write(json.dumps({"nonce": nonce, "users": users,
            "accounts": [{"username": account.username, "password": account.password} for account in accounts]}) + "\n")
        child.stdin.flush()
        deadline, count = time.monotonic() + 600, 0
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if line is None:
                break
            count += 1
            require(count <= 120 and len(line) <= 65536, "PRIVATE_PROTOCOL_INVALID")
            message = json.loads(line)
            require(isinstance(message, dict), "PRIVATE_PROTOCOL_INVALID")
            if message.get("type") == "event":
                require(set(message) == {"type", "sequence", "event"} and type(message["sequence"]) is int
                        and message["sequence"] == count, "PRIVATE_PROTOCOL_INVALID")
                event(message["event"])
                child.stdin.write(json.dumps({"ack": message["sequence"]}) + "\n")
                child.stdin.flush()
            elif message.get("type") == "result":
                require(result is None and set(message) == {"type", "result"}, "PRIVATE_PROTOCOL_INVALID")
                result = message["result"]
            else:
                raise AcceptanceError("PRIVATE_PROTOCOL_INVALID")
        else:
            raise AcceptanceError("BROWSER_ACCEPTANCE_TIMEOUT")
        child.wait(timeout=15)
        require(child.returncode == 0 and isinstance(result, dict) and result.get("status") == "pass"
                and set(result.get("checks", {})) == BROWSER_CHECKS
                and all(value is True for value in result["checks"].values()), "BROWSER_ACCEPTANCE_FAILED")
        return {"status": "pass", "checks": {name: True for name in sorted(BROWSER_CHECKS)}}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise AcceptanceError("BROWSER_ACCEPTANCE_FAILED") from None
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream:
                stream.close()


class IntegrationAcceptance:
    def __init__(self, admin: CloudAdmin, http: CommunityHttp, role_change: RoleChange,
                 browser: BrowserRunner = run_browser) -> None:
        self.admin, self.http, self.role_change, self.browser = admin, http, role_change, browser
        self.accounts: list[SyntheticAccount] = []
        self.users: list[str] = []
        self.parents: list[dict] = []
        self.nonce = "pc04-" + secrets.token_hex(10)
        self.stage = "preflight"
        self.checks: dict[str, bool] = {}
        self.attempted_content: dict[str, tuple[str, int, str]] = {}
        self.attempted_payloads: dict[str, dict[str, Any]] = {}
        self.report_id: str | None = None
        self.report_key: str | None = None
        self.report_body: dict[str, Any] | None = None
        self.relations: set[str] = set()
        self.browser_tokens: dict[str, int] = {}
        self.grant_attempted = False
        self.grant_confirmed = False
        self.nickname_attempts: set[int] = set()
        self.nickname_settled: set[int] = set()
        self.cleanup_failures = 0

    def api(self, method: str, path: str, account: int | None = None, **kwargs: Any) -> httpx.Response:
        return self.http.request(method, API_BASE + path,
            token=self.accounts[account].token if account is not None else "", **kwargs)

    def event(self, value: dict[str, Any]) -> None:
        """Validate and record a bounded synthetic attempt before acknowledging it."""
        require(isinstance(value, dict) and type(value.get("account")) is int
                and value["account"] in (0, 1), "PRIVATE_EVENT_INVALID")
        account = value["account"]
        kind = value.get("kind")
        if kind == "token":
            require(set(value) == {"kind", "account", "token"} and isinstance(value["token"], str)
                    and 1 <= len(value["token"]) <= 16384 and not re.search(r"\s", value["token"]), "PRIVATE_EVENT_INVALID")
            require(len(self.browser_tokens) < 12 or value["token"] in self.browser_tokens, "PRIVATE_EVENT_BOUND_EXCEEDED")
            require(value["token"] not in self.browser_tokens or self.browser_tokens[value["token"]] == account, "PRIVATE_EVENT_INVALID")
            # Retain an issued opaque token before any potentially failing
            # introspection. An unverified token never receives an ACK.
            self.browser_tokens[value["token"]] = account
            principal = payload(require_status(self.http.request("GET", CLOUDBASE_BASE + "/auth/v1/token/introspect", token=value["token"]), 200))
            require(principal.get("sub") == self.accounts[account].uid and principal.get("client_id") == ENV_ID
                    and principal.get("token_type") == "Bearer", "PRIVATE_TOKEN_PRINCIPAL_INVALID")
        elif kind in {"post", "comment"}:
            fields = {"kind", "account", "key", "body"} | ({"post_id"} if kind == "comment" else set())
            require(set(value) == fields and account == (0 if kind == "post" else 1)
                    and value["body"] == (SYNTHETIC_POST if kind == "post" else SYNTHETIC_COMMENT), "PRIVATE_EVENT_INVALID")
            if kind == "comment":
                require(self.attempted_content.get(value["post_id"], (None,))[0] == "post", "PRIVATE_EVENT_INVALID")
            key = idempotency_key(value["key"])
            identifier = deterministic_id(kind, self.users[account], key)
            existing = [target for target, (target_kind, _, _) in self.attempted_content.items() if target_kind == kind]
            require(not existing or existing == [identifier], "PRIVATE_EVENT_BOUND_EXCEEDED")
            self.attempted_content[identifier] = (kind, account, key)
            self.attempted_payloads[identifier] = {**value["body"], **({"post_id": value["post_id"]} if kind == "comment" else {})}
        elif kind == "report":
            require(set(value) == {"kind", "account", "key", "target_id", "body"} and account == 1, "PRIVATE_EVENT_INVALID")
            idempotency_key(value["key"])
            require(self.attempted_content.get(value["target_id"], (None,))[0] == "post", "PRIVATE_EVENT_INVALID")
            require(value["body"] == {"target_type": "post", "target_id": value["target_id"],
                "reason": "privacy", "detail": SYNTHETIC_REPORT_DETAIL}, "PRIVATE_EVENT_INVALID")
            identifier = content_report_id(self.users[1], "post", value["target_id"], 1)
            require(self.report_id in (None, identifier), "PRIVATE_EVENT_BOUND_EXCEEDED")
            self.report_id = identifier
            if self.report_key is None:
                self.report_key, self.report_body = value["key"], dict(value["body"])
        elif kind == "relation":
            require(set(value) == {"kind", "account", "relation", "target_id"} and account == 1
                    and value["relation"] in {"like", "bookmark"}
                    and self.attempted_content.get(value["target_id"], (None,))[0] == "post", "PRIVATE_EVENT_INVALID")
            self.relations.add(value["relation"])
        elif kind == "nickname":
            require(set(value) == {"kind", "account"}, "PRIVATE_EVENT_INVALID")
            self.nickname_attempts.add(account)
        elif kind == "nickname_settled":
            require(set(value) == {"kind", "account"} and account in self.nickname_attempts, "PRIVATE_EVENT_INVALID")
            self.nickname_settled.add(account)
        else:
            raise AcceptanceError("PRIVATE_EVENT_INVALID")

    def run(self) -> dict[str, Any]:
        try:
            self._run()
        finally:
            self.stage = "cleanup"
            self._cleanup()
        require(self.cleanup_failures == 0 and set(self.checks) == CHECKS, "PC04_ACCEPTANCE_INCOMPLETE")
        self.stage = "complete"
        return self.public_evidence("pass")

    def _run(self) -> None:
        verify_target(self.admin.preflight, lambda: self.admin.api("DescribeEnvInfo", {"EnvId": ENV_ID}), error="PC04_TARGET_UNVERIFIED")
        require_status(self.api("GET", "/community/posts", params={"limit": 1}), 200)
        self.checks["actual_target_billing_verified"] = True
        self.stage = "authentication"
        self.accounts = existing_fixture_accounts(self.admin)
        require(len(self.accounts) == 2 and len({account.uid for account in self.accounts}) == 2, "SYNTHETIC_FIXTURE_INVALID")
        for account in self.accounts:
            reset_fixture_password(self.admin, account)
            login(self.http, account)
            identifier = canonical_id(payload(require_status(self.http.request("GET", API_BASE + "/me", token=account.token), 200))["id"])
            require(identifier == identity_records(AppPrincipal(account.uid, ENV_ID))[0]["id"], "APPLICATION_IDENTITY_INVALID")
            self.users.append(identifier)
            parent = payload(require_status(self.api("GET", "/parent-profile", len(self.users) - 1), 200))
            require(set(parent) == {"id", "nickname", "created_at", "updated_at"}
                    and isinstance(parent["nickname"], str) and 2 <= len(parent["nickname"]) <= 24, "PARENT_DTO_INVALID")
            self.parents.append(parent)
            require_status(self.api("GET", "/ops/moderation", len(self.users) - 1), 403)
        require(len(set(self.users)) == 2, "APPLICATION_IDENTITY_INVALID")
        self.checks["existing_synthetic_mapping_verified"] = True
        self.stage = "role_grant"
        self.grant_attempted = True
        result = self.role_change(self.users[1], "grant", "PC04 合成界面验收临时运营", self.nonce + "-grant")
        require(result.get("status") == "pass" and result.get("role_status") == "active"
                and result.get("action_applied") is True, "ROLE_GRANT_UNCONFIRMED")
        self.grant_confirmed = True
        self.stage = "official_sdk_ui"
        result = self.browser(self.accounts, self.users, self.nonce, self.event)
        require(result.get("status") == "pass" and set(result.get("checks", {})) == BROWSER_CHECKS
                and all(value is True for value in result["checks"].values()), "BROWSER_ACCEPTANCE_FAILED")
        self.checks.update({name: True for name in BROWSER_CHECKS})

    def _guard_cleanup(self, name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
            self.checks[name] = True
        except Exception:
            self.cleanup_failures += 1

    def _withdraw(self, identifier: str, kind: str, account: int) -> None:
        for _ in range(5):
            response = self.api("GET", f"/me/community/{kind}s/{identifier}", account)
            if response.status_code == 404:
                # An ACKed POST can outlive its browser connection. Absence is
                # not settlement. Replaying the exact immutable input/key first
                # creates or reads one deterministic record; subsequent late
                # replays return its tombstone and cannot revive withdrawn data.
                body = self.attempted_payloads[identifier]
                key = self.attempted_content[identifier][2]
                path = "/community/posts" if kind == "post" else f"/community/posts/{body['post_id']}/comments"
                wire_body = {name: value for name, value in body.items() if name != "post_id"}
                replay = self.api("POST", path, account, body=wire_body, key=key)
                if replay.status_code == 503:
                    continue
                record = payload(require_status(replay, 200, 201))
                require(record.get("id") == identifier, "CLEANUP_TARGET_INVALID")
                continue
            record = payload(require_status(response, 200))
            require(record.get("id") == identifier, "CLEANUP_TARGET_INVALID")
            if record.get("status") == "deleted":
                require_status(self.api("GET", f"/community/{kind}s/{identifier}"), 404)
                return
            require(type(record.get("content_revision")) is int and record["content_revision"] > 0, "CLEANUP_TARGET_INVALID")
            require_status(self.api("DELETE", f"/community/{kind}s/{identifier}", account,
                params={"expected_revision": record["content_revision"]}), 204, 409, 503)
        raise AcceptanceError("CONTENT_CLEANUP_UNCONFIRMED")

    def _report_cleanup(self) -> None:
        if self.report_id is None:
            return
        response = self.api("POST", f"/ops/content-reports/{self.report_id}/resolve", 1,
            body={"expected_revision": 1, "decision": "resolved", "reason": "PC04 合成验收撤销清理；不隐藏内容"}, key=self.nonce + "-report-cleanup")
        if response.status_code == 404:
            # Settle the original report before resolving it. A hidden parent
            # may block replay; then cleanup is explicitly unverified, not PASS.
            target_id = (self.report_body or {}).get("target_id")
            target = payload(require_status(self.api("GET", f"/me/community/posts/{target_id}", 0), 200))
            require(target.get("id") == target_id and target.get("status") == "published"
                    and target.get("content_revision") == 1, "REPORT_CLEANUP_UNCONFIRMED")
            replay = payload(require_status(self.api("POST", "/community/content-reports", 1,
                body=self.report_body, key=self.report_key or ""), 200, 201))
            require(replay.get("id") == self.report_id and replay.get("target_id") == target_id
                    and replay.get("target_revision") == 1, "REPORT_CLEANUP_UNCONFIRMED")
            response = self.api("POST", f"/ops/content-reports/{self.report_id}/resolve", 1,
                body={"expected_revision": 1, "decision": "resolved", "reason": "PC04 合成验收撤销清理；不隐藏内容"}, key=self.nonce + "-report-cleanup")
        if response.status_code == 200:
            report = payload(response).get("report", {})
            require(report.get("id") == self.report_id and report.get("status") == "resolved", "REPORT_CLEANUP_UNCONFIRMED")
            return
        require_status(response, 404, 409, 503)
        for status in ("open", "resolved", "dismissed"):
            cursor = None
            for _ in range(3):
                page = payload(require_status(self.api("GET", "/ops/content-reports", 1,
                    params={"status": status, "limit": 50, **({"cursor": cursor} if cursor else {})}), 200))
                require(isinstance(page.get("items"), list), "REPORT_CLEANUP_UNCONFIRMED")
                if any(item.get("id") == self.report_id for item in page["items"]):
                    require(status != "open", "REPORT_CLEANUP_UNCONFIRMED")
                    return
                cursor = page.get("next_cursor")
                if cursor is None:
                    break
            else:
                raise AcceptanceError("REPORT_CLEANUP_BOUND_EXCEEDED")
        raise AcceptanceError("REPORT_CLEANUP_UNCONFIRMED")

    def _cleanup(self) -> None:
        # An SDK logout can revoke other sessions depending on provider policy.
        # Reauthenticate only these already-selected fixtures for bounded cleanup.
        for account in self.accounts:
            if account.token:
                try:
                    response = self.http.request("GET", API_BASE + "/me", token=account.token)
                    if response.status_code == 401:
                        login(self.http, account)
                    else:
                        require_status(response, 200)
                except Exception:
                    self.cleanup_failures += 1
        self._guard_cleanup("synthetic_report_resolved_or_absent", self._report_cleanup)
        post_id = next((identifier for identifier, (kind, _, _) in self.attempted_content.items() if kind == "post"), None)

        def relations() -> None:
            for kind in self.relations:
                response = self.api("DELETE", f"/community/posts/{post_id}/{kind}", 1)
                if response.status_code == 404:
                    require_status(self.api("GET", f"/community/posts/{post_id}"), 404)
                else:
                    require(payload(require_status(response, 200)) == {"post_id": post_id, "kind": kind, "active": False}, "RELATION_CLEANUP_UNCONFIRMED")

        self._guard_cleanup("relations_inactive_or_nonpublic", relations)

        def content() -> None:
            failed = False
            for identifier, (kind, account, _) in reversed(list(self.attempted_content.items())):
                try:
                    self._withdraw(identifier, kind, account)
                except Exception:
                    failed = True
            require(not failed, "CONTENT_CLEANUP_UNCONFIRMED")

        self._guard_cleanup("synthetic_content_withdrawn", content)

        def nicknames() -> None:
            failed = False
            for account in self.nickname_attempts:
                try:
                    result = payload(require_status(self.api("PUT", "/parent-profile", account, body={"nickname": self.parents[account]["nickname"]}), 200))
                    require(result.get("nickname") == self.parents[account]["nickname"], "NICKNAME_RESTORE_UNCONFIRMED")
                except Exception:
                    failed = True
            require(not failed, "NICKNAME_RESTORE_UNCONFIRMED")
            # PC02 nickname updates have no CAS. A missing successful original
            # receipt leaves a possible late overwrite even after restoration.
            require(self.nickname_attempts <= self.nickname_settled, "NICKNAME_SETTLEMENT_UNCONFIRMED")

        self._guard_cleanup("synthetic_nicknames_restored", nicknames)

        def role() -> None:
            if not self.grant_attempted:
                return
            settled = self.grant_confirmed
            if not settled:
                try:
                    replay = self.role_change(self.users[1], "grant", "PC04 合成界面验收临时运营", self.nonce + "-grant")
                    settled = replay.get("status") == "pass" and replay.get("action_applied") is True
                except Exception:
                    settled = False
            # Always attempt revocation, including when same-key settlement is
            # unavailable. An unconfirmed grant remains a cleanup failure.
            result = self.role_change(self.users[1], "revoke", "PC04 合成界面验收撤销临时运营", self.nonce + "-revoke")
            require(result.get("status") == "pass" and result.get("role_status") in {"revoked", "absent"}, "ROLE_REVOKE_UNCONFIRMED")
            require_status(self.api("GET", "/ops/moderation", 1), 403)
            require(settled, "ROLE_SETTLEMENT_UNCONFIRMED")

        self._guard_cleanup("temporary_moderator_revoked", role)

        def tokens() -> None:
            failed = False
            for token, account_index in self.browser_tokens.items():
                try:
                    # A UI logout may already have revoked this token. Verify first.
                    response = self.http.request("GET", API_BASE + "/me", token=token)
                    if response.status_code != 401:
                        principal = payload(require_status(self.http.request("GET", CLOUDBASE_BASE + "/auth/v1/token/introspect", token=token), 200))
                        require(principal.get("sub") == self.accounts[account_index].uid and principal.get("client_id") == ENV_ID
                                and principal.get("token_type") == "Bearer", "PRIVATE_TOKEN_PRINCIPAL_INVALID")
                        require_status(self.http.request("POST", CLOUDBASE_BASE + "/auth/v1/user/signout", token=token, body={}), 200, 204)
                        require_status(self.http.request("GET", API_BASE + "/me", token=token), 401)
                except Exception:
                    failed = True
            for account in self.accounts:
                if account.token:
                    try:
                        if self.http.request("GET", API_BASE + "/me", token=account.token).status_code == 401:
                            account.token = ""
                        else:
                            revoke(self.http, account)
                    except Exception:
                        failed = True
                account.password = ""
            require(not failed, "TOKEN_CLEANUP_UNCONFIRMED")
            self.browser_tokens.clear()

        self._guard_cleanup("issued_tokens_revoked", tokens)

    def public_evidence(self, status: str) -> dict[str, Any]:
        return {"status": status, "stage": self.stage if self.stage in {"preflight", "authentication", "role_grant", "official_sdk_ui", "cleanup", "complete"} else "unknown",
            "code": "PC04_ACCEPTANCE_PASS" if status == "pass" else "PC04_ACCEPTANCE_FAILED",
            "checks": {name: True for name in sorted(CHECKS) if self.checks.get(name) is True},
            "synthetic_users_created": 0, "attempted_synthetic_posts": sum(kind == "post" for kind, _, _ in self.attempted_content.values()),
            "attempted_synthetic_comments": sum(kind == "comment" for kind, _, _ in self.attempted_content.values()),
            "attempted_synthetic_reports": int(self.report_id is not None), "cleanup_failures": self.cleanup_failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cloud-write-authorized", action="store_true")
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps(plan(), sort_keys=True))
        return 0
    if not args.cloud_write_authorized:
        print(json.dumps({"status": "blocked", "code": "PC04_CLOUD_WRITE_AUTHORIZATION_REQUIRED", "real_calls": False}))
        return 1
    runner = None
    try:
        validate_browser_build()
        from cloud_admin import load_private_environment
        api_key = load_private_environment().get("CLOUDBASE_APIKEY")
        require(bool(api_key), "SERVER_API_KEY_REQUIRED")
        admin = CloudAdmin()
        with httpx.Client(follow_redirects=False, trust_env=False) as client:
            runner = IntegrationAcceptance(admin, CommunityHttp(client, sleep=time.sleep), real_role_change(admin, api_key))
            result = runner.run()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps(runner.public_evidence("failed") if runner else {
            "status": "failed", "code": "PC04_ACCEPTANCE_FAILED", "stage": "initialization", "checks": {}}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
