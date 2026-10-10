"""PC02 real acceptance is opt-in; these tests use local API and Fake providers."""

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
import cloud_family_acceptance as family

from cloud.api.soulcompanion_cloud.app import create_app
from cloud.api.soulcompanion_cloud.auth import AppPrincipal
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError
from cloud.api.soulcompanion_cloud.repository import InMemoryRepository, identity_records


@pytest.mark.parametrize("arguments", [[], ["--cloud-write-authorized"]])
def test_default_plan_never_reads_credentials_contacts_cloud_or_resets_users(monkeypatch, capsys, arguments):
    monkeypatch.setattr(sys, "argv", ["cloud_family_acceptance.py", *arguments])
    monkeypatch.setattr(family.httpx, "Client", lambda **_: pytest.fail("network initialized"))
    monkeypatch.setattr(family.CloudAdmin, "preflight", lambda *_: pytest.fail("cloud preflight"))
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: pytest.fail("CLI started"))
    assert family.main() == 0
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["status"] == "plan" and evidence["real_calls"] is False
    assert evidence["existing_synthetic_users"] == 2 and evidence["synthetic_users_created"] == 0
    assert evidence["destructive_operations"] == []


def test_apply_without_explicit_cloud_authorization_is_blocked_before_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cloud_family_acceptance.py", "--apply"])
    monkeypatch.setattr(family.httpx, "Client", lambda **_: pytest.fail("network initialized"))
    assert family.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "blocked",
        "code": "CLOUD_WRITE_AUTHORIZATION_REQUIRED",
        "real_calls": False,
    }


