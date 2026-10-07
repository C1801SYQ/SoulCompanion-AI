import type { CloudConfig } from '../config';
import { WeChatCloudBaseAuthAdapter } from './wechat';
import { CloudError, type SourcePlatform } from '../types';
export function createCloudAuthAdapter(config: CloudConfig) {
  return new WeChatCloudBaseAuthAdapter(async storage => {
    if (PUBLIC_CLOUD_ENABLED) {
      const [{ default: cloudbase }, { default: wxAdapter }] = await Promise.all([import('@cloudbase/js-sdk'), import('@cloudbase/adapter-wx_mp')]);
      cloudbase.useAdapters(wxAdapter);
      const options = { env: config.envId, region: config.region, persistence: 'none' as const, storage, timeout: 8000, debug: false, auth: { detectSessionInUrl: false } };
      const app = cloudbase.init(options);
      const authOptions = { persistence: 'none' as const, storage, detectSessionInUrl: false };
      return app.auth(authOptions);
    }
    throw new CloudError('not_configured');
  }, config.envId);
}
export const cloudSourcePlatform: SourcePlatform = 'wechat';
