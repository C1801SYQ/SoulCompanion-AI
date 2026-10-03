import type {
  AnalyticsView, DashboardSnapshot, HistoryPage, HistoryQuery, ParentReportView,
  PeriodDays, SettingsView, SystemStatus,
} from '../types/contracts';

export interface RequestHandle<T> {
  promise: Promise<T>;
  cancel(): void;
}

export interface CompanionApi {
  getSnapshot(): RequestHandle<DashboardSnapshot>;
  getHistory(query: HistoryQuery): RequestHandle<HistoryPage>;
  getAnalytics(days: PeriodDays): RequestHandle<AnalyticsView>;
  getReport(days: PeriodDays): RequestHandle<ParentReportView>;
  getSettings(): RequestHandle<SettingsView>;
  getSystem(): RequestHandle<SystemStatus>;
  getMarkdown(days: PeriodDays): RequestHandle<string>;
}

export type ConnectionState = 'connecting' | 'online' | 'offline' | 'error';
export type FailureKind = 'offline' | 'error' | 'cancelled';

export class CompanionError extends Error {
  readonly kind: FailureKind;
  readonly requestId?: string;
  readonly retryAfterMs?: number;

  constructor(kind: FailureKind, message: string, details: {
    requestId?: string; retryAfterMs?: number;
  } = {}) {
    super(message);
    this.name = 'CompanionError';
    this.kind = kind;
    this.requestId = details.requestId;
    this.retryAfterMs = details.retryAfterMs;
  }
}
