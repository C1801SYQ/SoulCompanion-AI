import { describe, expect, it, vi } from 'vitest';
import { MemoryAuthStorage } from '../src/cloud/auth/memory';
const mock = vi.hoisted(() => {
  const auth = { signInWithPassword: vi.fn(async () => ({ data: { user: { id: 'synthetic-subject' } }, error: null })), signInWithOpenId: vi.fn(async () => ({ data: { user: { id: 'synthetic-subject' } }, error: null })), getSession: vi.fn(async () => ({ data: { user: { id: 'synthetic-subject' } }, error: null })), signOut: vi.fn(async () => undefined), getAccessToken: vi.fn(async () => ({ accessToken: 'synthetic-token', env: 'synthetic-env' })), onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) };
  const authFactory = vi.fn(() => auth); const init = vi.fn(() => ({ auth: authFactory })); const adapter = { runtime: 'wx_mp' };
  return { auth, authFactory, init, adapter, useAdapters: vi.fn() };
});
vi.mock('@cloudbase/js-sdk', () => ({ default: { init: mock.init, useAdapters: mock.useAdapters } }));
vi.mock('@cloudbase/adapter-wx_mp', () => ({ default: mock.adapter }));
import { createCloudAuthAdapter as web } from '../src/cloud/auth/platform.h5';
import { createCloudAuthAdapter as wechat } from '../src/cloud/auth/platform.weapp';
const config = { enabled: true, envId: 'synthetic-env', region: 'ap-shanghai', appId: 'synthetic-app-id', apiBaseUrl: 'https://synthetic.test' };
describe('official SDK platform initialization', () => {
  it('H5 passes memory storage before SDK auto-auth initialization and disables URL sessions', async () => {
    const auth = web(config); expect(mock.init).not.toHaveBeenCalled(); await auth.signIn({ username: 'synthetic', password: 'synthetic-password' });
    const options = mock.init.mock.calls[0] as unknown as [Record<string, unknown>];
    expect(options[0]).toMatchObject({ env: config.envId, region: config.region, persistence: 'none', auth: { detectSessionInUrl: false } }); expect(options[0].storage).toBeInstanceOf(MemoryAuthStorage);
    const authOptions = mock.authFactory.mock.calls[0] as unknown as [Record<string, unknown>]; expect(authOptions[0].storage).toBe(options[0].storage);
  });
  it('Mini Program chooses native wx adapter and official OpenID token flow', async () => {
    const auth = wechat(config); await auth.signIn(); expect(mock.useAdapters).toHaveBeenCalledWith(mock.adapter); expect(mock.auth.signInWithOpenId).toHaveBeenCalledWith({ useWxCloud: false });
    const options = mock.init.mock.calls[mock.init.mock.calls.length - 1] as unknown as [Record<string, unknown>]; expect(options[0].storage).toBeInstanceOf(MemoryAuthStorage); expect(await auth.getAccessToken()).toBe('synthetic-token');
  });
});
