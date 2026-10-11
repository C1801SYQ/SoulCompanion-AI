import { afterEach, describe, expect, it, vi } from 'vitest';
import Taro from '@tarojs/taro';
import { FakeAuthAdapter } from '../src/cloud/auth/fake';
import type { RequestHandle } from '../src/services/types';
import { CommunityStore, createCommunityActionKey } from '../src/community/store';
import { CommunityError } from '../src/community/apiTypes';
import type { CommunityApi, CommunityPage, PublicPost } from '../src/community/apiTypes';
vi.mock('@tarojs/taro', () => ({ default: { getRandomValues: vi.fn() } }));
afterEach(() => { vi.unstubAllGlobals(); vi.mocked(Taro.getRandomValues).mockReset(); });
const id = '11111111-1111-4111-8111-111111111111', second = '22222222-2222-4222-8222-222222222222';
const at = '2026-10-11T00:00:00.000000Z';
const post: PublicPost = { id, title: '合成正文', body: '合成分享', age_band: '6-8', topic: 'parent-child', author: { id: second, nickname: '合成家长' }, created_at: at, updated_at: at, published_at: at };
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { handle: { promise, cancel: vi.fn() } as RequestHandle<T>, resolve, reject };
}
function fixture(mode: 'real' | 'demo' = 'real') {
  const requests: ReturnType<typeof deferred<CommunityPage<PublicPost>>>[] = [];
  const api = { listPosts: vi.fn(() => { const request = deferred<CommunityPage<PublicPost>>(); requests.push(request); return request.handle; }) } as unknown as CommunityApi;
  const auth = new FakeAuthAdapter(); let serial = 0;
  const keyFactory = vi.fn(async () => `synthetic-${++serial}`);
  return { auth, api, requests, keyFactory, store: new CommunityStore(mode, api, auth, keyFactory) };
}
const page = (items: PublicPost[] = [], cursor: string | null = null): CommunityPage<PublicPost> => ({ items, limit: 20, next_cursor: cursor });

