import type { CloudConfig } from '../config';
import { WebCloudBaseAuthAdapter } from './web';
import { CloudError, type SourcePlatform } from '../types';
export function createCloudAuthAdapter(config: CloudConfig) {
  return new WebCloudBaseAuthAdapter(async storage => {
    if (PUBLIC_CLOUD_ENABLED) {
      const { default: cloudbase } = await import('@cloudbase/js-sdk');
      const options = { env: config.envId, region: config.region, persistence: 'none' as const, storage, timeout: 8000, debug: false, auth: { detectSessionInUrl: false } };
      const app = cloudbase.init(options);
      const authOptions = { persistence: 'none' as const, storage, detectSessionInUrl: false };
      return app.auth(authOptions);
    }
    throw new CloudError('not_configured');
  }, config.envId);
}
export const cloudSourcePlatform: SourcePlatform = 'web';
