import type { CompanionApi } from './types';
import { CompanionError } from './types';
import { request } from './transport';
import {
  validateAnalytics, validateHistory, validateHistoryQuery, validatePeriod,
  validateReport, validateSettings, validateSnapshot, validateSystem,
} from './validation';

export function apiBase(configuredUrl: string): string {
  const base = configuredUrl.trim().replace(/\/+$/, '');
  if (!base || base === '/api/v1') return '/api/v1';
  if (!/^https?:\/\/[^/?#]+(?:\/[^?#]*)?$/.test(base)
    || base.replace(/^https?:\/\//, '').split('/')[0].includes('@')) {
    throw new CompanionError('error', 'API 地址必须是不含凭据的 HTTP(S) 地址。');
  }
  return base.endsWith('/api/v1') ? base : `${base}/api/v1`;
}

export function createV1Api(configuredUrl = typeof PUBLIC_API_URL === 'undefined' ? '' : PUBLIC_API_URL): CompanionApi {
  // Resolve lazily so an invalid public configuration becomes an explicit UI ERROR.
  const url = (path: string) => `${apiBase(configuredUrl)}${path}`;
  return {
    getSnapshot: () => request(url('/dashboard/snapshot'), validateSnapshot),
    getHistory(query) {
      validateHistoryQuery(query);
      const captured = { ...query };
      return request(url(`/emotions/history?days=${query.days}&limit=${query.limit}&offset=${query.offset}`),
        value => validateHistory(value, captured));
    },
    getAnalytics(days) {
      validatePeriod(days);
      return request(url(`/emotions/analytics?days=${days}`), value => validateAnalytics(value, days));
    },
    getReport(days) {
      validatePeriod(days);
      return request(url(`/reports/parent?days=${days}`), validateReport);
    },
    getSettings: () => request(url('/system/settings'), validateSettings),
    getSystem: () => request(url('/system/status'), validateSystem),
    getMarkdown(days) {
      validatePeriod(days);
      return request(url(`/reports/parent.md?days=${days}`), value => {
        if (typeof value !== 'string') throw new CompanionError('error', '报告格式无法读取。');
        return value;
      }, { format: 'text' });
    },
  };
}
