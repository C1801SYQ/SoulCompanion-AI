import type { CSSProperties } from 'react';
import { Text, View } from '@tarojs/components';
import type { EmotionView } from '../types/contracts';
import { emotionLabel, timeLabel, valenceLabel } from './format';

export function EmotionOrb({ emotion, motionEnabled, compact = false, demo = false }: {
  emotion: EmotionView | null; motionEnabled: boolean; compact?: boolean; demo?: boolean;
}) {
  const valid = emotion && [emotion.valence, emotion.arousal, emotion.confidence].every(Number.isFinite);
  const valence = valid ? Math.max(-1, Math.min(1, emotion.valence)) : 0;
  const arousal = valid ? Math.max(0, Math.min(1, emotion.arousal)) : 0;
  const confidence = valid ? Math.max(0, Math.min(1, emotion.confidence)) : 0;
  const style = {
    '--orb-duration': `${14 - arousal * 6}s`,
    '--orb-glow': String(.08 + confidence * .12),
    '--orb-color': !valid ? 'var(--sc-emotion-resting)' : valence > .2 ? 'var(--sc-emotion-positive)' : valence < -.2 ? 'var(--sc-emotion-negative)' : 'var(--sc-emotion-resting)',
    '--orb-radius': `${48 + arousal * 3}% ${52 - arousal * 2}% ${49 + arousal * 2}% ${51 - arousal * 3}%`,
  } as CSSProperties;
  return <View className={`sc-orb-area ${compact ? 'sc-orb-area--compact' : ''}`}>
    <View id="emotion-orb" className={`sc-orb ${valid && motionEnabled ? 'sc-orb--breathing' : ''} ${!valid ? 'sc-orb--resting' : ''}`} style={style} ariaHidden><View className="sc-orb-halo" /><View className="sc-orb-core" /><View className="sc-orb-light" /></View>
    <View className="sc-orb-caption"><Text id="emotion-label" className="sc-orb-label">{valid ? emotionLabel(emotion.category) : '等待一次真实的观察'}</Text><Text className="sc-body-muted">{valid ? `${demo ? '合成示例 · ' : ''}${timeLabel(emotion.timestamp)} 更新` : '尚无有效数据，保持安静的等待。'}</Text></View>
    <Text id="confidence-value" className="sc-orb-text">{valid ? `效价 ${valenceLabel(valence)} · 唤醒度 ${Math.round(arousal * 100)}% · 置信度 ${Math.round(confidence * 100)}%` : '置信度 —'}</Text>
  </View>;
}
