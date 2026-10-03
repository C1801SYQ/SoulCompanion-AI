import { WebMediaCaptureAdapter, type WebMediaDriver } from './web';
import { MediaCaptureError, type CaptureConfig } from '../types';

export interface NativeLifecycleHandle { remove(): void | Promise<void> }
export interface AndroidLifecycleDriver {
  onPause(listener: () => void): Promise<NativeLifecycleHandle>;
  onAppStateChange(listener: (active: boolean) => void): Promise<NativeLifecycleHandle>;
  onNetworkChange(listener: (connected: boolean) => void): Promise<NativeLifecycleHandle>;
}

/** Capacitor's WebView uses genuine Web media; Phase08 injects App/Network handles. */
export class AndroidMediaCaptureAdapter extends WebMediaCaptureAdapter {
  private readonly nativeHandles = new Set<NativeLifecycleHandle>();
  private nativeDisposed = false;
  private nativeCleanup: Promise<void> | null = null;
  private readonly registrations: Promise<void>[] = [];

  constructor(config: Partial<CaptureConfig> = {}, web: WebMediaDriver = {}, native?: AndroidLifecycleDriver) {
    super(config, web);
    if (!native) return;
    const add = (pending: Promise<NativeLifecycleHandle>) => {
      // Retain ownership even when a registration resolves during disposal.
      this.registrations.push(pending.then(handle => { this.nativeHandles.add(handle); }));
    };
    add(native.onPause(() => this.interrupt('interrupted')));
    add(native.onAppStateChange(active => { if (!active) this.interrupt('interrupted'); }));
    add(native.onNetworkChange(connected => { if (!connected) this.interrupt('interrupted'); }));
    for (const registration of this.registrations) void registration.catch(() => this.interrupt('unsupported'));
  }
  override async dispose(): Promise<void> {
    if (this.nativeCleanup) return this.nativeCleanup;
    const alreadyDisposed = this.nativeDisposed;
    this.nativeDisposed = true;
    const pending = (async () => {
      const results = await Promise.allSettled([alreadyDisposed ? super.stopAll() : super.dispose(), ...this.registrations]);
      const removals = await Promise.allSettled([...this.nativeHandles].map(async handle => {
        await handle.remove(); this.nativeHandles.delete(handle);
      }));
      if ([...results, ...removals].some(result => result.status === 'rejected')) throw new MediaCaptureError('cleanup_failed');
    })();
    this.nativeCleanup = pending;
    try { await pending; } finally { if (this.nativeCleanup === pending) this.nativeCleanup = null; }
  }
}
