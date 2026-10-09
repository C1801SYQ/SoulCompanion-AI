import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../components/AccessibleButton';
import { AGE_FILTERS, TOPIC_FILTERS, ageLabel, topicLabel } from './constants';
import type { CommunityAgeFilter, CommunityTopicFilter } from './constants';
import type { CommunityPostPreview } from './types';

export function ChoiceGroup<T extends string>({ label, items, selected, onChange, idPrefix }: {
  label: string; items: readonly { value: T; label: string }[]; selected: string;
  onChange: (value: T) => void; idPrefix: string;
}) {
  return <View className="pc-filter-section" role="group" ariaLabel={label}>
    <Text className="pc-filter-label">{label}</Text>
    <View className="pc-filter-options">
      {items.map(item => <Button key={item.value} id={`${idPrefix}-${item.value}`} className={`pc-filter-chip ${item.value === selected ? 'pc-filter-chip--selected' : ''}`} aria-pressed={item.value === selected} ariaLabel={`${item.label}${item.value === selected ? '，已选择' : ''}`} onClick={() => onChange(item.value)}><Text>{item.label}</Text>{item.value === selected && <Text className="pc-filter-check" ariaHidden> ✓</Text>}</Button>)}
    </View>
  </View>;
}

export function CommunityFilterControls({ age, topic, onAge, onTopic }: {
  age: CommunityAgeFilter; topic: CommunityTopicFilter; onAge: (value: CommunityAgeFilter) => void; onTopic: (value: CommunityTopicFilter) => void;
}) {
  return <View className="pc-filters">
    <ChoiceGroup label="内容适用年龄" items={AGE_FILTERS} selected={age} onChange={onAge} idPrefix="pc-age" />
    <ChoiceGroup label="交流话题" items={TOPIC_FILTERS} selected={topic} onChange={onTopic} idPrefix="pc-topic" />
    <Text className="pc-form-hint">年龄只表示内容适用范围，不是健康、诊断或能力评级；浏览无需儿童档案。</Text>
  </View>;
}

export function ExampleLabel() {
  return <Text className="pc-example-label">示例内容</Text>;
}

export function PostTags({ post }: { post: Pick<CommunityPostPreview, 'age' | 'topic'> }) {
  return <View className="pc-post-tags"><Text>{ageLabel(post.age)}</Text><Text>{topicLabel(post.topic)}</Text></View>;
}

export function PostCard({ post, onOpen }: { post: CommunityPostPreview; onOpen: () => void }) {
  return <View className="pc-post-card" data-post-id={post.id} data-age-band={post.age} data-topic={post.topic} data-published-at={post.publishedAt}>
    <View className="pc-post-top"><PostTags post={post} /><ExampleLabel /></View>
    <View role="heading" aria-level="2"><Button id={`pc-open-${post.id}`} className="pc-post-title" onClick={onOpen} ariaLabel={`查看示例帖子：${post.title}`}>{post.title}</Button></View>
    <Text className="pc-post-summary">{post.summary}</Text>
    <View className="pc-post-meta"><Text>{post.author.displayName} · 合成昵称</Text><Text>{post.publishedAt.slice(0, 10)} · 示例日期</Text></View>
    <View className="pc-post-bottom"><Text>文字交流 · 产品预览</Text><Text ariaHidden>阅读详情 ↗</Text></View>
  </View>;
}
