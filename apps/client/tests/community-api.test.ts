import { afterEach, describe, expect, it, vi } from 'vitest';
import { FakeAuthAdapter } from '../src/cloud/auth/fake';
import { CloudError } from '../src/cloud/types';
import type { CloudWire, CloudWireResponse } from '../src/cloud/transport';
import { CommunityTransport } from '../src/community/transport';
import { createCommunityApi } from '../src/community/api';
import { CommunityError } from '../src/community/apiTypes';
import * as parse from '../src/community/validation';
vi.mock('@tarojs/taro', () => ({ default: { request: vi.fn(), getRandomValues: vi.fn() } }));

const id = '11111111-1111-4111-8111-111111111111';
const second = '22222222-2222-4222-8222-222222222222';
const at = '2026-10-11T00:00:00.000000Z';
const publicPost = { id, title: '合成家长分享', body: '一段虚构的交流文字。', age_band: '6-8', topic: 'parent-child', author: { id: second, nickname: '合成家长' }, created_at: at, updated_at: at, published_at: at };
const ownedPost = { ...publicPost, published_at: null, status: 'pending', content_revision: 1 };
const comment = { id: second, post_id: id, body: '合成评论', author: publicPost.author, created_at: at, updated_at: at, published_at: at };
const ownedComment = { ...comment, published_at: null, status: 'pending', content_revision: 1 };
const audit = [{ action: 'create', target_revision: 1, reason: '', at, actor_id: 'private-actor', payload_hash: 'private-hash', action_id: id }];
const ops = { ...ownedPost, kind: 'post', row_version: 1, audit };
const report = { id: second, target_type: 'post', target_id: id, target_revision: 1, reason: 'privacy', detail: '', status: 'open', created_at: at, handled_at: null };
const tick = async () => { for (let index = 0; index < 8; index++) await Promise.resolve(); };
function wire() {
  const callbacks: ((response: CloudWireResponse) => void)[] = [], aborts: ReturnType<typeof vi.fn>[] = [];
  const request: CloudWire = vi.fn((_, respond) => { callbacks.push(respond); const abort = vi.fn(); aborts.push(abort); return { abort }; });
  return { request, aborts, send: (index: number, status: number, data: unknown, headers: Record<string, unknown> = { 'content-type': 'application/json' }) => callbacks[index]({ status, data: JSON.stringify(data), headers }) };
}
async function setup(signed = true, timeout = 8000) {
  const auth = new FakeAuthAdapter(); if (signed) await auth.signIn();
  const mock = wire(), transport = new CommunityTransport('https://synthetic.test', auth, mock.request, timeout);
  return { auth, mock, transport, api: createCommunityApi(transport) };
}
afterEach(() => vi.useRealTimers());

