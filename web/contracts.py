"""Versioned product contracts; domain dataclasses remain independent of the web layer."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["real", "demo"]
ComponentState = Literal["healthy", "degraded", "unavailable", "disabled", "unknown"]


class Contract(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", allow_inf_nan=False)


class ErrorDetail(Contract):
    code: str
    message: str
    request_id: str


class ErrorResponse(Contract):
    error: ErrorDetail


class Liveness(Contract):
    status: Literal["ok"] = "ok"
    version: str


class EmotionView(Contract):
    category: str
    confidence: float = Field(ge=0, le=1)
    valence: float = Field(ge=-1, le=1)
    arousal: float = Field(ge=0, le=1)
    vision_emotion: str
    speech_emotion: str
    environment_signal: str
    emotional_cause: str
    attention_level: float = Field(ge=0, le=1)
    timestamp: str


class BehaviorView(Contract):
    actions: list[str]
    speech_rate: float
    led_color: str
    led_brightness: float = Field(ge=0, le=1)
    servo_speed: float = Field(ge=0, le=1)
    priority: int
    reason: str


class InterventionView(Contract):
    intervention_type: str = "none"
    guidance_text: str = ""
    guidance_style: str = "gentle"
    parent_alert: bool = False


class RiskView(Contract):
    status: Literal["known", "unknown"] = "unknown"
    has_risk: bool | None = None
    triggers: list[str] = Field(default_factory=list)
    checked_at: str | None = None


class BridgeView(Contract):
    connected: bool = False
    running: bool = False
    cycle_count: int = 0
    last_update: str | None = None


class CachedSystem(Contract):
    status: Literal["healthy", "degraded", "unavailable", "unknown"] = "unknown"
    checked_at: str | None = None


class DashboardSnapshot(Contract):
    timestamp: str
    mode: Mode
    data_available: bool
    emotion: EmotionView | None = None
    behavior: BehaviorView | None = None
    intervention: InterventionView = Field(default_factory=InterventionView)
    risk: RiskView = Field(default_factory=RiskView)
    bridge: BridgeView = Field(default_factory=BridgeView)
    system: CachedSystem = Field(default_factory=CachedSystem)


class RecordView(Contract):
    timestamp: str
    category: str
    valence: float = Field(ge=-1, le=1)
    arousal: float = Field(ge=0, le=1)
    cause: str


class HistoryPage(Contract):
    mode: Literal["real"] = "real"
    days: int
    limit: int
    offset: int
    total: int
    has_more: bool
    records: list[RecordView]


class TrendView(Contract):
    period: str
    dominant_emotion: str
    average_valence: float = Field(ge=-1, le=1)
    average_arousal: float = Field(ge=0, le=1)
    stability_score: float = Field(ge=0, le=1)
    risk_periods: list[str]
    positive_periods: list[str]
    total_records: int


class ValencePoint(Contract):
    timestamp: str
    valence: float = Field(ge=-1, le=1)


class AnalyticsView(Contract):
    mode: Literal["real"] = "real"
    days: int
    trend: TrendView
    counts: dict[str, int]
    series: list[ValencePoint]
    patterns: dict[str, float]
    total_records: int


class ParentReportView(Contract):
    mode: Literal["real"] = "real"
    data_available: bool
    period_start: str
    period_end: str
    summary: str
    emotion_trend: TrendView | None
    highlights: list[str]
    concerns: list[str]
    suggestions: list[str]
    interaction_count: int
    health_score: float | None = Field(ge=0, le=100)


class ComponentStatus(Contract):
    status: ComponentState
    reason: str
    checked_at: str | None = None


class SystemComponents(Contract):
    backend: ComponentStatus
    database: ComponentStatus
    bridge: ComponentStatus
    camera: ComponentStatus
    microphone: ComponentStatus
    vision_model: ComponentStatus
    speech_model: ComponentStatus
    ser_model: ComponentStatus
    ollama: ComponentStatus
    hardware: ComponentStatus


class SystemStatus(Contract):
    status: Literal["healthy", "degraded", "unavailable"]
    timestamp: str
    mode: Mode
    components: SystemComponents
    reasons: list[str]


class StorageSettings(Contract):
    status: ComponentState
    retention_days: int
    retention_policy: Literal["manual"] = "manual"
    raw_text_saved: bool


class SettingsView(Contract):
    mode: Mode
    local_only: Literal[True] = True
    single_profile: Literal[True] = True
    api_base: str = "/api/v1"
    privacy_notice: str
    storage: StorageSettings
    app_env: str
