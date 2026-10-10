"""Strict request and response contracts, with UTC server timestamps."""

from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .family_identity import ChildAgeBand, normalize_community_nickname


Name = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64),
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UserPatch(Contract):
    display_name: Name


class ChildWrite(Contract):
    nickname: Name
    age_band: ChildAgeBand | None = None


class ParentProfileWrite(Contract):
    nickname: Annotated[str, StringConstraints(strict=True)]

    @field_validator("nickname")
    @classmethod
    def community_nickname(cls, value: str) -> str:
        return normalize_community_nickname(value)


class SessionCreate(Contract):
    child_profile_id: UUID
    source_platform: Literal["web", "wechat", "android_future"]


class EmptyBody(Contract):
    pass


class User(Contract):
    id: UUID
    display_name: str
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime


class ChildProfile(Contract):
    id: UUID
    nickname: str
    created_at: datetime
    updated_at: datetime
    status: Literal["active", "archived"]
    age_band: ChildAgeBand | None = None


class ParentCommunityProfile(Contract):
    id: UUID
    nickname: str
    created_at: datetime
    updated_at: datetime


class FamilyCapabilities(Contract):
    child_age_band: bool
    parent_profile: bool


class Session(Contract):
    id: UUID
    child_profile_id: UUID
    source_platform: Literal["web", "wechat", "android_future"]
    started_at: datetime
    ended_at: datetime | None
    status: Literal["active", "ended"]
    created_at: datetime


class EmotionRecord(Contract):
    id: UUID
    child_profile_id: UUID
    session_id: UUID
    timestamp: datetime
    category: Annotated[str, Field(min_length=1, max_length=64)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    valence: Annotated[float, Field(ge=-1, le=1)]
    arousal: Annotated[float, Field(ge=0, le=1)]
    source: Literal["legacy_import", "test_fixture", "cloud_inference"]
    created_at: datetime


class Report(Contract):
    id: UUID
    child_profile_id: UUID
    range_start: datetime
    range_end: datetime
    summary: Annotated[str, Field(max_length=4096)]
    created_at: datetime


T = TypeVar("T")


class Paginated(Contract, Generic[T]):
    items: list[T]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0, le=10000)]
    total: Annotated[int, Field(ge=0)]


class CurrentReport(Contract):
    status: Literal["empty", "available"]
    report: Report | None


class Health(Contract):
    status: Literal["ok"] = "ok"


class Readiness(Contract):
    status: Literal["healthy", "degraded", "unavailable"]


class QueryRange(Contract):
    range_start: datetime | None = None
    range_end: datetime | None = None

    @field_validator("range_start", "range_end")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("UTC offset is required")
        return value
