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

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

app = FastAPI(
    title="小予情绪智能仪表板",
    description="SoulCompanion AI - ASD儿童多模态情绪智能监控系统",
    version="1.0.0",
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Bridge Integration ──────────────────────────────────────────────
# When a bridge is injected, all endpoints read from the bridge's shared state.
# When no bridge, endpoints create standalone module instances.

_bridge = None  # Optional[EmotionBridge]


def set_bridge(bridge):
    """
    Inject an EmotionBridge instance for integrated mode.
    Call this BEFORE starting uvicorn.

    Args:
        bridge: EmotionBridge instance from emotion.bridge
    """
    global _bridge
    _bridge = bridge


def _has_bridge() -> bool:
    """Check if a bridge is available."""
    return _bridge is not None


# ─── Standalone Module Instances (fallback when no bridge) ────────────

_memory_axis = None
_fusion_engine = None
_behavior_sync = None
_embodied_engine = None
_intervention_engine = None


def _get_memory_axis():
    global _memory_axis
    if _memory_axis is None:
        from emotion.memory_axis import MemoryAxis
        _memory_axis = MemoryAxis()
    return _memory_axis


def _get_fusion_engine():
    global _fusion_engine
    if _fusion_engine is None:
        from emotion.fusion_engine import FusionEngine
        _fusion_engine = FusionEngine(memory_axis=_get_memory_axis())
    return _fusion_engine


def _get_behavior_sync():
    global _behavior_sync
    if _behavior_sync is None:
        from emotion.behavior_sync import BehaviorSync
        _behavior_sync = BehaviorSync()
    return _behavior_sync


def _get_embodied_engine():
    global _embodied_engine
    if _embodied_engine is None:
        from emotion.embodied_engine import EmbodiedEngine
        _embodied_engine = EmbodiedEngine()
    return _embodied_engine


def _get_intervention_engine():
    global _intervention_engine
    if _intervention_engine is None:
        from emotion.intervention import InterventionEngine
        _intervention_engine = InterventionEngine(memory_axis=_get_memory_axis())
    return _intervention_engine


# ─── Helper: get modules from bridge or standalone ───────────────────

def _memory():
    return _bridge.get_memory() if _has_bridge() else _get_memory_axis()

def _fusion():
    return _bridge.get_fusion_engine() if _has_bridge() else _get_fusion_engine()

def _behavior():
    return _bridge.get_behavior_sync() if _has_bridge() else _get_behavior_sync()

def _embodied():
    return _bridge.get_embodied_engine() if _has_bridge() else _get_embodied_engine()

def _intervention():
    return _bridge.get_intervention_engine() if _has_bridge() else _get_intervention_engine()


# ─── Static Files & Templates ─────────────────────────────────────────

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir) if os.path.exists(templates_dir) else None


# ─── Dashboard Page ───────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the main dashboard page."""
    if templates:
        return templates.TemplateResponse(request, "dashboard.html")
    return HTMLResponse("<h1>小予情绪智能仪表板</h1><p>Templates not found. Use /docs for API.</p>")


# ─── Emotion API ──────────────────────────────────────────────────────

@app.get("/api/emotion/current")
async def get_current_emotion():
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
async def get_emotion_history(limit: int = 50, offset: int = 0):
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
async def get_emotion_trends(period: str = "daily"):
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
async def get_emotion_periodicity(lookback_days: int = 30):
    """Get emotion periodicity patterns."""
    patterns = _memory().detect_periodicity(lookback_days=lookback_days)
    return {"patterns": patterns, "lookback_days": lookback_days}


@app.get("/api/emotion/counts")
async def get_emotion_counts(days: int = 7):
    """Get emotion category counts."""
    counts = _memory().get_emotion_counts(days=days)
    return {"counts": counts, "days": days}


@app.get("/api/emotion/valence-series")
async def get_valence_series(days: int = 7):
    """Get timestamped valence series for charting."""
    series = _memory().get_valence_series(days=days)
    return {
        "series": [{"timestamp": ts, "valence": v} for ts, v in series],
        "days": days,
    }


# ─── Behavior API ─────────────────────────────────────────────────────

@app.get("/api/behavior/status")
async def get_behavior_status():
    """Get current behavior engine status."""
    if _has_bridge():
        return _embodied().get_status()
    return _embodied().get_status()


@app.get("/api/behavior/command")
async def get_behavior_command():
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
async def get_parent_report(days: int = 7):
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
async def get_parent_report_markdown(days: int = 7):
    """Get parent report as Markdown."""
    return _intervention().generate_parent_report_markdown(days=days)


# ─── Intervention API ────────────────────────────────────────────────

@app.get("/api/intervention/last")
async def get_last_intervention():
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
async def get_risk_triggers(window_minutes: int = 60):
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
async def get_bridge_status():
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

@app.get("/api/system/status")
async def get_system_status():
    """Get overall system health status."""
    bridge_connected = _has_bridge()
    bridge_running = _bridge.is_running if bridge_connected else False

    return {
        "status": "running" if (bridge_connected and bridge_running) else "standalone",
        "timestamp": datetime.now().isoformat(),
        "bridge": {
            "connected": bridge_connected,
            "running": bridge_running,
        },
        "modules": {
            "fusion_engine": True,
            "memory_axis": True,
            "behavior_sync": True,
            "embodied_engine": True,
            "intervention_engine": True,
        },
        "version": "1.0.0",
    }


# ─── Skill-driven UI Generation ──────────────────────────────────────

@app.get("/api/skill/emotion-panel")
async def skill_emotion_panel():
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
async def skill_emotion_timeline():
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
async def skill_behavior_monitor():
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
async def skill_parent_insight():
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
async def skill_dashboard_layout():
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
