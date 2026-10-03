import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { useDidHide, useDidShow } from '@tarojs/taro';
import { MediaSessionController } from '../media/MediaSessionController';
import { createMediaCaptureAdapter } from '../media/factory';
import type { MediaCaptureAdapter, MediaSelection, MediaSessionState, MediaStopReason } from '../media/types';
import { useCompanion } from './AppProvider';

interface SessionContext {
  adapter: MediaCaptureAdapter;
  state: MediaSessionState;
  start(selection: MediaSelection): Promise<void>;
  stop(reason?: MediaStopReason): Promise<void>;
}

const Context = createContext<SessionContext | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const { source, connection } = useCompanion();
  const [session] = useState(() => {
    const adapter = createMediaCaptureAdapter();
    return { adapter, controller: new MediaSessionController(adapter) };
  });
  const contextRef = useRef({ source, connection, visible: true });
  contextRef.current = { ...contextRef.current, source, connection };
  const subscribe = useCallback((listener: () => void) => session.controller.subscribe(listener), [session]);
  const getState = useCallback(() => session.controller.getState(), [session]);
  const state = useSyncExternalStore(subscribe, getState, getState);
  useEffect(() => session.controller.setContext(contextRef.current), [session, source, connection]);
  useDidHide(() => {
    contextRef.current = { ...contextRef.current, visible: false };
    session.controller.setContext(contextRef.current);
  });
  useDidShow(() => {
    contextRef.current = { ...contextRef.current, visible: true };
    session.controller.setContext(contextRef.current);
  });
  useEffect(() => () => { void session.controller.dispose(); }, [session]);
  const start = useCallback((selection: MediaSelection) => session.controller.start(selection), [session]);
  const stop = useCallback((reason?: MediaStopReason) => session.controller.stop(reason), [session]);
  const value = useMemo(() => ({ adapter: session.adapter, state, start, stop }), [session, state, start, stop]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSession(): SessionContext {
  const context = useContext(Context);
  if (!context) throw new Error('useSession must be used inside SessionProvider');
  return context;
}
