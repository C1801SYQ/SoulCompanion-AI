import { Text, View } from '@tarojs/components';
import { AccessibleButton } from './AccessibleButton';

export function MediaChoice({ id, title, note, selected, disabled, onClick }: {
  id: string;
  title: string;
  note: string;
  selected: boolean;
  disabled: boolean;
  onClick(): void;
}) {
  return <AccessibleButton id={id} className={`sc-media-option ${selected ? 'sc-media-option--selected' : ''}`}
    role="switch" aria-checked={selected} ariaLabel={`${title}，${selected ? '已选择' : '未选择'}`}
    disabled={disabled} onClick={onClick}>
    <View><Text className="sc-media-option-title">{title}</Text><Text className="sc-media-option-note">{note}</Text></View>
    <View className="sc-media-option-choice" ariaHidden><Text className="sc-media-option-check">{selected ? '✓' : ''}</Text></View>
  </AccessibleButton>;
}
