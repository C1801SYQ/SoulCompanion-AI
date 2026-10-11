"""Bounded keyset pagination with strict query/filter-bound cursors."""

import base64
from hashlib import sha256
import json
import re
from typing import Any, Callable, Generic, TypeVar, TypedDict

from ..errors import CloudError, unavailable
from .models import canonical_id, canonical_time


Projected = TypeVar("Projected")


class PageResult(TypedDict, Generic[Projected]):
    items: list[Projected]
    limit: int
    next_cursor: str | None


def invalid_cursor() -> CloudError:
    return CloudError(422, "invalid_cursor", "Invalid community page cursor.")


def normalize_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= 50:
        raise CloudError(422, "invalid_page_limit", "Community page size must be between 1 and 50.")
    return limit


def scope_hash(scope: dict[str, Any]) -> str:
    return sha256(json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate cursor keys.")
        result[key] = value
    return result


def decode_cursor(cursor: str, scope: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
            raise ValueError("Invalid cursor encoding.")
        payload = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        value = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != {"v", "scope", "time", "id"}:
            raise ValueError("Invalid cursor object.")
        if type(value["v"]) is not int or value["v"] != 1 or value["scope"] != scope_hash(scope):
            raise ValueError("Cursor scope does not match.")
        canonical_time(value["time"])
        canonical_id(value["id"])
        canonical = base64.urlsafe_b64encode(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        if cursor != canonical:
            raise ValueError("Noncanonical cursor.")
        return value
    except (ValueError, TypeError, UnicodeError, KeyError):
        raise invalid_cursor() from None


def encode_cursor(record: dict[str, Any], scope: dict[str, Any], time_field: str) -> str:
    try:
        value = {
            "v": 1, "scope": scope_hash(scope),
            "time": canonical_time(record[time_field]), "id": canonical_id(record["id"]),
        }
    except (KeyError, ValueError, TypeError):
        raise unavailable() from None
    return base64.urlsafe_b64encode(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")


def cursor_query(
    base_query: dict[str, Any], scope: dict[str, Any], time_field: str, cursor: str | None,
) -> dict[str, Any]:
    query = dict(base_query)
    if cursor is not None:
        value = decode_cursor(cursor, scope)
        query["$or"] = [
            {time_field: {"$lt": value["time"]}},
            {time_field: value["time"], "id": {"$lt": value["id"]}},
        ]
    return query


def page(
    records: list[dict[str, Any]], limit: int, scope: dict[str, Any], time_field: str,
    projector: Callable[[dict[str, Any]], Projected],
) -> PageResult[Projected]:
    normalize_limit(limit)
    if not isinstance(records, list) or len(records) > limit + 1:
        raise unavailable()
    visible = records[:limit]
    # Validation/projecting runs on the lookahead as well: it must not carry an invalid boundary.
    projected = [projector(record) for record in records]
    return {
        "items": projected[:limit], "limit": limit,
        "next_cursor": encode_cursor(visible[-1], scope, time_field) if len(records) > limit else None,
    }
