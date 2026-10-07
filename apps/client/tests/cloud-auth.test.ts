import { describe, expect, it, vi } from 'vitest';
import { MemoryAuthStorage } from '../src/cloud/auth/memory';
import { WebCloudBaseAuthAdapter } from '../src/cloud/auth/web';
import { WeChatCloudBaseAuthAdapter } from '../src/cloud/auth/wechat';
import type { CloudAuthSdk, SdkSignIn } from '../src/cloud/auth/sdk';
import { cloudConfig } from '../src/cloud/config';
import { safeCloudOrigin } from '../src/cloud/url';

const envId = 'synthetic-environment';
const credentials = { username: 'synthetic', password: 'synthetic-test-password' };
const result = (): SdkSignIn => ({ data: { user: { id: 'synthetic-principal' }, session: { access_token: 'synthetic-token', user: { id: 'synthetic-principal' } } }, error: null });
function sdk() {
  let callback: ((event: string, session: null) => void) | undefined;
  const value: CloudAuthSdk = { signInWithPassword: vi.fn(async () => result()), signInWithOpenId: vi.fn(async () => result()), signOut: vi.fn(async () => undefined), getSession: vi.fn(async () => result()), getAccessToken: vi.fn(async () => ({ accessToken: 'synthetic-token', env: envId })), onAuthStateChange: vi.fn(listener => { callback = listener; return { data: { subscription: { unsubscribe: vi.fn() } } }; }) };
  return { value, emit: (event: string) => callback?.(event, null) };
}
const tick = async () => { for (let index = 0; index < 8; index++) await Promise.resolve(); };
describe('CloudBase auth adapter and memory-only SDK storage', () => {
  it('implements all six SDK storage methods without platform storage', async () => {
    const memory = new MemoryAuthStorage();
    memory.setItemSync('synthetic-key', 'synthetic-value');
    expect(await memory.getItem('synthetic-key')).toBe('synthetic-value');
    await memory.setItem('synthetic-key', 'updated-value');
    expect(memory.getItemSync('synthetic-key')).toBe('updated-value');
    await memory.removeItem('synthetic-key'); expect(memory.getItemSync('synthetic-key')).toBeNull();
    memory.setItemSync('synthetic-key', 'synthetic-value'); memory.removeItemSync('synthetic-key'); expect(await memory.getItem('synthetic-key')).toBeNull();
    await memory.setItem('synthetic-key', 'synthetic-value'); memory.clear(); expect(await memory.getItem('synthetic-key')).toBeNull();
  });
  it('does not load SDK or authenticate until explicit sign-in', async () => {
    const mock = sdk(); const loader = vi.fn(async () => mock.value);
    const auth = new WebCloudBaseAuthAdapter(loader, envId);
    expect(auth.getState().status).toBe('signed_out'); expect(loader).not.toHaveBeenCalled();
    await expect(auth.getAccessToken()).rejects.toMatchObject({ kind: 'unauthorized' });
    await auth.signIn(credentials);
    expect(auth.getState()).toMatchObject({ status: 'signed_in', principal: { subject: 'synthetic-principal', provider: 'cloudbase_web' } });
    expect(mock.value.signInWithPassword).toHaveBeenCalledWith(credentials);
    expect(await auth.getAccessToken()).toBe('synthetic-token');
    expect(JSON.stringify(auth.getState())).not.toContain('synthetic-token'); expect(JSON.stringify(auth.getState())).not.toContain(credentials.password);
  });
  it('exposes signing-in state and rejects late success after sign-out', async () => {
    const mock = sdk(); let resolve!: (result: SdkSignIn) => void;
    mock.value.signInWithPassword = vi.fn(() => new Promise<SdkSignIn>(done => { resolve = done; }));
    const auth = new WebCloudBaseAuthAdapter(async () => mock.value, envId);
    const signin = auth.signIn(credentials); await tick(); expect(auth.getState().status).toBe('signing_in');
    const logout = auth.signOut(); resolve(result()); await signin; await logout;
    expect(auth.getState()).toMatchObject({ status: 'signed_out', principal: null });
    await expect(auth.getAccessToken()).rejects.toMatchObject({ kind: 'unauthorized' });
  });
  it('normalizes SDK failures without exposing platform secrets', async () => {
    const mock = sdk(); mock.value.signInWithPassword = vi.fn(async () => ({ data: {}, error: new Error('synthetic-private-provider-error') }));
    const auth = new WebCloudBaseAuthAdapter(async () => mock.value, envId); await auth.signIn(credentials);
    expect(auth.getState().status).toBe('error'); expect(auth.getState().message).not.toContain('synthetic-private-provider-error');
  });
  it('reports offline SDK loading and allows an explicit retry', async () => {
    const mock = sdk(); const loader = vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValue(mock.value);
    const auth = new WebCloudBaseAuthAdapter(loader, envId); await auth.signIn(credentials);
    expect(auth.getState().status).toBe('offline'); await auth.signIn(credentials); expect(auth.getState().status).toBe('signed_in');
  });
  it('expires normalized state on provider sign-out', async () => {
    const mock = sdk(); const auth = new WebCloudBaseAuthAdapter(async () => mock.value, envId);
    await auth.signIn(credentials); mock.emit('SIGNED_OUT'); expect(auth.getState()).toMatchObject({ status: 'expired', principal: null });
  });
  it('rejects token environment mismatch and clears identity', async () => {
    const mock = sdk(); mock.value.getAccessToken = vi.fn(async () => ({ accessToken: 'synthetic-token', env: 'different-environment' }));
    const auth = new WebCloudBaseAuthAdapter(async () => mock.value, envId); await auth.signIn(credentials);
    await expect(auth.getAccessToken()).rejects.toMatchObject({ kind: 'unauthorized' }); expect(auth.getState().status).toBe('expired');
  });
  it('serializes new sign-in behind pending old sign-in revocation', async () => {
    const mock = sdk(); let resolveOld!: (value: SdkSignIn) => void;
    mock.value.signInWithPassword = vi.fn().mockReturnValueOnce(new Promise<SdkSignIn>(resolve => { resolveOld = resolve; })).mockResolvedValue(result());
    const auth = new WebCloudBaseAuthAdapter(async () => mock.value, envId);
    const old = auth.signIn(credentials); await tick(); const logout = auth.signOut(); const next = auth.signIn(credentials); await tick();
    expect(mock.value.signInWithPassword).toHaveBeenCalledTimes(1);
    resolveOld(result()); await old; await logout; await next;
    expect(mock.value.signOut).toHaveBeenCalledOnce(); expect(mock.value.signInWithPassword).toHaveBeenCalledTimes(2); expect(auth.getState().status).toBe('signed_in');
  });
  it('refuses SDK session subject mismatch before releasing a bearer token', async () => {
    const mock = sdk(); mock.value.getSession = vi.fn(async () => ({ data: { user: { id: 'other-synthetic-subject' } }, error: null }));
    const auth = new WebCloudBaseAuthAdapter(async () => mock.value, envId); await auth.signIn(credentials);
    await expect(auth.getAccessToken()).rejects.toMatchObject({ kind: 'unauthorized' }); expect(auth.getState().status).toBe('expired');
  });
  it('mini-program uses official OpenID provider HTTP flow and standard access token', async () => {
    const mock = sdk(); const auth = new WeChatCloudBaseAuthAdapter(async () => mock.value, envId);
    await auth.signIn(); expect(mock.value.signInWithOpenId).toHaveBeenCalledWith({ useWxCloud: false });
    expect(mock.value.signInWithPassword).not.toHaveBeenCalled(); expect(await auth.getAccessToken()).toBe('synthetic-token');
    expect(auth.getPrincipal()?.provider).toBe('wechat_mini');
  });
  it('clears SDK memory on logout even when remote revocation fails', async () => {
    const mock = sdk(); mock.value.signOut = vi.fn(async () => { throw new Error('network'); }); let storage!: MemoryAuthStorage;
    const auth = new WebCloudBaseAuthAdapter(async supplied => { storage = supplied; storage.setItemSync('synthetic-key', 'synthetic-value'); return mock.value; }, envId);
    await auth.signIn(credentials); await auth.signOut(); expect(storage.getItemSync('synthetic-key')).toBeNull();
    expect(auth.getState()).toMatchObject({ status: 'signed_out', principal: null }); expect(auth.getState().message).toContain('暂未确认');
  });
  it('does not falsely confirm revocation when SDK returns an error envelope', async () => {
    const mock = sdk(); mock.value.signOut = vi.fn(async () => ({ data: {}, error: new Error('synthetic-private-provider-error') }));
    const auth = new WebCloudBaseAuthAdapter(async () => mock.value, envId); await auth.signIn(credentials); await auth.signOut();
    expect(auth.getState()).toMatchObject({ status: 'signed_out', principal: null }); expect(auth.getState().message).toContain('暂未确认');
    expect(auth.getState().message).not.toContain('synthetic-private-provider-error');
  });
  it.each(['', 'http://remote.test', 'https://test.invalid/path', 'https://test.invalid?secret=x', 'https://user:password@test.invalid'])('disables unsafe or unconfigured cloud URL %s', apiBaseUrl => {
    expect(cloudConfig({ envId, region: 'ap-shanghai', apiBaseUrl }, false).enabled).toBe(false);
  });
  it('DEMO_ONLY always disables cloud even when public cloud values exist', () => { expect(cloudConfig({ envId, region: 'ap-shanghai', apiBaseUrl: 'https://test.invalid' }, true).enabled).toBe(false); });
  it('accepts HTTPS and loopback-only HTTP development configuration', () => {
    expect(cloudConfig({ envId, region: 'ap-shanghai', apiBaseUrl: 'https://test.invalid' }, false).enabled).toBe(true);
    expect(cloudConfig({ envId, region: 'ap-shanghai', apiBaseUrl: 'http://127.0.0.1:8500' }, false).enabled).toBe(true);
  });
  it.each(['https://trusted.test\\@evil.test', 'https://trusted.test:65536', 'https://..test', 'https://-test.invalid', 'https://test.invalid/#x', 'https://test.invalid?token=x'])('native-safe URL validation refuses %s', value => { expect(safeCloudOrigin(value)).toBe(false); });
});
