import { CompanionError } from './types';

/** Browsers can use the existing same-origin V1 proxy during development. */
export function apiBase(configuredUrl: string): string {
  const base = configuredUrl.trim().replace(/\/+$/, '');
  if (!base || base === '/api/v1') return '/api/v1';
  if (!/^https?:\/\/[^/?#]+(?:\/[^?#]*)?$/.test(base)
    || base.replace(/^https?:\/\//, '').split('/')[0].includes('@')) {
    throw new CompanionError('error', 'API 地址必须是不含凭据的 HTTP(S) 地址。');
  }
  return base.endsWith('/api/v1') ? base : `${base}/api/v1`;
}
