import type {
  AnalyticsView, DashboardSnapshot, HistoryPage, HistoryQuery, ParentReportView,
  PeriodDays, RecordView, SettingsView, SystemComponents, SystemStatus, TrendView,
} from '../types/contracts';
import { CompanionError, type CompanionApi, type RequestHandle } from './types';
import { componentNames, validateHistoryQuery, validatePeriod } from './validation';

/** Synthetic fixtures use explicit demo provenance and perform no HTTP or media work. */
function result<T>(build: () => T): RequestHandle<T> {
  let cancelled = false;
  return {
    promise: Promise.resolve().then(() => {
      if (cancelled) throw new CompanionError('cancelled', '请求已取消。');
      return build();
    }),
    cancel: () => { cancelled = true; },
  };
}

const samples = [
  { category: 'calm', valence: 0.36, arousal: 0.22 },
  { category: 'happy', valence: 0.74, arousal: 0.62 },
  { category: 'neutral', valence: 0.08, arousal: 0.31 },
  { category: 'anxious', valence: -0.32, arousal: 0.68 },
  { category: 'calm', valence: 0.29, arousal: 0.25 },
] as const;

function records(days: PeriodDays, now: number): RecordView[] {
  const data: RecordView[] = [];
  for (let index = 0; index < days * 4; index += 1) {
    const sample = samples[(index * 3 + 2) % samples.length];
    data.push({
      ...sample,
      timestamp: new Date(now - (index + 1) * 6 * 60 * 60 * 1_000).toISOString(),
      cause: '合成演示记录，不代表任何真实用户。',
    });
  }
  return data;
}

function analytics(days: PeriodDays, now: number): AnalyticsView {
  const data = records(days, now);
  const counts: Record<string, number> = {};
  data.forEach(item => { counts[item.category] = (counts[item.category] ?? 0) + 1; });
  const dominant = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
  const trend: TrendView = {
    period: `${days}d`, dominant_emotion: dominant,
    average_valence: data.reduce((sum, item) => sum + item.valence, 0) / data.length,
    average_arousal: data.reduce((sum, item) => sum + item.arousal, 0) / data.length,
    stability_score: 0.72, risk_periods: [], positive_periods: [], total_records: data.length,
  };
  return {
    mode: 'demo', days, trend, counts, patterns: {}, total_records: data.length,
    series: [...data].reverse().map(({ timestamp, valence }) => ({ timestamp, valence })),
  };
}

function report(days: PeriodDays, now: number): ParentReportView {
  const summary = analytics(days, now);
  return {
    mode: 'demo', data_available: true,
    period_start: new Date(now - days * 24 * 60 * 60 * 1_000).toISOString(),
    period_end: new Date(now).toISOString(),
    summary: '这是合成数据的趋势简报示例。情绪会随情境变化，给自己留一点从容的空间。',
    emotion_trend: summary.trend,
    highlights: ['合成示例中，平静与愉悦的记录较常见。'],
    concerns: [],
    suggestions: ['留意让自己感到舒适的时刻。', '需要时暂停一下，按照自己的节奏继续。'],
    interaction_count: summary.total_records,
    health_score: null,
  };
}

export function createDemoApi(now = () => Date.now()): CompanionApi {
  return {
    getSnapshot: () => result<DashboardSnapshot>(() => {
      const timestamp = new Date(now()).toISOString();
      return {
        timestamp, mode: 'demo', data_available: true,
        emotion: {
          category: 'calm', confidence: 0.84, valence: 0.36, arousal: 0.22,
          vision_emotion: 'calm', speech_emotion: 'calm', environment_signal: 'demo',
          emotional_cause: '合成演示，未采集摄像头或麦克风。', attention_level: 0.8, timestamp,
        },
        behavior: null,
        intervention: { intervention_type: 'none', guidance_text: '', guidance_style: 'gentle', parent_alert: false },
        risk: { status: 'unknown', has_risk: null, triggers: [], checked_at: null },
        bridge: { connected: false, running: false, cycle_count: 0, last_update: null },
        system: { status: 'unknown', checked_at: null },
      };
    }),
    getHistory(query: HistoryQuery) {
      validateHistoryQuery(query);
      const captured = { ...query };
      return result<HistoryPage>(() => {
        const data = records(captured.days, now());
        return {
          ...captured, mode: 'demo', total: data.length,
          records: data.slice(captured.offset, captured.offset + captured.limit),
          has_more: captured.offset + captured.limit < data.length,
        };
      });
    },
    getAnalytics(days) {
      validatePeriod(days);
      return result(() => analytics(days, now()));
    },
    getReport(days) {
      validatePeriod(days);
      return result(() => report(days, now()));
    },
    getSettings: () => result<SettingsView>(() => ({
      mode: 'demo', local_only: true, single_profile: true, api_base: '/api/v1',
      privacy_notice: '显式演示模式只展示合成数据，不连接后端、不申请设备权限、不保存原始音视频。',
      storage: { status: 'disabled', retention_days: 0, retention_policy: 'manual', raw_text_saved: false },
      app_env: 'demo-preview',
    })),
    getSystem: () => result<SystemStatus>(() => ({
      mode: 'demo', status: 'healthy', timestamp: new Date(now()).toISOString(),
      components: Object.fromEntries(componentNames.map(name => [name, {
        status: 'disabled', reason: '合成演示模式，未连接真实服务或设备。', checked_at: null,
      }])) as unknown as SystemComponents,
      reasons: ['演示数据来自固定合成样本，摄像头与麦克风均关闭。'],
    })),
    getMarkdown(days) {
      validatePeriod(days);
      return result(() => {
        const data = report(days, now());
        return `# SoulCompanion 演示趋势简报\n\n合成演示数据，不代表任何真实用户。\n\n时间范围：${days} 天\n\n${data.summary}\n\n## 建议\n\n${data.suggestions.map(item => `- ${item}`).join('\n')}\n`;
      });
    },
  };
}
