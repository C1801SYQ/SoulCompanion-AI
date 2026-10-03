export function emotionLabel(category: string): string {
  const labels: Record<string, string> = {
    joy: '愉悦', happy: '愉悦', happiness: '愉悦', calm: '平静', neutral: '平稳',
    sad: '低落', sadness: '低落', angry: '生气', anger: '生气', fear: '不安',
    fearful: '不安', anxious: '不安', anxiety: '不安', surprise: '惊讶',
    surprised: '惊讶', disgust: '反感', excited: '兴奋', unknown: '尚未识别',
  };
  const key = category.toLowerCase();
  return Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : category;
}

export function timeLabel(value: string, includeDate = false): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '时间未知';
  return date.toLocaleString('zh-CN', {
    ...(includeDate ? { month: 'numeric', day: 'numeric' } : {}),
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
}

export function dayLabel(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '日期未知';
  return date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' });
}

export function valenceLabel(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`;
}

export const componentLabels: Record<string, string> = {
  backend: '服务', database: '情绪记录存储', bridge: '旧设备接入', camera: '旧设备摄像头',
  microphone: '旧设备麦克风', vision_model: '视觉模型', speech_model: '语音模型',
  ser_model: '语音情绪模型', ollama: '本机 AI', hardware: '可选实体设备',
};

export const visibleComponentNames = [
  'backend', 'database', 'bridge', 'camera', 'microphone',
  'vision_model', 'speech_model', 'ser_model', 'ollama', 'hardware',
] as const;

export function componentLabel(name: string): string {
  return Object.prototype.hasOwnProperty.call(componentLabels, name) ? componentLabels[name] : name;
}

export const componentStateLabels: Record<string, string> = {
  healthy: '可用', degraded: '部分可用', unavailable: '不可用', disabled: '未启用', unknown: '未知',
};
