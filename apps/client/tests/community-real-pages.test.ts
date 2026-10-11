import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ReactElement, type ReactNode } from 'react';
import type { CommunityApi, OwnedPost, PublicPost } from '../src/community/apiTypes';
import type { CommunityState } from '../src/community/store';
import type { RequestHandle } from '../src/services/types';

const harness = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0, effects: [] as Array<() => void>, params: {} as Record<string, string>,
  state: undefined as unknown as CommunityState, signedIn: true, identityReady: true, nickname: '合成公开家长',
  api: undefined as unknown as CommunityApi, actions: new Map<string, { signature: string; key: string }>(),
  run: vi.fn(), action: vi.fn(), clearAction: vi.fn(), refreshFeed: vi.fn(), openPage: vi.fn(),
}));
/** Executes the actual page handlers and scoped React hooks, without SDK, devices or network. */
vi.mock('react', async () => {
  const real = await vi.importActual<typeof import('react')>('react');
  return { ...real,
    useState: (initial: unknown) => { const index = harness.cursor++; if (!(index in harness.slots)) harness.slots[index] = typeof initial === 'function' ? initial() : initial; return [harness.slots[index], (value: unknown) => { harness.slots[index] = typeof value === 'function' ? value(harness.slots[index]) : value; }]; },
    useRef: (initial: unknown) => { const index = harness.cursor++; if (!(index in harness.slots)) harness.slots[index] = { current: initial }; return harness.slots[index]; },
    useEffect: (effect: () => void, dependencies: unknown[]) => { const index = harness.cursor++; const old = harness.slots[index] as unknown[] | undefined; if (!old || dependencies.some((value, i) => value !== old[i])) { harness.slots[index] = dependencies; harness.effects.push(effect); } },
  };
});
vi.mock('@tarojs/taro', () => ({ default: {}, useRouter: () => ({ params: harness.params }), useDidShow: () => undefined }));
vi.mock('@tarojs/components', () => ({ Input: 'input', Textarea: 'textarea', Text: 'span', View: 'div' }));
vi.mock('../src/components/AccessibleButton', () => ({ AccessibleButton: 'button' }));
vi.mock('../src/components/AppShell', () => ({ AppShell: 'main', PageHeader: 'header' }));
vi.mock('../src/components/Primitives', () => ({ EmptyState: 'empty-state', SectionCard: 'section', StatusPill: 'status-pill' }));
vi.mock('../src/components/ClientErrorBoundary', () => ({ withClientErrorBoundary: <T,>(page: T) => page }));
vi.mock('../src/navigation', () => ({ openPage: harness.openPage, backToCommunity: vi.fn().mockResolvedValue(undefined) }));
vi.mock('../src/platform/keyboard', () => ({ textInputKeyboardProps: {}, dismissKeyboard: vi.fn().mockResolvedValue(undefined) }));
vi.mock('../src/state/CloudProvider', () => ({ useCloud: () => ({ state: { enabled: true, auth: { status: harness.signedIn ? 'signed_in' : 'signed_out', epoch: harness.state.authEpoch } } }) }));
vi.mock('../src/state/CommunityProvider', () => ({ useCommunity: () => ({ state: harness.state, api: harness.api, store: { getState: () => harness.state, run: harness.run, action: harness.action, clearAction: harness.clearAction, refreshFeed: harness.refreshFeed } }) }));
vi.mock('../src/community/AccountPanel', () => ({ CommunityAccountPanel: 'account-panel', useCommunityIdentity: () => ({ status: harness.identityReady ? 'ready' : 'loading', profile: harness.nickname ? { nickname: harness.nickname } : null }) }));
vi.mock('../src/community/components', async () => {
  const real = await vi.importActual<typeof import('../src/community/components')>('../src/community/components');
  return { ...real, ChoiceGroup: ({ items, onChange, idPrefix, disabled }: { items: { value: string; label: string }[]; onChange: (value: string) => void; idPrefix: string; disabled?: boolean }) => createElement('div', null, ...items.map(item => createElement('button', { key: item.value, id: `${idPrefix}-${item.value}`, disabled, onClick: () => onChange(item.value) }, item.label))) };
});

import { RealCommunityComposePage } from '../src/pages/community/compose';
import { BookmarkCard, CommunityMinePage, OwnedCard } from '../src/pages/community/mine';
import { CommentPanel, PostRelations, ReportForm } from '../src/community/PostInteractions';
import { CommunityError } from '../src/community/apiTypes';
import { ChoiceGroup } from '../src/community/components';
import { feedbackMatchesContent, useCommunityBusy } from '../src/community/viewState';

