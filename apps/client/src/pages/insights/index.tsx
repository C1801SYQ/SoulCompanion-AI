import { useState } from 'react';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { HistoryList } from '../../components/HistoryList';
import { emotionLabel, timeLabel, valenceLabel } from '../../components/format';
import { EmptyState, Metric, RangeTabs, ResourceNotice, SectionCard, type Days } from '../../components/Primitives';
import { useResource } from '../../hooks/useResource';
import { useCompanion } from '../../state/AppProvider';
import { CloudRecords } from '../../components/CloudRecords';

function InsightsPage() {
  const { api, source } = useCompanion();
  const [days, setDays] = useState<Days>(7);
  const [offset, setOffset] = useState(0);
  const analytics = useResource(`insights:analytics:${source}:${days}`, () => api.getAnalytics(days), 30000);
  const history = useResource(`insights:history:${source}:${days}:${offset}`, () => api.getHistory({ days, limit: 10, offset }), 30000);
  const meaningful = analytics.status === 'ready' && analytics.data && analytics.data.total_records > 0;
  const points = analytics.data?.series || [];
  const stride = Math.max(1, Math.ceil(points.length / 40));
  const displayed = points.filter((_, index) => index % stride === 0 || index === points.length - 1);
  const counts = Object.entries(analytics.data?.counts || {}).sort((a, b) => b[1] - a[1]);
  const total = counts.reduce((sum, [, value]) => sum + value, 0);
  function changeRange(value: Days) { setDays(value); setOffset(0); }
  return <AppShell page="insights">
    <PageHeader eyebrow="INSIGHTS · 洞察" title="慢慢看见，情绪的变化。" description="从一些小片刻中回望，让感受有迹可循。" action={<RangeTabs days={days} onChange={changeRange} />} />
    <ResourceNotice {...analytics} />
    <CloudRecords kind="emotions" />
    <View className="sc-metrics-panel"><Metric label="情绪记录" value={analytics.status === 'ready' && analytics.data ? String(analytics.data.total_records) : '—'} detail={`最近 ${days} 天的观察条数`} /><Metric label="平均效价" value={meaningful && analytics.data ? valenceLabel(analytics.data.trend.average_valence) : '—'} detail="−1 到 +1，表示感受的方向" /><Metric label="平均唤醒度" value={meaningful && analytics.data ? `${Math.round(analytics.data.trend.average_arousal * 100)}%` : '—'} detail="感受的活跃程度，不代表好坏" /></View>
    <View className="sc-insights-grid">
      <SectionCard title="情绪走过的轨迹" eyebrow="效价趋势">
        {meaningful && displayed.length ? <>
          <View className="sc-trend" role="img" ariaLabel={`最近 ${days} 天效价趋势，共 ${points.length} 个样本；平均效价 ${valenceLabel(analytics.data!.trend.average_valence)}。详细记录位于下方。`}><View className="sc-trend-labels"><Text>+1</Text><Text>0</Text><Text>−1</Text></View><View className="sc-trend-plot" ariaHidden><View className="sc-trend-center" />{displayed.map((point, index) => <View className="sc-trend-column" key={`${point.timestamp}-${index}`}><View className={`sc-trend-bar ${point.valence < 0 ? 'sc-trend-bar--negative' : ''}`} style={{ height: `${Math.max(1, Math.abs(point.valence) * 45)}%`, top: point.valence < 0 ? '50%' : `${50 - Math.max(1, point.valence * 45)}%` }} /></View>)}</View></View>
          <View className="sc-chart-dates"><Text>{timeLabel(points[0].timestamp, true)}</Text><Text>{timeLabel(points[points.length - 1].timestamp, true)}</Text></View><Text className="sc-chart-description">效价描述感受偏积极或偏消极的方向。图形显示 {displayed.length} 个代表性样本，下方提供可读的原始记录。</Text>
        </> : <EmptyState title="等待情绪的第一条轨迹" detail={analytics.status === 'ready' ? '这个时间范围还没有记录，换个范围看看，或从一次陪伴开始。' : '连接恢复后，我们会显示这个范围内的真实记录。'} />}
      </SectionCard>
      <SectionCard title="感受的不同侧面" eyebrow="情绪类别分布">
        {meaningful && counts.length ? <View className="sc-distribution">{counts.map(([category, count]) => <View key={category} className="sc-distribution-row"><View className="sc-distribution-heading"><Text>{emotionLabel(category)}</Text><Text className="sc-distribution-value">{count} 条 · {Math.round(count / total * 100)}%</Text></View><View className="sc-distribution-track" ariaHidden><View style={{ width: `${count / total * 100}%` }} /></View></View>)}</View> : <EmptyState compact title="尚无类别分布" detail="有了有效情绪记录后，分布会在这里呈现。" />}
      </SectionCard>
    </View>
    <SectionCard title="情绪记录" eyebrow="每一个被看见的片刻" className="sc-history-card">
      <ResourceNotice {...history} />{history.status === 'ready' && history.data && <><HistoryList records={history.data.records} /><View className="sc-pagination"><Text id="history-summary">{history.data.total ? `共 ${history.data.total} 条记录 · 第 ${Math.floor(offset / 10) + 1} 页` : '共 0 条记录'}</Text><View className="sc-pagination-controls"><Button id="history-prev" className="sc-small-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>上一页</Button><Button id="history-next" className="sc-small-button" disabled={!history.data.has_more} onClick={() => setOffset(offset + 10)}>下一页</Button></View></View></>}
    </SectionCard>
  </AppShell>;
}

export default withClientErrorBoundary(InsightsPage);
