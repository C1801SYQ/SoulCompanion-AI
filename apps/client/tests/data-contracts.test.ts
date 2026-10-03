import { describe, expect, it, vi } from 'vitest';
import { createDemoApi } from '../src/services/demo';
import { apiBase } from '../src/services/v1';
import {
  validateAnalytics, validateHistory, validateHistoryQuery, validateReport,
  validateSettings, validateSnapshot, validateSystem,
} from '../src/services/validation';

const now = Date.parse('2026-10-03T08:00:00Z');
vi.mock('@tarojs/taro', () => ({ default: { request: vi.fn() } }));

describe('V1 contracts retain real meaning', () => {
  it('preserves unavailable live data and unknown risk as null', async () => {
    const sample = await createDemoApi(() => now).getSnapshot().promise;
    const empty = { ...sample, mode: 'real', data_available: false, emotion: null };
    expect(validateSnapshot(empty)).toEqual(empty);
    expect(validateSnapshot(empty).risk.has_risk).toBeNull();
  });

  it('rejects demo responses on the real API instead of relabelling them', async () => {
    const sample = await createDemoApi(() => now).getSnapshot().promise;
    expect(() => validateSnapshot(sample)).toThrow();
  });

  it('rejects manufactured availability without an emotion', async () => {
    const sample = await createDemoApi(() => now).getSnapshot().promise;
    expect(() => validateSnapshot({ ...sample, mode: 'real', emotion: null })).toThrow();
  });

  it.each([NaN, Infinity, -Infinity, 1.1, -0.1])('rejects invalid confidence %s', async value => {
    const sample = await createDemoApi(() => now).getSnapshot().promise;
    expect(() => validateSnapshot({ ...sample, mode: 'real',
      emotion: { ...sample.emotion, confidence: value } })).toThrow();
  });

  it('keeps an unknown emotion category available for a neutral UI fallback', async () => {
    const sample = await createDemoApi(() => now).getSnapshot().promise;
    const value = validateSnapshot({ ...sample, mode: 'real',
      emotion: { ...sample.emotion, category: 'future_category' } });
    expect(value.emotion?.category).toBe('future_category');
  });

  it('rejects known risk without a verified value and timestamp', async () => {
    const sample = await createDemoApi(() => now).getSnapshot().promise;
    expect(() => validateSnapshot({ ...sample, mode: 'real',
      risk: { ...sample.risk, status: 'known' } })).toThrow();
  });

  it('rejects a late history page from a previous range or offset', async () => {
    const query = { days: 7 as const, limit: 20, offset: 0 };
    const sample = await createDemoApi(() => now).getHistory(query).promise;
    const real = { ...sample, mode: 'real' };
    expect(validateHistory(real, query).records).toHaveLength(20);
    expect(() => validateHistory(real, { ...query, offset: 20 })).toThrow();
    expect(() => validateHistory(real, { ...query, days: 30 })).toThrow();
  });

  it('retains the V1 valence-only time series and the arousal period mean', async () => {
    const sample = await createDemoApi(() => now).getAnalytics(7).promise;
    const real = validateAnalytics({ ...sample, mode: 'real' }, 7);
    expect(real.series[0]).not.toHaveProperty('arousal');
    expect(real.trend.average_arousal).toBeGreaterThan(0);
    expect(() => validateAnalytics({ ...sample, mode: 'real' }, 30)).toThrow();
  });

  it('rejects malformed or oversized chart data', async () => {
    const sample = await createDemoApi(() => now).getAnalytics(7).promise;
    expect(() => validateAnalytics({ ...sample, mode: 'real',
      series: Array(501).fill(sample.series[0]) }, 7)).toThrow();
    expect(() => validateAnalytics({ ...sample, mode: 'real',
      counts: { calm: -1 } }, 7)).toThrow();
  });

  it('preserves an empty report with no score', async () => {
    const sample = await createDemoApi(() => now).getReport(7).promise;
    const empty = { ...sample, mode: 'real', data_available: false,
      interaction_count: 0, emotion_trend: null, health_score: null };
    expect(validateReport(empty).health_score).toBeNull();
    expect(() => validateReport({ ...empty, health_score: 0 })).toThrow();
  });

  it('requires all ten actual system components and their status fields', async () => {
    const sample = await createDemoApi(() => now).getSystem().promise;
    expect(Object.keys(validateSystem({ ...sample, mode: 'real' }).components)).toHaveLength(10);
    expect(() => validateSystem({ ...sample, mode: 'real', components: {} })).toThrow();
    expect(() => validateSystem({ ...sample, mode: 'real',
      components: { ...sample.components, camera: { status: 'active', reason: '', checked_at: null } } })).toThrow();
  });

  it('does not silently turn the local V1 product into a remote profile service', async () => {
    const sample = await createDemoApi(() => now).getSettings().promise;
    expect(validateSettings({ ...sample, mode: 'real' }).local_only).toBe(true);
    expect(() => validateSettings({ ...sample, mode: 'real', single_profile: false })).toThrow();
  });

  it.each([
    { days: 2, limit: 20, offset: 0 },
    { days: 7, limit: 0, offset: 0 },
    { days: 7, limit: 501, offset: 0 },
    { days: 7, limit: 20, offset: -1 },
  ])('rejects unsupported query before sending it: %o', query => {
    expect(() => validateHistoryQuery(query as Parameters<typeof validateHistoryQuery>[0])).toThrow();
  });

  it('builds configurable API origins without hardcoded localhost', () => {
    expect(apiBase('')).toBe('/api/v1');
    expect(apiBase('https://api.example.test/')).toBe('https://api.example.test/api/v1');
    expect(apiBase('https://api.example.test/api/v1')).toBe('https://api.example.test/api/v1');
    expect(() => apiBase('https://user:secret@api.example.test')).toThrow();
    expect(() => apiBase('javascript:alert(1)')).toThrow();
  });
});

describe('explicit synthetic source', () => {
  it('marks every DTO and exported report as demo and leaves devices off', async () => {
    const api = createDemoApi(() => now);
    const values = await Promise.all([
      api.getSnapshot().promise,
      api.getHistory({ days: 7, limit: 20, offset: 0 }).promise,
      api.getAnalytics(7).promise, api.getReport(7).promise,
      api.getSettings().promise, api.getSystem().promise,
    ]);
    expect(values.every(value => value.mode === 'demo')).toBe(true);
    expect((await api.getSystem().promise).components.camera.status).toBe('disabled');
    expect((await api.getSettings().promise).storage.raw_text_saved).toBe(false);
    expect(await api.getMarkdown(7).promise).toContain('合成演示数据');
  });

  it('produces repeatable history with no raw transcript fields', async () => {
    const query = { days: 7 as const, limit: 20, offset: 0 };
    const api = createDemoApi(() => now);
    expect(await api.getHistory(query).promise).toEqual(await api.getHistory(query).promise);
    const history = await api.getHistory(query).promise;
    expect(history.records[0]).not.toHaveProperty('source_text');
    expect(history.records[0]).not.toHaveProperty('session_id');
  });

  it('can cancel a synthetic request before it publishes', async () => {
    const request = createDemoApi(() => now).getSnapshot();
    request.cancel();
    await expect(request.promise).rejects.toMatchObject({ kind: 'cancelled' });
  });
});
