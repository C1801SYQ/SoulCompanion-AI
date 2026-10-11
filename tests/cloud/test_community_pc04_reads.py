"""Incremental private community reads on local synthetic HTTP/Fake adapters only."""

from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from cloud.api.soulcompanion_cloud.app import create_app
from cloud.api.soulcompanion_cloud.auth import AppPrincipal
from cloud.api.soulcompanion_cloud.community.repository import InMemoryCommunityRepository
from cloud.api.soulcompanion_cloud.community.service import append_audit, relation_id, utc_now
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError
from cloud.api.soulcompanion_cloud.repository import InMemoryRepository


BASE = "/api/v2/community"
PRIVATE = "/api/v2/me/community"
OPERATOR = "33333333-3333-4333-8333-333333333333"
POST_BODY = {"title": "合成交流", "body": "仅用于本地验收的虚构分享。", "age_band": "6-8", "topic": "parent-child"}
OWNED_FIELDS = {"id", "body", "author", "created_at", "updated_at", "published_at", "status", "content_revision"}


def auth(account="a", key=None):
    headers = {"Authorization": f"Bearer pc04-account-{account}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


class SyntheticVerifier:
    async def verify(self, token):
        if token not in {"pc04-account-a", "pc04-account-b"}:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        return AppPrincipal(token, "pc04-synthetic-environment")

    async def ready(self):
        return True


class FamilyReadSpy(InMemoryRepository):
    def __init__(self):
        super().__init__(family_identity_enabled=True)
        self.private_calls = []

    async def get_parent_profile(self, *args, **kwargs):
        self.private_calls.append("parent_profile")
        return await super().get_parent_profile(*args, **kwargs)

    async def get_owned(self, *args, **kwargs):
        self.private_calls.append("private_record")
        return await super().get_owned(*args, **kwargs)

    async def list_owned(self, *args, **kwargs):
        self.private_calls.append("private_list")
        return await super().list_owned(*args, **kwargs)


@pytest.fixture
def setup():
    storage, family = InMemoryCommunityRepository(), FamilyReadSpy()
    configuration = Settings(private_rate_limit=1000, preauth_rate_limit=1000)
    with TestClient(create_app(configuration, family, SyntheticVerifier(), storage)) as client:
        owners = {}
        for account in ("a", "b"):
            owners[account] = client.get("/api/v2/me", headers=auth(account)).json()["id"]
            response = client.put("/api/v2/parent-profile", headers=auth(account), json={"nickname": f"合成家长{account}"})
            assert response.status_code == 200
        family.private_calls.clear()
        yield client, storage, family, owners


def pending(client):
    post = client.post(f"{BASE}/posts", headers=auth(key="pc04-post"), json=POST_BODY)
    assert post.status_code == 201
    return post.json()


def review(storage, identifier, action="approve", reason="合成审核意见"):
    """Seed valid reviewed fixtures without implying real moderator authorization."""
    record = deepcopy(storage.records["content"][identifier])
    at = utc_now(record["updated_at"])
    status = {"approve": "published", "reject": "rejected", "hide": "hidden"}[action]
    changes = append_audit(record, {
        "status": status, "updated_at": at, "moderated_at": at,
        "published_at": at if status == "published" else None,
    }, action=action, actor=OPERATOR,
        payload={"expected_revision": record["content_revision"], "reason": reason}, reason=reason)
    storage.records["content"][identifier].update(changes)


def own_content(setup, kind):
    client, storage, _, _ = setup
    post = pending(client)
    if kind == "post":
        return post
    review(storage, post["id"])
    comment = client.post(f"{BASE}/posts/{post['id']}/comments", headers=auth(key="pc04-comment"),
                          json={"body": "合成一级评论。"})
    assert comment.status_code == 201
    return comment.json()


def feedback_path(kind, identifier):
    return f"{PRIVATE}/{kind}s/{identifier}/feedback"


def relation_path(identifier):
    return f"{PRIVATE}/posts/{identifier}/relations"


def assert_safe(response):
    assert response.headers["Cache-Control"] == "no-store"
    for internal in ("owner_id", "principal_id", "actor_id", "action_id", "row_version", "audit", "payload_hash",
                     "idempotency_hash", "initial_payload_hash", "pc04-account", OPERATOR):
        assert internal not in response.text


@pytest.mark.parametrize("suffix", ["relations", "feedback"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-token"}])
def test_new_reads_require_verified_auth_before_resource_disclosure(setup, suffix, headers):
    client, storage, _, _ = setup
    before = deepcopy(storage.records)
    response = client.get(f"{PRIVATE}/posts/{uuid4()}/{suffix}", headers=headers)
    assert response.status_code == 401
    assert storage.records == before


@pytest.mark.parametrize("liked,bookmarked", [(False, False), (True, False), (False, True), (True, True)])
def test_relation_state_reads_both_confirmed_values_without_writes(setup, liked, bookmarked):
    client, storage, family, _ = setup
    post = pending(client)
    review(storage, post["id"])
    for kind, active in (("like", liked), ("bookmark", bookmarked)):
        if active:
            assert client.put(f"{BASE}/posts/{post['id']}/{kind}", headers=auth()).status_code == 200
    before = deepcopy(storage.records)
    family.private_calls.clear()
    response = client.get(relation_path(post["id"]), headers=auth())
    assert response.status_code == 200
    assert response.json() == {"post_id": post["id"], "liked": liked, "bookmarked": bookmarked}
    assert storage.records == before
    assert family.private_calls == []
    assert_safe(response)


def test_relation_state_uses_verified_owner_and_inactive_is_false(setup):
    client, storage, _, owners = setup
    post = pending(client)
    review(storage, post["id"])
    assert client.put(f"{BASE}/posts/{post['id']}/like", headers=auth()).status_code == 200
    assert client.put(f"{BASE}/posts/{post['id']}/bookmark", headers=auth()).status_code == 200
    assert client.delete(f"{BASE}/posts/{post['id']}/bookmark", headers=auth()).status_code == 200
    response = client.get(relation_path(post["id"]), headers=auth("b"), params={"owner_id": owners["a"]})
    assert response.json() == {"post_id": post["id"], "liked": False, "bookmarked": False}
    own = client.get(relation_path(post["id"]), headers=auth())
    assert own.json() == {"post_id": post["id"], "liked": True, "bookmarked": False}
    assert len(storage.records["relations"]) == 2


def test_relation_reads_are_bounded_and_check_public_parent_twice(setup, monkeypatch):
    client, storage, _, _ = setup
    post = pending(client)
    review(storage, post["id"])
    original, calls = storage.get, []

    async def tracked_get(kind, identifier):
        calls.append((kind, identifier))
        return await original(kind, identifier)

    monkeypatch.setattr(storage, "get", tracked_get)
    response = client.get(relation_path(post["id"]), headers=auth())
    assert response.status_code == 200
    assert [kind for kind, _ in calls] == ["content", "relations", "relations", "content"]
    assert calls[0] == calls[-1] == ("content", post["id"])


@pytest.mark.parametrize("state", ["pending", "rejected", "hidden", "deleted"])
def test_relation_state_never_reveals_invisible_parent(setup, state):
    client, storage, _, _ = setup
    post = pending(client)
    if state in {"rejected", "hidden"}:
        review(storage, post["id"], "reject" if state == "rejected" else "hide")
    if state == "deleted":
        assert client.delete(f"{BASE}/posts/{post['id']}", headers=auth(), params={"expected_revision": 1}).status_code == 204
    before = deepcopy(storage.records)
    assert client.get(relation_path(post["id"]), headers=auth()).status_code == 404
    assert storage.records == before


def test_relation_state_fails_if_parent_hidden_during_read(setup, monkeypatch):
    client, storage, _, _ = setup
    post = pending(client)
    review(storage, post["id"])
    original, hidden = storage.get, False

    async def hide_during_read(kind, identifier):
        nonlocal hidden
        result = await original(kind, identifier)
        if kind == "relations" and not hidden:
            hidden = True
            review(storage, post["id"], "hide")
        return result

    monkeypatch.setattr(storage, "get", hide_during_read)
    assert client.get(relation_path(post["id"]), headers=auth()).status_code == 404


@pytest.mark.parametrize("corruption", [
    {"active": 1}, {"kind": "report"}, {"owner_id": "invalid"}, {"post_id": "invalid"},
    {"id": str(uuid4())}, {"_id": str(uuid4())}, {"updated_at": "not-a-time"}, {"row_version": True},
])
def test_corrupt_relation_cannot_be_reported_as_confirmed_state(setup, corruption):
    client, storage, _, owners = setup
    post = pending(client)
    review(storage, post["id"])
    assert client.put(f"{BASE}/posts/{post['id']}/like", headers=auth()).status_code == 200
    storage.records["relations"][relation_id("like", owners["a"], post["id"])].update(corruption)
    response = client.get(relation_path(post["id"]), headers=auth())
    assert response.status_code == 503
    assert_safe(response)


def test_valid_foreign_relation_substitution_is_not_trusted(setup):
    client, storage, _, owners = setup
    post = pending(client)
    review(storage, post["id"])
    assert client.put(f"{BASE}/posts/{post['id']}/like", headers=auth("b")).status_code == 200
    foreign = storage.records["relations"][relation_id("like", owners["b"], post["id"])]
    storage.records["relations"][relation_id("like", owners["a"], post["id"])] = deepcopy(foreign)
    assert client.get(relation_path(post["id"]), headers=auth()).status_code == 503


@pytest.mark.parametrize("kind", ["post", "comment"])
def test_pending_feedback_is_null_and_original_owned_dto_is_unchanged(setup, kind):
    client, _, family, _ = setup
    content = own_content(setup, kind)
    family.private_calls.clear()
    response = client.get(feedback_path(kind, content["id"]), headers=auth())
    assert response.status_code == 200
    assert response.json() == {"target_type": kind, "target_id": content["id"], "content_revision": 1,
                               "status": "pending", "feedback": None}
    old = client.get(f"{PRIVATE}/{kind}s/{content['id']}", headers=auth())
    extra = {"title", "age_band", "topic"} if kind == "post" else {"post_id"}
    assert set(old.json()) == OWNED_FIELDS | extra
    assert family.private_calls == []
    assert_safe(response)


@pytest.mark.parametrize("kind", ["post", "comment"])
@pytest.mark.parametrize("action", ["approve", "reject", "hide"])
def test_feedback_projects_only_current_safe_moderation_entry(setup, kind, action):
    client, storage, family, _ = setup
    content = own_content(setup, kind)
    review(storage, content["id"], action, "合成审核：请保护孩子隐私")
    before = deepcopy(storage.records)
    family.private_calls.clear()
    response = client.get(feedback_path(kind, content["id"]), headers=auth())
    event = storage.records["content"][content["id"]]["audit"][-1]
    assert response.status_code == 200
    assert response.json() == {
        "target_type": kind, "target_id": content["id"], "content_revision": 1,
        "status": {"approve": "published", "reject": "rejected", "hide": "hidden"}[action],
        "feedback": {"action": action, "reason": event["reason"], "at": event["at"], "content_revision": 1},
    }
    assert storage.records == before
    assert family.private_calls == []
    assert_safe(response)


@pytest.mark.parametrize("kind", ["post", "comment"])
def test_latest_moderation_feedback_replaces_previous_same_revision(setup, kind):
    client, storage, _, _ = setup
    content = own_content(setup, kind)
    review(storage, content["id"], "reject", "合成先前拒绝理由")
    review(storage, content["id"], "hide", "合成最新隐藏理由")
    result = client.get(feedback_path(kind, content["id"]), headers=auth()).json()
    assert result["feedback"]["action"] == "hide"
    assert result["feedback"]["reason"] == "合成最新隐藏理由"
    assert "先前" not in str(result)


@pytest.mark.parametrize("action", ["approve", "reject", "hide"])
def test_edit_does_not_reuse_previous_revision_feedback(setup, action):
    client, storage, _, _ = setup
    content = pending(client)
    review(storage, content["id"], action)
    edited = client.patch(f"{BASE}/posts/{content['id']}", headers=auth(),
                          json={**POST_BODY, "body": "合成修改后的新正文。", "expected_revision": 1})
    assert edited.status_code == 200
    result = client.get(feedback_path("post", content["id"]), headers=auth()).json()
    assert result["status"] == "pending" and result["content_revision"] == 2
    assert result["feedback"] is None
    review(storage, content["id"], "reject", "合成第二版反馈")
    result = client.get(feedback_path("post", content["id"]), headers=auth()).json()
    assert result["feedback"]["content_revision"] == 2
    assert result["feedback"]["reason"] == "合成第二版反馈"


@pytest.mark.parametrize("kind", ["post", "comment"])
def test_withdrawn_owner_can_read_historical_feedback_for_unchanged_body(setup, kind):
    client, storage, _, _ = setup
    content = own_content(setup, kind)
    review(storage, content["id"], "approve")
    assert client.delete(f"{BASE}/{kind}s/{content['id']}", headers=auth(), params={"expected_revision": 1}).status_code == 204
    result = client.get(feedback_path(kind, content["id"]), headers=auth()).json()
    assert result["status"] == "deleted" and result["feedback"]["action"] == "approve"


@pytest.mark.parametrize("kind", ["post", "comment"])
def test_feedback_ownership_precedes_validation_of_corrupt_foreign_content(setup, kind):
    client, storage, _, _ = setup
    content = own_content(setup, kind)
    storage.records["content"][content["id"]]["audit"] = "corrupt-sensitive-record"
    foreign = client.get(feedback_path(kind, content["id"]), headers=auth("b"))
    assert foreign.status_code == 404
    own = client.get(feedback_path(kind, content["id"]), headers=auth())
    assert own.status_code == 503
    assert "corrupt-sensitive-record" not in foreign.text + own.text


def test_comment_feedback_remains_private_when_parent_hidden(setup):
    client, storage, _, _ = setup
    content = own_content(setup, "comment")
    review(storage, content["id"], "approve")
    review(storage, content["post_id"], "hide")
    assert client.get(f"{BASE}/comments/{content['id']}").status_code == 404
    own = client.get(feedback_path("comment", content["id"]), headers=auth())
    assert own.status_code == 200 and own.json()["feedback"]["action"] == "approve"
    assert client.get(feedback_path("comment", content["id"]), headers=auth("b")).status_code == 404


@pytest.mark.parametrize("suffix", ["relations", "feedback"])
def test_unknown_ids_are_not_disclosed_and_bad_ids_are_validated(setup, suffix):
    client, _, _, _ = setup
    assert client.get(f"{PRIVATE}/posts/{uuid4()}/{suffix}", headers=auth()).status_code == 404
    assert client.get(f"{PRIVATE}/posts/not-a-uuid/{suffix}", headers=auth()).status_code == 422


@pytest.mark.parametrize("suffix", ["relations", "feedback"])
def test_incomplete_schema_disables_new_reads_without_changes(setup, suffix):
    client, storage, _, _ = setup
    storage.enabled = False
    before = deepcopy(storage.records)
    response = client.get(f"{PRIVATE}/posts/{uuid4()}/{suffix}", headers=auth())
    assert response.status_code == 503 and response.json()["error"]["code"] == "service_unavailable"
    assert storage.records == before


def test_feedback_rejects_unknown_content_kind(setup):
    client, _, _, _ = setup
    assert client.get(f"{PRIVATE}/children/{uuid4()}/feedback", headers=auth()).status_code == 422
