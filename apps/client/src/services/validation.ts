import type {
  AnalyticsView, DashboardSnapshot, HistoryPage, HistoryQuery, ParentReportView,
  PeriodDays, SettingsView, SystemStatus,
} from '../types/contracts';
import { CompanionError } from './types';

type ObjectValue = Record<string, unknown>;
const object = (value: unknown): value is ObjectValue =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string';
const bool = (value: unknown): value is boolean => typeof value === 'boolean';
const number = (value: unknown, min = -Infinity, max = Infinity): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max;
const integer = (value: unknown, min = 0, max = Infinity): value is number =>
  number(value, min, max) && Number.isInteger(value);
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const oneOf = (value: unknown, values: readonly string[]) => text(value) && values.includes(value);
const timestamp = (value: unknown) => text(value)
  && Number.isFinite(Date.parse(value.replace(/(\.\d{3})\d+/, '$1')));
const optionalTime = (value: unknown) => value === null || timestamp(value);
const componentStates = ['healthy', 'degraded', 'unavailable', 'disabled', 'unknown'];
export const componentNames = [
  'backend', 'database', 'bridge', 'camera', 'microphone', 'vision_model',
  'speech_model', 'ser_model', 'ollama', 'hardware',
] as const;

function requireContract(condition: unknown): asserts condition {
  if (!condition) throw new CompanionError('error', '后端返回的数据格式不符合产品接口，请重试。');
}

function realObject(value: unknown): ObjectValue {
  requireContract(object(value) && value.mode === 'real');
  return value;
}

function emotion(value: unknown): void {
  requireContract(object(value));
  requireContract(text(value.category) && number(value.confidence, 0, 1)
    && number(value.valence, -1, 1) && number(value.arousal, 0, 1)
    && number(value.attention_level, 0, 1) && timestamp(value.timestamp));
  ['vision_emotion', 'speech_emotion', 'environment_signal', 'emotional_cause']
    .forEach(key => requireContract(text(value[key])));
}

function behavior(value: unknown): void {
  requireContract(object(value));
  requireContract(texts(value.actions) && number(value.speech_rate)
    && text(value.led_color) && number(value.led_brightness, 0, 1)
    && number(value.servo_speed, 0, 1) && integer(value.priority, -Infinity)
    && text(value.reason));
}

function trend(value: unknown): void {
  requireContract(object(value));
  requireContract(text(value.period) && text(value.dominant_emotion)
    && number(value.average_valence, -1, 1) && number(value.average_arousal, 0, 1)
    && number(value.stability_score, 0, 1) && texts(value.risk_periods)
    && texts(value.positive_periods) && integer(value.total_records));
}

function record(value: unknown): void {
  requireContract(object(value) && timestamp(value.timestamp) && text(value.category)
    && text(value.cause) && number(value.valence, -1, 1) && number(value.arousal, 0, 1));
}

export function validatePeriod(days: number): asserts days is PeriodDays {
  if (days !== 1 && days !== 7 && days !== 30) {
    throw new CompanionError('error', '请选择 1、7 或 30 天的时间范围。');
  }
}

export function validateHistoryQuery(query: HistoryQuery): void {
  validatePeriod(query.days);
  if (!integer(query.limit, 1, 500) || !integer(query.offset, 0, 1_000_000)) {
    throw new CompanionError('error', '历史记录分页参数无效。');
  }
}

export function validateSnapshot(value: unknown): DashboardSnapshot {
  const data = realObject(value);
  requireContract(timestamp(data.timestamp) && bool(data.data_available));
  if (data.emotion !== null) emotion(data.emotion);
  if (data.behavior !== null) behavior(data.behavior);
  requireContract(!data.data_available || data.emotion !== null);
  requireContract(object(data.intervention) && text(data.intervention.intervention_type)
    && text(data.intervention.guidance_text) && text(data.intervention.guidance_style)
    && bool(data.intervention.parent_alert));
  requireContract(object(data.risk) && oneOf(data.risk.status, ['known', 'unknown'])
    && texts(data.risk.triggers) && optionalTime(data.risk.checked_at));
  requireContract(data.risk.status === 'known'
    ? bool(data.risk.has_risk) && timestamp(data.risk.checked_at)
    : data.risk.has_risk === null);
  requireContract(object(data.bridge) && bool(data.bridge.connected) && bool(data.bridge.running)
    && integer(data.bridge.cycle_count) && optionalTime(data.bridge.last_update));
  requireContract(object(data.system)
    && oneOf(data.system.status, ['healthy', 'degraded', 'unavailable', 'unknown'])
    && optionalTime(data.system.checked_at));
  return data as unknown as DashboardSnapshot;
}

export function validateHistory(value: unknown, query: HistoryQuery): HistoryPage {
  const data = realObject(value);
  requireContract(data.days === query.days && data.limit === query.limit
    && data.offset === query.offset && integer(data.total) && bool(data.has_more)
    && Array.isArray(data.records) && data.records.length <= query.limit);
  data.records.forEach(record);
  requireContract(data.has_more === (query.offset + data.records.length < data.total));
  return data as unknown as HistoryPage;
}

export function validateAnalytics(value: unknown, days: PeriodDays): AnalyticsView {
  const data = realObject(value);
  requireContract(data.days === days && integer(data.total_records)
    && object(data.counts) && object(data.patterns)
    && Array.isArray(data.series) && data.series.length <= 500);
  trend(data.trend);
  requireContract(object(data.trend) && data.trend.total_records === data.total_records
    && data.trend.period === `${days}d`);
  Object.values(data.counts).forEach(count => requireContract(integer(count)));
  Object.values(data.patterns).forEach(pattern => requireContract(number(pattern)));
  data.series.forEach(point => requireContract(object(point)
    && timestamp(point.timestamp) && number(point.valence, -1, 1)));
  return data as unknown as AnalyticsView;
}

export function validateReport(value: unknown): ParentReportView {
  const data = realObject(value);
  requireContract(bool(data.data_available) && timestamp(data.period_start)
    && timestamp(data.period_end) && text(data.summary) && texts(data.highlights)
    && texts(data.concerns) && texts(data.suggestions) && integer(data.interaction_count)
    && (data.health_score === null || number(data.health_score, 0, 100)));
  if (data.emotion_trend !== null) trend(data.emotion_trend);
  requireContract(data.data_available || data.health_score === null);
  requireContract(data.data_available === (data.interaction_count > 0));
  return data as unknown as ParentReportView;
}

export function validateSystem(value: unknown): SystemStatus {
  const data = realObject(value);
  requireContract(oneOf(data.status, ['healthy', 'degraded', 'unavailable'])
    && timestamp(data.timestamp) && object(data.components) && texts(data.reasons));
  const components = data.components;
  componentNames.forEach(name => {
    const component = components[name];
    requireContract(object(component) && oneOf(component.status, componentStates)
      && text(component.reason) && optionalTime(component.checked_at));
  });
  return data as unknown as SystemStatus;
}

export function validateSettings(value: unknown): SettingsView {
  const data = realObject(value);
  requireContract(data.local_only === true && data.single_profile === true
    && text(data.api_base) && text(data.privacy_notice) && text(data.app_env)
    && object(data.storage) && oneOf(data.storage.status, componentStates)
    && integer(data.storage.retention_days) && data.storage.retention_policy === 'manual'
    && bool(data.storage.raw_text_saved));
  return data as unknown as SettingsView;
}
