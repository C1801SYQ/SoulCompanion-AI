import { useEffect, useRef, useState } from 'react';
import { Text, View } from '@tarojs/components';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { dayLabel } from '../../components/format';
import { EmptyState, PrimaryAction, RangeTabs, ResourceNotice, SectionCard, StatusPill, type Days } from '../../components/Primitives';
import { useResource } from '../../hooks/useResource';
import { exportMarkdown } from '../../platform/export';
import { useCompanion } from '../../state/AppProvider';
import { CloudRecords } from '../../components/CloudRecords';

function ReportNotes({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? <View className="sc-report-notes">{items.map((item, index) => <View className="sc-report-note" key={`${index}-${item}`}><Text className="sc-report-note-number">{String(index + 1).padStart(2, '0')}</Text><Text>{item}</Text></View>)}</View> : <Text className="sc-body-muted">{empty}</Text>;
}

function ReportsPage() {
  const { api, source } = useCompanion();
  const [days, setDays] = useState<Days>(7);
  const [exportStatus, setExportStatus] = useState('');
  const [exporting, setExporting] = useState(false);
  const generation = useRef(0);
  const pending = useRef<(() => void) | null>(null);
  const report = useResource(`reports:${source}:${days}`, () => api.getReport(days), 60000);
  useEffect(() => {
    setExportStatus(''); setExporting(false);
    return () => { generation.current += 1; pending.current?.(); pending.current = null; };
  }, [source, days]);
  function changeRange(value: Days) {
    if (value === days) return;
    generation.current += 1;
    pending.current?.(); pending.current = null;
    setExportStatus(''); setExporting(false); setDays(value);
  }
  async function download() {
    if (exporting || report.status !== 'ready') return;
    const current = ++generation.current;
    const requestedDays = days;
    const requestedSource = source;
    setExporting(true); setExportStatus('');
    const handle = api.getMarkdown(requestedDays);
    pending.current = handle.cancel;
    try {
      const markdown = await handle.promise;
      if (generation.current !== current) return;
      const result = await exportMarkdown(markdown, `soulcompanion-${requestedSource}-${requestedDays}days.md`);
      if (generation.current === current) setExportStatus(result === 'downloaded' ? 'Markdown 报告已导出。' : '报告已复制到剪贴板，可粘贴保存。');
    } catch {
      if (generation.current === current) setExportStatus('导出暂时没有完成，请稍后再试。');
    } finally {
      if (generation.current === current) { setExporting(false); pending.current = null; }
    }
  }
  return <AppShell page="reports">
    <PageHeader eyebrow="REPORTS · 报告" title="把陪伴，轻轻记下来。" description="回顾一段时间的情绪观察，给下一次陪伴一点参考。" action={<RangeTabs days={days} onChange={changeRange} />} />
    <ResourceNotice {...report} />
    <CloudRecords kind="reports" />
    <View className="sc-report-toolbar"><StatusPill tone={source === 'demo' ? 'warm' : 'quiet'}>{source === 'demo' ? '合成示例报告' : '真实情绪记录报告'}</StatusPill><PrimaryAction id="report-export" onClick={() => void download()} disabled={report.status !== 'ready' || exporting}>{exporting ? '正在导出…' : '导出 Markdown'}</PrimaryAction></View>
    {exportStatus && <View className="sc-export-status" role="status"><Text>{exportStatus}</Text></View>}
    {report.status === 'ready' && report.data && <>
      <View className="sc-report-cover"><Text className="sc-eyebrow">这一段日常 · 最近 {days} 天</Text><Text className="sc-report-period">{dayLabel(report.data.period_start)} — {dayLabel(report.data.period_end)}</Text><Text className="sc-report-summary">{report.data.data_available ? report.data.summary : '这个时间范围还没有情绪观察。报告会随着有效记录慢慢积累。'}</Text><Text className="sc-report-source">基于 {report.data.interaction_count} 条情绪记录{source === 'demo' ? ' · 全部为合成示例' : ''}。记录条数不代表陪伴会话次数。</Text></View>
      {!report.data.data_available ? <SectionCard title="给下一次陪伴留一点空间"><EmptyState title="不急着总结，也是一种陪伴" detail="有了有效情绪观察后，这里会呈现摘要、值得留意的片刻与陪伴建议。" /></SectionCard> : <>
        <View className="sc-two-column"><SectionCard title="值得记住的小片刻" eyebrow="亮点"><ReportNotes items={report.data.highlights} empty="这个范围内暂无特别记录的亮点。" /></SectionCard><SectionCard title="值得温柔留意" eyebrow="观察线索"><ReportNotes items={report.data.concerns} empty="这个范围内暂无需要特别留意的线索。" /></SectionCard></View>
        <SectionCard title="下一次，可以这样陪伴" eyebrow="陪伴建议" className="sc-report-suggestions"><ReportNotes items={report.data.suggestions} empty="暂无新的建议。先从倾听、尊重和舒适的节奏开始。" /></SectionCard>
      </>}
      <Text className="sc-report-disclaimer">报告根据当前可用记录整理，可能不完整。它帮助回顾日常，不提供临床判断。</Text>
    </>}
  </AppShell>;
}

export default withClientErrorBoundary(ReportsPage);
