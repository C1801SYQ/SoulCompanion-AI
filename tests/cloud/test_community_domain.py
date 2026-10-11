"""PC03 domain behavior on synthetic, explicitly injected storage only."""

import asyncio
import base64
from copy import deepcopy
import json
from uuid import UUID, uuid4

from pydantic import ValidationError
import pytest

from cloud.api.soulcompanion_cloud.community.models import (
    CommentCreate, ContentReportCreate, ContentReportResolve, ModerationAction, PostCreate, PostPatch,
)
from cloud.api.soulcompanion_cloud.community.pagination import decode_cursor, encode_cursor, normalize_limit
from cloud.api.soulcompanion_cloud.community.repository import InMemoryCommunityRepository, matches
from cloud.api.soulcompanion_cloud.community.service import (
    CommunityService, append_audit, content_dto, deterministic_id, idempotency_key,
    content_report_dto, normalized_hash, relation_id, role_binding_id, utc_now,
    validate_content, validate_content_report, validate_relation, validate_role,
)
from cloud.api.soulcompanion_cloud.errors import CloudError, unavailable
from cloud.api.soulcompanion_cloud.family_identity import parent_profile_id
from cloud.api.soulcompanion_cloud.repository import InMemoryRepository


OWNER_A = "11111111-1111-4111-8111-111111111111"
OWNER_B = "22222222-2222-4222-8222-222222222222"
OPERATOR = "33333333-3333-4333-8333-333333333333"
AGES = ("0-2", "3-5", "6-8", "9-12", "13-15", "16-18")
TOPICS = ("parent-child", "emotional-support", "daily-habits", "school-transition", "learning-peers", "adolescence", "parent-growth")


def run(awaitable):
    return asyncio.run(awaitable)


def post_body(**changes):
    return PostCreate(title="合成家长分享", body="这是虚构的交流内容。", age_band="6-8", topic="parent-child", **changes)


@pytest.fixture
def domain():
    family = InMemoryRepository(family_identity_enabled=True)
    run(family.save_parent_profile(OWNER_A, "合成小禾"))
    run(family.save_parent_profile(OWNER_B, "合成青木"))
    storage = InMemoryCommunityRepository()
    return CommunityService(storage, family), storage, family


def created(domain, key="synthetic-post-01"):
    return run(domain[0].create_post(OWNER_A, post_body(), key))[0]


def transition(storage, identifier, action="approve", reason="合成人工审核理由"):
    """Fixture-only simulated reviewer writes; production review is implemented in PC03-F."""
    record = deepcopy(storage.records["content"][identifier])
    at = utc_now(record["updated_at"])
    target = {"approve": "published", "reject": "rejected", "hide": "hidden"}[action]
    changes = append_audit(record, {
        "status": target, "updated_at": at, "moderated_at": at,
        "published_at": at if target == "published" else None,
    }, action=action, actor=OPERATOR, payload={"expected_revision": record["content_revision"], "reason": reason}, reason=reason)
    storage.records["content"][identifier] = {**record, **changes}
    return deepcopy(storage.records["content"][identifier])


def assert_error(status, call, code=None):
    with pytest.raises(CloudError) as error:
        run(call)
    assert error.value.status == status
    if code is not None:
        assert error.value.code == code
    return error.value


@pytest.mark.parametrize("age", AGES)
@pytest.mark.parametrize("topic", TOPICS)
def test_all_six_age_bands_and_seven_topics_are_strict_contracts(age, topic):
    value = PostCreate(title="合成标题", body="合成正文", age_band=age, topic=topic)
    assert value.age_band == age and value.topic == topic


@pytest.mark.parametrize("changes", [
    {"title": ""}, {"title": " "}, {"title": "中" * 81}, {"body": "中" * 2001},
    {"body": ""}, {"body": "\ud800"}, {"body": "hello\u202Eworld"},
    {"body": "<script>alert(1)</script>"}, {"body": "<img src=x>"},
    {"body": "javascript:alert(1)"}, {"body": "data:text/html,<b>x</b>"},
    {"title": "\n标题"}, {"body": "\r\n文本"}, {"body": "\t文本"},
    {"body": 1}, {"title": True}, {"age_band": "all"}, {"age_band": None},
    {"topic": "diagnosis"}, {"owner_id": OWNER_B}, {"status": "published"},
])
def test_invalid_content_and_forbidden_fields_rejected(changes):
    payload = {"title": "合成标题", "body": "合成正文", "age_band": "6-8", "topic": "parent-child", **changes}
    with pytest.raises(ValidationError):
        PostCreate.model_validate(payload)


def test_unicode_nfc_multiline_and_actual_length_limits():
    value = PostCreate(title="  e\u0301 ", body="  第一段\n第二段  ", age_band="0-2", topic="parent-growth")
    assert value.title == "é" and value.body == "第一段\n第二段"
    assert len(CommentCreate(body="🙂" * 1000).body.encode("utf-8")) == 4000
    with pytest.raises(ValidationError):
        CommentCreate(body="x" * 1001)
    with pytest.raises(ValidationError):
        PostPatch(title="标题", body="正文", age_band="6-8", topic="parent-child", expected_revision=True)


@pytest.mark.parametrize("key", ["", "a" * 65, "含中文", "two words", "\nvalue", "<script>", 1, None, "a/b", "a\t"])
def test_idempotency_header_validation(key):
    with pytest.raises(CloudError) as error:
        idempotency_key(key)
    assert error.value.status == 422


def test_created_pending_never_public_and_has_atomic_initial_audit(domain):
    service, storage, _ = domain
    value, is_new = run(service.create_post(OWNER_A, post_body(), "post-key"))
    assert is_new and value["status"] == "pending" and value["content_revision"] == 1
    assert value["published_at"] is None
    record = storage.records["content"][value["id"]]
    assert record["row_version"] == 1 and record["audit"][0]["action"] == "create"
    assert record["audit"][0]["to_status"] == "pending"
    assert run(service.list_posts())["items"] == []
    assert_error(404, service.get_post(value["id"]))
    assert run(service.get_owned(OWNER_A, "post", value["id"])) == value
    assert_error(404, service.get_owned(OWNER_B, "post", value["id"]))