class LocalRun:
    def __init__(self, monkeypatch, boundary_failure=None):
        self.accounts = [
            common.SyntheticAccount(
                "scphase04_" + name * 20, "SyntheticPrivate123!", uid="private-synthetic-uid-" + name
            )
            for name in "ab"
        ]
        self.valid_tokens = {}
        self.requests = []
        self.resets = []
        self.boundary_failure = boundary_failure
        self.repository = InMemoryRepository(family_identity_enabled=True)
        state = self

        class Verifier:
            async def verify(self, token):
                if token not in state.valid_tokens:
                    raise CloudError(401, "unauthorized", "Please sign in again.")
                return AppPrincipal(state.valid_tokens[token], common.ENV_ID)

            async def ready(self):
                return True

        self.api = TestClient(
            create_app(Settings(private_rate_limit=1000, preauth_rate_limit=1000), self.repository, Verifier())
        )
        monkeypatch.setattr(family, "existing_fixture_accounts", lambda _: self.accounts)
        monkeypatch.setattr(family, "reset_fixture_password", self.reset)
        monkeypatch.setattr(common, "create_account", lambda *_: pytest.fail("new auth account created"))

    def reset(self, _admin, account):
        self.resets.append(account.username)

    def transport(self, request):
        self.requests.append(request)
        if request.url.host == httpx.URL(common.API_BASE).host:
            if (
                self.boundary_failure == "age_required_on_create"
                and request.url.path == "/api/v2/children"
                and request.method == "POST"
                and "age_band" not in json.loads(request.content)
            ):
                return httpx.Response(422, json={"error": {"code": "validation_error"}})
            if (
                self.boundary_failure == "capabilities_disabled"
                and request.url.path.endswith("/capabilities")
                and request.headers.get("authorization", "").removeprefix("Bearer ") in self.valid_tokens
            ):
                return httpx.Response(200, json={"child_age_band": False, "parent_profile": False})
            response = self.api.request(
                request.method,
                request.url.path,
                params=request.url.params,
                headers=request.headers,
                content=request.content,
            )
            data = response.json() if response.content else None
            if request.url.path.endswith("/parent-profile") and response.status_code == 200:
                if self.boundary_failure == "profile_owner_leak" and data:
                    data["owner_user_id"] = "private-synthetic-uid-a"
                if self.boundary_failure == "profile_write_response_ignored" and request.method == "PUT":
                    data["nickname"] = "Wrong synthetic response"
                if self.boundary_failure == "profile_readback_ignored" and request.method == "GET" and data:
                    data["nickname"] = "Wrong synthetic readback"
            if (
                self.boundary_failure == "rejected_parent_put_changed_b"
                and request.url.path.endswith("/parent-profile")
                and request.method == "PUT"
                and response.status_code == 422
            ):
                b_id = identity_records(AppPrincipal(self.accounts[1].uid, common.ENV_ID))[0]["id"]
                from cloud.api.soulcompanion_cloud.family_identity import parent_profile_id

                self.repository.parent_profiles[parent_profile_id(b_id)]["nickname"] = "PC02合成意外变化"
            if (
                self.boundary_failure == "denied_foreign_patch_changed_age"
                and "/children/" in request.url.path
                and request.method == "PATCH"
                and response.status_code == 404
            ):
                self.repository.records["children"][request.url.path.rsplit("/", 1)[1]]["age_band"] = "0-2"
            if (
                self.boundary_failure == "invalid_patch_changed_age"
                and "/children/" in request.url.path
                and request.method == "PATCH"
                and response.status_code == 422
            ):
                self.repository.records["children"][request.url.path.rsplit("/", 1)[1]]["age_band"] = "0-2"
            if "/children/" in request.url.path and response.status_code == 200 and request.method == "PATCH":
                body = json.loads(request.content)
                if self.boundary_failure == "omitted_age_not_preserved" and "age_band" not in body:
                    data["age_band"] = None
                if self.boundary_failure == "explicit_age_not_cleared" and body.get("age_band", "missing") is None:
                    data["age_band"] = "6-8"
                if self.boundary_failure == "age_update_not_persisted" and body.get("age_band") == "9-12":
                    # Return an expected patch while the next GET still sees old age.
                    record = self.repository.records["children"][data["id"]]
                    record["age_band"] = "6-8"
                if self.boundary_failure == "patch_upstream_failed" and "age_band" not in body:
                    return httpx.Response(500, json={"private_upstream": "SyntheticPrivate123!"})
            if (
                self.boundary_failure == "b_children_leaked"
                and request.url.path == "/api/v2/children"
                and request.method == "GET"
                and response.status_code == 200
                and data["items"] == []
            ):
                data["items"] = [{"id": "private-existing-child"}]
                data["total"] = 1
            if (
                self.boundary_failure == "create_response_unconfirmed"
                and request.url.path == "/api/v2/children"
                and request.method == "POST"
            ):
                data.pop("id")
            if (
                self.boundary_failure == "create_response_extra_field"
                and request.url.path == "/api/v2/children"
                and request.method == "POST"
            ):
                data["owner_user_id"] = "private-synthetic-owner"
            if response.content and data is None:
                return httpx.Response(response.status_code, content=b"null")
            return (
                httpx.Response(response.status_code, json=data)
                if response.content
                else httpx.Response(response.status_code)
            )
        if request.url.path == "/auth/v1/signin":
            body = json.loads(request.content)
            account = next(item for item in self.accounts if item.username == body["username"])
            assert body["password"] == account.password
            token = "private-synthetic-token-" + account.uid[-1]
            self.valid_tokens[token] = account.uid
            return httpx.Response(200, json={"access_token": token})
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if request.url.path == "/auth/v1/token/introspect":
            return httpx.Response(
                200, json={"sub": self.valid_tokens[token], "client_id": common.ENV_ID, "token_type": "Bearer"}
            )
        if request.url.path == "/auth/v1/user/signout":
            if self.boundary_failure == "a_revocation_failed" and token.endswith("-a"):
                return httpx.Response(500, json={"private": token})
            self.valid_tokens.pop(token, None)
            return httpx.Response(204)
        assert request.url.path == family.PARENT_DATABASE_DENIAL_PATH
        return httpx.Response(
            200 if self.boundary_failure == "direct_database_open" else 403, json={"private": "not-for-evidence"}
        )

    def run(self):
        with self.api, httpx.Client(transport=httpx.MockTransport(self.transport)) as client:
            self.runner = family.FamilyAcceptance(SimpleNamespace(preflight=lambda: None), common.PrivateHttp(client))
            return self.runner.run()


