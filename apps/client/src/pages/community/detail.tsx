import { useState } from 'react';
import { useRouter } from '@tarojs/taro';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { EmptyState, SectionCard } from '../../components/Primitives';
import { ExampleLabel, PostTags } from '../../community/components';
import { EXAMPLE_POSTS } from '../../community/fixtures/posts';
import { findCommunityPost } from '../../community/model';
import { backToCommunity } from '../../navigation';

function CommunityDetailPage() {
  const router = useRouter();
  const post = findCommunityPost(EXAMPLE_POSTS, router.params.id);
  const [navigationError, setNavigationError] = useState('');
  function back() {
    setNavigationError('');
    void backToCommunity().catch(() => setNavigationError('暂时无法返回社区，请再试一次。'));
  }
  const backAction = <Button id="pc-detail-back" className="pc-action" onClick={back}>← 返回社区列表</Button>;

  return <AppShell page="community-detail">
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

export default withClientErrorBoundary(CommunityDetailPage);
