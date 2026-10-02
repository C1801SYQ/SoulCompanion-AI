"""
web/api.py - FastAPI REST API for the Emotion Dashboard

Dual-mode operation:
  1. Standalone: Creates its own module instances (for development)
  2. Bridge mode: Uses injected EmotionBridge (for production via launcher)

Set bridge via: set_bridge(bridge_instance) before starting uvicorn.

Provides endpoints for:
- /api/emotion/current  - Current emotion state
- /api/emotion/history  - Emotion history records
- /api/emotion/trends   - Trend analysis
- /api/behavior/status  - Current behavior status
- /api/behavior/command - Latest behavior command
- /api/parent/report    - Weekly parent report
- /api/parent/report.md - Parent report as Markdown
- /api/bridge/status    - Bridge integration status
- /api/system/status    - System health check
- /api/skill/*          - Skill-driven UI generation
"""
from __future__ import annotations

import sys
import os
from datetime import datetime
from typing import Optional
from functools import wraps
from threading import RLock
from typing import Literal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from config import CORS_ORIGINS, DASHBOARD_HOST, DASHBOARD_PORT, DEMO_MODE
from web.contracts import Liveness, SystemStatus

APP_VERSION = "2.0.0"


def _legacy_mode_boundary(request: Request):
    if DEMO_MODE and request.url.path.startswith("/api/") and not request.url.path.startswith("/api/v1/"):
        from web.service import ProductError
        raise ProductError("DEMO_MODE", "Legacy real-data APIs are disabled in explicit demo mode", 409)

app = FastAPI(
    title="小予情绪智能仪表板",
    description="SoulCompanion AI - ASD儿童多模态情绪智能监控系统",
    version=APP_VERSION,
    dependencies=[Depends(_legacy_mode_boundary)],
)
from web.security import install_security

# ─── CORS ─────────────────────────────────────────────────────────────
# Origins are validated by config; the local boundary applies to every route.
_origins = [o.strip() for o in (CORS_ORIGINS or "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
)
install_security(app)

# ─── Bridge Integration ──────────────────────────────────────────────
# When a bridge is injected, all endpoints read from the bridge's shared state.
# When no bridge, endpoints create standalone module instances.

_bridge = None  # Optional[EmotionBridge]
_runtime = None
_module_lock = RLock()


def set_bridge(bridge):
    """
    Inject an EmotionBridge instance for integrated mode.
    Call this BEFORE starting uvicorn.

    Args:
        bridge: EmotionBridge instance from emotion.bridge
    """
    global _bridge
    _bridge = bridge
    if "product_service" in globals():
        product_service.invalidate_status()


def set_runtime(runtime):
    """Attach the native robot's status provider, without importing heavy models."""
    global _runtime
    _runtime = runtime
    product_service.invalidate_status()


def _serialized_initialization(factory):
    @wraps(factory)
    def get_instance():
        with _module_lock:
            return factory()
    return get_instance


def _has_bridge() -> bool:
    """Check if a bridge is available."""
    return _bridge is not None


# ─── Standalone Module Instances (fallback when no bridge) ────────────

_memory_axis = None
_fusion_engine = None
_behavior_sync = None
_embodied_engine = None
_intervention_engine = None


@_serialized_initialization
def _get_memory_axis():
    global _memory_axis
    if _memory_axis is None:
        from emotion.memory_axis import MemoryAxis
        _memory_axis = MemoryAxis()
    return _memory_axis


@_serialized_initialization
def _get_fusion_engine():
    global _fusion_engine
    if _fusion_engine is None:
        from emotion.fusion_engine import FusionEngine
        _fusion_engine = FusionEngine(memory_axis=_get_memory_axis())
    return _fusion_engine


@_serialized_initialization
def _get_behavior_sync():
    global _behavior_sync
    if _behavior_sync is None:
        from emotion.behavior_sync import BehaviorSync
        _behavior_sync = BehaviorSync()
    return _behavior_sync


@_serialized_initialization
def _get_embodied_engine():
    global _embodied_engine
    if _embodied_engine is None:
        from emotion.embodied_engine import EmbodiedEngine
        _embodied_engine = EmbodiedEngine()
    return _embodied_engine


@_serialized_initialization
def _get_intervention_engine():
    global _intervention_engine
    if _intervention_engine is None:
        from emotion.intervention import InterventionEngine
        _intervention_engine = InterventionEngine(memory_axis=_get_memory_axis())
    return _intervention_engine


# ─── Helper: get modules from bridge or standalone ───────────────────

def _memory():
    if DEMO_MODE:
        from web.service import ProductError
        raise ProductError("DEMO_MODE", "Real history is disabled in explicit demo mode", 409)
    return _bridge.get_memory() if _has_bridge() else _get_memory_axis()

def _fusion():
    return _bridge.get_fusion_engine() if _has_bridge() else _get_fusion_engine()

def _behavior():
    return _bridge.get_behavior_sync() if _has_bridge() else _get_behavior_sync()

def _embodied():
    return _bridge.get_embodied_engine() if _has_bridge() else _get_embodied_engine()

def _intervention():
    return _bridge.get_intervention_engine() if _has_bridge() else _get_intervention_engine()


from web.product import install_product_api
from web.service import ProductService

product_service = ProductService(
    bridge_getter=lambda: _bridge, runtime_getter=lambda: _runtime, memory_getter=_memory,
)
install_product_api(app, product_service)


# ─── Static Files & Templates ─────────────────────────────────────────

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir) if os.path.exists(templates_dir) else None