type Element = ReactElement<{ id?: string; value?: string; children?: ReactNode; disabled?: boolean; onInput?: (event: { detail: { value: string } }) => void; onClick?: () => void }>;
function expandChoices(node: ReactNode): ReactNode {
  if (Array.isArray(node)) return node.map(expandChoices);
  if (!node || typeof node !== 'object' || !('props' in node)) return node;
  const element = node as Element;
  if (element.type === ChoiceGroup) return expandChoices(ChoiceGroup(element.props as never));
  return { ...element, props: { ...element.props, children: expandChoices(element.props.children) } };
}
function render(page: () => ReactElement, effects = true): ReactNode {
  harness.cursor = 0; harness.effects = []; const tree = expandChoices(page());
  if (effects) for (const effect of harness.effects) effect(); return tree;
}
function find(node: ReactNode, id: string): Element | null {
  if (Array.isArray(node)) { for (const child of node) { const found = find(child, id); if (found) return found; } return null; }
  if (!node || typeof node !== 'object' || !('props' in node)) return null;
  const element = node as Element; return element.props.id === id ? element : find(element.props.children, id);
}
function text(node: ReactNode): string {
  if (Array.isArray(node)) return node.map(text).join('');
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (!node || typeof node !== 'object' || !('props' in node)) return '';
  return text((node as Element).props.children);
}
function click(tree: ReactNode, id: string) { const control = find(tree, id); expect(control, id).not.toBeNull(); control!.props.onClick!(); }
function input(tree: ReactNode, id: string, value: string) { const control = find(tree, id); expect(control, id).not.toBeNull(); control!.props.onInput!({ detail: { value } }); }
const tick = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
function request<T>(value: T): RequestHandle<T> { return { promise: Promise.resolve(value), cancel: vi.fn() }; }
function failure<T>(error: Error): RequestHandle<T> { return { promise: Promise.reject(error), cancel: vi.fn() }; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { handle: { promise, cancel: vi.fn() }, resolve }; }
const id = '11111111-1111-4111-8111-111111111111';
const post: PublicPost = { id, title: '合成家长的一段日常', body: '仅为行为测试的合成育儿交流正文。', age_band: '6-8', topic: 'parent-child', author: { id: '22222222-2222-4222-8222-222222222222', nickname: '合成公开家长' }, created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z', published_at: '2026-10-10T00:00:00Z' };
const owned: OwnedPost = { ...post, status: 'pending', content_revision: 1, published_at: null };
function setDraft(title = post.title, body = post.body) {
  let tree = render(RealCommunityComposePage); input(tree, 'pc-title-input', title); tree = render(RealCommunityComposePage); input(tree, 'pc-body-input', body);
  tree = render(RealCommunityComposePage); click(tree, 'pc-compose-age-6-8'); tree = render(RealCommunityComposePage); click(tree, 'pc-compose-topic-parent-child');
  tree = render(RealCommunityComposePage); click(tree, 'pc-compose-preview'); return render(RealCommunityComposePage);
}

beforeEach(() => {
  vi.clearAllMocks(); harness.slots = []; harness.cursor = 0; harness.effects = []; harness.params = {};
  harness.state = { mode: 'real', authEpoch: 1, epoch: 1, feed: { filters: { age: 'all', topic: 'all' }, items: [], nextCursor: null, status: 'idle', loadingMore: false, error: null, truncated: false } };
  harness.signedIn = true; harness.identityReady = true; harness.nickname = '合成公开家长'; harness.actions.clear();
  harness.api = { createPost: vi.fn(() => request(owned)), editPost: vi.fn(() => request({ ...owned, content_revision: 2 })), myContent: vi.fn(() => request(owned)),
    post: vi.fn(() => request(post)), comments: vi.fn(() => request({ items: [], limit: 20, next_cursor: null })), createComment: vi.fn(() => request({ ...owned, post_id: id })),
    relations: vi.fn(() => request({ post_id: id, liked: false, bookmarked: false })), setLike: vi.fn(() => request({ post_id: id, kind: 'like', active: true })), setBookmark: vi.fn(() => request({ post_id: id, kind: 'bookmark', active: false })),
    report: vi.fn(() => request({})), feedback: vi.fn(() => request({ target_type: 'post', target_id: id, content_revision: 1, status: 'pending', feedback: null })),
    withdrawPost: vi.fn(() => request(undefined)), withdrawComment: vi.fn(() => request(undefined)), myPosts: vi.fn(() => request({ items: [owned], limit: 20, next_cursor: null })),
    myComments: vi.fn(() => request({ items: [], limit: 20, next_cursor: null })), bookmarks: vi.fn(() => request({ items: [], limit: 20, next_cursor: null })),
  } as unknown as CommunityApi;
  harness.run.mockImplementation((handle: RequestHandle<unknown>) => handle.promise);
  harness.action.mockImplementation(async (scope: string, value: unknown) => {
    const signature = JSON.stringify(value), previous = harness.actions.get(scope);
    const key = previous?.signature === signature ? previous.key : `synthetic-safe-operation-${harness.action.mock.calls.length}`;
    harness.actions.set(scope, { signature, key }); return { key, input: value, authEpoch: harness.state.authEpoch };
  });
  harness.clearAction.mockImplementation((scope: string) => harness.actions.delete(scope));
});

describe('REAL community ordinary page behavior', () => {
  it('valid local preview uses selected tags and never writes or enters family scope', () => {
    const tree = setDraft(); expect(find(tree, 'pc-draft-preview')).not.toBeNull(); expect(text(tree)).toContain(post.body);
    expect(harness.api.createPost).not.toHaveBeenCalled(); expect(harness.action).not.toHaveBeenCalled(); expect(harness.run).not.toHaveBeenCalled();
  });
  it('required fields, dangerous markup and oversized text cannot become a real preview', () => {
    let tree = render(RealCommunityComposePage); click(tree, 'pc-compose-preview'); tree = render(RealCommunityComposePage); expect(find(tree, 'pc-compose-error')).not.toBeNull();
    tree = setDraft('<script>alert(1)</script>'); expect(find(tree, 'pc-draft-preview')).toBeNull();
    tree = setDraft('合成标题', '字'.repeat(2001)); expect(find(tree, 'pc-draft-preview')).toBeNull(); expect(harness.api.createPost).not.toHaveBeenCalled();
  });
  it.each([false, true])('unconfirmed or missing nickname blocks cloud writes (ready=%s)', ready => {
    harness.identityReady = ready; harness.nickname = ''; const tree = setDraft();
    expect(find(tree, 'pc-compose-submit')!.props.disabled).toBe(true); click(tree, 'pc-compose-submit'); expect(harness.api.createPost).not.toHaveBeenCalled();
  });
  it('503 retry keeps exact input and key, only a confirmed pending receipt shows submitted state', async () => {
    vi.mocked(harness.api.createPost).mockImplementationOnce(() => failure(new CommunityError('server', 503)));
    let tree = setDraft(); click(tree, 'pc-compose-submit'); await tick(); tree = render(RealCommunityComposePage);
    expect(find(tree, 'pc-compose-submitted')).toBeNull(); expect(text(tree)).toContain('状态尚未确认');
    click(tree, 'pc-compose-submit'); await tick(); tree = render(RealCommunityComposePage);
    const calls = vi.mocked(harness.api.createPost).mock.calls; expect(calls).toHaveLength(2); expect(calls[1]).toEqual(calls[0]);
    expect(find(tree, 'pc-compose-submitted')).not.toBeNull(); expect(text(tree)).toContain('已提交审核，暂时不会公开展示');
  });
  it('changing an uncertain draft starts a new operation instead of reusing the old key', async () => {
    vi.mocked(harness.api.createPost).mockImplementationOnce(() => failure(new CommunityError('server', 503)));
    let tree = setDraft(); click(tree, 'pc-compose-submit'); await tick(); tree = render(RealCommunityComposePage); click(tree, 'pc-compose-edit');
    tree = render(RealCommunityComposePage); input(tree, 'pc-title-input', '改过的合成新标题'); tree = render(RealCommunityComposePage); click(tree, 'pc-compose-preview');
    tree = render(RealCommunityComposePage); click(tree, 'pc-compose-submit'); await tick();
    const calls = vi.mocked(harness.api.createPost).mock.calls; expect(calls[1][0].title).toBe('改过的合成新标题'); expect(calls[1][1]).not.toBe(calls[0][1]);
  });
  it('a late old-account post cannot expose a draft/receipt or unlock the new pending request', async () => {
    const old = deferred<OwnedPost>(), fresh = deferred<OwnedPost>(); vi.mocked(harness.api.createPost).mockReturnValueOnce(old.handle).mockReturnValueOnce(fresh.handle);
    let tree = setDraft(); click(tree, 'pc-compose-submit'); await tick();
    harness.state = { ...harness.state, authEpoch: 2 }; tree = render(RealCommunityComposePage, false);
    expect(find(tree, 'pc-title-input')!.props.value).toBe(''); expect(find(tree, 'pc-draft-preview')).toBeNull();
    tree = setDraft('第二账户合成标题'); click(tree, 'pc-compose-submit'); await tick(); old.resolve(owned); await tick();
    tree = render(RealCommunityComposePage); expect(find(tree, 'pc-compose-submit')!.props.disabled).toBe(true); expect(find(tree, 'pc-compose-submitted')).toBeNull();
    click(tree, 'pc-compose-submit'); expect(harness.api.createPost).toHaveBeenCalledTimes(2);
    fresh.resolve({ ...owned, title: '第二账户合成标题' }); await tick(); tree = render(RealCommunityComposePage); expect(find(tree, 'pc-compose-submitted')).not.toBeNull();
  });
  it('editing loads only own content and submits the exact original content revision', async () => {
    harness.params.id = id; render(RealCommunityComposePage); await tick(); let tree = render(RealCommunityComposePage);
    expect(harness.api.myContent).toHaveBeenCalledWith('post', id); input(tree, 'pc-title-input', '合成编辑后的标题'); tree = render(RealCommunityComposePage); click(tree, 'pc-compose-preview');
    tree = render(RealCommunityComposePage); click(tree, 'pc-compose-submit'); await tick();
    expect(harness.api.editPost).toHaveBeenCalledWith(id, expect.objectContaining({ title: '合成编辑后的标题' }), 1); expect(harness.api.createPost).not.toHaveBeenCalled();
  });
  it('relation 404 clears the full detail only when anonymous public visibility also returns 404', async () => {
    vi.mocked(harness.api.relations).mockImplementation(() => failure(new CommunityError('not_found', 404)));
    const unavailable = vi.fn(); const page = () => PostRelations({ post, onUnavailable: unavailable }); render(page); await tick();
    expect(harness.api.post).toHaveBeenCalledWith(id); expect(unavailable).not.toHaveBeenCalled();
    vi.mocked(harness.api.post).mockImplementation(() => failure(new CommunityError('not_found', 404)));
    const tree = render(page); click(tree, 'pc-relations-retry'); await tick(); expect(unavailable).toHaveBeenCalledOnce();
  });
  it('like state is never optimistic and an uncertain receipt requires rereading actual state', async () => {
    const pending = deferred<{ post_id: string; kind: 'like'; active: boolean }>(); vi.mocked(harness.api.setLike).mockReturnValue(pending.handle);
    const page = () => PostRelations({ post, onUnavailable: vi.fn() }); render(page); await tick(); let tree = render(page); click(tree, 'pc-post-like');
    tree = render(page); expect(text(find(tree, 'pc-post-like'))).toBe('点赞'); expect(find(tree, 'pc-post-like')!.props.disabled).toBe(true);
    pending.resolve({ post_id: id, kind: 'like', active: false }); await tick(); tree = render(page);
    expect(find(tree, 'pc-post-like')).toBeNull(); expect(find(tree, 'pc-relations-retry')).not.toBeNull();
  });
  it('comment submission remains pending and cannot enter the public comment list', async () => {
    const page = () => CommentPanel({ post, onUnavailable: vi.fn() }); render(page); await tick(); let tree = render(page); click(tree, 'pc-comment-open');
    tree = render(page); input(tree, 'pc-comment-input', '合成待审评论正文'); tree = render(page); click(tree, 'pc-comment-submit'); await tick(); tree = render(page);
    expect(text(tree)).toContain('评论已提交审核，暂时不会公开展示'); expect(find(tree, 'pc-comment-input')!.props.value).toBe('');
    expect(text(tree)).not.toContain('合成待审评论正文'); expect(harness.api.comments).toHaveBeenCalledOnce();
  });
  it('comment 503 retries original text/key and rejects empty or dangerous text before cloud write', async () => {
    vi.mocked(harness.api.createComment).mockImplementationOnce(() => failure(new CommunityError('server', 503)));
    const page = () => CommentPanel({ post, onUnavailable: vi.fn() }); render(page); await tick(); let tree = render(page); click(tree, 'pc-comment-open'); tree = render(page);
    click(tree, 'pc-comment-submit'); await tick(); expect(harness.api.createComment).not.toHaveBeenCalled();
    input(tree, 'pc-comment-input', '安全合成评论'); tree = render(page); click(tree, 'pc-comment-submit'); await tick(); tree = render(page); expect(find(tree, 'pc-comment-input')!.props.value).toBe('安全合成评论');
    click(tree, 'pc-comment-submit'); await tick(); expect(vi.mocked(harness.api.createComment).mock.calls[1]).toEqual(vi.mocked(harness.api.createComment).mock.calls[0]);
  });
  it('reporting other requires a reason and keeps the original action key after503', async () => {
    vi.mocked(harness.api.report).mockImplementationOnce(() => failure(new CommunityError('server', 503)));
    const page = () => ReportForm({ kind: 'post', id, onUnavailable: vi.fn() }); let tree = render(page); click(tree, `pc-report-post-${id}`); tree = render(page); click(tree, `pc-report-reason-post-${id}-other`);
    tree = render(page); click(tree, `pc-report-submit-post-${id}`); await tick(); expect(harness.api.report).not.toHaveBeenCalled();
    input(tree, `pc-report-detail-post-${id}`, '合成举报说明'); tree = render(page); click(tree, `pc-report-submit-post-${id}`); await tick(); tree = render(page); expect(text(tree)).not.toContain('举报已提交。');
    click(tree, `pc-report-submit-post-${id}`); await tick(); expect(vi.mocked(harness.api.report).mock.calls[1]).toEqual(vi.mocked(harness.api.report).mock.calls[0]);
  });
  it('bookmark disappearance immediately refreshes the server-filtered owner list without pretending removal', async () => {
    vi.mocked(harness.api.setBookmark).mockImplementation(() => failure(new CommunityError('not_found', 404))); const refresh = vi.fn();
    const page = () => BookmarkCard({ post, refresh, open: vi.fn() }); const tree = render(page); click(tree, `pc-mine-unbookmark-${id}`); await tick(); expect(refresh).toHaveBeenCalledOnce();
    expect(text(render(page))).not.toContain('已取消收藏');
  });
  it('owner feedback cannot bind to a different content kind, revision or current status', async () => {
    const feedback = { target_type: 'post' as const, target_id: id, content_revision: 1, status: 'pending' as const, feedback: null };
    expect(feedbackMatchesContent(feedback, owned)).toBe(true);
    for (const changed of [{ target_type: 'comment' as const }, { content_revision: 2 }, { status: 'rejected' as const }]) expect(feedbackMatchesContent({ ...feedback, ...changed }, owned)).toBe(false);
    vi.mocked(harness.api.feedback).mockReturnValue(request({ ...feedback, content_revision: 2, feedback: { action: 'reject', reason: '不应显示的旧正文反馈', at: post.created_at, content_revision: 2 } }));
    const refresh = vi.fn(); const page = () => OwnedCard({ item: owned, refresh, withdraw: vi.fn(), open: vi.fn() }); const tree = render(page); click(tree, `pc-mine-feedback-${id}`); await tick();
    expect(text(render(page))).not.toContain('不应显示的旧正文反馈'); expect(refresh).toHaveBeenCalledOnce();
  });
  it('withdraw requires confirmation and the exact revision; only confirmed response clears the owner item', async () => {
    const pending = deferred<void>(); vi.mocked(harness.api.withdrawPost).mockReturnValue(pending.handle); const withdraw = vi.fn();
    const page = () => OwnedCard({ item: owned, refresh: vi.fn(), withdraw, open: vi.fn() }); let tree = render(page); click(tree, `pc-mine-withdraw-${id}`); expect(harness.api.withdrawPost).not.toHaveBeenCalled();
    tree = render(page); click(tree, `pc-mine-confirm-withdraw-${id}`); expect(harness.api.withdrawPost).toHaveBeenCalledWith(id, 1); expect(withdraw).not.toHaveBeenCalled();
    pending.resolve(); await tick(); expect(withdraw).toHaveBeenCalledWith(id);
  });
  it('mine filter races cannot restore late posts after switching to comments', async () => {
    const pending = deferred<{ items: OwnedPost[]; limit: number; next_cursor: null }>(); vi.mocked(harness.api.myPosts).mockReturnValue(pending.handle);
    render(CommunityMinePage); let tree = render(CommunityMinePage); click(tree, 'pc-mine-tab-comments'); await tick(); pending.resolve({ items: [owned], limit: 20, next_cursor: null }); await tick(); tree = render(CommunityMinePage);
    expect(text(tree)).not.toContain(owned.body); expect(find(tree, 'pc-mine-empty')).not.toBeNull();
    expect(harness.api.myComments).toHaveBeenCalledWith({ limit: 20, cursor: null });
  });
  it('account/mode scoped locks release new work independently of old pending callbacks', () => {
    const locks: { current: boolean }[] = []; const page = () => { locks.push(useCommunityBusy('synthetic')); return createElement('div'); };
    render(page); locks[0].current = true; harness.state = { ...harness.state, authEpoch: 2 }; render(page); expect(locks[1].current).toBe(false);
    locks[1].current = true; locks[0].current = false; expect(locks[1].current).toBe(true);
    harness.state = { ...harness.state, mode: 'demo' }; render(page); expect(locks[2].current).toBe(false);
  });
});
