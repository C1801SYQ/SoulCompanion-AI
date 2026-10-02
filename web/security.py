"""Local operator boundary, request IDs, bounded access and uniform errors."""
from __future__ import annotations

import ipaddress
import logging
import time
import uuid
from collections import deque
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import RATE_LIMIT_PER_MINUTE

logger = logging.getLogger("web.requests")


def error_response(request: Request, code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message,
                                   "request_id": request.state.request_id}}, status_code=status)


def is_loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value == "localhost"


def local_request(request: Request) -> bool:
    """Do not trust proxy headers or arbitrary DNS names, even on loopback."""
    host = urlsplit("http://" + request.headers.get("host", ""))
    client = request.client.host if request.client else ""
    test_client = client == "testclient" and host.hostname == "testserver"
    if not test_client and (not is_loopback(client) or not is_loopback(host.hostname or "")):
        return False
    if any(name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto")):
        return False
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != host.netloc:
            return False
    return request.headers.get("sec-fetch-site") != "cross-site"


def install_security(app: FastAPI) -> None:
    # A fixed one-operator bucket has bounded memory and is shared by all local clients.
    requests: deque[float] = deque(maxlen=RATE_LIMIT_PER_MINUTE)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        try:
            allowed = local_request(request)
        except ValueError:
            allowed = False
        if not allowed:
            response = error_response(request, "LOCAL_ACCESS_ONLY", "Only same-origin local access is supported", 403)
        else:
            now = time.monotonic()
            while requests and now - requests[0] >= 60:
                requests.popleft()
            if request.url.path.startswith("/api/") and len(requests) >= RATE_LIMIT_PER_MINUTE:
                response = error_response(request, "RATE_LIMITED", "Too many requests; retry in one minute", 429)
                response.headers["Retry-After"] = "60"
            else:
                if request.url.path.startswith("/api/"):
                    requests.append(now)
                try:
                    response = await call_next(request)
                except Exception as exc:
                    logger.error("request_failed request_id=%s type=%s", request.state.request_id, type(exc).__name__)
                    response = error_response(request, "INTERNAL_ERROR", "The request could not be completed", 500)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, "INVALID_REQUEST", "Request parameters failed validation", 422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: HTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "REQUEST_FAILED"
        return error_response(request, code, "Resource not found" if exc.status_code == 404 else "Request rejected", exc.status_code)