# ─── Dashboard Page ───────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Serve the main dashboard page."""
    if templates:
        return templates.TemplateResponse(request, "dashboard.html", {"system_mode": "demo" if DEMO_MODE else "real"})
    return HTMLResponse("<h1>小予情绪智能仪表板</h1><p>Templates not found. Use /docs for API.</p>")


# ─── Emotion API ──────────────────────────────────────────────────────

@app.get("/api/emotion/current")
def get_current_emotion():
    """Get the current fused emotion state."""
    if _has_bridge():
        snap = _bridge.get_snapshot()
        state = snap.emotion
    else:
        state = _fusion().get_last_state()

    return {
        "category": state.category.value if hasattr(state.category, 'value') else str(state.category),
        "confidence": state.confidence,
        "valence": state.valence,
        "arousal": state.arousal,
        "vision_emotion": state.vision_emotion,
        "speech_emotion": state.speech_emotion,
        "environment_signal": state.environment_signal,
        "emotional_cause": state.emotional_cause,
        "attention_level": state.attention_level,
        "timestamp": state.timestamp,
    }


@app.get("/api/emotion/history")
def get_emotion_history(limit: int = Query(50, ge=1, le=500),
                              offset: int = Query(0, ge=0, le=1000000)):
    """Get emotion history records."""
    records = _memory().get_records(limit=limit, offset=offset)
    return {
        "records": [
            {
                "timestamp": r.timestamp,
                "category": r.category,
                "valence": r.valence,
                "arousal": r.arousal,
                "cause": r.cause,
                "context": r.context,
                "source_text": r.source_text,
            }
            for r in records
        ],
        "count": len(records),
    }


@app.get("/api/emotion/trends")
def get_emotion_trends(period: Literal["hourly", "daily", "weekly"] = "daily"):
    """Get emotion trend analysis."""
    trend = _memory().get_trend_analysis(period=period)
    return {
        "period": trend.period,
        "dominant_emotion": trend.dominant_emotion,
        "average_valence": trend.average_valence,
        "average_arousal": trend.average_arousal,
        "stability_score": trend.stability_score,
        "risk_periods": trend.risk_periods,
        "positive_periods": trend.positive_periods,
        "total_records": trend.total_records,
    }


@app.get("/api/emotion/periodicity")
def get_emotion_periodicity(lookback_days: int = Query(30, ge=1, le=365)):
    """Get emotion periodicity patterns."""
    patterns = _memory().detect_periodicity(lookback_days=lookback_days)
    return {"patterns": patterns, "lookback_days": lookback_days}


@app.get("/api/emotion/counts")
def get_emotion_counts(days: int = Query(7, ge=1, le=365)):
    """Get emotion category counts."""
    counts = _memory().get_emotion_counts(days=days)
    return {"counts": counts, "days": days}


@app.get("/api/emotion/valence-series")
def get_valence_series(days: int = Query(7, ge=1, le=365)):
    """Get timestamped valence series for charting."""
    series = _memory().get_valence_series(days=days)
    return {
        "series": [{"timestamp": ts, "valence": v} for ts, v in series],
        "days": days,
    }


# ─── Behavior API ─────────────────────────────────────────────────────

