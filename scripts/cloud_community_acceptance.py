"""Independently authorized PC03 acceptance with two existing synthetic accounts.

Default execution is offline. Passwords, tokens, application identities and
content identifiers remain private in memory. Every mutation has a bounded
synthetic target; cleanup preserves soft-withdrawal and role audit history.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
import json
import math
from pathlib import Path
import re
import secrets
import sys
import time
from typing import Any, Literal

import httpx

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from cloud_acceptance import (
    API_BASE, AcceptanceError, FIXTURE_NAME_PATTERN, UID_PATTERN, PrivateHttp,
    SyntheticAccount, existing_fixture_accounts, login, payload, require,
    require_status, reset_fixture_password, revoke, validate_target,
)
from cloud_admin import CloudAdmin, ENV_ID, REGION
from cloud_community_roles import RoleManager
from cloud_community_target import DATABASE_ID, verify_target
from cloud.api.soulcompanion_cloud.auth import AppPrincipal
from cloud.api.soulcompanion_cloud.community.models import (
    OwnedComment, OwnedPost, PublicComment, PublicPost, canonical_id,
)
from cloud.api.soulcompanion_cloud.community.repository import CommunityDocumentRepository
from cloud.api.soulcompanion_cloud.community.service import deterministic_id, idempotency_key
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.repository import CloudBaseDocumentRepository, identity_records


CHECK_NAMES = {
    "actual_target_billing_and_schema_verified", "health_and_anonymous_denial",
    "two_existing_official_principals_verified", "stable_distinct_application_mapping",
    "pc02_nicknames_and_private_family_boundary", "ordinary_accounts_ops_denied",
    "temporary_moderator_grant_verified", "pending_post_private_and_replay",
    "foreign_content_and_identity_input_denied", "current_revision_approval_public_dto",
    "edit_requeues_and_stale_review_conflicts", "age_topic_and_keyset_pagination",
    "comment_pending_approval_and_direct_url", "like_bookmark_idempotent_and_private",
    "content_report_dedup_and_resolution", "hidden_parent_blocks_post_and_comments",
    "synthetic_role_revoked_verified", "synthetic_content_withdrawn_verified",
    "issued_tokens_revoked_private_denied",
}
STAGES = {
    "preflight", "health", "authentication", "identity", "role_grant", "posts",
    "edit", "pagination", "comment", "relations", "reports", "hide", "cleanup", "complete",
}
RoleChange = Callable[[str, str, str, str], dict[str, Any]]


def plan() -> dict[str, Any]:
    return {
        "status": "plan", "env_id": ENV_ID, "region": REGION, "database_id": DATABASE_ID,
        "real_calls": False, "requires": ["--apply", "--cloud-write-authorized"],
        "existing_synthetic_users": 2, "synthetic_users_created": 0,
        "maximum_new_posts": 3, "maximum_new_comments": 1, "maximum_new_reports": 1,
        "temporary_moderators": 1, "new_resources": [], "paid_upgrade": False,
        "destructive_operations": [], "cleanup": ["audited role revoke", "own synthetic withdrawal", "issued token revoke"],
        "retained": ["soft-withdrawn synthetic content", "moderation and role audit", "quota and report history"],
    }


class CommunityHttp(PrivateHttp):
    """Fixed-target HTTP with safe action keys; never retry ambiguous writes."""

    def request(
        self, method: str, url: str, *, token: str = "", body: dict | None = None,
        params: dict | None = None, key: str = "",
    ) -> httpx.Response:
        validate_target(url)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if key:
            try:
                idempotency_key(key)
            except Exception:
                raise AcceptanceError("ACTION_KEY_INVALID") from None
            headers["Idempotency-Key"] = key
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
            self.max_latency_ms = max(self.max_latency_ms, math.ceil((self.clock() - started) * 1000))
            if response.status_code != 429:
                return response
            value = response.headers.get("retry-after", "")
            wait = float(value) if re.fullmatch(r"\d+(?:\.\d+)?", value) else 2 ** attempt
            wait = min(60, max(0.1, wait))
            if attempt == 4 or self.clock() + wait >= deadline:
                raise AcceptanceError("RATE_LIMIT_RETRY_EXHAUSTED")
            self.rate_retries += 1
            self.sleep(wait)
        raise AcceptanceError("RATE_LIMIT_RETRY_EXHAUSTED")


class CommunityAcceptance:
    def __init__(self, admin: CloudAdmin, http: CommunityHttp, role_change: RoleChange) -> None:
        self.admin, self.http, self.role_change = admin, http, role_change
        self.stage = "preflight"
        self.checks: dict[str, bool] = {}
        self.accounts: list[SyntheticAccount] = []
        self.users: list[str] = []
        self.parents: list[dict] = []
        self.nonce = "pc03-" + secrets.token_hex(10)
        self.attempted_content: list[tuple[str, str]] = []
        self.attempted_relations: list[tuple[str, str]] = []
        self.grant_attempted = False
        self.role_cleanup_verified = True
        self.content_cleanup_verified = True
        self.relation_cleanup_verified = True
        self.token_cleanup_failures = 0
        self.verified_token_revocations = 0

    def mark(self, name: str) -> None:
        require(name in CHECK_NAMES, "CHECK_NAME_INVALID")
        self.checks[name] = True

    def api(
        self, method: str, path: str, account: SyntheticAccount | None = None, *,
        body: dict | None = None, params: dict | None = None, key: str = "", status: int = 200,
    ) -> httpx.Response:
        return require_status(self.http.request(
            method, API_BASE + path, token=account.token if account else "",
            body=body, params=params, key=key,
        ), status)

    def content(self, response: httpx.Response, kind: str, *, owned: bool = False) -> dict:
        model = (OwnedPost if owned else PublicPost) if kind == "post" else (OwnedComment if owned else PublicComment)
        record = payload(response)
        try:
            model.model_validate(record)
            canonical_id(record["id"])
            canonical_id(record["author"]["id"])
        except Exception:
            raise AcceptanceError("CONTENT_DTO_INVALID") from None
        author = record["author"]
        require(set(author) == {"id", "nickname"}, "CONTENT_DTO_INVALID")
        require(author == {"id": self.parents[0]["id"], "nickname": self.parents[0]["nickname"]}, "PUBLIC_AUTHOR_INVALID")
        require(author["id"] not in self.users, "PUBLIC_AUTHOR_INVALID")
        return record

    def page(self, response: httpx.Response, *, limit: int, kind: str = "post") -> dict:
        result = payload(response)
        require(set(result) == {"items", "limit", "next_cursor"}, "PAGE_DTO_INVALID")
        require(type(result["limit"]) is int and result["limit"] == limit, "PAGE_DTO_INVALID")
        require(isinstance(result["items"], list) and len(result["items"]) <= limit, "PAGE_DTO_INVALID")
        require(result["next_cursor"] is None or isinstance(result["next_cursor"], str) and 1 <= len(result["next_cursor"]) <= 1024, "PAGE_DTO_INVALID")
        for record in result["items"]:
            try:
                (PublicPost if kind == "post" else PublicComment).model_validate(record)
            except Exception:
                raise AcceptanceError("PAGE_DTO_INVALID") from None
        return result

    def review(self, kind: str, identifier: str, revision: int, action: str, *, suffix: str = "", status: int = 200) -> dict:
        result = payload(self.api(
            "POST", f"/ops/moderation/{kind}s/{identifier}/{action}", self.accounts[1],
            body={"expected_revision": revision, "reason": "PC03 合成验收审核"},
            key=f"{self.nonce}-{action}-{kind}-{suffix or revision}", status=status,
        ))
        if status == 200:
            require(set(result) == {"action_applied", "action_id", "action", "applied_revision", "applied_at", "content"}, "REVIEW_DTO_INVALID")
            require(result["action_applied"] is True and result["action"] == action and result["applied_revision"] == revision, "REVIEW_NOT_CONFIRMED")
            require(result["content"]["id"] == identifier and result["content"]["content_revision"] == revision, "REVIEW_NOT_CONFIRMED")
        return result

    def create_post(self, number: int, *, age: str, topic: str) -> tuple[str, dict, str]:
        key = f"{self.nonce}-post-{number}"
        identifier = deterministic_id("post", self.users[0], key)
        self.attempted_content.append(("post", identifier))
        body = {"title": f"PC03 合成验收帖子 {number}", "body": "PC03 合成验收：无真实儿童或家庭信息。", "age_band": age, "topic": topic}
        record = self.content(self.api("POST", "/community/posts", self.accounts[0], body=body, key=key, status=201), "post", owned=True)
        require(record["id"] == identifier and record["status"] == "pending" and record["content_revision"] == 1, "POST_CREATE_NOT_CONFIRMED")
        return identifier, body, key

    def run(self) -> dict[str, Any]:
        try:
            self._run()
            self.stage = "cleanup"
        finally:
            self._cleanup()
        require(self.role_cleanup_verified and self.content_cleanup_verified and self.relation_cleanup_verified and self.token_cleanup_failures == 0, "CLEANUP_NOT_VERIFIED")
        require(set(self.checks) == CHECK_NAMES, "ACCEPTANCE_INCOMPLETE")
        self.stage = "complete"
        return self.public_evidence("pass")

    def _run(self) -> None:
        verify_target(self.admin.preflight, lambda: self.admin.api("DescribeEnvInfo", {"EnvId": ENV_ID}), error="ACCEPTANCE_TARGET_UNVERIFIED")
        self.stage = "health"
        require(payload(self.api("GET", "/healthz")) == {"status": "ok"})
        require(payload(self.api("GET", "/readyz")) == {"status": "healthy"})
        # Old readyz checks the family API, not the independent PC03 schema.
        # Verify the anonymous production community path before account resets.
        self.page(self.api("GET", "/community/posts", params={"limit": 1}), limit=1)
        self.mark("actual_target_billing_and_schema_verified")
        self.api("GET", "/me", status=401)
        self.api("POST", "/community/posts", body={}, key=self.nonce, status=401)
        require_status(self.http.request("GET", API_BASE + "/me", token="pc03-invalid-synthetic-token"), 401)
        self.mark("health_and_anonymous_denial")
        self.stage = "authentication"
        self.accounts = existing_fixture_accounts(self.admin)
        require(len(self.accounts) == 2 and len({a.uid for a in self.accounts}) == 2 and len({a.username for a in self.accounts}) == 2, "SYNTHETIC_FIXTURE_INVALID")
        require(all(FIXTURE_NAME_PATTERN.fullmatch(a.username) and UID_PATTERN.fullmatch(a.uid) for a in self.accounts), "SYNTHETIC_FIXTURE_INVALID")
        for account in self.accounts:
            reset_fixture_password(self.admin, account)
            login(self.http, account)
        self.mark("two_existing_official_principals_verified")
        self.stage = "identity"
        for account in self.accounts:
            first = payload(self.api("GET", "/me", account))
            identifier = canonical_id(first["id"])
            expected = identity_records(AppPrincipal(account.uid, ENV_ID))[0]["id"]
            require(identifier == expected and payload(self.api("GET", "/me", account))["id"] == identifier, "APPLICATION_IDENTITY_INVALID")
            self.users.append(identifier)
            parent = payload(self.api("GET", "/parent-profile", account))
            require(set(parent) == {"id", "nickname", "created_at", "updated_at"}, "PARENT_DTO_INVALID")
            canonical_id(parent["id"])
            require(isinstance(parent["nickname"], str) and 2 <= len(parent["nickname"]) <= 24, "PARENT_DTO_INVALID")
            self.parents.append(parent)
            children = payload(self.api("GET", "/children", account))
            require(isinstance(children.get("items"), list), "PRIVATE_FAMILY_API_INVALID")
            self.api("GET", "/ops/moderation", account, status=403)
        require(len(set(self.users)) == 2 and len({parent["id"] for parent in self.parents}) == 2, "APPLICATION_IDENTITY_INVALID")
        self.mark("stable_distinct_application_mapping")
        self.mark("pc02_nicknames_and_private_family_boundary")
        self.mark("ordinary_accounts_ops_denied")
        a, b = self.accounts
        self.stage = "role_grant"
        self.grant_attempted = True
        self.role_cleanup_verified = False
        result = self.role_change(self.users[1], "grant", "PC03 合成验收临时运营", self.nonce + "-grant")
        require(result.get("status") == "pass" and result.get("role_status") == "active" and result.get("action_applied") is True, "ROLE_GRANT_UNCONFIRMED")
        self.api("GET", "/ops/moderation", b)
        self.api("GET", "/ops/moderation", a, status=403)
        self.mark("temporary_moderator_grant_verified")
        self.stage = "posts"
        p1, original, key = self.create_post(1, age="6-8", topic="parent-child")
        replay = self.content(self.api("POST", "/community/posts", a, body=original, key=key), "post", owned=True)
        require(replay["id"] == p1 and replay["content_revision"] == 1, "POST_REPLAY_INVALID")
        self.api("GET", f"/community/posts/{p1}", status=404)
        require(all(item["id"] != p1 for item in self.page(self.api("GET", "/community/posts"), limit=20)["items"]), "PENDING_CONTENT_PUBLIC")
        self.content(self.api("GET", f"/me/community/posts/{p1}", a), "post", owned=True)
        self.mark("pending_post_private_and_replay")
        self.api("GET", f"/me/community/posts/{p1}", b, status=404)
        self.api("PATCH", f"/community/posts/{p1}", b, body={**original, "expected_revision": 1}, status=404)
        self.api("POST", "/community/posts", a, body={**original, "owner_id": self.users[1]}, key=self.nonce + "-bad-owner", status=422)
        require(self.content(self.api("GET", f"/me/community/posts/{p1}", a), "post", owned=True)["content_revision"] == 1, "DENIED_WRITE_CHANGED_POST")
        self.mark("foreign_content_and_identity_input_denied")
        self.review("post", p1, 1, "approve", suffix="first")
        require(self.content(self.api("GET", f"/community/posts/{p1}"), "post")["body"] == original["body"], "PUBLIC_POST_NOT_CONFIRMED")
        self.mark("current_revision_approval_public_dto")
        self.stage = "edit"
        edited = {**original, "body": "PC03 合成验收：修改后必须重新审核。", "expected_revision": 1}
        record = self.content(self.api("PATCH", f"/community/posts/{p1}", a, body=edited), "post", owned=True)
        require(record["status"] == "pending" and record["content_revision"] == 2, "EDIT_NOT_REQUEUED")
        self.api("GET", f"/community/posts/{p1}", status=404)
        self.review("post", p1, 1, "approve", suffix="stale", status=409)
        require(self.content(self.api("GET", f"/me/community/posts/{p1}", a), "post", owned=True)["status"] == "pending", "STALE_REVIEW_PUBLISHED")
        self.review("post", p1, 2, "approve", suffix="edited")
        require(self.content(self.api("GET", f"/community/posts/{p1}"), "post")["body"] == edited["body"], "EDIT_PUBLIC_NOT_CONFIRMED")
        self.mark("edit_requeues_and_stale_review_conflicts")
        self.stage = "pagination"
        p2, _, _ = self.create_post(2, age="6-8", topic="daily-habits")
        self.review("post", p2, 1, "approve", suffix="second")
        p3, _, _ = self.create_post(3, age="9-12", topic="parent-child")
        self.review("post", p3, 1, "approve", suffix="third")
        first = self.page(self.api("GET", "/community/posts", params={"age_band": "6-8", "limit": 1}), limit=1)
        require(len(first["items"]) == 1 and first["items"][0]["id"] == p2 and first["next_cursor"] is not None, "KEYSET_FIRST_PAGE_INVALID")
        second = self.page(self.api("GET", "/community/posts", params={"age_band": "6-8", "limit": 1, "cursor": first["next_cursor"]}), limit=1)
        require(len(second["items"]) == 1 and second["items"][0]["id"] == p1, "KEYSET_SECOND_PAGE_INVALID")
        require(first["items"][0]["published_at"] >= second["items"][0]["published_at"], "KEYSET_SORT_INVALID")
        combined = self.page(self.api("GET", "/community/posts", params={"age_band": "6-8", "topic": "parent-child", "limit": 5}), limit=5)
        require(p1 in {item["id"] for item in combined["items"]} and all(item["age_band"] == "6-8" and item["topic"] == "parent-child" for item in combined["items"]), "COMBINED_FILTER_INVALID")
        require(p2 not in {item["id"] for item in combined["items"]} and p3 not in {item["id"] for item in combined["items"]}, "COMBINED_FILTER_INVALID")
        self.api("GET", "/community/posts", params={"age_band": "9-12", "limit": 1, "cursor": first["next_cursor"]}, status=422)
        self.mark("age_topic_and_keyset_pagination")
        self.stage = "comment"
        comment_key = self.nonce + "-comment"
        comment_id = deterministic_id("comment", self.users[0], comment_key)
        self.attempted_content.append(("comment", comment_id))
        comment = self.content(self.api("POST", f"/community/posts/{p1}/comments", a, body={"body": "PC03 合成验收评论。"}, key=comment_key, status=201), "comment", owned=True)
        require(comment["id"] == comment_id and comment["status"] == "pending", "COMMENT_CREATE_INVALID")
        self.api("GET", f"/community/comments/{comment_id}", status=404)
        require(all(item["id"] != comment_id for item in self.page(self.api("GET", f"/community/posts/{p1}/comments"), limit=20, kind="comment")["items"]), "PENDING_COMMENT_PUBLIC")
        self.review("comment", comment_id, 1, "approve")
        self.content(self.api("GET", f"/community/comments/{comment_id}"), "comment")
        require(comment_id in {item["id"] for item in self.page(self.api("GET", f"/community/posts/{p1}/comments"), limit=20, kind="comment")["items"]}, "COMMENT_LIST_INVALID")
        self.mark("comment_pending_approval_and_direct_url")
        self.stage = "relations"
        for kind in ("like", "bookmark"):
            self.attempted_relations.append((p1, kind))
            for _ in range(2):
                result = payload(self.api("PUT", f"/community/posts/{p1}/{kind}", a, body={}))
                require(result == {"post_id": p1, "kind": kind, "active": True}, "RELATION_NOT_CONFIRMED")
        require(p1 in {item["id"] for item in self.page(self.api("GET", "/me/community/bookmarks", a), limit=20)["items"]}, "BOOKMARK_NOT_VISIBLE")
        require(p1 not in {item["id"] for item in self.page(self.api("GET", "/me/community/bookmarks", b), limit=20)["items"]}, "BOOKMARK_OWNER_LEAK")
        for kind in ("like", "bookmark"):
            for _ in range(2):
                require(payload(self.api("DELETE", f"/community/posts/{p1}/{kind}", a)) == {"post_id": p1, "kind": kind, "active": False}, "RELATION_CANCEL_NOT_CONFIRMED")
        self.mark("like_bookmark_idempotent_and_private")
        self.stage = "reports"
        report_body = {"target_type": "post", "target_id": p1, "reason": "other", "detail": "PC03 合成验收举报。"}
        report = payload(self.api("POST", "/community/content-reports", a, body=report_body, key=self.nonce + "-report", status=201))
        require(set(report) == {"id", "target_type", "target_id", "target_revision", "reason", "detail", "status", "created_at", "handled_at"}, "REPORT_DTO_INVALID")
        canonical_id(report["id"])
        require(report["target_revision"] == 2 and report["status"] == "open", "REPORT_NOT_CONFIRMED")
        duplicate = payload(self.api("POST", "/community/content-reports", a, body=report_body, key=self.nonce + "-report-other-key"))
        require(duplicate == report, "REPORT_DEDUP_INVALID")
        self.api("GET", "/ops/content-reports", a, status=403)
        result = payload(self.api("POST", f"/ops/content-reports/{report['id']}/resolve", b, body={"expected_revision": 1, "decision": "resolved", "reason": "PC03 合成验收已处理"}, key=self.nonce + "-resolve"))
        require(result.get("action_applied") is True and result["report"]["id"] == report["id"] and result["report"]["status"] == "resolved" and result["report"]["report_revision"] == 2, "REPORT_RESOLUTION_UNCONFIRMED")
        self.mark("content_report_dedup_and_resolution")
        self.stage = "hide"
        self.review("post", p1, 2, "hide")
        for path in (f"/community/posts/{p1}", f"/community/posts/{p1}/comments", f"/community/comments/{comment_id}"):
            self.api("GET", path, status=404)
        self.mark("hidden_parent_blocks_post_and_comments")

    def _withdraw(self, kind: str, identifier: str) -> bool:
        account = self.accounts[0]
        path = f"/me/community/{kind}s/{identifier}"
        for _ in range(2):
            response = self.http.request("GET", API_BASE + path, token=account.token)
            if response.status_code == 404:
                return True  # Deterministic attempted create was never committed.
            record = self.content(require_status(response, 200), kind, owned=True)
            require(record["id"] == identifier, "CLEANUP_TARGET_INVALID")
            if record["status"] == "deleted":
                return True
            response = self.http.request("DELETE", API_BASE + f"/community/{kind}s/{identifier}", token=account.token, params={"expected_revision": record["content_revision"]})
            require_status(response, 204, 409, 503)
            # Even a 204 is confirmed by the next read. A 503 may have committed;
            # recovery reads the known ID before considering another revision.
        record = self.content(self.api("GET", path, account), kind, owned=True)
        return record["id"] == identifier and record["status"] == "deleted"

    def _cleanup(self) -> None:
        if self.grant_attempted:
            try:
                result = self.role_change(self.users[1], "revoke", "PC03 合成验收撤销临时运营", self.nonce + "-revoke")
                require(result.get("status") == "pass" and result.get("role_status") in {"revoked", "absent"}, "ROLE_REVOKE_UNCONFIRMED")
                self.api("GET", "/ops/moderation", self.accounts[1], status=403)
                self.role_cleanup_verified = True
                self.mark("synthetic_role_revoked_verified")
            except Exception:
                self.role_cleanup_verified = False
        for identifier, kind in self.attempted_relations:
            try:
                response = self.http.request("DELETE", API_BASE + f"/community/posts/{identifier}/{kind}", token=self.accounts[0].token)
                if response.status_code == 404:
                    self.api("GET", f"/community/posts/{identifier}", status=404)
                else:
                    require(payload(require_status(response, 200)) == {"post_id": identifier, "kind": kind, "active": False}, "RELATION_CLEANUP_UNCONFIRMED")
            except Exception:
                self.relation_cleanup_verified = False
        for kind, identifier in reversed(self.attempted_content):
            try:
                require(self._withdraw(kind, identifier), "CONTENT_CLEANUP_UNCONFIRMED")
            except Exception:
                self.content_cleanup_verified = False
        if self.attempted_content and self.content_cleanup_verified:
            self.mark("synthetic_content_withdrawn_verified")
        for account in self.accounts:
            if account.token:
                try:
                    issued = account.token
                    revoke(self.http, account)
                    for path in ("/me/community/posts", "/parent-profile", "/children", "/ops/moderation"):
                        require_status(self.http.request("GET", API_BASE + path, token=issued), 401)
                    self.verified_token_revocations += 1
                except Exception:
                    self.token_cleanup_failures += 1
        if self.verified_token_revocations == 2 and self.token_cleanup_failures == 0 and all(not account.token for account in self.accounts):
            self.mark("issued_tokens_revoked_private_denied")

    def public_evidence(self, status: Literal["pass", "failed"]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": status, "env_id": ENV_ID, "region": REGION,
            "stage": self.stage if self.stage in STAGES else "unknown",
            "checks": {name: True for name in sorted(CHECK_NAMES) if self.checks.get(name) is True},
            "synthetic_users_created": 0, "attempted_synthetic_posts": sum(kind == "post" for kind, _ in self.attempted_content),
            "attempted_synthetic_comments": sum(kind == "comment" for kind, _ in self.attempted_content),
            "role_cleanup_verified": self.role_cleanup_verified is True,
            "content_cleanup_verified": self.content_cleanup_verified is True,
            "relations_inactive_or_nonpublic_verified": self.relation_cleanup_verified is True,
            "token_cleanup_verified": self.token_cleanup_failures == 0 and all(not account.token for account in self.accounts),
        }
        for name, value in (("requests", self.http.requests), ("rate_limit_retries", self.http.rate_retries), ("max_request_latency_ms", self.http.max_latency_ms)):
            if type(value) is int and value >= 0:
                result[name] = value
        if status == "failed":
            result["code"] = "PC03_ACCEPTANCE_FAILED"
        return result


def real_role_change(admin: CloudAdmin, api_key: str) -> RoleChange:
    def change(principal: str, action: str, reason: str, key: str) -> dict[str, Any]:
        async def execute() -> dict[str, Any]:
            async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
                family = CloudBaseDocumentRepository(Settings(env_id=ENV_ID, api_key=api_key), client)
                async def lookup(identifier: str) -> dict | None:
                    return await family._find_one("users", {"_id": identifier, "id": identifier, "status": "active"})
                manager = RoleManager(CommunityDocumentRepository(family), lookup, admin.preflight, lambda: admin.api("DescribeEnvInfo", {"EnvId": ENV_ID}))
                return await manager.change(principal, action, reason, key, cloud_write_authorized=True)
        return asyncio.run(execute())
    return change


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cloud-write-authorized", action="store_true")
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps(plan(), sort_keys=True))
        return 0
    if not args.cloud_write_authorized:
        print(json.dumps({"status": "blocked", "code": "PC03_CLOUD_WRITE_AUTHORIZATION_REQUIRED", "real_calls": False}))
        return 1
    runner = None
    try:
        from cloud_admin import load_private_environment
        api_key = load_private_environment().get("CLOUDBASE_APIKEY")
        require(bool(api_key), "SERVER_API_KEY_REQUIRED")
        admin = CloudAdmin()
        with httpx.Client(follow_redirects=False, trust_env=False) as client:
            runner = CommunityAcceptance(admin, CommunityHttp(client, sleep=time.sleep), real_role_change(admin, api_key))
            result = runner.run()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # Responses, exception messages and credential-bearing objects never
        # cross the result boundary, even after an ambiguous write or cleanup.
        result = runner.public_evidence("failed") if runner else {"status": "failed", "code": "PC03_ACCEPTANCE_FAILED", "stage": "initialization", "checks": {}}
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
