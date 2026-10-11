import Taro from '@tarojs/taro';
import { CloudError, type AuthAdapter } from '../cloud/types';
import type { CloudWire, CloudWireRequest } from '../cloud/transport';
import { safeCloudOrigin } from '../cloud/url';
import type { RequestHandle } from '../services/types';
import { CommunityError, type CommunityFailure } from './apiTypes';
import * as validate from './validation';

const taroWire: CloudWire = (request, respond, fail) => {
  const task = Taro.request({ url: request.url, method: request.method, header: request.headers, data: request.data,
    timeout: request.timeoutMs, dataType: 'text', responseType: 'text',
    success: response => respond({ status: response.statusCode, data: response.data, headers: response.header as Record<string, unknown> }), fail });
  void task.catch(() => undefined);
  return task;
};
interface Route { public: boolean; query?: readonly string[]; body?: readonly string[]; key?: boolean; empty?: boolean }
const uuid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const routePattern = (value: string, pattern: string) => new RegExp(`^${pattern}$`).test(value);
function route(method: CloudWireRequest['method'], path: string): Route {
  const [base, raw, extra] = path.split('?');
  if (extra !== undefined || path.length > 1800) throw new CommunityError('invalid');
  let result: Route | undefined;
  const paging = ['limit', 'cursor'] as const;
  if (method === 'GET') {
    if (base === '/api/v2/community/posts') result = { public: true, query: [...paging, 'age_band', 'topic'] };
    else if (routePattern(base, `/api/v2/community/posts/${uuid}/comments`)) result = { public: true, query: paging };
    else if (routePattern(base, `/api/v2/community/(?:posts|comments)/${uuid}`)) result = { public: true };
    else if (routePattern(base, '/api/v2/me/community/(?:posts|comments|bookmarks)')) result = { public: false, query: paging };
    else if (routePattern(base, `/api/v2/me/community/posts/${uuid}/relations`)
      || routePattern(base, `/api/v2/me/community/(?:posts|comments)/${uuid}(?:/feedback)?`)) result = { public: false };
    else if (base === '/api/v2/ops/moderation' || base === '/api/v2/ops/content-reports') result = { public: false, query: [...paging, 'status'] };
    else if (routePattern(base, `/api/v2/ops/moderation/(?:posts|comments)/${uuid}`)) result = { public: false };
  } else if (method === 'POST') {
    if (base === '/api/v2/community/posts') result = { public: false, body: ['title', 'body', 'age_band', 'topic'], key: true };
    else if (routePattern(base, `/api/v2/community/posts/${uuid}/comments`)) result = { public: false, body: ['body'], key: true };
    else if (base === '/api/v2/community/content-reports') result = { public: false, body: ['target_type', 'target_id', 'reason', 'detail'], key: true };
    else if (routePattern(base, `/api/v2/ops/moderation/(?:posts|comments)/${uuid}/(?:approve|reject|hide)`)) result = { public: false, body: ['expected_revision', 'reason'], key: true };
    else if (routePattern(base, `/api/v2/ops/content-reports/${uuid}/resolve`)) result = { public: false, body: ['expected_revision', 'decision', 'reason'], key: true };
  } else if (method === 'PATCH' && routePattern(base, `/api/v2/community/posts/${uuid}`)) result = { public: false, body: ['expected_revision', 'title', 'body', 'age_band', 'topic'] };
  else if ((method === 'PUT' || method === 'DELETE') && routePattern(base, `/api/v2/community/posts/${uuid}/(?:like|bookmark)`)) result = { public: false, body: [] };
  else if (method === 'DELETE' && routePattern(base, `/api/v2/community/(?:posts|comments)/${uuid}`)) result = { public: false, query: ['expected_revision'], empty: true };
  if (!result) throw new CommunityError('invalid');
  const seen = new Set<string>();
  if (raw !== undefined) {
    if (!raw) throw new CommunityError('invalid');
    for (const pair of raw.split('&')) {
      const [key, encoded, surplus] = pair.split('=');
      if (surplus !== undefined || encoded === undefined || !result.query?.includes(key) || seen.has(key)) throw new CommunityError('invalid');
      seen.add(key);
      let value: string;
      try { value = decodeURIComponent(encoded); } catch { throw new CommunityError('invalid'); }
      if (key === 'age_band') validate.age(value);
      else if (key === 'topic') validate.topic(value);
      else if (key === 'cursor') validate.cursor(value);
      else if (key === 'status') base === '/api/v2/ops/moderation' ? validate.status(value) : validate.reportStatus(value);
      else if (!/^[1-9]\d{0,15}$/.test(value) || !Number.isSafeInteger(Number(value)) || key === 'limit' && Number(value) > 50) throw new CommunityError('invalid');
    }
  }
  if (result.empty && !seen.has('expected_revision')) throw new CommunityError('invalid');
  return result;
}
function bodyValid(path: string, description: Route, body?: Record<string, unknown>): void {
  if (body === undefined) {
    if (description.body?.length) throw new CommunityError('invalid');
    return;
  }
  const v = validate.object(body);
  if (!description.body || Object.keys(v).some(key => !description.body!.includes(key))) throw new CommunityError('invalid');
  if ('title' in v || description.body.includes('title')) validate.postInput(v);
  else if (description.body.includes('body')) validate.plainText(v.body, 1000, { multiline: true });
  else if (path === '/api/v2/community/content-reports') validate.reportInput(v);
  if (description.body.includes('expected_revision')) validate.revision(v.expected_revision);
  if (description.body.includes('decision')) validate.choice(v.decision, ['resolved', 'dismissed']);
  if (description.body.includes('reason') && path !== '/api/v2/community/content-reports') validate.plainText(v.reason, 200);
}
function header(values: Record<string, unknown>, key: string): string {
  const value = Object.entries(values).find(([name]) => name.toLowerCase() === key)?.[1];
  return typeof value === 'string' ? value : '';
}
const SAFE_CODES = new Set(['unauthorized', 'forbidden', 'not_found', 'service_unavailable', 'invalid_request', 'invalid_identifier', 'invalid_age_band',
  'invalid_topic', 'invalid_status', 'invalid_revision', 'invalid_idempotency_key', 'invalid_cursor', 'invalid_page_limit', 'invalid_relationship',
  'parent_profile_required', 'revision_conflict', 'state_conflict', 'idempotency_conflict', 'relationship_conflict', 'audit_capacity_exceeded',
  'moderator_required', 'request_too_large', 'rate_limited', 'community_quota_exceeded', 'invalid_content', 'invalid_text', 'storage_unavailable',
  'validation_error', 'origin_not_allowed', 'request_rejected', 'internal_error']);