@app.get("/api/behavior/status")
def get_behavior_status():
    """Get current behavior engine status."""
    # 无论是否接入桥接器，行为引擎实例都从 _embodied() 取（桥接模式下
    # 它会返回桥接器内部的那一份），因此无需分支。
    return _embodied().get_status()


@app.get("/api/behavior/command")
def get_behavior_command():
    """Get the latest behavior command."""
    if _has_bridge():
        snap = _bridge.get_snapshot()
        cmd = snap.behavior
    else:
        cmd = _behavior().get_last_command()

    return {
        "actions": [a.value for a in cmd.actions],
        "speech_rate": cmd.speech_rate,
        "led_color": cmd.led_color,
        "led_brightness": cmd.led_brightness,
        "servo_speed": cmd.servo_speed,
        "priority": cmd.priority,
        "reason": cmd.reason,
    }


# ─── Parent Report API ───────────────────────────────────────────────

@app.get("/api/parent/report")
def get_parent_report(days: int = Query(7, ge=1, le=365)):
    """Get parent report as JSON."""
    report = _intervention().generate_parent_report(days=days)
    return {
        "period_start": report.period_start,
        "period_end": report.period_end,
        "summary": report.summary,
        "emotion_trend": {
            "period": report.emotion_trend.period if report.emotion_trend else "weekly",
            "dominant_emotion": report.emotion_trend.dominant_emotion if report.emotion_trend else "neutral",
            "average_valence": report.emotion_trend.average_valence if report.emotion_trend else 0.0,
            "stability_score": report.emotion_trend.stability_score if report.emotion_trend else 0.0,
        } if report.emotion_trend else None,
        "highlights": report.highlights,
        "concerns": report.concerns,
        "suggestions": report.suggestions,
        "interaction_count": report.interaction_count,
        "health_score": report.health_score,
    }


@app.get("/api/parent/report.md", response_class=PlainTextResponse)
def get_parent_report_markdown(days: int = Query(7, ge=1, le=365)):
    """Get parent report as Markdown."""
    return _intervention().generate_parent_report_markdown(days=days)


# ─── Intervention API ────────────────────────────────────────────────

@app.get("/api/intervention/last")
def get_last_intervention():
    """Get the last intervention plan."""
    if _has_bridge():
        snap = _bridge.get_snapshot()
        return {
            "intervention_type": snap.intervention_type,
            "guidance_text": snap.guidance_text,
            "guidance_style": snap.guidance_style,
            "parent_alert": snap.parent_alert,
            "parent_note": "",
            "duration_seconds": 0,
            "metadata": {},
        }

    plan = _intervention().get_last_plan()
    return {
        "intervention_type": plan.intervention_type.value if hasattr(plan.intervention_type, 'value') else str(plan.intervention_type),
        "guidance_text": plan.guidance_text,
        "guidance_style": plan.guidance_style,
        "parent_alert": plan.parent_alert,
        "parent_note": plan.parent_note,
        "duration_seconds": plan.duration_seconds,
        "metadata": plan.metadata,
    }


# ─── Risk Detection API ──────────────────────────────────────────────

@app.get("/api/risk/triggers")
def get_risk_triggers(window_minutes: int = Query(60, ge=1, le=525600)):
    """Get current risk triggers."""
    if _has_bridge():
        snap = _bridge.get_snapshot()
        return {
            "triggers": snap.risk_triggers,
            "has_risk": snap.has_risk,
            "window_minutes": window_minutes,
        }

    triggers = _memory().check_risk_triggers(window_minutes=window_minutes)
    return {
        "triggers": triggers,
        "has_risk": len(triggers) > 0,
        "window_minutes": window_minutes,
    }


# ─── Bridge Status API ───────────────────────────────────────────────

@app.get("/api/bridge/status")
def get_bridge_status():
    """Get the emotion bridge integration status."""
    if _has_bridge():
        snap = _bridge.get_snapshot()
        return {
            "connected": True,
            "is_running": snap.is_running,
            "cycle_count": snap.cycle_count,
            "last_update": snap.last_update,
            "attention_level": snap.attention_level,
        }
    return {
        "connected": False,
        "is_running": False,
        "cycle_count": 0,
        "last_update": "",
        "attention_level": 0.0,
    }


# ─── System Status API ───────────────────────────────────────────────

@app.get("/healthz", response_model=Liveness)
def healthz():
    """Process liveness only; does not initialize models, hardware, or storage."""
    return {"status": "ok", "version": APP_VERSION}