def test_create_idempotency_uses_initial_input_after_edit_and_nickname_change(domain):
    service, storage, family = domain
    first = created(domain, "replay-key")
    run(family.save_parent_profile(OWNER_A, "合成改名"))
    edited = run(service.edit_post(OWNER_A, first["id"], PostPatch(
        title="修改后的合成内容", body="新的合成正文", age_band="9-12", topic="parent-growth", expected_revision=1,
    )))
    quota_before = deepcopy(storage.records["write_quotas"])
    replay, is_new = run(service.create_post(OWNER_A, post_body(), "replay-key"))
    assert not is_new and replay == edited and replay["content_revision"] == 2
    assert replay["author"]["nickname"] == "合成改名"
    assert storage.records["write_quotas"] == quota_before
    changed = PostCreate(title="不同的输入", body="合成正文", age_band="6-8", topic="parent-child")
    assert_error(409, service.create_post(OWNER_A, changed, "replay-key"), "idempotency_conflict")
    assert len(storage.records["content"]) == 1


def test_public_and_private_dtos_never_leak_ownership_child_fields_or_audit(domain):
    service, storage, family = domain
    value = created(domain)
    transition(storage, value["id"])
    record = storage.records["content"][value["id"]]
    record.update(openid="synthetic-private-openid", child_name="synthetic-private-child", child_profile_id=str(uuid4()))
    public = run(service.get_post(value["id"]))
    private = run(service.get_owned(OWNER_A, "post", value["id"]))
    for result in (public, private):
        encoded = json.dumps(result)
        for forbidden in ("owner_id", "actor_id", "audit", "openid", "child_name", "child_profile_id", "initial_payload_hash", "row_version"):
            assert forbidden not in encoded
        assert result["author"]["id"] == parent_profile_id(OWNER_A) != OWNER_A
    run(family.save_parent_profile(OWNER_A, "合成新昵称"))
    assert run(service.get_post(value["id"]))["author"]["nickname"] == "合成小禾"


def test_profile_is_explicit_public_identity_and_children_are_not_read(domain):
    service, storage, family = domain
    class ProfileOnly:
        async def get_parent_profile(self, owner):
            return await family.get_parent_profile(owner)
        def __getattr__(self, name):
            raise AssertionError(f"No private family read is permitted: {name}")
    service.family_repository = ProfileOnly()
    value = created(domain)
    assert value["author"]["nickname"] == "合成小禾"
    assert not family.records["children"] and not family.records["reports"]
    family.parent_profiles.clear()
    assert run(service.list_posts())["items"] == []
    assert_error(409, service.create_post(OWNER_B, post_body(), "no-profile"), "parent_profile_required")
    assert len(storage.records["content"]) == 1


@pytest.mark.parametrize("corruption", [
    {"id": OWNER_A}, {"owner_user_id": OWNER_B}, {"nickname": "<private>"}, {"nickname": " 合成小禾 "},
])
def test_invalid_parent_profile_fails_closed_without_private_name_fallback(domain, corruption):
    service, storage, family = domain
    family.parent_profiles[parent_profile_id(OWNER_A)].update(corruption)
    assert_error(503, service.create_post(OWNER_A, post_body(), "bad-profile"))
    assert not storage.records["content"]


@pytest.mark.parametrize("prior", ["pending", "published", "rejected", "hidden"])
def test_edit_always_requires_new_review_and_preserves_audit(domain, prior):
    service, storage, _ = domain
    value = created(domain)
    if prior != "pending":
        transition(storage, value["id"], {"published": "approve", "rejected": "reject", "hidden": "hide"}[prior])
    old_audit = deepcopy(storage.records["content"][value["id"]]["audit"])
    result = run(service.edit_post(OWNER_A, value["id"], PostPatch(
        title="新的合成标题", body="重新待审的正文", age_band="0-2", topic="daily-habits", expected_revision=1,
    )))
    assert result["status"] == "pending" and result["content_revision"] == 2 and result["published_at"] is None
    assert storage.records["content"][value["id"]]["audit"][:-1] == old_audit
    assert_error(404, service.get_post(value["id"]))
    assert_error(409, service.edit_post(OWNER_A, value["id"], PostPatch(expected_revision=1, **post_body().model_dump())))
    assert_error(404, service.edit_post(OWNER_B, value["id"], PostPatch(expected_revision=2, **post_body().model_dump())))


def test_withdraw_is_soft_terminal_and_duplicate_does_not_consume_quota(domain):
    service, storage, _ = domain
    value = created(domain)
    transition(storage, value["id"])
    old_audit = deepcopy(storage.records["content"][value["id"]]["audit"])
    assert_error(404, service.withdraw(OWNER_B, "post", value["id"], 1))
    assert_error(409, service.withdraw(OWNER_A, "post", value["id"], 2))
    run(service.withdraw(OWNER_A, "post", value["id"], 1))
    snapshot = deepcopy(storage.records)
    run(service.withdraw(OWNER_A, "post", value["id"], 1))
    assert storage.records == snapshot
    record = storage.records["content"][value["id"]]
    assert record["body"] == post_body().body and record["status"] == "deleted"
    assert record["audit"][:-1] == old_audit and record["audit"][-1]["action"] == "withdraw"
    assert_error(404, service.get_post(value["id"]))
    assert_error(409, service.edit_post(OWNER_A, value["id"], PostPatch(expected_revision=1, **post_body().model_dump())), "state_conflict")


def test_public_comments_require_public_parent_before_after_and_direct_url(domain):
    service, storage, _ = domain
    value = created(domain)
    assert_error(404, service.create_comment(OWNER_B, value["id"], CommentCreate(body="合成评论"), "comment-key"))
    transition(storage, value["id"])
    comment, is_new = run(service.create_comment(OWNER_B, value["id"], CommentCreate(body="合成评论"), "comment-key"))
    assert is_new and comment["status"] == "pending"
    assert run(service.list_comments(value["id"]))["items"] == []
    assert_error(404, service.get_comment(comment["id"]))
    transition(storage, comment["id"])
    assert run(service.get_comment(comment["id"]))["body"] == "合成评论"
    assert run(service.list_comments(value["id"]))["items"][0]["id"] == comment["id"]
    transition(storage, value["id"], "hide")
    assert_error(404, service.get_comment(comment["id"]))
    assert_error(404, service.list_comments(value["id"]))
    assert_error(404, service.create_comment(OWNER_A, value["id"], CommentCreate(body="新评论"), "new-comment"))
    assert run(service.get_owned(OWNER_B, "comment", comment["id"]))["status"] == "published"


def test_parent_hides_during_comment_query_cannot_leak_results(domain):
    service, storage, _ = domain
    value = created(domain)
    transition(storage, value["id"])
    comment, _ = run(service.create_comment(OWNER_B, value["id"], CommentCreate(body="合成评论"), "parent-race"))
    transition(storage, comment["id"])
    original_list = storage.list
    async def hide_during_list(*args, **kwargs):
        result = await original_list(*args, **kwargs)
        transition(storage, value["id"], "hide")
        return result
    storage.list = hide_during_list
    assert_error(404, service.list_comments(value["id"]))