describe('strict community DTO projection and text contracts', () => {
  it('public post and author never retain identity or family fields', () => {
    expect(parse.publicPost({ ...publicPost, owner_id: 'private', audit, child_name: 'private', author: { ...publicPost.author, uid: 'private', email: 'private', openid: 'private' } })).toEqual(publicPost);
  });
  it('owner content is distinct from public visibility and requires revision/state consistency', () => {
    expect(parse.ownedPost(ownedPost)).toEqual(ownedPost);
    expect(() => parse.publicPost(ownedPost)).toThrow(CommunityError);
    expect(() => parse.ownedPost({ ...ownedPost, published_at: at })).toThrow(CommunityError);
    expect(() => parse.ownedComment({ ...ownedComment, content_revision: 0 })).toThrow(CommunityError);
  });
  it('operator audit keeps only safe review fields and action responses reflect current state', () => {
    const parsed = parse.opsContent(ops);
    expect(parsed.audit).toEqual([{ action: 'create', target_revision: 1, reason: '', at }]);
    expect(JSON.stringify(parsed)).not.toContain('private-');
    const result = parse.contentAction({ action_applied: true, action_id: id, action: 'approve', applied_revision: 1, applied_at: at,
      content: { ...ops, status: 'pending', content_revision: 2 } });
    expect(result.content.status).toBe('pending'); expect(result.applied_revision).toBe(1); expect(result).not.toHaveProperty('action_id');
  });
  it('owner feedback cannot retain operator identity or refer to an old revision', () => {
    const value = { target_type: 'post', target_id: id, content_revision: 1, status: 'rejected', feedback: { action: 'reject', reason: '合成审核说明', at, content_revision: 1, actor_id: 'private' } };
    expect(parse.feedback(value).feedback).toEqual({ action: 'reject', reason: '合成审核说明', at, content_revision: 1 });
    expect(() => parse.feedback({ ...value, content_revision: 2 })).toThrow();
  });
  it.each(['\u0000', '\u202e', '\ud800', '\r', '<script>bad</script>', 'javascript:bad', 'data:text/html,bad'])('rejects unsafe text before trim: %j', input => expect(() => parse.plainText(`${input}合成`, 80, { multiline: true })).toThrow());
  it('matches NFC, code point limits and native-safe UTF8 byte sizing', () => {
    expect(parse.plainText(' e\u0301\n合成 ', 80, { multiline: true })).toBe('é\n合成');
    expect(parse.plainText('😀'.repeat(80), 80)).toHaveLength(160);
    expect(parse.utf8Bytes('a中😀')).toBe(8);
    expect(() => parse.plainText('😀'.repeat(81), 80)).toThrow();
  });
  it.each(['2026-02-30T00:00:00.000000Z', '2026-10-11T24:00:00.000000Z', '2026-10-11T00:00:00Z', '2026-10-11T00:00:00.000000+00:00'])('rejects noncanonical or invalid timestamp %s', value => expect(() => parse.timestamp(value)).toThrow());
  it('enforces server list bounds, cursor shape and duplicate IDs', () => {
    expect(parse.page(parse.publicPost)({ items: [], limit: 20, next_cursor: 'abc_def-123' })).toEqual({ items: [], limit: 20, next_cursor: 'abc_def-123' });
    expect(() => parse.page(parse.publicPost)({ items: [publicPost, publicPost], limit: 20, next_cursor: null })).toThrow();
    expect(() => parse.page(parse.publicPost)({ items: [], limit: 51, next_cursor: null })).toThrow();
    expect(() => parse.cursor('abc=')).toThrow();
  });
  it('requires other-report detail, exact enums and positive numeric revisions', () => {
    expect(() => parse.reportInput({ target_type: 'post', target_id: id, reason: 'other', detail: '' })).toThrow();
    expect(() => parse.postInput({ ...publicPost, age_band: 'all' })).toThrow();
    expect(() => parse.revision(true)).toThrow(); expect(() => parse.revision('1')).toThrow();
    expect(() => parse.relations({ post_id: id, liked: 'false', bookmarked: false })).toThrow();
  });
});

