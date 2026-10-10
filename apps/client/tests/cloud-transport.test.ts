import { afterEach, describe, expect, it, vi } from 'vitest';
import { CloudApiTransport, type CloudWire, type CloudWireResponse } from '../src/cloud/transport';
import { FakeAuthAdapter } from '../src/cloud/auth/fake';
import { createCloudApi } from '../src/cloud/api';
import * as parse from '../src/cloud/validation';
vi.mock('@tarojs/taro', () => ({ default: { request: vi.fn() } }));
const id = '11111111-1111-4111-8111-111111111111';
const created = '2026-10-07T01:00:00+00:00';
const child = { id, nickname: 'Synthetic profile', age_band: null, status: 'active', created_at: created, updated_at: created };
const tick = async () => { for (let index = 0; index < 6; index++) await Promise.resolve(); };
function wire() { let respond!: (response: CloudWireResponse) => void; const abort = vi.fn(); const request: CloudWire = vi.fn((_, success) => { respond = success; return { abort }; }); return { request, abort, send: (status: number, data: unknown, headers: Record<string, unknown> = { 'content-type': 'application/json' }) => respond({ status, data: JSON.stringify(data), headers }) }; }
async function setup(timeoutMs = 8000) { const auth = new FakeAuthAdapter(); await auth.signIn(); const mock = wire(); const transport = new CloudApiTransport('https://synthetic.test', auth, mock.request, timeoutMs); return { auth, mock, transport }; }
afterEach(() => vi.useRealTimers());
describe('bounded authenticated API v2 transport', () => {
  it('adds only CORS-allowed auth/content-type headers; profile request contains only nickname', async () => {
    const { mock, transport } = await setup(); const handle = createCloudApi(transport).createChild('Synthetic profile'); await tick();
    const request = vi.mocked(mock.request).mock.calls[0][0]; expect(request.headers).toEqual({ Authorization: 'Bearer synthetic-test-token', 'Content-Type': 'application/json' });
    expect(JSON.parse(request.data!)).toEqual({ nickname: 'Synthetic profile' }); expect(request.url).toBe('https://synthetic.test/api/v2/children');
    mock.send(201, child); expect(await handle.promise).toEqual(child);
  });
  it('anonymous request sends no wire request', async () => {
    const { auth, mock, transport } = await setup(); await auth.signOut(); const handle = transport.request('GET', '/api/v2/me', value => value);
    await expect(handle.promise).rejects.toMatchObject({ kind: 'unauthorized' }); expect(mock.request).not.toHaveBeenCalled();
  });
  it.each([[401, 'unauthorized'], [403, 'forbidden'], [429, 'rate_limited'], [500, 'server'], [503, 'server'], [422, 'invalid']] as const)('normalizes %s to %s without reflecting arbitrary error details', async (status, kind) => {
    const { auth, mock, transport } = await setup(); const handle = transport.request('GET', '/api/v2/me', value => value); await tick();
    mock.send(status, { error: { message: 'synthetic-private-token' } }, { 'content-type': 'application/json', 'x-request-id': 'synthetic-request', 'retry-after': '2' });
    await expect(handle.promise).rejects.toMatchObject({ kind, requestId: 'synthetic-request' }); if (status === 401) expect(auth.getState().status).toBe('expired'); else expect(auth.getState().status).toBe('signed_in');
  });
  it('rejects late response from old account without clearing new identity', async () => {
    const { auth, mock, transport } = await setup(); const handle = transport.request('GET', '/api/v2/me', value => value); await tick(); auth.setAccount('other-synthetic-user', 'other-synthetic-token'); mock.send(401, {});
    await expect(handle.promise).rejects.toMatchObject({ kind: 'cancelled' }); expect(auth.getPrincipal()?.subject).toBe('other-synthetic-user');
  });
  it('cancellation aborts wire and prevents late response', async () => {
    const { mock, transport } = await setup(); const handle = transport.request('GET', '/api/v2/me', value => value); await tick(); handle.cancel();
    await expect(handle.promise).rejects.toMatchObject({ kind: 'cancelled' }); expect(mock.abort).toHaveBeenCalledOnce(); mock.send(200, {});
  });
  it('total deadline includes a stalled token acquisition, and sends nothing after timeout', async () => {
    vi.useFakeTimers(); const { auth, mock, transport } = await setup(20); let resolve!: (token: string) => void;
    auth.getAccessToken = () => new Promise(done => { resolve = done; }); const handle = transport.request('GET', '/api/v2/me', value => value);
    const failure = expect(handle.promise).rejects.toMatchObject({ kind: 'offline' }); await vi.advanceTimersByTimeAsync(21); await failure; resolve('synthetic-token'); await tick(); expect(mock.request).not.toHaveBeenCalled();
  });
  it('rejects response size and non-JSON content type', async () => {
    const { mock, transport } = await setup(); const large = transport.request('GET', '/api/v2/me', value => value); await tick(); mock.send(200, 'x'.repeat(512001)); await expect(large.promise).rejects.toMatchObject({ kind: 'invalid' });
    const html = transport.request('GET', '/api/v2/me', value => value); await tick(); mock.send(200, {}, { 'content-type': 'text/html' }); await expect(html.promise).rejects.toMatchObject({ kind: 'invalid' });
  });
  it.each(['/api/v2/media/upload', '/api/v2/children/../admin', '/api/v2/me#fragment', 'https://different.test/api/v2/me'])('refuses non-product route %s', async path => { const { transport } = await setup(); expect(() => transport.request('POST', path, value => value)).toThrow(); });
  it('refuses arbitrary owner, principal, media and device fields', async () => {
    const { transport } = await setup(); for (const key of ['owner_user_id', 'openid', 'uid', 'video', 'audio', 'cameraDeviceId']) expect(() => transport.request('POST', '/api/v2/sessions', value => value, { [key]: 'synthetic' })).toThrow();
  });
  it('handles idempotent profile archive 204 without inventing response data', async () => { const { mock, transport } = await setup(); const archive = createCloudApi(transport).archiveChild(id); await tick(); mock.send(204, null, {}); expect(await archive.promise).toBeUndefined(); });
});
describe('strict private cloud response contracts', () => {
  it('validates owned profile and strips unexpected owner/principal fields', () => { expect(parse.child({ ...child, owner_user_id: 'synthetic-private-owner', openid: 'synthetic-private-openid' })).toEqual(child); });
  it.each(['', 'not-a-uuid', '../', '11111111-1111-1111-1111-111111111111'])('rejects malformed ID %s', value => expect(() => parse.cloudId(value)).toThrow());
  it('validates page bounds and explicit empty current report', () => { expect(parse.page(parse.child)({ items: [], limit: 100, offset: 0, total: 0 }).items).toEqual([]); expect(parse.currentReport({ status: 'empty', report: null })).toBeNull(); expect(() => parse.page(parse.child)({ items: [child], limit: 0, offset: 0, total: 1 })).toThrow(); });
  it('requires server timestamps and matching ended-session state', () => { const session = { id, child_profile_id: id, source_platform: 'web', started_at: created, ended_at: null, status: 'active', created_at: created }; expect(parse.session(session)).toEqual(session); expect(() => parse.session({ ...session, status: 'ended' })).toThrow(); expect(() => parse.session({ ...session, started_at: '2026-10-07' })).toThrow(); });
  it('validates nickname and refuses inference-like extra write fields through transport', () => { expect(parse.nickname('  Synthetic  ')).toBe('Synthetic'); expect(() => parse.nickname('x'.repeat(65))).toThrow(); expect(() => parse.nickname('\n')).toThrow(); });
});
