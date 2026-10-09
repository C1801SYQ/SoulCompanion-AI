import { useState } from 'react';
import { openTool } from '../../navigation';
import { Text, View } from '@tarojs/components';
import { AppShell } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { EmotionOrb } from '../../components/EmotionOrb';
import { HistoryList } from '../../components/HistoryList';
import { Metric, PrimaryAction, ResourceNotice, SectionCard, TextAction } from '../../components/Primitives';
import { useResource } from '../../hooks/useResource';
import { useCompanion } from '../../state/AppProvider';
import { CloudRecords } from '../../components/CloudRecords';

function HomePage() {
  const { api, source, motionEnabled } = useCompanion();
  const [navigationError, setNavigationError] = useState('');
  const snapshot = useResource(`home:snapshot:${source}`, () => api.getSnapshot(), 2500);
  const history = useResource(`home:history:${source}`, () => api.getHistory({ days: 1, limit: 3, offset: 0 }), 30000);
  const report = useResource(`home:report:${source}`, () => api.getReport(1), 60000);
  function go(page: 'session' | 'insights' | 'reports') {
    void openTool(page).catch(() => setNavigationError('页面暂时无法打开，请稍后重试。'));
  }
  const emotion = snapshot.status === 'ready' && snapshot.data?.data_available ? snapshot.data.emotion : null;
  return <AppShell page="home">
    <View className="sc-home-heading"><Text className="sc-eyebrow">{new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</Text><View className="sc-home-greeting" role="heading" aria-level="1"><Text>你好，今天也慢慢来。</Text></View><Text className="sc-page-description">每一种情绪，都值得被温柔地看见。</Text></View>
    <View className="sc-home-grid">
      <View className="sc-hero">
        <View className="sc-hero-copy"><Text className="sc-eyebrow">此刻 · 留一点时间</Text><Text className="sc-hero-title">从一小段陪伴开始。</Text><Text className="sc-hero-description">在安静的空间里，听一听、说一说，感受自己的节奏。</Text><PrimaryAction id="start-session" onClick={() => go('session')}>开始陪伴 <Text className="sc-action-arrow">↗</Text></PrimaryAction><Text className="sc-hero-footnote">进入陪伴页不会申请摄像头或麦克风权限。</Text></View>
        <EmotionOrb emotion={emotion} motionEnabled={motionEnabled} demo={source === 'demo'} />
      </View>
      <SectionCard title="今日简报" eyebrow="慢慢积累，看见变化" className="sc-daily-summary" action={<TextAction onClick={() => go('reports')}>查看报告</TextAction>}>
        <ResourceNotice {...report} />
        {report.status === 'ready' && report.data && <>
          <View className="sc-daily-metric"><Metric label="今日情绪记录" value={String(report.data.interaction_count)} detail={source === 'demo' ? '合成示例记录' : '有效情绪观察条数'} /></View>
          {report.data.data_available ? <Text className="sc-summary-text">{report.data.summary}</Text> : <Text className="sc-summary-text">今天还没有情绪记录。不必着急，我们从一次陪伴开始。</Text>}
          <View className="sc-soft-note"><Text className="sc-soft-note-title">小提醒</Text><Text>不需要急着改变情绪，给感受一点被听见的时间。</Text></View>
        </>}
      </SectionCard>
    </View>
    <ResourceNotice {...snapshot} retryId="retry-connection" />
    <CloudRecords />
    {navigationError && <View className="sc-inline-error" role="status"><Text>{navigationError}</Text></View>}
    <View className="sc-two-column sc-home-secondary">
      <SectionCard title="最近情绪记录" eyebrow="今日的几个小片刻" action={<TextAction onClick={() => go('insights')}>全部记录</TextAction>}>
        <ResourceNotice {...history} />
        {history.status === 'ready' && history.data && <HistoryList records={history.data.records} compact />}
      </SectionCard>
      <View className="sc-companion-note"><Text className="sc-eyebrow">陪伴的节奏</Text><Text className="sc-note-title">先听见，再回应。</Text><Text className="sc-note-description">一次短暂的停留，一句轻轻的回应。陪伴可以从很小的事情开始。</Text><View className="sc-note-divider" /><Text className="sc-body-muted">摄像头和麦克风只在陪伴页主动开启后工作。当前音视频仅在本地临时处理，不上传、不长期保存。DEMO 数据也可以体验本地设备预览。</Text></View>
    </View>
  </AppShell>;
}

export default withClientErrorBoundary(HomePage);
