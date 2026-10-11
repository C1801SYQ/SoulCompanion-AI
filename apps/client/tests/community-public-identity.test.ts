import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ReactElement, type ReactNode } from 'react';
import type { CloudState } from '../src/cloud/store';
import type { ParentCommunityProfile } from '../src/cloud/types';
import type { RequestHandle } from '../src/services/types';

const mock = vi.hoisted(() => ({
  state: undefined as unknown as CloudState, slots: [] as unknown[], cursor: 0, effects: [] as Array<() => void>, shown: [] as Array<() => void>,
  parentProfile: vi.fn(), updateParentProfile: vi.fn(), signIn: vi.fn(), signOut: vi.fn(), run: vi.fn(),
}));
vi.mock('react', async () => {
  const real = await vi.importActual<typeof import('react')>('react');
  return { ...real,
    useState: (initial: unknown) => { const index = mock.cursor++; if (!(index in mock.slots)) mock.slots[index] = typeof initial === 'function' ? initial() : initial; return [mock.slots[index], (value: unknown) => { mock.slots[index] = typeof value === 'function' ? value(mock.slots[index]) : value; }]; },
    useRef: (initial: unknown) => { const index = mock.cursor++; if (!(index in mock.slots)) mock.slots[index] = { current: initial }; return mock.slots[index]; },
    useId: () => { const index = mock.cursor++; if (!(index in mock.slots)) mock.slots[index] = `synthetic-owner-${index}`; return mock.slots[index]; },
    useEffect: (effect: () => void, dependencies: unknown[]) => { const index = mock.cursor++; const old = mock.slots[index] as unknown[] | undefined; if (!old || dependencies.some((value, i) => value !== old[i])) { mock.slots[index] = dependencies; mock.effects.push(effect); } },
  };
});
vi.mock('@tarojs/taro', () => ({ default: {}, useDidShow: (callback: () => void) => { mock.shown.push(callback); } }));
vi.mock('@tarojs/components', () => ({ Input: 'input', Text: 'span', View: 'div' }));
vi.mock('../src/components/AccessibleButton', () => ({ AccessibleButton: 'button' }));
vi.mock('../src/components/Primitives', () => ({ EmptyState: 'empty-state', SectionCard: 'section', StatusPill: 'status-pill' }));
vi.mock('../src/platform/keyboard', () => ({ textInputKeyboardProps: {}, dismissKeyboard: vi.fn().mockResolvedValue(undefined) }));
vi.mock('../src/cloud/auth/platform', () => ({ cloudSourcePlatform: 'web' }));
vi.mock('../src/state/CloudProvider', () => ({ useCloud: () => ({ state: mock.state, store: publicStore() }) }));
vi.mock('../src/state/CommunityProvider', () => ({ useCommunity: () => ({ state: { mode: 'real', authEpoch: mock.state.auth.epoch }, store: { getState: () => ({ mode: 'real', authEpoch: mock.state.auth.epoch }), run: mock.run } }) }));

import { CommunityAccountPanel, useCommunityIdentity, type CommunityIdentity } from '../src/community/AccountPanel';
import { CommunityError } from '../src/community/apiTypes';

const forbidden = () => { throw new Error('Community identity accessed private family data'); };
function publicStore() {
  const api = { parentProfile: mock.parentProfile, updateParentProfile: mock.updateParentProfile };
  for (const key of ['profiles', 'user', 'sessions', 'reports', 'emotions']) Object.defineProperty(api, key, { get: forbidden });
  const store = { getState: () => mock.state, api, signIn: mock.signIn, signOut: mock.signOut };
  for (const key of ['refresh', 'updateProfile', 'selectProfile', 'createProfile', 'updateParentProfile']) Object.defineProperty(store, key, { get: forbidden });
  return store;
}
function setState(epoch = 1, signedIn = true) {
  const auth = { status: signedIn ? 'signed_in' : 'signed_out', epoch, message: '' };
  Object.defineProperty(auth, 'principal', { get: forbidden });
  const state = { enabled: true, auth };
  for (const key of ['user', 'profiles', 'selectedId', 'sessions', 'emotions', 'reports', 'parentProfile']) Object.defineProperty(state, key, { get: forbidden });
  mock.state = state as CloudState;
}
type Element = ReactElement<{ id?: string; value?: string; children?: ReactNode; disabled?: boolean; onInput?: (event: { detail: { value: string } }) => void; onClick?: () => void }>;
function render(page: () => ReactElement, effects = true) { mock.cursor = 0; mock.effects = []; mock.shown = []; const tree = page(); if (effects) for (const effect of mock.effects) effect(); return tree; }
function find(node: ReactNode, id: string): Element | null {
  if (Array.isArray(node)) { for (const child of node) { const found = find(child, id); if (found) return found; } return null; }
  if (!node || typeof node !== 'object' || !('props' in node)) return null;
  const element = node as Element; return element.props.id === id ? element : find(element.props.children, id);
}
function request<T>(value: T): RequestHandle<T> { return { promise: Promise.resolve(value), cancel: vi.fn() }; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { handle: { promise, cancel: vi.fn() }, resolve }; }
const tick = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const profile: ParentCommunityProfile = { id: '11111111-1111-4111-8111-111111111111', nickname: '合成公开家长', created_at: '', updated_at: '' };
let identity: CommunityIdentity;
const identityPage = () => { identity = useCommunityIdentity(); return createElement('div'); };
beforeEach(() => {
  vi.clearAllMocks(); mock.slots = []; mock.cursor = 0; mock.effects = []; mock.shown = []; setState();
  mock.parentProfile.mockReturnValue(request(profile)); mock.updateParentProfile.mockImplementation((nickname: string) => request({ ...profile, nickname }));
  mock.run.mockImplementation((handle: RequestHandle<unknown>) => handle.promise); mock.signIn.mockResolvedValue(undefined); mock.signOut.mockResolvedValue(undefined);
});

