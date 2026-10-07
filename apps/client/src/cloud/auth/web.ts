import { SdkAuthAdapter, type SdkLoader } from './sdk';
export class WebCloudBaseAuthAdapter extends SdkAuthAdapter {
  constructor(load: SdkLoader, envId: string) { super(load, 'cloudbase_web', envId); }
}
