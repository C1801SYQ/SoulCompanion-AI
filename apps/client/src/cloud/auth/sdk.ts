import { CloudError, type AuthAdapter, type AuthPrincipal, type AuthState, type SignInInput } from '../types';
import { MemoryAuthStorage } from './memory';

export interface SdkUser { id?: unknown }
export interface SdkSession { user?: SdkUser; access_token?: string }
export interface SdkSignIn { data: { user?: SdkUser | null; session?: SdkSession | null }; error: unknown | null }
export interface CloudAuthSdk {
  signInWithPassword(input: { username: string; password: string }): Promise<SdkSignIn>;
  signInWithOpenId(input: { useWxCloud: boolean }): Promise<SdkSignIn>;
  signOut(): Promise<unknown>;
  getAccessToken(): Promise<{ accessToken: string; env: string }>;
  getSession(): Promise<SdkSignIn>;
  onAuthStateChange(callback: (event: string, session: SdkSession | null) => void): { data: { subscription: { unsubscribe(): void } } };
}
export type SdkLoader = (storage: MemoryAuthStorage) => Promise<CloudAuthSdk>;

/** SDK owns credential verification and refresh. Only normalized state crosses this boundary. */
export class SdkAuthAdapter implements AuthAdapter {
  private state: AuthState = Object.freeze({ status: 'signed_out', principal: null, epoch: 0, message: '' });
  private listeners = new Set<() => void>();
  private storage = new MemoryAuthStorage();
  private sdk: CloudAuthSdk | null = null;
  private loading: Promise<CloudAuthSdk> | null = null;
  private unsubscribe: (() => void) | null = null;
  private disposed = false;
  private generation = 0;
  private signing: Promise<SdkSignIn> | null = null;
  private resetting: Promise<void> | null = null;
  constructor(private readonly load: SdkLoader, private readonly provider: AuthPrincipal['provider'], private readonly envId: string) {}
  getState = (): AuthState => this.state;
  getPrincipal = (): AuthPrincipal | null => this.state.principal;
  subscribeAuthState = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update(status: AuthState['status'], principal: AuthPrincipal | null, message = '') {
    if (this.disposed) return;
    this.state = Object.freeze({ status, principal, message, epoch: this.state.epoch + 1 });
    for (const listener of this.listeners) listener();
  }
  private async getSdk(): Promise<CloudAuthSdk> {
    if (!this.loading) this.loading = this.load(this.storage).then(sdk => {
      this.sdk = sdk;
      if (this.disposed) { this.storage.clear(); return sdk; }
      this.unsubscribe = sdk.onAuthStateChange((event, session) => {
        if (event === 'SIGNED_OUT' && this.state.status === 'signed_in') this.expire();
        // Sign-in is published by the awaited operation, never by a late SDK callback.
        if (event === 'TOKEN_REFRESHED' && this.state.status === 'signed_in'
          && session?.user?.id !== this.state.principal?.subject) this.expire();
      }).data.subscription.unsubscribe;
      return sdk;
    }).catch(() => { this.loading = null; throw new CloudError('offline'); });
    return this.loading;
  }
  async signIn(input: SignInInput = {}): Promise<void> {
    if (this.disposed || this.state.status === 'signing_in') return;
    if (this.provider === 'cloudbase_web' && (!input.username?.trim() || !input.password || input.username.length > 128 || input.password.length > 256)) {
      this.update('error', null, '请输入用户名和密码。'); return;
    }
    const generation = ++this.generation;
    this.update('signing_in', null);
    try {
      if (this.resetting) await this.resetting;
      const sdk = await this.getSdk();
      if (generation !== this.generation || this.disposed) return;
      const operation = this.provider === 'wechat_mini' ? sdk.signInWithOpenId({ useWxCloud: false })
        : sdk.signInWithPassword({ username: input.username!.trim(), password: input.password! });
      this.signing = operation;
      const result = await operation.finally(() => { if (this.signing === operation) this.signing = null; });
      if (generation !== this.generation || this.disposed) { if (this.disposed) this.storage.clear(); return; }
      const subject = result.data?.user?.id ?? result.data?.session?.user?.id;
      if (result.error || typeof subject !== 'string' || !subject || subject.length > 512) throw new CloudError('unauthorized');
      this.update('signed_in', Object.freeze({ subject, provider: this.provider }));
    } catch (error) {
      if (generation !== this.generation || this.disposed) return;
      this.storage.clear();
      this.update(error instanceof CloudError && error.kind === 'offline' ? 'offline' : 'error', null, '登录没有完成，请检查账号或网络后重试。');
    }
  }
  async getAccessToken(): Promise<string> {
    const generation = this.generation;
    if (this.state.status !== 'signed_in') throw new CloudError('unauthorized');
    try {
      const result = await (await this.getSdk()).getAccessToken();
      if (generation !== this.generation || this.state.status !== 'signed_in') throw new CloudError('cancelled');
      const session = await (await this.getSdk()).getSession();
      if (generation !== this.generation || this.state.status !== 'signed_in') throw new CloudError('cancelled');
      const subject = session.data?.user?.id ?? session.data?.session?.user?.id;
      if (session.error || subject !== this.state.principal?.subject) { this.expire(); throw new CloudError('unauthorized'); }
      if (result.env !== this.envId || !result.accessToken || /[\r\n]/.test(result.accessToken) || result.accessToken.length > 16384) {
        this.expire(); throw new CloudError('unauthorized');
      }
      return result.accessToken;
    } catch (error) {
      if (error instanceof CloudError) throw error;
      throw new CloudError('offline');
    }
  }
  async signOut(): Promise<void> {
    const generation = ++this.generation;
    this.update('signed_out', null);
    // Clear local visibility first, even if revocation cannot reach the provider.
    await this.resetSdk(generation, true);
  }
  private resetSdk(generation: number, warn: boolean): Promise<void> {
    const signing = this.signing;
    const previous = this.resetting;
    const reset = (async () => {
      try {
        await previous;
        try { await signing; } catch { /* Failed sign-in still needs local credential cleanup. */ }
        if (this.loading) {
          const result = await (await this.loading).signOut();
          // SDK v3 may return { error } instead of rejecting the revocation operation.
          if (result && typeof result === 'object' && 'error' in result && result.error) throw new CloudError('offline');
        }
      }
      catch { if (warn && generation === this.generation) this.update('signed_out', null, '本机已退出；云端撤销暂未确认，请检查网络后再次退出。'); }
      finally { this.storage.clear(); }
    })();
    this.resetting = reset;
    void reset.finally(() => { if (this.resetting === reset) this.resetting = null; });
    return reset;
  }
  expire(): void { const generation = ++this.generation; this.storage.clear(); this.update('expired', null, '登录已失效，请重新登录。'); void this.resetSdk(generation, false); }
  dispose(): void { ++this.generation; this.disposed = true; this.unsubscribe?.(); this.storage.clear(); this.listeners.clear(); this.sdk = null; }
}
