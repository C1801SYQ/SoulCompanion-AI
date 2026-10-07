import { SdkAuthAdapter, type SdkLoader } from './sdk';
/** Official OpenID provider → CloudBase access token; HTTP API still verifies that token. */
export class WeChatCloudBaseAuthAdapter extends SdkAuthAdapter {
  constructor(load: SdkLoader, envId: string) { super(load, 'wechat_mini', envId); }
}