describe('REAL community public identity boundaries', () => {
  it('reads only the public profile through safe private run and never prefills child/old nickname text', async () => {
    render(identityPage); await tick(); render(identityPage);
    expect(identity.status).toBe('ready'); expect(identity.profile?.nickname).toBe(profile.nickname); expect(identity.draft).toBe('');
    expect(mock.parentProfile).toHaveBeenCalledOnce(); expect(mock.run).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ private: true }));
    expect(mock.updateParentProfile).not.toHaveBeenCalled();
  });
  it('two cached identity panels keep independent request slots across login and page return', async () => {
    let left!: CommunityIdentity, right!: CommunityIdentity;
    const page = () => { left = useCommunityIdentity(); right = useCommunityIdentity(); return createElement('div'); };
    // Match the core's same-slot latest-wins cancellation instead of pretending concurrent reads cannot cancel.
    const pendingSlots = new Map<string, { reject: (error: Error) => void }>();
    mock.run.mockImplementation((handle: RequestHandle<unknown>, options: { key: string }) => new Promise((resolve, reject) => {
      pendingSlots.get(options.key)?.reject(new CommunityError('cancelled'));
      const request = { reject }; pendingSlots.set(options.key, request);
      handle.promise.then(value => { if (pendingSlots.get(options.key) === request) resolve(value); }, reject);
    }));
    const oldLeft = deferred<ParentCommunityProfile>(), oldRight = deferred<ParentCommunityProfile>();
    const newLeft = deferred<ParentCommunityProfile>(), newRight = deferred<ParentCommunityProfile>();
    mock.parentProfile.mockReturnValueOnce(oldLeft.handle).mockReturnValueOnce(oldRight.handle).mockReturnValueOnce(newLeft.handle).mockReturnValueOnce(newRight.handle);
    render(page); render(page); expect(left.status).toBe('loading'); expect(right.status).toBe('loading');
    expect(mock.run.mock.calls[0][1].key).not.toBe(mock.run.mock.calls[1][1].key);
    setState(2); render(page, false); expect(left.profile).toBeNull(); expect(right.profile).toBeNull();
    // Run the queued new-account effects, then complete old requests after new ones have started.
    for (const effect of mock.effects) effect(); oldLeft.resolve(profile); oldRight.resolve(profile); await tick();
    newLeft.resolve({ ...profile, nickname: '第二账户左侧合成昵称' }); newRight.resolve({ ...profile, nickname: '第二账户右侧合成昵称' }); await tick(); render(page);
    expect(left.status).toBe('ready'); expect(right.status).toBe('ready'); expect(left.profile?.nickname).toBe('第二账户左侧合成昵称'); expect(right.profile?.nickname).toBe('第二账户右侧合成昵称');
    const returning = deferred<ParentCommunityProfile>(); mock.parentProfile.mockReturnValueOnce(returning.handle);
    mock.shown[0](); render(page); expect(left.status).toBe('loading'); expect(right.status).toBe('ready');
    returning.resolve({ ...profile, nickname: '返回后重新核对的合成昵称' }); await tick(); render(page);
    expect(left.status).toBe('ready'); expect(left.profile?.nickname).toBe('返回后重新核对的合成昵称'); expect(right.status).toBe('ready');
  });
  it('a pending or failed public profile read cannot be presented as unset or saved', async () => {
    const pending = deferred<ParentCommunityProfile | null>(); mock.parentProfile.mockReturnValue(pending.handle);
    render(identityPage); render(identityPage); expect(identity.status).toBe('loading'); identity.setDraft('合成公开稿'); render(identityPage); await identity.save(); expect(mock.updateParentProfile).not.toHaveBeenCalled();
    // New read remains exact and does not infer absent nickname from an error.
    mock.parentProfile.mockReturnValue({ promise: Promise.reject(new CommunityError('server', 503)), cancel: vi.fn() });
    await identity.reload(); render(identityPage); expect(identity.status).toBe('error'); expect(identity.profile).toBeNull();
    await identity.save(); expect(mock.updateParentProfile).not.toHaveBeenCalled(); pending.resolve(null); await tick(); render(identityPage); expect(identity.status).toBe('error');
  });
  it('nickname validation blocks invalid input and confirmation occurs only after the cloud receipt', async () => {
    render(identityPage); await tick(); render(identityPage); identity.setDraft('<script>'); render(identityPage); await identity.save(); expect(mock.updateParentProfile).not.toHaveBeenCalled();
    identity.setDraft('主动合成家长'); render(identityPage); const pending = deferred<ParentCommunityProfile>(); mock.updateParentProfile.mockReturnValue(pending.handle);
    const operation = identity.save(); render(identityPage); expect(identity.saving).toBe(true); expect(identity.message).not.toContain('确认保存'); expect(identity.profile?.nickname).toBe(profile.nickname);
    pending.resolve({ ...profile, nickname: '主动合成家长' }); await operation; render(identityPage); expect(identity.draft).toBe(''); expect(identity.profile?.nickname).toBe('主动合成家长'); expect(identity.message).toContain('云端确认保存');
  });
  it('failed nickname save preserves typed input without inventing a saved cloud profile', async () => {
    render(identityPage); await tick(); render(identityPage); identity.setDraft('尚未确认合成稿'); render(identityPage);
    mock.updateParentProfile.mockReturnValue({ promise: Promise.reject(new CommunityError('server', 503)), cancel: vi.fn() }); await identity.save(); render(identityPage);
    expect(identity.draft).toBe('尚未确认合成稿'); expect(identity.profile?.nickname).toBe(profile.nickname); expect(identity.message).toContain('保存尚未确认');
  });
  it('account switch masks nickname, drafts and receipts on the first render before effects', async () => {
    render(identityPage); await tick(); render(identityPage); identity.setDraft('旧账号合成稿'); render(identityPage); setState(2);
    render(identityPage, false); expect(identity.draft).toBe(''); expect(identity.profile).toBeNull(); expect(identity.status).toBe('idle'); expect(identity.message).toBe('');
  });
  it('old save completion cannot unlock, clear or confirm a new-account pending nickname save', async () => {
    render(identityPage); await tick(); render(identityPage); identity.setDraft('第一账户合成稿'); render(identityPage);
    const old = deferred<ParentCommunityProfile>(), fresh = deferred<ParentCommunityProfile>(); mock.updateParentProfile.mockReturnValueOnce(old.handle).mockReturnValueOnce(fresh.handle);
    const first = identity.save(); setState(2); render(identityPage); await tick(); render(identityPage); identity.setDraft('第二账户合成稿'); render(identityPage);
    const second = identity.save(); old.resolve({ ...profile, nickname: '第一账户合成稿' }); await first; render(identityPage);
    expect(identity.saving).toBe(true); expect(identity.draft).toBe('第二账户合成稿'); await identity.save(); expect(mock.updateParentProfile).toHaveBeenCalledTimes(2);
    fresh.resolve({ ...profile, nickname: '第二账户合成稿' }); await second; render(identityPage); expect(identity.profile?.nickname).toBe('第二账户合成稿');
  });
  it('stale login handlers cannot reuse old username/password after an auth epoch change', () => {
    setState(1, false); const page = () => CommunityAccountPanel({}); render(page); let tree = render(page);
    find(tree, 'pc-community-username')!.props.onInput!({ detail: { value: 'synthetic-old-login' } }); find(tree, 'pc-community-password')!.props.onInput!({ detail: { value: 'synthetic-test-secret' } }); tree = render(page);
    setState(2, false); find(tree, 'pc-community-sign-in')!.props.onClick!(); expect(mock.signIn).not.toHaveBeenCalled(); tree = render(page, false);
    expect(find(tree, 'pc-community-username')!.props.value).toBe(''); expect(find(tree, 'pc-community-password')!.props.value).toBe('');
  });
});
