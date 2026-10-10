import { CompanionError } from './types';

/** wx.request has no browser origin; V1 and the CloudBase V2 origin stay independent. */
export function apiBase(configuredUrl: string): string {
  const base = configuredUrl.trim().replace(/\/+$/, '');
  if (!base) {
    throw new CompanionError('offline', '微信端尚未配置陪伴数据接口，暂时无法读取陪伴、洞察和报告。');
  }
  // Validate without URL/DOM globals, which are absent in native WeChat runtimes.
  const match = /^https:\/\/([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?(\/[^?#\\\s]*)?$/.exec(base);
  const hostname = match?.[1] ?? '';
  const port = match?.[2];
  if (!match || base.length > 2048 || hostname.length > 253
    || hostname.split('.').some(label => !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label))
    || (port !== undefined && (Number(port) < 1 || Number(port) > 65535))) {
    throw new CompanionError('error', '微信端陪伴数据接口必须配置为不含凭据、查询或片段的有效 HTTPS 地址。');
  }
  return base.endsWith('/api/v1') ? base : `${base}/api/v1`;
}
