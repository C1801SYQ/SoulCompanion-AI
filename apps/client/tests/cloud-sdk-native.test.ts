import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryAuthStorage } from '../src/cloud/auth/memory';
const require = createRequire(import.meta.url);
afterEach(() => vi.unstubAllGlobals());
describe('published CloudBase SDK native adapter credential storage', () => {
  it('retains the supplied memory storage with the real wx adapter and never writes credentials to wx storage', async () => {
    const writes = vi.fn();
    vi.stubGlobal('Page', () => undefined);
    vi.stubGlobal('wx', {
      getSystemInfoSync: () => ({}), getAccountInfoSync: () => ({ miniProgram: { appId: 'synthetic-app-id' } }),
      getStorageSync: vi.fn(() => ''), setStorageSync: writes, removeStorageSync: vi.fn(), clearStorageSync: vi.fn(),
      connectSocket: vi.fn(), request: vi.fn(() => ({ abort: vi.fn() })),
    });
    // Use the published browser/native distribution, rather than Node's credential adapter.
    const cloudbase = require(join(dirname(require.resolve('@cloudbase/js-sdk')), 'index.cjs.js'));
    const wxAdapter = require('@cloudbase/adapter-wx_mp').default;
    const storage = new MemoryAuthStorage();
    cloudbase.useAdapters(wxAdapter);
    const options = { env: 'synthetic-env', region: 'ap-shanghai', persistence: 'none', storage, debug: false, auth: { detectSessionInUrl: false } };
    const app = cloudbase.init(options);
    app.auth({ persistence: 'none', storage, detectSessionInUrl: false });
    expect(app.platform.runtime).toBe('wx_mp');
    const oauth = app.oauthInstance.oauth2client;
    expect(oauth.localCredentials.storage).toBe(storage);
    await oauth.initializePromise;
    await oauth.setCredentials({ access_token: 'synthetic-access-token', refresh_token: 'synthetic-refresh-token', sub: 'synthetic-subject', expires_in: 3600 });
    expect((await oauth.getCredentials()).access_token).toBe('synthetic-access-token');
    // The SDK may cache the locale. No credentials or account data may enter native storage.
    expect(writes.mock.calls.every(([key, value]) => String(key) === 'lang_synthetic-env' && !String(value).includes('synthetic'))).toBe(true);
    storage.clear();
    oauth.destroy();
  });
});
