import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useDidHide, useDidShow } from '@tarojs/taro';
import type { RequestHandle } from '../services/types';
import { useCompanion } from '../state/AppProvider';
import { createResourceLoop, type ResourceValue } from './resourceLoop';

export function useResource<T>(key: string, loader: () => RequestHandle<T>, interval = 0):
ResourceValue<T> & { retry(): void } {
  const { epoch, reportConnection } = useCompanion();
  const channelId = useId();
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const [retryToken, setRetryToken] = useState(0);
  const [visible, setVisible] = useState(true);
  useDidHide(() => setVisible(false));
  useDidShow(() => {
    setVisible(true);
    setRetryToken(value => value + 1);
  });
  const [state, setState] = useState<ResourceValue<T> & { key: string; epoch: number; retryToken: number }>({
    key, epoch, retryToken, data: null, status: 'loading', error: '',
  });
  useEffect(() => {
    if (!visible) {
      reportConnection(channelId, null);
      return;
    }
    const loop = createResourceLoop({
      load: () => loaderRef.current(), interval,
      onState: value => setState({ ...value, key, epoch, retryToken }),
      onConnection: connection => reportConnection(channelId, connection),
    });
    loop.start();
    return () => {
      loop.stop();
      reportConnection(channelId, null);
    };
  }, [key, epoch, retryToken, interval, visible, reportConnection, channelId]);
  const retry = useCallback(() => setRetryToken(value => value + 1), []);
  // Hide previous source/range results in this render, before effects cancel the request.
  if (!visible || state.key !== key || state.epoch !== epoch || state.retryToken !== retryToken) {
    return { data: null, status: 'loading', error: '', retry };
  }
  return { data: state.data, status: state.status, error: state.error, retry };
}
