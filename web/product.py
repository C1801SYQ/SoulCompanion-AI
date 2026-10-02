"""Versioned local-product routes; handlers use the thread pool for storage work."""
import logging
import sqlite3
from enum import IntEnum

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from web.contracts import (
    AnalyticsView, DashboardSnapshot, ErrorDetail, ErrorResponse, HistoryPage,
    ParentReportView, SettingsView, SystemStatus,
)
from web.service import ProductError, ProductService

logger = logging.getLogger("web.product")


class PeriodDays(IntEnum):
    DAY = 1
    WEEK = 7
    MONTH = 30


ERROR_RESPONSES = {
    status: {"model": ErrorResponse}
    for status in (403, 409, 422, 429, 500, 503)
}


def create_product_router(service: ProductService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)

    @router.get("/dashboard/snapshot", response_model=DashboardSnapshot, tags=["dashboard"])
    def snapshot():
        return service.snapshot()

    @router.get("/emotions/history", response_model=HistoryPage, tags=["emotions"])
    def history(
        days: PeriodDays = PeriodDays.WEEK,
        limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0, le=1000000),
    ):
        return service.history(days.value, limit, offset)

    @router.get("/emotions/analytics", response_model=AnalyticsView, tags=["emotions"])
    def analytics(days: PeriodDays = PeriodDays.WEEK):
        return service.analytics(days.value)

    @router.get("/reports/parent", response_model=ParentReportView, tags=["reports"])
    def parent_report(days: PeriodDays = PeriodDays.WEEK):
        return service.parent_report(days.value)

    @router.get("/reports/parent.md", response_class=Response, tags=["reports"],
                responses={200: {"content": {"text/markdown": {"schema": {"type": "string"}}}}})
    def parent_report_markdown(days: PeriodDays = PeriodDays.WEEK):
        return PlainTextResponse(
            service.parent_report_markdown(days.value), media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="parent-report.md"'},
        )

    @router.get("/system/status", response_model=SystemStatus, tags=["system"])
    def system_status():
        return service.system_status()

    @router.get("/system/readiness", response_model=SystemStatus, tags=["system"],
                responses={503: {"model": SystemStatus}})
    def readiness(response: Response):
        status = service.system_status()
        if status.status == "unavailable":
            response.status_code = 503
        return status

    @router.get("/system/settings", response_model=SettingsView, tags=["system"])
    def settings():
        return service.settings()

    return router


def install_product_api(app: FastAPI, service: ProductService) -> None:
    app.include_router(create_product_router(service))

    @app.exception_handler(ProductError)
    async def product_error(request: Request, exc: ProductError):
        body = ErrorResponse(error=ErrorDetail(
            code=exc.code, message=exc.message, request_id=request.state.request_id,
        ))
        return JSONResponse(body.model_dump(), status_code=exc.status_code)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request: Request, exc: sqlite3.Error):
        logger.warning("storage_error request_id=%s type=%s", request.state.request_id, type(exc).__name__)
        body = ErrorResponse(error=ErrorDetail(
            code="STORAGE_UNAVAILABLE", message="Emotion storage is unavailable",
            request_id=request.state.request_id,
        ))
        return JSONResponse(body.model_dump(), status_code=503)
