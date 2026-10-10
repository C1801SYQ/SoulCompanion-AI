import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ reLaunch: vi.fn(), navigateTo: vi.fn(), redirectTo: vi.fn(), navigateBack: vi.fn(), getCurrentPages: vi.fn(), dismissKeyboard: vi.fn() }));
vi.mock('@tarojs/taro', () => ({ default: mocks }));
vi.mock('../src/platform/keyboard', () => ({ dismissKeyboard: mocks.dismissKeyboard }));
import { PRIMARY_NAVIGATION, backFromTool, backToCommunity, navigatePrimary, openPage, openTool } from '../src/navigation';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(complete => { resolve = complete; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getCurrentPages.mockReturnValue([{ route: 'pages/community/index' }]);
  for (const method of [mocks.reLaunch, mocks.navigateTo, mocks.redirectTo, mocks.navigateBack]) method.mockResolvedValue({});
  mocks.dismissKeyboard.mockResolvedValue(undefined);
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
  it('coalesces different navigation requests while the first route is unresolved', async () => {
    const route = deferred();
    mocks.navigateTo.mockReturnValueOnce(route.promise);
    const first = openPage('/pages/community/detail?id=example-01');
    const following = [
      openPage('/pages/community/compose'), navigatePrimary('profile'), openTool('reports'),
      backToCommunity(), backFromTool(),
    ];
    for (const request of following) expect(request).toBe(first);
    await vi.waitFor(() => expect(mocks.navigateTo).toHaveBeenCalledTimes(1));
    expect(mocks.navigateTo).toHaveBeenCalledWith({ url: '/pages/community/detail?id=example-01' });
    expect(mocks.reLaunch).not.toHaveBeenCalled();
    expect(mocks.redirectTo).not.toHaveBeenCalled();
    expect(mocks.navigateBack).not.toHaveBeenCalled();
    route.resolve();
    await Promise.all([first, ...following]);
    await navigatePrimary('profile');
    expect(mocks.reLaunch).toHaveBeenCalledWith({ url: '/pages/profile/index' });
  });
  it.each(['reLaunch', 'redirectTo', 'navigateBack'] as const)('coalesces repeated %s transitions', async method => {
    const route = deferred();
    mocks[method].mockReturnValueOnce(route.promise);
    mocks.getCurrentPages.mockReturnValue([{ route: 'pages/growth/index' }, { route: 'pages/session/index' }]);
    const start = method === 'reLaunch' ? () => navigatePrimary('community')
      : method === 'redirectTo' ? () => openTool('reports') : () => backFromTool();
    const first = start();
    const second = start();
    expect(second).toBe(first);
    await vi.waitFor(() => expect(mocks[method]).toHaveBeenCalledTimes(1));
    route.resolve();
    await Promise.all([first, second]);
  });
  it('clears a rejected transition and allows a later retry', async () => {
    mocks.navigateTo.mockRejectedValueOnce(new Error('navigation unavailable'));
    const first = openPage('/pages/community/compose');
    expect(openPage('/pages/community/compose')).toBe(first);
    await expect(first).rejects.toThrow('navigation unavailable');
    await openPage('/pages/community/compose');
    expect(mocks.navigateTo).toHaveBeenCalledTimes(2);
  });
  it('dismisses the keyboard before route mutation and guards taps during dismissal', async () => {
    const keyboard = deferred();
    mocks.dismissKeyboard.mockReturnValueOnce(keyboard.promise);
    const first = openPage('/pages/community/compose');
    await vi.waitFor(() => expect(mocks.dismissKeyboard).toHaveBeenCalledTimes(1));
    expect(navigatePrimary('growth')).toBe(first);
    expect(mocks.navigateTo).not.toHaveBeenCalled();
    keyboard.resolve();
    await first;
    expect(mocks.navigateTo).toHaveBeenCalledWith({ url: '/pages/community/compose' });
    expect(mocks.reLaunch).not.toHaveBeenCalled();
  });
  it('still navigates when keyboard dismissal fails', async () => {
    mocks.dismissKeyboard.mockRejectedValueOnce(new Error('keyboard API unavailable'));
    await openPage('/pages/community/compose');
    expect(mocks.navigateTo).toHaveBeenCalledWith({ url: '/pages/community/compose' });
  });
  it.each(['settings', '/settings', 'pages/settings/index', '/pages/settings/index?from=profile'])('returns a shallow %s tool entry to profile', async route => {
    mocks.getCurrentPages.mockReturnValue([{ route }]);
    await backFromTool();
    expect(mocks.reLaunch).toHaveBeenCalledWith({ url: '/pages/profile/index' });
    expect(mocks.navigateBack).not.toHaveBeenCalled();
  });
  it('preserves the stack when leaving settings and falls back to growth for other direct tools', async () => {
    mocks.getCurrentPages.mockReturnValue([{ route: 'pages/profile/index' }, { route: 'pages/settings/index' }]);
    await backFromTool();
    expect(mocks.navigateBack).toHaveBeenCalledWith({ delta: 1 });
    expect(mocks.reLaunch).not.toHaveBeenCalled();
    mocks.getCurrentPages.mockReturnValue([{ route: '/reports' }]);
    await backFromTool();
    expect(mocks.reLaunch).toHaveBeenCalledWith({ url: '/pages/growth/index' });
  });
});
