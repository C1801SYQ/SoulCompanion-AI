import { useState } from 'react';
import { Text, View } from '@tarojs/components';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { EmptyState, SectionCard, StatusPill } from '../../components/Primitives';
import { ChoiceGroup } from '../../community/components';
import { AGE_FILTERS, TOPIC_FILTERS, ageLabel, topicLabel } from '../../community/constants';
import type { CommunityAgeFilter, CommunityTopicFilter } from '../../community/constants';

function KnowledgePage() {
  const [age, setAge] = useState<CommunityAgeFilter>('all');
  const [topic, setTopic] = useState<CommunityTopicFilter>('all');
  const selection = `${age === 'all' ? '全部年龄' : ageLabel(age)} · ${topic === 'all' ? '全部生活情境' : topicLabel(topic)}`;

  return <AppShell page="knowledge">
    <PageHeader eyebrow="育儿知识 · 产品预览" title="陪你一起，慢慢了解孩子。" description="从年龄与日常情境出发，寻找你关心的内容。这里面向 0～18 岁儿童家庭，无需先建立儿童档案。" />
    <View className="pc-inline-note"><StatusPill tone="warm">内容入口预览</StatusPill><Text>这里正在整理分龄与分类结构，尚无已核实来源的知识文章，也未接入专家服务。</Text></View>
    <View className="pc-support-grid">
      <SectionCard title="孩子处在哪个阶段" eyebrow="分龄导航">
        <ChoiceGroup label="知识内容适用年龄" items={AGE_FILTERS} selected={age} onChange={setAge} idPrefix="pc-knowledge-age" />
        <Text className="pc-form-hint">年龄只是内容适用范围，不是健康、诊断或能力评级。</Text>
      </SectionCard>
      <SectionCard title="今天关心的日常" eyebrow="内容分类">
        <ChoiceGroup label="知识生活情境" items={TOPIC_FILTERS} selected={topic} onChange={setTopic} idPrefix="pc-knowledge-topic" />
        <Text className="pc-form-hint">你可以自由切换年龄和生活情境，选择不会读取任何家庭资料。</Text>
      </SectionCard>
    </View>
    <SectionCard title="适合当前选择的内容" eyebrow="来源核实后再呈现">
      <View id="pc-knowledge-selection" role="status"><Text className="pc-form-hint">当前选择：{selection}</Text></View>
      <EmptyState title="这里暂时还没有内容" detail="当前只有分类入口。我们会在核实文章来源与适用范围后，再提供可阅读的内容；这页暂不提供专业建议。" />
    </SectionCard>
  </AppShell>;
}

export default withClientErrorBoundary(KnowledgePage);
