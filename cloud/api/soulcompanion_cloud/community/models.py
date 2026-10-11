"""Strict, pure-text community contracts; internal ownership is never an input."""

from datetime import datetime
import re
from typing import Annotated, Generic, Literal, Self, TypeVar
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ..family_identity import ChildAgeBand


CommunityTopic = Literal[
    "parent-child", "emotional-support", "daily-habits", "school-transition",
    "learning-peers", "adolescence", "parent-growth",
]
ContentKind = Literal["post", "comment"]
ContentStatus = Literal["pending", "published", "rejected", "hidden", "deleted"]
UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
StrictText = Annotated[str, StringConstraints(strict=True)]
PositiveRevision = Annotated[int, Field(strict=True, ge=1)]
UtcTime = Annotated[str, StringConstraints(strict=True, pattern=UTC_PATTERN)]


def canonical_id(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("A canonical UUID is required.")
    return value


def canonical_time(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(UTC_PATTERN, value) is None:
        raise ValueError("A canonical UTC timestamp is required.")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != value:
        raise ValueError("A canonical UTC timestamp is required.")
    return value


def plain_text(value: str, maximum: int, *, multiline: bool = False, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise ValueError("Plain text is required.")
    # Validate before strip/NFC so invalid characters cannot be hidden at the edges.
    if any(unicodedata.category(c).startswith("C") and not (multiline and c == "\n") for c in value):
        raise ValueError("Unsupported text characters.")
    normalized = unicodedata.normalize("NFC", value).strip()
    encoded = normalized.encode("utf-8", errors="strict")
    if not minimum <= len(normalized) <= maximum or len(encoded) > maximum * 4:
        raise ValueError("Text length is outside the allowed range.")
    if re.search(r"<\s*/?\s*[A-Za-z]|javascript\s*:|data\s*:\s*(?:text/html|application/)", normalized, re.I):
        raise ValueError("Dangerous embedded content is not allowed.")
    return normalized


class CommunityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PostCreate(CommunityContract):
    title: StrictText
    body: StrictText
    age_band: ChildAgeBand
    topic: CommunityTopic

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        return plain_text(value, 80)

    @field_validator("body")
    @classmethod
    def body_text(cls, value: str) -> str:
        return plain_text(value, 2000, multiline=True)


class PostPatch(PostCreate):
    expected_revision: PositiveRevision


class CommentCreate(CommunityContract):
    body: StrictText

    @field_validator("body")
    @classmethod
    def body_text(cls, value: str) -> str:
        return plain_text(value, 1000, multiline=True)


class EmptyCommunityBody(CommunityContract):
    pass


class RelationReceipt(CommunityContract):
    post_id: str
    kind: Literal["like", "bookmark"]
    active: Annotated[bool, Field(strict=True)]


class PostRelationState(CommunityContract):
    post_id: StrictText
    liked: Annotated[bool, Field(strict=True)]
    bookmarked: Annotated[bool, Field(strict=True)]

    @field_validator("post_id")
    @classmethod
    def post_identifier(cls, value: str) -> str:
        return canonical_id(value)


class ModerationFeedback(CommunityContract):
    action: Literal["approve", "reject", "hide"]
    reason: StrictText
    at: UtcTime
    content_revision: PositiveRevision


class OwnedContentFeedback(CommunityContract):
    target_type: ContentKind
    target_id: StrictText
    content_revision: PositiveRevision
    status: ContentStatus
    feedback: ModerationFeedback | None

    @field_validator("target_id")
    @classmethod
    def target_identifier(cls, value: str) -> str:
        return canonical_id(value)


ContentReportReason = Literal["privacy", "harassment", "unsafe", "spam", "other"]
ContentReportStatus = Literal["open", "resolved", "dismissed"]


class ContentReportCreate(CommunityContract):
    target_type: ContentKind
    target_id: StrictText
    reason: ContentReportReason
    detail: StrictText = ""

    @field_validator("target_id")
    @classmethod
    def target_identifier(cls, value: str) -> str:
        return canonical_id(value)

    @field_validator("detail")
    @classmethod
    def detail_text(cls, value: str) -> str:
        return plain_text(value, 500, multiline=True, minimum=0)

    @model_validator(mode="after")
    def other_requires_detail(self) -> Self:
        if self.reason == "other" and not self.detail:
            raise ValueError("Other reports require a plain-text explanation.")
        return self


class ContentReportReceipt(CommunityContract):
    id: str
    target_type: ContentKind
    target_id: str
    target_revision: PositiveRevision
    reason: ContentReportReason
    detail: str
    status: ContentReportStatus
    created_at: UtcTime
    handled_at: UtcTime | None


class ModerationAction(CommunityContract):
    expected_revision: PositiveRevision
    reason: StrictText

    @field_validator("reason")
    @classmethod
    def review_reason(cls, value: str) -> str:
        return plain_text(value, 200)


class ContentReportResolve(ModerationAction):
    decision: Literal["resolved", "dismissed"]


class PublicAuthor(CommunityContract):
    id: str
    nickname: StrictText


class PublicPost(CommunityContract):
    id: str
    title: str
    body: str
    age_band: ChildAgeBand
    topic: CommunityTopic
    author: PublicAuthor
    created_at: UtcTime
    updated_at: UtcTime
    published_at: UtcTime


class PublicComment(CommunityContract):
    id: str
    post_id: str
    body: str
    author: PublicAuthor
    created_at: UtcTime
    updated_at: UtcTime
    published_at: UtcTime


class OwnedPost(PublicPost):
    published_at: UtcTime | None
    status: ContentStatus
    content_revision: PositiveRevision


class OwnedComment(PublicComment):
    published_at: UtcTime | None
    status: ContentStatus
    content_revision: PositiveRevision


T = TypeVar("T")


class CommunityPage(CommunityContract, Generic[T]):
    items: list[T]
    limit: Annotated[int, Field(strict=True, ge=1, le=50)]
    next_cursor: str | None
