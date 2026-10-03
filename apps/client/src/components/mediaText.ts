import type { DeviceCaptureStatus, MediaSessionState } from '../media/types';

const problemLabels: Record<string, string> = {
  permission_denied: '权限没有获准。你可以在浏览器或系统设置中允许权限，再主动开始。',
  device_missing: '没有找到所选设备。可以关闭缺少的设备选项，只使用另一种方式。',
  device_in_use: '设备可能被占用或暂时不可用。请确认设备连接，并关闭正在使用它的其他应用，再主动开始。',
  device_ended: '设备连接已结束，本次采集已停止。请检查设备，再主动开始。',
  unsupported: '当前环境暂不支持所选媒体能力。请使用支持摄像头和麦克风的浏览器或设备。',
  insecure_context: '当前页面不满足媒体权限要求。请使用 HTTPS，或在本机安全地址打开。',
  capture_failed: '本次没有成功开启设备。请确认设备可用，再主动开始。',
  encoding_failed: '本次媒体处理没有完成，采集已停止。请稍后再主动开始。',
  oversize: '本次媒体片段超出处理范围，采集已停止。请稍后再主动开始。',
  interrupted: '采集已中断。恢复到前台并确认网络后，需要再次点击开始。',
  timeout: '等待设备的时间过长，本次已取消。稍后获准的权限不会继续这次采集。',
  cleanup_failed: '设备释放暂未确认完成。请关闭此页并确认系统的摄像头和麦克风指示状态。',
  nothing_selected: '请至少选择摄像头或麦克风中的一种。',
};

export function mediaProblemText(problem: MediaSessionState['problem']): string {
  return problem && Object.prototype.hasOwnProperty.call(problemLabels, problem)
    ? problemLabels[problem] : '';
}

export function deviceText(name: 'Camera' | 'Mic', device: DeviceCaptureStatus): string {
  if (device.state === 'off' && device.problem === 'device_missing') return `${name} UNAVAILABLE · 未找到设备`;
  if (device.state === 'off' && device.permission === 'denied') return `${name} DENIED · 权限被拒绝`;
  switch (device.state) {
    case 'on': return `${name} ON · 本机采集`;
    case 'requesting': return `${name} REQUESTING · 等待权限`;
    case 'denied': return `${name} DENIED · 权限被拒绝`;
    case 'missing': return `${name} UNAVAILABLE · 未找到设备`;
    case 'error': return `${name} ERROR · ${device.problem === 'cleanup_failed' ? '释放待确认' : '采集不可用'}`;
    default: return `${name} OFF · ${device.permission === 'unknown' ? '未申请权限' : '已停止'}`;
  }
}

export function permissionText(device: DeviceCaptureStatus): string {
  if (device.state === 'requesting') return '等待你的选择';
  if (device.permission === 'granted') return '已获准';
  if (device.permission === 'denied') return '未获准';
  return '尚未申请';
}

export function sessionText(state: MediaSessionState): string {
  if (state.problem === 'cleanup_failed') return '设备释放待确认';
  if (state.phase === 'starting') return '等待设备权限';
  if (state.phase === 'active') return '正在本机采集 · 未上传';
  if (state.phase === 'stopping') return '正在停止设备';
  if (state.phase === 'error') return '本次未能继续';
  return state.stoppedReason ? '本次采集已停止' : '尚未开始采集';
}

export function stoppedSessionText(state: MediaSessionState): string {
  if (state.phase !== 'idle' || state.problem === 'cleanup_failed'
    || [state.capture.camera.state, state.capture.microphone.state].some(value => value === 'on' || value === 'requesting')) return '';
  return stoppedText(state.stoppedReason);
}

export function previewText(state: MediaSessionState): string {
  if (state.problem === 'cleanup_failed') return '设备释放待确认';
  if (state.phase === 'stopping') return '正在停止设备';
  if ([state.capture.camera.state, state.capture.microphone.state].includes('on')) return '仅本机采集';
  if (state.phase === 'starting') return '等待你的权限选择';
  return '设备未启用';
}

export function stoppedText(reason: MediaSessionState['stoppedReason']): string {
  if (reason === 'background') return '离开前台时已停止采集。回来后需要再次点击开始。';
  if (reason === 'offline') return '设备网络中断时已停止采集。恢复连接后需要再次点击开始。';
  if (reason === 'source_change') return '切换数据来源时已停止采集。任何数据模式下，都需要再次主动开始。';
  if (reason === 'unmount') return '离开陪伴页时已停止采集。新的陪伴由你再次开始。';
  if (reason === 'user') return '你已停止本次采集。等待中的权限即使稍后获准，也不会继续这次采集。';
  return '';
}
