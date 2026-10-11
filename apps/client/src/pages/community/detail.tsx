import { useEffect, useState } from 'react';
import { useDidShow, useRouter } from '@tarojs/taro';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { EmptyState, SectionCard } from '../../components/Primitives';
import { CommunityModeNote, ExampleLabel, PostTags } from '../../community/components';
import { EXAMPLE_POSTS } from '../../community/fixtures/posts';
import { findCommunityPost } from '../../community/model';
import { backToCommunity } from '../../navigation';
import { useCommunity } from '../../state/CommunityProvider';
import type { PublicPost } from '../../community/apiTypes';
import { useCommunityViewState } from '../../community/viewState';
import { communityFailureText, isCancelled, isUnavailable, publicTime } from '../../community/presentation';
import { communityId } from '../../community/validation';
import { CommentPanel, PostRelations, ReportForm } from '../../community/PostInteractions';

function ExampleCommunityDetailPage() {
  const router = useRouter();
  const post = findCommunityPost(EXAMPLE_POSTS, router.params.id);
  const [navigationError, setNavigationError] = useState('');
  function back() {
    setNavigationError('');
    void backToCommunity().catch(() => setNavigationError('暂时无法返回社区，请再试一次。'));
  }
  const backAction = <Button id="pc-detail-back" className="pc-action" onClick={back}>← 返回社区列表</Button>;

  return <AppShell page="community-detail">
    <CommunityModeNote mode="demo" />
    {post ? <>
      <View className="pc-detail-nav">{backAction}<ExampleLabel /></View>
      <View className="pc-detail">
        <PageHeader eyebrow="予怀 · 示例帖子" title={post.title} description={`${post.author.displayName} · 合成昵称 ｜ ${post.publishedAt.slice(0, 10)} · 示例日期`} />
        <PostTags post={post} />
        <Text className="pc-plain-text">{post.body}</Text>
        <View className="pc-preview-note" role="note"><Text>示例内容：作者、日期与正文均为合成展示。不来自真实家庭，也不是专业育儿或医学建议。</Text></View>
        <SectionCard title="评论与交流" eyebrow="功能尚未接入"><Text className="sc-body-muted">目前只有本地示例帖子，尚不能发表评论、点赞或收藏。真实社区互动和内容审核将在后续阶段实现。</Text></SectionCard>
      </View>
    </> : <>
      <PageHeader eyebrow="予怀 · 示例帖子" title="这条示例暂时找不到" description="链接可能不完整，或该编号不在本地示例中。没有读取云端内容。" action={backAction} />
      <View id="pc-detail-missing"><EmptyState title="没有这个示例帖子" detail="请返回社区列表，重新打开一条示例内容。" /></View>
    </>}
    {navigationError && <View className="sc-inline-error" role="status"><Text>{navigationError}</Text></View>}
  </AppShell>;
}

function RealCommunityDetailPage() {
  const id = useRouter().params.id;
  const { state, store, api } = useCommunity();
  const form = useCommunityViewState(`detail:${id ?? 'missing'}`, () => ({ post: null as PublicPost | null, status: 'idle' as 'idle' | 'loading' | 'ready' | 'missing' | 'error', message: '' }));
  const [navigationError, setNavigationError] = useState('');
  async function load() {
    if (!form.isCurrent() || !api) return;
    let canonicalId: string;
    try { canonicalId = communityId(id); } catch { form.update(value => ({ ...value, post: null, status: 'missing', message: '' })); return; }
    form.update(value => ({ ...value, post: null, status: 'loading', message: '' }));
    const version = form.version();
    try {
      const post = await store.run(api.post(canonicalId), { key: `public-detail:${canonicalId}` });
      form.complete(version, value => ({ ...value, post, status: 'ready' }));
    } catch (error) {
      if (!isCancelled(error)) form.complete(version, value => ({ ...value, post: null, status: isUnavailable(error) ? 'missing' : 'error', message: communityFailureText(error) }));
    }
  }
  useEffect(() => { void load(); }, [id, state.authEpoch]);
  useDidShow(() => { void load(); });
  function unavailable() {
    if (!form.isCurrent()) return;
    form.update(value => ({ ...value, post: null, status: 'missing', message: '' }));
    void store.refreshFeed();
  }
  function back() {
    setNavigationError('');
    void backToCommunity().catch(() => setNavigationError('暂时无法返回社区，请再试一次。'));
  }
  const backAction = <Button id="pc-detail-back" className="pc-action" onClick={back}>← 返回社区列表</Button>;
  const { post, status, message } = form.values;
  return <AppShell page="community-detail">
    <CommunityModeNote mode="real" />
    <View className="pc-detail-nav">{backAction}</View>
    {post && status === 'ready' ? <View className="pc-detail">
      <PageHeader eyebrow="予怀 · 家长交流 · 已审核" title={post.title} description={`${post.author.nickname} ｜ ${publicTime(post.published_at)}`} />
      <PostTags post={{ age: post.age_band, topic: post.topic }} />
      <Text id="pc-real-post-body" className="pc-plain-text">{post.body}</Text>
      <Text className="pc-form-hint">家长经验分享不代表专业、医疗或心理诊断建议。请共同留意隐私和交流边界。</Text>
      <PostRelations post={post} onUnavailable={unavailable} />
      <ReportForm kind="post" id={post.id} onUnavailable={unavailable} />
      <CommentPanel post={post} onUnavailable={unavailable} />
    </View> : status === 'missing' ? <View id="pc-detail-missing"><PageHeader eyebrow="予怀 · 社区内容" title="内容已不可查看" description="请返回社区，继续查看目前公开的内容。" /><EmptyState title="内容已不可查看" detail="这条内容当前没有公开访问入口。" /></View> : <>
      <PageHeader eyebrow="予怀 · 真实社区" title={status === 'loading' || status === 'idle' ? '正在读取帖子…' : '帖子暂时无法读取'} description="这里只读取公开帖子，不会显示待审内容或用示例替代。" />
      {message && <View id="pc-detail-error" className="sc-inline-error" role="status"><Text>{message}</Text></View>}
      {status === 'error' && <Button id="pc-detail-retry" className="pc-action" onClick={() => void load()}>重新读取帖子</Button>}
    </>}
    {navigationError && <View className="sc-inline-error" role="status"><Text>{navigationError}</Text></View>}
  </AppShell>;
}

function CommunityDetailPage() {
  const { state } = useCommunity();
  return state.mode === 'demo' ? <ExampleCommunityDetailPage /> : <RealCommunityDetailPage />;
}

export default withClientErrorBoundary(CommunityDetailPage);
