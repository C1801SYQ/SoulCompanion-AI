"""PC03 HTTP boundaries with synthetic accounts and explicitly injected adapters.

Published fixtures are seeded with a valid synthetic audit chain, not with an
HTTP moderation endpoint. Their setup does not assert real moderation or cloud
deployment success.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from cloud.api.soulcompanion_cloud.app import create_app
from cloud.api.soulcompanion_cloud.auth import AppPrincipal
from cloud.api.soulcompanion_cloud.community.repository import InMemoryCommunityRepository
from cloud.api.soulcompanion_cloud.community.service import (
    append_audit,
    content_hash,
    normalized_hash,
    role_binding_id,
    utc_now,
    validate_content,
    validate_role,
)
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError, unavailable
from cloud.api.soulcompanion_cloud.family_identity import parent_profile_id
from cloud.api.soulcompanion_cloud.repository import InMemoryRepository


AGES = ("0-2", "3-5", "6-8", "9-12", "13-15", "16-18")
TOPICS = (
    "parent-child", "emotional-support", "daily-habits", "school-transition",
    "learning-peers", "adolescence", "parent-growth",
)
BASE = "/api/v2/community"
MY = "/api/v2/me/community"
SYNTHETIC_OWNER = "027fe5b4-a04b-427d-b057-509f1bda97b8"
SYNTHETIC_MODERATOR = "9ed4a178-1846-40ac-a7b0-0f991e99ccdc"
CREATED_AT = "2026-10-10T00:00:00.000000Z"
PUBLISHED_AT = "2026-10-10T00:00:01.000000Z"
PUBLIC_POST_FIELDS = {
    "id", "title", "body", "age_band", "topic", "author", "created_at",
    "updated_at", "published_at",
}


class CommunityVerifier:
    def __init__(self):
        self.calls = []

    async def verify(self, token):
        self.calls.append(token)
        if token not in {"community-account-a", "community-account-b", "community-account-c"}:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        return AppPrincipal(token, "synthetic-community-environment")

    async def ready(self):
        return True


class PrivateReadSpy(InMemoryRepository):
    """Catch attempted family access even when its result would be empty."""

    def __init__(self):
        super().__init__(family_identity_enabled=True)
        self.private_calls = []

    async def resolve_user(self, principal):
        self.private_calls.append("resolve_user")
        return await super().resolve_user(principal)

    async def get_parent_profile(self, owner):
        self.private_calls.append("get_parent_profile")
        return await super().get_parent_profile(owner)

    async def get_owned(self, *args, **kwargs):
        self.private_calls.append("get_owned")
        return await super().get_owned(*args, **kwargs)

    async def list_owned(self, *args, **kwargs):
        self.private_calls.append("list_owned")
        return await super().list_owned(*args, **kwargs)


def settings(**overrides):
    # Higher bounded transport limits keep large fixture loops from testing the
    # unrelated per-instance limiter. Distributed write quotas stay unchanged.
    return Settings(
        allowed_origins=("https://client.example.test",),
        private_rate_limit=1000,
        preauth_rate_limit=1000,
        **overrides,
    )


@pytest.fixture
def store():
    return InMemoryCommunityRepository()


@pytest.fixture
def family():
    return PrivateReadSpy()


@pytest.fixture
def verifier():
    return CommunityVerifier()


@pytest.fixture
def client(store, family, verifier):
    with TestClient(create_app(settings(), family, verifier, store)) as value:
        yield value


def auth(account="a", key=None):
    headers = {"Authorization": f"Bearer community-account-{account}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def post_body(**changes):
    return {
        "title": "合成分享：晚饭后聊聊天",
        "body": "这是一段虚构的亲子交流记录，仅用于本地测试。",
        "age_band": "6-8",
        "topic": "parent-child",
        **changes,
    }


def save_profile(client, account="a", nickname="合成家长小禾"):
    response = client.put("/api/v2/parent-profile", headers=auth(account), json={"nickname": nickname})
    assert response.status_code == 200, response.text
    return response.json()


def create_post(client, key="synthetic-post-1", account="a", **changes):
    response = client.post(f"{BASE}/posts", headers=auth(account, key), json=post_body(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def seed_content(store, *, owner=SYNTHETIC_OWNER, age="6-8", topic="parent-child",
                 post_id=None, published=True, identifier=None, published_at=PUBLISHED_AT):
    """Make a strict synthetic post/comment and optional approved test fixture."""
    kind = "post" if post_id is None else "comment"
    identifier = identifier or str(uuid4())
    body = post_body(age_band=age, topic=topic) if kind == "post" else {
        "post_id": post_id, "body": "合成评论：感谢分享，这只是测试内容。",
    }
    record = {
        "_id": identifier, "id": identifier, "kind": kind, "owner_id": owner,
        **body, "public_author_id": parent_profile_id(owner), "author_nickname": "合成家长",
        "status": "pending", "content_revision": 1, "row_version": 1,
        "created_at": CREATED_AT, "updated_at": CREATED_AT,
        "published_at": None, "moderated_at": None,
        "initial_payload_hash": normalized_hash(body),
        "idempotency_hash": sha256(identifier.encode()).hexdigest(),
    }
    if kind == "post":
        record["post_id"] = None
    record["audit"] = [{
        "action_id": str(uuid4()), "actor_id": owner, "action": "create",
        "target_revision": 1, "from_status": None, "to_status": "pending",
        "reason": "", "at": CREATED_AT, "payload_hash": normalized_hash(body),
        "content_hash": content_hash(record),
    }]
    if published:
        changes = append_audit(
            record,
            {"status": "published", "updated_at": published_at,
             "published_at": published_at, "moderated_at": published_at},
            action="approve", actor=SYNTHETIC_MODERATOR,
            payload={"expected_revision": 1, "reason": "合成测试审核"}, reason="合成测试审核",
        )
        record.update(changes)
    validate_content(record)
    store.records["content"][identifier] = deepcopy(record)
    return record


def assert_error(response, status, code=None):
    assert response.status_code == status, response.text
    value = response.json()
    assert set(value) == {"error"}
    assert set(value["error"]) == {"code", "message", "request_id"}
    if code is not None:
        assert value["error"]["code"] == code
    assert value["error"]["request_id"] == response.headers["X-Request-ID"]
    UUID(value["error"]["request_id"])
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    return value["error"]


def hide_seed(store, record):
    """Fixture-only audited hiding; does not exercise a moderation endpoint."""
    at = "2026-10-10T00:00:02.000000Z"
    changes = append_audit(
        record, {"status": "hidden", "published_at": None, "moderated_at": at, "updated_at": at},
        action="hide", actor=SYNTHETIC_MODERATOR,
        payload={"expected_revision": 1, "reason": "合成测试隐藏"}, reason="合成测试隐藏",
    )
    store.records["content"][record["id"]].update(changes)


def grant_operator_seed(client, store, account="c"):
    """Strict synthetic role fixture; no role-creation HTTP API or cloud call."""
    response = client.get("/api/v2/me", headers=auth(account))
    assert response.status_code == 200
    principal = response.json()["id"]
    identifier = role_binding_id(principal)
    record = {
        "_id": identifier, "id": identifier, "principal_id": principal,
        "role": "moderator", "status": "active", "row_version": 1,
        "created_at": CREATED_AT, "updated_at": CREATED_AT, "granted_at": CREATED_AT,
        "granted_by": "cloud-admin-cli",
        "audit": [{
            "action_id": str(uuid4()), "actor_id": "cloud-admin-cli", "action": "grant",
            "target_revision": 1, "from_status": None, "to_status": "active",
            "reason": "合成测试运营授权", "at": CREATED_AT,
            "payload_hash": normalized_hash({"principal_id": principal, "action": "grant", "reason": "合成测试运营授权"}),
        }],
    }
    validate_role(record)
    store.records["role_bindings"][identifier] = deepcopy(record)
    return principal


def revoke_operator_seed(store, principal):
    record = deepcopy(store.records["role_bindings"][role_binding_id(principal)])
    at = utc_now(record["updated_at"])
    record["audit"].append({
        "action_id": str(uuid4()), "actor_id": "cloud-admin-cli", "action": "revoke",
        "target_revision": 2, "from_status": "active", "to_status": "revoked",
        "reason": "合成测试撤销授权", "at": at,
        "payload_hash": normalized_hash({"principal_id": principal, "action": "revoke", "reason": "合成测试撤销授权"}),
    })
    record.update(status="revoked", row_version=2, updated_at=at)
    validate_role(record)
    store.records["role_bindings"][record["id"]] = record


def moderation_path(identifier, action="approve", target="posts"):
    return f"/api/v2/ops/moderation/{target}/{identifier}/{action}"


def review_body(expected_revision=1, reason="合成人工审核确认"):
    return {"expected_revision": expected_revision, "reason": reason}


def apply_review(client, identifier, *, action="approve", target="posts", revision=1, key="synthetic-review"):
    response = client.post(moderation_path(identifier, action, target), headers=auth("c", key), json=review_body(revision))
    assert response.status_code == 200, response.text
    assert response.json()["action_applied"] is True
    return response.json()


def test_existing_family_injection_does_not_enable_community_mock():
    family = InMemoryRepository(family_identity_enabled=True)
    with TestClient(create_app(settings(), family, CommunityVerifier())) as client:
        assert_error(client.get(f"{BASE}/posts"), 503, "service_unavailable")
        assert client.get("/api/v2/readyz").json() == {"status": "healthy"}
        assert not family.users and not family.parent_profiles
        assert_error(client.post(f"{BASE}/posts", json=post_body()), 401, "unauthorized")


def test_anonymous_browsing_does_not_resolve_identity_or_read_private_data(client, store, family, verifier):
    post = seed_content(store)
    comment = seed_content(store, post_id=post["id"])
    pending = seed_content(store, published=False)
    for path in (
        f"{BASE}/posts", f"{BASE}/posts?age_band=6-8&topic=parent-child",
        f"{BASE}/posts/{post['id']}", f"{BASE}/posts/{post['id']}/comments",
        f"{BASE}/comments/{comment['id']}",
    ):
        assert client.get(path).status_code == 200
        # A token is optional public input, not a reason to resolve private data.
        assert client.get(path, headers=auth()).status_code == 200
    assert_error(client.get(f"{BASE}/posts/{pending['id']}"), 404, "not_found")
    assert not verifier.calls and not family.private_calls
    assert not family.users and not family.identities and not family.parent_profiles
    assert all(not records for records in family.records.values())


def test_public_and_owned_dtos_have_exact_safe_fields(client, store):
    save_profile(client)
    created = create_post(client)
    owner = client.get("/api/v2/me", headers=auth()).json()["id"]
    record = seed_content(store, owner=owner)
    public = client.get(f"{BASE}/posts/{record['id']}")
    assert public.status_code == 200
    assert set(public.json()) == PUBLIC_POST_FIELDS
    assert set(public.json()["author"]) == {"id", "nickname"}
    owned = client.get(f"{MY}/posts/{created['id']}", headers=auth())
    assert set(owned.json()) == PUBLIC_POST_FIELDS | {"status", "content_revision"}
    for response in (public, owned):
        for secret in (owner, SYNTHETIC_MODERATOR, "community-account", "owner_id", "_id",
                       "audit", "idempotency_hash", "initial_payload_hash", "moderated_at", "row_version"):
            assert secret not in response.text
    assert public.json()["author"]["id"] == parent_profile_id(owner)


@pytest.mark.parametrize("age", AGES)
def test_each_age_filter_matches_only_explicit_selected_band(client, store, age):
    for candidate in AGES:
        seed_content(store, age=candidate)
    response = client.get(f"{BASE}/posts", params={"age_band": age})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["age_band"] == age


@pytest.mark.parametrize("topic", TOPICS)
def test_each_topic_filter_matches_only_explicit_selected_topic(client, store, topic):
    for candidate in TOPICS:
        seed_content(store, topic=candidate)
    response = client.get(f"{BASE}/posts", params={"topic": topic})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["topic"] == topic


def test_filters_are_and_composed_and_empty_page_is_honest(client, store):
    matching = seed_content(store, age="6-8", topic="parent-child")
    seed_content(store, age="3-5", topic="parent-child")
    seed_content(store, age="6-8", topic="emotional-support")
    seed_content(store, age="6-8", topic="parent-child", published=False)
    response = client.get(f"{BASE}/posts", params={"age_band": "6-8", "topic": "parent-child"})
    assert [item["id"] for item in response.json()["items"]] == [matching["id"]]
    empty = client.get(f"{BASE}/posts", params={"age_band": "16-18", "topic": "adolescence"})
    assert empty.json() == {"items": [], "limit": 20, "next_cursor": None}


@pytest.mark.parametrize("params", [
    {"age_band": "all"}, {"age_band": "18-20"}, {"topic": "diagnosis"},
    {"limit": 0}, {"limit": 51}, {"limit": "false"}, {"cursor": ""},
    {"cursor": "not_a_valid_cursor"}, {"cursor": "x" * 1025},
    {"age_band": '{"$ne":null}'}, {"topic": '{"$in":[]}'},
])
def test_public_query_input_is_bounded_and_does_not_accept_database_operators(client, params):
    assert_error(client.get(f"{BASE}/posts", params=params), 422)


def test_public_pagination_is_stable_at_equal_timestamps_and_filter_bound(client, store):
    identifiers = [seed_content(store)["id"] for _ in range(5)]
    seen, cursor = [], None
    while True:
        response = client.get(f"{BASE}/posts", params={"limit": 2, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200
        result = response.json()
        seen.extend(item["id"] for item in result["items"])
        if cursor is None:
            assert result["next_cursor"] is not None
            wrong_scope = client.get(f"{BASE}/posts", params={"age_band": "6-8", "cursor": result["next_cursor"]})
            assert_error(wrong_scope, 422, "invalid_cursor")
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(identifiers, reverse=True)
    assert len(seen) == len(set(seen)) == 5


@pytest.mark.parametrize("method,path,body", [
    ("POST", f"{BASE}/posts", post_body()),
    ("PATCH", f"{BASE}/posts/{uuid4()}", {**post_body(), "expected_revision": 1}),
    ("DELETE", f"{BASE}/posts/{uuid4()}?expected_revision=1", None),
    ("POST", f"{BASE}/posts/{uuid4()}/comments", {"body": "合成评论"}),
    ("DELETE", f"{BASE}/comments/{uuid4()}?expected_revision=1", None),
    ("GET", f"{MY}/posts", None), ("GET", f"{MY}/comments", None),
    ("GET", f"{MY}/posts/{uuid4()}", None),
])
@pytest.mark.parametrize("headers", [{}, {"x-wx-openid": "synthetic-spoof"}, {"Authorization": "Bearer expired"}])
def test_write_and_private_routes_require_existing_verified_identity(client, method, path, body, headers):
    assert_error(client.request(method, path, headers=headers, json=body), 401, "unauthorized")


def test_writing_requires_parent_nickname_without_child_profile_gate(client, family):
    response = client.post(f"{BASE}/posts", headers=auth(key="profile-required"), json=post_body())
    assert_error(response, 409, "parent_profile_required")
    profile = save_profile(client)
    created = create_post(client)
    assert created["author"] == {"id": profile["id"], "nickname": profile["nickname"]}
    assert not family.records["children"]


def test_private_child_age_and_name_are_not_copied_to_public_author_or_tag(client):
    client.patch("/api/v2/me", headers=auth(), json={"display_name": "合成私有姓名"})
    child = client.post("/api/v2/children", headers=auth(), json={"nickname": "合成私有儿童", "age_band": "0-2"})
    assert child.status_code == 201
    profile = save_profile(client, nickname="合成公开家长")
    created = create_post(client, age_band="16-18")
    assert created["age_band"] == "16-18"
    assert created["author"] == {"id": profile["id"], "nickname": "合成公开家长"}
    assert "合成私有" not in json.dumps(created, ensure_ascii=False)
    assert child.json()["id"] not in json.dumps(created)


@pytest.mark.parametrize("extra", [
    {"owner_id": SYNTHETIC_OWNER}, {"uid": "spoof"}, {"openid": "spoof"},
    {"author": {"id": SYNTHETIC_OWNER, "nickname": "伪造作者"}},
    {"status": "published"}, {"published_at": PUBLISHED_AT}, {"role": "moderator"},
    {"child_profile_id": str(uuid4())}, {"audit": []},
])
def test_creation_cannot_accept_identity_visibility_or_private_child_fields(client, store, extra):
    response = client.post(f"{BASE}/posts", headers=auth(key="spoof-input"), json=post_body(**extra))
    assert_error(response, 422, "validation_error")
    assert not store.records["content"]


@pytest.mark.parametrize("changes", [
    {"title": " "}, {"title": "x" * 81}, {"title": 123}, {"body": "x" * 2001},
    {"body": "<script>alert(1)</script>"}, {"body": "javascript:alert(1)"},
    {"body": "内容\u202e翻转"}, {"title": "标题\n换行"}, {"body": "控制\t字符"},
    {"body": "\ud800"}, {"age_band": None}, {"topic": "medical-expert"},
])
def test_plain_text_validation_handles_lengths_types_controls_and_surrogates(client, changes):
    # ensure_ascii encodes surrogate test input without leaking it to a UTF-8 encoder.
    payload = json.dumps(post_body(**changes), ensure_ascii=True).encode("ascii")
    response = client.post(f"{BASE}/posts", headers={**auth(key="invalid-text"), "Content-Type": "application/json"}, content=payload)
    assert_error(response, 422, "validation_error")


def test_create_normalizes_text_and_idempotency_replays_current_owned_state(client, store):
    save_profile(client)
    initial = post_body(title="  合成标题  ", body="第一行\n第二行")
    first = client.post(f"{BASE}/posts", headers=auth(key="same-create"), json=initial)
    assert first.status_code == 201
    post = first.json()
    assert post["title"] == "合成标题" and post["body"] == "第一行\n第二行"
    assert post["status"] == "pending" and post["content_revision"] == 1
    assert post["published_at"] is None
    assert_error(client.get(f"{BASE}/posts/{post['id']}"), 404)
    changed = client.patch(f"{BASE}/posts/{post['id']}", headers=auth(), json={**post_body(title="合成修改"), "expected_revision": 1})
    assert changed.status_code == 200
    replay = client.post(f"{BASE}/posts", headers=auth(key="same-create"), json=initial)
    assert replay.status_code == 200
    assert replay.json() == changed.json()
    assert replay.json()["content_revision"] == 2
    assert_error(client.post(f"{BASE}/posts", headers=auth(key="same-create"), json=post_body()), 409, "idempotency_conflict")
    assert len(store.records["content"]) == 1
    assert sum(record["used"] for record in store.records["write_quotas"].values()) == 2


@pytest.mark.parametrize("key", [None, "", "x" * 65, "unsafe key", "comma,key", "slash/key"])
def test_creation_requires_unambiguous_safe_idempotency_key(client, store, key):
    save_profile(client)
    assert_error(client.post(f"{BASE}/posts", headers=auth(key=key), json=post_body()), 422)
    assert not store.records["content"]


def test_pending_foreign_and_missing_content_have_uniform_not_found(client, store):
    save_profile(client)
    post = create_post(client)
    foreign = str(uuid4())
    for identifier in (post["id"], foreign):
        assert_error(client.get(f"{BASE}/posts/{identifier}"), 404, "not_found")
        assert_error(client.get(f"{MY}/posts/{identifier}", headers=auth("b")), 404, "not_found")
        assert_error(client.patch(f"{BASE}/posts/{identifier}", headers=auth("b"), json={**post_body(), "expected_revision": 1}), 404, "not_found")
        assert_error(client.delete(f"{BASE}/posts/{identifier}?expected_revision=1", headers=auth("b")), 404, "not_found")
    assert client.get(f"{MY}/posts", headers=auth("b")).json()["items"] == []
    assert store.records["content"][post["id"]]["status"] == "pending"


def test_edit_of_published_content_revokes_visibility_and_refreshes_only_parent_snapshot(client, store):
    old_profile = save_profile(client)
    owner = client.get("/api/v2/me", headers=auth()).json()["id"]
    record = seed_content(store, owner=owner)
    # The fixture carries an independent synthetic public nickname snapshot.
    assert client.get(f"{BASE}/posts/{record['id']}").status_code == 200
    new_profile = save_profile(client, nickname="合成新公开昵称")
    edited = client.patch(f"{BASE}/posts/{record['id']}", headers=auth(), json={**post_body(), "expected_revision": 1})
    assert edited.status_code == 200
    assert edited.json()["status"] == "pending" and edited.json()["content_revision"] == 2
    assert edited.json()["published_at"] is None
    assert edited.json()["author"] == {"id": old_profile["id"], "nickname": new_profile["nickname"]}
    assert_error(client.get(f"{BASE}/posts/{record['id']}"), 404)
    assert_error(client.patch(f"{BASE}/posts/{record['id']}", headers=auth(), json={**post_body(), "expected_revision": 1}), 409, "revision_conflict")
    assert [event["action"] for event in store.records["content"][record["id"]]["audit"]] == ["create", "approve", "edit"]


def test_withdraw_requires_version_keeps_audit_and_is_terminal_idempotent(client, store):
    save_profile(client)
    post = create_post(client)
    path = f"{BASE}/posts/{post['id']}"
    assert_error(client.delete(path, headers=auth()), 422)
    assert_error(client.delete(path, headers=auth(), params={"expected_revision": 2}), 409)
    assert client.delete(path, headers=auth(), params={"expected_revision": 1}).status_code == 204
    assert client.delete(path, headers=auth(), params={"expected_revision": 1}).status_code == 204
    owned = client.get(f"{MY}/posts/{post['id']}", headers=auth()).json()
    assert owned["status"] == "deleted"
    assert_error(client.get(path), 404)
    assert_error(client.patch(path, headers=auth(), json={**post_body(), "expected_revision": 1}), 409, "state_conflict")
    assert len(store.records["content"][post["id"]]["audit"]) == 2


def test_comments_are_one_level_pending_and_parent_visibility_bound(client, store):
    save_profile(client)
    parent = seed_content(store)
    path = f"{BASE}/posts/{parent['id']}/comments"
    created = client.post(path, headers=auth(key="comment-1"), json={"body": "合成评论"})
    assert created.status_code == 201
    comment = created.json()
    assert comment["status"] == "pending" and comment["post_id"] == parent["id"]
    assert client.get(path).json()["items"] == []
    assert client.get(f"{MY}/comments/{comment['id']}", headers=auth()).status_code == 200
    assert_error(client.get(f"{MY}/comments/{comment['id']}", headers=auth("b")), 404)
    assert_error(client.get(f"{BASE}/comments/{comment['id']}"), 404)
    assert_error(client.post(path, headers=auth(key="nested-comment"), json={"body": "合成回复", "parent_comment_id": comment["id"]}), 422)
    assert_error(client.post(f"{BASE}/posts/{comment['id']}/comments", headers=auth(key="wrong-parent"), json={"body": "合成回复"}), 404)
    approved = seed_content(store, post_id=parent["id"])
    assert [row["id"] for row in client.get(path).json()["items"]] == [approved["id"]]
    # A real audit transition, applied only as test-fixture setup, hides parent.
    hide_seed(store, parent)
    assert_error(client.get(path), 404)
    assert_error(client.get(f"{BASE}/comments/{approved['id']}"), 404)
    assert_error(client.post(path, headers=auth(key="hidden-parent"), json={"body": "合成评论"}), 404)
    assert client.delete(f"{BASE}/comments/{comment['id']}?expected_revision=1", headers=auth()).status_code == 204


@pytest.mark.parametrize("payload", [b'\xff{"title":"invalid"}', '{"title":"合成"}'.encode("utf-16"), b'{"title":"bad\x00"}'])
def test_non_utf8_and_nul_json_are_rejected_before_decoding(client, payload):
    assert_error(client.post(f"{BASE}/posts", headers={**auth(key="encoding"), "Content-Type": "application/json"}, content=payload), 422, "validation_error")


def test_request_byte_limit_is_preserved(client, store):
    response = client.post(f"{BASE}/posts", headers={**auth(key="oversize"), "Content-Type": "application/json"}, content=b"x" * 16385)
    assert_error(response, 413, "request_too_large")
    assert not store.records["content"]


@pytest.mark.parametrize("duplicate,status", [("authorization", 401), ("idempotency-key", 400), ("content-type", 400)])
def test_duplicate_security_sensitive_headers_fail_closed(client, duplicate, status):
    headers = [*auth(key="duplicate").items(), ("Content-Type", "application/json")]
    headers.append((duplicate, "second-value"))
    assert_error(client.post(f"{BASE}/posts", headers=headers, content=json.dumps(post_body()).encode()), status)


def test_cors_explicitly_allows_community_idempotency_without_widening_legacy_routes(client):
    headers = {
        "Origin": "https://client.example.test", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
    }
    response = client.options(f"{BASE}/posts", headers=headers)
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "https://client.example.test"
    assert "Idempotency-Key" in response.headers["Access-Control-Allow-Headers"]
    assert_error(client.options("/api/v2/children", headers=headers), 403, "cors_not_allowed")
    assert_error(client.options(f"{BASE}/posts", headers={**headers, "Origin": "https://attacker.example.test"}), 403, "origin_not_allowed")
    assert_error(client.options(f"{BASE}/posts", headers={**headers, "Access-Control-Request-Headers": "authorization,owner-id"}), 403, "cors_not_allowed")


def test_invalid_stored_published_content_fails_closed_and_sanitized(client, store):
    record = seed_content(store)
    store.records["content"][record["id"]]["body"] = "未经对应审核的合成新正文"
    response = client.get(f"{BASE}/posts/{record['id']}")
    assert_error(response, 503, "service_unavailable")
    assert "未经对应" not in response.text and SYNTHETIC_OWNER not in response.text
    assert_error(client.get(f"{BASE}/posts"), 503, "service_unavailable")


def test_store_unavailable_is_standard_failure_not_empty_success(client, store, monkeypatch):
    async def fail(*args, **kwargs):
        raise unavailable()
    monkeypatch.setattr(store, "list", fail)
    assert_error(client.get(f"{BASE}/posts"), 503, "service_unavailable")


def test_request_deadline_does_not_become_empty_community_success():
    class SlowStore(InMemoryCommunityRepository):
        async def list(self, *args, **kwargs):
            await asyncio.sleep(0.1)
            return []

    with TestClient(create_app(settings(upstream_timeout_seconds=0.01, request_timeout_seconds=0.03), PrivateReadSpy(), CommunityVerifier(), SlowStore())) as client:
        assert_error(client.get(f"{BASE}/posts"), 503, "service_unavailable")


@pytest.mark.parametrize("kind", ["like", "bookmark"])
def test_relation_is_private_idempotent_toggle_with_no_duplicate_quota(client, store, kind):
    post = seed_content(store)
    path = f"{BASE}/posts/{post['id']}/{kind}"
    # Cancellation before first activation is a confirmed no-op.
    response = client.delete(path, headers=auth())
    assert response.status_code == 200 and response.json() == {"post_id": post["id"], "kind": kind, "active": False}
    assert not store.records["relations"] and not store.records["write_quotas"]
    for _ in range(3):
        response = client.put(path, headers=auth(), json={})
        assert response.status_code == 200
        assert response.json() == {"post_id": post["id"], "kind": kind, "active": True}
    assert len(store.records["relations"]) == 1
    assert sum(row["used"] for row in store.records["write_quotas"].values()) == 1
    for _ in range(3):
        response = client.delete(path, headers=auth())
        assert response.status_code == 200 and response.json()["active"] is False
    assert len(store.records["relations"]) == 1
    assert sum(row["used"] for row in store.records["write_quotas"].values()) == 2
    assert client.put(path, headers=auth("b")).json()["active"] is True
    assert len(store.records["relations"]) == 2
    assert {row["active"] for row in store.records["relations"].values()} == {True, False}
    assert set(client.get(f"{BASE}/posts/{post['id']}").json()) == PUBLIC_POST_FIELDS


@pytest.mark.parametrize("kind", ["like", "bookmark"])
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("extra", [{"owner_id": SYNTHETIC_OWNER}, {"active": True}, {"status": "published"}])
def test_relation_bodies_cannot_choose_actor_or_state(client, store, kind, method, extra):
    post = seed_content(store)
    assert_error(client.request(method, f"{BASE}/posts/{post['id']}/{kind}", headers=auth(), json=extra), 422, "validation_error")
    assert not store.records["relations"]


@pytest.mark.parametrize("kind", ["like", "bookmark"])
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_relations_require_auth_and_current_public_parent(client, store, kind, method):
    pending = seed_content(store, published=False)
    published = seed_content(store)
    path = f"{BASE}/posts/{published['id']}/{kind}"
    assert_error(client.request(method, path), 401, "unauthorized")
    assert_error(client.request(method, f"{BASE}/posts/{pending['id']}/{kind}", headers=auth()), 404, "not_found")
    hide_seed(store, published)
    assert_error(client.request(method, path, headers=auth()), 404, "not_found")
    assert not store.records["relations"]


def test_private_bookmarks_skip_hidden_posts_and_empty_cursor_keeps_advancing(client, store):
    posts = [seed_content(store) for _ in range(3)]
    for post in posts:
        assert client.put(f"{BASE}/posts/{post['id']}/bookmark", headers=auth()).status_code == 200
    hide_seed(store, posts[2])
    hide_seed(store, posts[1])
    assert_error(client.get(f"{MY}/bookmarks"), 401, "unauthorized")
    assert client.get(f"{MY}/bookmarks", headers=auth("b")).json()["items"] == []
    first = client.get(f"{MY}/bookmarks?limit=1", headers=auth()).json()
    assert first["items"] == [] and first["next_cursor"] is not None
    second = client.get(f"{MY}/bookmarks", params={"limit": 1, "cursor": first["next_cursor"]}, headers=auth()).json()
    assert second["items"] == [] and second["next_cursor"] is not None
    assert second["next_cursor"] != first["next_cursor"]
    final = client.get(f"{MY}/bookmarks", params={"limit": 1, "cursor": second["next_cursor"]}, headers=auth()).json()
    assert [row["id"] for row in final["items"]] == [posts[0]["id"]]
    assert final["next_cursor"] is None
    assert_error(client.get(f"{MY}/bookmarks", params={"cursor": first["next_cursor"]}, headers=auth("b")), 422, "invalid_cursor")
    # Filtering visibility does not delete or expose the private relationships.
    assert len(store.records["relations"]) == 3
    assert all(row["active"] for row in store.records["relations"].values())


def report_body(seed_target_id, **changes):
    return {"target_type": "post", "target_id": seed_target_id, "reason": "privacy", "detail": "合成内容举报说明", **changes}


@pytest.mark.parametrize("reason", ["privacy", "harassment", "unsafe", "spam", "other"])
def test_content_report_allowed_reasons_and_safe_receipt(client, store, reason):
    post = seed_content(store)
    response = client.post(f"{BASE}/content-reports", headers=auth(key=f"report-{reason}"), json=report_body(post["id"], reason=reason))
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert set(receipt) == {"id", "target_type", "target_id", "target_revision", "reason", "detail", "status", "created_at", "handled_at"}
    assert receipt["reason"] == reason and receipt["target_revision"] == 1
    assert receipt["status"] == "open" and receipt["handled_at"] is None
    owner = client.get("/api/v2/me", headers=auth()).json()["id"]
    for value in (owner, "reporter_owner_id", "actor_id", "audit", "row_version", "community-account"):
        assert value not in response.text
    assert "content_reports" not in client.get(f"{BASE}/posts/{post['id']}").text
    assert len(store.records["content_reports"]) == 1


@pytest.mark.parametrize("changes", [
    {"target_type": "posts"}, {"target_type": "family"}, {"target_id": "not-a-uuid"},
    {"reason": "diagnosis"}, {"reason": "other", "detail": " "}, {"detail": "x" * 501},
    {"detail": "<script>bad</script>"}, {"target_revision": 1}, {"status": "resolved"},
    {"reporter_owner_id": SYNTHETIC_OWNER}, {"handled_at": PUBLISHED_AT}, {"actor_id": SYNTHETIC_MODERATOR},
])
def test_content_report_rejects_invalid_or_caller_selected_privileged_fields(client, store, changes):
    post = seed_content(store)
    response = client.post(f"{BASE}/content-reports", headers=auth(key="invalid-report"), json=report_body(post["id"], **changes))
    assert_error(response, 422, "validation_error")
    assert not store.records["content_reports"]


def test_content_report_canonical_same_revision_replay_is_not_extra_write(client, store):
    post = seed_content(store)
    body = report_body(post["id"])
    first = client.post(f"{BASE}/content-reports", headers=auth(key="report-first"), json=body)
    assert first.status_code == 201
    for key in ("report-first", "report-second-key"):
        replay = client.post(f"{BASE}/content-reports", headers=auth(key=key), json=body)
        assert replay.status_code == 200 and replay.json() == first.json()
    assert len(store.records["content_reports"]) == 1
    assert sum(row["used"] for row in store.records["write_quotas"].values()) == 1
    changed = client.post(f"{BASE}/content-reports", headers=auth(key="report-first"), json={**body, "detail": "不同合成说明"})
    assert_error(changed, 409, "idempotency_conflict")
    another = client.post(f"{BASE}/content-reports", headers=auth("b", "other-reporter"), json=body)
    assert another.status_code == 201 and another.json()["id"] != first.json()["id"]
    assert len(store.records["content_reports"]) == 2


def test_report_target_must_be_visible_and_comment_parent_stays_public(client, store):
    parent = seed_content(store)
    pending = seed_content(store, published=False)
    comment = seed_content(store, post_id=parent["id"])
    for target in (pending["id"], str(uuid4())):
        assert_error(client.post(f"{BASE}/content-reports", headers=auth(key="private-report"), json=report_body(target)), 404, "not_found")
    assert_error(client.post(f"{BASE}/content-reports", json=report_body(parent["id"])), 401, "unauthorized")
    body = report_body(comment["id"], target_type="comment")
    response = client.post(f"{BASE}/content-reports", headers=auth(key="comment-report"), json=body)
    assert response.status_code == 201 and response.json()["target_type"] == "comment"
    hide_seed(store, parent)
    assert_error(client.post(f"{BASE}/content-reports", headers=auth("b", "hidden-comment-report"), json=body), 404, "not_found")
    # Existing canonical receipts do not provide a public-hidden-target bypass.
    assert_error(client.post(f"{BASE}/content-reports", headers=auth(key="comment-report"), json=body), 404, "not_found")
    assert len(store.records["content_reports"]) == 1


def test_community_report_does_not_read_or_modify_old_private_cloud_reports(client, store, family):
    owner = client.get("/api/v2/me", headers=auth()).json()["id"]
    child = client.post("/api/v2/children", headers=auth(), json={"nickname": "合成私有儿童"}).json()
    old_id = str(uuid4())
    family.records["reports"][old_id] = {
        "id": old_id, "owner_user_id": owner, "child_profile_id": child["id"],
        "range_start": CREATED_AT, "range_end": CREATED_AT, "created_at": CREATED_AT,
        "summary": "合成旧私有情绪报告，禁止放入内容举报。",
    }
    old_records = deepcopy(family.records)
    family.private_calls.clear()
    post = seed_content(store)
    response = client.post(f"{BASE}/content-reports", headers=auth(key="separate-domain"), json=report_body(post["id"]))
    assert response.status_code == 201
    assert family.records == old_records
    assert family.private_calls == ["resolve_user"]
    assert old_id not in response.text and "私有情绪" not in response.text
    assert client.get("/api/v2/reports", headers=auth()).json()["items"][0]["id"] == old_id


@pytest.mark.parametrize("resource", ["relations", "content_reports"])
def test_interaction_write_failure_is_not_acknowledged_as_success(client, store, monkeypatch, resource):
    post = seed_content(store)
    original_insert = store.insert

    async def unavailable_insert(kind, *args, **kwargs):
        if kind == resource:
            raise unavailable()
        return await original_insert(kind, *args, **kwargs)

    monkeypatch.setattr(store, "insert", unavailable_insert)
    if resource == "relations":
        response = client.put(f"{BASE}/posts/{post['id']}/like", headers=auth())
    else:
        response = client.post(f"{BASE}/content-reports", headers=auth(key="failed-report"), json=report_body(post["id"]))
    assert_error(response, 503, "service_unavailable")
    assert not store.records[resource]


def test_complete_http_review_comment_report_hide_withdraw_flow(client, store):
    save_profile(client)
    save_profile(client, "b", "合成家长小溪")
    post = create_post(client)
    for account in ("a", "b"):
        assert_error(client.post(moderation_path(post["id"]), headers=auth(account, "unprivileged"), json=review_body()), 403, "moderator_required")
    operator = grant_operator_seed(client, store)
    approved = apply_review(client, post["id"], key="approve-post")
    assert approved["content"]["status"] == "published"
    assert client.get(f"{BASE}/posts/{post['id']}").status_code == 200
    comment_response = client.post(f"{BASE}/posts/{post['id']}/comments", headers=auth("b", "comment-for-review"), json={"body": "合成家长交流回复"})
    assert comment_response.status_code == 201 and comment_response.json()["status"] == "pending"
    comment = comment_response.json()
    assert client.get(f"{BASE}/posts/{post['id']}/comments").json()["items"] == []
    apply_review(client, comment["id"], target="comments", key="approve-comment")
    assert client.get(f"{BASE}/comments/{comment['id']}").status_code == 200
    assert client.put(f"{BASE}/posts/{post['id']}/bookmark", headers=auth("b")).status_code == 200
    assert client.put(f"{BASE}/posts/{post['id']}/like", headers=auth("b")).status_code == 200
    report_response = client.post(f"{BASE}/content-reports", headers=auth("b", "flow-report"), json=report_body(post["id"]))
    assert report_response.status_code == 201
    report = report_response.json()
    resolved = client.post(f"/api/v2/ops/content-reports/{report['id']}/resolve", headers=auth("c", "resolve-flow-report"), json={**review_body(), "decision": "resolved"})
    assert resolved.status_code == 200
    assert resolved.json()["report"]["status"] == "resolved"
    # Resolving a report is independently auditable, never an implicit hide.
    assert client.get(f"{BASE}/posts/{post['id']}").status_code == 200
    reporter_receipt = client.post(f"{BASE}/content-reports", headers=auth("b", "flow-report"), json=report_body(post["id"]))
    assert reporter_receipt.status_code == 200 and reporter_receipt.json()["status"] == "resolved"
    assert "audit" not in reporter_receipt.json() and operator not in reporter_receipt.text
    hidden = apply_review(client, post["id"], action="hide", key="hide-flow-post")
    assert hidden["content"]["status"] == "hidden"
    for path in (f"{BASE}/posts/{post['id']}", f"{BASE}/comments/{comment['id']}", f"{BASE}/posts/{post['id']}/comments"):
        assert_error(client.get(path), 404, "not_found")
    for kind in ("like", "bookmark"):
        assert_error(client.put(f"{BASE}/posts/{post['id']}/{kind}", headers=auth("b")), 404)
    assert client.get(f"{MY}/bookmarks", headers=auth("b")).json()["items"] == []
    assert client.delete(f"{BASE}/posts/{post['id']}?expected_revision=1", headers=auth()).status_code == 204
    assert client.get(f"{MY}/posts/{post['id']}", headers=auth()).json()["status"] == "deleted"
    assert [event["action"] for event in store.records["content"][post["id"]]["audit"]] == ["create", "approve", "hide", "withdraw"]


@pytest.mark.parametrize("path", ["/api/v2/ops/moderation", "/api/v2/ops/content-reports"])
def test_operator_queues_require_current_role_not_merely_valid_identity(client, store, path):
    assert_error(client.get(path), 401, "unauthorized")
    assert_error(client.get(path, headers=auth()), 403, "moderator_required")
    principal = grant_operator_seed(client, store)
    assert client.get(path, headers=auth("c")).status_code == 200
    assert_error(client.get(path, headers={"Authorization": "Bearer expired"}), 401, "unauthorized")
    revoke_operator_seed(store, principal)
    assert_error(client.get(path, headers=auth("c")), 403, "moderator_required")


@pytest.mark.parametrize("corruption", [{"role": "admin"}, {"granted_by": "client"}, {"audit": []}, {"status": "published"}, {"row_version": True}, {"extra": "self-granted"}])
def test_corrupt_or_client_shaped_role_never_elevates_operator(client, store, corruption):
    principal = grant_operator_seed(client, store)
    store.records["role_bindings"][role_binding_id(principal)].update(corruption)
    assert_error(client.get("/api/v2/ops/moderation", headers=auth("c")), 503, "service_unavailable")


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "PUT", "DELETE"])
def test_there_is_no_http_self_grant_role_resource(client, store, method):
    before = deepcopy(store.records["role_bindings"])
    for path in ("/api/v2/ops/roles", "/api/v2/community/role-bindings", "/api/v2/me/roles"):
        assert_error(client.request(method, path, headers=auth(), json={"role": "moderator", "status": "active"}), 404, "not_found")
    assert store.records["role_bindings"] == before


@pytest.mark.parametrize("changes", [
    {"actor_id": SYNTHETIC_MODERATOR}, {"status": "published"}, {"role": "moderator"},
    {"owner_id": SYNTHETIC_OWNER}, {"action_id": str(uuid4())}, {"expected_revision": True},
    {"expected_revision": 1.0}, {"reason": " "}, {"reason": "x" * 201}, {"reason": "<script>x</script>"},
])
def test_operator_request_requires_revision_reason_and_cannot_forge_authority(client, store, changes):
    record = seed_content(store, published=False)
    grant_operator_seed(client, store)
    snapshot = deepcopy(store.records["content"])
    assert_error(client.post(moderation_path(record["id"]), headers=auth("c", "invalid-review"), json={**review_body(), **changes}), 422, "validation_error")
    assert store.records["content"] == snapshot


def test_old_approval_key_returns_historical_action_and_current_pending_content(client, store):
    save_profile(client)
    post = create_post(client)
    grant_operator_seed(client, store)
    first = apply_review(client, post["id"], key="approve-original")
    edited = client.patch(f"{BASE}/posts/{post['id']}", headers=auth(), json={**post_body(title="合成修改后需要重新审核"), "expected_revision": 1})
    assert edited.status_code == 200 and edited.json()["content_revision"] == 2
    before_quota = deepcopy(store.records["write_quotas"])
    replay = client.post(moderation_path(post["id"]), headers=auth("c", "approve-original"), json=review_body())
    assert replay.status_code == 200
    assert replay.json()["action_applied"] is True
    assert replay.json()["action_id"] == first["action_id"]
    assert replay.json()["applied_revision"] == 1
    assert replay.json()["content"]["content_revision"] == 2
    assert replay.json()["content"]["status"] == "pending"
    assert store.records["write_quotas"] == before_quota
    assert_error(client.get(f"{BASE}/posts/{post['id']}"), 404)
    assert_error(client.post(moderation_path(post["id"]), headers=auth("c", "approve-original"), json=review_body(reason="不同的合成审核理由")), 409, "idempotency_conflict")
    assert_error(client.post(moderation_path(post["id"]), headers=auth("c", "stale-new-action"), json=review_body()), 409, "revision_conflict")
    assert apply_review(client, post["id"], revision=2, key="approve-new-revision")["content"]["status"] == "published"


def test_revoked_or_expired_operator_cannot_mutate_pending_content(client, store):
    record = seed_content(store, published=False)
    principal = grant_operator_seed(client, store)
    snapshot = deepcopy(store.records["content"])
    assert_error(client.post(moderation_path(record["id"]), headers={"Authorization": "Bearer expired", "Idempotency-Key": "expired-review"}, json=review_body()), 401, "unauthorized")
    revoke_operator_seed(store, principal)
    assert_error(client.post(moderation_path(record["id"]), headers=auth("c", "revoked-review"), json=review_body()), 403, "moderator_required")
    assert store.records["content"] == snapshot


def test_concurrent_http_approve_and_reject_commit_exactly_one_audited_decision(client, store, monkeypatch):
    record = seed_content(store, published=False)
    grant_operator_seed(client, store)
    original_cas = store.cas
    arrived, release = 0, asyncio.Event()

    async def synchronized_cas(kind, *args, **kwargs):
        nonlocal arrived
        if kind == "content":
            arrived += 1
            if arrived == 2:
                release.set()
            await release.wait()
        return await original_cas(kind, *args, **kwargs)

    monkeypatch.setattr(store, "cas", synchronized_cas)
    def request(action):
        return client.post(moderation_path(record["id"], action), headers=auth("c", f"race-{action}"), json=review_body())
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(request, ("approve", "reject")))
    assert sorted(response.status_code for response in responses) == [200, 409]
    current = store.records["content"][record["id"]]
    validate_content(current)
    assert len(current["audit"]) == 2
    assert current["status"] in {"published", "rejected"}
    public = client.get(f"{BASE}/posts/{record['id']}")
    assert public.status_code == (200 if current["status"] == "published" else 404)


def test_failed_moderation_before_commit_leaves_audit_and_pending_state_unchanged(client, store, monkeypatch):
    record = seed_content(store, published=False)
    grant_operator_seed(client, store)
    snapshot = deepcopy(store.records["content"])
    original_cas = store.cas
    async def fail_content_cas(kind, *args, **kwargs):
        if kind == "content":
            raise unavailable()
        return await original_cas(kind, *args, **kwargs)
    monkeypatch.setattr(store, "cas", fail_content_cas)
    assert_error(client.post(moderation_path(record["id"]), headers=auth("c", "failed-cas"), json=review_body()), 503, "service_unavailable")
    assert store.records["content"] == snapshot
    assert_error(client.get(f"{BASE}/posts/{record['id']}"), 404)


def test_indeterminate_ack_after_atomic_commit_recovers_same_action_without_reapproval(client, store, monkeypatch):
    record = seed_content(store, published=False)
    grant_operator_seed(client, store)
    original_cas = store.cas
    lost = False
    async def lose_content_ack(kind, *args, **kwargs):
        nonlocal lost
        committed = await original_cas(kind, *args, **kwargs)
        if kind == "content" and committed and not lost:
            lost = True
            raise unavailable()
        return committed
    monkeypatch.setattr(store, "cas", lose_content_ack)
    path = moderation_path(record["id"])
    assert_error(client.post(path, headers=auth("c", "lost-ack"), json=review_body()), 503, "service_unavailable")
    # The write committed with valid audit; a missing ACK is indeterminate,
    # not evidence that a real database reverted its accepted update.
    current = deepcopy(store.records["content"][record["id"]])
    validate_content(current)
    assert current["status"] == "published" and len(current["audit"]) == 2
    before_quota = deepcopy(store.records["write_quotas"])
    replay = client.post(path, headers=auth("c", "lost-ack"), json=review_body())
    assert replay.status_code == 200 and replay.json()["action_applied"] is True
    assert replay.json()["action_id"] == current["audit"][-1]["action_id"]
    assert store.records["content"][record["id"]] == current
    assert store.records["write_quotas"] == before_quota


def test_moderation_queue_is_bounded_stable_and_protected_includes_pending_comments(client, store):
    grant_operator_seed(client, store)
    parent = seed_content(store)
    records = [seed_content(store, published=False) for _ in range(3)]
    records.append(seed_content(store, post_id=parent["id"], published=False))
    first = client.get("/api/v2/ops/moderation?limit=2", headers=auth("c"))
    assert first.status_code == 200
    first_page = first.json()
    assert len(first_page["items"]) == 2 and first_page["next_cursor"] is not None
    second = client.get("/api/v2/ops/moderation", headers=auth("c"), params={"limit": 2, "cursor": first_page["next_cursor"]})
    assert second.status_code == 200 and second.json()["next_cursor"] is None
    items = [*first_page["items"], *second.json()["items"]]
    assert [row["id"] for row in items] == sorted((row["id"] for row in records), reverse=True)
    assert {row["kind"] for row in items} == {"post", "comment"}
    assert all("audit" in row and "owner_id" not in row for row in items)
    assert_error(client.get("/api/v2/ops/moderation", headers=auth("c"), params={"status": "published", "cursor": first_page["next_cursor"]}), 422, "invalid_cursor")
    assert_error(client.get("/api/v2/ops/moderation?limit=51", headers=auth("c")), 422)
    assert_error(client.get("/api/v2/ops/moderation?status=admin", headers=auth("c")), 422)


def test_report_operator_queue_resolve_version_and_replay_never_leak_to_author(client, store):
    grant_operator_seed(client, store)
    post = seed_content(store)
    report = client.post(f"{BASE}/content-reports", headers=auth("b", "protected-report"), json=report_body(post["id"])).json()
    queue = client.get("/api/v2/ops/content-reports", headers=auth("c"))
    assert queue.status_code == 200 and [row["id"] for row in queue.json()["items"]] == [report["id"]]
    assert queue.json()["items"][0]["report_revision"] == 1
    assert "audit" in queue.json()["items"][0]
    assert_error(client.get("/api/v2/ops/content-reports", headers=auth()), 403, "moderator_required")
    path = f"/api/v2/ops/content-reports/{report['id']}/resolve"
    body = {**review_body(), "decision": "dismissed"}
    assert_error(client.post(path, headers=auth("c", "stale-report"), json={**body, "expected_revision": 2}), 409, "revision_conflict")
    result = client.post(path, headers=auth("c", "dismiss-report"), json=body)
    assert result.status_code == 200 and result.json()["report"]["status"] == "dismissed"
    assert result.json()["report"]["report_revision"] == 2
    quota = deepcopy(store.records["write_quotas"])
    replay = client.post(path, headers=auth("c", "dismiss-report"), json=body)
    assert replay.status_code == 200 and replay.json() == result.json()
    assert store.records["write_quotas"] == quota
    assert_error(client.post(path, headers=auth("c", "dismiss-report"), json={**body, "reason": "不同的合成处理原因"}), 409, "idempotency_conflict")
    assert_error(client.post(path, headers=auth("c", "new-terminal-action"), json={**body, "expected_revision": 2}), 409, "state_conflict")
    assert client.get("/api/v2/ops/content-reports", headers=auth("c")).json()["items"] == []
    assert client.get("/api/v2/ops/content-reports?status=dismissed", headers=auth("c")).json()["items"][0]["id"] == report["id"]
    assert client.get(f"{BASE}/posts/{post['id']}").status_code == 200
    assert_error(client.get(f"{BASE}/content-reports/{report['id']}", headers=auth()), 404)
    assert report["id"] not in client.get(f"{BASE}/posts/{post['id']}").text