function failure(status: number, data: unknown, headers: Record<string, unknown>): CommunityError {
  const kind: CommunityFailure = ({ 401: 'unauthorized', 403: 'forbidden', 404: 'not_found', 409: 'conflict', 413: 'too_large', 422: 'invalid', 429: 'rate_limited' } as Record<number, CommunityFailure>)[status] ?? (status >= 500 ? 'server' : 'invalid');
  let serverCode: string | undefined;
  try {
    const parsed = typeof data === 'string' && data.length <= 8192 ? JSON.parse(data) as unknown : data;
    const error = validate.object(validate.object(parsed).error);
    if (typeof error.code === 'string' && SAFE_CODES.has(error.code)) serverCode = error.code;
  } catch { /* Invalid error envelopes never enter UI or logs. */ }
  const seconds = Number(header(headers, 'retry-after'));
  const id = header(headers, 'x-request-id');
  return new CommunityError(kind, status, serverCode, status === 429 && Number.isFinite(seconds) && seconds > 0 ? Math.min(seconds * 1000, 300000) : undefined,
    /^[A-Za-z0-9._-]{1,128}$/.test(id) ? id : undefined);
}

/** No automatic retries or persistence. Public GET never obtains or transmits a token. */
export class CommunityTransport {
  constructor(private readonly baseUrl: string, private readonly auth: AuthAdapter | null,
    private readonly wire: CloudWire = taroWire, private readonly timeoutMs = 8000) {
    if (!safeCloudOrigin(baseUrl) || !Number.isFinite(timeoutMs) || timeoutMs < 10 || timeoutMs > 30000) throw new CommunityError('not_configured');
  }
  request<T>(method: CloudWireRequest['method'], path: string, parse: (value: unknown) => T,
    body?: Record<string, unknown>, key?: string): RequestHandle<T> {
    const description = route(method, path);
    bodyValid(path, description, body);
    if (description.key) validate.requestKey(key);
    else if (key !== undefined) throw new CommunityError('invalid');
    const encoded = body === undefined ? undefined : JSON.stringify(body);
    if (encoded !== undefined && validate.utf8Bytes(encoded) > 16384) throw new CommunityError('too_large', 413);
    const authEpoch = this.auth?.getState().epoch;
    const subject = this.auth?.getPrincipal()?.subject;
    const current = () => description.public || Boolean(subject) && this.auth?.getState().status === 'signed_in'
      && this.auth.getState().epoch === authEpoch && this.auth.getPrincipal()?.subject === subject;
    let settled = false;
    let task: { abort(): void } | undefined;
    let rejectOperation: (error: CommunityError) => void = () => undefined;
    const promise = new Promise<T>((resolve, reject) => {
      const fail = (error: CommunityError) => { if (settled) return; settled = true; clearTimeout(timer); reject(error); };
      rejectOperation = fail;
      const timer = setTimeout(() => { fail(new CommunityError('offline')); task?.abort(); }, this.timeoutMs);
      const send = (token?: string) => {
        if (settled) return;
        if (!current()) { fail(new CommunityError('cancelled')); return; }
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token !== undefined) {
          if (!token || /[\r\n]/.test(token) || token.length > 16384) { fail(new CommunityError('unauthorized')); return; }
          headers.Authorization = `Bearer ${token}`;
        }
        if (key !== undefined) headers['Idempotency-Key'] = key;
        try {
          task = this.wire({ url: `${this.baseUrl.replace(/\/$/, '')}${path}`, method, headers, data: encoded, timeoutMs: this.timeoutMs }, response => {
            if (settled) return;
            if (!current()) { fail(new CommunityError('cancelled')); return; }
            try {
              if (response.status < 200 || response.status >= 300) {
                const error = failure(response.status, response.data, response.headers);
                // Check identity first: an old account's 401 must never expire its replacement.
                if (response.status === 401 && !description.public) this.auth?.expire();
                throw error;
              }
              if (response.status === 204 && description.empty) { const result = parse(null); settled = true; clearTimeout(timer); resolve(result); return; }
              if (!/^application\/json(?:;|$)/i.test(header(response.headers, 'content-type'))) throw new CommunityError('invalid');
              const data = typeof response.data === 'string' ? response.data : JSON.stringify(response.data);
              if (typeof data !== 'string' || validate.utf8Bytes(data) > 512000) throw new CommunityError('invalid');
              const result = parse(JSON.parse(data));
              settled = true; clearTimeout(timer); resolve(result);
            } catch (error) { fail(error instanceof CommunityError ? error : new CommunityError('invalid')); }
          }, () => fail(new CommunityError('offline')));
        } catch { fail(new CommunityError('offline')); }
      };
      if (description.public) send();
      else if (!this.auth || this.auth.getState().status !== 'signed_in' || !subject) fail(new CommunityError('unauthorized', 401));
      else void this.auth.getAccessToken().then(send).catch(error => {
        if (!current()) { fail(new CommunityError('cancelled')); return; }
        fail(error instanceof CloudError && error.kind === 'offline'
          ? new CommunityError('offline') : new CommunityError('unauthorized', 401));
      });
    });
    return { promise, cancel() { if (settled) return; rejectOperation(new CommunityError('cancelled')); task?.abort(); } };
  }
}
