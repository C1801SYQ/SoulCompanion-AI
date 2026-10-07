"""FastAPI /api/v2; this app imports no legacy inference or hardware modules."""

from contextlib import asynccontextmanager
from datetime import datetime
import re
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import httpx
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from .auth import CloudBaseTokenVerifier, TokenVerifier
from .config import Settings
from .errors import CloudError
from .models import (
    ChildProfile,
    ChildWrite,
    CurrentReport,
    EmptyBody,
    EmotionRecord,
    Health,
    Paginated,
    QueryRange,
    Readiness,
    Report,
    Session,
    SessionCreate,
    User,
    UserPatch,
)
from .repository import CloudBaseDocumentRepository, CloudRepository
from .security import RateLimiter, SecurityMiddleware, check_user_rate
from .service import ApplicationService


def create_app(
    settings: Settings | None = None,
    repository: CloudRepository | None = None,
    verifier: TokenVerifier | None = None,
) -> FastAPI:
    configuration = settings if settings is not None else Settings.from_environment()
    upstream = httpx.AsyncClient(follow_redirects=False, trust_env=False)
    storage = (
        repository
        if repository is not None
        else CloudBaseDocumentRepository(configuration, upstream)
    )
    authentication = (
        verifier
        if verifier is not None
        else CloudBaseTokenVerifier(configuration, upstream)
    )
    service = ApplicationService(storage)
    limiter = RateLimiter(configuration.rate_window_seconds)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await upstream.aclose()

    app = FastAPI(
        title="SoulCompanion Cloud Metadata API",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityMiddleware, settings=configuration, limiter=limiter)
    app.state.service, app.state.settings = service, configuration

    def error_response(request: Request, status: int, code: str, message: str):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(CloudError)
    async def cloud_error(request, error):
        return error_response(request, error.status, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(
            request, 422, "validation_error", "Request fields are invalid."
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(
            request,
            error.status_code,
            "not_found" if error.status_code == 404 else "request_rejected",
            (
                "Route not found."
                if error.status_code == 404
                else "Request is not supported."
            ),
        )

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return error_response(
            request, 500, "internal_error", "Cloud service is temporarily unavailable."
        )

    async def current_user(request: Request):
        authorization = request.headers.get("authorization", "")
        match = re.fullmatch(
            r"Bearer ([A-Za-z0-9._~+/-]{1,4096}=*)", authorization, re.IGNORECASE
        )
        if match is None:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        principal = await authentication.verify(match.group(1))
        user = await service.resolve_user(principal)
        check_user_rate(limiter, configuration, str(user.id))
        return user

    UserDependency = Annotated[User, Depends(current_user)]
    Limit = Annotated[int, Query(ge=1, le=100)]
    Offset = Annotated[int, Query(ge=0, le=10000)]

    @app.get("/api/v2/healthz", response_model=Health)
    async def health():
        return Health()

    @app.get("/api/v2/readyz", response_model=Readiness)
    async def ready(response: Response):
        healthy = await authentication.ready() and await storage.ready()
        response.status_code = 200 if healthy else 503
        return Readiness(status="healthy" if healthy else "unavailable")

    @app.get("/api/v2/me", response_model=User)
    async def me(user: UserDependency):
        return user

    @app.patch("/api/v2/me", response_model=User)
    async def patch_me(body: UserPatch, user: UserDependency):
        return await service.update_me(user, body)

    @app.get("/api/v2/children", response_model=Paginated[ChildProfile])
    async def children(
        user: UserDependency,
        limit: Limit = 20,
        offset: Offset = 0,
        include_archived: bool = False,
    ):
        return await service.list_records(
            user,
            "children",
            limit=limit,
            offset=offset,
            include_archived=include_archived,
        )

    @app.post("/api/v2/children", response_model=ChildProfile, status_code=201)
    async def post_child(body: ChildWrite, user: UserDependency):
        return await service.create_child(user, body)

    @app.get("/api/v2/children/{child_id}", response_model=ChildProfile)
    async def child(child_id: UUID, user: UserDependency):
        return await service.child(user, child_id)

    @app.patch("/api/v2/children/{child_id}", response_model=ChildProfile)
    async def patch_child(child_id: UUID, body: ChildWrite, user: UserDependency):
        return await service.update_child(user, child_id, body)

    @app.delete("/api/v2/children/{child_id}", status_code=204)
    async def delete_child(child_id: UUID, user: UserDependency):
        await service.archive_child(user, child_id)
        return Response(status_code=204)

    @app.post("/api/v2/sessions", response_model=Session, status_code=201)
    async def post_session(body: SessionCreate, user: UserDependency):
        return await service.create_session(user, body)

    @app.get("/api/v2/sessions/{session_id}", response_model=Session)
    async def session(session_id: UUID, user: UserDependency):
        return await service.session(user, session_id)

    @app.post("/api/v2/sessions/{session_id}/end", response_model=Session)
    async def end_session(
        session_id: UUID, user: UserDependency, body: EmptyBody = EmptyBody()
    ):
        return await service.end_session(user, session_id)

    async def record_query(
        user: UserDependency,
        limit: Limit = 20,
        offset: Offset = 0,
        child_profile_id: UUID | None = None,
        range_start: datetime | None = None,
        range_end: datetime | None = None,
    ):
        try:
            bounds = QueryRange(range_start=range_start, range_end=range_end)
        except ValidationError:
            raise CloudError(
                422, "validation_error", "Time ranges require a UTC offset."
            ) from None
        if (
            bounds.range_start is not None
            and bounds.range_end is not None
            and bounds.range_start > bounds.range_end
        ):
            raise CloudError(422, "validation_error", "Time range is invalid.")
        return {
            "user": user,
            "limit": limit,
            "offset": offset,
            "child_profile_id": child_profile_id,
            "range_start": bounds.range_start,
            "range_end": bounds.range_end,
        }

    @app.get("/api/v2/sessions", response_model=Paginated[Session])
    async def sessions(query: Annotated[dict, Depends(record_query)]):
        return await service.list_records(kind="sessions", **query)

    @app.get("/api/v2/emotions", response_model=Paginated[EmotionRecord])
    async def emotions(query: Annotated[dict, Depends(record_query)]):
        return await service.list_records(kind="emotions", **query)

    @app.get("/api/v2/reports", response_model=Paginated[Report])
    async def reports(query: Annotated[dict, Depends(record_query)]):
        return await service.list_records(kind="reports", **query)

    @app.get("/api/v2/reports/current", response_model=CurrentReport)
    async def report_current(
        user: UserDependency, child_profile_id: UUID | None = None
    ):
        return await service.current_report(user, child_profile_id)

    return app
