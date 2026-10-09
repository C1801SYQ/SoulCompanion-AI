import { describe, expect, it, vi } from 'vitest';
import { FakeAuthAdapter } from '../src/cloud/auth/fake';
import { CloudStore } from '../src/cloud/store';
import { CloudSessionBridge } from '../src/cloud/session';
import { CloudError, type ChildProfile, type CloudApi, type CloudSession, type CloudUser } from '../src/cloud/types';
import type { RequestHandle } from '../src/services/types';
const id = '11111111-1111-4111-8111-111111111111';
const secondId = '22222222-2222-4222-8222-222222222222';
const sessionId = '33333333-3333-4333-8333-333333333333';
const date = '2026-10-07T01:00:00Z';
const user: CloudUser = { id, display_name: 'Synthetic user', status: 'active', created_at: date, updated_at: date };
const profile: ChildProfile = { id, nickname: 'Synthetic profile', status: 'active', created_at: date, updated_at: date };
const active: CloudSession = { id: sessionId, child_profile_id: id, source_platform: 'web', started_at: date, ended_at: null, status: 'active', created_at: date };
const ended: CloudSession = { ...active, ended_at: '2026-10-07T01:01:00Z', status: 'ended' };
const tick = async () => { for (let index = 0; index < 20; index++) await Promise.resolve(); };
function result<T>(value: T): RequestHandle<T> { return { promise: Promise.resolve(value), cancel: vi.fn() }; }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const handle = { promise: new Promise<T>((done, fail) => { resolve = done; reject = fail; }), cancel: vi.fn() }; return { handle, resolve, reject }; }
function api() {
  let profiles: ChildProfile[] = [];
  const page = <T>(items: T[]) => ({ items, limit: 100, offset: 0, total: items.length });
  const value: CloudApi = {
    me: vi.fn(() => result(user)), updateMe: vi.fn(display_name => result({ ...user, display_name })), children: vi.fn(() => result(page(profiles))),
    child: vi.fn(() => result(profile)), createChild: vi.fn(nickname => { profiles = [{ ...profile, nickname }]; return result(profiles[0]); }), updateChild: vi.fn((selected, nickname) => { profiles = profiles.map(item => item.id === selected ? { ...item, nickname } : item); return result(profiles[0]); }), archiveChild: vi.fn(selected => { profiles = profiles.filter(item => item.id !== selected); return result(undefined); }),
    createSession: vi.fn(() => result(active)), endSession: vi.fn(() => result(ended)), sessions: vi.fn(() => result(page<CloudSession>([]))), emotions: vi.fn(() => result(page([]))), reports: vi.fn(() => result(page([]))), currentReport: vi.fn(() => result(null)),
  };
  return { value, setProfiles: (next: ChildProfile[]) => { profiles = next; } };
}
async function setup() { const auth = new FakeAuthAdapter(); const mock = api(); const store = new CloudStore(auth, mock.value); await auth.signIn(); await tick(); return { auth, mock, store }; }
describe('public preview does not read private family data', () => {
  it('can pause before sign-in without changing auth or writing data', async () => {
    const auth = new FakeAuthAdapter(); const mock = api(); const store = new CloudStore(auth, mock.value);
    store.setPrivateReadsEnabled(false);
    await auth.signIn(); await tick(); await store.refresh();
    expect(store.getState().auth.status).toBe('signed_in');
    expect(mock.value.me).not.toHaveBeenCalled(); expect(mock.value.children).not.toHaveBeenCalled();
    store.setPrivateReadsEnabled(true); await tick();
    expect(mock.value.me).toHaveBeenCalledTimes(1); expect(mock.value.children).toHaveBeenCalledTimes(1);
  });
  it('cancels pending reads and ignores late results on public entry', async () => {
    const { auth, mock, store } = await setup();
    const pending = deferred<{ items: ChildProfile[]; total: number; limit: number; offset: number }>();
    mock.value.children = vi.fn(() => pending.handle);
    const read = store.refresh(); await tick();
    store.setPrivateReadsEnabled(false);
    expect(pending.handle.cancel).toHaveBeenCalled();
    pending.resolve({ items: [profile], total: 1, limit: 100, offset: 0 }); await read;
    expect(store.getState().profiles).toEqual([]);
    await auth.signOut(); expect(store.getState()).toMatchObject({ user: null, profiles: [], selectedId: null });
  });
  it('prevents selected-record reads in public scope and still clears changed identities', async () => {
    const { auth, mock, store } = await setup(); mock.setProfiles([profile]); await store.refresh();
    store.setPrivateReadsEnabled(false); store.selectProfile(id); await tick();
    expect(mock.value.sessions).not.toHaveBeenCalled(); expect(mock.value.emotions).not.toHaveBeenCalled(); expect(mock.value.reports).not.toHaveBeenCalled();
    auth.setAccount('other-synthetic-parent', 'other-synthetic-token'); await tick();
    expect(store.getState()).toMatchObject({ user: null, profiles: [], selectedId: null });
    expect(mock.value.children).toHaveBeenCalledTimes(2);
  });
});
describe('private cloud state ownership epochs', () => {
  it('unconfigured cloud neither authenticates nor requests and remains local-only', async () => { const store = new CloudStore(null, null); await store.refresh(); expect(store.getState()).toMatchObject({ enabled: false, status: 'not_configured', user: null, profiles: [], selectedId: null }); });
  it('signed-in empty profile state stays explicit and never auto-selects', async () => { const { mock, store } = await setup(); expect(store.getState()).toMatchObject({ status: 'ready', profiles: [], selectedId: null }); mock.setProfiles([profile]); await store.refresh(); expect(store.getState().profiles).toEqual([profile]); expect(store.getState().selectedId).toBeNull(); });
  it('creates, explicitly selects, updates and archives owned nickname', async () => { const { mock, store } = await setup(); await store.createProfile('Synthetic nickname'); expect(store.getState().profiles[0].nickname).toBe('Synthetic nickname'); expect(store.getState().selectedId).toBeNull(); store.selectProfile(id); await tick(); expect(store.getState().selectedId).toBe(id); expect(mock.value.sessions).toHaveBeenCalledWith(id); await store.updateProfile(id, 'Updated synthetic'); expect(store.getState().profiles[0].nickname).toBe('Updated synthetic'); await store.archiveProfile(id); expect(store.getState()).toMatchObject({ profiles: [], selectedId: null, sessions: [], emotions: [], reports: [] }); });
  it('rejects selecting an arbitrary profile absent from this account', async () => { const { store } = await setup(); expect(() => store.selectProfile(secondId)).toThrow(); });
  it('logout clears private records synchronously and ignores late previous-account result', async () => {
    const { auth, mock, store } = await setup(); const pending = deferred<ReturnType<CloudApi['children']> extends RequestHandle<infer T> ? T : never>(); mock.value.children = vi.fn(() => pending.handle); const read = store.refresh(); await tick(); const logout = auth.signOut();
    expect(store.getState()).toMatchObject({ user: null, profiles: [], selectedId: null, sessions: [], emotions: [], reports: [] }); expect(pending.handle.cancel).toHaveBeenCalled(); pending.resolve({ items: [profile], total: 1, limit: 100, offset: 0 }); await read; await logout; expect(store.getState().profiles).toEqual([]);
  });
  it('account change ignores late old profile success and preserves new-account user', async () => {
    const { auth, mock, store } = await setup(); const old = deferred<{ items: ChildProfile[]; total: number; limit: number; offset: number }>(); mock.value.children = vi.fn().mockReturnValueOnce(old.handle).mockReturnValue(result({ items: [], limit: 100, offset: 0, total: 0 })); const read = store.refresh(); await tick(); auth.setAccount('second-synthetic-subject', 'second-synthetic-token'); await tick(); old.resolve({ items: [profile], limit: 100, offset: 0, total: 1 }); await read; expect(store.getState().auth.principal?.subject).toBe('second-synthetic-subject'); expect(store.getState().profiles).toEqual([]);
  });
  it('profile change clears records before any asynchronous fetch and ignores old-profile response', async () => {
    const { mock, store } = await setup(); mock.setProfiles([profile, { ...profile, id: secondId, nickname: 'Second synthetic' }]); await store.refresh(); const old = deferred<{ items: CloudSession[]; total: number; limit: number; offset: number }>(); mock.value.sessions = vi.fn().mockReturnValueOnce(old.handle).mockReturnValue(result({ items: [], limit: 100, offset: 0, total: 0 })); store.selectProfile(id); await tick(); store.selectProfile(secondId); expect(store.getState().sessions).toEqual([]); old.resolve({ items: [active], limit: 100, offset: 0, total: 1 }); await tick(); expect(store.getState().selectedId).toBe(secondId); expect(store.getState().sessions).toEqual([]);
  });
  it('normalizes cloud failures without choosing a demo data source', async () => { const { mock, store } = await setup(); mock.value.children = vi.fn(() => ({ promise: Promise.reject(new CloudError('offline')), cancel: vi.fn() })); await store.refresh(); expect(store.getState().status).toBe('offline'); expect(store.getState().enabled).toBe(true); expect(store.getState().auth.status).toBe('signed_in'); });
});
describe('cloud session metadata cannot hold local device lifecycle', () => {
  it('anonymous/unselected local session invokes no cloud API', async () => { const auth = new FakeAuthAdapter(); const mock = api(); const bridge = new CloudSessionBridge(auth, mock.value, 'web'); bridge.begin(id); bridge.end(); expect(mock.value.createSession).not.toHaveBeenCalled(); await auth.signIn(); bridge.begin(null); expect(mock.value.createSession).not.toHaveBeenCalled(); expect(bridge.getState().status).toBe('local_only'); });
  it('uploads only selected profile and source platform, closes idempotent metadata', async () => { const auth = new FakeAuthAdapter(); await auth.signIn(); const mock = api(); const bridge = new CloudSessionBridge(auth, mock.value, 'web'); bridge.begin(id); await tick(); expect(mock.value.createSession).toHaveBeenCalledWith(id, 'web'); expect(bridge.getState().status).toBe('active'); const returnValue = bridge.end(); expect(returnValue).toBeUndefined(); await tick(); expect(mock.value.endSession).toHaveBeenCalledWith(sessionId); expect(bridge.getState().status).toBe('ended'); });
  it('late create after local End is closed under the same still-valid identity', async () => { const auth = new FakeAuthAdapter(); await auth.signIn(); const mock = api(); const create = deferred<CloudSession>(); mock.value.createSession = vi.fn(() => create.handle); const bridge = new CloudSessionBridge(auth, mock.value, 'web'); bridge.begin(id); bridge.end(); expect(bridge.getState().status).toBe('ending'); create.resolve(active); await tick(); expect(mock.value.endSession).toHaveBeenCalledWith(sessionId); expect(bridge.getState().status).toBe('ended'); });
  it('late create after logout never authenticates its end using the new account', async () => { const auth = new FakeAuthAdapter(); await auth.signIn(); const mock = api(); const create = deferred<CloudSession>(); mock.value.createSession = vi.fn(() => create.handle); const bridge = new CloudSessionBridge(auth, mock.value, 'web'); bridge.begin(id); bridge.end(); await auth.signOut(); create.resolve(active); await tick(); expect(mock.value.endSession).not.toHaveBeenCalled(); expect(bridge.getState()).toMatchObject({ status: 'end_unconfirmed', sessionId: null }); });
  it('stale completion after private context clear never replaces a newer session', async () => { const auth = new FakeAuthAdapter(); await auth.signIn(); const mock = api(); const old = deferred<CloudSession>(); mock.value.createSession = vi.fn().mockReturnValueOnce(old.handle).mockReturnValue(result({ ...active, id: secondId })); const bridge = new CloudSessionBridge(auth, mock.value, 'web'); bridge.begin(id); bridge.clearPrivate(); auth.setAccount('other-synthetic-subject', 'other-synthetic-token'); bridge.begin(id); await tick(); old.resolve(active); await tick(); expect(bridge.getState()).toMatchObject({ status: 'active', sessionId: secondId }); });
  it('failed cloud create is explicit and does not report successful recording', async () => { const auth = new FakeAuthAdapter(); await auth.signIn(); const mock = api(); mock.value.createSession = vi.fn(() => ({ promise: Promise.reject(new CloudError('offline')), cancel: vi.fn() })); const bridge = new CloudSessionBridge(auth, mock.value, 'web'); bridge.begin(id); await tick(); expect(bridge.getState()).toMatchObject({ status: 'create_unconfirmed', sessionId: null }); bridge.end(); expect(mock.value.endSession).not.toHaveBeenCalled(); expect(bridge.getState().status).toBe('end_unconfirmed'); });
  it('failed cloud End remains unconfirmed and supports explicit retry', async () => { const auth = new FakeAuthAdapter(); await auth.signIn(); const mock = api(); mock.value.endSession = vi.fn().mockReturnValueOnce({ promise: Promise.reject(new CloudError('offline')), cancel: vi.fn() }).mockReturnValue(result(ended)); const bridge = new CloudSessionBridge(auth, mock.value, 'wechat'); bridge.begin(id); await tick(); bridge.end(); await tick(); expect(bridge.getState()).toMatchObject({ status: 'end_unconfirmed', sessionId }); bridge.retryEnd(); await tick(); expect(bridge.getState().status).toBe('ended'); expect(mock.value.createSession).toHaveBeenCalledWith(id, 'wechat'); });
  it('profile switch still closes old session and hides its data immediately', async () => { const auth = new FakeAuthAdapter(); await auth.signIn(); const mock = api(); const bridge = new CloudSessionBridge(auth, mock.value, 'web'); bridge.begin(id); await tick(); bridge.clearPrivate(); expect(bridge.getState()).toMatchObject({ status: 'end_unconfirmed', sessionId: null }); await tick(); expect(mock.value.endSession).toHaveBeenCalledWith(sessionId); expect(bridge.getState().sessionId).toBeNull(); });
});
