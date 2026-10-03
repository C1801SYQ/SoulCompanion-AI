import { useState, type ReactNode } from 'react';
import Taro from '@tarojs/taro';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from './AccessibleButton';
import { useCompanion } from '../state/AppProvider';
import { StatusPill } from './Primitives';

export type PageName = 'home' | 'session' | 'insights' | 'reports' | 'settings';
const navigation: { page: PageName; label: string; caption: string }[] = [
  { page: 'home', label: '首页', caption: '陪伴当下' }, { page: 'session', label: '陪伴', caption: '留一点时间' },
  { page: 'insights', label: '洞察', caption: '看见情绪变化' }, { page: 'reports', label: '报告', caption: '回顾与记录' },
  { page: 'settings', label: '我的', caption: '偏好与设置' },
];

export function AppShell({ page, children }: { page: PageName; children: ReactNode }) {
  const { source, connection } = useCompanion();
  const connectionLabels = { connecting: '连接中', online: '已连接', offline: '离线', error: '连接错误' };
  const [navigationError, setNavigationError] = useState('');
  function navigate(next: PageName) {
    if (next === page) return;
    setNavigationError('');
    void Taro.reLaunch({ url: `/pages/${next}/index` }).catch(() => setNavigationError('页面暂时无法打开，请再试一次。'));
  }
  return <View className="sc-shell">
    <View className="sc-rail">
      <View className="sc-brand"><View className="sc-brand-mark" ariaHidden><View /></View><View><Text className="sc-brand-name">SoulCompanion</Text><Text className="sc-brand-caption">陪伴，让情绪被看见</Text></View></View>
      <View className="sc-navigation" role="navigation" ariaLabel="主要导航">
        {navigation.map(item => <Button id={`nav-${item.page}`} key={item.page} className={`sc-nav-item ${page === item.page ? 'sc-nav-item--active' : ''}`} aria-current={page === item.page ? 'page' : undefined} ariaLabel={`${item.label}${page === item.page ? '，当前页面' : ''}`} onClick={() => navigate(item.page)}><View className={`sc-nav-icon sc-nav-icon--${item.page}`} ariaHidden><View /></View><View><Text className="sc-nav-label">{item.label}</Text><Text className="sc-nav-caption">{item.caption}</Text></View></Button>)}
      </View>
      <View className="sc-rail-note"><View className="sc-rail-note-line" /><Text>一点时间，</Text><Text>好好陪伴。</Text><Text className="sc-rail-note-small">V2 · 体验预览</Text></View>
    </View>
    <View className="sc-workspace">
      <View className="sc-topbar"><Text className="sc-topbar-brand">SoulCompanion</Text><Text className="sc-topbar-caption">给日常留一处安静的空间</Text><StatusPill id={source === 'demo' ? 'demo-badge' : 'connection-status'} tone={source === 'demo' ? 'warm' : connection === 'online' ? 'good' : connection === 'error' ? 'error' : 'quiet'}>{source === 'demo' ? '演示模式 · 合成数据' : `REAL · ${connectionLabels[connection]}`}</StatusPill></View>
      {source === 'demo' && <View className="sc-demo-note"><Text>你正在体验合成示例。这些情绪和报告不来自真实采集。</Text></View>}
      {navigationError && <View className="sc-resource-notice sc-resource-notice--error" role="status"><Text>{navigationError}</Text></View>}
      <View className="sc-main" id="main-content" role="main">{children}</View>
      <View className="sc-footer"><Text>SoulCompanion</Text><Text>情绪观察用于陪伴与回顾，不作为诊断依据。</Text></View>
    </View>
  </View>;
}

export function PageHeader({ eyebrow, title, description, action }: {
  eyebrow: string; title: string; description: string; action?: ReactNode;
}) {
  return <View className="sc-page-header"><View><Text className="sc-eyebrow">{eyebrow}</Text><View className="sc-page-title" role="heading" aria-level="1"><Text>{title}</Text></View><Text className="sc-page-description">{description}</Text></View>{action}</View>;
}
