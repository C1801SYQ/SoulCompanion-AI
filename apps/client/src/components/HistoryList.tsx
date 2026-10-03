import { Text, View } from '@tarojs/components';
import type { RecordView } from '../types/contracts';
import { emotionLabel, timeLabel, valenceLabel } from './format';
import { EmptyState } from './Primitives';

export function HistoryList({ records, compact = false }: { records: RecordView[]; compact?: boolean }) {
  if (!records.length) return <EmptyState compact title="这里还没有情绪记录" detail="有了有效观察后，记录会在这里慢慢积累。" />;
  return <View className={`sc-history ${compact ? 'sc-history--compact' : ''}`}>
    {records.map((record, index) => <View key={`${record.timestamp}-${index}`} className="sc-history-row">
      <View className={`sc-emotion-dot ${record.valence > .2 ? 'sc-emotion-dot--positive' : record.valence < -.2 ? 'sc-emotion-dot--warm' : ''}`} ariaHidden />
      <View className="sc-history-description"><View className="sc-history-heading"><Text className="sc-history-category">{emotionLabel(record.category)}</Text><Text className="sc-history-time">{timeLabel(record.timestamp, true)}</Text></View>{!compact && <Text className="sc-history-cause">{record.cause || '未记录具体情境'}</Text>}<Text className="sc-history-meta">效价 {valenceLabel(record.valence)} · 唤醒度 {Math.round(record.arousal * 100)}%</Text></View>
    </View>)}
  </View>;
}
