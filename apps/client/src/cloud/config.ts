export interface CloudConfig { enabled: boolean; envId: string; region: string; appId: string; apiBaseUrl: string }
export function cloudConfig(values: Partial<CloudConfig> = {}, demoOnly = typeof PUBLIC_DEMO_ONLY !== 'undefined' && PUBLIC_DEMO_ONLY): CloudConfig {
  const envId = values.envId ?? (typeof PUBLIC_CLOUDBASE_ENV_ID === 'undefined' ? '' : PUBLIC_CLOUDBASE_ENV_ID);
  const region = values.region ?? (typeof PUBLIC_CLOUDBASE_REGION === 'undefined' ? '' : PUBLIC_CLOUDBASE_REGION);
  const appId = values.appId ?? (typeof PUBLIC_WECHAT_APP_ID === 'undefined' ? '' : PUBLIC_WECHAT_APP_ID);
  const apiBaseUrl = values.apiBaseUrl ?? (typeof PUBLIC_API_BASE_URL === 'undefined' ? '' : PUBLIC_API_BASE_URL);
  const valid = safeCloudOrigin(apiBaseUrl);
  return Object.freeze({ enabled: !demoOnly && valid && Boolean(envId) && region === 'ap-shanghai', envId, region, appId, apiBaseUrl: apiBaseUrl.replace(/\/$/, '') });
}
import { safeCloudOrigin } from './url';
