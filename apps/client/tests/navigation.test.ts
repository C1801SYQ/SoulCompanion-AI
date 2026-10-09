import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ reLaunch: vi.fn(), navigateTo: vi.fn(), redirectTo: vi.fn(), navigateBack: vi.fn(), getCurrentPages: vi.fn() }));
vi.mock('@tarojs/taro', () => ({ default: mocks }));
import { PRIMARY_NAVIGATION, backToCommunity, navigatePrimary, openPage, openTool } from '../src/navigation';

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getCurrentPages.mockReturnValue([{ route: 'pages/community/index' }]);
  for (const method of [mocks.reLaunch, mocks.navigateTo, mocks.redirectTo, mocks.navigateBack]) method.mockResolvedValue({});
});
describe('parent community navigation boundaries', () => {
  it('has four primary destinations with community first', () => {
    expect(PRIMARY_NAVIGATION.map(item => item.page)).toEqual(['community', 'knowledge', 'growth', 'profile']);
  });
  it('switches primary destinations without configuring details as tabs', async () => {
    await navigatePrimary('community');
    expect(mocks.reLaunch).toHaveBeenCalledWith({ url: '/pages/community/index' });
    expect(mocks.navigateTo).not.toHaveBeenCalled();
  });
  it('pushes detail and compose instead of relaunching', async () => {
    await openPage('/pages/community/detail?id=example-01');
    await openPage('/pages/community/compose');
    expect(mocks.navigateTo).toHaveBeenCalledTimes(2);
    expect(mocks.reLaunch).not.toHaveBeenCalled();
  });
  it('returns through the page stack and uses community only for direct entry', async () => {
    mocks.getCurrentPages.mockReturnValue([{ route: 'pages/community/index' }, { route: 'pages/community/detail' }]);
    await backToCommunity();
    expect(mocks.navigateBack).toHaveBeenCalledWith({ delta: 1 });
    mocks.getCurrentPages.mockReturnValue([{ route: 'pages/community/detail' }]);
    await backToCommunity();
    expect(mocks.reLaunch).toHaveBeenCalledWith({ url: '/pages/community/index' });
  });
  it('pushes family tools and replaces only a tool within its existing frame', async () => {
    await openTool('session');
    expect(mocks.navigateTo).toHaveBeenCalledWith({ url: '/pages/session/index' });
    mocks.getCurrentPages.mockReturnValue([{ route: 'pages/growth/index' }, { route: 'pages/session/index' }]);
    await openTool('reports');
    expect(mocks.redirectTo).toHaveBeenCalledWith({ url: '/pages/reports/index' });
  });
  it.each(['/session', 'session', '/pages/session/index', 'pages/session/index'])('keeps the current tool frame for %s and replaces it when switching', async route => {
    mocks.getCurrentPages.mockReturnValue([{ route: 'pages/growth/index' }, { route }]);
    await openTool('session');
    expect(mocks.navigateTo).not.toHaveBeenCalled();
    expect(mocks.redirectTo).not.toHaveBeenCalled();
    await openTool('insights');
    expect(mocks.redirectTo).toHaveBeenCalledWith({ url: '/pages/insights/index' });
    expect(mocks.navigateTo).not.toHaveBeenCalled();
  });
  it('propagates navigation failures and rejects external destinations', async () => {
    mocks.navigateTo.mockRejectedValue(new Error('navigation unavailable'));
    await expect(openPage('/pages/community/compose')).rejects.toThrow('navigation unavailable');
    await expect(openPage('https://example.invalid')).rejects.toThrow();
  });
});
