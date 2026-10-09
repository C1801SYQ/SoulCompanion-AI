import Taro from '@tarojs/taro';

export type PrimaryPage = 'community' | 'knowledge' | 'growth' | 'profile';
export type ToolPage = 'home' | 'session' | 'insights' | 'reports' | 'settings';
export type PageName = PrimaryPage | ToolPage | 'community-detail' | 'community-compose';
export const PRIMARY_NAVIGATION: ReadonlyArray<{ page: PrimaryPage; label: string; caption: string; icon: string }> = [
  { page: 'community', label: '社区', caption: '一起聊聊日常', icon: 'session' },
  { page: 'knowledge', label: '育儿知识', caption: '找到适合的内容', icon: 'reports' },
  { page: 'growth', label: '成长记录', caption: '留意小小变化', icon: 'insights' },
  { page: 'profile', label: '我的', caption: '资料与自主选择', icon: 'settings' },
];
export const FAMILY_TOOLS: ReadonlyArray<{ page: ToolPage; label: string }> = [
  { page: 'home', label: '陪伴看板' }, { page: 'session', label: '本地陪伴' },
  { page: 'insights', label: '情绪洞察' }, { page: 'reports', label: '旧情绪报告' }, { page: 'settings', label: '账号与设置' },
];
export function isFamilyTool(page: PageName): page is ToolPage { return FAMILY_TOOLS.some(item => item.page === page); }
export function primaryFor(page: PageName): PrimaryPage {
  if (page === 'community-detail' || page === 'community-compose') return 'community';
  if (isFamilyTool(page)) return page === 'settings' ? 'profile' : 'growth';
  return page;
}
export async function navigatePrimary(page: PrimaryPage): Promise<void> {
  await Taro.reLaunch({ url: `/pages/${page}/index` });
}
/** Public details, drafts and family tools use a page frame that can be returned from. */
export async function openPage(url: string): Promise<void> {
  if (!/^\/pages\/(?:community\/(?:detail(?:\?id=[a-zA-Z0-9_-]{1,80})?|compose)|(?:home|session|insights|reports|settings)\/index)$/.test(url)) {
    throw new Error('Unsupported local destination');
  }
  await Taro.navigateTo({ url });
}
export async function openTool(page: ToolPage): Promise<void> {
  const frames = Taro.getCurrentPages();
  // H5 custom routes use /session; WeChat uses pages/session/index.
  const current = frames[frames.length - 1]?.route?.split('?')[0].replace(/^\/+|\/+$/g, '');
  const currentTool = FAMILY_TOOLS.find(item => current === item.page || current === `pages/${item.page}/index`)?.page;
  if (currentTool === page) return;
  if (currentTool) await Taro.redirectTo({ url: `/pages/${page}/index` });
  else await openPage(`/pages/${page}/index`);
}
export async function backToCommunity(): Promise<void> {
  if (Taro.getCurrentPages().length > 1) await Taro.navigateBack({ delta: 1 });
  else await navigatePrimary('community');
}
export async function backFromTool(): Promise<void> {
  if (Taro.getCurrentPages().length > 1) await Taro.navigateBack({ delta: 1 });
  else await navigatePrimary('growth');
}
