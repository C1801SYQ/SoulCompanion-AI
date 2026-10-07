import { Text, View } from '@tarojs/components';
import { EmptyState, SectionCard } from './Primitives';
import { useCloud } from '../state/CloudProvider';
import { useSession } from '../state/SessionProvider';
import { AccessibleButton } from './AccessibleButton';
export function CloudRecords({ kind = 'summary' }: { kind?: 'summary' | 'emotions' | 'reports' }) {
  const { state, store } = useCloud();
  const { stop } = useSession();
  if (!state.enabled || state.auth.status !== 'signed_in') return null;
  const selected = state.profiles.find(profile => profile.id === state.selectedId);
  return <SectionCard title={kind === 'reports' ? '当前档案的云端报告' : kind === 'emotions' ? '当前档案的云端情绪记录' : '当前云端陪伴档案'} eyebrow="云端资料 · 与本机旧记录分开">
    {!selected ? <EmptyState title="请先选择一个陪伴档案" detail="在设置中创建或选择档案。这里不会自动选择或迁移本机记录。" /> : <View id="cloud-records"><Text id="cloud-selected-profile" className="sc-setting-name">{selected.nickname}</Text><Text className="sc-body-muted">仅同步账号资料和会话起止时间；摄像头和麦克风没有上传。</Text>
      {state.status === 'offline' || state.status === 'error' ? <View className="sc-inline-error" role="status"><Text>{state.message}</Text></View> : state.status === 'loading' ? <View role="status"><Text>正在读取云端资料…</Text></View> : kind === 'emotions' ? state.emotions.length ? state.emotions.map(item => <View key={item.id}><Text>{item.category} · {item.timestamp}</Text></View>) : <View id="cloud-emotions-empty"><EmptyState title="云端尚无情绪记录" detail="本阶段没有音视频上传或情绪推理。本机旧记录不会自动迁移。" /></View> : kind === 'reports' ? state.reports.length ? state.reports.map(item => <View key={item.id}><Text>{item.summary}</Text></View>) : <View id="cloud-reports-empty"><EmptyState title="云端还没有报告" detail="报告只基于云端已有情绪记录，不会生成虚构结论。" /></View> : <View id="cloud-session-list"><Text className="sc-body-muted">当前显示 {state.sessions.length} 条云端会话记录（最多 100 条）。</Text>{state.sessions.map((item, index) => <View key={item.id} className="sc-cloud-heading"><Text>{item.started_at} · {item.status === 'ended' ? '已结束' : '结束尚未确认'}</Text>{item.status === 'active' && <AccessibleButton id={`cloud-session-end-${index}`} className="sc-small-button" onClick={() => { void stop(); void store.endStoredSession(item.id); }}>确认结束云端会话</AccessibleButton>}</View>)}</View>}
    </View>}
  </SectionCard>;
}