def test_same_timestamp_keyset_pages_no_duplicates_or_omissions_and_bound_filters(domain):
    service, storage, _ = domain
    value = created(domain)
    template = transition(storage, value["id"])
    storage.records["content"].clear()
    for index in range(57):
        record = deepcopy(template)
        record["id"] = record["_id"] = str(UUID(int=index + 1))
        storage.records["content"][record["id"]] = record
    ids, cursor = [], None
    while True:
        result = run(service.list_posts(age_band="6-8", topic="parent-child", limit=7, cursor=cursor))
        ids.extend(item["id"] for item in result["items"])
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert len(ids) == len(set(ids)) == 57 and ids == sorted(ids, reverse=True)
    first = run(service.list_posts(age_band="6-8", topic="parent-child", limit=7))
    assert_error(422, service.list_posts(age_band="0-2", topic="parent-child", cursor=first["next_cursor"]))
    assert run(service.list_posts(age_band="0-2", topic="parent-child"))["items"] == []
    assert run(service.list_posts(age_band="6-8", topic="adolescence"))["items"] == []


def test_owned_list_scope_and_private_projection_are_owner_bound(domain):
    service, storage, _ = domain
    first = created(domain)
    run(service.create_post(OWNER_A, post_body(), "second"))
    run(service.create_post(OWNER_B, post_body(), "other"))
    result = run(service.list_owned(OWNER_A, "post", limit=1))
    assert len(result["items"]) == 1 and result["next_cursor"]
    assert_error(422, service.list_owned(OWNER_B, "post", cursor=result["next_cursor"]))
    assert {item["id"] for item in run(service.list_owned(OWNER_B, "post"))["items"]} != {first["id"]}
    original_list = storage.list
    async def leaking_list(*args):
        rows = await original_list(*args)
        rows[0]["owner_id"] = OWNER_B
        return rows
    storage.list = leaking_list
    assert_error(503, service.list_owned(OWNER_A, "post"))


@pytest.mark.parametrize("corruption", [
    {"content_revision": True}, {"row_version": True}, {"status": "published"},
    {"audit": []}, {"published_at": "2026-99-10T00:00:00.000000Z"},
    {"body": "changed-without-review"}, {"public_author_id": OWNER_A},
    {"author_nickname": "秘密孩子"}, {"moderated_at": None},
])
def test_malformed_or_unaudited_publication_never_public(domain, corruption):
    service, storage, _ = domain
    value = created(domain)
    if corruption != {"status": "published"}:
        transition(storage, value["id"])
    storage.records["content"][value["id"]].update(corruption)
    assert_error(503, service.get_post(value["id"]))
    if storage.records["content"][value["id"]]["status"] == "published":
        assert_error(503, service.list_posts())


def test_history_capacity_preserves_hide_and_withdraw_slots(domain):
    service, storage, _ = domain
    value = created(domain)
    record = deepcopy(storage.records["content"][value["id"]])
    # Exercise history boundaries directly, without bypassing production daily quotas.
    for revision in range(2, 31):
        changes = append_audit(record, {"content_revision": revision, "updated_at": utc_now(record["updated_at"])},
                               action="edit", actor=OWNER_A, payload={"expected_revision": revision - 1})
        record = {**record, **changes}
    assert len(record["audit"]) == 30
    storage.records["content"][record["id"]] = record
    assert_error(409, service.edit_post(OWNER_A, record["id"], PostPatch(expected_revision=30, **post_body().model_dump())), "audit_capacity_exceeded")
    transition(storage, record["id"], "hide")
    assert len(storage.records["content"][record["id"]]["audit"]) == 31
    run(service.withdraw(OWNER_A, "post", record["id"], 30))
    assert len(storage.records["content"][record["id"]]["audit"]) == 32
    assert run(service.get_owned(OWNER_A, "post", record["id"]))["status"] == "deleted"


def test_unknown_or_zero_match_acknowledgment_never_returns_success(domain):
    service, storage, _ = domain
    value = created(domain)
    original = deepcopy(storage.records["content"][value["id"]])
    async def conflict_cas(*args):
        return False
    storage.cas = conflict_cas
    # Bypass only quota here to isolate content CAS; quota failures are independently covered below.
    async def accepted_quota(*args):
        return None
    storage.consume_quota = accepted_quota
    assert_error(409, service.edit_post(OWNER_A, value["id"], PostPatch(expected_revision=1, **post_body().model_dump())))
    async def unconfirmed(*args):
        raise unavailable()
    storage.cas = unconfirmed
    assert_error(503, service.withdraw(OWNER_A, "post", value["id"], 1))
    assert storage.records["content"][value["id"]] == original


def test_concurrent_edits_only_one_conditional_update_succeeds(domain):
    service, storage, _ = domain
    value = created(domain)
    original_get, original_cas = storage.get, storage.cas
    async def race():
        seen = 0
        ready = asyncio.Event()
        async def simultaneous_get(kind, identifier):
            nonlocal seen
            result = await original_get(kind, identifier)
            if kind == "content" and identifier == value["id"]:
                seen += 1
                if seen == 2:
                    ready.set()
                await ready.wait()
            return result
        storage.get = simultaneous_get
        async def do_edit(title):
            try:
                return await service.edit_post(OWNER_A, value["id"], PostPatch(
                    title=title, body="合成正文", age_band="6-8", topic="parent-child", expected_revision=1,
                ))
            except CloudError as error:
                return error.status
        return await asyncio.gather(do_edit("并发合成一"), do_edit("并发合成二"))
    result = run(race())
    assert sum(isinstance(item, dict) for item in result) == 1 and 409 in result
    record = storage.records["content"][value["id"]]
    assert record["content_revision"] == 2 and len(record["audit"]) == 2
    assert storage.cas == original_cas


def test_daily_distributed_quota_still_blocks_new_creates_and_replay_is_free(domain):
    service, storage, _ = domain
    for index in range(10):
        run(service.create_post(OWNER_A, post_body(), f"daily-{index}"))
    assert_error(429, service.create_post(OWNER_A, post_body(), "daily-exhausted"), "community_quota_exceeded")
    assert run(service.create_post(OWNER_A, post_body(), "daily-0"))[1] is False
    assert len(storage.records["content"]) == 10


