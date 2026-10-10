import { describe, expect, it, vi } from 'vitest';
import { FakeAuthAdapter } from '../src/cloud/auth/fake';
import { createCloudApi } from '../src/cloud/api';
import { CloudApiTransport, type CloudWireResponse, type CloudWire } from '../src/cloud/transport';
import { CloudStore } from '../src/cloud/store';
import { CloudError, type CloudApi, type ParentCommunityProfile } from '../src/cloud/types';
import * as parse from '../src/cloud/validation';
import type { RequestHandle } from '../src/services/types';
vi.mock('@tarojs/taro', () => ({ default: { request: vi.fn() } }));
const id = '11111111-1111-4111-8111-111111111111';
const date = '2026-10-07T01:00:00Z';
const profile: ParentCommunityProfile = { id, nickname: '合成家长', created_at: date, updated_at: date };
const oldChild = { id, nickname: '合成家庭昵称', status: 'active', created_at: date, updated_at: date };
const tick = async () => { for (let index = 0; index < 30; index++) await Promise.resolve(); };
function result<T>(value: T): RequestHandle<T> { return { promise: Promise.resolve(value), cancel: vi.fn() }; }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const handle = { promise: new Promise<T>((done, fail) => { resolve = done; reject = fail; }), cancel: vi.fn() }; return { handle, resolve, reject }; }
async function transportFixture() {
  const auth = new FakeAuthAdapter(); await auth.signIn();
  let respond!: (value: CloudWireResponse) => void;
  const wire: CloudWire = vi.fn((_, done) => { respond = done; return { abort: vi.fn() }; });
  return { auth, wire, api: createCloudApi(new CloudApiTransport('https://synthetic.test', auth, wire)),
    send: (status: number, data: unknown) => respond({ status, data: JSON.stringify(data), headers: { 'content-type': 'application/json' } }) };
}
function storeFixture() {
  const auth = new FakeAuthAdapter();
  const api = { me: vi.fn(() => result({ id, display_name: '私有账号名', status: 'active', created_at: date, updated_at: date })),
    children: vi.fn(() => result({ items: [], limit: 100, offset: 0, total: 0 })),
    capabilities: vi.fn(() => result({ child_age_band: true, parent_profile: true })), parentProfile: vi.fn(() => result(profile)),
    updateParentProfile: vi.fn(() => result(profile)), createChild: vi.fn(() => result({ ...oldChild, age_band: null })),
  } as unknown as CloudApi;
  return { auth, api, store: new CloudStore(auth, api, false) };
}
describe('PC02 safe shared DTOs and optional family age', () => {
  it('normalizes old child data to optional null without reading hidden fields', () => {
    expect(parse.child({ ...oldChild, owner_user_id: 'private', birthday: 'private' })).toEqual({ ...oldChild, age_band: null });
  });
  it.each(['0-2', '3-5', '6-8', '9-12', '13-15', '16-18'] as const)('accepts private age %s', age_band => expect(parse.child({ ...oldChild, age_band }).age_band).toBe(age_band));
  it.each(['all', '18+', '', 'ASD', 6])('rejects invalid server age %s', age_band => expect(() => parse.child({ ...oldChild, age_band })).toThrow());
  it('public identity parser strips every private or platform field', () => {
    expect(parse.parentProfile({ ...profile, uid: 'private', openid: 'private', owner_user_id: 'private', child_name: 'private', email: 'private' })).toEqual(profile);
    expect(parse.parentProfile(null)).toBeNull();
  });
  it('normalizes parent nickname independently from private nickname; duplicate display names are valid', () => {
    expect(parse.parentNickname('  Cafe\u0301 家长  ')).toBe('Café 家长');
    expect(parse.parentNickname('同名家长')).toBe(parse.parentNickname('同名家长'));
    expect(parse.parentNickname('A ·_- 家长')).toBe('A ·_- 家长');
    expect(parse.parentNickname('家'.repeat(24))).toHaveLength(24);
  });
  it.each(['', '家', '家'.repeat(25), '<script>', 'https://example.test', '家长\n名字', '\n家长', '家长\t', '家长\u202e', '\uFEFF家长', '家长😀'])('rejects unsafe or invalid nickname %s', value => expect(() => parse.parentNickname(value)).toThrow());
  it('strict capabilities do not invent an enabled migration', () => {
    expect(parse.capabilities({ child_age_band: false, parent_profile: true, ignored: 'private' })).toEqual({ child_age_band: false, parent_profile: true });
    expect(() => parse.capabilities({ child_age_band: 'true', parent_profile: true })).toThrow();
  });
});
describe('PC02 authenticated route/body compatibility', () => {
  it('old server capabilities 404 is honest unavailable, not demo profile or auth expiry', async () => {
    const fixture = await transportFixture(); const read = fixture.api.capabilities(); await tick(); fixture.send(404, {});
    expect(await read.promise).toEqual({ child_age_band: false, parent_profile: false }); expect(fixture.auth.getState().status).toBe('signed_in');
  });
  it('non-404 capability failures remain errors', async () => {
    const fixture = await transportFixture(); const read = fixture.api.capabilities(); await tick(); fixture.send(503, {});
    await expect(read.promise).rejects.toMatchObject({ kind: 'server' });
  });
  it.each([undefined, null, '6-8'] as const)('child creation writes optional age %s and nothing else', async age => {
    const fixture = await transportFixture(); const write = fixture.api.createChild('合成昵称', age); await tick();
    expect(JSON.parse(vi.mocked(fixture.wire).mock.calls[0][0].data!)).toEqual({ nickname: '合成昵称', ...(age === undefined ? {} : { age_band: age }) });
    fixture.send(201, { ...oldChild, age_band: age ?? null }); await write.promise;
  });
  it('child modification uses same age key; null explicitly clears it', async () => {
    const fixture = await transportFixture(); const write = fixture.api.updateChild(id, '修改昵称', null); await tick();
    expect(JSON.parse(vi.mocked(fixture.wire).mock.calls[0][0].data!)).toEqual({ nickname: '修改昵称', age_band: null });
    fixture.send(200, { ...oldChild, nickname: '修改昵称', age_band: null }); await write.promise;
  });
  it('public nickname save is PUT nickname only and never uses a family name', async () => {
    const fixture = await transportFixture(); const write = fixture.api.updateParentProfile('  合成家长  '); await tick();
    expect(vi.mocked(fixture.wire).mock.calls[0][0]).toMatchObject({ method: 'PUT', url: 'https://synthetic.test/api/v2/parent-profile', data: '{"nickname":"合成家长"}' });
    fixture.send(200, profile); expect(await write.promise).toEqual(profile);
  });
  it('route-specific validation rejects age on /me and private fields on parent-profile', async () => {
    const fixture = await transportFixture(); const transport = new CloudApiTransport('https://synthetic.test', fixture.auth, fixture.wire);
    expect(() => transport.request('PATCH', '/api/v2/me', value => value, { age_band: '6-8' })).toThrow();
    for (const key of ['display_name', 'age_band', 'ownerId', 'owner_user_id', 'openid', 'uid', 'child_profile_id', 'avatar']) {
      expect(() => transport.request('PUT', '/api/v2/parent-profile', value => value, { [key]: 'synthetic' })).toThrow();
    }
    expect(fixture.wire).not.toHaveBeenCalled();
  });
});
describe('PC02 family tools explicit entry and identity epochs', () => {
  it('capability and parent reads stay explicitly loading and refuse saves despite overall ready', async () => {
    const { auth, api, store } = storeFixture(); const capability = deferred<{ child_age_band: boolean; parent_profile: boolean }>();
    const parent = deferred<ParentCommunityProfile | null>(); api.capabilities = vi.fn(() => capability.handle); api.parentProfile = vi.fn(() => parent.handle);
    expect(store.getState().parentProfileStatus).toBe('idle');
    store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    expect(store.getState()).toMatchObject({ status: 'loading', parentProfile: null, parentProfileStatus: 'loading' });
    expect(await store.updateParentProfile('合成昵称')).toBe(false); expect(api.updateParentProfile).not.toHaveBeenCalled();
    capability.resolve({ child_age_band: true, parent_profile: true }); await tick();
    expect(store.getState()).toMatchObject({ parentProfileStatus: 'loading', capabilities: { parent_profile: true } });
    expect(await store.updateParentProfile('合成昵称')).toBe(false); expect(api.updateParentProfile).not.toHaveBeenCalled();
    parent.resolve(null); await tick(); expect(store.getState()).toMatchObject({ parentProfile: null, parentProfileStatus: 'ready' });
    expect(await store.updateParentProfile('合成昵称')).toBe(true); expect(api.updateParentProfile).toHaveBeenCalledOnce();
  });
  it('parent read failure remains unconfirmed until an explicit successful retry', async () => {
    const { auth, api, store } = storeFixture(); api.parentProfile = vi.fn(() => ({ promise: Promise.reject(new CloudError('offline')), cancel: vi.fn() }));
    store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    expect(store.getState()).toMatchObject({ parentProfile: null, parentProfileStatus: 'error' });
    expect(await store.updateParentProfile('合成昵称')).toBe(false); expect(api.updateParentProfile).not.toHaveBeenCalled();
    api.parentProfile = vi.fn(() => result(null)); await store.refresh();
    expect(store.getState()).toMatchObject({ parentProfile: null, parentProfileStatus: 'ready' });
    expect(await store.updateParentProfile('合成昵称')).toBe(true);
  });
  it('capability failure is an error rather than unavailable or an empty parent profile', async () => {
    const { auth, api, store } = storeFixture(); api.capabilities = vi.fn(() => ({ promise: Promise.reject(new CloudError('server')), cancel: vi.fn() }));
    store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    expect(store.getState()).toMatchObject({ parentProfileStatus: 'error', capabilities: null, parentProfile: null });
    expect(api.parentProfile).not.toHaveBeenCalled(); expect(await store.updateParentProfile('合成昵称')).toBe(false);
  });
  it('new account pending read cannot inherit ready or empty confirmation from old account', async () => {
    const { auth, api, store } = storeFixture(); const old = deferred<ParentCommunityProfile | null>(), next = deferred<ParentCommunityProfile | null>();
    api.parentProfile = vi.fn().mockReturnValueOnce(old.handle).mockReturnValueOnce(next.handle);
    store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    auth.setAccount('next-synthetic-account', 'next-synthetic-token'); await tick();
    expect(store.getState().parentProfileStatus).toBe('loading'); old.resolve(null); await tick();
    expect(store.getState()).toMatchObject({ parentProfile: null, parentProfileStatus: 'loading' });
    expect(await store.updateParentProfile('合成昵称')).toBe(false); next.resolve(profile); await tick();
    expect(store.getState()).toMatchObject({ parentProfile: profile, parentProfileStatus: 'ready' });
    await auth.signOut(); expect(store.getState()).toMatchObject({ parentProfile: null, parentProfileStatus: 'idle' });
  });
  it('atomic page scopes request once per private entry and never query family data on legacy/public routes', async () => {
    const { auth, api, store } = storeFixture(); await auth.signIn(); await tick();
    store.setPageScope(false, false); await tick(); expect(api.me).not.toHaveBeenCalled();
    store.setPageScope(true, true); await tick();
    expect(api.me).toHaveBeenCalledTimes(1); expect(api.children).toHaveBeenCalledTimes(1);
    expect(api.capabilities).toHaveBeenCalledTimes(1); expect(api.parentProfile).toHaveBeenCalledTimes(1);
    store.setPageScope(true, true); await tick(); expect(api.me).toHaveBeenCalledTimes(1);
    store.setPageScope(true, false); await tick();
    expect(api.me).toHaveBeenCalledTimes(2); expect(api.children).toHaveBeenCalledTimes(2);
    expect(api.capabilities).toHaveBeenCalledTimes(1); expect(api.parentProfile).toHaveBeenCalledTimes(1);
    store.setPageScope(false, false); await tick();
    expect(api.me).toHaveBeenCalledTimes(2); expect(store.getState()).toMatchObject({ parentProfile: null, parentProfileStatus: 'idle' });
    store.setPageScope(true, true); await tick();
    expect(api.me).toHaveBeenCalledTimes(3); expect(api.children).toHaveBeenCalledTimes(3);
    expect(api.capabilities).toHaveBeenCalledTimes(2); expect(api.parentProfile).toHaveBeenCalledTimes(2);
  });
  it('atomic scope transition cancels pending family reads without issuing a duplicate private refresh', async () => {
    const { auth, api, store } = storeFixture(); const old = deferred<{ child_age_band: boolean; parent_profile: boolean }>(); api.capabilities = vi.fn(() => old.handle);
    await auth.signIn(); store.setPageScope(true, true); await tick();
    const epoch = store.getState().epoch; store.setPageScope(true, false); await tick();
    expect(store.getState().epoch).toBe(epoch + 1); expect(old.handle.cancel).toHaveBeenCalled();
    expect(api.me).toHaveBeenCalledTimes(2); old.resolve({ child_age_band: true, parent_profile: true }); await tick();
    expect(api.parentProfile).not.toHaveBeenCalled(); expect(store.getState()).toMatchObject({ status: 'ready', parentProfileStatus: 'idle' });
  });
  it('a pending child create and its deferred capability refresh cannot send a duplicate POST', async () => {
    const { auth, api, store } = storeFixture(); await auth.signIn(); store.setPageScope(true, true); await tick();
    const first = deferred<ReturnType<CloudApi['createChild']> extends RequestHandle<infer T> ? T : never>(); api.createChild = vi.fn(() => first.handle);
    const saving = store.createProfile('合成孩子', '6-8'); await tick();
    expect(await store.createProfile('合成孩子', '6-8')).toBe(false); expect(api.createChild).toHaveBeenCalledTimes(1);
    const capability = deferred<{ child_age_band: boolean; parent_profile: boolean }>(); api.capabilities = vi.fn(() => capability.handle);
    first.resolve({ ...oldChild, status: 'active', age_band: '6-8' }); await tick();
    expect(store.getState().status).toBe('loading'); expect(await store.createProfile('合成孩子')).toBe(false); expect(api.createChild).toHaveBeenCalledTimes(1);
    capability.resolve({ child_age_band: true, parent_profile: true }); expect(await saving).toBe(true);
    expect(api.createChild).toHaveBeenCalledTimes(1); expect(store.getState().status).toBe('ready');
  });
  it('signed-in public routes read no private data or capabilities', async () => {
    const { auth, api, store } = storeFixture(); await auth.signIn(); await tick(); await store.refresh();
    for (const key of ['me', 'children', 'capabilities', 'parentProfile', 'updateParentProfile'] as const) expect(api[key]).not.toHaveBeenCalled();
    expect(store.getState()).toMatchObject({ capabilities: null, parentProfile: null });
  });
  it('regular private tools do not discover new family capabilities until explicit entry', async () => {
    const { auth, api, store } = storeFixture(); await auth.signIn(); store.setPrivateReadsEnabled(true); await tick();
    expect(api.me).toHaveBeenCalledOnce(); expect(api.capabilities).not.toHaveBeenCalled();
    store.setFamilyToolsEnabled(true); await tick();
    expect(api.capabilities).toHaveBeenCalledOnce(); expect(api.parentProfile).toHaveBeenCalledOnce();
    expect(store.getState()).toMatchObject({ parentProfile: profile, capabilities: { child_age_band: true, parent_profile: true } });
  });
  it('disabled server keeps nickname CRUD and never fetches or saves new profile', async () => {
    const { auth, api, store } = storeFixture(); api.capabilities = vi.fn(() => result({ child_age_band: false, parent_profile: false }));
    store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    expect(api.parentProfile).not.toHaveBeenCalled(); expect(await store.updateParentProfile('合成家长')).toBe(false);
    expect(store.getState().parentProfileStatus).toBe('unavailable');
    expect(await store.createProfile('合成昵称')).toBe(true); expect(api.createChild).toHaveBeenCalledWith('合成昵称', undefined);
    expect(await store.createProfile('合成昵称', '6-8')).toBe(false); expect(api.createChild).toHaveBeenCalledTimes(1);
  });
  it('failed writes return false and no success is fabricated', async () => {
    const { auth, api, store } = storeFixture(); store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    api.updateParentProfile = vi.fn(() => ({ promise: Promise.reject(new CloudError('offline')), cancel: vi.fn() }));
    expect(await store.updateParentProfile('修改家长')).toBe(false); expect(store.getState()).toMatchObject({ parentProfile: profile, status: 'offline' });
  });
  it('late previous-account parent read is revoked and never replaces the next account', async () => {
    const { auth, api, store } = storeFixture(); const old = deferred<ParentCommunityProfile | null>();
    api.parentProfile = vi.fn().mockReturnValueOnce(old.handle).mockReturnValue(result(null));
    store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    auth.setAccount('second-synthetic-parent', 'second-synthetic-token'); expect(store.getState().parentProfile).toBeNull(); await tick();
    expect(old.handle.cancel).toHaveBeenCalled(); old.resolve(profile); await tick();
    expect(store.getState().parentProfile).toBeNull(); expect(store.getState().auth.principal?.subject).toBe('second-synthetic-parent');
  });
  it('public navigation cancels capabilities and does not publish a late response', async () => {
    const { auth, api, store } = storeFixture(); const old = deferred<{ child_age_band: boolean; parent_profile: boolean }>(); api.capabilities = vi.fn(() => old.handle);
    store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    store.setPrivateReadsEnabled(false); expect(old.handle.cancel).toHaveBeenCalled(); old.resolve({ child_age_band: true, parent_profile: true }); await tick();
    expect(api.parentProfile).not.toHaveBeenCalled(); expect(store.getState().capabilities).toBeNull();
  });
  it('logout immediately clears both identities and late save returns false', async () => {
    const { auth, api, store } = storeFixture(); store.setFamilyToolsEnabled(true); store.setPrivateReadsEnabled(true); await auth.signIn(); await tick();
    const old = deferred<ParentCommunityProfile>(); api.updateParentProfile = vi.fn(() => old.handle); const save = store.updateParentProfile('合成家长'); await tick();
    await auth.signOut(); expect(store.getState()).toMatchObject({ parentProfile: null, capabilities: null, profiles: [], user: null });
    old.resolve(profile); expect(await save).toBe(false); expect(store.getState().parentProfile).toBeNull();
  });
});
