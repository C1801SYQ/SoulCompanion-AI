"""Bounded request processing, exact CORS, and per-instance development limits."""

from collections import OrderedDict
import asyncio
from hashlib import sha256
import json
import logging
from threading import RLock
from time import monotonic
from uuid import uuid4

from .config import Settings
from .errors import CloudError


access_logger = logging.getLogger("soulcompanion.cloud.access")


class RateLimiter:
    """Bounded counters local to this function instance, not a global cloud quota."""

    def __init__(self, window_seconds: int, max_keys: int = 4096):
        self.window_seconds, self.max_keys = window_seconds, max_keys
        self.entries: OrderedDict[tuple[str, str], tuple[float, int]] = OrderedDict()
        self.lock = RLock()

    def consume(self, namespace: str, value: str, limit: int) -> bool:
        key = (namespace, sha256(value.encode()).hexdigest())
        now = monotonic()
        with self.lock:
            while self.entries:
                first_key, (started, _) = next(iter(self.entries.items()))
                if now - started < self.window_seconds:
                    break
                self.entries.pop(first_key)
            entry = self.entries.get(key)
            if entry is None or now - entry[0] >= self.window_seconds:
                # Saturation fails closed; new caller IDs cannot evict blocked IDs.
                if entry is None and len(self.entries) >= self.max_keys:
                    return False
                entry = (now, 0)
            self.entries[key] = (entry[0], entry[1] + 1)
            return entry[1] < limit


class SecurityMiddleware:
    def __init__(self, app, settings: Settings, limiter: RateLimiter):
        self.app, self.settings, self.limiter = app, settings, limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started, request_id, status = monotonic(), str(uuid4()), 500
        response_started = False
        scope.setdefault("state", {})["request_id"] = request_id
        headers: dict[str, str | None] = {}
        for key, value in scope.get("headers", []):
            name = key.decode("latin1").lower()
            # Duplicate security-sensitive headers must not be normalized ambiguously.
            if name in headers and name in {
                "origin",
                "content-length",
                "authorization",
            }:
                headers[name] = None
            elif name not in headers:
                headers[name] = value.decode("latin1")
        origin = headers.get("origin")
        allowed = origin is not None and origin in self.settings.allowed_origins

        async def send_response(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                extra = [
                    (b"x-request-id", request_id.encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
                if allowed and origin is not None:
                    extra += [
                        (b"access-control-allow-origin", origin.encode("latin1")),
                        (b"vary", b"Origin"),
                        (b"access-control-expose-headers", b"X-Request-ID"),
                    ]
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in {b"x-request-id", b"cache-control"}
                ] + extra
            await send(message)

        async def fail(code, error, message):
            body = json.dumps(
                {
                    "error": {
                        "code": error,
                        "message": message,
                        "request_id": request_id,
                    }
                },
                separators=(",", ":"),
            ).encode()
            await send_response(
                {
                    "type": "http.response.start",
                    "status": code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send_response({"type": "http.response.body", "body": body})

        try:
            if "origin" in headers and not allowed:
                await fail(403, "origin_not_allowed", "Origin is not allowed.")
                return
            if headers.get("authorization", "") is None:
                await fail(401, "unauthorized", "Please sign in again.")
                return
            host = (scope.get("client") or ("unknown", 0))[0]
            public = scope["path"] in {"/api/v2/healthz", "/api/v2/readyz"}
            namespace, limit = (
                ("health", self.settings.health_rate_limit)
                if public
                else ("preauth", self.settings.preauth_rate_limit)
            )
            if not self.limiter.consume(namespace, host, limit):
                await fail(429, "rate_limited", "Too many requests. Try again shortly.")
                return
            if scope["method"] == "OPTIONS" and allowed:
                requested_method = (
                    headers.get("access-control-request-method") or ""
                ).upper()
                requested_headers = {
                    item.strip().lower()
                    for item in (
                        headers.get("access-control-request-headers") or ""
                    ).split(",")
                    if item.strip()
                }
                if requested_method not in {
                    "GET",
                    "POST",
                    "PATCH",
                    "PUT",
                    "DELETE",
                } or not requested_headers <= {"authorization", "content-type"}:
                    await fail(
                        403, "cors_not_allowed", "Cross-origin request is not allowed."
                    )
                    return
                await send_response(
                    {
                        "type": "http.response.start",
                        "status": 204,
                        "headers": [
                            (
                                b"access-control-allow-methods",
                                b"GET, POST, PATCH, PUT, DELETE",
                            ),
                            (
                                b"access-control-allow-headers",
                                b"Authorization, Content-Type",
                            ),
                            (b"access-control-max-age", b"300"),
                        ],
                    }
                )
                await send_response({"type": "http.response.body", "body": b""})
                return
            length = headers.get("content-length", "0")
            if length is None or not length.isascii() or not length.isdecimal():
                await fail(400, "invalid_request", "Invalid request.")
                return
            if len(length) > 10 or int(length) > self.settings.max_body_bytes:
                await fail(413, "request_too_large", "Request body is too large.")
                return
            chunks, size = [], 0
            while True:
                remaining = max(
                    0, self.settings.request_timeout_seconds - (monotonic() - started)
                )
                message = await asyncio.wait_for(receive(), timeout=remaining)
                if message["type"] == "http.disconnect":
                    return
                body = message.get("body", b"")
                size += len(body)
                if size > self.settings.max_body_bytes:
                    await fail(413, "request_too_large", "Request body is too large.")
                    return
                chunks.append(body)
                if not message.get("more_body", False):
                    break
            content = b"".join(chunks)
            consumed = False

            async def bounded_receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": content, "more_body": False}
                return await receive()

            remaining = max(
                0, self.settings.request_timeout_seconds - (monotonic() - started)
            )
            async with asyncio.timeout(remaining):
                await self.app(scope, bounded_receive, send_response)
        except TimeoutError:
            if response_started:
                raise
            await fail(
                503, "service_unavailable", "Cloud service is temporarily unavailable."
            )
        except Exception:
            if response_started:
                raise
            await fail(
                500, "internal_error", "Cloud service is temporarily unavailable."
            )
        finally:
            route = scope.get("route")
            access_logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "route": getattr(route, "path", "unmatched"),
                        "status": status,
                        "latency_ms": round((monotonic() - started) * 1000, 2),
                    },
                    separators=(",", ":"),
                )
            )


def check_user_rate(limiter: RateLimiter, settings: Settings, user_id: str):
    if not limiter.consume("user", user_id, settings.private_rate_limit):
        raise CloudError(429, "rate_limited", "Too many requests. Try again shortly.")
