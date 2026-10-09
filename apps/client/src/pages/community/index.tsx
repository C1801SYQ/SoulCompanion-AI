import { useRef, useState } from 'react';
import Taro, { useDidHide, useDidShow, usePageScroll } from '@tarojs/taro';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { EmptyState } from '../../components/Primitives';
import { CommunityFilterControls, PostCard } from '../../community/components';
import type { CommunityAgeFilter, CommunityTopicFilter } from '../../community/constants';
import { EXAMPLE_POSTS } from '../../community/fixtures/posts';
import { readBrowseState, saveBrowseState } from '../../community/memory';
import { filterCommunityPosts } from '../../community/model';
import { openPage } from '../../navigation';

function CommunityPage() {
  const [browse, setBrowse] = useState(readBrowseState);
  const [navigationError, setNavigationError] = useState('');
  const browseRef = useRef(browse);
  const visibleRef = useRef(true);

  usePageScroll(({ scrollTop }) => {
    if (!visibleRef.current) return;
    const next = { ...browseRef.current, scrollTop };
    browseRef.current = next;
    saveBrowseState(next);
  });
  useDidHide(() => {
    visibleRef.current = false;
    saveBrowseState(browseRef.current);
  });
  useDidShow(() => {
    visibleRef.current = true;
    const saved = readBrowseState();
    browseRef.current = saved;
    setBrowse(saved);
    Taro.nextTick(() => {
      void Taro.pageScrollTo({ scrollTop: saved.scrollTop, duration: 0 }).catch(() => {
        setNavigationError('筛选已保留，暂时无法恢复阅读位置。请从列表继续浏览。');
      });
    });
  });

  function choose(age: CommunityAgeFilter, topic: CommunityTopicFilter) {
    const next = { ...browseRef.current, age, topic };
    browseRef.current = next;
    saveBrowseState(next);
    setBrowse(next);
  }
  function open(url: string) {
    saveBrowseState(browseRef.current);
    setNavigationError('');
    void openPage(url).catch(() => setNavigationError('页面暂时无法打开，请再试一次。'));
  }
  const posts = filterCommunityPosts(EXAMPLE_POSTS, browse);

  return <AppShell page="community">
    <PageHeader eyebrow="予怀 · 家长社区" title="把日常的小事，说给懂你的人。" description="面向 0～18 岁儿童家庭。成年家长和监护人都可以从这里开始，不需要诊断标签、购买、订阅或儿童档案。" action={<Button id="pc-compose-entry" className="pc-action pc-action--primary" onClick={() => open('/pages/community/compose')}>试写一篇投稿</Button>} />
    <View className="pc-preview-note" role="note"><Text className="pc-preview-note-title">社区产品预览</Text><Text>下面都是虚构的示例内容和合成家长昵称，用来体验浏览、筛选与详情。真实发布、互动与审核尚未接入。</Text></View>
    <View className="pc-community-layout">
      <View className="pc-feed">
        <CommunityFilterControls age={browse.age} topic={browse.topic} onAge={age => choose(age, browseRef.current.topic)} onTopic={topic => choose(browseRef.current.age, topic)} />
        <View className="pc-feed-heading"><View role="heading" aria-level="2"><Text>日常交流</Text></View><View id="pc-filter-count" role="status" aria-live="polite"><Text>{posts.length} 条示例 · 按发布时间从新到旧</Text></View></View>
        {navigationError && <View className="sc-inline-error" role="status"><Text>{navigationError}</Text></View>}
        {posts.length === 0 ? <View id="pc-community-empty"><EmptyState title="这个组合暂时没有示例" detail="可以换一个年龄段或话题看看。这只是当前示例范围，不代表真实社区的内容数量。" /></View> : <View className="pc-post-list">{posts.map(post => <PostCard key={post.id} post={post} onOpen={() => open(`/pages/community/detail?id=${post.id}`)} />)}</View>}
      </View>
      <View className="pc-aside">
        <View className="pc-aside-card"><Text className="sc-eyebrow">一起安心交流</Text><View role="heading" aria-level="2"><Text className="pc-aside-title">分享经验，也留住边界。</Text></View><Text className="pc-aside-text">可以聊感受和日常做法。请不填写孩子姓名、照片、学校、住址、病史或其他识别信息，也不公开他人的隐私。</Text><Text className="pc-aside-text">不同家庭有不同节奏，经验分享不代表专业建议或医学结论。</Text></View>
        <View className="pc-aside-card pc-aside-card--warm"><Text className="sc-eyebrow">为家长留一处空间</Text><Text className="pc-aside-title">从一点交流开始。</Text><Text className="pc-aside-text">这里不会读取你的儿童档案或私有报告，也不会自动开启摄像头和麦克风。</Text><Text className="pc-aside-text">陪伴、洞察与旧报告仍在“成长记录”的可选家庭工具中。</Text></View>
      </View>
    </View>
  </AppShell>;
}

export default withClientErrorBoundary(CommunityPage);
