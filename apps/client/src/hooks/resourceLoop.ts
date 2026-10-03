import { CompanionError, type ConnectionState, type RequestHandle } from '../services/types';

export type ResourceStatus = 'loading' | 'ready' | 'offline' | 'error';
export interface ResourceValue<T> {
  data: T | null;
  status: ResourceStatus;
  error: string;
}

/** Request lifetime logic is independent of React and platform APIs. */
export function createResourceLoop<T>(options: {
  load: () => RequestHandle<T>;
  interval: number;
  onState(value: ResourceValue<T>): void;
  onConnection(state: ConnectionState): void;
}): { start(): void; stop(): void } {
  let stopped = false;
  let started = false;
  let generation = 0;
  let failures = 0;
  let active: RequestHandle<T> | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const current = (version: number) => !stopped && version === generation;
  const schedule = (delay: number) => {
    if (!stopped && options.interval > 0) timer = setTimeout(run, delay);
  };
  const failure = (error: unknown, version: number) => {
    if (!current(version)) return;
    if (error instanceof CompanionError && error.kind === 'cancelled') return;
    failures += 1;
    const status = error instanceof CompanionError && error.kind === 'offline' ? 'offline' : 'error';
    options.onState({ data: null, status,
      error: error instanceof CompanionError ? error.message : '暂时无法读取数据，请重试。' });
    options.onConnection(status);
    const backoff = Math.min(30_000, 1_000 * 2 ** Math.min(failures - 1, 5));
    schedule(Math.max(backoff, error instanceof CompanionError ? error.retryAfterMs ?? 0 : 0));
  };
  function run() {
    if (stopped || active !== null) return;
    const version = ++generation;
    try {
      const handle = options.load();
      active = handle;
      void handle.promise.then(data => {
        if (!current(version)) return;
        failures = 0;
        options.onState({ data, status: 'ready', error: '' });
        options.onConnection('online');
        schedule(options.interval);
      }, error => failure(error, version)).finally(() => {
        if (current(version)) active = null;
      });
    } catch (error) {
      failure(error, version);
    }
  }
  return {
    start() {
      if (started || stopped) return;
      started = true;
      options.onState({ data: null, status: 'loading', error: '' });
      options.onConnection('connecting');
      run();
    },
    stop() {
      stopped = true;
      generation += 1;
      clearTimeout(timer);
      active?.cancel();
      active = null;
    },
  };
}
