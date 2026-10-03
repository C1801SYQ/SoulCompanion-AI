import { afterEach, describe, expect, it, vi } from 'vitest';
import { createResourceLoop, type ResourceValue } from '../src/hooks/resourceLoop';
import { CompanionError, type RequestHandle } from '../src/services/types';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((accept, fail) => { resolve = accept; reject = fail; });
  const cancel = vi.fn();
  return { handle: { promise, cancel } satisfies RequestHandle<T>, resolve, reject, cancel };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

afterEach(() => { vi.useRealTimers(); });

describe('resource lifecycle', () => {
  it('never overlaps a slow request with an interval tick', async () => {
    vi.useFakeTimers();
    const pending = deferred<number>();
    const load = vi.fn(() => pending.handle);
    const states: ResourceValue<number>[] = [];
    const loop = createResourceLoop({ load, interval: 1_000,
      onState: value => states.push(value), onConnection: vi.fn() });
    loop.start();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(load).toHaveBeenCalledTimes(1);
    expect(states).toEqual([{ data: null, status: 'loading', error: '' }]);
    pending.resolve(7);
    await flush();
    expect(states[states.length - 1]).toEqual({ data: 7, status: 'ready', error: '' });
    loop.stop();
  });

  it('cancels the old request and ignores its result after switching query or source', async () => {
    const previous = deferred<string>();
    const next = deferred<string>();
    const states: ResourceValue<string>[] = [];
    const oldLoop = createResourceLoop({ load: () => previous.handle, interval: 0,
      onState: value => states.push(value), onConnection: vi.fn() });
    oldLoop.start();
    oldLoop.stop();
    const currentLoop = createResourceLoop({ load: () => next.handle, interval: 0,
      onState: value => states.push(value), onConnection: vi.fn() });
    currentLoop.start();
    previous.resolve('old private data');
    next.resolve('current source');
    await flush();
    expect(previous.cancel).toHaveBeenCalledTimes(1);
    expect(states.some(value => value.data === 'old private data')).toBe(false);
    expect(states[states.length - 1]?.data).toBe('current source');
    currentLoop.stop();
  });

  it('clears previous data on offline failure and backs off before recovery', async () => {
    vi.useFakeTimers();
    const first = deferred<number>();
    const second = deferred<number>();
    const third = deferred<number>();
    const pending = [first, second, third];
    const load = vi.fn(() => pending.shift()!.handle);
    const states: ResourceValue<number>[] = [];
    const loop = createResourceLoop({ load, interval: 5_000,
      onState: value => states.push(value), onConnection: vi.fn() });
    loop.start();
    first.resolve(1);
    await flush();
    await vi.advanceTimersByTimeAsync(5_000);
    second.reject(new CompanionError('offline', 'offline'));
    await flush();
    expect(states[states.length - 1]).toEqual({ data: null, status: 'offline', error: 'offline' });
    await vi.advanceTimersByTimeAsync(999);
    expect(load).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(load).toHaveBeenCalledTimes(3);
    third.resolve(3);
    await flush();
    expect(states[states.length - 1]?.status).toBe('ready');
    loop.stop();
  });

  it('respects rate limit cooldown and clears its timer on unmount', async () => {
    vi.useFakeTimers();
    const pending = deferred<number>();
    const load = vi.fn(() => pending.handle);
    const loop = createResourceLoop({ load, interval: 1_000,
      onState: vi.fn(), onConnection: vi.fn() });
    loop.start();
    pending.reject(new CompanionError('error', 'limited', { retryAfterMs: 60_000 }));
    await flush();
    await vi.advanceTimersByTimeAsync(59_999);
    expect(load).toHaveBeenCalledTimes(1);
    loop.stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('keeps HTTP/contract failures as error and handles synchronous invalid config', () => {
    const onState = vi.fn();
    const loop = createResourceLoop<number>({
      load: () => { throw new CompanionError('error', 'invalid api'); },
      interval: 0, onState, onConnection: vi.fn(),
    });
    loop.start();
    expect(onState).toHaveBeenLastCalledWith({ data: null, status: 'error', error: 'invalid api' });
    loop.stop();
  });
});
