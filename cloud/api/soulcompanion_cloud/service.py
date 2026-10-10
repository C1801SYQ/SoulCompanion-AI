"""Application rules shared by HTTP and future platform transports."""

from datetime import datetime, timezone
from typing import Any, TypeVar
from uuid import UUID, uuid4

from .auth import AppPrincipal
from .errors import CloudError, unavailable
from .models import (
    ChildProfile,
    ChildWrite,
    Contract,
    CurrentReport,
    EmotionRecord,
    FamilyCapabilities,
    Paginated,
    ParentCommunityProfile,
    ParentProfileWrite,
    Report,
    Session,
    SessionCreate,
    User,
    UserPatch,
)
from .repository import CloudRepository, Entity, utc_now


RecordModel = TypeVar("RecordModel", bound=Contract)
RecordPage = (
    Paginated[ChildProfile]
    | Paginated[Session]
    | Paginated[EmotionRecord]
    | Paginated[Report]
)


def public_record(model: type[RecordModel], record: dict[str, Any]) -> RecordModel:
    return model.model_validate(
        {key: record[key] for key in model.model_fields if key in record}
    )


def record_page(
    model: type[RecordModel],
    records: list[dict[str, Any]],
    limit: int,
    offset: int,
    total: int,
) -> Paginated[RecordModel]:
    # Items are validated by their concrete model before pagination. This avoids
    # constructing a runtime generic type from an untyped dynamic variable.
    return Paginated(
        items=[public_record(model, record) for record in records],
        limit=limit,
        offset=offset,
        total=total,
    )


class ApplicationService:
    def __init__(self, repository: CloudRepository):
        self.repository = repository

    async def resolve_user(self, principal: AppPrincipal) -> User:
        user = public_record(User, await self.repository.resolve_user(principal))
        if user.status != "active":
            raise CloudError(403, "account_disabled", "This account is unavailable.")
        return user

    async def update_me(self, user: User, body: UserPatch) -> User:
        record = await self.repository.update_user(
            str(user.id), {"display_name": body.display_name, "updated_at": utc_now()}
        )
        return public_record(User, record)

    async def family_capabilities(self) -> FamilyCapabilities:
        enabled = await self.repository.family_identity_ready()
        return FamilyCapabilities(child_age_band=enabled, parent_profile=enabled)

    async def require_family_identity(self) -> None:
        if not await self.repository.family_identity_ready():
            raise CloudError(
                503,
                "feature_unavailable",
                "Family identity is not enabled in this environment.",
            )

    async def parent_profile(self, user: User) -> ParentCommunityProfile | None:
        await self.require_family_identity()
        record = await self.repository.get_parent_profile(str(user.id))
        return (
            public_record(ParentCommunityProfile, record)
            if record is not None
            else None
        )

    async def save_parent_profile(
        self, user: User, body: ParentProfileWrite
    ) -> ParentCommunityProfile:
        await self.require_family_identity()
        return public_record(
            ParentCommunityProfile,
            await self.repository.save_parent_profile(str(user.id), body.nickname),
        )

    async def child(self, user: User, child_id: UUID) -> ChildProfile:
        return public_record(
            ChildProfile,
            await self.repository.get_owned("children", str(child_id), str(user.id)),
        )

    async def create_child(self, user: User, body: ChildWrite) -> ChildProfile:
        if "age_band" in body.model_fields_set:
            await self.require_family_identity()
        now = utc_now()
        record: dict[str, Any] = {
            "id": str(uuid4()),
            "nickname": body.nickname,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        if "age_band" in body.model_fields_set:
            record["age_band"] = body.age_band
        return public_record(
            ChildProfile,
            await self.repository.create_owned("children", record, str(user.id)),
        )

    async def update_child(
        self, user: User, child_id: UUID, body: ChildWrite
    ) -> ChildProfile:
        await self.child(user, child_id)
        if "age_band" in body.model_fields_set:
            await self.require_family_identity()
        changes: dict[str, Any] = {"nickname": body.nickname, "updated_at": utc_now()}
        if "age_band" in body.model_fields_set:
            changes["age_band"] = body.age_band
        record = await self.repository.update_owned(
            "children",
            str(child_id),
            str(user.id),
            changes,
        )
        return public_record(ChildProfile, record)

    async def archive_child(self, user: User, child_id: UUID):
        child = await self.child(user, child_id)
        if child.status != "archived":
            await self.repository.update_owned(
                "children",
                str(child_id),
                str(user.id),
                {"status": "archived", "updated_at": utc_now()},
                {"status": "active"},
            )

    async def create_session(self, user: User, body: SessionCreate) -> Session:
        child = await self.child(user, body.child_profile_id)
        # Archive blocks requests validated after archival. A request which
        # already validated an active profile may finish while archive overlaps;
        # cloud metadata does not control or stop independent local capture.
        if child.status != "active":
            raise CloudError(409, "profile_archived", "Choose an active child profile.")
        now = utc_now()
        record = {
            "id": str(uuid4()),
            "child_profile_id": str(child.id),
            "source_platform": body.source_platform,
            "started_at": now,
            "ended_at": None,
            "status": "active",
            "created_at": now,
        }
        return public_record(
            Session,
            await self.repository.create_owned("sessions", record, str(user.id)),
        )

    async def session(self, user: User, session_id: UUID) -> Session:
        return public_record(
            Session,
            await self.repository.get_owned("sessions", str(session_id), str(user.id)),
        )

    async def end_session(self, user: User, session_id: UUID) -> Session:
        session = await self.session(user, session_id)
        if session.status == "ended":
            return session
        record = await self.repository.update_owned(
            "sessions",
            str(session_id),
            str(user.id),
            {"status": "ended", "ended_at": utc_now()},
            {"status": "active"},
        )
        return public_record(Session, record)

    async def list_records(
        self,
        user: User,
        kind: Entity,
        *,
        limit: int = 20,
        offset: int = 0,
        child_profile_id: UUID | None = None,
        include_archived: bool = False,
        range_start: datetime | None = None,
        range_end: datetime | None = None,
    ) -> RecordPage:
        filters: dict[str, Any] = {}
        if child_profile_id is not None:
            await self.child(user, child_profile_id)
            filters["child_profile_id"] = str(child_profile_id)
        if kind == "children" and not include_archived:
            filters["status"] = "active"
        if range_start is not None or range_end is not None:
            field = {
                "emotions": "timestamp",
                "reports": "range_end",
                "sessions": "started_at",
            }[kind]
            filters[field] = {}
            for operator, date in (("$gte", range_start), ("$lte", range_end)):
                if date is not None:
                    filters[field][operator] = (
                        date.astimezone(timezone.utc)
                        .isoformat(timespec="microseconds")
                        .replace("+00:00", "Z")
                    )
        records, total = await self.repository.list_owned(
            kind, str(user.id), filters, limit, offset
        )
        if kind == "children":
            return record_page(ChildProfile, records, limit, offset, total)
        if kind == "sessions":
            return record_page(Session, records, limit, offset, total)
        if kind == "emotions":
            return record_page(EmotionRecord, records, limit, offset, total)
        return record_page(Report, records, limit, offset, total)

    async def current_report(
        self, user: User, child_profile_id: UUID | None = None
    ) -> CurrentReport:
        reports = await self.list_records(
            user, "reports", child_profile_id=child_profile_id, limit=1
        )
        report = reports.items[0] if reports.items else None
        if report is not None and not isinstance(report, Report):
            raise unavailable()
        return CurrentReport(
            status="available" if report is not None else "empty", report=report
        )
