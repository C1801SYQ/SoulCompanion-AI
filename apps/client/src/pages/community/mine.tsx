import { useEffect, useRef } from 'react';
import { useDidShow, useRouter } from '@tarojs/taro';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { EmptyState } from '../../components/Primitives';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { useCloud } from '../../state/CloudProvider';
import { useCommunity } from '../../state/CommunityProvider';
import { backToCommunity, openPage } from '../../navigation';
import { CommunityAccountPanel } from '../../community/AccountPanel';
import { ChoiceGroup, CommunityModeNote, ContentStatusLabel, PostTags, PublicPostCard } from '../../community/components';
import { appendContentPage, feedbackMatchesContent, useCommunityBusy, useCommunityViewState, VISIBLE_PAGE_LIMIT } from '../../community/viewState';
import { communityFailureText, isCancelled, isUncertainWrite, isUnavailable, publicTime } from '../../community/presentation';
import { CommunityError, type CommunityPage, type ContentKind, type Feedback, type OwnedContent, type PublicPost } from '../../community/apiTypes';

type MyTab = 'posts' | 'comments' | 'bookmarks';
const MY_TABS: readonly { value: MyTab; label: string }[] = [{ value: 'posts', label: '我的投稿' }, { value: 'comments', label: '我的评论' }, { value: 'bookmarks', label: '我的收藏' }];

export function OwnedCard({ item, refresh, withdraw, open }: {
  item: OwnedContent; refresh: () => void; withdraw: (id: string) => void; open: (url: string) => void;
}) {
  const { api, store } = useCommunity();
  const kind: ContentKind = 'title' in item ? 'post' : 'comment';
  const form = useCommunityViewState(`owned-card:${kind}:${item.id}:${item.content_revision}:${item.status}`, () => ({ confirm: false, busy: false, message: '', uncertain: false, feedback: null as Feedback | null }));
  const busy = useCommunityBusy(`owned-card:${kind}:${item.id}:${item.content_revision}:${item.status}`);
  async function loadFeedback() {
    if (!form.isCurrent() || !api || busy.current) return;
    busy.current = true;
    form.update(value => ({ ...value, busy: true, message: '', feedback: null }));
    const version = form.version();
    try {
      const feedback = await store.run(api.feedback(kind, item.id), { private: true, key: `feedback:${kind}:${item.id}` });
      if (!feedbackMatchesContent(feedback, item)) {
        form.complete(version, value => ({ ...value, busy: false, message: '内容状态或版本已经变化，请刷新后核对当前内容。' }));
        if (form.isCurrent()) refresh();
        return;
      }
      form.complete(version, value => ({ ...value, busy: false, feedback }));
    } catch (error) { if (!isCancelled(error)) form.complete(version, value => ({ ...value, busy: false, message: communityFailureText(error) })); }
    finally { busy.current = false; }
  }
  async function performWithdraw() {
    if (!form.isCurrent() || !api || busy.current || item.status === 'deleted') return;
    busy.current = true;
    form.update(value => ({ ...value, busy: true, message: '' }));
    const version = form.version();
    try {
      await store.run(kind === 'post' ? api.withdrawPost(item.id, item.content_revision) : api.withdrawComment(item.id, item.content_revision), { private: true, key: `withdraw:${kind}:${item.id}` });
      if (!form.isCurrent()) return;
      form.complete(version, value => ({ ...value, busy: false, confirm: false, uncertain: false, message: '撤回已由云端确认。' }));
      withdraw(item.id);
      void store.refreshFeed();
    } catch (error) { if (!isCancelled(error)) form.complete(version, value => ({ ...value, busy: false, uncertain: isUncertainWrite(error), message: communityFailureText(error) })); }
    finally { busy.current = false; }
  }
  return <View className="pc-post-card pc-owned-card" data-owned-id={item.id} data-content-status={item.status}>
    <View className="pc-post-top"><ContentStatusLabel status={item.status} /><Text>内容版本 {item.content_revision}</Text></View>
    {'title' in item ? <><View role="heading" aria-level="2"><Text className="pc-draft-title">{item.title}</Text></View><PostTags post={{ age: item.age_band, topic: item.topic }} /></> : <Text className="sc-setting-name">我的一级评论</Text>}
    <Text className="pc-plain-text">{item.body}</Text>
    <View className="pc-post-meta"><Text>{item.author.nickname}</Text><Text>创建于 {publicTime(item.created_at)}</Text></View>
    <View className="pc-interactions">
      {item.status === 'published' && <Button id={`pc-mine-open-${item.id}`} className="pc-action" onClick={() => open(`/pages/community/detail?id=${'title' in item ? item.id : item.post_id}`)}>查看公开帖子</Button>}
      {'title' in item && item.status !== 'deleted' && <Button id={`pc-mine-edit-${item.id}`} className="pc-action" disabled={form.values.busy} onClick={() => open(`/pages/community/compose?id=${item.id}`)}>编辑投稿</Button>}
      <Button id={`pc-mine-feedback-${item.id}`} className="pc-action" disabled={form.values.busy} onClick={() => void loadFeedback()}>查看审核反馈</Button>
      {item.status !== 'deleted' && <Button id={`pc-mine-withdraw-${item.id}`} className="pc-action" disabled={form.values.busy} onClick={() => form.update(value => ({ ...value, confirm: true, message: '' }))}>撤回{kind === 'post' ? '投稿' : '评论'}</Button>}
    </View>
    {form.values.confirm && <View className="pc-confirm-panel"><Text>撤回后不再公开，保留必要审核记录。此操作只针对本人这条内容和当前版本。</Text>{form.values.uncertain && <Text>结果尚未确认。安全重试沿用原版本；也可以刷新本人列表核对。</Text>}<Button id={`pc-mine-confirm-withdraw-${item.id}`} className="pc-action" disabled={form.values.busy} onClick={() => void performWithdraw()}>{form.values.busy ? '正在确认…' : form.values.uncertain ? '使用原版本安全重试撤回' : '确认撤回'}</Button><Button className="pc-action" disabled={form.values.busy} onClick={() => form.update(value => ({ ...value, confirm: false }))}>暂不撤回</Button></View>}
    {form.values.feedback && <View className="pc-feedback" role="status">{form.values.feedback.feedback ? <><Text>{({ approve: '审核通过', reject: '审核未通过', hide: '内容隐藏' })[form.values.feedback.feedback.action]}</Text><Text className="pc-plain-text">{form.values.feedback.feedback.reason}</Text><Text>{publicTime(form.values.feedback.feedback.at)} · 正文版本 {form.values.feedback.feedback.content_revision}</Text></> : <Text>当前正文版本没有可展示的审核反馈。待审不代表已经通过。</Text>}</View>}
    {form.values.message && <View id={`pc-mine-message-${item.id}`} className="pc-mutation-status" role="status"><Text>{form.values.message}</Text><Button className="pc-action" disabled={form.values.busy} onClick={refresh}>刷新本人内容</Button></View>}
  </View>;
}

