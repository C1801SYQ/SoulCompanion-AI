import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { useDidHide, useDidShow } from '@tarojs/taro';
import { MediaSessionController } from '../media/MediaSessionController';
import { createMediaCaptureAdapter } from '../media/factory';
import type { MediaCaptureAdapter, MediaSelection, MediaSessionState, MediaStopReason } from '../media/types';
import { useCompanion } from './AppProvider';
import { useCloud } from './CloudProvider';
import { CloudSessionBridge, type MetadataState } from '../cloud/session';
import { cloudSourcePlatform } from '../cloud/auth/platform';

interface SessionContext {
  adapter: MediaCaptureAdapter;
  state: MediaSessionState;
  start(selection: MediaSelection): Promise<void>;
  stop(reason?: MediaStopReason): Promise<void>;
  metadata: MetadataState;
  retryCloudEnd(): void;
}

const Context = createContext<SessionContext | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const { source, connection } = useCompanion();
  const { state: cloudState, store: cloudStore } = useCloud();
  const [session] = useState(() => {
    const adapter = createMediaCaptureAdapter();
    return { adapter, controller: new MediaSessionController(adapter) };
  });
  const [bridge] = useState(() => new CloudSessionBridge(cloudStore.auth, cloudStore.api, cloudSourcePlatform));
  const metadata = useSyncExternalStore(bridge.subscribe, bridge.getState, bridge.getState);
  const cloudContext = useRef({ identity: cloudState.auth.principal?.subject ?? null, authEpoch: cloudState.auth.epoch, selectedId: cloudState.selectedId });
  const currentCloud = useRef(cloudState);
  currentCloud.current = cloudState;
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
  useEffect(() => {
    let previous = session.controller.getState().phase;
    const unsubscribe = session.controller.subscribe(() => {
      const phase = session.controller.getState().phase;
      if (phase === previous) return;
      previous = phase;
      if (phase === 'active') bridge.begin(currentCloud.current.selectedId);
      else bridge.end();
    });
    return () => {
      // Stop local intent first; metadata confirmation never controls device release.
      void session.controller.dispose();
      bridge.end(); unsubscribe(); bridge.dispose();
    };
  }, [session, bridge]);
  useEffect(() => {
    const next = { identity: cloudState.auth.principal?.subject ?? null, authEpoch: cloudState.auth.epoch, selectedId: cloudState.selectedId };
    const previous = cloudContext.current;
    cloudContext.current = next;
    if (next.identity !== previous.identity || next.authEpoch !== previous.authEpoch || next.selectedId !== previous.selectedId) {
      const phase = session.controller.getState().phase;
      if (phase === 'active' || phase === 'starting') void session.controller.stop('source_change');
      bridge.clearPrivate();
    }
  }, [session, bridge, cloudState.auth.epoch, cloudState.auth.principal, cloudState.selectedId]);
  const start = useCallback((selection: MediaSelection) => session.controller.start(selection), [session]);
  const stop = useCallback((reason?: MediaStopReason) => session.controller.stop(reason), [session]);
  const retryCloudEnd = useCallback(() => bridge.retryEnd(), [bridge]);
  const value = useMemo(() => ({ adapter: session.adapter, state, start, stop, metadata, retryCloudEnd }), [session, state, start, stop, metadata, retryCloudEnd]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSession(): SessionContext {
  const context = useContext(Context);
  if (!context) throw new Error('useSession must be used inside SessionProvider');
  return context;
}