describe('REAL/DEMO community store and request races', () => {
  it('DEMO feed and auth updates never invoke real API or fabricate real posts', async () => {
    const { store, api, auth } = fixture('demo'); await store.refreshFeed(); await auth.signIn(); await store.setFilters({ age: '6-8', topic: 'parent-child' });
    expect(api.listPosts).not.toHaveBeenCalled(); expect(store.getState()).toMatchObject({ mode: 'demo', feed: { items: [], status: 'ready' } }); store.dispose();
  });
  it('unconfigured REAL explicitly errors and does not fall back to examples', async () => {
    const store = new CommunityStore('real', null, null); await store.refreshFeed();
    expect(store.getState()).toMatchObject({ mode: 'real', feed: { items: [], status: 'error', error: { kind: 'not_configured' } } }); store.dispose();
  });
  it('real empty database and request failure are distinct and never get fake items', async () => {
    const { store, requests } = fixture(); const empty = store.refreshFeed(); requests[0].resolve(page()); await empty;
    expect(store.getState().feed).toMatchObject({ status: 'ready', items: [], error: null });
    const failure = store.refreshFeed(); requests[1].reject(new CommunityError('server', 503)); await failure;
    expect(store.getState().feed).toMatchObject({ status: 'error', items: [], error: { status: 503 } }); store.dispose();
  });
  it('changing both filters clears cursor/list synchronously and stale response cannot win', async () => {
    const { store, requests, api } = fixture(); const old = store.refreshFeed();
    const latest = store.setFilters({ age: '6-8', topic: 'parent-child' });
    expect(store.getState().feed).toMatchObject({ items: [], nextCursor: null, filters: { age: '6-8', topic: 'parent-child' }, status: 'loading' });
    expect(requests[0].handle.cancel).toHaveBeenCalledOnce(); requests[1].resolve(page([post], 'fresh_cursor')); await latest;
    requests[0].resolve(page([{ ...post, title: '旧筛选结果' }], 'old_cursor')); await old;
    expect(store.getState().feed.items[0].title).toBe(post.title); expect(store.getState().feed.nextCursor).toBe('fresh_cursor');
    expect(api.listPosts).toHaveBeenLastCalledWith({ age: '6-8', topic: 'parent-child' }, { limit: 20 }); store.dispose();
  });
  it('double load-more starts one request and appends only new IDs', async () => {
    const { store, requests, api } = fixture(); const first = store.refreshFeed(); requests[0].resolve(page([post], 'next_cursor')); await first;
    const more = store.loadMore(), duplicate = store.loadMore(); await duplicate; expect(api.listPosts).toHaveBeenCalledTimes(2);
    requests[1].resolve(page([post, { ...post, id: second }], null)); await more;
    expect(store.getState().feed.items.map(item => item.id)).toEqual([id, second]); expect(store.getState().feed.loadingMore).toBe(false); store.dispose();
  });
  it('refresh during pagination cannot reappend the old page', async () => {
    const { store, requests } = fixture(); const first = store.refreshFeed(); requests[0].resolve(page([post], 'next_cursor')); await first;
    const more = store.loadMore(), fresh = store.refreshFeed(); requests[2].resolve(page()); await fresh;
    requests[1].resolve(page([{ ...post, id: second }])); await more;
    expect(store.getState().feed).toMatchObject({ items: [], nextCursor: null, loadingMore: false, status: 'ready' }); store.dispose();
  });
  it('pagination failure preserves valid current list and repeats the same cursor only on explicit retry', async () => {
    const { store, requests, api } = fixture(); const first = store.refreshFeed(); requests[0].resolve(page([post], 'next_cursor')); await first;
    const more = store.loadMore(); requests[1].reject(new CommunityError('offline')); await more;
    expect(store.getState().feed).toMatchObject({ items: [post], nextCursor: 'next_cursor', loadingMore: false, error: { kind: 'offline' } });
    const retry = store.loadMore(); expect(api.listPosts).toHaveBeenLastCalledWith({ age: 'all', topic: 'all' }, { limit: 20, cursor: 'next_cursor' }); requests[2].resolve(page()); await retry; store.dispose();
  });
  it('nonadvancing cursor fails explicitly rather than making an infinite load-more loop', async () => {
    const { store, requests } = fixture(); const first = store.refreshFeed(); requests[0].resolve(page([post], 'cursor')); await first;
    const more = store.loadMore(); requests[1].resolve(page([], 'cursor')); await more;
    expect(store.getState().feed.error?.kind).toBe('invalid'); expect(store.getState().feed.items).toEqual([post]); store.dispose();
  });
  it('bounds feed memory and explicitly records truncation after 200 records', async () => {
    const { store, requests } = fixture();
    const makePage = (start: number) => page(Array.from({ length: 20 }, (_, i) => ({ ...post, id: `${String(start + i).padStart(8, '0')}-1111-4111-8111-111111111111` })), `cursor_${start}`);
    const first = store.refreshFeed(); requests[0].resolve(makePage(0)); await first;
    for (let index = 1; index < 10; index++) { const more = store.loadMore(); requests[index].resolve(makePage(index * 20)); await more; }
    expect(store.getState().feed).toMatchObject({ truncated: true, nextCursor: null }); expect(store.getState().feed.items).toHaveLength(200);
    await store.loadMore(); expect(requests).toHaveLength(10); store.dispose();
  });
  it('account change synchronously clears state and cancels old owner/ops promises', async () => {
    const { store, auth, requests } = fixture(); await auth.signIn(); const first = store.refreshFeed(); requests[0].resolve(page([post])); await first;
    const snapshot = store.capture(), privateRequest = deferred<string>(), operation = store.run(privateRequest.handle, { private: true, key: 'owner-content' });
    auth.setAccount('new-synthetic-parent', 'new-synthetic-token');
    expect(privateRequest.handle.cancel).toHaveBeenCalledOnce(); expect(store.isCurrent(snapshot)).toBe(false); expect(store.getState().feed.items).toEqual([]);
    privateRequest.resolve('old-private-content'); await expect(operation).rejects.toMatchObject({ kind: 'cancelled' }); store.dispose();
  });
  it('latest named request slot rejects a late older success', async () => {
    const { store, auth } = fixture(); await auth.signIn(); const a = deferred<string>(), b = deferred<string>();
    const first = store.run(a.handle, { private: true, key: 'ops-detail' }), latest = store.run(b.handle, { private: true, key: 'ops-detail' });
    b.resolve('latest'); await expect(latest).resolves.toBe('latest'); a.resolve('old'); await expect(first).rejects.toMatchObject({ kind: 'cancelled' }); store.dispose();
  });
  it('dispose cancels requests without disposing the shared authentication adapter', async () => {
    const { store, auth } = fixture(); auth.dispose = vi.fn(); const request = deferred<string>(), operation = store.run(request.handle); store.dispose();
    expect(request.handle.cancel).toHaveBeenCalledOnce(); expect(auth.dispose).not.toHaveBeenCalled(); request.resolve('late'); await expect(operation).rejects.toMatchObject({ kind: 'cancelled' });
  });
  it('DEMO and anonymous private run reject immediately even if a fake handle ignores cancellation', async () => {
    const demo = fixture('demo'), anonymous = fixture(), a = deferred<string>(), b = deferred<string>();
    await expect(demo.store.run(a.handle)).rejects.toMatchObject({ kind: 'cancelled' });
    await expect(anonymous.store.run(b.handle, { private: true })).rejects.toMatchObject({ kind: 'unauthorized' });
    expect(a.handle.cancel).toHaveBeenCalledOnce(); expect(b.handle.cancel).toHaveBeenCalledOnce(); demo.store.dispose(); anonymous.store.dispose();
  });
  it('bounds concurrent requests without waiting for an ignored cancellation', async () => {
    const { store } = fixture(); const requests = Array.from({ length: 32 }, () => deferred<string>());
    const operations = requests.map(request => store.run(request.handle)); const excessive = deferred<string>();
    await expect(store.run(excessive.handle)).rejects.toMatchObject({ kind: 'rate_limited' }); expect(excessive.handle.cancel).toHaveBeenCalledOnce();
    requests.forEach(request => request.resolve('synthetic')); await Promise.all(operations); store.dispose();
  });
});