describe('community route and transport safety', () => {
  it('anonymous public GET obtains no token and sends no authorization', async () => {
    const { auth, api, mock } = await setup(false); auth.getAccessToken = vi.fn(auth.getAccessToken.bind(auth));
    const handle = api.listPosts({ age: 'all', topic: 'all' });
    expect(auth.getAccessToken).not.toHaveBeenCalled(); expect(mock.request).toHaveBeenCalledOnce();
    expect(vi.mocked(mock.request).mock.calls[0][0].headers).toEqual({ 'Content-Type': 'application/json' });
    mock.send(0, 200, { items: [], limit: 20, next_cursor: null }); expect((await handle.promise).items).toEqual([]);
  });
  it('signed-in public reading still sends zero credentials', async () => {
    const { auth, api, mock } = await setup(); auth.getAccessToken = vi.fn(auth.getAccessToken.bind(auth));
    const handle = api.post(id); mock.send(0, 200, publicPost); await handle.promise;
    expect(auth.getAccessToken).not.toHaveBeenCalled(); expect(vi.mocked(mock.request).mock.calls[0][0].headers).not.toHaveProperty('Authorization');
  });
  it('private writes require auth and reject unsafe ownership fields before wire', async () => {
    const { transport, mock, api } = await setup(false);
    const handle = api.createPost({ title: publicPost.title, body: publicPost.body, age_band: '6-8', topic: 'parent-child' }, 'synthetic-action');
    await expect(handle.promise).rejects.toMatchObject({ kind: 'unauthorized' }); expect(mock.request).not.toHaveBeenCalled();
    for (const key of ['owner_id', 'actor', 'role', 'uid', 'openid', 'child_profile_id', 'status', 'audio']) {
      expect(() => transport.request('POST', '/api/v2/community/posts', parse.ownedPost,
        { title: '合成', body: '合成正文', age_band: '6-8', topic: 'parent-child', [key]: 'private' }, 'synthetic-action')).toThrow();
    }
  });
  it.each([
    ['POST', '/api/v2/ops/roles'], ['GET', '/api/v2/children'], ['GET', '/api/v2/community/posts/../admin'],
    ['GET', '/api/v2/community/posts?age_band=all'], ['GET', '/api/v2/community/posts?limit=0'],
    ['GET', '/api/v2/community/posts?limit=20&limit=30'], ['GET', '/api/v2/community/posts?owner=private'],
    ['DELETE', `/api/v2/community/posts/${id}`], ['GET', '/api/v2/community/posts#bad'],
    ['GET', 'https://other.test/api/v2/community/posts'], ['PATCH', `/api/v2/community/comments/${id}`],
  ] as const)('rejects unsupported %s %s', async (method, path) => {
    const { transport } = await setup(); expect(() => transport.request(method, path, value => value)).toThrow(CommunityError);
  });
  it('old private 401 cannot expire a replacement account', async () => {
    const { auth, api, mock } = await setup(); const handle = api.myPosts(); await tick();
    auth.setAccount('new-synthetic-parent', 'new-synthetic-token'); mock.send(0, 401, { error: { code: 'unauthorized', message: 'private-secret' } });
    await expect(handle.promise).rejects.toMatchObject({ kind: 'cancelled' }); expect(auth.getState().status).toBe('signed_in'); expect(auth.getPrincipal()?.subject).toBe('new-synthetic-parent');
  });
  it('current private 401 expires auth without reflecting server messages', async () => {
    const { auth, api, mock } = await setup(); const handle = api.myPosts(); await tick();
    mock.send(0, 401, { error: { code: 'unauthorized', message: 'private-secret' } });
    await expect(handle.promise).rejects.toMatchObject({ kind: 'unauthorized', status: 401, serverCode: 'unauthorized' }); expect(auth.getState().status).toBe('expired');
  });
  it.each([[403, 'forbidden'], [404, 'not_found'], [409, 'conflict'], [413, 'too_large'], [422, 'invalid'], [429, 'rate_limited'], [503, 'server']] as const)('classifies %s and strips private server detail', async (status, kind) => {
    const { api, mock } = await setup(); const handle = api.myPosts(); await tick();
    mock.send(0, status, { error: { code: status === 409 ? 'parent_profile_required' : 'private-secret', message: 'private-secret' } }, { 'content-type': 'application/json', 'retry-after': '2' });
    try { await handle.promise; throw new Error('Expected failure'); } catch (error) {
      expect(error).toMatchObject({ kind, status }); expect(String(error)).not.toContain('private-secret');
      expect(JSON.stringify(error)).not.toContain('private-secret');
      if (status === 409) expect(error).toMatchObject({ serverCode: 'parent_profile_required' });
      if (status === 429) expect(error).toMatchObject({ retryAfterMs: 2000 });
    }
  });
  it('deadline covers token acquisition and prevents a late write', async () => {
    vi.useFakeTimers(); const { auth, api, mock } = await setup(true, 20); let resolve!: (token: string) => void;
    auth.getAccessToken = () => new Promise(done => { resolve = done; });
    const handle = api.myPosts(), failure = expect(handle.promise).rejects.toMatchObject({ kind: 'offline' });
    await vi.advanceTimersByTimeAsync(21); await failure; resolve('synthetic-test-token'); await tick(); expect(mock.request).not.toHaveBeenCalled();
  });
  it('token acquisition network failure stays offline without claiming identity rejection', async () => {
    const { auth, api, mock } = await setup();
    auth.getAccessToken = vi.fn(async () => { throw new CloudError('offline'); });
    const handle = api.myPosts();
    await expect(handle.promise).rejects.toMatchObject({ kind: 'offline', status: undefined });
    expect(mock.request).not.toHaveBeenCalled(); expect(auth.getState().status).toBe('signed_in');
  });
  it('real token acquisition identity rejection remains unauthorized and sends no request', async () => {
    const { auth, api, mock } = await setup();
    auth.getAccessToken = vi.fn(async () => { throw new CloudError('unauthorized'); });
    await expect(api.myPosts().promise).rejects.toMatchObject({ kind: 'unauthorized', status: 401 });
    expect(mock.request).not.toHaveBeenCalled();
  });
  it('late old-account token failure is cancelled before its failure kind is classified', async () => {
    const { auth, api, mock } = await setup(); let reject!: (error: CloudError) => void;
    auth.getAccessToken = () => new Promise((_, fail) => { reject = fail; });
    const handle = api.myPosts(); auth.setAccount('replacement-synthetic-parent', 'replacement-synthetic-token'); reject(new CloudError('offline'));
    await expect(handle.promise).rejects.toMatchObject({ kind: 'cancelled' });
    expect(mock.request).not.toHaveBeenCalled(); expect(auth.getPrincipal()?.subject).toBe('replacement-synthetic-parent'); expect(auth.getState().status).toBe('signed_in');
  });
  it('cancels requests and ignores successful late response', async () => {
    const { api, mock } = await setup(); const handle = api.post(id); handle.cancel();
    await expect(handle.promise).rejects.toMatchObject({ kind: 'cancelled' }); expect(mock.aborts[0]).toHaveBeenCalledOnce(); mock.send(0, 200, publicPost);
  });
  it('404 relations stays unavailable, never synthesizes false state', async () => {
    const { api, mock } = await setup(); const handle = api.relations(id); await tick(); mock.send(0, 404, { error: { code: 'not_found' } });
    await expect(handle.promise).rejects.toMatchObject({ kind: 'not_found', status: 404 });
  });
  it('rejects mismatched target response and non-JSON response', async () => {
    const { api, mock } = await setup(); const wrong = api.post(id); mock.send(0, 200, { ...publicPost, id: second }); await expect(wrong.promise).rejects.toMatchObject({ kind: 'invalid' });
    const html = api.post(id); mock.send(1, 200, publicPost, { 'content-type': 'text/html' }); await expect(html.promise).rejects.toMatchObject({ kind: 'invalid' });
  });
  it('uses canonical AND filter and opaque encoded cursor without all label', async () => {
    const { api, mock } = await setup(); const handle = api.listPosts({ age: '6-8', topic: 'parent-child' }, { cursor: 'abc_123', limit: 10 });
    expect(vi.mocked(mock.request).mock.calls[0][0].url).toBe('https://synthetic.test/api/v2/community/posts?age_band=6-8&topic=parent-child&limit=10&cursor=abc_123');
    mock.send(0, 200, { items: [], limit: 10, next_cursor: null }); await handle.promise;
  });
  it('refuses a public page that violates AND filters or stable newest-first order', async () => {
    const { api, mock } = await setup();
    const wrongAge = api.listPosts({ age: '9-12', topic: 'parent-child' });
    mock.send(0, 200, { items: [publicPost], limit: 20, next_cursor: null }); await expect(wrongAge.promise).rejects.toMatchObject({ kind: 'invalid' });
    const wrongOrder = api.listPosts({ age: 'all', topic: 'all' });
    mock.send(1, 200, { items: [publicPost, { ...publicPost, id: second }], limit: 20, next_cursor: null }); await expect(wrongOrder.promise).rejects.toMatchObject({ kind: 'invalid' });
  });
  it('accepts valid full-size Unicode input without the legacy transport 2048-character ceiling', async () => {
    const { api, mock } = await setup(); const body = '😀'.repeat(2000);
    const handle = api.createPost({ title: '合成投稿', body, age_band: '6-8', topic: 'parent-child' }, 'synthetic-key'); await tick();
    expect(JSON.parse(vi.mocked(mock.request).mock.calls[0][0].data!).body).toBe(body);
    mock.send(0, 201, { ...ownedPost, body }); await expect(handle.promise).resolves.toHaveProperty('body', body);
  });
  it('does not expire a signed-in account on a public GET 401', async () => {
    const { api, auth, mock } = await setup(); const handle = api.post(id);
    mock.send(0, 401, { error: { code: 'unauthorized' } }); await expect(handle.promise).rejects.toMatchObject({ kind: 'unauthorized' });
    expect(auth.getState().status).toBe('signed_in');
  });
  it('rejects a fake edit success retaining published state or the old revision', async () => {
    const { api, mock } = await setup(); const input = { title: '合成标题', body: '合成正文', age_band: '6-8', topic: 'parent-child' } as const;
    const handle = api.editPost(id, input, 1); await tick(); mock.send(0, 200, ownedPost);
    await expect(handle.promise).rejects.toMatchObject({ kind: 'invalid' });
    const published = api.editPost(id, input, 1); await tick(); mock.send(1, 200, { ...publicPost, status: 'published', content_revision: 2 });
    await expect(published.promise).rejects.toMatchObject({ kind: 'invalid' });
  });
  it('keeps the same create key/input on explicit retry after 503 and never automatically retries', async () => {
    const { api, mock } = await setup(); const input = { title: '合成投稿', body: '虚构合成正文', age_band: '6-8', topic: 'parent-child' } as const;
    const first = api.createPost(input, 'fixed-synthetic-key'); await tick(); mock.send(0, 503, { error: { code: 'service_unavailable' } }); await expect(first.promise).rejects.toMatchObject({ kind: 'server' });
    expect(mock.request).toHaveBeenCalledOnce(); const retry = api.createPost(input, 'fixed-synthetic-key'); await tick();
    expect(vi.mocked(mock.request).mock.calls[0][0]).toEqual(vi.mocked(mock.request).mock.calls[1][0]); mock.send(1, 200, ownedPost); expect((await retry.promise).status).toBe('pending');
  });
});

