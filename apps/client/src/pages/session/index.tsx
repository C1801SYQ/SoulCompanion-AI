import { Text, View } from '@tarojs/components';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { EmotionOrb } from '../../components/EmotionOrb';
import { EmptyState, ResourceNotice, SectionCard, StatusPill } from '../../components/Primitives';
import { useResource } from '../../hooks/useResource';
import { useCompanion } from '../../state/AppProvider';

function SessionPage() {
  const { api, source, motionEnabled } = useCompanion();
  const snapshot = useResource(`session:snapshot:${source}`, () => api.getSnapshot(), 2500);
  const emotion = snapshot.status === 'ready' && snapshot.data?.data_available ? snapshot.data.emotion : null;
  return <AppShell page="session">
    <PageHeader eyebrow="COMPANIONSHIP · 陪伴" title="留一点时间，陪伴当下。" description="在这里，我们可以慢慢说，也可以安静地待一会儿。" action={<StatusPill>尚未开始采集</StatusPill>} />
    <View className="sc-session-notice"><Text className="sc-notice-title">这是陪伴界面的预览</Text><Text>摄像头、麦克风与会话处理将在后续阶段接入。当前没有录音、录像或音视频上传；进入页面不会申请权限。</Text></View>
    <View className="sc-session-grid">
      <View className="sc-preview-card"><View className="sc-preview"><View className="sc-preview-outline" ariaHidden><View className="sc-preview-person" /></View><Text className="sc-preview-title">你的陪伴空间</Text><Text className="sc-preview-caption">摄像头未启用 · 没有预览画面</Text></View><View className="sc-device-strip"><StatusPill id="camera-status">Camera OFF · 未申请权限</StatusPill><StatusPill id="microphone-status">Mic OFF · 未申请权限</StatusPill></View><View className="sc-preview-footer"><Text>会话未开始</Text><Text>媒体能力待接入</Text></View></View>
      <SectionCard title="此刻的情绪" eyebrow={source === 'demo' ? '合成示例，不来自本次会话' : '现有服务观察，不来自本次会话'}>
        <ResourceNotice {...snapshot} /><EmotionOrb emotion={emotion} motionEnabled={motionEnabled} compact demo={source === 'demo'} /><Text className="sc-body-muted">情绪是一种观察线索，不需要急着给自己下结论。</Text>
      </SectionCard>
    </View>
    <View className="sc-two-column sc-session-notes"><SectionCard title="你说的话" eyebrow="语音转写"><EmptyState title="先从一句话开始" detail="当前未录音，没有语音转写内容。媒体接入后，你可以自主开始或停止。" /></SectionCard><SectionCard title="轻轻的回应" eyebrow="AI 陪伴"><EmptyState title="回应会在这里出现" detail="当前没有发送会话请求，也没有生成本次会话的 AI 回复。" /></SectionCard></View>
  </AppShell>;
}

export default withClientErrorBoundary(SessionPage);