export function BookmarkCard({ post, refresh, open }: { post: PublicPost; refresh: () => void; open: (url: string) => void }) {
  const { api, store } = useCommunity();
  const form = useCommunityViewState(`my-bookmark:${post.id}`, () => ({ busy: false, message: '' }));
  const busy = useCommunityBusy(`my-bookmark:${post.id}`);
  async function remove() {
    if (!form.isCurrent() || !api || busy.current) return;
    busy.current = true;
    form.update(value => ({ ...value, busy: true, message: '' }));
    const version = form.version();
    try {
      const receipt = await store.run(api.setBookmark(post.id, false), { private: true, key: `my-bookmark:${post.id}` });
      if (receipt.kind !== 'bookmark' || receipt.post_id !== post.id || receipt.active) throw new CommunityError('invalid');
      if (form.isCurrent()) refresh();
    } catch (error) {
      if (!isCancelled(error)) form.complete(version, value => ({ ...value, busy: false, message: `${communityFailureText(error)} 请刷新收藏核对，页面不会假设已取消。` }));
      if (form.isCurrent() && isUnavailable(error)) refresh();
    }
    finally { busy.current = false; }
  }
  return <View><PublicPostCard post={post} onOpen={() => open(`/pages/community/detail?id=${post.id}`)} /><Button id={`pc-mine-unbookmark-${post.id}`} className="pc-action" disabled={form.values.busy} onClick={() => void remove()}>取消收藏</Button>{form.values.message && <View role="status"><Text>{form.values.message}</Text><Button className="pc-action" disabled={form.values.busy} onClick={refresh}>刷新收藏</Button></View>}</View>;
}

