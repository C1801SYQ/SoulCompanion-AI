"""Real acceptance is guarded; behavioral coverage uses local HTTP and Fake SDK."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cloud_acceptance as common
import cloud_community_acceptance as acceptance
import cloud_community_roles as roles

from cloud.api.soulcompanion_cloud.app import create_app
from cloud.api.soulcompanion_cloud.auth import AppPrincipal
from cloud.api.soulcompanion_cloud.community.repository import InMemoryCommunityRepository
from cloud.api.soulcompanion_cloud.community.service import validate_role
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError
from cloud.api.soulcompanion_cloud.repository import InMemoryRepository, identity_records


@pytest.mark.parametrize("arguments", [[], ["--cloud-write-authorized"]])
def test_offline_plan_uses_no_cloud_credentials_cli_or_client(monkeypatch, capsys, arguments):
    monkeypatch.setattr(acceptance, "CloudAdmin", lambda: pytest.fail("cloud admin created"))
    monkeypatch.setattr(acceptance.httpx, "Client", lambda **_: pytest.fail("network initialized"))
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: pytest.fail("CLI executed"))
    import cloud_admin
    monkeypatch.setattr(cloud_admin, "load_private_environment", lambda: pytest.fail("private environment loaded"))
    assert acceptance.main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "plan" and result["real_calls"] is False
    assert result["synthetic_users_created"] == 0 and result["existing_synthetic_users"] == 2
    assert result["new_resources"] == result["destructive_operations"] == []


def test_apply_missing_independent_authorization_has_zero_calls(monkeypatch, capsys):
    monkeypatch.setattr(acceptance, "CloudAdmin", lambda: pytest.fail("cloud admin created"))
    monkeypatch.setattr(acceptance.httpx, "Client", lambda **_: pytest.fail("network initialized"))
    assert acceptance.main(["--apply"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "blocked", "code": "PC03_CLOUD_WRITE_AUTHORIZATION_REQUIRED", "real_calls": False,
    }


class LocalRun:
    def __init__(self, monkeypatch, failure=None):
        self.failure = failure
        self.accounts = [common.SyntheticAccount("scphase04_" + name * 20, "PrivateSynthetic123!", uid="private-synthetic-uid-" + name) for name in "ab"]
        self.valid_tokens = {}
        self.requests = []
        self.resets = []
        self.role_changes = []
        self.store = InMemoryCommunityRepository()
        self.family = InMemoryRepository(family_identity_enabled=True)
        for account in self.accounts:
            owner = identity_records(AppPrincipal(account.uid, common.ENV_ID))[0]["id"]
            asyncio.run(self.family.save_parent_profile(owner, "PC02合成家长"))
        state = self

        class Verifier:
            async def verify(self, token):
                if token not in state.valid_tokens:
                    raise CloudError(401, "unauthorized", "Please sign in again.")
                return AppPrincipal(state.valid_tokens[token], common.ENV_ID)

            async def ready(self):
                return True

        self.api = TestClient(create_app(Settings(private_rate_limit=1000, preauth_rate_limit=1000), self.family, Verifier(), self.store))
        monkeypatch.setattr(acceptance, "existing_fixture_accounts", lambda _: self.accounts)
        monkeypatch.setattr(acceptance, "reset_fixture_password", self.reset)
        monkeypatch.setattr(common, "create_account", lambda *_: pytest.fail("new cloud auth account created"))
        self.audit = {"env_id": common.ENV_ID, "region": common.REGION, "package_id": "baas_trial", "overrun": False, "auto_renew": False, "database_id": acceptance.DATABASE_ID}
        self.environment = {"EnvInfo": {"EnvBaseInfo": {"EnvId": common.ENV_ID, "Region": common.REGION, "Status": "NORMAL", "Databases": [{"InstanceId": acceptance.DATABASE_ID, "Status": "RUNNING"}]}}}

    def preflight(self):
        return deepcopy(self.audit)

    def admin_api(self, operation, params):
        assert operation == "DescribeEnvInfo" and params == {"EnvId": common.ENV_ID}
        return deepcopy(self.environment)

    def reset(self, _admin, account):
        self.resets.append(account.username)

    def role_change(self, principal, action, reason, key):
        self.role_changes.append((principal, action, reason, key))
        async def lookup(identifier):
            return deepcopy(self.family.users.get(identifier))
        manager = roles.RoleManager(self.store, lookup, self.preflight, lambda: self.environment)
        if self.failure == "role_revoke_failed" and action == "revoke":
            raise RuntimeError("private-role-exception-token")
        result = asyncio.run(manager.change(principal, action, reason, key, cloud_write_authorized=True))
        if self.failure == "role_grant_ack_lost" and action == "grant":
            raise RuntimeError("private-role-exception-token")
        return result

    def transport(self, request):
        self.requests.append(request)
        if request.url.host == httpx.URL(common.API_BASE).host:
            if self.failure == "schema_unready" and request.url.path == "/api/v2/community/posts" and request.method == "GET":
                return httpx.Response(503, json={"private": "private-synthetic-token-a"})
            response = self.api.request(request.method, request.url.path, params=request.url.params, headers=request.headers, content=request.content)
            data = response.json() if response.content else None
            if self.failure == "wrong_identity" and request.url.path == "/api/v2/me" and response.status_code == 200:
                data["id"] = "00000000-0000-4000-8000-000000000001"
            if self.failure == "parent_private_leak" and request.url.path.endswith("/parent-profile") and response.status_code == 200:
                data["owner_user_id"] = "private-synthetic-uid-a"
            if self.failure == "b_already_moderator" and request.url.path == "/api/v2/ops/moderation" and request.headers.get("authorization", "").endswith("-b") and not self.role_changes and response.status_code == 403:
                return httpx.Response(200, json={"items": [], "limit": 20, "next_cursor": None})
            if self.failure == "create_ack_lost" and request.url.path == "/api/v2/community/posts" and request.method == "POST" and response.status_code == 201:
                return httpx.Response(503, json={"private": "private-upstream-message"})
            if self.failure == "public_owner_leak" and "/community/posts/" in request.url.path and "/me/" not in request.url.path and request.method == "GET" and response.status_code == 200 and isinstance(data, dict) and "title" in data:
                data["owner_id"] = "private-synthetic-uid-a"
            if self.failure == "stale_review_not_conflicting" and request.url.path.endswith("/approve") and response.status_code == 409:
                return httpx.Response(200, json={"private": "not-conflicting"})
            if self.failure == "combined_filter_not_and" and request.url.path == "/api/v2/community/posts" and request.method == "GET" and "topic" in request.url.params and response.status_code == 200:
                data["items"][0]["age_band"] = "9-12"
            if self.failure == "hidden_comment_public" and "/community/comments/" in request.url.path and "/me/" not in request.url.path and request.method == "GET" and response.status_code == 404 and self.runner.stage == "hide":
                return httpx.Response(200, json={"private": "hidden comment"})
            if self.failure == "withdraw_ack_lost" and request.method == "DELETE" and response.status_code == 204 and "/community/posts/" in request.url.path:
                return httpx.Response(503, json={"private": "private-upstream"})
            if self.failure == "content_cleanup_unavailable" and request.method == "GET" and "/me/community/" in request.url.path and self.runner.stage == "cleanup":
                return httpx.Response(503, json={"private": "private-upstream"})
            return httpx.Response(response.status_code, json=data) if response.content else httpx.Response(response.status_code)
        assert request.url.host == httpx.URL(common.CLOUDBASE_BASE).host
        if request.url.path == "/auth/v1/signin":
            body = json.loads(request.content)
            account = next(item for item in self.accounts if item.username == body["username"])
            assert body["password"] == account.password
            token = "private-synthetic-token-" + account.uid[-1]
            self.valid_tokens[token] = account.uid
            return httpx.Response(200, json={"access_token": token})
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if request.url.path == "/auth/v1/token/introspect":
            return httpx.Response(200, json={"sub": self.valid_tokens[token], "client_id": common.ENV_ID, "token_type": "Bearer"})
        assert request.url.path == "/auth/v1/user/signout"
        if self.failure == "a_token_revoke_failed" and token.endswith("-a"):
            return httpx.Response(500, json={"private": token})
        self.valid_tokens.pop(token, None)
        return httpx.Response(204)

    def run(self):
        with self.api, httpx.Client(transport=httpx.MockTransport(self.transport)) as client:
            admin = SimpleNamespace(preflight=self.preflight, api=self.admin_api)
            self.runner = acceptance.CommunityAcceptance(admin, acceptance.CommunityHttp(client), self.role_change)
            return self.runner.run()


def assert_private_evidence(result, local):
    encoded = json.dumps(result, sort_keys=True)
    for account in local.accounts:
        for private in (account.uid, account.username, account.password):
            assert private not in encoded
    assert "private-synthetic-token" not in encoded and "private-upstream" not in encoded
    assert all(identifier not in encoded for _, identifier in local.runner.attempted_content)
    assert all(identifier not in encoded for identifier in local.runner.users)


def test_complete_bounded_real_acceptance_uses_actual_local_api_and_real_role_logic(monkeypatch):
    local = LocalRun(monkeypatch)
    old_child = {"id": "00000000-0000-4000-8000-000000000999", "status": "active", "nickname": "Untouched synthetic historical child",
                 "owner_user_id": identity_records(AppPrincipal(local.accounts[0].uid, common.ENV_ID))[0]["id"],
                 "age_band": None, "created_at": "2026-10-10T00:00:00.000000Z", "updated_at": "2026-10-10T00:00:00.000000Z"}
    local.family.records["children"][old_child["id"]] = deepcopy(old_child)
    parents_before = deepcopy(local.family.parent_profiles)
    result = local.run()
    assert result["status"] == "pass" and set(result["checks"]) == acceptance.CHECK_NAMES
    assert result["attempted_synthetic_posts"] == 3 and result["attempted_synthetic_comments"] == 1
    assert result["role_cleanup_verified"] is result["content_cleanup_verified"] is result["token_cleanup_verified"] is True
    assert not local.valid_tokens
    assert len(local.resets) == 2 and [action for _, action, _, _ in local.role_changes] == ["grant", "revoke"]
    assert local.family.records["children"][old_child["id"]] == old_child
    assert local.family.parent_profiles == parents_before
    assert all(record["status"] == "deleted" for record in local.store.records["content"].values())
    assert all(record["status"] == "revoked" and len(record["audit"]) == 2 for record in local.store.records["role_bindings"].values())
    assert len(local.store.records["relations"]) == 2 and all(record["active"] is False for record in local.store.records["relations"].values())
    assert len(local.store.records["content_reports"]) == 1 and next(iter(local.store.records["content_reports"].values()))["status"] == "resolved"
    assert_private_evidence(result, local)


@pytest.mark.parametrize("failure", [
    "wrong_identity", "parent_private_leak", "b_already_moderator", "create_ack_lost",
    "public_owner_leak", "stale_review_not_conflicting", "combined_filter_not_and", "hidden_comment_public",
])
def test_boundary_failure_still_cleans_owned_content_roles_and_tokens(monkeypatch, failure):
    local = LocalRun(monkeypatch, failure)
    with pytest.raises(Exception):
        local.run()
    evidence = local.runner.public_evidence("failed")
    assert local.runner.stage == {
        "wrong_identity": "identity", "parent_private_leak": "identity", "b_already_moderator": "identity",
        "create_ack_lost": "posts", "public_owner_leak": "posts", "stale_review_not_conflicting": "edit",
        "combined_filter_not_and": "pagination", "hidden_comment_public": "hide",
    }[failure]
    assert evidence["status"] == "failed" and evidence["code"] == "PC03_ACCEPTANCE_FAILED"
    assert evidence["role_cleanup_verified"] is evidence["content_cleanup_verified"] is evidence["token_cleanup_verified"] is True
    assert not local.valid_tokens
    assert all(record["status"] == "deleted" for record in local.store.records["content"].values())
    assert all(record["status"] == "revoked" for record in local.store.records["role_bindings"].values())
    assert_private_evidence(evidence, local)


def test_lost_grant_acknowledgement_still_revokes_deterministic_role(monkeypatch):
    local = LocalRun(monkeypatch, "role_grant_ack_lost")
    with pytest.raises(RuntimeError):
        local.run()
    assert [action for _, action, _, _ in local.role_changes] == ["grant", "revoke"]
    assert len(local.store.records["role_bindings"]) == 1
    binding = next(iter(local.store.records["role_bindings"].values()))
    validate_role(binding)
    assert binding["status"] == "revoked" and len(binding["audit"]) == 2
    assert not local.store.records["content"] and not local.valid_tokens
    assert local.runner.public_evidence("failed")["role_cleanup_verified"] is True


def test_lost_withdraw_acknowledgement_is_recovered_by_owned_readback(monkeypatch):
    local = LocalRun(monkeypatch, "withdraw_ack_lost")
    assert local.run()["status"] == "pass"
    assert all(record["status"] == "deleted" for record in local.store.records["content"].values())


@pytest.mark.parametrize("failure,field", [
    ("role_revoke_failed", "role_cleanup_verified"),
    ("content_cleanup_unavailable", "content_cleanup_verified"),
    ("a_token_revoke_failed", "token_cleanup_verified"),
])
def test_cleanup_failure_is_reported_and_remaining_cleanup_still_runs(monkeypatch, failure, field):
    local = LocalRun(monkeypatch, failure)
    with pytest.raises(Exception):
        local.run()
    result = local.runner.public_evidence("failed")
    assert result[field] is False and result["status"] == "failed"
    assert "private-synthetic-token-b" not in local.valid_tokens
    if failure != "content_cleanup_unavailable":
        assert all(record["status"] == "deleted" for record in local.store.records["content"].values())
    assert_private_evidence(result, local)


@pytest.mark.parametrize("field,value", [("EnvId", "foreign"), ("Region", "ap-guangzhou"), ("Status", "SUSPENDED"), ("Databases", [{"InstanceId": "foreign", "Status": "RUNNING"}])])
def test_actual_target_mismatch_precedes_password_reset_and_role_write(monkeypatch, field, value):
    local = LocalRun(monkeypatch)
    local.environment["EnvInfo"]["EnvBaseInfo"][field] = value
    with pytest.raises(Exception):
        local.run()
    assert local.resets == local.role_changes == local.requests == []
    assert not local.valid_tokens and not local.store.records["content"]


def test_community_503_precedes_fixture_login_or_role_write(monkeypatch):
    local = LocalRun(monkeypatch, "schema_unready")
    with pytest.raises(common.AcceptanceError):
        local.run()
    assert local.resets == local.role_changes == [] and not local.valid_tokens
    assert not local.store.records["content"] and not local.store.records["role_bindings"]


@pytest.mark.parametrize("mutation", ["name", "duplicate_uid", "missing_account"])
def test_malformed_fixture_selection_never_resets_accounts(monkeypatch, mutation):
    local = LocalRun(monkeypatch)
    if mutation == "name":
        local.accounts[1].username = "ordinary-real-user"
    elif mutation == "duplicate_uid":
        local.accounts[1].uid = local.accounts[0].uid
    else:
        local.accounts.pop()
    with pytest.raises(common.AcceptanceError):
        local.run()
    assert local.resets == local.role_changes == [] and not local.valid_tokens


def test_safe_action_header_and_ambiguous_5xx_are_not_retried():
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(503, json={"private": "upstream"})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        http = acceptance.CommunityHttp(client, sleep=lambda _: pytest.fail("unexpected sleep"))
        response = http.request("POST", common.API_BASE + "/community/posts", token="private-token", body={"title": "合成"}, key="synthetic-key")
        assert response.status_code == 503 and len(requests) == 1
        assert requests[0].headers["Idempotency-Key"] == "synthetic-key"
        assert requests[0].headers["Authorization"] == "Bearer private-token"


@pytest.mark.parametrize("url,key", [("https://foreign.example/api/v2/community/posts", "safe-key"), (common.API_BASE + "/community/posts", "invalid\r\nheader")])
def test_unapproved_target_or_action_key_has_zero_http_calls(url, key):
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("HTTP was called"))) as client:
        with pytest.raises(common.AcceptanceError):
            acceptance.CommunityHttp(client).request("POST", url, token="private-token", body={}, key=key)


def test_rate_limit_retries_are_bounded_and_keep_identical_action_key():
    requests, waits = [], []
    def transport(request):
        requests.append(request)
        return httpx.Response(429, headers={"retry-after": "0.1"})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(common.AcceptanceError, match="RATE_LIMIT_RETRY_EXHAUSTED"):
            acceptance.CommunityHttp(client, sleep=waits.append).request("POST", common.API_BASE + "/community/posts", body={}, key="bounded-key")
    assert len(requests) == 5 and waits == [0.1] * 4
    assert {request.headers["Idempotency-Key"] for request in requests} == {"bounded-key"}


def test_main_exception_output_never_contains_private_upstream_data(monkeypatch, capsys):
    import cloud_admin
    monkeypatch.setattr(cloud_admin, "load_private_environment", lambda: {"CLOUDBASE_APIKEY": "private-api-key"})
    monkeypatch.setattr(acceptance, "CloudAdmin", lambda: (_ for _ in ()).throw(RuntimeError("private-token-and-secret")))
    assert acceptance.main(["--apply", "--cloud-write-authorized"]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "code": "PC03_ACCEPTANCE_FAILED", "stage": "initialization", "checks": {}}
