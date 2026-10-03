import { useEffect, useRef, useState } from 'react';
import { useDidHide } from '@tarojs/taro';
import { Text, View } from '@tarojs/components';
import { AppShell, PageHeader } from '../../components/AppShell';
import { AccessibleButton } from '../../components/AccessibleButton';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { MediaChoice } from '../../components/SessionControls';
import { deviceText, mediaProblemText, permissionText, previewText, sessionText, stoppedSessionText } from '../../components/mediaText';
import { EmptyState, PrimaryAction, SectionCard, StatusPill } from '../../components/Primitives';
import { MediaPreview } from '../../media/MediaPreview';
import type { CameraFacing, CameraOption, MediaSelection, MediaStopReason } from '../../media/types';
import { useCompanion } from '../../state/AppProvider';
import { useSession } from '../../state/SessionProvider';

function SessionPage() {
  const { source } = useCompanion();
  const { adapter, state, start, stop } = useSession();
  const [selection, setSelection] = useState<MediaSelection>({ camera: true, microphone: true, facing: 'user' });
  const [unexpectedFailure, setUnexpectedFailure] = useState('');
  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [cameraListError, setCameraListError] = useState('');
  const cameraListEpoch = useRef(0);
  const busy = state.phase === 'starting' || state.phase === 'active' || state.phase === 'stopping';
  const anySelected = selection.camera || selection.microphone;
  const canStart = !busy && anySelected && state.problem !== 'cleanup_failed';
  const canStop = state.phase === 'starting' || state.phase === 'active'
    || state.capture.camera.state === 'on' || state.capture.microphone.state === 'on' || state.problem === 'cleanup_failed';
  async function end(reason: MediaStopReason = 'user') {
    try { await stop(reason); }
    catch { setUnexpectedFailure('设备停止暂未确认完成。请关闭本页，并检查系统的摄像头和麦克风指示。'); }
  }
  useEffect(() => () => { cameraListEpoch.current += 1; void stop('unmount'); }, [stop]);
  async function refreshCameras() {
    const current = ++cameraListEpoch.current;
    try {
      const available = await adapter.listCameras();
      if (current !== cameraListEpoch.current) return;
      setCameras(available);
      setCameraListError(available.length ? '' : '当前没有可列出的摄像头，仍可使用前置或后置选项尝试。');
    } catch {
      if (current === cameraListEpoch.current) setCameraListError('摄像头列表暂时无法读取，仍可使用方向选项。');
    }
  }
  useEffect(() => {
    if (state.capture.camera.permission === 'granted') void refreshCameras();
  }, [adapter, state.capture.camera.permission]);
  useDidHide(() => { void end('background'); });
  async function begin() {
    if (!canStart) return;
    setUnexpectedFailure('');
    try { await start(selection); }
    catch {
      setUnexpectedFailure('本次没有成功开始。请稍后重试。');
      await end('device_error');
    }
  }
  function choose(device: 'camera' | 'microphone') {
    if (busy) return;
    setSelection(current => ({ ...current, [device]: !current[device] }));
  }
  function chooseFacing(facing: CameraFacing) {
    if (!busy) setSelection(current => ({ ...current, facing, cameraDeviceId: undefined }));
  }
  const problem = mediaProblemText(state.problem);
  const stopped = stoppedSessionText(state);
  const guidance = !anySelected ? '请至少选择摄像头或麦克风中的一种。'
        : state.phase === 'starting' ? '请在权限窗口中选择。你也可以随时停止等待；迟到的授权不会继续已取消的采集。'
          : busy ? '本次媒体仅在本地临时处理，不上传、不长期保存。'
            : '点击开始后才申请所选设备权限。每次停止后，都需要再次主动开始。';
  return <AppShell page="session">
    <View className="sc-device-session-header"><PageHeader eyebrow="COMPANIONSHIP · 陪伴" title="留一点时间，陪伴当下。" description="摄像头和麦克风仅在你主动开始陪伴后启用。" /></View>
    <View className="sc-local-session-controls">
      <View className="sc-local-session-heading"><Text className="sc-eyebrow">LOCAL DEVICE ONLY · 本地设备预览</Text><StatusPill id="session-status" tone={state.phase === 'active' ? 'good' : state.phase === 'error' ? 'warm' : 'quiet'}>{sessionText(state)}</StatusPill></View>
      <View className="sc-device-strip"><StatusPill id="camera-status" tone={state.capture.camera.state === 'on' ? 'good' : 'quiet'}>{deviceText('Camera', state.capture.camera)}</StatusPill><StatusPill id="microphone-status" tone={state.capture.microphone.state === 'on' ? 'good' : 'quiet'}>{deviceText('Mic', state.capture.microphone)}</StatusPill></View>
      <View className="sc-media-actions"><PrimaryAction id="session-start" disabled={!canStart} onClick={() => void begin()}>{state.phase === 'starting' ? '等待权限…' : '开始陪伴'}</PrimaryAction><AccessibleButton id="session-stop" className="sc-media-stop" disabled={!canStop || state.phase === 'stopping'} onClick={() => void end()}>结束陪伴</AccessibleButton></View>
      <Text className="sc-local-session-privacy">NO MEDIA UPLOAD · 当前音视频不会上传</Text>
      {(problem || unexpectedFailure) && <View className="sc-media-error" id="media-problem" role="status"><Text>{unexpectedFailure || problem}</Text></View>}
      {stopped && <View className="sc-media-guidance" id="media-stopped-reason" role="status"><Text>{stopped}</Text></View>}
    </View>
    <View className="sc-session-grid">
      <View className="sc-preview-card">
        <MediaPreview adapter={adapter} status={state.capture} facing={state.selection.facing} />
        <View className="sc-preview-footer"><Text>{previewText(state)}</Text><Text>未上传 · 不长期保存</Text></View>
        <View className="sc-media-statistics"><Text id="media-frame-count">图像采样 {state.videoFrames} 帧</Text><Text id="media-audio-count">音频采样 {state.audioChunks} 段</Text></View>
        <View className="sc-input-level"><Text id="microphone-input-level">麦克风输入强度 · {state.inputLevel === null ? '尚未获得读数' : `${Math.round(Math.max(0, Math.min(1, state.inputLevel)) * 100)}%`}</Text><View className="sc-input-level-track" ariaHidden><View className="sc-input-level-fill" style={{ transform: `scaleX(${state.inputLevel === null ? 0 : Math.max(0, Math.min(1, state.inputLevel))})` }} /></View><Text className="sc-input-level-note">只表示声音输入强度，不代表情绪。</Text></View>
      </View>
      <SectionCard title="选择你的陪伴方式" eyebrow="开始前，先确认">
        <View className="sc-media-options"><MediaChoice id="camera-enabled" title="摄像头" note="显示本机预览，低频采样" selected={selection.camera} disabled={busy} onClick={() => choose('camera')} /><MediaChoice id="microphone-enabled" title="麦克风" note="短片段采样，不长期保存" selected={selection.microphone} disabled={busy} onClick={() => choose('microphone')} /></View>
        <View className="sc-media-facing"><Text className="sc-media-facing-label">摄像头方向</Text><View className="sc-media-facing-buttons" role="group" ariaLabel="摄像头方向">{(['user', 'environment'] as const).map(facing => <AccessibleButton key={facing} id={`camera-facing-${facing}`} className={`sc-media-facing-button ${selection.facing === facing ? 'sc-media-facing-button--selected' : ''}`} aria-pressed={selection.facing === facing} disabled={busy || !selection.camera} onClick={() => chooseFacing(facing)}>{facing === 'user' ? '前置' : '后置'}</AccessibleButton>)}</View></View>
        <View className="sc-camera-list"><View className="sc-camera-list-heading"><Text className="sc-media-facing-label">可用摄像头</Text><AccessibleButton id="camera-list-refresh" className="sc-small-button" disabled={busy} onClick={() => void refreshCameras()}>刷新列表</AccessibleButton></View>{cameras.length > 0 && <View className="sc-camera-list-options" role="group" ariaLabel="摄像头设备">{cameras.map((camera, index) => <AccessibleButton key={camera.deviceId} id={`camera-device-${index}`} className={`sc-camera-device ${selection.cameraDeviceId === camera.deviceId ? 'sc-camera-device--selected' : ''}`} aria-pressed={selection.cameraDeviceId === camera.deviceId} disabled={busy || !selection.camera} onClick={() => setSelection(current => ({ ...current, cameraDeviceId: camera.deviceId }))}>{camera.label || `摄像头 ${index + 1}`}{selection.cameraDeviceId === camera.deviceId ? ' · 已选择' : ''}</AccessibleButton>)}</View>}<Text className="sc-media-guidance">{cameraListError || (busy ? '先结束陪伴，再选择设备并主动开始。' : '设备选择在下一次主动开始时生效，刷新列表不会申请权限。')}</Text></View>
        <Text className="sc-media-guidance">{guidance}</Text>
        <View className="sc-media-permissions"><View className="sc-media-permission-row"><Text>摄像头权限</Text><Text id="camera-permission">{permissionText(state.capture.camera)}</Text></View><View className="sc-media-permission-row"><Text>麦克风权限</Text><Text id="microphone-permission">{permissionText(state.capture.microphone)}</Text></View></View>
      </SectionCard>
    </View>
    <View className="sc-session-notice sc-session-notes"><Text className="sc-notice-title">设备预览，与情绪数据分开</Text><Text>尚未连接情绪分析后端。本次没有进行情绪推理、语音转写或 AI 回应。{source === 'demo' ? 'DEMO 情绪只是合成示例，不是摄像头推理结果。' : '现有服务中的情绪记录不代表本次陪伴。'}音视频仅在设备内临时处理，不上传、不长期保存；平台生成的临时片段会在处理后清理。</Text></View>
    <View className="sc-session-notes"><SectionCard title="此刻的情绪" eyebrow="本次陪伴"><View className="sc-media-unprocessed" id="session-emotion-status"><Text className="sc-setting-name">本次尚无情绪推理结果</Text><Text className="sc-body-muted">这次采集没有发送到推理服务。首页与洞察中的现有记录，不代表这次陪伴的情绪。</Text></View></SectionCard></View>
    <View className="sc-two-column sc-session-notes"><SectionCard title="你说的话" eyebrow="语音转写"><EmptyState title="本次还没有语音转写" detail={state.capture.microphone.state === 'on' ? '麦克风正在本机采样，尚未发送给语音识别服务，因此没有转写内容。' : '本次没有发送语音识别请求，转写会在服务接入后呈现。'} /></SectionCard><SectionCard title="轻轻的回应" eyebrow="AI 陪伴"><EmptyState title="回应会在这里出现" detail="本次没有发送 AI 会话请求，也没有生成回复。" /></SectionCard></View>
  </AppShell>;
}

export default withClientErrorBoundary(SessionPage);
