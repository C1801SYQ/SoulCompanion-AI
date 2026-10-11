"""No-cloud PC04 acceptance gates, bounded attempt ledger and failure cleanup."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cloud_community_integration_acceptance as integration
from cloud.api.soulcompanion_cloud.community.service import deterministic_id
from cloud.api.soulcompanion_cloud.community.models import PostCreate
from test_community_acceptance import LocalRun


@pytest.mark.parametrize("arguments", [[], ["--cloud-write-authorized"]])
def test_default_plan_never_initializes_network_credentials_or_cli(monkeypatch, capsys, arguments):
    monkeypatch.setattr(integration, "CloudAdmin", lambda: pytest.fail("cloud admin initialized"))
    monkeypatch.setattr(integration.httpx, "Client", lambda **_: pytest.fail("network initialized"))
    monkeypatch.setattr(integration.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("browser executed"))
    import cloud_admin
    monkeypatch.setattr(cloud_admin, "load_private_environment", lambda: pytest.fail("private credentials loaded"))
    assert integration.main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "plan" and result["real_calls"] is False
    assert result["existing_synthetic_users"] == 2 and result["synthetic_users_created"] == 0
    assert (result["maximum_new_posts"], result["maximum_new_comments"], result["maximum_new_reports"]) == (1, 1, 1)
    assert result["new_resources"] == result["schema_changes"] == result["destructive_operations"] == []


def test_apply_without_independent_pc04_authorization_has_zero_calls(monkeypatch, capsys):
    monkeypatch.setattr(integration, "CloudAdmin", lambda: pytest.fail("cloud admin initialized"))
    monkeypatch.setattr(integration.httpx, "Client", lambda **_: pytest.fail("network initialized"))
    assert integration.main(["--apply"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "blocked", "code": "PC04_CLOUD_WRITE_AUTHORIZATION_REQUIRED", "real_calls": False,
    }


def test_missing_or_stale_official_build_rejects_before_cloud_credentials(monkeypatch, capsys):
    def unavailable():
        raise integration.AcceptanceError("OFFICIAL_H5_BUILD_REQUIRED")
    monkeypatch.setattr(integration, "validate_browser_build", unavailable)
    monkeypatch.setattr(integration, "CloudAdmin", lambda: pytest.fail("cloud admin initialized"))
    import cloud_admin
    monkeypatch.setattr(cloud_admin, "load_private_environment", lambda: pytest.fail("private environment loaded"))
    assert integration.main(["--apply", "--cloud-write-authorized"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed" and result["code"] == "PC04_ACCEPTANCE_FAILED"


def make_local(monkeypatch, failure=None):
    local = LocalRun(monkeypatch, failure)
    monkeypatch.setattr(integration, "existing_fixture_accounts", lambda _: local.accounts)
    monkeypatch.setattr(integration, "reset_fixture_password", local.reset)
    return local


def run_local(local, browser):
    with local.api, httpx.Client(transport=httpx.MockTransport(local.transport)) as client:
        admin = SimpleNamespace(preflight=local.preflight, api=local.admin_api)
        local.runner = integration.IntegrationAcceptance(admin, integration.CommunityHttp(client, sleep=lambda _: None), local.role_change, browser)
        return local.runner.run()


def simulated_browser(local, failure=None):
    """Exercise real FastAPI routes in memory, never claim this fake UI is a real-cloud PASS."""
    def browser(accounts, users, nonce, event):
        runner = local.runner
        for index, account in enumerate(accounts):
            event({"kind": "token", "account": index, "token": account.token})
            event({"kind": "nickname", "account": index})
            result = integration.payload(integration.require_status(runner.api("PUT", "/parent-profile", index, body={"nickname": "PC04合成家长" + "甲乙"[index]}), 200))
            assert result["nickname"].startswith("PC04合成家长")
            event({"kind": "nickname_settled", "account": index})
        post_key = nonce + "-post"
        post_id = deterministic_id("post", users[0], post_key)
        event({"kind": "post", "account": 0, "key": post_key, "body": integration.SYNTHETIC_POST})
        post = integration.payload(integration.require_status(runner.api("POST", "/community/posts", 0,
            body=integration.SYNTHETIC_POST, key=post_key), 201))
        assert post["id"] == post_id and post["status"] == "pending"
        assert runner.api("GET", "/community/posts/" + post_id).status_code == 404
        if failure == "after_post":
            raise RuntimeError("private-browser-password-token-post-url")
        result = integration.payload(integration.require_status(runner.api("POST", f"/ops/moderation/posts/{post_id}/approve", 1,
            body={"expected_revision": 1, "reason": "PC04合成审核"}, key=nonce + "-approve-post"), 200))
        assert result["content"]["status"] == "published"
        comment_key = nonce + "-comment"
        event({"kind": "comment", "account": 1, "key": comment_key, "body": integration.SYNTHETIC_COMMENT, "post_id": post_id})
        comment = integration.payload(integration.require_status(runner.api("POST", f"/community/posts/{post_id}/comments", 1,
            body=integration.SYNTHETIC_COMMENT, key=comment_key), 201))
        assert comment["status"] == "pending"
        integration.require_status(runner.api("POST", f"/ops/moderation/comments/{comment['id']}/approve", 1,
            body={"expected_revision": 1, "reason": "PC04合成审核"}, key=nonce + "-approve-comment"), 200)
        for kind in ("like", "bookmark"):
            event({"kind": "relation", "account": 1, "relation": kind, "target_id": post_id})
            assert integration.payload(integration.require_status(runner.api("PUT", f"/community/posts/{post_id}/{kind}", 1), 200))["active"] is True
        report_key = nonce + "-report"
        report_body = {"target_type": "post", "target_id": post_id, "reason": "privacy", "detail": integration.SYNTHETIC_REPORT_DETAIL}
        event({"kind": "report", "account": 1, "key": report_key, "target_id": post_id, "body": report_body})
        report = integration.payload(integration.require_status(runner.api("POST", "/community/content-reports", 1,
            body=report_body, key=report_key), 201))
        if failure == "after_report":
            raise RuntimeError("private-browser-password-token-report-url")
        resolution = integration.payload(integration.require_status(runner.api("POST", f"/ops/content-reports/{report['id']}/resolve", 1,
            body={"expected_revision": 1, "decision": "resolved", "reason": "合成举报处理，无隐藏"}, key=nonce + "-resolve"), 200))
        assert resolution["report"]["status"] == "resolved"
        assert runner.api("GET", "/community/posts/" + post_id).status_code == 200
        for kind, identifier, account in (("post", post_id, 0), ("comment", comment["id"], 1)):
            integration.require_status(runner.api("DELETE", f"/community/{kind}s/{identifier}", account, params={"expected_revision": 1}), 204)
        assert runner.api("GET", "/community/posts/" + post_id).status_code == 404
        return {"status": "pass", "checks": {name: True for name in integration.BROWSER_CHECKS}}
    return browser


def assert_safe_result(result, local):
    # Existing helper assumes PC03 tuple ledger; inspect PC04 dictionary explicitly.
    encoded = json.dumps(result, sort_keys=True)
    for account in local.accounts:
        assert account.username not in encoded and account.uid not in encoded
    assert "private-synthetic-token" not in encoded and "private-browser" not in encoded
    assert not any(identifier in encoded for identifier in local.runner.attempted_content)
    assert not any(identifier in encoded for identifier in local.runner.users)
    assert all(value is True for value in result["checks"].values())


def test_complete_local_tool_plan_uses_one_post_comment_report_and_cleans_all(monkeypatch):
    local = make_local(monkeypatch)
    parents = {identifier: record["nickname"] for identifier, record in local.family.parent_profiles.items()}
    result = run_local(local, simulated_browser(local))
    assert result["status"] == "pass" and set(result["checks"]) == integration.CHECKS
    assert (result["attempted_synthetic_posts"], result["attempted_synthetic_comments"], result["attempted_synthetic_reports"]) == (1, 1, 1)
    assert result["cleanup_failures"] == 0 and len(local.resets) == 2
    assert [action for _, action, _, _ in local.role_changes] == ["grant", "revoke"]
    assert {identifier: record["nickname"] for identifier, record in local.family.parent_profiles.items()} == parents
    assert all(record["status"] == "deleted" for record in local.store.records["content"].values())
    assert all(record["status"] == "resolved" for record in local.store.records["content_reports"].values())
    assert not local.valid_tokens
    assert not any("/children" in request.url.path or "/sessions" in request.url.path for request in local.requests)
    assert not any("role" in request.url.path for request in local.requests)
    assert_safe_result(result, local)


@pytest.mark.parametrize("failure", ["after_post", "after_report"])
def test_browser_failure_cleans_acknowledged_targets_nickname_role_and_tokens(monkeypatch, failure):
    local = make_local(monkeypatch)
    with pytest.raises(RuntimeError, match="private-browser"):
        run_local(local, simulated_browser(local, failure))
    assert all(record["status"] == "deleted" for record in local.store.records["content"].values())
    assert all(record["status"] == "resolved" for record in local.store.records["content_reports"].values())
    assert all(record["status"] == "revoked" for record in local.store.records["role_bindings"].values())
    assert not local.valid_tokens and local.runner.cleanup_failures == 0
    assert_safe_result(local.runner.public_evidence("failed"), local)


def test_lost_post_reply_keeps_attempt_id_for_cleanup(monkeypatch):
    local = make_local(monkeypatch, "create_ack_lost")
    with pytest.raises(integration.AcceptanceError):
        run_local(local, simulated_browser(local))
    assert len(local.runner.attempted_content) == 1
    assert all(record["status"] == "deleted" for record in local.store.records["content"].values())
    assert not local.valid_tokens and local.runner.cleanup_failures == 0


def test_lost_role_grant_reply_still_revoke_existing_second_fixture(monkeypatch):
    local = make_local(monkeypatch, "role_grant_ack_lost")
    original = local.role_change

    def change(*args):
        try:
            return original(*args)
        except RuntimeError:
            local.failure = None
            raise

    local.role_change = change
    with pytest.raises(RuntimeError):
        run_local(local, lambda *_: pytest.fail("browser should not start"))
    assert [action for _, action, _, _ in local.role_changes] == ["grant", "grant", "revoke"]
    assert not local.valid_tokens and local.runner.cleanup_failures == 0


def test_cleanup_failure_never_becomes_pass_and_attempts_remaining_cleanup(monkeypatch):
    local = make_local(monkeypatch, "role_revoke_failed")
    with pytest.raises(integration.AcceptanceError, match="PC04_ACCEPTANCE_INCOMPLETE"):
        run_local(local, simulated_browser(local))
    evidence = local.runner.public_evidence("failed")
    assert evidence["cleanup_failures"] > 0 and "temporary_moderator_revoked" not in evidence["checks"]
    assert not local.valid_tokens and all(record["status"] == "deleted" for record in local.store.records["content"].values())
    assert_safe_result(evidence, local)


@pytest.mark.parametrize("event", [
    {"kind": "post", "account": 1, "key": "bad-owner"},
    {"kind": "comment", "account": 0, "key": "bad-owner"},
    {"kind": "post", "account": 0, "key": "unsafe key"},
    {"kind": "nickname", "account": True},
    {"kind": "nickname", "account": 0, "child_name": "forbidden"},
    {"kind": "report", "account": 1, "key": "report", "target_id": "00000000-0000-4000-8000-000000000009"},
    {"kind": "relation", "account": 1, "relation": "like", "target_id": "00000000-0000-4000-8000-000000000009"},
    {"kind": "role", "account": 1},
])
def test_private_attempt_protocol_rejects_extra_targets_fields_and_wrong_owner(monkeypatch, event):
    local = make_local(monkeypatch)
    runner = integration.IntegrationAcceptance(SimpleNamespace(), SimpleNamespace(), local.role_change)
    runner.users = ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"]
    with pytest.raises(Exception):
        runner.event(event)
    assert not runner.attempted_content and runner.report_id is None and not runner.nickname_attempts


def test_private_ledger_allows_same_key_replay_but_blocks_second_new_content(monkeypatch):
    local = make_local(monkeypatch)
    runner = integration.IntegrationAcceptance(SimpleNamespace(), SimpleNamespace(), local.role_change)
    runner.users = ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"]
    for _ in range(2):
        runner.event({"kind": "post", "account": 0, "key": "same-action", "body": integration.SYNTHETIC_POST})
    with pytest.raises(integration.AcceptanceError, match="BOUND_EXCEEDED"):
        runner.event({"kind": "post", "account": 0, "key": "second-action", "body": integration.SYNTHETIC_POST})
    assert len(runner.attempted_content) == 1


def test_acknowledged_but_delayed_post_is_settled_once_with_original_key_then_withdrawn(monkeypatch):
    local = make_local(monkeypatch)
    original = {}

    def browser(_accounts, users, nonce, event):
        original.update(owner=users[0], key=nonce + "-post", body=deepcopy(integration.SYNTHETIC_POST))
        event({"kind": "post", "account": 0, "key": original["key"], "body": original["body"]})
        # The child acknowledged the intended POST, but its server execution has
        # not yet inserted anything when cleanup performs the first GET.
        raise RuntimeError("private-original-request-still-in-flight")

    with pytest.raises(RuntimeError):
        run_local(local, browser)
    assert local.runner.cleanup_failures == 0
    assert len(local.store.records["content"]) == 1
    assert next(iter(local.store.records["content"].values()))["status"] == "deleted"
    # Simulate the original request resuming after auth verification and after
    # cleanup. Production's same-key path must read the tombstone, never revive.
    record, created = asyncio.run(local.api.app.state.community_service.create_post(
        original["owner"], PostCreate.model_validate(original["body"]), original["key"]))
    assert created is False and record["status"] == "deleted"
    assert len(local.store.records["content"]) == 1


def test_delayed_comment_is_settled_before_parent_withdrawal_and_late_insert_cannot_revive(monkeypatch):
    local = make_local(monkeypatch)
    original = {}

    def browser(_accounts, users, nonce, event):
        post_key = nonce + "-post"
        event({"kind": "post", "account": 0, "key": post_key, "body": integration.SYNTHETIC_POST})
        post = integration.payload(integration.require_status(local.runner.api("POST", "/community/posts", 0,
            body=integration.SYNTHETIC_POST, key=post_key), 201))
        integration.require_status(local.runner.api("POST", f"/ops/moderation/posts/{post['id']}/approve", 1,
            body={"expected_revision": 1, "reason": "PC04合成审核"}, key=nonce + "-approve"), 200)
        original.update(owner=users[1], key=nonce + "-comment", post_id=post["id"])
        event({"kind": "comment", "account": 1, "key": original["key"], "post_id": post["id"], "body": integration.SYNTHETIC_COMMENT})
        raise RuntimeError("private-comment-still-in-flight")

    with pytest.raises(RuntimeError):
        run_local(local, browser)
    assert local.runner.cleanup_failures == 0 and len(local.store.records["content"]) == 2
    assert all(record["status"] == "deleted" for record in local.store.records["content"].values())
    # The original already passed its first parent visibility check. Resume at
    # its deterministic insert, which must retain the withdrawn canonical row.
    record, created = asyncio.run(local.api.app.state.community_service._create(original["owner"], "comment",
        {"post_id": original["post_id"], **integration.SYNTHETIC_COMMENT}, original["key"]))
    assert created is False and record["status"] == "deleted"


def test_delayed_report_is_settled_with_same_key_before_resolution(monkeypatch):
    local = make_local(monkeypatch)

    def browser(_accounts, _users, nonce, event):
        event({"kind": "post", "account": 0, "key": nonce + "-post", "body": integration.SYNTHETIC_POST})
        post = integration.payload(integration.require_status(local.runner.api("POST", "/community/posts", 0,
            body=integration.SYNTHETIC_POST, key=nonce + "-post"), 201))
        integration.require_status(local.runner.api("POST", f"/ops/moderation/posts/{post['id']}/approve", 1,
            body={"expected_revision": 1, "reason": "PC04合成审核"}, key=nonce + "-approve"), 200)
        body = {"target_type": "post", "target_id": post["id"], "reason": "privacy", "detail": integration.SYNTHETIC_REPORT_DETAIL}
        event({"kind": "report", "account": 1, "key": nonce + "-report", "target_id": post["id"], "body": body})
        raise RuntimeError("private-report-still-in-flight")

    with pytest.raises(RuntimeError):
        run_local(local, browser)
    assert local.runner.cleanup_failures == 0
    assert len(local.store.records["content_reports"]) == 1
    assert next(iter(local.store.records["content_reports"].values()))["status"] == "resolved"
    assert len([request for request in local.requests if request.method == "POST" and request.url.path == "/api/v2/community/content-reports"]) == 1


def test_unsettleable_comment_on_hidden_parent_does_not_claim_absence_clean(monkeypatch):
    local = make_local(monkeypatch)

    def browser(_accounts, _users, nonce, event):
        event({"kind": "post", "account": 0, "key": nonce + "-post", "body": integration.SYNTHETIC_POST})
        post = integration.payload(integration.require_status(local.runner.api("POST", "/community/posts", 0,
            body=integration.SYNTHETIC_POST, key=nonce + "-post"), 201))
        event({"kind": "comment", "account": 1, "key": nonce + "-comment", "post_id": post["id"], "body": integration.SYNTHETIC_COMMENT})
        # Not published, so no safe comment replay is possible. Lack of a row
        # alone must not be converted into successful settlement evidence.
        raise RuntimeError("private-unsettled-comment")

    with pytest.raises(RuntimeError):
        run_local(local, browser)
    assert local.runner.cleanup_failures > 0 and "synthetic_content_withdrawn" not in local.runner.checks
    assert next(iter(local.store.records["content"].values()))["status"] == "deleted"
    assert not local.valid_tokens


def test_missing_nickname_completion_remains_fail_after_best_effort_restore(monkeypatch):
    local = make_local(monkeypatch)

    def browser(_accounts, _users, _nonce, event):
        event({"kind": "nickname", "account": 0})
        raise RuntimeError("private-nickname-ack-without-receipt")

    with pytest.raises(RuntimeError):
        run_local(local, browser)
    assert local.runner.cleanup_failures > 0 and "synthetic_nicknames_restored" not in local.runner.checks
    assert not local.valid_tokens


def test_unconfirmed_delayed_grant_is_settled_before_revoke_and_late_replay_stays_revoked(monkeypatch):
    local = make_local(monkeypatch)
    original_change = local.role_change
    attempts = []

    def delayed_change(principal, action, reason, key):
        attempts.append((principal, action, reason, key))
        if len(attempts) == 1:
            raise RuntimeError("private-grant-delayed-before-insert")
        return original_change(principal, action, reason, key)

    local.role_change = delayed_change
    with pytest.raises(RuntimeError):
        run_local(local, lambda *_: pytest.fail("browser started after unconfirmed grant"))
    assert local.runner.cleanup_failures == 0
    assert [action for _, action, _, _ in attempts] == ["grant", "grant", "revoke"]
    result = original_change(*attempts[0])
    assert result["role_status"] == "revoked" and result["action_applied"] is True
    assert len(local.store.records["role_bindings"]) == 1


@pytest.mark.parametrize("permanent", [False, True])
def test_token_introspection_failure_retains_issued_token_for_bounded_cleanup(monkeypatch, permanent):
    local = make_local(monkeypatch)
    original_transport = local.transport
    retained_before_failure = []

    def transport(request):
        if request.url.path == "/auth/v1/token/introspect" and request.headers.get("authorization") == "Bearer private-ui-issued-token":
            if permanent or local.runner.stage == "official_sdk_ui":
                return httpx.Response(503, json={"private": "do-not-echo-token"})
        return original_transport(request)

    local.transport = transport

    def browser(accounts, _users, _nonce, event):
        local.valid_tokens["private-ui-issued-token"] = accounts[0].uid
        try:
            event({"kind": "token", "account": 0, "token": "private-ui-issued-token"})
        finally:
            retained_before_failure.append("private-ui-issued-token" in local.runner.browser_tokens)

    with pytest.raises(integration.AcceptanceError):
        run_local(local, browser)
    assert retained_before_failure == [True]
    assert bool(local.runner.cleanup_failures) is permanent
    assert ("private-ui-issued-token" in local.valid_tokens) is permanent
    assert all(record["status"] == "revoked" for record in local.store.records["role_bindings"].values())
    assert_safe_result(local.runner.public_evidence("failed"), local)


def test_browser_cli_itself_is_offline_and_independently_gated():
    script = str(Path(__file__).resolve().parents[2] / "scripts/cloud_community_browser.cjs")
    for arguments, expected, code in (([], "plan", 0), (["--apply"], "blocked", 1)):
        result = subprocess.run(["node", script, *arguments], capture_output=True, text=True, timeout=15)
        assert result.returncode == code
        value = json.loads(result.stdout)
        assert value["status"] == expected and value["real_calls"] is False
