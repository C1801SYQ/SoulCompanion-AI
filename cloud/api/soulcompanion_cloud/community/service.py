"""Community state transitions with ownership, bounded reads and atomic audit."""

from datetime import datetime, timezone
from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Literal, Protocol, get_args
from uuid import UUID, uuid4, uuid5

from pydantic import ValidationError

from ..errors import CloudError, not_found, unavailable
from ..family_identity import ChildAgeBand, normalize_community_nickname, parent_profile_id
from ..repository import CloudRepository
from .models import (
    CommentCreate, CommunityTopic, ContentKind, ContentReportCreate, ContentReportReceipt,
    ContentReportResolve, ContentReportStatus, ContentStatus,
    ModerationAction, OwnedComment, OwnedContentFeedback, OwnedPost, PostCreate, PostPatch,
    PostRelationState, RelationReceipt,
    PublicComment, PublicPost, canonical_id, canonical_time, plain_text,
)
from .pagination import PageResult, cursor_query, normalize_limit, page


COMMUNITY_NAMESPACE = UUID("e5f8cf36-c8b1-4f3d-8546-e8f96bed9239")
MAX_AUDIT = 32
MAX_RECORD_BYTES = 65536
CONTENT_STATUSES = {"pending", "published", "rejected", "hidden", "deleted"}
AUDIT_FIELDS = {
    "action_id", "actor_id", "action", "target_revision", "from_status", "to_status",
    "reason", "at", "payload_hash", "content_hash",
}
CommunityRecord = dict[str, Any]
RelationKind = Literal["like", "bookmark"]
ModerationKind = Literal["approve", "reject", "hide"]


class CommunityStorage(Protocol):
    async def ready(self) -> bool: ...
    async def get(self, kind: str, record_id: str) -> CommunityRecord | None: ...
    async def list(self, kind: str, query: CommunityRecord, time_field: str, limit: int) -> list[CommunityRecord]: ...
    async def insert(self, kind: str, record: CommunityRecord, immutable: CommunityRecord) -> tuple[CommunityRecord, bool]: ...
    async def cas(self, kind: str, record_id: str, expected: CommunityRecord, changes: CommunityRecord) -> bool: ...
    async def consume_quota(self, owner: str, action: str) -> None: ...


def conflict(code: str = "revision_conflict") -> CloudError:
    return CloudError(409, code, "Community content changed or the action cannot be applied.")


