/** V1 wire fields, with explicit demo provenance for the synthetic adapter. */
export type Mode = 'real' | 'demo';
export type PeriodDays = 1 | 7 | 30;
export type ComponentState = 'healthy' | 'degraded' | 'unavailable' | 'disabled' | 'unknown';

export interface ErrorResponse {
  error: { code: string; message: string; request_id: string };
}

export interface EmotionView {
  category: string;
  confidence: number;
  valence: number;
  arousal: number;
  vision_emotion: string;
  speech_emotion: string;
  environment_signal: string;
  emotional_cause: string;
  attention_level: number;
  timestamp: string;
}

export interface BehaviorView {
  actions: string[];
  speech_rate: number;
  led_color: string;
  led_brightness: number;
  servo_speed: number;
  priority: number;
  reason: string;
}

export interface DashboardSnapshot {
  timestamp: string;
  mode: Mode;
  data_available: boolean;
  emotion: EmotionView | null;
  behavior: BehaviorView | null;
  intervention: {
    intervention_type: string;
    guidance_text: string;
    guidance_style: string;
    parent_alert: boolean;
  };
  risk: {
    status: 'known' | 'unknown';
    has_risk: boolean | null;
    triggers: string[];
    checked_at: string | null;
  };
  bridge: {
    connected: boolean;
    running: boolean;
    cycle_count: number;
    last_update: string | null;
  };
  system: {
    status: 'healthy' | 'degraded' | 'unavailable' | 'unknown';
    checked_at: string | null;
  };
}

export interface RecordView {
  timestamp: string;
  category: string;
  valence: number;
  arousal: number;
  cause: string;
}

export interface HistoryQuery {
  days: PeriodDays;
  limit: number;
  offset: number;
}

export interface HistoryPage extends HistoryQuery {
  mode: Mode;
  total: number;
  has_more: boolean;
  records: RecordView[];
}

export interface TrendView {
  period: string;
  dominant_emotion: string;
  average_valence: number;
  average_arousal: number;
  stability_score: number;
  risk_periods: string[];
  positive_periods: string[];
  total_records: number;
}

export interface AnalyticsView {
  mode: Mode;
  days: PeriodDays;
  trend: TrendView;
  counts: Record<string, number>;
  series: { timestamp: string; valence: number }[];
  patterns: Record<string, number>;
  total_records: number;
}

export interface ParentReportView {
  mode: Mode;
  data_available: boolean;
  period_start: string;
  period_end: string;
  summary: string;
  emotion_trend: TrendView | null;
  highlights: string[];
  concerns: string[];
  suggestions: string[];
  interaction_count: number;
  health_score: number | null;
}

export interface ComponentStatus {
  status: ComponentState;
  reason: string;
  checked_at: string | null;
}

export interface SystemComponents {
  backend: ComponentStatus;
  database: ComponentStatus;
  bridge: ComponentStatus;
  camera: ComponentStatus;
  microphone: ComponentStatus;
  vision_model: ComponentStatus;
  speech_model: ComponentStatus;
  ser_model: ComponentStatus;
  ollama: ComponentStatus;
  hardware: ComponentStatus;
}

export interface SystemStatus {
  status: 'healthy' | 'degraded' | 'unavailable';
  timestamp: string;
  mode: Mode;
  components: SystemComponents;
  reasons: string[];
}

export interface SettingsView {
  mode: Mode;
  local_only: true;
  single_profile: true;
  api_base: string;
  privacy_notice: string;
  storage: {
    status: ComponentState;
    retention_days: number;
    retention_policy: 'manual';
    raw_text_saved: boolean;
  };
  app_env: string;
}
