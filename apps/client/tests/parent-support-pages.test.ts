import { createElement, type ComponentType, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuthStatus } from '../src/cloud/types';

const mocks = vi.hoisted(() => ({ useCloud: vi.fn(), openPage: vi.fn() }));

type DisplayProps = { children?: ReactNode; id?: string; role?: string; ariaLabel?: string; 'aria-pressed'?: boolean };
vi.mock('@tarojs/components', async () => {
  const { createElement: element } = await import('react');
  const display = (tag: string) => ({ children, id, role }: DisplayProps) => element(tag, { id, role }, children);
  return { View: display('div'), Text: display('span') };
});
vi.mock('../src/components/AccessibleButton', async () => {
  const { createElement: element } = await import('react');
  return { AccessibleButton: ({ children, id, ariaLabel, 'aria-pressed': pressed }: DisplayProps) => element('button', { id, 'aria-label': ariaLabel, 'aria-pressed': pressed }, children) };
});
vi.mock('../src/components/AppShell', async () => {
  const { createElement: element } = await import('react');
  return {
    AppShell: ({ children, page }: { children: ReactNode; page: string }) => element('main', { 'data-page': page }, children),
    PageHeader: ({ title, description, eyebrow }: { title: string; description: string; eyebrow: string }) => element('header', null, element('span', null, eyebrow), element('h1', null, title), element('p', null, description)),
  };
});
vi.mock('../src/components/Primitives', async () => {
  const { createElement: element } = await import('react');
  return {
    SectionCard: ({ title, eyebrow, children }: { title: string; eyebrow?: string; children: ReactNode }) => element('section', null, element('h2', null, title), element('span', null, eyebrow), children),
    EmptyState: ({ title, detail }: { title: string; detail: string }) => element('div', null, element('h3', null, title), element('p', null, detail)),
    StatusPill: ({ children, id }: DisplayProps) => element('span', { id }, children),
  };
});
vi.mock('../src/components/ClientErrorBoundary', () => ({ withClientErrorBoundary: (page: ComponentType) => page }));
vi.mock('../src/state/CloudProvider', () => ({ useCloud: mocks.useCloud }));
vi.mock('../src/navigation', () => ({ openPage: mocks.openPage }));

import KnowledgePage from '../src/pages/knowledge';
import GrowthPage from '../src/pages/growth';
import ProfilePage from '../src/pages/profile';
import { AGE_BANDS, TOPICS } from '../src/community/constants';

function publicOnlyContext(enabled: boolean, status: AuthStatus) {
  const forbiddenRead = () => { throw new Error('Public page tried to read private account data'); };
  const auth = { status };
  Object.defineProperty(auth, 'principal', { get: forbiddenRead });
  const state = { enabled, auth };
  for (const key of ['user', 'profiles', 'selectedId', 'sessions', 'emotions', 'reports']) {
    Object.defineProperty(state, key, { get: forbiddenRead });
  }
  const context = { state };
  Object.defineProperty(context, 'store', { get: forbiddenRead });
  return context;
}

describe('public support pages keep private family tools behind explicit entry', () => {
  beforeEach(() => mocks.useCloud.mockReturnValue(publicOnlyContext(false, 'signed_out')));

  it.each([
    [false, 'signed_out', '云端账号尚未配置'],
    [true, 'signed_out', '未登录'],
    [true, 'signing_in', '正在登录'],
    [true, 'signed_in', '已登录'],
    [true, 'expired', '登录已失效'],
    [true, 'offline', '账号连接暂时不可用'],
    [true, 'error', '账号状态暂时不可用'],
  ] as const)('account entry safely shows enabled=%s status=%s without reading principal or family data', (enabled, status, label) => {
    mocks.useCloud.mockReturnValue(publicOnlyContext(enabled, status));
    const html = renderToStaticMarkup(createElement(ProfilePage));
    expect(html).toContain(`id="pc-account-status">${label}`);
    expect(html).toContain('id="pc-private-account"');
    expect(html).toContain('尚未接入');
    expect(mocks.useCloud).toHaveBeenCalledOnce();
    expect(mocks.openPage).not.toHaveBeenCalled();
  });

  it('knowledge exposes every shared age and scenario choice while presenting a source-aware empty state', () => {
    const html = renderToStaticMarkup(createElement(KnowledgePage));
    for (const age of AGE_BANDS) expect(html).toContain(`id="pc-knowledge-age-${age.value}"`);
    for (const topic of TOPICS) expect(html).toContain(`id="pc-knowledge-topic-${topic.value}"`);
    expect(html).toContain('这里暂时还没有内容');
    expect(html).toContain('尚无已核实来源的知识文章');
    expect(mocks.useCloud).not.toHaveBeenCalled();
    expect(mocks.openPage).not.toHaveBeenCalled();
  });

  it('growth keeps the three old tools distinct from unimplemented manual observation without reading records', () => {
    const html = renderToStaticMarkup(createElement(GrowthPage));
    for (const tool of ['session', 'insights', 'reports']) expect(html).toContain(`id="pc-tool-${tool}"`);
    expect(html).toContain('手动观察记录还在准备中');
    expect(html).toContain('不是新社区功能，也不是新的手动观察记录');
    expect(mocks.useCloud).not.toHaveBeenCalled();
    expect(mocks.openPage).not.toHaveBeenCalled();
  });
});
