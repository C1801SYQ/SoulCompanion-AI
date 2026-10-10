import type { CompanionApi, RequestHandle } from './types';
import { CompanionError } from './types';
import { request } from './transport';
import { apiBase } from './api-platform';
import {
  validateAnalytics, validateHistory, validateHistoryQuery, validatePeriod,
  validateReport, validateSettings, validateSnapshot, validateSystem,
} from './validation';

export { apiBase } from './api-platform';

function unavailable<T>(error: CompanionError): RequestHandle<T> {
  let cancelled = false;
  return {
    promise: Promise.resolve().then(() => {
      if (cancelled) throw new CompanionError('cancelled', '请求已取消。');
      throw error;
    }),
    cancel: () => { cancelled = true; },
  };
}

export function createV1Api(configuredUrl = typeof PUBLIC_API_URL === 'undefined' ? '' : PUBLIC_API_URL): CompanionApi {
  // Resolve lazily so an invalid public configuration becomes an explicit UI ERROR.
  const read = <T>(path: string, parse: (data: unknown) => T,
    options?: Parameters<typeof request>[2]): RequestHandle<T> => {
    let base: string;
    try {
      base = apiBase(configuredUrl);
    } catch (error) {
      if (error instanceof CompanionError && error.kind === 'offline') return unavailable(error);
      throw error;
    }
    return request(`${base}${path}`, parse, options);
  };
  return {
    getSnapshot: () => read('/dashboard/snapshot', validateSnapshot),
    getHistory(query) {
      validateHistoryQuery(query);
      const captured = { ...query };
      return read(`/emotions/history?days=${query.days}&limit=${query.limit}&offset=${query.offset}`,
        value => validateHistory(value, captured));
    },
    getAnalytics(days) {
      validatePeriod(days);
      return read(`/emotions/analytics?days=${days}`, value => validateAnalytics(value, days));
    },
    getReport(days) {
      validatePeriod(days);
      return read(`/reports/parent?days=${days}`, validateReport);
    },
    getSettings: () => read('/system/settings', validateSettings),
    getSystem: () => read('/system/status', validateSystem),
    getMarkdown(days) {
      validatePeriod(days);
      return read(`/reports/parent.md?days=${days}`, value => {
        if (typeof value !== 'string') throw new CompanionError('error', '报告格式无法读取。');
        return value;
      }, { format: 'text' });
    },
  };
}
