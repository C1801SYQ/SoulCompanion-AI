import Taro from '@tarojs/taro';
import { CompanionError, type RequestHandle } from './types';

const DEFAULT_TIMEOUT_MS = 6_000;
const MAX_RESPONSE_CHARACTERS = 2_000_000;

function headerValue(headers: Record<string, unknown>, name: string): string {
  const entry = Object.entries(headers).find(([key]) => key.toLowerCase() === name);
  return entry && typeof entry[1] === 'string' ? entry[1] : '';
}

function httpFailure(status: number, payload: unknown, headers: Record<string, unknown>): CompanionError {
  const detail = payload !== null && typeof payload === 'object'
    && 'error' in payload ? payload.error : null;
  const requestId = detail !== null && typeof detail === 'object'
    && 'request_id' in detail && typeof detail.request_id === 'string'
    ? detail.request_id : headerValue(headers, 'x-request-id') || undefined;
  const waitSeconds = Number(headerValue(headers, 'retry-after'));
  const retryAfterMs = status === 429 && Number.isFinite(waitSeconds) && waitSeconds > 0
    ? Math.min(300_000, Math.max(1_000, waitSeconds * 1_000)) : undefined;
  const message = status === 403 ? '当前后端仅允许本机同源访问，请检查连接配置。'
    : status === 409 ? '当前后端模式不支持真实数据读取。'
      : status === 429 ? '请求较频繁，请稍后重试。'
        : status === 503 ? '后端数据服务暂时不可用，请稍后重试。'
          : `后端暂时无法完成请求（HTTP ${status}）。`;
  return new CompanionError('error', message, { requestId, retryAfterMs });
}

/** A single bounded request; callers own cancellation and never see platform errors. */
export function request<T>(url: string, parse: (data: unknown) => T, options: {
  format?: 'json' | 'text'; timeoutMs?: number;
} = {}): RequestHandle<T> {
  let task: { abort(): void } | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let settled = false;
  let rejectRequest: (error: CompanionError) => void = () => undefined;
  const promise = new Promise<T>((resolve, reject) => {
    const fail = (error: CompanionError) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    };
    rejectRequest = fail;
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    timer = setTimeout(() => {
      fail(new CompanionError('offline', '连接超时，请检查网络后重试。'));
      task?.abort();
    }, timeoutMs);
    try {
      const pending = Taro.request({
        url,
        method: 'GET',
        timeout: timeoutMs,
        dataType: options.format === 'text' ? 'text' : 'json',
        responseType: 'text',
        success(response) {
          if (settled) return;
          try {
            const headers = response.header as Record<string, unknown>;
            if (response.statusCode < 200 || response.statusCode >= 300) {
              throw httpFailure(response.statusCode, response.data, headers);
            }
            const contentType = headerValue(headers, 'content-type').toLowerCase();
            const expectedType = options.format === 'text' ? 'text/markdown' : 'application/json';
            if (!contentType.startsWith(expectedType)) {
              throw new CompanionError('error', '后端响应类型不符合产品接口。');
            }
            const encoded = typeof response.data === 'string'
              ? response.data : JSON.stringify(response.data);
            if (typeof encoded !== 'string' || encoded.length > MAX_RESPONSE_CHARACTERS) {
              throw new CompanionError('error', '后端响应超出允许大小。');
            }
            const value = parse(response.data);
            settled = true;
            clearTimeout(timer);
            resolve(value);
          } catch (error) {
            fail(error instanceof CompanionError ? error
              : new CompanionError('error', '后端返回的数据无法读取，请重试。'));
          }
        },
        fail() {
          fail(new CompanionError('offline', '无法连接后端，请检查网络或服务是否运行。'));
        },
      });
      task = pending;
      // Taro also returns a promise when callbacks are supplied; consume its rejection.
      void pending.catch(() => undefined);
    } catch {
      fail(new CompanionError('offline', '无法建立后端连接，请检查网络后重试。'));
    }
  });
  return {
    promise,
    cancel() {
      if (settled) return;
      rejectRequest(new CompanionError('cancelled', '请求已取消。'));
      task?.abort();
    },
  };
}
