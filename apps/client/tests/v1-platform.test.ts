import { beforeEach, describe, expect, it, vi } from 'vitest';
import Taro from '@tarojs/taro';
import { apiBase as weappApiBase } from '../src/services/api-platform.weapp';
import { apiBase as h5ApiBase } from '../src/services/api-platform.h5';
import { createV1Api } from '../src/services/v1';
import { createDemoApi } from '../src/services/demo';

vi.mock('@tarojs/taro', () => ({ default: { request: vi.fn() } }));
vi.mock('../src/services/api-platform', async () => import('../src/services/api-platform.weapp'));

beforeEach(() => { vi.mocked(Taro.request).mockReset(); });

describe('WeChat V1 API configuration boundary', () => {
  it('keeps every unconfigured endpoint offline with zero native requests or synthetic responses', async () => {
    const api = createV1Api('');
    const handles = [
      api.getSnapshot(), api.getHistory({ days: 7, limit: 20, offset: 0 }),
      api.getAnalytics(7), api.getReport(7), api.getSettings(), api.getSystem(), api.getMarkdown(7),
    ];
    const outcomes = await Promise.allSettled(handles.map(handle => handle.promise));
    expect(outcomes).toHaveLength(7);
    for (const outcome of outcomes) {
      expect(outcome.status).toBe('rejected');
      if (outcome.status === 'rejected') expect(outcome.reason).toMatchObject({
        kind: 'offline', message: expect.stringContaining('尚未配置'),
      });
    }
    expect(Taro.request).not.toHaveBeenCalled();
  });

  it('honors cancellation before the unavailable request settles', async () => {
    const handle = createV1Api(' ').getSnapshot();
    handle.cancel();
    handle.cancel();
    await expect(handle.promise).rejects.toMatchObject({ kind: 'cancelled' });
    expect(Taro.request).not.toHaveBeenCalled();
  });

  it('keeps an empty public build configuration offline instead of falling back to a relative URL', async () => {
    await expect(createV1Api().getSnapshot().promise).rejects.toMatchObject({ kind: 'offline' });
    expect(Taro.request).not.toHaveBeenCalled();
  });

  it('uses only the explicitly configured HTTPS V1 URL and retains response validation', async () => {
    const sample = await createDemoApi().getSnapshot().promise;
    vi.mocked(Taro.request).mockImplementation(options => {
      options.success?.({ statusCode: 200, data: { ...sample, mode: 'real' },
        header: { 'Content-Type': 'application/json' }, cookies: [], errMsg: 'request:ok' });
      return Object.assign(Promise.resolve(undefined), { abort: vi.fn() }) as unknown as ReturnType<typeof Taro.request>;
    });
    const response = await createV1Api('https://api.example.test/api/v1/').getSnapshot().promise;
    expect(response.mode).toBe('real');
    expect(Taro.request).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      url: 'https://api.example.test/api/v1/dashboard/snapshot', method: 'GET',
    }));
  });

  it.each([
    '/api/v1', 'http://api.example.test', 'https://user:secret@api.example.test',
    'https://api.example.test?token=secret', 'https://api.example.test/#token',
    'https://api.example.test\\@other.test', 'https://bad host.test',
    'https://api..example.test', 'https://-invalid.example.test',
    'https://api.example.test:0', 'https://api.example.test:65536', 'javascript:alert(1)',
  ])('rejects invalid native configuration before transport: %s', configured => {
    expect(() => createV1Api(configured).getSnapshot()).toThrow(expect.objectContaining({ kind: 'error' }));
    expect(Taro.request).not.toHaveBeenCalled();
  });

  it('supports an explicit HTTPS origin or prefixed API base without browser globals', () => {
    expect(weappApiBase('https://api.example.test/')).toBe('https://api.example.test/api/v1');
    expect(weappApiBase('https://api.example.test:8443/legacy/api/v1')).toBe('https://api.example.test:8443/legacy/api/v1');
  });
});

describe('H5 V1 configuration remains independent', () => {
  it('retains the same-origin fallback and local HTTP development URLs', () => {
    expect(h5ApiBase('')).toBe('/api/v1');
    expect(h5ApiBase('/api/v1')).toBe('/api/v1');
    expect(h5ApiBase('http://localhost:8080')).toBe('http://localhost:8080/api/v1');
    expect(h5ApiBase('https://api.example.test/api/v1')).toBe('https://api.example.test/api/v1');
  });
});
