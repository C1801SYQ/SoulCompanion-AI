"""Bounded PC03 storage: official NoSQL transport, canonical insert and CAS.

The in-memory implementation is explicitly injected only by tests. Neither
adapter provisions resources or accepts database operators from HTTP callers.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid5

from ..errors import CloudError, unavailable
from ..repository import CloudBaseDocumentRepository, _UnconfirmedInsert
from .schema import (
    COMMUNITY_BASE_MARKERS,
    COMMUNITY_COLLECTIONS,
    COMMUNITY_MARKER_ID,
    COMMUNITY_SCHEMA_CHECKSUM,
    COMMUNITY_SCHEMA_OWNER,
    COMMUNITY_SCHEMA_VERSION,
    SCHEMA_COLLECTION,
)


QUOTA_LIMITS = {"post": 10, "comment": 100, "report": 20, "relation": 200, "moderation": 200}
QUOTA_NAMESPACE = UUID("3e3f419a-b964-4a6d-8e52-8c333896ef2e")
MAX_RECORD_BYTES = 65536
MAX_QUERY_RECORDS = 51
SORT_FIELDS = {"created_at", "updated_at", "published_at"}


class CommunityRepository(Protocol):
    async def ready(self) -> bool: ...
    async def get(self, kind: str, record_id: str) -> dict | None: ...
    async def list(self, kind: str, query: dict, time_field: str, limit: int) -> list[dict]: ...
    async def insert(self, kind: str, record: dict, immutable: dict) -> tuple[dict, bool]: ...
    async def cas(self, kind: str, record_id: str, expected: dict, changes: dict) -> bool: ...
    async def consume_quota(self, owner: str, action: str) -> None: ...


def validate_query(query: dict, *, depth: int = 0) -> None:
    if not isinstance(query, dict) or len(query) > 16 or depth > 1:
        raise unavailable()
    for key, expected in query.items():
        if key == "$or":
            if depth or not isinstance(expected, list) or not 1 <= len(expected) <= 2:
                raise unavailable()
            for branch in expected:
                validate_query(branch, depth=depth + 1)
            continue
        if not isinstance(key, str) or re.fullmatch(r"[a-z_][a-z0-9_]{0,63}", key) is None:
            raise unavailable()
        if isinstance(expected, dict):
            if len(expected) != 1:
                raise unavailable()
            operator, value = next(iter(expected.items()))
            if operator == "$lt":
                if not isinstance(value, str):
                    raise unavailable()
            elif operator == "$in":
                if not isinstance(value, list) or len(value) > MAX_QUERY_RECORDS or any(not isinstance(item, str) for item in value):
                    raise unavailable()
            else:
                raise unavailable()
        elif expected is not None and type(expected) not in {str, int, bool}:
            raise unavailable()


def matches(record: dict, query: dict) -> bool:
    """Strict server-generated subset; unknown operators fail rather than match."""
    if not isinstance(record, dict) or not isinstance(query, dict):
        raise unavailable()
    validate_query(query)
    for key, expected in query.items():
        if key == "$or":
            if not isinstance(expected, list) or not 1 <= len(expected) <= 2:
                raise unavailable()
            results = [matches(record, branch) for branch in expected]
            if not any(results):
                return False
            continue
        if not isinstance(key, str) or key.startswith("$") or "." in key:
            raise unavailable()
        actual = record.get(key)
        if isinstance(expected, dict):
            if len(expected) != 1:
                raise unavailable()
            operator, boundary = next(iter(expected.items()))
            if operator == "$in":
                if not isinstance(boundary, list) or len(boundary) > MAX_QUERY_RECORDS:
                    raise unavailable()
                if actual not in boundary:
                    return False
            elif operator == "$lt":
                if not isinstance(actual, str) or not isinstance(boundary, str):
                    raise unavailable()
                if actual >= boundary:
                    return False
            else:
                raise unavailable()
        elif type(actual) is not type(expected) or actual != expected:
            return False
    return True


def validate_record(record: dict) -> None:
    try:
        if not isinstance(record, dict) or record.get("_id") != record.get("id"):
            raise ValueError
        if str(UUID(record["id"])) != record["id"]:
            raise ValueError
        data = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_RECORD_BYTES:
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise unavailable() from None


def verified_existing(value: dict | None, immutable: dict) -> dict:
    if value is None:
        raise unavailable()
    if not matches(value, immutable):
        raise CloudError(409, "idempotency_conflict", "This request key is already used for different input.")
    validate_record(value)
    return value


class QuotaMixin:
    async def consume_quota(self, owner: str, action: str) -> None:
        if action not in QUOTA_LIMITS:
            raise unavailable()
        bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota_id = str(uuid5(QUOTA_NAMESPACE, json.dumps([owner, action, bucket], separators=(",", ":"))))
        immutable = {"_id": quota_id, "id": quota_id, "owner_id": owner, "action": action, "bucket": bucket}
        record = await self.get("write_quotas", quota_id)
        if record is None:
            record, _ = await self.insert("write_quotas", {**immutable, "used": 0, "row_version": 1}, immutable)
        for attempt in range(3):
            if not matches(record, immutable):
                raise unavailable()
            used, version = record.get("used"), record.get("row_version")
            if type(used) is not int or type(version) is not int or used < 0 or version != used + 1:
                raise unavailable()
            if used >= QUOTA_LIMITS[action]:
                raise CloudError(429, "community_quota_exceeded", "Daily community action limit reached.")
            if await self.cas("write_quotas", quota_id, {**immutable, "used": used, "row_version": version},
                              {"used": used + 1, "row_version": version + 1}):
                return
            if attempt < 2:
                record = await self.get("write_quotas", quota_id)
                if record is None:
                    raise unavailable()
        raise unavailable()


class CommunityDocumentRepository(QuotaMixin):
    def __init__(self, transport: CloudBaseDocumentRepository):
        self.transport = transport

    @staticmethod
    def _documents(kind: str) -> str:
        if kind not in COMMUNITY_COLLECTIONS:
            raise unavailable()
        return f"collections/{COMMUNITY_COLLECTIONS[kind]}/documents"

    async def ready(self) -> bool:
        expected = (*COMMUNITY_BASE_MARKERS,
                    (COMMUNITY_MARKER_ID, COMMUNITY_SCHEMA_OWNER, COMMUNITY_SCHEMA_CHECKSUM, COMMUNITY_SCHEMA_VERSION))
        response = await self.transport._request("GET", f"collections/{SCHEMA_COLLECTION}/documents", params={
            "query": json.dumps({"_id": {"$in": [row[0] for row in expected]}}, separators=(",", ":")),
            "limit": "3", "offset": "0",
        })
        rows = response.get("list")
        if not isinstance(rows, list) or len(rows) != 3 or any(not isinstance(row, dict) for row in rows):
            return False
        by_id = {row.get("_id"): row for row in rows if isinstance(row.get("_id"), str)}
        if len(by_id) != 3 or set(by_id) != {row[0] for row in expected}:
            return False
        return all(row.get("owner") == owner and row.get("checksum") == checksum
                   and type(row.get("version")) is int and row["version"] == version
                   for marker_id, owner, checksum, version in expected for row in (by_id[marker_id],))

    async def get(self, kind: str, record_id: str) -> dict | None:
        rows = await self._query(kind, {"_id": record_id, "id": record_id}, limit=1)
        return rows[0] if rows else None

    async def _query(self, kind: str, query: dict, *, limit: int, time_field: str | None = None) -> list[dict]:
        validate_query(query)
        if type(limit) is not int or not 1 <= limit <= MAX_QUERY_RECORDS:
            raise unavailable()
        params = {"query": json.dumps(query, separators=(",", ":")), "limit": str(limit), "offset": "0"}
        if time_field is not None:
            if time_field not in SORT_FIELDS:
                raise unavailable()
            params["order"] = json.dumps([
                {"field": time_field, "direction": "desc"},
                {"field": "id", "direction": "desc"},
            ], separators=(",", ":"))
        data = await self.transport._request("GET", self._documents(kind), params=params)
        rows = data.get("list")
        if not isinstance(rows, list) or len(rows) > limit or any(not isinstance(row, dict) for row in rows):
            raise unavailable()
        ids = set()
        for row in rows:
            validate_record(row)
            if not matches(row, query) or row["id"] in ids:
                raise unavailable()
            ids.add(row["id"])
        if time_field is not None:
            try:
                keys = [(row[time_field], row["id"]) for row in rows]
                if any(not isinstance(key[0], str) for key in keys) or keys != sorted(keys, reverse=True):
                    raise unavailable()
            except (KeyError, TypeError):
                raise unavailable() from None
        return rows

    async def list(self, kind: str, query: dict, time_field: str, limit: int) -> list[dict]:
        return await self._query(kind, query, limit=limit, time_field=time_field)

    async def insert(self, kind: str, record: dict, immutable: dict) -> tuple[dict, bool]:
        validate_record(record)
        if not matches(record, immutable) or immutable.get("_id") != record["id"]:
            raise unavailable()
        try:
            response = await self.transport._request("POST", self._documents(kind), body={"data": [record]},
                                                     confirm_insert_conflict=True)
        except _UnconfirmedInsert:
            return verified_existing(await self.get(kind, record["id"]), immutable), False
        if response.get("insertedIds") != [record["id"]]:
            # A malformed acknowledgment cannot claim success; a canonical
            # record read is the only permissible confirmation.
            return verified_existing(await self.get(kind, record["id"]), immutable), False
        return deepcopy(record), True

    async def cas(self, kind: str, record_id: str, expected: dict, changes: dict) -> bool:
        validate_query(expected)
        if expected.get("_id") != record_id or not isinstance(changes, dict) or not changes or {"id", "_id"} & changes.keys():
            raise unavailable()
        try:
            if len(json.dumps(changes, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RECORD_BYTES:
                raise unavailable()
        except (ValueError, TypeError, UnicodeError):
            raise unavailable() from None
        response = await self.transport._request("PATCH", self._documents(kind), body={
            "query": expected, "data": {"$set": changes}, "multi": False, "upsert": False, "replaceMode": False,
        })
        matched, updated = response.get("matched"), response.get("updated")
        if type(matched) is not int or type(updated) is not int or (matched, updated) not in {(0, 0), (1, 1)}:
            raise unavailable()
        return matched == 1


class InMemoryCommunityRepository(QuotaMixin):
    """Explicit test injection; lock models atomic single-document operations."""

    def __init__(self, *, enabled: bool = True):
        self.enabled = enabled
        self.records = {kind: {} for kind in COMMUNITY_COLLECTIONS}
        self._lock = RLock()

    async def ready(self) -> bool:
        return self.enabled

    async def get(self, kind: str, record_id: str) -> dict | None:
        with self._lock:
            return deepcopy(self.records[kind].get(record_id))

    async def list(self, kind: str, query: dict, time_field: str, limit: int) -> list[dict]:
        validate_query(query)
        if type(limit) is not int or not 1 <= limit <= MAX_QUERY_RECORDS or time_field not in SORT_FIELDS:
            raise unavailable()
        with self._lock:
            rows = [row for row in self.records[kind].values() if matches(row, query)]
            rows.sort(key=lambda row: (row[time_field], row["id"]), reverse=True)
            return deepcopy(rows[:limit])

    async def insert(self, kind: str, record: dict, immutable: dict) -> tuple[dict, bool]:
        validate_record(record)
        with self._lock:
            existing = self.records[kind].get(record["id"])
            if existing is not None:
                return deepcopy(verified_existing(existing, immutable)), False
            if not matches(record, immutable) or immutable.get("_id") != record["id"]:
                raise unavailable()
            self.records[kind][record["id"]] = deepcopy(record)
            return deepcopy(record), True

    async def cas(self, kind: str, record_id: str, expected: dict, changes: dict) -> bool:
        validate_query(expected)
        with self._lock:
            record = self.records[kind].get(record_id)
            if record is None or not matches(record, expected):
                return False
            updated = {**record, **deepcopy(changes)}
            validate_record(updated)
            self.records[kind][record_id] = updated
            return True


class UnavailableCommunityRepository:
    """An old injected family store must not silently enable test community data."""

    async def ready(self) -> bool:
        return False

    def __getattr__(self, name):
        raise unavailable()