describe('memory-only immutable logical-action identity', () => {
  it('same scope/input coalesces concurrent key creation and survives an uncertain write', async () => {
    const { store, auth, keyFactory } = fixture(); await auth.signIn(); const input = { title: '合成投稿', nested: { body: '合成正文' } };
    const [a, b] = await Promise.all([store.action('create-post', input), store.action('create-post', input)]);
    expect(a).toBe(b); expect(keyFactory).toHaveBeenCalledOnce(); expect(Object.isFrozen(a.input)).toBe(true); expect(Object.isFrozen(a.input.nested)).toBe(true);
    const request = deferred<unknown>(), write = store.run(request.handle, { private: true }); request.reject(new CommunityError('server', 503)); await expect(write).rejects.toMatchObject({ status: 503 });
    expect((await store.action('create-post', input)).key).toBe(a.key); input.title = '外部修改'; expect(a.input.title).toBe('合成投稿'); store.dispose();
  });
  it('changed input or explicitly cleared action creates a new key', async () => {
    const { store, auth } = fixture(); await auth.signIn(); const a = await store.action('create-post', { body: '合成一' }), b = await store.action('create-post', { body: '合成二' });
    expect(a.key).not.toBe(b.key); store.clearAction('create-post'); const c = await store.action('create-post', { body: '合成二' }); expect(c.key).not.toBe(b.key); store.dispose();
  });
  it('sign-out/new account destroys old action keys and rejects pending key acquisition', async () => {
    const auth = new FakeAuthAdapter(); await auth.signIn(); const random = deferred<string>();
    const store = new CommunityStore('real', null, auth, () => random.handle.promise);
    const pending = store.action('create-post', { body: '合成旧稿' }); await tick(); auth.setAccount('new-synthetic-parent', 'new-synthetic-token'); random.resolve('old-action-key');
    await expect(pending).rejects.toMatchObject({ kind: 'cancelled' }); await auth.signOut(); await expect(store.action('create-post', {})).rejects.toMatchObject({ kind: 'unauthorized' }); store.dispose();
  });
  it('rejects unbounded action memory instead of silently replacing uncertain actions', async () => {
    const { store, auth } = fixture(); await auth.signIn();
    for (let index = 0; index < 24; index++) await store.action(`action-${index}`, { index });
    await expect(store.action('action-25', {})).rejects.toMatchObject({ kind: 'rate_limited' });
    store.clearAction('action-0'); await expect(store.action('action-25', {})).resolves.toHaveProperty('key'); store.dispose();
  });
  it('cryptographic keys have a bounded safe format and differ across actions', async () => {
    const first = await createCommunityActionKey(), secondKey = await createCommunityActionKey();
    expect(first).toMatch(/^pc04-[0-9a-f]{32}$/); expect(first).not.toBe(secondKey);
  });
  it('uses the native Taro cryptographic API without requiring browser crypto', async () => {
    vi.stubGlobal('crypto', undefined); const bytes = new Uint8Array(16); bytes.fill(7);
    vi.mocked(Taro.getRandomValues).mockResolvedValue({ randomValues: bytes.buffer, errMsg: 'synthetic' });
    expect(await createCommunityActionKey()).toBe(`pc04-${'07'.repeat(16)}`);
    expect(Taro.getRandomValues).toHaveBeenCalledWith({ length: 16 });
  });
  it('native random failure never falls back to a predictable clock or Math.random key', async () => {
    vi.stubGlobal('crypto', undefined); vi.mocked(Taro.getRandomValues).mockRejectedValue(new Error('synthetic-private-error'));
    await expect(createCommunityActionKey()).rejects.toMatchObject({ kind: 'invalid' });
    vi.mocked(Taro.getRandomValues).mockResolvedValue({ randomValues: new ArrayBuffer(1), errMsg: 'synthetic' });
    await expect(createCommunityActionKey()).rejects.toMatchObject({ kind: 'invalid' });
  });
});