@pytest.mark.parametrize("kind", ["post", "comment"])
def test_withdrawal_privacy_path_is_not_blocked_by_exhausted_contribution_quota(domain, kind):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    owner, identifier, maximum = OWNER_A, post["id"], 10
    if kind == "comment":
        comment, _ = run(service.create_comment(OWNER_B, post["id"], CommentCreate(body="合成待撤回评论"), "quota-withdraw-comment"))
        owner, identifier, maximum = OWNER_B, comment["id"], 100
        transition(storage, identifier)
    for _ in range(maximum - 1):
        run(storage.consume_quota(owner, kind))
    assert_error(429, storage.consume_quota(owner, kind), "community_quota_exceeded")
    quotas = deepcopy(storage.records["write_quotas"])
    run(service.withdraw(owner, kind, identifier, 1))
    assert storage.records["content"][identifier]["status"] == "deleted"
    assert storage.records["write_quotas"] == quotas


def test_disabled_schema_gate_does_not_read_profile_or_content(domain):
    service, storage, _ = domain
    storage.enabled = False
    async def forbidden(*args):
        raise AssertionError("No content/profile read before schema gate.")
    storage.get = forbidden
    service.family_repository.get_parent_profile = forbidden
    assert_error(503, service.list_posts())
    assert_error(503, service.create_post(OWNER_A, post_body(), "disabled"))


@pytest.mark.parametrize("value", [0, 51, True, "20", None, 1.5])
def test_limit_rejects_out_of_range_and_ambiguous_types(value):
    with pytest.raises(CloudError) as error:
        normalize_limit(value)
    assert error.value.status == 422


@pytest.mark.parametrize("cursor", ["", "=", "!", "x" * 1025, "e30", 1, "eyJ2Ijp0cnVlfQ"])
def test_cursor_invalid_encoding_or_object(cursor):
    with pytest.raises(CloudError) as error:
        decode_cursor(cursor, {"list": "public_posts"})
    assert error.value.status == 422


