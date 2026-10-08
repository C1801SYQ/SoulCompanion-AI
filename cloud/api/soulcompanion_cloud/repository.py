"""Storage boundary. Private document queries always include the application owner."""

from copy import deepcopy
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import UUID, uuid5

import httpx

from .auth import AppPrincipal
from .config import Settings
from .errors import not_found, unavailable


Entity = Literal["children", "sessions", "emotions", "reports"]
COLLECTIONS = {
    "users": "sc_v2_users",
    "identities": "sc_v2_identities",
    "children": "sc_v2_child_profiles",
    "sessions": "sc_v2_sessions",
    "emotions": "sc_v2_emotion_records",
    "reports": "sc_v2_reports",
    "schema": "sc_v2_app_schema",
}
IDENTITY_NAMESPACE = UUID("83133d5c-ea3f-4d0d-b4ca-dfa7af613bc0")
USER_NAMESPACE = UUID("1cf37531-0292-40e9-9619-4f6c1589f9cc")


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def identity_records(principal: AppPrincipal) -> tuple[dict, dict]:
    key = json.dumps(
        [principal.issuer, principal.provider, principal.subject], separators=(",", ":")
    )
    # Public IDs contain neither the raw CloudBase UID nor a reversible encoding.
    digest = sha256(key.encode()).hexdigest()
    user_id, identity_id = str(uuid5(USER_NAMESPACE, digest)), str(
        uuid5(IDENTITY_NAMESPACE, digest)
    )
    now = utc_now()
    user = {
        "_id": user_id,
        "id": user_id,
        "display_name": "",
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    identity = {
        "_id": identity_id,
        "id": identity_id,
        "user_id": user_id,
        "provider": principal.provider,
        "provider_subject": principal.subject,
        "issuer": principal.issuer,
        "created_at": now,
    }
    return user, identity


class CloudRepository(Protocol):
    async def ready(self) -> bool: ...
    async def resolve_user(self, principal: AppPrincipal) -> dict: ...
    async def update_user(self, user_id: str, changes: dict) -> dict: ...
    async def get_owned(self, entity: Entity, record_id: str, owner: str) -> dict: ...
    async def create_owned(self, entity: Entity, record: dict, owner: str) -> dict: ...
    async def update_owned(
        self,
        entity: Entity,
        record_id: str,
        owner: str,
        changes: dict,
        expected: dict | None = None,
    ) -> dict: ...
    async def list_owned(
        self, entity: Entity, owner: str, filters: dict, limit: int, offset: int
    ) -> tuple[list[dict], int]: ...


def _matches(record: dict, query: dict) -> bool:
    for key, expected in query.items():
        actual = record.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                return False
            if "$lte" in expected and (actual is None or actual > expected["$lte"]):
                return False
        elif actual != expected:
            return False
    return True


class InMemoryRepository:
    """Injected deterministic local test store; production never selects this class."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.identities: dict[str, dict] = {}
        self.records: dict[str, dict[str, dict]] = {
            kind: {} for kind in ("children", "sessions", "emotions", "reports")
        }
        self._lock = RLock()

    async def ready(self) -> bool:
        return True

    async def resolve_user(self, principal: AppPrincipal) -> dict:
        user, identity = identity_records(principal)
        with self._lock:
            self.users.setdefault(user["id"], user)
            self.identities.setdefault(identity["id"], identity)
            return deepcopy(self.users[user["id"]])

    async def update_user(self, user_id: str, changes: dict) -> dict:
        with self._lock:
            if user_id not in self.users:
                raise not_found()
            self.users[user_id].update(changes)
            return deepcopy(self.users[user_id])

    async def get_owned(self, entity: Entity, record_id: str, owner: str) -> dict:
        with self._lock:
            record = self.records[entity].get(record_id)
            if record is None or record["owner_user_id"] != owner:
                raise not_found()
            return deepcopy(record)

    async def create_owned(self, entity: Entity, record: dict, owner: str) -> dict:
        with self._lock:
            value = {**record, "_id": record["id"], "owner_user_id": owner}
            self.records[entity][record["id"]] = value
            return deepcopy(value)

    async def update_owned(
        self,
        entity: Entity,
        record_id: str,
        owner: str,
        changes: dict,
        expected: dict | None = None,
    ) -> dict:
        with self._lock:
            record = await self.get_owned(entity, record_id, owner)
            if expected is None or _matches(record, expected):
                self.records[entity][record_id].update(changes)
            return deepcopy(self.records[entity][record_id])

    async def list_owned(
        self, entity: Entity, owner: str, filters: dict, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        with self._lock:
            records = [
                value
                for value in self.records[entity].values()
                if _matches(value, {**filters, "owner_user_id": owner})
            ]
            time_field = {"emotions": "timestamp", "reports": "range_end"}.get(
                entity, "created_at"
            )
            records.sort(key=lambda item: (item[time_field], item["id"]), reverse=True)
            return deepcopy(records[offset : offset + limit]), len(records)


def decode_ejson(value: Any) -> Any:
    """Decode the limited Strict EJSON scalar types used in metadata records."""
    if isinstance(value, list):
        return [decode_ejson(item) for item in value]
    if isinstance(value, dict):
        if len(value) == 1:
            key, item = next(iter(value.items()))
            if key in {"$numberInt", "$numberLong"}:
                return int(item)
            if key in {"$numberDouble", "$numberDecimal"}:
                number = float(item)
                if not math.isfinite(number):
                    raise ValueError("Nonfinite metadata number")
                return number
            if key == "$date":
                if isinstance(item, str):
                    return item
                milliseconds = decode_ejson(item)
                return (
                    datetime.fromtimestamp(milliseconds / 1000, timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
        return {key: decode_ejson(item) for key, item in value.items()}
    return value


class _UnconfirmedInsert(Exception):
    """An insert may conflict with a concurrent deterministic-key insert."""


class CloudBaseDocumentRepository:
    """Official NoSQL HTTP API with an explicit, server-only API key.

    The default document database and pre-provisioned sc_v2_* collections are used.
    This adapter cannot create collections, indexes, auth providers or cloud resources.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client
        self.base = f"{settings.cloudbase_base_url}/v1/database/instances/(default)/databases/(default)"

    async def _request(
        self,
        method: str,
        suffix: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
        missing_ok: bool = False,
        confirm_insert_conflict: bool = False,
    ) -> Any:
        if not self.settings.env_id or not self.settings.api_key:
            raise unavailable()
        try:
            response = await self.client.request(
                method,
                f"{self.base}/{suffix}",
                params=params,
                json=body,
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                timeout=self.settings.upstream_timeout_seconds,
            )
        except httpx.HTTPError:
            raise unavailable() from None
        if response.status_code == 404 and missing_ok:
            return None
        if confirm_insert_conflict and response.status_code in {409, 500}:
            # This provider also reports duplicate primary keys as HTTP 500.
            # Never treat that response itself as acknowledgment of a write.
            raise _UnconfirmedInsert()
        if response.status_code not in {200, 201}:
            raise unavailable()
        try:
            data = decode_ejson(response.json())
        except (ValueError, TypeError, OverflowError):
            raise unavailable() from None
        if not isinstance(data, dict):
            raise unavailable()
        return data

    @staticmethod
    def _documents(entity: str) -> str:
        return f"collections/{COLLECTIONS[entity]}/documents"

    async def ready(self) -> bool:
        if not self.settings.api_key or not self.settings.env_id:
            return False
        try:
            marker = await self._request(
                "GET", f"{self._documents('schema')}/phase04", missing_ok=True
            )
            if marker is None or marker.get("version") != 1:
                return False
            # A marker alone cannot turn readiness healthy if collections are missing.
            async with asyncio.timeout(2.2):
                counts = await asyncio.gather(
                    *(
                        self._request(
                            "GET",
                            self._documents(kind),
                            params={"query": "{}", "count": "true"},
                        )
                        for kind in (
                            "users",
                            "identities",
                            "children",
                            "sessions",
                            "emotions",
                            "reports",
                        )
                    )
                )
            return all(
                type(count.get("total")) is int and count["total"] >= 0
                for count in counts
            )
        except Exception:
            # Readiness deliberately exposes only a boolean; request failures still
            # propagate as sanitized 503 on application routes.
            return False

    async def _find_one(self, kind: str, query: dict) -> dict | None:
        data = await self._request(
            "GET",
            self._documents(kind),
            params={
                "query": json.dumps(query, separators=(",", ":")),
                "limit": "1",
                "offset": "0",
            },
        )
        items = data.get("list")
        if (
            not isinstance(items, list)
            or len(items) > 1
            or any(not isinstance(item, dict) for item in items)
        ):
            raise unavailable()
        if items and not _matches(items[0], query):
            raise unavailable()
        return items[0] if items else None

    @staticmethod
    def _validate_update_acknowledgment(response: dict):
        if (
            type(response.get("matched")) is not int
            or response["matched"] not in {0, 1}
            or type(response.get("updated")) is not int
            or response["updated"] not in {0, 1}
        ):
            raise unavailable()

    async def resolve_user(self, principal: AppPrincipal) -> dict:
        user, identity = identity_records(principal)
        identity_query = {
            key: identity[key]
            for key in (
                "_id",
                "id",
                "issuer",
                "provider",
                "provider_subject",
                "user_id",
            )
        }
        # Unique deterministic primary keys make first requests converge without
        # provider-specific update operators or overwriting existing profile data.
        existing = await self._ensure_canonical_insert(
            "users", user, {"_id": user["id"], "id": user["id"]}
        )
        await self._ensure_canonical_insert("identities", identity, identity_query)
        return existing

    async def _ensure_canonical_insert(
        self, kind: str, record: dict, immutable_query: dict
    ) -> dict:
        existing = await self._find_one(kind, immutable_query)
        if existing is not None:
            return existing
        try:
            response = await self._request(
                "POST",
                self._documents(kind),
                body={"data": [record]},
                confirm_insert_conflict=True,
            )
            if response.get("insertedIds") != [record["id"]]:
                raise unavailable()
        except _UnconfirmedInsert:
            # A conflicting insert is valid only when the independently fetched
            # canonical document matches every immutable identity field below.
            pass
        existing = await self._find_one(kind, immutable_query)
        if existing is None:
            raise unavailable()
        return existing

    async def update_user(self, user_id: str, changes: dict) -> dict:
        response = await self._request(
            "PATCH",
            self._documents("users"),
            body={
                "query": {"_id": user_id, "id": user_id},
                "data": {"$set": changes},
                "multi": False,
                "upsert": False,
                "replaceMode": False,
            },
        )
        self._validate_update_acknowledgment(response)
        value = await self._find_one("users", {"_id": user_id, "id": user_id})
        if value is None:
            raise not_found()
        if response["matched"] != 1 or not _matches(value, changes):
            raise unavailable()
        return value

    async def get_owned(self, entity: Entity, record_id: str, owner: str) -> dict:
        record = await self._find_one(entity, {"id": record_id, "owner_user_id": owner})
        if record is None:
            raise not_found()
        return record

    async def create_owned(self, entity: Entity, record: dict, owner: str) -> dict:
        value = {**record, "_id": record["id"], "owner_user_id": owner}
        response = await self._request(
            "POST", self._documents(entity), body={"data": [value]}
        )
        if response.get("insertedIds") != [record["id"]]:
            raise unavailable()
        return value

    async def update_owned(
        self,
        entity: Entity,
        record_id: str,
        owner: str,
        changes: dict,
        expected: dict | None = None,
    ) -> dict:
        query = {**(expected or {}), "id": record_id, "owner_user_id": owner}
        response = await self._request(
            "PATCH",
            self._documents(entity),
            body={
                "query": query,
                "data": {"$set": changes},
                "multi": False,
                "upsert": False,
                "replaceMode": False,
            },
        )
        self._validate_update_acknowledgment(response)
        value = await self.get_owned(entity, record_id, owner)
        if response["matched"] == 1 and not _matches(value, changes):
            raise unavailable()
        if response["matched"] == 0 and (expected is None or _matches(value, expected)):
            raise unavailable()
        return value

    async def list_owned(
        self, entity: Entity, owner: str, filters: dict, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        query = {**filters, "owner_user_id": owner}
        params = {"query": json.dumps(query, separators=(",", ":"))}
        count = await self._request(
            "GET", self._documents(entity), params={**params, "count": "true"}
        )
        field = {"emotions": "timestamp", "reports": "range_end"}.get(
            entity, "created_at"
        )
        response = await self._request(
            "GET",
            self._documents(entity),
            params={
                **params,
                "limit": str(limit),
                "offset": str(offset),
                "order": json.dumps(
                    [
                        {"field": field, "direction": "desc"},
                        {"field": "id", "direction": "desc"},
                    ],
                    separators=(",", ":"),
                ),
            },
        )
        records, total = response.get("list"), count.get("total")
        if (
            not isinstance(records, list)
            or len(records) > limit
            or type(total) is not int
            or total < 0
            or any(
                not isinstance(record, dict) or not _matches(record, query)
                for record in records
            )
        ):
            raise unavailable()
        return records, total
