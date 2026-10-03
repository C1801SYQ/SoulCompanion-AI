import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Taro from '@tarojs/taro';
import { request } from '../src/services/transport';
import { createV1Api } from '../src/services/v1';
import { createDemoApi } from '../src/services/demo';
import { validateSnapshot } from '../src/services/validation';

vi.mock('@tarojs/taro', () => ({ default: { request: vi.fn() } }));

interface RecordedRequest {
  url: string;
  dataType: string;
  timeout: number;
  success(response: { statusCode: number; data: unknown; header: Record<string, string> }): void;
  fail(): void;
}

let calls: RecordedRequest[];
let aborts: ReturnType<typeof vi.fn>[];

beforeEach(() => {
  calls = [];
  aborts = [];
  vi.mocked(Taro.request).mockImplementation(options => {
    calls.push(options as unknown as RecordedRequest);
    const abort = vi.fn();
    aborts.push(abort);
    return Object.assign(Promise.resolve(undefined), { abort }) as unknown as ReturnType<typeof Taro.request>;
  });
});
afterEach(() => { vi.useRealTimers(); });

function respond(data: unknown, statusCode = 200, headers: Record<string, string> = {}) {
  calls[calls.length - 1].success({ statusCode, data,
    header: { 'Content-Type': 'application/json; charset=utf-8', ...headers } });
}

describe('bounded Taro request', () => {
  it('uses a validated real response and configured API base', async () => {
    const sample = await createDemoApi().getSnapshot().promise;
    const handle = createV1Api('https://api.example.test').getSnapshot();
    expect(calls[0].url).toBe('https://api.example.test/api/v1/dashboard/snapshot');
    respond({ ...sample, mode: 'real' });
    expect((await handle.promise).mode).toBe('real');
  });

  it('keeps network failures offline without substituting demo data', async () => {
    const handle = createV1Api().getSnapshot();
    calls[0].fail();
    await expect(handle.promise).rejects.toMatchObject({ kind: 'offline' });
    expect(Taro.request).toHaveBeenCalledTimes(1);
  });

  it.each([403, 409, 422, 500, 503])('keeps HTTP %s as ERROR rather than offline', async status => {
    const handle = createV1Api().getSnapshot();
    respond({ error: { code: 'TEST', message: 'private transcript must not leak', request_id: 'request-1' } }, status);
    await expect(handle.promise).rejects.toMatchObject({ kind: 'error', requestId: 'request-1' });
    await expect(handle.promise).rejects.not.toHaveProperty('message', 'private transcript must not leak');
  });

  it('honors bounded Retry-After on 429', async () => {
    const handle = createV1Api().getSnapshot();
    respond({}, 429, { 'Retry-After': '60' });
    await expect(handle.promise).rejects.toMatchObject({ kind: 'error', retryAfterMs: 60_000 });
  });

  it('rejects success with invalid content type or contract', async () => {
    const handle = createV1Api().getSnapshot();
    respond('<html>bad gateway</html>', 200, { 'Content-Type': 'text/html' });
    await expect(handle.promise).rejects.toMatchObject({ kind: 'error' });
    const second = createV1Api().getSnapshot();
    respond({ mode: 'real', data_available: true });
    await expect(second.promise).rejects.toMatchObject({ kind: 'error' });
  });

  it('cancels platform work and ignores its late success callback', async () => {
    const sample = await createDemoApi().getSnapshot().promise;
    const handle = request('/api/v1/dashboard/snapshot', validateSnapshot);
    handle.cancel();
    respond({ ...sample, mode: 'real' });
    await expect(handle.promise).rejects.toMatchObject({ kind: 'cancelled' });
    expect(aborts[0]).toHaveBeenCalledTimes(1);
    handle.cancel();
    expect(aborts[0]).toHaveBeenCalledTimes(1);
  });

  it('aborts an unresponsive request at its total deadline', async () => {
    vi.useFakeTimers();
    const handle = request('/api/v1/dashboard/snapshot', validateSnapshot, { timeoutMs: 1_000 });
    const assertion = expect(handle.promise).rejects.toMatchObject({ kind: 'offline' });
    await vi.advanceTimersByTimeAsync(1_000);
    await assertion;
    expect(aborts[0]).toHaveBeenCalledTimes(1);
  });

  it('exports only a bounded markdown response, with its selected range', async () => {
    const handle = createV1Api().getMarkdown(30);
    expect(calls[0].url).toContain('days=30');
    expect(calls[0].dataType).toBe('text');
    respond('# Real report\n', 200, { 'Content-Type': 'text/markdown; charset=utf-8' });
    expect(await handle.promise).toBe('# Real report\n');
    const oversized = createV1Api().getMarkdown(7);
    respond('x'.repeat(2_000_001), 200, { 'Content-Type': 'text/markdown' });
    await expect(oversized.promise).rejects.toMatchObject({ kind: 'error' });
  });

  it('performs zero Taro HTTP requests in explicit demo mode', async () => {
    const api = createDemoApi();
    await Promise.all([
      api.getSnapshot().promise, api.getAnalytics(7).promise,
      api.getHistory({ days: 7, limit: 20, offset: 0 }).promise,
      api.getReport(7).promise, api.getMarkdown(7).promise,
      api.getSettings().promise, api.getSystem().promise,
    ]);
    expect(Taro.request).not.toHaveBeenCalled();
  });

  it('does not send unsupported pagination to the backend', () => {
    expect(() => createV1Api().getHistory({ days: 7, limit: 501, offset: 0 })).toThrow();
    expect(Taro.request).not.toHaveBeenCalled();
  });
});
