import type { ReactNode } from 'react';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from './AccessibleButton';
import { Button as TaroifyButton } from '@taroify/core';
import type { ButtonProps as TaroifyButtonProps } from '@taroify/core/button';
import { activateOnKey, type ActivationEvent } from './keyboard';

export function PrimaryAction({ children, onClick, disabled = false, id }: {
  children: ReactNode; onClick: () => void; disabled?: boolean; id?: string;
}) {
  const semanticProps: TaroifyButtonProps & { role: 'button'; tabindex: number; 'aria-disabled': boolean; onKeyDown: (event: ActivationEvent) => void } = {
    id, className: 'sc-primary-action', color: 'primary', variant: 'contained', disabled,
    role: 'button', tabindex: disabled ? -1 : 0,
    'aria-disabled': Boolean(disabled),
    onClick: () => { if (!disabled) onClick(); },
    onKeyDown: event => activateOnKey(event, onClick, disabled),
  };
  return <TaroifyButton {...semanticProps}>{children}</TaroifyButton>;
}

export function TextAction({ children, onClick, disabled = false }: {
  children: ReactNode; onClick: () => void; disabled?: boolean;
}) {
  return <Button className="sc-text-action" onClick={onClick} disabled={disabled}>{children}</Button>;
}

export function StatusPill({ children, tone = 'quiet', id }: {
  children: ReactNode; tone?: 'quiet' | 'good' | 'warm' | 'error'; id?: string;
}) {
  return <View id={id} className={`sc-status sc-status--${tone}`}><View className="sc-status-dot" ariaHidden /><Text>{children}</Text></View>;
}

export function SectionCard({ title, eyebrow, action, children, className = '' }: {
  title: string; eyebrow?: string; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return <View className={`sc-card ${className}`}>
    <View className="sc-section-heading">
      <View className="sc-section-labels">{eyebrow && <Text className="sc-eyebrow">{eyebrow}</Text>}<View className="sc-section-title" role="heading" aria-level="2"><Text>{title}</Text></View></View>
      {action}
    </View>
    {children}
  </View>;
}

export function EmptyState({ title, detail, compact = false }: { title: string; detail: string; compact?: boolean }) {
  return <View className={`sc-empty ${compact ? 'sc-empty--compact' : ''}`}>
    <View className="sc-empty-mark" ariaHidden><View /></View>
    <Text className="sc-empty-title">{title}</Text><Text className="sc-body-muted">{detail}</Text>
  </View>;
}

export function ResourceNotice({ status, error, retry, retryId }: {
  status: 'loading' | 'ready' | 'offline' | 'error'; error: string; retry: () => void; retryId?: string;
}) {
  if (status === 'ready') return null;
  if (status === 'loading') return <View className="sc-resource-notice" role="status"><Text>正在读取…</Text></View>;
  return <View className={`sc-resource-notice sc-resource-notice--${status}`} role="status">
    <View><Text className="sc-notice-title">{status === 'offline' ? '暂时无法连接服务' : '这部分信息暂时不可用'}</Text><Text className="sc-body-muted">{error || '请稍后重试，或到设置中查看连接。'}</Text></View>
    <Button id={retryId} className="sc-text-action" onClick={retry}>重试</Button>
  </View>;
}

export type Days = 1 | 7 | 30;
export function RangeTabs({ days, onChange }: { days: Days; onChange: (value: Days) => void }) {
  return <View className="sc-range-tabs" role="group" ariaLabel="时间范围">
    {([1, 7, 30] as const).map(value => <Button id={`range-${value}`} key={value} className={`sc-range-tab ${days === value ? 'sc-range-tab--selected' : ''}`} aria-pressed={days === value} ariaLabel={`最近 ${value} 天${days === value ? '，已选择' : ''}`} onClick={() => onChange(value)}>{value === 1 ? '今天' : `${value} 天`}</Button>)}
  </View>;
}

export function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <View className="sc-metric"><Text className="sc-metric-label">{label}</Text><Text className="sc-metric-value">{value}</Text>{detail && <Text className="sc-metric-detail">{detail}</Text>}</View>;
}
