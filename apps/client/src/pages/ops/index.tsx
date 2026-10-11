import { useEffect, useRef, useState } from 'react';
import { useDidShow } from '@tarojs/taro';
import { Text, Textarea, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { EmptyState, SectionCard } from '../../components/Primitives';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { useCommunity } from '../../state/CommunityProvider';
import { useCloud } from '../../state/CloudProvider';
import { CommunityAccountPanel } from '../../community/AccountPanel';
import { CommunityError, type ContentKind, type ContentStatus, type OpsContent, type OpsReport } from '../../community/apiTypes';
import { backToCommunity } from '../../navigation';

const contentStates: ReadonlyArray<{ value: ContentStatus; label: string }> = [
  { value: 'pending', label: '待审核' }, { value: 'published', label: '已公开' },
  { value: 'rejected', label: '已拒绝' }, { value: 'hidden', label: '已隐藏' }, { value: 'deleted', label: '已撤回' },
];
const reportStates = [{ value: 'open', label: '待处理' }, { value: 'resolved', label: '已处理' }, { value: 'dismissed', label: '已驳回' }] as const;
type Decision = 'approve' | 'reject' | 'hide';
type ReportDecision = 'resolved' | 'dismissed';
type Unconfirmed = { kind: ContentKind; id: string; action: Decision; revision: number; reason: string; key: string }
  | { kind: 'report'; id: string; action: ReportDecision; revision: number; reason: string; key: string };
interface Workspace {
  epoch: number; gate: 'checking' | 'authorized' | 'denied' | 'error';
  contents: OpsContent[]; reports: OpsReport[]; cursor: string | null; reportCursor: string | null;
  selected: OpsContent | null; selectedReport: OpsReport | null; error: string; message: string; uncertain: Unconfirmed | null;
}
const empty = (epoch: number): Workspace => ({ epoch, gate: 'checking', contents: [], reports: [], cursor: null, reportCursor: null,
  selected: null, selectedReport: null, error: '', message: '', uncertain: null });

/** Direct, server-authorized route. There is intentionally no ordinary navigation entry. */
function ModerationPage() {
  const { state, store, api } = useCommunity();
  const { state: cloud } = useCloud();
  const epoch = cloud.auth.epoch;
  const [workspace, setWorkspace] = useState<Workspace>(() => empty(epoch));
  // Taro can retain page frames. An account change hides all protected data in this render.
  const visible = workspace.epoch === epoch ? workspace : empty(epoch);
  const [tab, setTab] = useState<'content' | 'reports'>('content');
  const [kind, setKind] = useState<ContentKind>('post');
  const [status, setStatus] = useState<ContentStatus>('pending');
  const [reportStatus, setReportStatus] = useState<'open' | ReportDecision>('open');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const signedIn = cloud.auth.status === 'signed_in';
  const patch = (values: Partial<Workspace>) => setWorkspace(previous => ({ ...(previous.epoch === epoch ? previous : empty(epoch)), ...values }));
  function clearDetail() {
    detailGeneration.current++;
    patch({ selected: null, selectedReport: null, error: '', message: '' });
    setReason('');
  }
  function fail(error: unknown) {
    if (error instanceof CommunityError && error.kind === 'cancelled') return;
    if (error instanceof CommunityError && error.status === 403) {
      detailGeneration.current++;
      generation.current++;
      busyRef.current = false; setBusy(false); setReason('');
      setWorkspace({ ...empty(epoch), gate: 'denied', error: '此账号没有社区运营权限。请联系已授权的项目负责人。' });
    } else patch({ error: error instanceof Error ? error.message : '审核服务暂时不可用。' });
  }
  async function queue(more = false) {
    if (!api || !signedIn || busyRef.current || visible.uncertain) return;
    if (!more) clearDetail();
    busyRef.current = true; setBusy(true);
    const version = ++generation.current, snapshot = store.capture();
    try {
      const result = await store.run(api.opsQueue(status, { limit: 20, ...(more && visible.cursor ? { cursor: visible.cursor } : {}) }), { private: true, key: 'ops-queue' });
      if (!store.isCurrent(snapshot) || version !== generation.current) return;
      patch({ gate: 'authorized', contents: more ? merge(visible.contents, result.items) : result.items,
        cursor: result.next_cursor, error: '' });
    } catch (error) { if (store.isCurrent(snapshot) && version === generation.current) { fail(error); if (!(error instanceof CommunityError && error.status === 403)) patch({ gate: 'error' }); } }
    finally { if (version === generation.current) { busyRef.current = false; setBusy(false); } }
  }
  async function reports(more = false) {
    if (!api || !signedIn || visible.gate !== 'authorized' || busyRef.current || visible.uncertain) return;
    if (!more) clearDetail();
    busyRef.current = true; setBusy(true);
    const version = ++generation.current, snapshot = store.capture();
    try {
      const result = await store.run(api.opsReports(reportStatus, { limit: 20, ...(more && visible.reportCursor ? { cursor: visible.reportCursor } : {}) }), { private: true, key: 'ops-reports' });
      if (store.isCurrent(snapshot) && version === generation.current) patch({ reports: more ? merge(visible.reports, result.items) : result.items, reportCursor: result.next_cursor, error: '' });
    } catch (error) { if (store.isCurrent(snapshot) && version === generation.current) fail(error); }
    finally { if (version === generation.current) { busyRef.current = false; setBusy(false); } }
  }
  useEffect(() => {
    generation.current++; detailGeneration.current++; busyRef.current = false; setBusy(false); setReason(''); setWorkspace(empty(epoch));
    if (state.mode === 'real' && signedIn) void queue();
    return () => { generation.current++; detailGeneration.current++; };
  }, [epoch, signedIn, status, state.mode]);
  useEffect(() => { if (tab === 'reports' && visible.gate === 'authorized') void reports(); }, [tab, reportStatus, visible.gate]);
  useDidShow(() => { if (state.mode === 'real' && signedIn && !visible.uncertain) void queue(); });
  async function inspect(content: Pick<OpsContent, 'kind' | 'id'>) {
    if (!api || busyRef.current || visible.uncertain) return;
    const snapshot = store.capture(), version = ++detailGeneration.current;
    patch({ selected: null, selectedReport: null, error: '', message: '' }); setReason('');
    try {
      const result = await store.run(api.opsContent(content.kind, content.id), { private: true, key: 'ops-detail' });
      if (store.isCurrent(snapshot) && version === detailGeneration.current) patch({ selected: result });
    } catch (error) { if (store.isCurrent(snapshot) && version === detailGeneration.current) fail(error); }
  }
  async function execute(action?: Decision | ReportDecision) {
    if (!api || !signedIn || visible.gate !== 'authorized' || busyRef.current) return;
    busyRef.current = true; setBusy(true);
    const snapshot = store.capture();
    let operation = visible.uncertain;
    try {
      if (!operation) {
        const target = visible.selectedReport ?? visible.selected;
        if (!target || !action || !reason.trim()) { patch({ error: '请检查全文，并填写 1～200 字的审核理由。' }); return; }
        const targetKind = visible.selectedReport ? 'report' : visible.selected!.kind;
        const revision = visible.selectedReport ? visible.selectedReport.report_revision : visible.selected!.content_revision;
        const input = { expected_revision: revision, reason: reason.trim(), ...(targetKind === 'report' ? { decision: action } : {}) };
        const logical = await store.action(`ops-${targetKind}-${target.id}-${action}`, input);
        if (!store.isCurrent(snapshot)) return;
        operation = { kind: targetKind, id: target.id, revision, reason: reason.trim(), action, key: logical.key } as Unconfirmed;
      }
      patch({ error: '', message: '' });
      if (operation.kind === 'report') {
        const result = await store.run(api.resolveReport(operation.id, operation.revision, operation.action, operation.reason, operation.key), { private: true });
        if (!store.isCurrent(snapshot)) return;
        if (!result.action_applied || !result.report) throw new CommunityError('invalid');
        patch({ selectedReport: result.report, reports: visible.reports.filter(item => item.id !== operation!.id), uncertain: null,
          message: `处理回执已确认；举报当前状态：${result.report.status}。内容是否隐藏需独立操作。` });
      } else {
        const result = await store.run(api.moderate(operation.kind, operation.id, operation.action, operation.revision, operation.reason, operation.key), { private: true });
        if (!store.isCurrent(snapshot)) return;
        if (!result.action_applied || !result.content) throw new CommunityError('invalid');
        patch({ selected: result.content, contents: visible.contents.filter(item => item.id !== operation!.id), uncertain: null,
          message: `动作回执已确认；内容当前状态：${result.content.status}，正文版本 ${result.content.content_revision}。` });
        void store.refreshFeed();
      }
      store.clearAction(`ops-${operation.kind}-${operation.id}-${operation.action}`); setReason('');
    } catch (error) {
      if (!store.isCurrent(snapshot)) return;
      if (operation && error instanceof CommunityError && (error.status === 503 || error.kind === 'offline')) {
        patch({ uncertain: operation, error: '状态尚未确认。原审核对象、版本、理由与动作键已保留；仅可同输入安全重试。' });
      } else { fail(error); patch({ uncertain: null }); }
    } finally { if (store.isCurrent(snapshot)) { busyRef.current = false; setBusy(false); } }
  }

  const selected = visible.selected;
  const selectedReport = visible.selectedReport;
  return <AppShell page="ops">
    <Button className="pc-action" onClick={() => { void backToCommunity().catch(() => patch({ error: '暂时无法返回，请使用主导航。' })); }}>返回社区</Button>
    <PageHeader eyebrow="受限工作台 · 人工审核" title="让每一条分享被认真看见。" description="访问与每次操作均由服务端校验运营角色；这里不会授予角色，也没有 AI 自动审核。" />
    {state.mode === 'demo' ? <EmptyState title="DEMO 不连接运营服务" detail="本构建只提供合成社区预览，不提供虚假审核结果。" /> : <>
      <CommunityAccountPanel />
      {!signedIn ? <EmptyState title="请先登录授权的运营账号" detail="普通家长账户登录后仍需要服务端运营授权。" /> : <>
        {visible.error && <View id="ops-error" className="sc-resource-notice sc-resource-notice--error" role="status"><Text>{visible.error}</Text></View>}
        {visible.message && <View id="ops-message" className="pc-inline-note" role="status"><Text>{visible.message}</Text></View>}
        {visible.gate !== 'authorized' ? <View><Text>{visible.gate === 'checking' ? '正在核验运营权限…' : '受保护内容尚未开放。'}</Text><Button id="ops-retry" className="pc-action" disabled={busy} onClick={() => { void queue(); }}>重新核验</Button></View> : <>
          <View className="pc-compose-actions" role="group" ariaLabel="工作台区域">
            <Button id="ops-tab-content" className="pc-action" aria-pressed={tab === 'content'} disabled={busy || Boolean(visible.uncertain)} onClick={() => { clearDetail(); setTab('content'); }}>内容审核</Button>
            <Button id="ops-tab-reports" className="pc-action" aria-pressed={tab === 'reports'} disabled={busy || Boolean(visible.uncertain)} onClick={() => { clearDetail(); setTab('reports'); }}>举报处理</Button>
          </View>
          {tab === 'content' ? <>
            <View className="pc-compose-actions" role="group" ariaLabel="内容类型">{(['post', 'comment'] as const).map(value => <Button key={value} id={`ops-kind-${value}`} className="pc-action" aria-pressed={kind === value} disabled={busy || Boolean(visible.uncertain)} onClick={() => { clearDetail(); setKind(value); }}>{value === 'post' ? '帖子' : '一级评论'}</Button>)}</View>
            <View className="pc-compose-actions" role="group" ariaLabel="审核状态">{contentStates.map(item => <Button key={item.value} id={`ops-status-${item.value}`} className="pc-action" aria-pressed={status === item.value} disabled={busy || Boolean(visible.uncertain)} onClick={() => { clearDetail(); patch({ contents: [], cursor: null }); setStatus(item.value); }}>{item.label}</Button>)}</View>
            <Button id="ops-refresh" className="pc-action" disabled={busy || Boolean(visible.uncertain)} onClick={() => { void queue(); }}>刷新队列</Button>
            <View className="pc-owner-list">{visible.contents.filter(item => item.kind === kind).map(item => <Button key={item.id} id={`ops-content-${item.id}`} className="pc-tool-button" disabled={Boolean(visible.uncertain)} onClick={() => { void inspect(item); }}><Text className="pc-tool-heading">{'title' in item ? item.title : item.body}</Text><Text>{item.author.nickname} · {item.status} · 正文版本 {item.content_revision}</Text></Button>)}</View>
            {!visible.contents.some(item => item.kind === kind) && <EmptyState title="本页没有此类内容" detail={visible.cursor ? '混合队列还有下一页，可继续加载；这里不代表整个队列为空。' : '当前筛选下没有更多待处理内容。'} compact />}
            {visible.cursor && <Button id="ops-more" className="pc-action" disabled={busy || Boolean(visible.uncertain)} onClick={() => { void queue(true); }}>加载下一页</Button>}
          </> : <>
            <View className="pc-compose-actions" role="group" ariaLabel="举报状态">{reportStates.map(item => <Button key={item.value} id={`ops-report-status-${item.value}`} className="pc-action" aria-pressed={reportStatus === item.value} disabled={busy || Boolean(visible.uncertain)} onClick={() => { clearDetail(); patch({ reports: [], reportCursor: null }); setReportStatus(item.value); }}>{item.label}</Button>)}</View>
            <Button id="ops-reports-refresh" className="pc-action" disabled={busy || Boolean(visible.uncertain)} onClick={() => { void reports(); }}>刷新举报</Button>
            <View className="pc-owner-list">{visible.reports.map(item => <Button key={item.id} id={`ops-report-${item.id}`} className="pc-tool-button" disabled={Boolean(visible.uncertain)} onClick={() => { clearDetail(); patch({ selectedReport: item }); }}><Text className="pc-tool-heading">{item.reason} · {item.status}</Text><Text>{item.detail || '未补充说明'} · 处理版本 {item.report_revision}</Text></Button>)}</View>
            {!visible.reports.length && <EmptyState title="本页没有举报" detail={visible.reportCursor ? '还有下一页，可继续加载。' : '当前状态下没有举报。'} compact />}
            {visible.reportCursor && <Button id="ops-reports-more" className="pc-action" disabled={busy || Boolean(visible.uncertain)} onClick={() => { void reports(true); }}>加载下一页</Button>}
          </>}
          {(selected || selectedReport) && <SectionCard title={selected && 'title' in selected ? selected.title : selected ? '评论全文检查' : '举报处理'} eyebrow="当前内容与版本">
            {selected && <><Text className="pc-plain-text" id="ops-full-body">{selected.body}</Text><Text>公开作者：{selected.author.nickname} · {selected.status} · 正文版本 {selected.content_revision}</Text>
              <View className="pc-inline-note"><Text>请检查儿童姓名、学校、住址与联系方式，骚扰、危险内容，以及缺乏支持的诊断或治疗断言。请阅读全文后再做决定。</Text></View>
              <View>{selected.audit.map((event, index) => <Text className="pc-history-line" key={index}>{event.action} · {event.reason} · {event.at} · 版本 {event.target_revision}</Text>)}</View><Button id="ops-detail-refresh" className="pc-action" disabled={busy || Boolean(visible.uncertain)} onClick={() => { void inspect(selected); }}>重新读取当前版本</Button></>}
            {selectedReport && <><Text className="pc-plain-text">{selectedReport.detail || '未补充说明'}</Text><Text>举报原因 {selectedReport.reason} · {selectedReport.status} · 处理版本 {selectedReport.report_revision}</Text><Text className="sc-body-muted">处理举报不会自动隐藏内容。如需检查或隐藏目标，请独立打开目标内容。</Text><Button id="ops-inspect-report-target" className="pc-action" disabled={busy || Boolean(visible.uncertain)} onClick={() => { void inspect({ kind: selectedReport.target_type, id: selectedReport.target_id }); setTab('content'); }}>检查目标全文</Button></>}
            <View className="pc-form-field"><Text className="pc-field-label">审核理由（1～200 字）</Text><Textarea id="ops-reason" className="pc-textarea pc-textarea--compact" ariaLabel="审核理由" value={reason} maxlength={-1} disabled={busy || Boolean(visible.uncertain)} onInput={event => setReason(event.detail.value)} /></View>
            <View className="pc-compose-actions">
              {selected && !visible.uncertain && <>{selected.status === 'pending' && <><Button id="ops-approve" className="pc-action pc-action--primary" disabled={busy} onClick={() => { void execute('approve'); }}>通过审核</Button><Button id="ops-reject" className="pc-action" disabled={busy} onClick={() => { void execute('reject'); }}>拒绝审核</Button></>}{['pending', 'published', 'rejected'].includes(selected.status) && <Button id="ops-hide" className="pc-action" disabled={busy} onClick={() => { void execute('hide'); }}>独立隐藏内容</Button>}</>}
              {selectedReport?.status === 'open' && !visible.uncertain && <><Button id="ops-resolve" className="pc-action" disabled={busy} onClick={() => { void execute('resolved'); }}>标记已处理</Button><Button id="ops-dismiss" className="pc-action" disabled={busy} onClick={() => { void execute('dismissed'); }}>驳回举报</Button></>}
              {visible.uncertain && <Button id="ops-safe-retry" className="pc-action" disabled={busy} onClick={() => { void execute(); }}>同输入安全重试</Button>}
            </View>
          </SectionCard>}
        </>}
      </>}
    </>}
  </AppShell>;
}
function merge<T extends { id: string }>(previous: T[], next: T[]): T[] {
  return [...new Map([...previous, ...next].map(item => [item.id, item])).values()].slice(-200);
}
export default withClientErrorBoundary(ModerationPage);
