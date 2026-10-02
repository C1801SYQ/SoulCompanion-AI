"""Small application layer for local dashboard snapshots, history and readiness."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

import config
from core.memory import database_connection
from emotion.intervention import InterventionEngine
from web.contracts import (
    AnalyticsView, BehaviorView, BridgeView, CachedSystem, ComponentStatus,
    DashboardSnapshot, EmotionView, HistoryPage, InterventionView, ParentReportView,
    RecordView, RiskView, SettingsView, StorageSettings, SystemComponents,
    SystemStatus, TrendView, ValencePoint,
)

logger = logging.getLogger("web.product")
SENSOR_COMPONENTS = ("camera", "microphone", "vision_model", "speech_model", "ser_model", "hardware")


class LocalProbeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProductError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ProductService:
    def __init__(
        self, bridge_getter: Callable, runtime_getter: Callable, memory_getter: Callable,
        *, demo_mode: bool | None = None, status_ttl: float = 5.0,
    ):
        self._bridge_getter = bridge_getter
        self._runtime_getter = runtime_getter
        self._memory_getter = memory_getter
        self.demo_mode = config.DEMO_MODE if demo_mode is None else demo_mode
        self._status_ttl = status_ttl
        self._status_lock = threading.Lock()
        self._cached_status: SystemStatus | None = None
        self._status_cached_at = 0.0

    @property
    def mode(self) -> str:
        return "demo" if self.demo_mode else "real"

    def invalidate_status(self) -> None:
        """An attached or stopped runtime must invalidate the cached readiness result."""
        with self._status_lock:
            self._cached_status = None
            self._status_cached_at = 0.0

    def _current_cached_status(self) -> SystemStatus | None:
        cached = self._cached_status
        if cached is not None and time.monotonic() - self._status_cached_at < self._status_ttl:
            return cached
        return None

    def _memory(self):
        if self.demo_mode:
            raise ProductError("DEMO_MODE", "Real history is disabled in explicit demo mode", 409)
        return self._memory_getter()

    @staticmethod
    def _fresh(timestamp: str | None, maximum_age: float = 10.0) -> bool:
        if not timestamp:
            return False
        try:
            age = time.time() - datetime.fromisoformat(timestamp).timestamp()
            return -1.0 <= age <= maximum_age
        except (ValueError, TypeError, OverflowError):
            return False

    def snapshot(self) -> DashboardSnapshot:
        """Read one already-published bridge snapshot; never probe dependencies here."""
        bridge = None if self.demo_mode else self._bridge_getter()
        snap = bridge.get_snapshot() if bridge is not None else None
        bridge_view = BridgeView()
        emotion = None
        behavior = None
        intervention = InterventionView()
        risk = RiskView()
        available = False
        if snap is not None:
            updated = snap.last_update or None
            bridge_view = BridgeView(
                connected=True, running=snap.is_running,
                cycle_count=snap.cycle_count, last_update=updated,
            )
            available = bool(
                getattr(snap, "data_available", False)
                and snap.is_running and self._fresh(updated)
            )
            if available:
                emotion = EmotionView.model_validate(snap.emotion)
                behavior = BehaviorView.model_validate(snap.behavior)
                intervention = InterventionView(
                    intervention_type=snap.intervention_type,
                    guidance_text=snap.guidance_text, guidance_style=snap.guidance_style,
                    parent_alert=snap.parent_alert,
                )
            checked_at = getattr(snap, "risk_checked_at", None) or None
            if snap.is_running and self._fresh(checked_at, maximum_age=15.0):
                risk = RiskView(
                    status="known", has_risk=snap.has_risk,
                    triggers=list(snap.risk_triggers), checked_at=checked_at,
                )
        cached = self._current_cached_status()
        system = CachedSystem(
            status=cached.status, checked_at=cached.timestamp,
        ) if cached is not None else CachedSystem()
        return DashboardSnapshot(
            timestamp=datetime.now().isoformat(), mode=self.mode,
            data_available=available, emotion=emotion, behavior=behavior,
            intervention=intervention, risk=risk, bridge=bridge_view, system=system,
        )

    def history(self, days: int, limit: int, offset: int) -> HistoryPage:
        records, total = self._memory().get_history_page(days, limit, offset)
        return HistoryPage(
            days=days, limit=limit, offset=offset, total=total,
            has_more=offset + len(records) < total,
            records=[RecordView.model_validate(record) for record in records],
        )

    def analytics(self, days: int) -> AnalyticsView:
        memory = self._memory()
        trend = memory.get_trend_analysis(period=f"{days}d", days=days)
        return AnalyticsView(
            days=days, trend=TrendView.model_validate(trend),
            counts=memory.get_emotion_counts(days=days),
            series=[ValencePoint(timestamp=timestamp, valence=valence)
                    for timestamp, valence in memory.get_valence_series(days=days, max_points=500)],
            patterns=memory.detect_periodicity(lookback_days=days),
            total_records=trend.total_records,
        )

    def parent_report(self, days: int) -> ParentReportView:
        report = InterventionEngine(self._memory()).generate_parent_report(days=days)
        return ParentReportView(
            data_available=report.interaction_count > 0,
            period_start=report.period_start, period_end=report.period_end,
            summary=report.summary,
            emotion_trend=TrendView.model_validate(report.emotion_trend) if report.emotion_trend else None,
            highlights=report.highlights, concerns=report.concerns, suggestions=report.suggestions,
            interaction_count=report.interaction_count, health_score=report.health_score,
        )

    def parent_report_markdown(self, days: int) -> str:
        return InterventionEngine(self._memory()).generate_parent_report_markdown(days=days)

    def settings(self) -> SettingsView:
        cached = self._current_cached_status()
        storage_status = "disabled" if self.demo_mode else (
            cached.components.database.status if cached else "unknown"
        )
        return SettingsView(
            mode=self.mode, app_env=config.APP_ENV,
            privacy_notice="Single-child local installation. Raw speech may be stored on this computer. Remote access is unsupported.",
            storage=StorageSettings(
                status=storage_status, retention_days=config.RETENTION_DAYS,
                raw_text_saved=not self.demo_mode,
            ),
        )

    @staticmethod
    def _component(status: str, reason: str, checked_at: str) -> ComponentStatus:
        return ComponentStatus(status=status, reason=reason, checked_at=checked_at)

    def _probe_database(self, checked_at: str) -> ComponentStatus:
        try:
            memory = self._memory()
            with database_connection(memory.db_path) as connection:
                connection.execute("SELECT id FROM emotion_records LIMIT 1").fetchone()
            return self._component("healthy", "Emotion storage is accessible", checked_at)
        except Exception as exc:
            logger.warning("database_probe_failed type=%s", type(exc).__name__)
            return self._component("unavailable", "Emotion storage could not be opened or queried", checked_at)

    def _probe_ollama(self, checked_at: str) -> ComponentStatus:
        try:
            settings = config.Config()
            parsed = urlsplit(settings.OLLAMA_URL)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                return self._component("unavailable", "Ollama URL must be a local HTTP(S) endpoint", checked_at)
            config.validate_bind_host(parsed.hostname)
            tags_url = urlunsplit((parsed.scheme, parsed.netloc, "/api/tags", "", ""))
            # Readiness must not follow environment proxies or perform model inference.
            with build_opener(ProxyHandler({}), LocalProbeRedirectHandler()).open(tags_url, timeout=0.6) as response:
                payload = json.loads(response.read(1024 * 1024))
            models = payload.get("models") if isinstance(payload, dict) else None
            if not isinstance(models, list):
                return self._component("degraded", "Ollama returned an invalid model list", checked_at)
            names = {model.get("name") for model in models if isinstance(model, dict) and isinstance(model.get("name"), str)}
            if settings.OLLAMA_MODEL not in names:
                return self._component("degraded", "Ollama is reachable but the configured model is not installed", checked_at)
            return self._component("healthy", "Ollama and the configured model are available", checked_at)
        except Exception as exc:
            logger.debug("ollama_probe_failed type=%s", type(exc).__name__)
            return self._component("unavailable", "Local Ollama is not reachable", checked_at)

    def _runtime_components(self, checked_at: str) -> dict[str, ComponentStatus]:
        try:
            runtime = self._runtime_getter()
            if runtime is not None and not isinstance(runtime, dict):
                runtime = runtime.get_status() if hasattr(runtime, "get_status") else None
            values = runtime.get("components", runtime) if isinstance(runtime, dict) else {}
            if not isinstance(values, dict):
                values = {}
        except Exception as exc:
            logger.warning("runtime_status_failed type=%s", type(exc).__name__)
            values = {}
        components = {}
        for name in SENSOR_COMPONENTS:
            value = values.get(name)
            if isinstance(value, ComponentStatus):
                components[name] = value
            elif isinstance(value, dict):
                try:
                    components[name] = ComponentStatus.model_validate(value)
                except ValueError:
                    components[name] = self._component("unknown", "Runtime status is not valid", checked_at)
            else:
                components[name] = self._component("unknown", "No device runtime status has been published", checked_at)
        return components

    def system_status(self) -> SystemStatus:
        """Probe only at the low-frequency system endpoint, with a shared 5-second cache."""
        with self._status_lock:
            now = time.monotonic()
            if self._cached_status is not None and now - self._status_cached_at < self._status_ttl:
                return self._cached_status
            checked_at = datetime.now().isoformat()
            components = {"backend": self._component("healthy", "API process is running", checked_at)}
            if self.demo_mode:
                for name in ("database", "bridge", "ollama", *SENSOR_COMPONENTS):
                    components[name] = self._component("disabled", "Disabled in explicit browser demo mode", checked_at)
                status = "healthy"
                reasons = ["Explicit demo mode; no real data is collected"]
            else:
                components["database"] = self._probe_database(checked_at)
                bridge = self._bridge_getter()
                if bridge is None:
                    components["bridge"] = self._component("disabled", "No edge runtime is attached", checked_at)
                else:
                    snap = bridge.get_snapshot()
                    alive = bool(snap.is_running and self._fresh(snap.last_update))
                    components["bridge"] = self._component(
                        "healthy" if alive else "unavailable",
                        "Bridge is publishing fresh snapshots" if alive else "Bridge is stopped or its snapshot is stale",
                        checked_at,
                    )
                components.update(self._runtime_components(checked_at))
                components["ollama"] = self._probe_ollama(checked_at)
                reasons = [f"{name}: {component.reason}" for name, component in components.items()
                           if component.status not in {"healthy", "disabled"}]
                if components["bridge"].status == "disabled":
                    reasons.append("bridge: No edge runtime is attached; live emotion is unavailable")
                status = "unavailable" if components["database"].status == "unavailable" else (
                    "degraded" if reasons else "healthy"
                )
            result = SystemStatus(
                status=status, timestamp=checked_at, mode=self.mode,
                components=SystemComponents(**components), reasons=reasons,
            )
            self._cached_status = result
            self._status_cached_at = time.monotonic()
            return result