def test_complete_family_acceptance_reuses_two_fixtures_and_archives_only_its_child(monkeypatch):
    local = LocalRun(monkeypatch)
    # An old owned record must never be touched or archived by new acceptance.
    old = {
        "id": "00000000-0000-4000-8000-000000000099",
        "owner_user_id": identity_records(AppPrincipal(local.accounts[0].uid, common.ENV_ID))[0]["id"],
        "nickname": "Untouched synthetic existing",
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    local.repository.records["children"][old["id"]] = deepcopy(old)
    result = local.run()
    assert result["status"] == "pass" and set(result["checks"]) == family.CHECK_NAMES
    assert all(result["checks"].values())
    assert result["api_token_cleanup_verified"] is True and result["child_cleanup_verified"] is True
    assert local.valid_tokens == {} and local.resets == [item.username for item in local.accounts]
    assert len(local.repository.parent_profiles) == 2 and len(local.repository.users) == 2
    children = local.repository.records["children"]
    assert children[old["id"]] == old
    new = [record for key, record in children.items() if key != old["id"]]
    assert len(new) == 1 and new[0]["status"] == "archived"
    b = local.accounts[1]
    b_owner = identity_records(AppPrincipal(b.uid, common.ENV_ID))[0]["id"]
    assert not any(record["owner_user_id"] == b_owner for record in children.values())
    serialized = json.dumps(result)
    assert all(
        item.password not in serialized and item.uid not in serialized and item.username not in serialized
        for item in local.accounts
    )
    assert "private-synthetic-token" not in serialized


def test_repeat_acceptance_reads_existing_profile_preserves_ids_and_keeps_b_empty(monkeypatch):
    local = LocalRun(monkeypatch)
    local.run()
    original = {
        owner: (record["id"], record["created_at"]) for owner, record in local.repository.parent_profiles.items()
    }
    local.run()
    assert {
        owner: (record["id"], record["created_at"]) for owner, record in local.repository.parent_profiles.items()
    } == original
    assert len(local.repository.users) == 2 and len(local.repository.parent_profiles) == 2
    assert len(local.repository.records["children"]) == 2
    assert all(record["status"] == "archived" for record in local.repository.records["children"].values())
    b_owner = identity_records(AppPrincipal(local.accounts[1].uid, common.ENV_ID))[0]["id"]
    assert not any(record["owner_user_id"] == b_owner for record in local.repository.records["children"].values())
    assert local.valid_tokens == {}


@pytest.mark.parametrize(
    "failure",
    [
        "capabilities_disabled",
        "profile_owner_leak",
        "profile_write_response_ignored",
        "profile_readback_ignored",
        "omitted_age_not_preserved",
        "explicit_age_not_cleared",
        "age_update_not_persisted",
        "patch_upstream_failed",
        "b_children_leaked",
        "direct_database_open",
        "create_response_extra_field",
        "rejected_parent_put_changed_b",
        "denied_foreign_patch_changed_age",
        "invalid_patch_changed_age",
        "age_required_on_create",
    ],
)
def test_real_checks_fail_and_cleanup_both_tokens_even_when_boundary_regresses(monkeypatch, failure):
    local = LocalRun(monkeypatch, failure)
    with pytest.raises(common.AcceptanceError):
        local.run()
    assert local.valid_tokens == {} and local.runner.token_cleanup_failures == 0
    assert all(record["status"] == "archived" for record in local.repository.records["children"].values())
    if failure == "capabilities_disabled":
        assert not local.repository.parent_profiles and not local.repository.records["children"]


def test_unconfirmed_child_creation_is_never_guessed_or_deleted(monkeypatch):
    local = LocalRun(monkeypatch, "create_response_unconfirmed")
    with pytest.raises(common.AcceptanceError):
        local.run()
    assert local.valid_tokens == {}
    assert local.runner.child_cleanup_verified is False
    assert not any(request.method == "DELETE" for request in local.requests)
    assert next(iter(local.repository.records["children"].values()))["status"] == "active"


def test_failed_a_revocation_still_attempts_b_and_reports_cleanup_failure(monkeypatch):
    local = LocalRun(monkeypatch, "a_revocation_failed")
    with pytest.raises(common.AcceptanceError):
        local.run()
    assert local.runner.token_cleanup_failures == 1
    assert list(local.valid_tokens) == ["private-synthetic-token-a"]
    assert local.accounts[1].token == ""
    assert local.runner.child_cleanup_verified is True


def test_main_discards_private_exception_and_arbitrary_evidence(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cloud_family_acceptance.py", "--apply", "--cloud-write-authorized"])

    def fail(self):
        self.stage = "private-token-stage"
        self.checks["private-token-check"] = "private-secret"
        raise RuntimeError("SyntheticPrivate123! upstream token uid private response")

    monkeypatch.setattr(family.FamilyAcceptance, "run", fail)
    assert family.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed" and result["code"] == "PC02_ACCEPTANCE_FAILED"
    assert result["stage"] == "unknown" and result["checks"] == {}
    assert "private" not in json.dumps(result) and "SyntheticPrivate" not in json.dumps(result)


def test_prelogin_validation_failure_does_not_claim_token_revocation_verified(monkeypatch):
    local = LocalRun(monkeypatch)
    local.accounts[0].username = "foreign-not-fixture-user"
    with pytest.raises(common.AcceptanceError):
        local.run()
    result = local.runner.public_evidence("failed")
    assert result["api_token_cleanup_verified"] is False
    assert "issued_tokens_revoked_private_api_denied" not in result["checks"]
    assert local.resets == [] and local.valid_tokens == {}
