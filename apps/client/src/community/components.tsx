import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../components/AccessibleButton';
import { AGE_FILTERS, TOPIC_FILTERS, ageLabel, topicLabel } from './constants';
import type { CommunityAgeFilter, CommunityTopicFilter } from './constants';
import type { CommunityPostPreview } from './types';
import type { CommunityMode, PublicPost, ContentStatus } from './apiTypes';
import { CONTENT_STATUS_LABELS, publicTime, textSummary } from './presentation';

export function ChoiceGroup<T extends string>({ label, items, selected, onChange, idPrefix, disabled }: {
  label: string; items: readonly { value: T; label: string }[]; selected: string;
  onChange: (value: T) => void; idPrefix: string; disabled?: boolean;
}) {
  return <View className="pc-filter-section" role="group" ariaLabel={label}>
    <Text className="pc-filter-label">{label}</Text>
    <View className="pc-filter-options">
      {items.map(item => <Button key={item.value} id={`${idPrefix}-${item.value}`} disabled={disabled} className={`pc-filter-chip ${item.value === selected ? 'pc-filter-chip--selected' : ''}`} aria-pressed={item.value === selected} ariaLabel={`${item.label}${item.value === selected ? '，已选择' : ''}`} onClick={() => onChange(item.value)}><Text>{item.label}</Text>{item.value === selected && <Text className="pc-filter-check" ariaHidden> ✓</Text>}</Button>)}
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

export function CommunityModeNote({ mode }: { mode: CommunityMode }) {
  return <View id="pc-community-mode" className="pc-preview-note pc-mode-note" role="note">
    <Text className="pc-preview-note-title">{mode === 'demo' ? 'DEMO · 社区产品预览' : 'REAL · 真实家长社区'}</Text>
    <Text>{mode === 'demo' ? '下面都是虚构的示例内容和合成家长昵称，用来体验浏览、筛选与详情。示例模式不会发布、互动或送审。' : '这里读取真实社区 API。内容经过人工审核后公开；空列表和连接错误都按真实状态显示，不会替换为示例。'}</Text>
  </View>;
}

export function ContentStatusLabel({ status }: { status: ContentStatus }) {
  return <Text className={`pc-content-status pc-content-status--${status}`}>{CONTENT_STATUS_LABELS[status]}</Text>;
}

export function PublicPostCard({ post, onOpen }: { post: PublicPost; onOpen: () => void }) {
  return <View className="pc-post-card" data-post-id={post.id} data-age-band={post.age_band} data-topic={post.topic} data-published-at={post.published_at}>
    <View className="pc-post-top"><PostTags post={{ age: post.age_band, topic: post.topic }} /><Text className="pc-content-status">真实社区 · 已审核</Text></View>
    <View role="heading" aria-level="2"><Button id={`pc-open-${post.id}`} className="pc-post-title" onClick={onOpen} ariaLabel={`查看帖子：${post.title}`}>{post.title}</Button></View>
    <Text className="pc-post-summary">{textSummary(post.body)}</Text>
    <View className="pc-post-meta"><Text>{post.author.nickname}</Text><Text>{publicTime(post.published_at)}</Text></View>
    <View className="pc-post-bottom"><Text>家长经验 · 不代表专业建议</Text><Text ariaHidden>阅读详情 ↗</Text></View>
  </View>;
}