def normalized_hash(value: CommunityRecord) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def idempotency_key(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", value) is None:
        raise CloudError(422, "invalid_idempotency_key", "A safe Idempotency-Key of 1 to 64 characters is required.")
    return value


def deterministic_id(kind: str, owner: str, key: str) -> str:
    return str(uuid5(COMMUNITY_NAMESPACE, json.dumps([kind, owner, key], separators=(",", ":"))))


def content_hash(record: CommunityRecord) -> str:
    fields = ["kind", "body", "public_author_id", "author_nickname"]
    fields += ["title", "age_band", "topic"] if record["kind"] == "post" else ["post_id"]
    return normalized_hash({field: record[field] for field in fields})


def utc_now(previous: str | None = None) -> str:
    value = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return max(value, previous) if previous is not None else value


def _digest(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Invalid digest.")


def _positive_int(value: object) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("Invalid version.")


def validate_content(record: CommunityRecord, kind: ContentKind | None = None) -> CommunityRecord:
    """Never project an invalid record or an unaudited published body."""
    try:
        if not isinstance(record, dict) or record.get("kind") not in {"post", "comment"}:
            raise ValueError("Invalid content kind.")
        if kind is not None and record["kind"] != kind:
            raise ValueError("Unexpected content kind.")
        canonical_id(record["id"])
        if record.get("_id") != record["id"]:
            raise ValueError("Invalid canonical key.")
        owner = canonical_id(record["owner_id"])
        if record["public_author_id"] != parent_profile_id(owner):
            raise ValueError("Invalid public author.")
        if normalize_community_nickname(record["author_nickname"]) != record["author_nickname"]:
            raise ValueError("Invalid nickname.")
        canonical_time(record["created_at"])
        canonical_time(record["updated_at"])
        if record["created_at"] > record["updated_at"] or record["status"] not in CONTENT_STATUSES:
            raise ValueError("Invalid content state.")
        _positive_int(record["content_revision"])
        _positive_int(record["row_version"])
        _digest(record["initial_payload_hash"])
        _digest(record["idempotency_hash"])
        if record["kind"] == "post":
            body = PostCreate.model_validate({field: record[field] for field in ("title", "body", "age_band", "topic")})
            if body.model_dump() != {field: record[field] for field in PostCreate.model_fields} or record.get("post_id") is not None:
                raise ValueError("Invalid normalized post.")
        else:
            canonical_id(record["post_id"])
            if plain_text(record["body"], 1000, multiline=True) != record["body"]:
                raise ValueError("Invalid normalized comment.")
        audit = record["audit"]
        if not isinstance(audit, list) or not 1 <= len(audit) <= MAX_AUDIT or record["row_version"] != len(audit):
            raise ValueError("Invalid audit capacity/version.")
        prior_status, prior_revision, prior_at = None, 0, record["created_at"]
        identifiers = set()
        for index, event in enumerate(audit):
            if not isinstance(event, dict) or set(event) != AUDIT_FIELDS:
                raise ValueError("Invalid audit event.")
            canonical_id(event["action_id"])
            canonical_id(event["actor_id"])
            if event["action_id"] in identifiers:
                raise ValueError("Duplicate audit action.")
            identifiers.add(event["action_id"])
            _positive_int(event["target_revision"])
            canonical_time(event["at"])
            _digest(event["payload_hash"])
            _digest(event["content_hash"])
            if event["from_status"] != prior_status or event["at"] < prior_at:
                raise ValueError("Invalid audit chain.")
            action = event["action"]
            destination = event["to_status"]
            revision = event["target_revision"]
            if index == 0:
                if (action, destination, revision, event["actor_id"], event["at"], event["payload_hash"]) != (
                    "create", "pending", 1, owner, record["created_at"], record["initial_payload_hash"]
                ):
                    raise ValueError("Invalid initial audit.")
            elif action == "edit":
                if prior_status == "deleted" or destination != "pending" or revision != prior_revision + 1:
                    raise ValueError("Invalid edit.")
            elif action == "approve":
                if prior_status != "pending" or destination != "published" or revision != prior_revision or index >= 30:
                    raise ValueError("Invalid approval.")
            elif action == "reject":
                if prior_status != "pending" or destination != "rejected" or revision != prior_revision or index >= 30:
                    raise ValueError("Invalid rejection.")
            elif action == "hide":
                if prior_status not in {"pending", "published", "rejected"} or destination != "hidden" or revision != prior_revision or index >= 31:
                    raise ValueError("Invalid hide.")
            elif action == "withdraw":
                if prior_status == "deleted" or destination != "deleted" or revision != prior_revision:
                    raise ValueError("Invalid withdrawal.")
            else:
                raise ValueError("Invalid action.")
            if action in {"create", "edit", "withdraw"}:
                if event["actor_id"] != owner or event["reason"] != "" or (action == "edit" and index >= 30):
                    raise ValueError("Invalid author action.")
            elif plain_text(event["reason"], 200) != event["reason"]:
                raise ValueError("Invalid moderation reason.")
            prior_status, prior_revision, prior_at = destination, revision, event["at"]
        if (prior_status, prior_revision, prior_at) != (record["status"], record["content_revision"], record["updated_at"]):
            raise ValueError("Audit does not match current content.")
        if audit[-1]["content_hash"] != content_hash(record):
            raise ValueError("Audit does not match current body.")
        published_at, moderated_at = record["published_at"], record["moderated_at"]
        if record["status"] == "published":
            if audit[-1]["action"] != "approve" or published_at != prior_at or moderated_at != prior_at:
                raise ValueError("Missing current approval.")
            canonical_time(published_at)
        elif published_at is not None:
            raise ValueError("Private content has publication time.")
        if record["status"] in {"pending", "deleted"}:
            if moderated_at is not None:
                raise ValueError("Invalid author moderation metadata.")
        elif moderated_at != prior_at:
            raise ValueError("Invalid moderation time.")
        if len(json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8", errors="strict")) > MAX_RECORD_BYTES:
            raise ValueError("Record byte limit exceeded.")
        return record
    except (KeyError, TypeError, ValueError, ValidationError, UnicodeError):
        raise unavailable() from None


def append_audit(
    record: CommunityRecord, changes: CommunityRecord, *, action: str, actor: str,
    payload: CommunityRecord, reason: str = "", action_id: str | None = None,
) -> CommunityRecord:
    """Return changes containing the entire immutable-prefix audit, for one CAS."""
    maximum = 32 if action == "withdraw" else 31 if action == "hide" else 30
    if len(record["audit"]) >= maximum:
        raise conflict("audit_capacity_exceeded")
    candidate = {**record, **changes, "row_version": record["row_version"] + 1}
    event = {
        "action_id": action_id or str(uuid4()), "actor_id": actor, "action": action,
        "target_revision": candidate["content_revision"], "from_status": record["status"],
        "to_status": candidate["status"], "reason": reason, "at": candidate["updated_at"],
        "payload_hash": normalized_hash(payload), "content_hash": content_hash(candidate),
    }
    candidate["audit"] = [*record["audit"], event]
    validate_content(candidate)
    return {**changes, "row_version": candidate["row_version"], "audit": candidate["audit"]}


def content_dto(record: CommunityRecord, *, owned: bool = False) -> CommunityRecord:
    validate_content(record)
    result = {field: record[field] for field in ("id", "body", "created_at", "updated_at", "published_at")}
    result["author"] = {"id": record["public_author_id"], "nickname": record["author_nickname"]}
    if record["kind"] == "post":
        result.update({field: record[field] for field in ("title", "age_band", "topic")})
        model = OwnedPost if owned else PublicPost
    else:
        result["post_id"] = record["post_id"]
        model = OwnedComment if owned else PublicComment
    if owned:
        result.update(status=record["status"], content_revision=record["content_revision"])
    elif record["status"] != "published":
        raise not_found()
    return model.model_validate(result).model_dump(mode="json")


def relation_id(kind: RelationKind, owner: str, post_id: str) -> str:
    return deterministic_id("relation", owner, f"{kind}:{post_id}")


def validate_relation(record: CommunityRecord) -> CommunityRecord:
    try:
        if not isinstance(record, dict) or record["kind"] not in {"like", "bookmark"}:
            raise ValueError("Invalid relationship.")
        canonical_id(record["owner_id"])
        canonical_id(record["post_id"])
        if record["id"] != relation_id(record["kind"], record["owner_id"], record["post_id"]) or record["_id"] != record["id"]:
            raise ValueError("Invalid relationship key.")
        if type(record["active"]) is not bool:
            raise ValueError("Invalid relationship state.")
        _positive_int(record["row_version"])
        canonical_time(record["created_at"])
        canonical_time(record["updated_at"])
        if record["created_at"] > record["updated_at"]:
            raise ValueError("Invalid relationship time.")
        if len(json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("Invalid relationship capacity.")
        return record
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise unavailable() from None


def content_report_id(owner: str, target_type: ContentKind, target_id: str, revision: int) -> str:
    return deterministic_id("content_report", owner, f"{target_type}:{target_id}:{revision}")


REPORT_AUDIT_FIELDS = {
    "action_id", "actor_id", "action", "target_revision", "from_status", "to_status",
    "reason", "at", "payload_hash",
}


def validate_content_report(record: CommunityRecord) -> CommunityRecord:
    try:
        if not isinstance(record, dict):
            raise ValueError("Invalid content report.")
        owner = canonical_id(record["reporter_owner_id"])
        _positive_int(record["target_revision"])
        _positive_int(record["report_revision"])
        _positive_int(record["row_version"])
        payload = ContentReportCreate.model_validate({field: record[field] for field in ContentReportCreate.model_fields})
        if payload.model_dump() != {field: record[field] for field in ContentReportCreate.model_fields}:
            raise ValueError("Invalid report text.")
        if record["id"] != content_report_id(owner, record["target_type"], record["target_id"], record["target_revision"]) or record["_id"] != record["id"]:
            raise ValueError("Invalid content report key.")
        canonical_time(record["created_at"])
        canonical_time(record["updated_at"])
        if record["created_at"] > record["updated_at"] or record["status"] not in {"open", "resolved", "dismissed"}:
            raise ValueError("Invalid report state.")
        _digest(record["initial_payload_hash"])
        _digest(record["idempotency_hash"])
        if normalized_hash({**payload.model_dump(), "target_revision": record["target_revision"]}) != record["initial_payload_hash"]:
            raise ValueError("Invalid report payload hash.")
        audit = record["audit"]
        if not isinstance(audit, list) or not 1 <= len(audit) <= 2 or record["row_version"] != len(audit) or record["report_revision"] != len(audit):
            raise ValueError("Invalid report audit/version.")
        ids = set()
        previous_state, previous_at = None, record["created_at"]
        for index, event in enumerate(audit):
            if not isinstance(event, dict) or set(event) != REPORT_AUDIT_FIELDS:
                raise ValueError("Invalid report audit event.")
            canonical_id(event["action_id"])
            canonical_id(event["actor_id"])
            canonical_time(event["at"])
            _digest(event["payload_hash"])
            if event["action_id"] in ids or event["from_status"] != previous_state or event["at"] < previous_at:
                raise ValueError("Invalid report audit chain.")
            if type(event["target_revision"]) is not int or event["target_revision"] != index + 1:
                raise ValueError("Invalid report action revision.")
            ids.add(event["action_id"])
            if index == 0:
                if (event["action"], event["to_status"], event["actor_id"], event["at"], event["payload_hash"], event["reason"]) != (
                    "create", "open", owner, record["created_at"], record["initial_payload_hash"], ""
                ):
                    raise ValueError("Invalid report creation audit.")
            elif event["action"] != "resolve" or previous_state != "open" or event["to_status"] not in {"resolved", "dismissed"} or plain_text(event["reason"], 200) != event["reason"]:
                raise ValueError("Invalid report handling audit.")
            previous_state, previous_at = event["to_status"], event["at"]
        if previous_state != record["status"] or previous_at != record["updated_at"]:
            raise ValueError("Invalid report current state.")
        if record["status"] == "open":
            if record["handled_at"] is not None:
                raise ValueError("Invalid open report time.")
        elif record["handled_at"] != previous_at:
            raise ValueError("Invalid report handled time.")
        if len(json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("Invalid report capacity.")
        return record
    except (KeyError, TypeError, ValueError, ValidationError, UnicodeError):
        raise unavailable() from None


def content_report_dto(record: CommunityRecord) -> CommunityRecord:
    validate_content_report(record)
    fields = ("id", "target_type", "target_id", "target_revision", "reason", "detail", "status", "created_at", "handled_at")
    return ContentReportReceipt.model_validate({field: record[field] for field in fields}).model_dump(mode="json")


def role_binding_id(principal: str) -> str:
    return deterministic_id("role_binding", principal, "moderator")


ROLE_AUDIT_FIELDS = REPORT_AUDIT_FIELDS
ROLE_FIELDS = {
    "_id", "id", "principal_id", "role", "status", "row_version", "created_at", "updated_at",
    "granted_at", "granted_by", "audit",
}


def validate_role(record: CommunityRecord) -> CommunityRecord:
    """Only a fully audited, server-managed binding can authorize an operator."""
    try:
        if not isinstance(record, dict) or set(record) != ROLE_FIELDS:
            raise ValueError("Invalid role fields.")
        principal = canonical_id(record["principal_id"])
        if record["id"] != role_binding_id(principal) or record["_id"] != record["id"]:
            raise ValueError("Invalid role key.")
        if record["role"] != "moderator" or record["status"] not in {"active", "revoked"}:
            raise ValueError("Invalid role state.")
        canonical_time(record["created_at"])
        canonical_time(record["updated_at"])
        canonical_time(record["granted_at"])
        if record["granted_by"] != "cloud-admin-cli":
            raise ValueError("Invalid granting authority.")
        audit = record["audit"]
        if not isinstance(audit, list) or not 1 <= len(audit) <= MAX_AUDIT or type(record["row_version"]) is not int or record["row_version"] != len(audit):
            raise ValueError("Invalid role history/version.")
        ids, previous_state, previous_at, grant_at = set(), None, record["created_at"], None
        for index, event in enumerate(audit):
            if not isinstance(event, dict) or set(event) != ROLE_AUDIT_FIELDS:
                raise ValueError("Invalid role audit.")
            canonical_id(event["action_id"])
            canonical_time(event["at"])
            _digest(event["payload_hash"])
            if event["action_id"] in ids or event["actor_id"] != "cloud-admin-cli" or event["from_status"] != previous_state or event["at"] < previous_at:
                raise ValueError("Invalid role authority/history.")
            if type(event["target_revision"]) is not int or event["target_revision"] != index + 1:
                raise ValueError("Invalid role audit revision.")
            if plain_text(event["reason"], 200) != event["reason"]:
                raise ValueError("Invalid role reason.")
            if index == 0 and event["at"] != record["created_at"]:
                raise ValueError("Invalid role creation time.")
            if event["action"] == "grant":
                if previous_state not in {None, "revoked"} or event["to_status"] != "active" or index >= 31:
                    raise ValueError("Invalid role grant.")
                grant_at = event["at"]
            elif event["action"] == "revoke":
                if previous_state != "active" or event["to_status"] != "revoked":
                    raise ValueError("Invalid role revocation.")
            else:
                raise ValueError("Invalid role action.")
            ids.add(event["action_id"])
            previous_state, previous_at = event["to_status"], event["at"]
        if (record["status"], record["updated_at"], record["granted_at"]) != (previous_state, previous_at, grant_at):
            raise ValueError("Role state does not match audit.")
        if len(json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("Role byte limit exceeded.")
        return record
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise unavailable() from None


def moderation_dto(record: CommunityRecord) -> CommunityRecord:
    return {**content_dto(record, owned=True), "kind": record["kind"], "row_version": record["row_version"], "audit": deepcopy(record["audit"])}


def operator_report_dto(record: CommunityRecord) -> CommunityRecord:
    return {**content_report_dto(record), "report_revision": record["report_revision"], "row_version": record["row_version"], "audit": deepcopy(record["audit"])}


def action_result(
    current: CommunityRecord, event: CommunityRecord | None, action: str, *, report: bool = False,
) -> CommunityRecord:
    return {
        "action_applied": event is not None,
        "action_id": event["action_id"] if event is not None else None,
        "action": action,
        "applied_revision": event["target_revision"] if event is not None else None,
        "applied_at": event["at"] if event is not None else None,
        "report" if report else "content": operator_report_dto(current) if report else moderation_dto(current),
    }


class CommunityService:
    def __init__(self, storage: CommunityStorage, family_repository: CloudRepository) -> None:
        self.storage = storage
        self.family_repository = family_repository

    async def require_ready(self) -> None:
        if await self.storage.ready() is not True:
            raise unavailable()

    async def _require_operator(self, owner: str) -> None:
        self._identifier(owner)
        record = await self.storage.get("role_bindings", role_binding_id(owner))
        if record is None:
            raise CloudError(403, "moderator_required", "A current community moderator role is required.")
        validate_role(record)
        if record["principal_id"] != owner:
            raise unavailable()
        if record["status"] != "active":
            raise CloudError(403, "moderator_required", "A current community moderator role is required.")

    @staticmethod
    def _identifier(value: str) -> str:
        try:
            return canonical_id(value)
        except (TypeError, ValueError):
            raise CloudError(422, "invalid_identifier", "Invalid community resource identifier.") from None

    async def _content(self, identifier: str, kind: ContentKind) -> CommunityRecord:
        self._identifier(identifier)
        record = await self.storage.get("content", identifier)
        if record is None or record.get("kind") != kind:
            raise not_found()
        return validate_content(record, kind)

    async def _public_post(self, identifier: str) -> CommunityRecord:
        record = await self._content(identifier, "post")
        if record["status"] != "published":
            raise not_found()
        return record

    async def _owned_content(self, owner: str, kind: ContentKind, identifier: str) -> CommunityRecord:
        self._identifier(owner)
        self._identifier(identifier)
        if kind not in {"post", "comment"}:
            raise not_found()
        record = await self.storage.get("content", identifier)
        if record is None or record.get("kind") != kind or record.get("owner_id") != owner:
            raise not_found()
        return validate_content(record, kind)

    async def _author(self, owner: str) -> dict[str, str]:
        self._identifier(owner)
        record = await self.family_repository.get_parent_profile(owner)
        if record is None:
            raise CloudError(409, "parent_profile_required", "Set your own public parent nickname before contributing.")
        try:
            if record["id"] != parent_profile_id(owner) or record["owner_user_id"] != owner:
                raise ValueError("Invalid parent profile ownership.")
            nickname = normalize_community_nickname(record["nickname"])
            if nickname != record["nickname"]:
                raise ValueError("Invalid stored nickname.")
            return {"public_author_id": record["id"], "author_nickname": nickname}
        except (KeyError, ValueError, TypeError):
            raise unavailable() from None

    async def list_posts(
        self, age_band: ChildAgeBand | None = None, topic: CommunityTopic | None = None,
        limit: int = 20, cursor: str | None = None,
    ) -> PageResult[CommunityRecord]:
        await self.require_ready()
        normalize_limit(limit)
        if age_band is not None and age_band not in get_args(ChildAgeBand):
            raise CloudError(422, "invalid_age_band", "Invalid community age band.")
        if topic is not None and topic not in get_args(CommunityTopic):
            raise CloudError(422, "invalid_topic", "Invalid community topic.")
        base = {"kind": "post", "status": "published"}
        if age_band is not None:
            base["age_band"] = age_band
        if topic is not None:
            base["topic"] = topic
        scope = {"list": "public_posts", "age_band": age_band, "topic": topic}
        records = await self.storage.list("content", cursor_query(base, scope, "published_at", cursor), "published_at", limit + 1)
        return page(records, limit, scope, "published_at", content_dto)

    async def get_post(self, post_id: str) -> CommunityRecord:
        await self.require_ready()
        return content_dto(await self._public_post(post_id))

    async def get_comment(self, comment_id: str) -> CommunityRecord:
        await self.require_ready()
        record = await self._content(comment_id, "comment")
        if record["status"] != "published":
            raise not_found()
        await self._public_post(record["post_id"])
        result = content_dto(record)
        await self._public_post(record["post_id"])
        return result

    async def _public_target(self, kind: ContentKind, identifier: str) -> CommunityRecord:
        if kind == "post":
            return await self._public_post(identifier)
        if kind != "comment":
            raise not_found()
        record = await self._content(identifier, "comment")
        if record["status"] != "published":
            raise not_found()
        await self._public_post(record["post_id"])
        return record

    async def list_comments(
        self, post_id: str, limit: int = 20, cursor: str | None = None,
    ) -> PageResult[CommunityRecord]:
        await self.require_ready()
        normalize_limit(limit)
        await self._public_post(post_id)
        scope = {"list": "public_comments", "post_id": post_id}
        query = cursor_query({"kind": "comment", "post_id": post_id, "status": "published"}, scope, "published_at", cursor)
        records = await self.storage.list("content", query, "published_at", limit + 1)
        result = page(records, limit, scope, "published_at", content_dto)
        await self._public_post(post_id)
        return result

    async def list_owned(
        self, owner: str, kind: ContentKind, limit: int = 20, cursor: str | None = None,
    ) -> PageResult[CommunityRecord]:
        await self.require_ready()
        self._identifier(owner)
        normalize_limit(limit)
        if kind not in {"post", "comment"}:
            raise not_found()
        scope = {"list": "owned_content", "owner": owner, "kind": kind}
        query = cursor_query({"owner_id": owner, "kind": kind}, scope, "created_at", cursor)
        records = await self.storage.list("content", query, "created_at", limit + 1)
        def project(record: CommunityRecord) -> CommunityRecord:
            if record.get("owner_id") != owner or record.get("kind") != kind:
                raise unavailable()
            return content_dto(record, owned=True)
        return page(records, limit, scope, "created_at", project)

    async def get_owned(self, owner: str, kind: ContentKind, identifier: str) -> CommunityRecord:
        await self.require_ready()
        return content_dto(await self._owned_content(owner, kind, identifier), owned=True)

    async def get_owned_feedback(self, owner: str, kind: ContentKind, identifier: str) -> CommunityRecord:
        await self.require_ready()
        record = await self._owned_content(owner, kind, identifier)
        # Ownership precedes validation and projection, including malformed foreign records.
        latest = next((event for event in reversed(record["audit"])
                       if event["target_revision"] == record["content_revision"]
                       and event["action"] in {"approve", "reject", "hide"}), None)
        feedback = None if latest is None else {
            "action": latest["action"], "reason": latest["reason"], "at": latest["at"],
            "content_revision": latest["target_revision"],
        }
        return OwnedContentFeedback(
            target_type=kind, target_id=record["id"], content_revision=record["content_revision"],
            status=record["status"], feedback=feedback,
        ).model_dump(mode="json")

    async def _create(self, owner: str, kind: ContentKind, body: CommunityRecord, key: str) -> tuple[CommunityRecord, bool]:
        key = idempotency_key(key)
        self._identifier(owner)
        identifier = deterministic_id(kind, owner, key)
        payload_hash = normalized_hash(body)
        immutable = {
            "_id": identifier, "id": identifier, "kind": kind, "owner_id": owner,
            "initial_payload_hash": payload_hash, "idempotency_hash": sha256(key.encode()).hexdigest(),
        }
        existing = await self.storage.get("content", identifier)
        if existing is not None:
            if any(existing.get(field) != value for field, value in immutable.items()):
                raise conflict("idempotency_conflict")
            return content_dto(existing, owned=True), False
        author = await self._author(owner)
        at = utc_now()
        record = {
            **immutable, **body, **author, "status": "pending", "content_revision": 1,
            "row_version": 1, "created_at": at, "updated_at": at,
            "published_at": None, "moderated_at": None,
        }
        if kind == "post":
            record["post_id"] = None
        record["audit"] = [{
            "action_id": deterministic_id("create_action", owner, f"{kind}:{key}"),
            "actor_id": owner, "action": "create", "target_revision": 1,
            "from_status": None, "to_status": "pending", "reason": "", "at": at,
            "payload_hash": payload_hash, "content_hash": content_hash(record),
        }]
        validate_content(record)
        await self.storage.consume_quota(owner, kind)
        canonical, created = await self.storage.insert("content", record, immutable)
        if any(canonical.get(field) != value for field, value in immutable.items()):
            raise unavailable()
        return content_dto(canonical, owned=True), created

    async def create_post(self, owner: str, body: PostCreate, key: str) -> tuple[CommunityRecord, bool]:
        await self.require_ready()
        return await self._create(owner, "post", body.model_dump(), key)

    async def create_comment(self, owner: str, post_id: str, body: CommentCreate, key: str) -> tuple[CommunityRecord, bool]:
        await self.require_ready()
        await self._public_post(post_id)
        result = await self._create(owner, "comment", {"post_id": post_id, **body.model_dump()}, key)
        await self._public_post(post_id)
        return result

    async def edit_post(self, owner: str, identifier: str, body: PostPatch) -> CommunityRecord:
        await self.require_ready()
        record = await self._owned_content(owner, "post", identifier)
        if record["status"] == "deleted":
            raise conflict("state_conflict")
        if record["content_revision"] != body.expected_revision:
            raise conflict()
        payload = body.model_dump(exclude={"expected_revision"})
        changes = {
            **payload, **await self._author(owner), "status": "pending",
            "content_revision": record["content_revision"] + 1, "published_at": None,
            "moderated_at": None, "updated_at": utc_now(record["updated_at"]),
        }
        changes = append_audit(record, changes, action="edit", actor=owner, payload=body.model_dump())
        await self.storage.consume_quota(owner, "post")
        if await self.storage.cas("content", identifier, self._expected(record, owner), changes) is not True:
            raise conflict()
        return content_dto({**record, **changes}, owned=True)

    @staticmethod
    def _expected(record: CommunityRecord, owner: str | None = None) -> CommunityRecord:
        result = {field: record[field] for field in ("_id", "id", "row_version", "content_revision", "status")}
        if owner is not None:
            result["owner_id"] = owner
        return result

    async def withdraw(self, owner: str, kind: ContentKind, identifier: str, expected_revision: int) -> None:
        await self.require_ready()
        if type(expected_revision) is not int or expected_revision < 1:
            raise CloudError(422, "invalid_revision", "A positive expected revision is required.")
        record = await self._owned_content(owner, kind, identifier)
        if record["status"] == "deleted":
            return None
        if record["content_revision"] != expected_revision:
            raise conflict()
        changes = append_audit(
            record,
            {"status": "deleted", "published_at": None, "moderated_at": None, "updated_at": utc_now(record["updated_at"])},
            action="withdraw", actor=owner, payload={"expected_revision": expected_revision},
        )
        if await self.storage.cas("content", identifier, self._expected(record, owner), changes) is not True:
            raise conflict()
        return None

    async def get_relation_state(self, owner: str, post_id: str) -> CommunityRecord:
        await self.require_ready()
        self._identifier(owner)
        await self._public_post(post_id)
        active: dict[RelationKind, bool] = {}
        kinds: tuple[RelationKind, RelationKind] = ("like", "bookmark")
        for kind in kinds:
            identifier = relation_id(kind, owner, post_id)
            record = await self.storage.get("relations", identifier)
            if record is None:
                active[kind] = False
                continue
            validate_relation(record)
            expected = {"_id": identifier, "id": identifier, "kind": kind, "owner_id": owner, "post_id": post_id}
            if any(record.get(field) != value for field, value in expected.items()):
                raise unavailable()
            active[kind] = record["active"]
        await self._public_post(post_id)
        return PostRelationState(post_id=post_id, liked=active["like"], bookmarked=active["bookmark"]).model_dump()

    async def set_relation(self, owner: str, post_id: str, kind: RelationKind, active: bool) -> CommunityRecord:
        await self.require_ready()
        self._identifier(owner)
        if kind not in {"like", "bookmark"} or type(active) is not bool:
            raise CloudError(422, "invalid_relationship", "Invalid community relationship action.")
        await self._public_post(post_id)
        identifier = relation_id(kind, owner, post_id)
        immutable = {"_id": identifier, "id": identifier, "kind": kind, "owner_id": owner, "post_id": post_id}
        record = await self.storage.get("relations", identifier)
        if record is None and not active:
            await self._public_post(post_id)
            return RelationReceipt(post_id=post_id, kind=kind, active=False).model_dump()
        if record is not None:
            validate_relation(record)
            if any(record.get(field) != value for field, value in immutable.items()):
                raise unavailable()
            if record["active"] == active:
                await self._public_post(post_id)
                return RelationReceipt(post_id=post_id, kind=kind, active=active).model_dump()
            changes = {"active": active, "row_version": record["row_version"] + 1, "updated_at": utc_now(record["updated_at"])}
            validate_relation({**record, **changes})
            await self.storage.consume_quota(owner, "relation")
            if await self.storage.cas("relations", identifier, {**immutable, "row_version": record["row_version"], "active": record["active"]}, changes) is not True:
                raise conflict("relationship_conflict")
        else:
            at = utc_now()
            candidate = {**immutable, "active": True, "row_version": 1, "created_at": at, "updated_at": at}
            await self.storage.consume_quota(owner, "relation")
            record, _ = await self.storage.insert("relations", candidate, immutable)
            validate_relation(record)
            if any(record.get(field) != value for field, value in immutable.items()):
                raise unavailable()
            if record["active"] != active:
                raise conflict("relationship_conflict")
        await self._public_post(post_id)
        return RelationReceipt(post_id=post_id, kind=kind, active=active).model_dump()

    async def list_bookmarks(
        self, owner: str, limit: int = 20, cursor: str | None = None,
    ) -> PageResult[CommunityRecord]:
        await self.require_ready()
        self._identifier(owner)
        normalize_limit(limit)
        scope = {"list": "private_bookmarks", "owner": owner}
        query = cursor_query({"owner_id": owner, "kind": "bookmark", "active": True}, scope, "created_at", cursor)
        relations = await self.storage.list("relations", query, "created_at", limit + 1)
        def validate_scan(record: CommunityRecord) -> CommunityRecord:
            validate_relation(record)
            if record["owner_id"] != owner or record["kind"] != "bookmark" or record["active"] is not True:
                raise unavailable()
            return record
        scanned = page(relations, limit, scope, "created_at", validate_scan)
        post_ids = [record["post_id"] for record in scanned["items"]]
        if not post_ids:
            return {"items": [], "limit": limit, "next_cursor": scanned["next_cursor"]}
        posts = await self.storage.list("content", {"kind": "post", "status": "published", "id": {"$in": post_ids}}, "published_at", len(post_ids))
        by_id = {}
        for record in posts:
            if record.get("id") not in post_ids or record.get("kind") != "post" or record.get("status") != "published" or record["id"] in by_id:
                raise unavailable()
            by_id[record["id"]] = content_dto(record)
        return {"items": [by_id[identifier] for identifier in post_ids if identifier in by_id], "limit": limit, "next_cursor": scanned["next_cursor"]}

    async def create_content_report(self, owner: str, body: ContentReportCreate, key: str) -> tuple[CommunityRecord, bool]:
        await self.require_ready()
        self._identifier(owner)
        key = idempotency_key(key)
        target = await self._public_target(body.target_type, body.target_id)
        revision = target["content_revision"]
        payload = {**body.model_dump(), "target_revision": revision}
        payload_hash = normalized_hash(payload)
        identifier = content_report_id(owner, body.target_type, body.target_id, revision)
        immutable = {
            "_id": identifier, "id": identifier, "reporter_owner_id": owner,
            "target_type": body.target_type, "target_id": body.target_id,
            "target_revision": revision, "initial_payload_hash": payload_hash,
        }
        existing = await self.storage.get("content_reports", identifier)
        if existing is not None:
            if any(existing.get(field) != value for field, value in immutable.items()):
                raise conflict("idempotency_conflict")
            result = content_report_dto(existing)
            await self._public_target(body.target_type, body.target_id)
            return result, False
        at = utc_now()
        record = {
            **immutable, "reason": body.reason, "detail": body.detail, "status": "open",
            "report_revision": 1, "row_version": 1, "idempotency_hash": sha256(key.encode()).hexdigest(),
            "created_at": at, "updated_at": at, "handled_at": None,
            "audit": [{
                "action_id": deterministic_id("report_create_action", owner, f"{identifier}:{key}"),
                "actor_id": owner, "action": "create", "target_revision": 1,
                "from_status": None, "to_status": "open", "reason": "", "at": at, "payload_hash": payload_hash,
            }],
        }
        validate_content_report(record)
        await self.storage.consume_quota(owner, "report")
        canonical, is_new = await self.storage.insert("content_reports", record, immutable)
        if any(canonical.get(field) != value for field, value in immutable.items()):
            raise unavailable()
        result = content_report_dto(canonical)
        await self._public_target(body.target_type, body.target_id)
        return result, is_new

    async def list_moderation(
        self, owner: str, status: ContentStatus = "pending", limit: int = 20,
        cursor: str | None = None,
    ) -> PageResult[CommunityRecord]:
        await self.require_ready()
        await self._require_operator(owner)
        normalize_limit(limit)
        if not isinstance(status, str) or status not in CONTENT_STATUSES:
            raise CloudError(422, "invalid_status", "Invalid moderation queue status.")
        scope = {"list": "moderation", "status": status}
        query = cursor_query({"status": status}, scope, "updated_at", cursor)
        records = await self.storage.list("content", query, "updated_at", limit + 1)
        return page(records, limit, scope, "updated_at", moderation_dto)

    async def get_moderation(self, owner: str, kind: ContentKind, identifier: str) -> CommunityRecord:
        await self.require_ready()
        await self._require_operator(owner)
        if kind not in {"post", "comment"}:
            raise not_found()
        return moderation_dto(await self._content(identifier, kind))

    @staticmethod
    def _applied_event(
        record: CommunityRecord, action_id: str, actor: str, payload: CommunityRecord,
        action: str,
    ) -> CommunityRecord | None:
        for event in record["audit"]:
            if event["action_id"] == action_id:
                if event["actor_id"] != actor or event["action"] != action or event["payload_hash"] != normalized_hash(payload):
                    raise conflict("idempotency_conflict")
                return event
        return None

    async def moderate(
        self, owner: str, kind: ContentKind, identifier: str, action: ModerationKind,
        body: ModerationAction, key: str,
    ) -> CommunityRecord:
        await self.require_ready()
        await self._require_operator(owner)
        key = idempotency_key(key)
        if kind not in {"post", "comment"} or action not in {"approve", "reject", "hide"}:
            raise not_found()
        record = await self._content(identifier, kind)
        action_id = deterministic_id("moderation_action", owner, f"{kind}:{identifier}:{action}:{key}")
        payload = {"action": action, "target_type": kind, "target_id": identifier, **body.model_dump()}
        applied = self._applied_event(record, action_id, owner, payload, action)
        if applied is not None:
            return action_result(record, applied, action)
        if record["content_revision"] != body.expected_revision:
            raise conflict()
        if action == "hide" and record["status"] == "hidden":
            return action_result(record, None, action)
        if (action in {"approve", "reject"} and record["status"] != "pending") or (
            action == "hide" and record["status"] not in {"pending", "published", "rejected"}
        ):
            raise conflict("state_conflict")
        if action == "approve" and kind == "comment":
            await self._public_post(record["post_id"])
        destination = {"approve": "published", "reject": "rejected", "hide": "hidden"}[action]
        at = utc_now(record["updated_at"])
        changes = append_audit(record, {
            "status": destination, "published_at": at if destination == "published" else None,
            "moderated_at": at, "updated_at": at,
        }, action=action, actor=owner, payload=payload, reason=body.reason, action_id=action_id)
        await self.storage.consume_quota(owner, "moderation")
        if await self.storage.cas("content", identifier, self._expected(record), changes) is not True:
            raise conflict()
        current = await self._content(identifier, kind)
        applied = self._applied_event(current, action_id, owner, payload, action)
        if applied is None:
            raise unavailable()
        if action == "approve" and kind == "comment":
            await self._public_post(record["post_id"])
        return action_result(current, applied, action)

    async def list_content_reports(
        self, owner: str, status: ContentReportStatus = "open", limit: int = 20,
        cursor: str | None = None,
    ) -> PageResult[CommunityRecord]:
        await self.require_ready()
        await self._require_operator(owner)
        normalize_limit(limit)
        if not isinstance(status, str) or status not in {"open", "resolved", "dismissed"}:
            raise CloudError(422, "invalid_status", "Invalid content report queue status.")
        scope = {"list": "content_reports", "status": status}
        query = cursor_query({"status": status}, scope, "created_at", cursor)
        records = await self.storage.list("content_reports", query, "created_at", limit + 1)
        return page(records, limit, scope, "created_at", operator_report_dto)

    async def resolve_content_report(
        self, owner: str, identifier: str, body: ContentReportResolve, key: str,
    ) -> CommunityRecord:
        await self.require_ready()
        await self._require_operator(owner)
        self._identifier(identifier)
        key = idempotency_key(key)
        record = await self.storage.get("content_reports", identifier)
        if record is None:
            raise not_found()
        validate_content_report(record)
        action_id = deterministic_id("report_resolve_action", owner, f"{identifier}:{key}")
        payload = {"report_id": identifier, **body.model_dump()}
        applied = self._applied_event(record, action_id, owner, payload, "resolve")
        if applied is not None:
            return action_result(record, applied, "resolve", report=True)
        if record["report_revision"] != body.expected_revision:
            raise conflict()
        if record["status"] != "open":
            raise conflict("state_conflict")
        at = utc_now(record["updated_at"])
        event = {
            "action_id": action_id, "actor_id": owner, "action": "resolve",
            "target_revision": record["report_revision"] + 1, "from_status": "open",
            "to_status": body.decision, "reason": body.reason, "at": at, "payload_hash": normalized_hash(payload),
        }
        changes = {
            "status": body.decision, "report_revision": record["report_revision"] + 1,
            "row_version": record["row_version"] + 1, "updated_at": at, "handled_at": at,
            "audit": [*record["audit"], event],
        }
        validate_content_report({**record, **changes})
        await self.storage.consume_quota(owner, "moderation")
        expected = {field: record[field] for field in ("_id", "id", "row_version", "report_revision", "status")}
        if await self.storage.cas("content_reports", identifier, expected, changes) is not True:
            raise conflict()
        current = await self.storage.get("content_reports", identifier)
        if current is None:
            raise unavailable()
        validate_content_report(current)
        applied = self._applied_event(current, action_id, owner, payload, "resolve")
        if applied is None:
            raise unavailable()
        return action_result(current, applied, "resolve", report=True)