export function CommunityMinePage() {
  const { state: cloud } = useCloud();
  const { state, api, store } = useCommunity();
  const queryTab = useRouter().params.tab;
  const initialTab = MY_TABS.some(item => item.value === queryTab) ? queryTab as MyTab : 'posts';
  const form = useCommunityViewState(`mine:${initialTab}`, () => ({ tab: initialTab, rows: [] as (OwnedContent | PublicPost)[], cursor: null as string | null, loading: false, ready: false, message: '', navigationError: '', truncated: false }));
  const tabScope = `${state.mode}:${state.authEpoch}:${initialTab}`;
  const tabOwner = useRef({ scope: tabScope, tab: { current: form.values.tab } });
  if (tabOwner.current.scope !== tabScope) tabOwner.current = { scope: tabScope, tab: { current: form.values.tab } };
  const currentTab = tabOwner.current.tab;
  const signedIn = cloud.auth.status === 'signed_in';
  async function load(more = false, requestedTab = currentTab.current) {
    if (!form.isCurrent() || !api || !signedIn || state.mode !== 'real' || requestedTab !== currentTab.current) return;
    const previous = form.values;
    if (more && (previous.tab !== requestedTab || !previous.cursor || previous.loading || previous.truncated)) return;
    const query = { limit: 20, cursor: more ? previous.cursor : null };
    form.update(value => ({ ...value, tab: requestedTab, loading: true, message: '', ...(!more ? { rows: [], cursor: null, ready: false, truncated: false } : {}) }));
    const version = form.version();
    try {
      const handle = requestedTab === 'posts' ? api.myPosts(query) : requestedTab === 'comments' ? api.myComments(query) : api.bookmarks(query);
      const page = await store.run<CommunityPage<OwnedContent | PublicPost>>(handle, { private: true, key: 'my-community-list' });
      if (more && page.next_cursor === previous.cursor) throw new CommunityError('invalid');
      const rows = appendContentPage(more ? previous.rows : [], page.items);
      const truncated = rows.length >= VISIBLE_PAGE_LIMIT && page.next_cursor !== null;
      form.complete(version, value => ({ ...value, rows, cursor: truncated ? null : page.next_cursor, loading: false, ready: true, truncated }));
    } catch (error) { if (!isCancelled(error)) form.complete(version, value => ({ ...value, rows: [], cursor: null, loading: false, ready: false, message: communityFailureText(error) })); }
  }
  useEffect(() => { currentTab.current = initialTab; void load(false, initialTab); }, [state.authEpoch, state.mode, signedIn, initialTab]);
  useDidShow(() => { void load(); });
  function choose(tab: MyTab) {
    if (!form.isCurrent()) return;
    currentTab.current = tab;
    form.update(value => ({ ...value, tab, rows: [], cursor: null, loading: false, ready: false, message: '', truncated: false }));
    void load(false, tab);
  }
  function open(url: string) { void openPage(url).catch(() => form.update(value => ({ ...value, navigationError: '暂时无法打开页面，请再试一次。' }))); }
  function withdraw(id: string) { form.update(value => ({ ...value, rows: value.rows.map(row => row.id === id && 'status' in row ? { ...row, status: 'deleted', published_at: null } : row) })); }
  return <AppShell page="community-mine">
    <CommunityModeNote mode={state.mode} />
    <PageHeader eyebrow="我的 · 社区内容" title="留住分享，也保留自己的选择。" description="这里仅显示当前账号的投稿、评论和收藏。退出或切换账号后立即隐藏，不读取私有儿童档案。" action={<Button id="pc-mine-back" className="pc-action" onClick={() => { void backToCommunity().catch(() => form.update(value => ({ ...value, navigationError: '暂时无法返回，请再试一次。' }))); }}>← 返回</Button>} />
    {state.mode === 'demo' ? <EmptyState title="示例模式不会保存真实内容" detail="投稿仅用于本地预览，示例点赞、收藏或审核不会被当成云端操作。" /> : !signedIn ? <CommunityAccountPanel /> : <>
      <ChoiceGroup label="本人社区内容" items={MY_TABS} selected={form.values.tab} idPrefix="pc-mine-tab" onChange={choose} />
      <Button id="pc-mine-refresh" className="pc-action" onClick={() => void load()}>刷新本人内容</Button>
      {form.values.loading && <View role="status"><Text>正在读取当前账号内容…</Text></View>}
      {form.values.message && <View id="pc-mine-error" className="sc-inline-error" role="status"><Text>{form.values.message}</Text></View>}
      {form.values.ready && form.values.rows.length === 0 && <View id="pc-mine-empty"><EmptyState title={form.values.tab === 'bookmarks' ? '这一页没有当前可见的收藏' : form.values.tab === 'comments' ? '还没有本人评论' : '还没有本人投稿'} detail={form.values.tab === 'bookmarks' ? '收藏只显示目前仍公开的帖子；若还有游标，可以继续读取下一页。' : '新提交会先进入待审核，可以在这里核对状态。'} /></View>}
      <View className="pc-post-list">{form.values.rows.map(row => 'status' in row ? <OwnedCard key={row.id} item={row} refresh={() => void load()} withdraw={withdraw} open={open} /> : <BookmarkCard key={row.id} post={row} refresh={() => void load()} open={open} />)}</View>
      {form.values.cursor && <Button id="pc-mine-more" className="pc-action" disabled={form.values.loading} onClick={() => void load(true)}>加载更多本人内容</Button>}
      {form.values.truncated && <Text className="pc-form-hint">本次最多显示 200 条内容，请刷新或切换分类继续。</Text>}
    </>}
    {form.values.navigationError && <View role="status"><Text>{form.values.navigationError}</Text></View>}
  </AppShell>;
}

export default withClientErrorBoundary(CommunityMinePage);
