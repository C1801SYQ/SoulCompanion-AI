"""Acceptance tooling is private by construction and has no default writes."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cloud_acceptance as acceptance


class Clock:
    def __init__(self):
        self.value = 0
        self.waits = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


def test_plan_cannot_create_users_contact_cloud_or_read_credentials(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cloud_acceptance.py", "--browser"])
    monkeypatch.setattr(acceptance.CloudAdmin, "preflight", lambda *_: pytest.fail("cloud call"))
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: pytest.fail("child process"))
    assert acceptance.main() == 0
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["status"] == "plan" and evidence["real_calls"] is False
    assert evidence["synthetic_users"] == 2 and evidence["destructive_operations"] == []


@pytest.mark.parametrize("url", [
    "https://other-environment.api.tcloudbasegateway.com/auth/v1/signin",
    "http://" + acceptance.API_BASE.removeprefix("https://") + "/me",
    "https://example.com/api/v2/me", acceptance.API_BASE.replace("/api/v2", "/admin"),
    acceptance.API_BASE + "/me#private", acceptance.API_BASE.replace("https://", "https://private@"),
    acceptance.API_BASE + "/me\r\n", acceptance.API_BASE.replace(".com/", ".com:invalid/"),
    acceptance.CLOUDBASE_BASE + "/v1/database/instances/(default)/databases/(default)/collections/other/documents",
])
def test_only_confirmed_https_targets_receive_private_headers(url):
    contacted = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: contacted.append(request))) as client:
        with pytest.raises(acceptance.AcceptanceError, match="UNAPPROVED_TARGET"):
            acceptance.PrivateHttp(client).request("GET", url, token="synthetic-private-token")
    assert contacted == []


def test_generated_passwords_fit_official_policy_without_external_storage():
    for _ in range(20):
        account = acceptance.new_account()
        assert acceptance.NAME_PATTERN.fullmatch(account.username)
        assert 8 <= len(account.password) <= 32 and account.password[0].isalpha()
        assert any(item.islower() for item in account.password)
        assert any(item.isupper() for item in account.password)
        assert any(item.isdigit() for item in account.password)
        assert account.password not in repr(account)


def test_private_cli_password_never_appears_in_os_arguments(tmp_path, monkeypatch):
    entry = tmp_path / "cli.js"
    entry.write_text("unused", encoding="utf-8")
    account = acceptance.SyntheticAccount("scphase04_" + "a" * 20, "SyntheticPrivate123!")
    preflights, invocations = [], []
    admin = SimpleNamespace(cli_entry=entry, preflight=lambda: preflights.append(True))

    def capture(args, **kwargs):
        invocations.append((args, kwargs))
        assert preflights == [True]
        assert account.password not in " ".join(args)
        private_input = json.loads(kwargs["input"])
        assert private_input["entry"] == str(entry)
        assert private_input["args"][private_input["args"].index("--password") + 1] == account.password
        assert "runMain()" in args[2]
        assert kwargs["capture_output"] is True
        return SimpleNamespace(returncode=0, stdout=json.dumps({"data": {"Data": {"Uid": "synthetic-private-uid"}}}), stderr="")

    monkeypatch.setattr(subprocess, "run", capture)
    acceptance.create_account(admin, account)
    assert account.uid == "synthetic-private-uid" and len(invocations) == 1


def test_cli_failure_discards_private_output_and_exception_context(tmp_path, monkeypatch):
    entry = tmp_path / "cli.js"
    entry.touch()
    account = acceptance.SyntheticAccount("scphase04_" + "a" * 20, "SyntheticPrivate123!")
    admin = SimpleNamespace(cli_entry=entry, preflight=lambda: None)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=1, stdout=json.dumps({"data": {"Error": {"Code": "InvalidParameter", "Message": account.password}}}), stderr=account.password,
    ))
    with pytest.raises(acceptance.AcceptanceError) as error:
        acceptance.create_account(admin, account)
    assert str(error.value) == "SYNTHETIC_USER_CREATE_REJECTED"
    assert error.value.__suppress_context__ is True
    assert account.password not in str(error.value)


def test_mutating_503_is_not_replayed():
    seen = []
    clock = Clock()
    def handler(request):
        seen.append(request)
        return httpx.Response(503, json={"error": "synthetic-private-material"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        http = acceptance.PrivateHttp(client, sleep=clock.sleep, clock=clock.now)
        response = http.request("POST", acceptance.API_BASE + "/children", token="synthetic-private-token", body={"nickname": "synthetic"})
    assert response.status_code == 503 and len(seen) == 1 and clock.waits == []


def test_429_honors_retry_after_and_preserves_only_counters():
    clock = Clock()
    seen = []
    def handler(request):
        seen.append(request)
        if len(seen) < 3:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"status": "ok"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        http = acceptance.PrivateHttp(client, sleep=clock.sleep, clock=clock.now)
        assert http.request("GET", acceptance.API_BASE + "/healthz").status_code == 200
    assert clock.waits == [2, 2] and http.requests == 3 and http.rate_retries == 2


def test_429_cannot_wait_forever_or_accept_unbounded_retry_after():
    clock = Clock()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "900000000"}))) as client:
        http = acceptance.PrivateHttp(client, sleep=clock.sleep, clock=clock.now)
        with pytest.raises(acceptance.AcceptanceError, match="RATE_LIMIT_RETRY_EXHAUSTED"):
            http.request("GET", acceptance.API_BASE + "/me", token="synthetic-private-token")
    assert clock.waits == [60, 60] and http.requests == 3


def test_expired_or_revoked_token_must_be_rejected_by_api():
    account = acceptance.SyntheticAccount("synthetic", "private", token="synthetic-private-token")
    requests = []
    def handler(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(204 if request.method == "POST" else 401)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acceptance.revoke(acceptance.PrivateHttp(client), account)
    assert account.token == ""
    assert requests == [("POST", "/auth/v1/user/signout"), ("GET", "/api/v2/me")]


def test_provider_signout_without_server_rejection_cannot_pass():
    account = acceptance.SyntheticAccount("synthetic", "private", token="synthetic-private-token")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(204 if request.method == "POST" else 200))) as client:
        with pytest.raises(acceptance.AcceptanceError, match="UNEXPECTED_HTTP_STATUS"):
            acceptance.revoke(acceptance.PrivateHttp(client), account)


def test_login_requires_server_introspection_matching_created_principal():
    account = acceptance.SyntheticAccount("synthetic", "private", uid="expected-private-uid")
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"access_token": "synthetic-private-token"})
        return httpx.Response(200, json={"sub": "foreign-private-uid", "client_id": acceptance.ENV_ID, "token_type": "Bearer"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(acceptance.AcceptanceError, match="AUTH_PRINCIPAL_MISMATCH"):
            acceptance.login(acceptance.PrivateHttp(client), account)
    assert account.token == ""


def test_apply_failure_stdout_contains_only_fixed_stage_and_check_names(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cloud_acceptance.py", "--apply"])
    def fail(_self, **_kwargs):
        raise RuntimeError("synthetic-private-password token uid upstream message")
    monkeypatch.setattr(acceptance.Acceptance, "run", fail)
    assert acceptance.main() == 1
    output = capsys.readouterr().out
    assert "synthetic-private" not in output and "token" not in output and "uid" not in output
    assert json.loads(output) == {"status": "failed", "code": "CLOUD_ACCEPTANCE_FAILED", "stage": "preflight", "checks": {}}


def test_browser_private_credentials_use_stdin_and_output_is_reconstructed(monkeypatch):
    account = acceptance.SyntheticAccount("synthetic", "SyntheticPrivate123!")
    checks = {name: True for name in (
        "guest_private_requests_absent", "official_sdk_login", "me_ui_loaded", "profile_created",
        "profile_renamed", "profile_selected", "profile_archived", "logout_hides_private_data",
        "token_revoked", "auth_storage_absent", "automatic_device_acquisition_absent", "raw_media_requests_absent",
    )}
    def capture(args, **kwargs):
        assert account.password not in " ".join(args)
        assert json.loads(kwargs["input"])["password"] == account.password
        return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "pass", "checks": checks, "extra_private_value": account.password}), stderr=account.password)
    monkeypatch.setattr(subprocess, "run", capture)
    result = acceptance.run_browser(account)
    assert result == {"status": "pass", "checks": checks}
    assert account.password not in json.dumps(result)


def test_browser_plan_never_reads_stdin_or_starts_a_browser():
    result = subprocess.run(["node", str(acceptance.ROOT / "scripts/cloud_browser.cjs")], input="not-private-json", capture_output=True, text=True, timeout=10, cwd=acceptance.ROOT)
    assert result.returncode == 0 and result.stderr == ""
    plan = json.loads(result.stdout)
    assert plan["status"] == "plan" and plan["real_calls"] is False


@pytest.mark.parametrize("boundary_failure", [
    None, "patch_response_ignored", "patch_persistence_ignored",
    "unfiltered_children_leaked", "unfiltered_sessions_leaked",
])
def test_complete_acceptance_contract_against_real_local_application(monkeypatch, boundary_failure):
    """Real application/repository rules, with only the external provider mocked.

    This is local integration evidence; it does not claim a deployed CloudBase
    call or replace the explicitly gated real acceptance run.
    """
    from fastapi.testclient import TestClient
    from cloud.api.soulcompanion_cloud.app import create_app
    from cloud.api.soulcompanion_cloud.auth import AppPrincipal
    from cloud.api.soulcompanion_cloud.config import Settings
    from cloud.api.soulcompanion_cloud.errors import CloudError
    from cloud.api.soulcompanion_cloud.repository import InMemoryRepository

    accounts, valid_tokens = {}, {}
    class Verifier:
        async def ready(self):
            return True

        async def verify(self, token):
            if token not in valid_tokens:
                raise CloudError(401, "unauthorized", "Please sign in again.")
            return AppPrincipal(valid_tokens[token], acceptance.ENV_ID)

    def synthetic_create(_admin, account):
        account.uid = "local-private-uid-" + str(len(accounts))
        accounts[account.username] = account

    monkeypatch.setattr(acceptance, "create_account", synthetic_create)
    repository = InMemoryRepository()
    settings = Settings(env_id=acceptance.ENV_ID, private_rate_limit=200, preauth_rate_limit=200)
    with TestClient(create_app(settings, repository, Verifier())) as app_client:
        def upstream(request):
            if request.url.host == httpx.URL(acceptance.API_BASE).host:
                if request.url.path == "/api/v2/me" and request.method == "PATCH" and boundary_failure:
                    if boundary_failure == "patch_response_ignored":
                        # A successful status alone must not accept an ignored mutation.
                        local = app_client.get(request.url.path, headers=request.headers)
                        return httpx.Response(local.status_code, headers=local.headers, content=local.content)
                    if boundary_failure == "patch_persistence_ignored":
                        # Even an expected PATCH response must be read back from storage.
                        local = app_client.get(request.url.path, headers=request.headers)
                        body = local.json()
                        body["display_name"] = json.loads(request.content)["display_name"]
                        return httpx.Response(local.status_code, json=body)
                local = app_client.request(request.method, request.url.path,
                                           params=request.url.params, headers=request.headers,
                                           content=request.content)
                collection = request.url.path.removeprefix("/api/v2/")
                if (boundary_failure == f"unfiltered_{collection}_leaked"
                        and request.method == "GET" and not request.url.query
                        and json.loads(local.content).get("items") == []):
                    return httpx.Response(200, json={"items": [{"id": "foreign-synthetic-resource"}]})
                return httpx.Response(local.status_code, headers=local.headers, content=local.content)
            if request.url.path == "/auth/v1/signin":
                body = json.loads(request.content)
                account = accounts[body["username"]]
                assert body["password"] == account.password
                token = "local-private-token-" + str(len(valid_tokens))
                valid_tokens[token] = account.uid
                return httpx.Response(200, json={"access_token": token})
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if request.url.path == "/auth/v1/token/introspect":
                return httpx.Response(200, json={"sub": valid_tokens[token], "client_id": acceptance.ENV_ID, "token_type": "Bearer"})
            if request.url.path == "/auth/v1/user/signout":
                valid_tokens.pop(token)
                return httpx.Response(204)
            assert request.url.path == acceptance.DATABASE_DENIAL_PATH
            return httpx.Response(403)

        with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
            runner = acceptance.Acceptance(SimpleNamespace(preflight=lambda: None), acceptance.PrivateHttp(client))
            if boundary_failure:
                with pytest.raises(acceptance.AcceptanceError, match="ACCEPTANCE_ASSERTION_FAILED"):
                    runner.run()
                return
            result = runner.run()
    assert result["status"] == "pass" and all(result["checks"].values())
    assert len(result["checks"]) == 11
    assert result["browser"] is None and valid_tokens == {}
    assert len(repository.users) == 2
    assert len(repository.records["children"]) == len(repository.records["sessions"]) == 1
    assert next(iter(repository.records["children"].values()))["status"] == "archived"
    assert next(iter(repository.records["sessions"].values()))["status"] == "ended"
    serialized = json.dumps(result)
    assert all(account.uid not in serialized and account.password not in serialized for account in accounts.values())
