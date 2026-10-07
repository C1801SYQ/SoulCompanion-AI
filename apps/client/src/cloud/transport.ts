import Taro from '@tarojs/taro';
import type { RequestHandle } from '../services/types';
import { CloudError, type AuthAdapter } from './types';
import { safeCloudOrigin } from './url';
export interface CloudWireResponse { status: number; data: unknown; headers: Record<string, unknown> }
export interface CloudWireRequest { url: string; method: 'GET' | 'POST' | 'PATCH' | 'DELETE'; headers: Record<string, string>; data?: string; timeoutMs: number }
export type CloudWire = (request: CloudWireRequest, respond: (response: CloudWireResponse) => void, fail: () => void) => { abort(): void };
const taroWire: CloudWire = (request, respond, fail) => {
  const task = Taro.request({ url: request.url, method: request.method, header: request.headers, data: request.data, timeout: request.timeoutMs, dataType: 'text', responseType: 'text',
    success: response => respond({ status: response.statusCode, data: response.data, headers: response.header as Record<string, unknown> }), fail });
  void task.catch(() => undefined);
  return task;
};
function header(headers: Record<string, unknown>, key: string): string { const value = Object.entries(headers).find(([name]) => name.toLowerCase() === key)?.[1]; return typeof value === 'string' ? value : ''; }
function safeRequestId(value: string): string | undefined { return /^[A-Za-z0-9._-]{1,128}$/.test(value) ? value : undefined; }

/** One deadline covers token acquisition and HTTP. No retries, media fields, cookies or persistence. */
export class CloudApiTransport {
  constructor(private readonly baseUrl: string, private readonly auth: AuthAdapter, private readonly wire: CloudWire = taroWire, private readonly timeoutMs = 8000) {
    if (!safeCloudOrigin(baseUrl) || !Number.isFinite(timeoutMs) || timeoutMs < 10 || timeoutMs > 30000) throw new CloudError('not_configured');
  }
  request<T>(method: CloudWireRequest['method'], path: string, parse: (value: unknown) => T, body?: Record<string, string>, allowEmpty = false): RequestHandle<T> {
    const uuid = '[0-9a-fA-F-]{36}';
    const route = new RegExp(`^/api/v2/(?:me|children(?:/${uuid})?|sessions(?:/${uuid}(?:/end)?)?|emotions|reports(?:/current)?)(?:\\?(?:child_profile_id|limit|offset|include_archived)=[A-Za-z0-9%-]+(?:&(?:child_profile_id|limit|offset|include_archived)=[A-Za-z0-9%-]+)*)?$`);
    if (!route.test(path)) throw new CloudError('invalid');
    if (body && Object.keys(body).some(key => !['nickname', 'display_name', 'child_profile_id', 'source_platform'].includes(key))) throw new CloudError('invalid');
    const encoded = body ? JSON.stringify(body) : undefined;
    if (encoded && encoded.length > 2048) throw new CloudError('invalid');
    const principal = this.auth.getPrincipal();
    const authEpoch = this.auth.getState().epoch;
    let settled = false;
    let task: { abort(): void } | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let rejectOperation: (error: CloudError) => void = () => undefined;
    const promise = new Promise<T>((resolve, reject) => {
      const fail = (error: CloudError) => { if (settled) return; settled = true; clearTimeout(timer); reject(error); };
      rejectOperation = fail;
      timer = setTimeout(() => { fail(new CloudError('offline')); task?.abort(); }, this.timeoutMs);
      const identityCurrent = () => Boolean(principal) && this.auth.getState().status === 'signed_in'
        && this.auth.getState().epoch === authEpoch && this.auth.getPrincipal()?.subject === principal!.subject;
      void this.auth.getAccessToken().then(token => {
        if (settled) return;
        if (!identityCurrent()) { fail(new CloudError('cancelled')); return; }
        if (!token || /[\r\n]/.test(token) || token.length > 16384) { fail(new CloudError('unauthorized')); return; }
        try {
          task = this.wire({ url: `${this.baseUrl.replace(/\/$/, '')}${path}`, method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, data: encoded, timeoutMs: this.timeoutMs }, response => {
            if (settled) return;
            if (!identityCurrent()) { fail(new CloudError('cancelled')); return; }
            try {
              const id = safeRequestId(header(response.headers, 'x-request-id'));
              if (response.status === 401) { this.auth.expire(); throw new CloudError('unauthorized', 401, id); }
              if (response.status === 403) throw new CloudError('forbidden', 403, id);
              if (response.status === 429) { const seconds = Number(header(response.headers, 'retry-after')); throw new CloudError('rate_limited', 429, id, Number.isFinite(seconds) && seconds > 0 ? Math.min(seconds * 1000, 300000) : undefined); }
              if (response.status >= 500) throw new CloudError('server', response.status, id);
              if (response.status < 200 || response.status >= 300) throw new CloudError('invalid', response.status, id);
              if (response.status === 204 && allowEmpty) { settled = true; clearTimeout(timer); resolve(parse(null)); return; }
              if (!/^application\/json(?:;|$)/i.test(header(response.headers, 'content-type'))) throw new CloudError('invalid', response.status, id);
              const data = typeof response.data === 'string' ? response.data : JSON.stringify(response.data);
              if (!data || data.length > 512000) throw new CloudError('invalid', response.status, id);
              const result = parse(JSON.parse(data));
              settled = true; clearTimeout(timer); resolve(result);
            } catch (error) { fail(error instanceof CloudError ? error : new CloudError('invalid')); }
          }, () => fail(new CloudError('offline')));
        } catch { fail(new CloudError('offline')); }
      }).catch(error => fail(error instanceof CloudError ? error : new CloudError('offline')));
    });
    return { promise, cancel() { if (settled) return; rejectOperation(new CloudError('cancelled')); task?.abort(); } };
  }
}