@app.get("/readyz", response_model=SystemStatus, responses={503: {"model": SystemStatus}})
def readyz(response: Response):
    status = product_service.system_status()
    if status.status == "unavailable":
        response.status_code = 503
    return status


@app.get("/api/system/status", response_model=SystemStatus, deprecated=True)
def get_system_status():
    """Get overall system health status."""
    return product_service.system_status()


# ─── Skill-driven UI Generation ──────────────────────────────────────

@app.get("/api/skill/emotion-panel")
def skill_emotion_panel():
    """Generate Emotion Live Panel configuration for skill-driven UI."""
    return {
        "panel": "emotion_live",
        "title": "实时情绪状态",
        "components": [
            {"type": "emotion_badge", "source": "/api/emotion/current", "refresh_ms": 500},
            {"type": "confidence_bar", "source": "/api/emotion/current", "field": "confidence"},
            {"type": "cause_text", "source": "/api/emotion/current", "field": "emotional_cause"},
            {"type": "source_tags", "fields": ["vision_emotion", "speech_emotion", "environment_signal"]},
        ],
        "layout": "card",
        "color_scheme": "emotion_adaptive",
    }


@app.get("/api/skill/emotion-timeline")
def skill_emotion_timeline():
    """Generate Emotion Timeline configuration for skill-driven UI."""
    return {
        "panel": "emotion_timeline",
        "title": "情绪趋势",
        "components": [
            {"type": "line_chart", "source": "/api/emotion/valence-series", "x": "timestamp", "y": "valence"},
            {"type": "emotion_pie", "source": "/api/emotion/counts"},
            {"type": "periodicity_map", "source": "/api/emotion/periodicity"},
        ],
        "layout": "card",
        "time_ranges": ["1d", "7d", "30d"],
    }


@app.get("/api/skill/behavior-monitor")
def skill_behavior_monitor():
    """Generate Behavior Monitor configuration for skill-driven UI."""
    return {
        "panel": "behavior_monitor",
        "title": "行为同步状态",
        "components": [
            {"type": "action_list", "source": "/api/behavior/command", "field": "actions"},
            {"type": "led_indicator", "source": "/api/behavior/command", "fields": ["led_color", "led_brightness"]},
            {"type": "speed_gauge", "source": "/api/behavior/command", "fields": ["speech_rate", "servo_speed"]},
            {"type": "status_dot", "source": "/api/behavior/status"},
        ],
        "layout": "card",
    }


@app.get("/api/skill/parent-insight")
def skill_parent_insight():
    """Generate Parent Insight Panel configuration for skill-driven UI."""
    return {
        "panel": "parent_insight",
        "title": "家长洞察",
        "components": [
            {"type": "health_score", "source": "/api/parent/report", "field": "health_score", "max": 100},
            {"type": "summary_text", "source": "/api/parent/report", "field": "summary"},
            {"type": "highlight_list", "source": "/api/parent/report", "field": "highlights"},
            {"type": "concern_list", "source": "/api/parent/report", "field": "concerns"},
            {"type": "suggestion_list", "source": "/api/parent/report", "field": "suggestions"},
            {"type": "risk_alert", "source": "/api/risk/triggers"},
        ],
        "layout": "card",
    }


@app.get("/api/skill/dashboard-layout")
def skill_dashboard_layout():
    """Get the full dashboard layout configuration."""
    return {
        "dashboard": "soulcompanion_emotion",
        "version": "1.0.0",
        "grid": {
            "columns": 12,
            "rows": "auto",
            "gap": 16,
        },
        "panels": [
            {"skill": "/api/skill/emotion-panel", "col_span": 6, "row_span": 1, "position": "top-left"},
            {"skill": "/api/skill/behavior-monitor", "col_span": 6, "row_span": 1, "position": "top-right"},
            {"skill": "/api/skill/emotion-timeline", "col_span": 8, "row_span": 2, "position": "middle-left"},
            {"skill": "/api/skill/parent-insight", "col_span": 4, "row_span": 2, "position": "middle-right"},
        ],
        "theme": {
            "primary": "#4CAF50",
            "secondary": "#2196F3",
            "background": "#f5f7fa",
            "surface": "#ffffff",
            "text": "#333333",
        },
    }


if __name__ == "__main__":
    import uvicorn

    # 默认只绑定本机：看板上是儿童的情绪数据，不应默认暴露到局域网。
    # 本交付版本只允许本机操作，不提供远程入口。
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT, proxy_headers=False)
