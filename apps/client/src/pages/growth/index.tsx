import { useState } from 'react';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { EmptyState, SectionCard, StatusPill } from '../../components/Primitives';
import { openPage } from '../../navigation';

const tools = [
  { page: 'session', title: '本地陪伴', detail: '保留原有摄像头与麦克风预览。只有你主动开始时，才会申请设备权限。' },
  { page: 'insights', title: '情绪洞察', detail: '查看已有情绪数据的范围与趋势，不是家长手动观察记录。' },
  { page: 'reports', title: '旧情绪报告', detail: '访问原有情绪报告能力，不等同于新的家庭成长记录。' },
] as const;

function GrowthPage() {
  const [navigationError, setNavigationError] = useState('');
  function openTool(page: typeof tools[number]['page']) {
    setNavigationError('');
    void openPage(`/pages/${page}/index`).catch(() => setNavigationError('暂时无法打开家庭工具，请再试一次。'));
  }

  return <AppShell page="growth">
    <PageHeader eyebrow="成长记录 · 家庭私有空间" title="把小小的变化，留给自己。" description="未来你可以主动记下亲子日常与自己的观察。记录属于你的家庭，不会自动变成社区帖子。" />
    <View className="pc-inline-note"><StatusPill tone="quiet">私有工具入口</StatusPill><Text>本页不读取儿童档案或私有报告，也不会开启摄像头和麦克风。</Text></View>
    <View className="pc-support-grid">
      <SectionCard title="家长观察记录" eyebrow="尚未接入">
        <EmptyState compact title="手动观察记录还在准备中" detail="目前展示功能入口，暂不能新建、查看或保存手动观察。原有情绪数据不会自动转成家长记录。" />
      </SectionCard>
      <SectionCard title="记录之前，你有选择" eyebrow="由你决定写什么">
        <View className="pc-preview-placeholder"><Text className="sc-setting-name">先记录感受，再慢慢整理</Text><Text className="sc-body-muted">未来的观察记录将由家长主动填写，而不是通过摄像头、模型或社区内容自动生成。</Text><Text className="sc-body-muted">家庭记录与公开交流分开。你不必为了逛社区而建立儿童档案。</Text></View>
      </SectionCard>
    </View>
    <SectionCard title="已有家庭工具" eyebrow="保留旧能力 · 按需进入">
      <Text className="pc-form-hint">以下是原有陪伴、洞察与情绪报告。它们是可选工具，不是新社区功能，也不是新的手动观察记录。进入旧工具后会按原有数据模式读取对应信息。</Text>
      <View className="pc-tool-list">{tools.map(tool => <Button id={`pc-tool-${tool.page}`} key={tool.page} className="pc-tool-button" onClick={() => openTool(tool.page)} ariaLabel={`打开${tool.title}`}><View className="pc-tool-heading"><Text className="sc-setting-name">{tool.title}</Text><Text ariaHidden>进入 ↗</Text></View><Text className="sc-body-muted">{tool.detail}</Text></Button>)}</View>
      {navigationError && <View className="sc-resource-notice sc-resource-notice--error" role="status"><Text>{navigationError}</Text></View>}
    </SectionCard>
  </AppShell>;
}

export default withClientErrorBoundary(GrowthPage);
