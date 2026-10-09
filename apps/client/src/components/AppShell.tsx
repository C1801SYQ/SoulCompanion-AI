import { useEffect, useState, type ReactNode } from 'react';
import { useDidHide, useDidShow } from '@tarojs/taro';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from './AccessibleButton';
import { useCompanion } from '../state/AppProvider';
import { StatusPill } from './Primitives';
import { useCloud } from '../state/CloudProvider';
import { FAMILY_TOOLS, PRIMARY_NAVIGATION, backFromTool, isFamilyTool, navigatePrimary, openTool, primaryFor, type PageName, type PrimaryPage } from '../navigation';

export type { PageName } from '../navigation';

export function AppShell({ page, children }: { page: PageName; children: ReactNode }) {
  const { source, connection } = useCompanion();
  const { store } = useCloud();
  const familyTool = isFamilyTool(page);
  const primaryPage = primaryFor(page);
  useEffect(() => { store.setPrivateReadsEnabled(familyTool); }, [store, familyTool]);
  useDidShow(() => store.setPrivateReadsEnabled(familyTool));
  useDidHide(() => store.setPrivateReadsEnabled(false));
  const connectionLabels = { connecting: '连接中', online: '已连接', offline: '离线', error: '连接错误' };
  const [navigationError, setNavigationError] = useState('');
  function navigate(next: PrimaryPage) {
    if (next === page) return;
    setNavigationError('');
    store.setPrivateReadsEnabled(false);
    void navigatePrimary(next).catch(() => { store.setPrivateReadsEnabled(familyTool); setNavigationError('页面暂时无法打开，请再试一次。'); });
  }
  return <View className={`sc-shell pc-shell ${familyTool ? 'pc-shell--family' : 'pc-shell--public'}`}>
    <View className="sc-rail">
      <View className="sc-brand"><View className="sc-brand-mark" ariaHidden><View /></View><View><Text className="sc-brand-name">予怀</Text><Text className="sc-brand-caption">一起理解孩子，陪伴成长</Text></View></View>
      <View className="sc-navigation" role="navigation" ariaLabel="主要导航">
        {PRIMARY_NAVIGATION.map(item => <Button id={`nav-${item.page}`} key={item.page} className={`sc-nav-item ${primaryPage === item.page ? 'sc-nav-item--active' : ''}`} aria-current={primaryPage === item.page ? 'page' : undefined} ariaLabel={`${item.label}${primaryPage === item.page ? '，当前入口' : ''}`} onClick={() => navigate(item.page)}><View className={`sc-nav-icon sc-nav-icon--${item.icon}`} ariaHidden><View /></View><View><Text className="sc-nav-label">{item.label}</Text><Text className="sc-nav-caption">{item.caption}</Text></View></Button>)}
      </View>
      <View className="sc-rail-note"><View className="sc-rail-note-line" /><Text>一起聊聊，</Text><Text>慢慢成长。</Text><Text className="sc-rail-note-small">PC01 · 产品预览</Text></View>
    </View>
    <View className="sc-workspace">
      <View className="sc-topbar"><Text className="sc-topbar-brand">予怀</Text><Text className="sc-topbar-caption">给家庭日常，多一点理解</Text>{familyTool ? <StatusPill id={source === 'demo' ? 'demo-badge' : 'connection-status'} tone={source === 'demo' ? 'warm' : connection === 'online' ? 'good' : connection === 'error' ? 'error' : 'quiet'}>{source === 'demo' ? '演示模式 · 合成数据' : `REAL · ${connectionLabels[connection]}`}</StatusPill> : <StatusPill id="community-preview-badge" tone="warm">产品预览 · 示例内容</StatusPill>}</View>
      {familyTool && source === 'demo' && <View className="sc-demo-note"><Text>你正在体验合成示例。这些情绪和报告不来自真实采集。</Text></View>}
      {navigationError && <View className="sc-resource-notice sc-resource-notice--error" role="status"><Text>{navigationError}</Text></View>}
      <View className="sc-main" id="main-content" role="main">
        {familyTool && <View className="pc-family-tools">
          <View className="pc-family-tools-heading"><Text>可选家庭工具 · 保留原有功能</Text><Button id="family-tools-back" className="sc-text-action" onClick={() => { void backFromTool().catch(() => setNavigationError('暂时无法返回，请使用主入口。')); }}>返回</Button></View>
          <View className="pc-family-tools-links" role="group" ariaLabel="家庭工具">{FAMILY_TOOLS.map(item => <Button key={item.page} id={`nav-${item.page}`} className={`pc-tool-tab ${page === item.page ? 'pc-tool-tab--active' : ''}`} aria-current={page === item.page ? 'page' : undefined} onClick={() => { void openTool(item.page).catch(() => setNavigationError('工具暂时无法打开，请重试。')); }}>{item.label}</Button>)}</View>
        </View>}
        {children}
      </View>
      <View className="sc-footer"><Text>予怀</Text><Text>{familyTool ? '情绪观察用于陪伴与回顾，不作为诊断依据。' : '面向 0～18 岁儿童家庭 · 经验交流，不替代专业支持'}</Text></View>
    </View>
  </View>;
}

export function PageHeader({ eyebrow, title, description, action }: {
  eyebrow: string; title: string; description: string; action?: ReactNode;
}) {
  return <View className="sc-page-header"><View><Text className="sc-eyebrow">{eyebrow}</Text><View className="sc-page-title" role="heading" aria-level="1"><Text>{title}</Text></View><Text className="sc-page-description">{description}</Text></View>{action}</View>;
}