def test_cursor_rejects_duplicate_keys_noncanonical_time_uuid_and_scope():
    scope = {"list": "test"}
    record = {"id": OWNER_A, "published_at": "2026-10-10T00:00:00.000000Z"}
    cursor = encode_cursor(record, scope, "published_at")
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    for field, value in [("v", True), ("time", "2026-10-10T00:00:00Z"), ("time", "2026-19-10T00:00:00.000000Z"), ("id", OWNER_A.upper()), ("scope", "different")]:
        altered = {**payload, field: value}
        # OWNER_A is digits only, use an actually uppercase UUID for canonical check.
        if field == "id":
            altered[field] = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
        bad = base64.urlsafe_b64encode(json.dumps(altered, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
        with pytest.raises(CloudError):
            decode_cursor(bad, scope)
    duplicate = '{"v":1,"v":1,"scope":"x","time":"2026-10-10T00:00:00.000000Z","id":"' + OWNER_A + '"}'
    with pytest.raises(CloudError):
        decode_cursor(base64.urlsafe_b64encode(duplicate.encode()).decode().rstrip("="), scope)


def test_noncanonical_resource_and_wrong_kind_are_not_read(domain):
    service, _, _ = domain
    value = created(domain)
    assert_error(422, service.get_post("not-a-uuid"))
    assert_error(404, service.get_owned(OWNER_A, "comment", value["id"]))
    assert_error(404, service.get_comment(value["id"]))


def test_deterministic_keys_separate_owners_kinds_and_payload():
    assert deterministic_id("post", OWNER_A, "same") == deterministic_id("post", OWNER_A, "same")
    assert deterministic_id("post", OWNER_A, "same") != deterministic_id("post", OWNER_B, "same")
    assert deterministic_id("post", OWNER_A, "same") != deterministic_id("comment", OWNER_A, "same")


def test_strict_fake_query_never_accepts_unrecognized_operators():
    with pytest.raises(CloudError):
        matches({"id": "x"}, {"id": {"$where": "script"}})


def test_validation_rejects_broken_audit_prefix_and_byte_capacity(domain):
    service, storage, _ = domain
    value = created(domain)
    record = transition(storage, value["id"])
    record["audit"][0]["to_status"] = "published"
    with pytest.raises(CloudError):
        validate_content(record)
    record = deepcopy(storage.records["content"][value["id"]])
    record["unrelated_large_private_blob"] = "x" * 65536
    with pytest.raises(CloudError):
        content_dto(record)


@pytest.mark.parametrize("kind", ["like", "bookmark"])
def test_relations_set_cancel_and_repeated_calls_are_canonical_and_private(domain, kind):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    false = run(service.set_relation(OWNER_A, post["id"], kind, False))
    assert false == {"post_id": post["id"], "kind": kind, "active": False}
    assert not storage.records["relations"]
    first = run(service.set_relation(OWNER_A, post["id"], kind, True))
    snapshot = deepcopy(storage.records)
    assert run(service.set_relation(OWNER_A, post["id"], kind, True)) == first
    assert storage.records == snapshot
    record_id = relation_id(kind, OWNER_A, post["id"])
    assert len(storage.records["relations"]) == 1
    assert storage.records["relations"][record_id]["row_version"] == 1
    cancelled = run(service.set_relation(OWNER_A, post["id"], kind, False))
    assert not cancelled["active"] and storage.records["relations"][record_id]["row_version"] == 2
    snapshot = deepcopy(storage.records)
    assert run(service.set_relation(OWNER_A, post["id"], kind, False)) == cancelled
    assert storage.records == snapshot
    run(service.set_relation(OWNER_B, post["id"], kind, True))
    assert len(storage.records["relations"]) == 2
    assert not {"owner_id", "row_version", "_id"} & set(first)


@pytest.mark.parametrize("state", ["pending", "rejected", "hidden", "deleted"])
def test_interactions_reject_every_nonpublic_parent(domain, state):
    service, storage, _ = domain
    post = created(domain)
    if state in {"rejected", "hidden"}:
        transition(storage, post["id"], "reject" if state == "rejected" else "hide")
    elif state == "deleted":
        run(service.withdraw(OWNER_A, "post", post["id"], 1))
    for kind in ("like", "bookmark"):
        for active in (True, False):
            assert_error(404, service.set_relation(OWNER_B, post["id"], kind, active))
    assert not storage.records["relations"]
    assert_error(404, service.create_content_report(OWNER_B, ContentReportCreate(target_type="post", target_id=post["id"], reason="privacy"), "hidden-report"))
    assert not storage.records["content_reports"]


def test_relation_creation_collision_with_opposite_state_returns_conflict(domain):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    original_insert = storage.insert
    async def cancelled_concurrently(kind, record, immutable):
        canonical, new = await original_insert(kind, record, immutable)
        if kind == "relations":
            canonical.update(active=False, row_version=2)
            storage.records[kind][canonical["id"]] = deepcopy(canonical)
            return canonical, False
        return canonical, new
    storage.insert = cancelled_concurrently
    assert_error(409, service.set_relation(OWNER_A, post["id"], "like", True), "relationship_conflict")
    assert next(iter(storage.records["relations"].values()))["active"] is False


def test_relation_saved_during_parent_hide_stays_inert_and_response_is_404(domain):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    original_insert = storage.insert
    async def hidden_concurrently(kind, record, immutable):
        result = await original_insert(kind, record, immutable)
        if kind == "relations":
            transition(storage, post["id"], "hide")
        return result
    storage.insert = hidden_concurrently
    assert_error(404, service.set_relation(OWNER_A, post["id"], "bookmark", True))
    assert len(storage.records["relations"]) == 1
    assert run(service.list_bookmarks(OWNER_A))["items"] == []
    assert run(service.list_bookmarks(OWNER_B))["items"] == []


def test_bookmarks_batch_is_bounded_private_and_empty_scanned_pages_advance(domain):
    service, storage, _ = domain
    post = created(domain)
    template = transition(storage, post["id"])
    storage.records["content"].clear()
    for index in range(8):
        record = deepcopy(template)
        record["id"] = record["_id"] = str(UUID(int=100 + index))
        storage.records["content"][record["id"]] = record
        run(service.set_relation(OWNER_A, record["id"], "bookmark", True))
    all_relations = sorted(storage.records["relations"].values(), key=lambda item: (item["created_at"], item["id"]), reverse=True)
    for relation in all_relations[:3]:
        transition(storage, relation["post_id"], "hide")
    calls = []
    original_list = storage.list
    async def recorded_list(kind, query, time_field, limit):
        calls.append((kind, deepcopy(query), time_field, limit))
        return await original_list(kind, query, time_field, limit)
    storage.list = recorded_list
    first = run(service.list_bookmarks(OWNER_A, limit=3))
    assert first["items"] == [] and first["next_cursor"]
    assert len(calls) == 2
    assert calls[0][0] == "relations" and calls[0][3] == 4
    assert calls[0][1]["owner_id"] == OWNER_A
    assert calls[1][0] == "content" and calls[1][3] == 3 and len(calls[1][1]["id"]["$in"]) == 3
    second = run(service.list_bookmarks(OWNER_A, limit=3, cursor=first["next_cursor"]))
    assert len(second["items"]) == 3
    assert [item["id"] for item in second["items"]] == [item["post_id"] for item in all_relations[3:6]]
    assert_error(422, service.list_bookmarks(OWNER_B, cursor=first["next_cursor"]))
    assert run(service.list_bookmarks(OWNER_B))["items"] == []


@pytest.mark.parametrize("corruption", [{"active": 1}, {"row_version": True}, {"id": OWNER_A}, {"created_at": "invalid"}])
def test_corrupt_relation_cannot_be_projected_or_changed(domain, corruption):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    run(service.set_relation(OWNER_A, post["id"], "bookmark", True))
    identifier = relation_id("bookmark", OWNER_A, post["id"])
    storage.records["relations"][identifier].update(corruption)
    assert_error(503, service.set_relation(OWNER_A, post["id"], "bookmark", False))
    # Non-bool active cannot match the strict storage query, but direct mutation still fails.
    if corruption != {"active": 1}:
        assert_error(503, service.list_bookmarks(OWNER_A))


@pytest.mark.parametrize("changes", [
    {"target_type": "child"}, {"target_type": "posts"}, {"target_id": "invalid"},
    {"reason": "diagnosis"}, {"reason": "other", "detail": " "},
    {"detail": "x" * 501}, {"detail": "<script>x</script>"},
    {"target_revision": 1}, {"reporter_owner_id": OWNER_B}, {"status": "resolved"},
])
def test_report_inputs_refuse_private_targets_unsafe_text_and_forged_ownership(changes):
    payload = {"target_type": "post", "target_id": OWNER_A, "reason": "privacy", **changes}
    with pytest.raises(ValidationError):
        ContentReportCreate.model_validate(payload)


@pytest.mark.parametrize("reason", ["privacy", "harassment", "unsafe", "spam", "other"])
def test_report_reasons_and_other_explanation_are_explicit(reason):
    value = ContentReportCreate(target_type="post", target_id=OWNER_A, reason=reason, detail="合成说明" if reason == "other" else "")
    assert value.reason == reason


def test_reports_unique_per_target_revision_and_return_only_private_safe_receipt(domain):
    service, storage, family = domain
    post = created(domain)
    transition(storage, post["id"])
    body = ContentReportCreate(target_type="post", target_id=post["id"], reason="privacy", detail="合成举报说明")
    first, is_new = run(service.create_content_report(OWNER_B, body, "report-one"))
    assert is_new and first["status"] == "open" and first["target_revision"] == 1
    quota_before = deepcopy(storage.records["write_quotas"])
    second, is_new = run(service.create_content_report(OWNER_B, body, "report-other-key"))
    assert not is_new and second == first and storage.records["write_quotas"] == quota_before
    assert len(storage.records["content_reports"]) == 1
    assert not {"reporter_owner_id", "audit", "row_version", "idempotency_hash", "initial_payload_hash"} & set(first)
    changed = ContentReportCreate(target_type="post", target_id=post["id"], reason="spam")
    assert_error(409, service.create_content_report(OWNER_B, changed, "report-three"), "idempotency_conflict")
    assert storage.records["write_quotas"] == quota_before
    run(service.edit_post(OWNER_A, post["id"], PostPatch(expected_revision=1, **post_body().model_dump())))
    transition(storage, post["id"])
    third, is_new = run(service.create_content_report(OWNER_B, body, "report-new-revision"))
    assert is_new and third["target_revision"] == 2 and third["id"] != first["id"]
    assert len(storage.records["content_reports"]) == 2
    assert not family.records["reports"]


def test_reports_on_comments_cannot_bypass_hidden_parent(domain):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    comment, _ = run(service.create_comment(OWNER_A, post["id"], CommentCreate(body="合成评论"), "reported-comment"))
    transition(storage, comment["id"])
    report, is_new = run(service.create_content_report(OWNER_B, ContentReportCreate(target_type="comment", target_id=comment["id"], reason="harassment"), "comment-report"))
    assert is_new and report["target_type"] == "comment"
    transition(storage, post["id"], "hide")
    assert_error(404, service.create_content_report(OWNER_B, ContentReportCreate(target_type="comment", target_id=comment["id"], reason="harassment"), "comment-report"))
    assert len(storage.records["content_reports"]) == 1


def test_report_write_with_parent_hidden_during_insert_returns_404_without_fake_success(domain):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    original_insert = storage.insert
    async def hidden_during_report(kind, record, immutable):
        result = await original_insert(kind, record, immutable)
        if kind == "content_reports":
            transition(storage, post["id"], "hide")
        return result
    storage.insert = hidden_during_report
    assert_error(404, service.create_content_report(OWNER_B, ContentReportCreate(target_type="post", target_id=post["id"], reason="privacy"), "hide-report"))
    assert len(storage.records["content_reports"]) == 1


def test_concurrent_report_creates_converge_without_duplicate_records(domain):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    original_get = storage.get
    async def race():
        count = 0
        ready = asyncio.Event()
        async def simultaneous_get(kind, identifier):
            nonlocal count
            result = await original_get(kind, identifier)
            if kind == "content_reports":
                count += 1
                if count == 2:
                    ready.set()
                await ready.wait()
            return result
        storage.get = simultaneous_get
        body = ContentReportCreate(target_type="post", target_id=post["id"], reason="privacy")
        return await asyncio.gather(service.create_content_report(OWNER_B, body, "one"), service.create_content_report(OWNER_B, body, "two"))
    results = run(race())
    assert results[0][0]["id"] == results[1][0]["id"]
    assert sum(item[1] for item in results) == 1 and len(storage.records["content_reports"]) == 1


@pytest.mark.parametrize("corruption", [
    {"report_revision": True}, {"target_revision": True}, {"status": "resolved"},
    {"audit": []}, {"reporter_owner_id": OWNER_A}, {"detail": "changed after create"},
])
def test_invalid_report_state_and_private_data_never_acknowledged(domain, corruption):
    service, storage, _ = domain
    post = created(domain)
    transition(storage, post["id"])
    body = ContentReportCreate(target_type="post", target_id=post["id"], reason="privacy")
    report, _ = run(service.create_content_report(OWNER_B, body, "invalid-report"))
    record = deepcopy(storage.records["content_reports"][report["id"]])
    record.update(corruption)
    with pytest.raises(CloudError) as error:
        content_report_dto(record)
    assert error.value.status == 503


def test_interaction_validators_never_treat_bool_as_version_or_allow_forged_keys():
    with pytest.raises(CloudError):
        validate_relation({"kind": "like", "owner_id": OWNER_A, "post_id": OWNER_B, "id": OWNER_A})
    with pytest.raises(CloudError):
        validate_content_report({"reporter_owner_id": OWNER_A, "target_revision": True})


def seed_role(storage, principal=OPERATOR):
    """Explicit synthetic test fixture, never an HTTP role grant."""
    at = utc_now()
    identifier = role_binding_id(principal)
    record = {
        "_id": identifier, "id": identifier, "principal_id": principal, "role": "moderator",
        "status": "active", "row_version": 1, "created_at": at, "updated_at": at,
        "granted_at": at, "granted_by": "cloud-admin-cli",
        "audit": [{
            "action_id": str(uuid4()), "actor_id": "cloud-admin-cli", "action": "grant",
            "target_revision": 1, "from_status": None, "to_status": "active",
            "reason": "合成测试授权", "at": at, "payload_hash": normalized_hash({"principal": principal}),
        }],
    }
    validate_role(record)
    storage.records["role_bindings"][identifier] = record
    return record


def revoke_role(storage, principal=OPERATOR):
    identifier = role_binding_id(principal)
    record = deepcopy(storage.records["role_bindings"][identifier])
    at = utc_now(record["updated_at"])
    event = {
        "action_id": str(uuid4()), "actor_id": "cloud-admin-cli", "action": "revoke",
        "target_revision": record["row_version"] + 1, "from_status": "active", "to_status": "revoked",
        "reason": "合成测试撤销", "at": at, "payload_hash": normalized_hash({"principal": principal, "revoke": True}),
    }
    record.update(status="revoked", row_version=record["row_version"] + 1, updated_at=at, audit=[*record["audit"], event])
    validate_role(record)
    storage.records["role_bindings"][identifier] = record
    return record


def review(expected=1, reason="合成人工审核记录"):
    return ModerationAction(expected_revision=expected, reason=reason)


@pytest.mark.parametrize("payload", [
    {"expected_revision": 0, "reason": "理由"}, {"expected_revision": True, "reason": "理由"},
    {"expected_revision": 1, "reason": ""}, {"expected_revision": 1, "reason": "x" * 201},
    {"expected_revision": 1, "reason": "<script>x</script>"},
    {"expected_revision": 1, "reason": "理由", "actor_id": OWNER_B},
    {"expected_revision": 1, "reason": "理由", "status": "published"},
    {"expected_revision": 1, "reason": "理由", "role": "moderator"},
])
def test_moderation_only_accepts_expected_version_and_plain_human_reason(payload):
    with pytest.raises(ValidationError):
        ModerationAction.model_validate(payload)


def test_every_ops_method_checks_current_role_and_has_no_self_grant(domain):
    service, storage, _ = domain
    post = created(domain)
    for action in ("approve", "reject", "hide"):
        assert_error(403, service.moderate(OWNER_A, "post", post["id"], action, review(), "no-role"), "moderator_required")
    assert_error(403, service.list_moderation(OWNER_A))
    assert_error(403, service.get_moderation(OWNER_A, "post", post["id"]))
    assert_error(403, service.list_content_reports(OWNER_A))
    assert_error(403, service.resolve_content_report(OWNER_A, OWNER_B, ContentReportResolve(expected_revision=1, decision="resolved", reason="合成理由"), "no-role"))
    assert not storage.records["role_bindings"]
    seed_role(storage)
    assert run(service.list_moderation(OPERATOR))["items"][0]["id"] == post["id"]
    revoke_role(storage)
    assert_error(403, service.list_moderation(OPERATOR))
    assert_error(403, service.moderate(OPERATOR, "post", post["id"], "approve", review(), "revoked"))


@pytest.mark.parametrize("corruption", [
    {"role": "admin"}, {"status": True}, {"row_version": True}, {"principal_id": OWNER_A},
    {"audit": []}, {"granted_by": OWNER_A}, {"granted_at": "invalid"}, {"client_owner": OWNER_A},
])
def test_bad_role_binding_never_elevates_a_parent(domain, corruption):
    service, storage, _ = domain
    seed_role(storage)
    storage.records["role_bindings"][role_binding_id(OPERATOR)].update(corruption)
    assert_error(503, service.list_moderation(OPERATOR))


def test_role_immutable_authority_and_reserved_revoke_capacity(domain):
    _, storage, _ = domain
    record = deepcopy(seed_role(storage))
    for revision in range(2, 33):
        action = "revoke" if record["status"] == "active" else "grant"
        status = "revoked" if action == "revoke" else "active"
        at = utc_now(record["updated_at"])
        event = {
            "action_id": str(uuid4()), "actor_id": "cloud-admin-cli", "action": action,
            "target_revision": revision, "from_status": record["status"], "to_status": status,
            "reason": "合成角色历史", "at": at, "payload_hash": normalized_hash({"version": revision}),
        }
        record.update(status=status, row_version=revision, updated_at=at, audit=[*record["audit"], event])
        if action == "grant":
            record["granted_at"] = at
        validate_role(record)
    assert len(record["audit"]) == 32 and record["status"] == "revoked"
    record["audit"][0]["actor_id"] = OPERATOR
    with pytest.raises(CloudError):
        validate_role(record)


@pytest.mark.parametrize("action, expected_status", [("approve", "published"), ("reject", "rejected"), ("hide", "hidden")])
def test_moderation_state_and_audit_committed_together_with_version_bound_receipt(domain, action, expected_status):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    before = deepcopy(storage.records["content"][post["id"]]["audit"])
    result = run(service.moderate(OPERATOR, "post", post["id"], action, review(), "review-key"))
    assert result["action_applied"] and result["applied_revision"] == 1
    assert result["content"]["status"] == expected_status
    record = storage.records["content"][post["id"]]
    assert record["audit"][:-1] == before and record["audit"][-1]["action_id"] == result["action_id"]
    assert record["row_version"] == len(record["audit"]) == 2
    if action == "approve":
        assert run(service.get_post(post["id"]))["published_at"] == result["applied_at"]
    else:
        assert_error(404, service.get_post(post["id"]))
    snapshot = deepcopy(storage.records)
    assert run(service.moderate(OPERATOR, "post", post["id"], action, review(), "review-key")) == result
    assert storage.records == snapshot
    assert_error(409, service.moderate(OPERATOR, "post", post["id"], action, review(reason="不同理由"), "review-key"), "idempotency_conflict")


def test_historical_approve_replay_reports_current_edited_state_without_republishing(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    initial = run(service.moderate(OPERATOR, "post", post["id"], "approve", review(), "history-key"))
    run(service.edit_post(OWNER_A, post["id"], PostPatch(expected_revision=1, **post_body().model_dump())))
    snapshot = deepcopy(storage.records)
    replay = run(service.moderate(OPERATOR, "post", post["id"], "approve", review(), "history-key"))
    assert replay["action_applied"] and replay["action_id"] == initial["action_id"] and replay["applied_revision"] == 1
    assert replay["content"]["status"] == "pending" and replay["content"]["content_revision"] == 2
    assert storage.records == snapshot
    assert_error(404, service.get_post(post["id"]))
    assert_error(409, service.moderate(OPERATOR, "post", post["id"], "approve", review(), "new-stale-key"))
    revoke_role(storage)
    assert_error(403, service.moderate(OPERATOR, "post", post["id"], "approve", review(), "history-key"))


def test_valid_commit_with_lost_ack_is_indeterminate_then_same_key_recovers(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    original_cas = storage.cas
    async def lost_ack(kind, identifier, expected, changes):
        result = await original_cas(kind, identifier, expected, changes)
        if kind == "content" and result:
            raise unavailable()
        return result
    storage.cas = lost_ack
    assert_error(503, service.moderate(OPERATOR, "post", post["id"], "approve", review(), "ack-lost"))
    record = storage.records["content"][post["id"]]
    assert record["status"] == "published" and record["audit"][-1]["action"] == "approve"
    # The submitted review was legitimate and atomic; delivery failed, rather than audit being absent.
    assert run(service.get_post(post["id"]))["id"] == post["id"]
    before = deepcopy(storage.records)
    recovered = run(service.moderate(OPERATOR, "post", post["id"], "approve", review(), "ack-lost"))
    assert recovered["action_applied"] and storage.records == before


def test_database_failure_before_apply_and_stale_revision_leave_pending(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    before = deepcopy(storage.records["content"][post["id"]])
    assert_error(409, service.moderate(OPERATOR, "post", post["id"], "approve", review(expected=2), "wrong-revision"))
    original_cas = storage.cas
    async def fail_before(kind, identifier, expected, changes):
        if kind == "content":
            raise unavailable()
        return await original_cas(kind, identifier, expected, changes)
    storage.cas = fail_before
    assert_error(503, service.moderate(OPERATOR, "post", post["id"], "approve", review(), "before-fail"))
    assert storage.records["content"][post["id"]] == before
    assert_error(404, service.get_post(post["id"]))


def test_concurrent_author_edit_prevents_old_revision_approval(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    original_cas = storage.cas
    async def edit_before_apply(kind, identifier, expected, changes):
        if kind == "content" and changes.get("status") == "published":
            await service.edit_post(OWNER_A, post["id"], PostPatch(expected_revision=1, **post_body().model_dump()))
        return await original_cas(kind, identifier, expected, changes)
    storage.cas = edit_before_apply
    assert_error(409, service.moderate(OPERATOR, "post", post["id"], "approve", review(), "edit-race"))
    record = storage.records["content"][post["id"]]
    assert record["status"] == "pending" and record["content_revision"] == 2
    assert [event["action"] for event in record["audit"]] == ["create", "edit"]
    assert_error(404, service.get_post(post["id"]))


def test_concurrent_approve_and_reject_only_one_audited_decision_wins(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    original_get = storage.get
    async def race():
        count = 0
        ready = asyncio.Event()
        async def both_read(kind, identifier):
            nonlocal count
            result = await original_get(kind, identifier)
            if kind == "content" and identifier == post["id"]:
                count += 1
                if count == 2:
                    ready.set()
                await ready.wait()
            return result
        storage.get = both_read
        async def submit(action):
            try:
                return await service.moderate(OPERATOR, "post", post["id"], action, review(), f"race-{action}")
            except CloudError as error:
                return error.status
        return await asyncio.gather(submit("approve"), submit("reject"))
    results = run(race())
    assert sum(isinstance(result, dict) for result in results) == 1 and 409 in results
    record = storage.records["content"][post["id"]]
    assert len(record["audit"]) == 2 and record["status"] in {"published", "rejected"}


def test_comment_approval_checks_parent_and_hidden_parent_cannot_leak(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    run(service.moderate(OPERATOR, "post", post["id"], "approve", review(), "parent-approved"))
    comment, _ = run(service.create_comment(OWNER_B, post["id"], CommentCreate(body="合成待审评论"), "comment-review"))
    run(service.moderate(OPERATOR, "post", post["id"], "hide", review(), "parent-hidden"))
    assert_error(404, service.moderate(OPERATOR, "comment", comment["id"], "approve", review(), "comment-approved"))
    assert storage.records["content"][comment["id"]]["status"] == "pending"
    assert run(service.get_moderation(OPERATOR, "comment", comment["id"]))["status"] == "pending"
    run(service.moderate(OPERATOR, "comment", comment["id"], "reject", review(), "comment-rejected"))
    assert storage.records["content"][comment["id"]]["status"] == "rejected"


def test_hide_new_key_on_already_hidden_is_honest_noop_and_deleted_terminal(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    run(service.moderate(OPERATOR, "post", post["id"], "hide", review(), "first-hide"))
    before = deepcopy(storage.records)
    noop = run(service.moderate(OPERATOR, "post", post["id"], "hide", review(), "other-hide"))
    assert not noop["action_applied"] and noop["action_id"] is None and noop["applied_revision"] is None
    assert noop["content"]["status"] == "hidden" and storage.records == before
    assert_error(409, service.moderate(OPERATOR, "post", post["id"], "approve", review(), "hidden-approve"))
    run(service.withdraw(OWNER_A, "post", post["id"], 1))
    for action in ("approve", "reject", "hide"):
        assert_error(409, service.moderate(OPERATOR, "post", post["id"], action, review(), "deleted-action"))


def test_operator_queue_is_bounded_status_bound_and_audit_is_ops_only(domain):
    service, storage, _ = domain
    post = created(domain)
    run(service.create_post(OWNER_B, post_body(), "second-queue"))
    seed_role(storage)
    first = run(service.list_moderation(OPERATOR, limit=1))
    assert len(first["items"]) == 1 and first["next_cursor"]
    assert first["items"][0]["kind"] == "post" and "audit" in first["items"][0]
    assert_error(422, service.list_moderation(OPERATOR, status="published", cursor=first["next_cursor"]))
    assert_error(422, service.list_moderation(OPERATOR, status="all"))
    assert "audit" not in run(service.get_owned(OWNER_A, "post", post["id"]))
    assert "owner_id" not in run(service.get_moderation(OPERATOR, "post", post["id"]))


@pytest.mark.parametrize("decision", ["resolved", "dismissed"])
def test_report_resolution_is_atomic_audited_and_independent_of_content_visibility(domain, decision):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    run(service.moderate(OPERATOR, "post", post["id"], "approve", review(), "report-post"))
    report, _ = run(service.create_content_report(OWNER_B, ContentReportCreate(target_type="post", target_id=post["id"], reason="privacy"), "resolve-me"))
    content_before = deepcopy(storage.records["content"])
    body = ContentReportResolve(expected_revision=1, decision=decision, reason="合成处理说明")
    result = run(service.resolve_content_report(OPERATOR, report["id"], body, "report-handled"))
    assert result["action_applied"] and result["report"]["status"] == decision
    assert result["report"]["report_revision"] == 2 and result["applied_revision"] == 2
    assert storage.records["content"] == content_before
    record = storage.records["content_reports"][report["id"]]
    assert record["row_version"] == len(record["audit"]) == 2 and record["audit"][-1]["action"] == "resolve"
    snapshot = deepcopy(storage.records)
    assert run(service.resolve_content_report(OPERATOR, report["id"], body, "report-handled")) == result
    assert storage.records == snapshot
    assert_error(409, service.resolve_content_report(OPERATOR, report["id"], body, "different-handle"))
    changed = ContentReportResolve(expected_revision=1, decision="dismissed" if decision == "resolved" else "resolved", reason="合成处理说明")
    assert_error(409, service.resolve_content_report(OPERATOR, report["id"], changed, "report-handled"), "idempotency_conflict")
    assert run(service.list_content_reports(OPERATOR))["items"] == []
    assert run(service.list_content_reports(OPERATOR, status=decision))["items"][0]["id"] == report["id"]
    assert_error(403, service.list_content_reports(OWNER_A, status=decision))


def test_report_resolution_unknown_ack_recovers_and_revocation_still_blocks_replay(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    run(service.moderate(OPERATOR, "post", post["id"], "approve", review(), "report-visible"))
    report, _ = run(service.create_content_report(OWNER_B, ContentReportCreate(target_type="post", target_id=post["id"], reason="spam"), "report-ack"))
    body = ContentReportResolve(expected_revision=1, decision="resolved", reason="合成处理理由")
    original_cas = storage.cas
    async def lost_ack(kind, identifier, expected, changes):
        applied = await original_cas(kind, identifier, expected, changes)
        if kind == "content_reports" and applied:
            raise unavailable()
        return applied
    storage.cas = lost_ack
    assert_error(503, service.resolve_content_report(OPERATOR, report["id"], body, "lost-report-ack"))
    snapshot = deepcopy(storage.records)
    assert run(service.resolve_content_report(OPERATOR, report["id"], body, "lost-report-ack"))["action_applied"]
    assert storage.records == snapshot
    revoke_role(storage)
    assert_error(403, service.resolve_content_report(OPERATOR, report["id"], body, "lost-report-ack"))


def test_moderation_capacity_cannot_spend_reserved_hide_withdraw_slots(domain):
    service, storage, _ = domain
    post = created(domain)
    seed_role(storage)
    record = deepcopy(storage.records["content"][post["id"]])
    for revision in range(2, 31):
        changes = append_audit(record, {"content_revision": revision, "updated_at": utc_now(record["updated_at"])},
                               action="edit", actor=OWNER_A, payload={"expected_revision": revision - 1})
        record = {**record, **changes}
    storage.records["content"][post["id"]] = record
    assert_error(409, service.moderate(OPERATOR, "post", post["id"], "approve", review(expected=30), "capacity-approve"), "audit_capacity_exceeded")
    run(service.moderate(OPERATOR, "post", post["id"], "hide", review(expected=30), "capacity-hide"))
    assert len(storage.records["content"][post["id"]]["audit"]) == 31
    run(service.withdraw(OWNER_A, "post", post["id"], 30))
    assert len(storage.records["content"][post["id"]]["audit"]) == 32