describe('all PC03 and compatible PC04 API mappings', () => {
  it('sends exact endpoint/method/body for owner, interaction and operator workflows', async () => {
    const { api, mock } = await setup();
    const input = { title: '合成投稿', body: '虚构合成正文', age_band: '6-8', topic: 'parent-child' } as const;
    const receipt = { action_applied: true, action_id: id, action: 'approve', applied_revision: 1, applied_at: at, content: ops };
    const opsReport = { ...report, row_version: 1, report_revision: 1, audit };
    const cases: [() => { promise: Promise<unknown> }, string, string, unknown][] = [
      [() => api.comments(id), 'GET', `/community/posts/${id}/comments`, { items: [comment], limit: 20, next_cursor: null }],
      [() => api.comment(second), 'GET', `/community/comments/${second}`, comment],
      [() => api.createComment(id, '合成评论', 'synthetic-key'), 'POST', `/community/posts/${id}/comments`, ownedComment],
      [() => api.editPost(id, input, 1), 'PATCH', `/community/posts/${id}`, { ...ownedPost, content_revision: 2 }],
      [() => api.withdrawPost(id, 1), 'DELETE', `/community/posts/${id}?expected_revision=1`, null],
      [() => api.withdrawComment(second, 1), 'DELETE', `/community/comments/${second}?expected_revision=1`, null],
      [() => api.myPosts(), 'GET', '/me/community/posts', { items: [ownedPost], limit: 20, next_cursor: null }],
      [() => api.myComments(), 'GET', '/me/community/comments', { items: [ownedComment], limit: 20, next_cursor: null }],
      [() => api.myContent('post', id), 'GET', `/me/community/posts/${id}`, ownedPost],
      [() => api.myContent('comment', second), 'GET', `/me/community/comments/${second}`, ownedComment],
      [() => api.bookmarks(), 'GET', '/me/community/bookmarks', { items: [publicPost], limit: 20, next_cursor: null }],
      [() => api.relations(id), 'GET', `/me/community/posts/${id}/relations`, { post_id: id, liked: false, bookmarked: true }],
      [() => api.feedback('post', id), 'GET', `/me/community/posts/${id}/feedback`, { target_type: 'post', target_id: id, status: 'pending', content_revision: 1, feedback: null }],
      [() => api.setLike(id, true), 'PUT', `/community/posts/${id}/like`, { post_id: id, kind: 'like', active: true }],
      [() => api.setLike(id, false), 'DELETE', `/community/posts/${id}/like`, { post_id: id, kind: 'like', active: false }],
      [() => api.setBookmark(id, true), 'PUT', `/community/posts/${id}/bookmark`, { post_id: id, kind: 'bookmark', active: true }],
      [() => api.setBookmark(id, false), 'DELETE', `/community/posts/${id}/bookmark`, { post_id: id, kind: 'bookmark', active: false }],
      [() => api.report({ target_type: 'post', target_id: id, reason: 'privacy' }, 'synthetic-key'), 'POST', '/community/content-reports', report],
      [() => api.opsQueue(), 'GET', '/ops/moderation?status=pending', { items: [ops], limit: 20, next_cursor: null }],
      [() => api.opsContent('post', id), 'GET', `/ops/moderation/posts/${id}`, ops],
      [() => api.moderate('post', id, 'approve', 1, '合成审核理由', 'synthetic-key'), 'POST', `/ops/moderation/posts/${id}/approve`, receipt],
      [() => api.moderate('post', id, 'reject', 1, '合成审核理由', 'synthetic-key'), 'POST', `/ops/moderation/posts/${id}/reject`, { ...receipt, action: 'reject' }],
      [() => api.moderate('post', id, 'hide', 1, '合成审核理由', 'synthetic-key'), 'POST', `/ops/moderation/posts/${id}/hide`, { ...receipt, action: 'hide' }],
      [() => api.opsReports(), 'GET', '/ops/content-reports?status=open', { items: [opsReport], limit: 20, next_cursor: null }],
      [() => api.resolveReport(second, 1, 'dismissed', '合成处理理由', 'synthetic-key'), 'POST', `/ops/content-reports/${second}/resolve`, { ...receipt, action: 'resolve', content: undefined, report: opsReport }],
    ];
    for (let index = 0; index < cases.length; index++) {
      const [invoke, method, suffix, result] = cases[index], handle = invoke(); await tick();
      const request = vi.mocked(mock.request).mock.calls[index][0]; expect(request.url).toBe(`https://synthetic.test/api/v2${suffix}`); expect(request.method).toBe(method);
      if (method === 'GET' && suffix.startsWith('/community/')) expect(request.headers).not.toHaveProperty('Authorization');
      else expect(request.headers.Authorization).toBe('Bearer synthetic-test-token');
      expect(request.headers).not.toHaveProperty('owner');
      if (method === 'DELETE') expect(request.data).toBeUndefined();
      mock.send(index, result === null ? 204 : 200, result); await handle.promise;
    }
  });
});
