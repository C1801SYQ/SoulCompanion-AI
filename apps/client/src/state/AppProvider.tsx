import { createContext, useCallback, useContext, useMemo, useReducer, type ReactNode } from 'react';
import type { Mode } from '../types/contracts';
import { createDemoApi } from '../services/demo';
import { createV1Api } from '../services/v1';
import type { CompanionApi, ConnectionState } from '../services/types';

const DEFAULT_DEMO_ONLY = typeof PUBLIC_DEMO_ONLY !== 'undefined' && PUBLIC_DEMO_ONLY;

interface AppState {
  source: Mode;
  epoch: number;
  motionEnabled: boolean;
  channels: Record<string, ConnectionState>;
}

type AppAction =
  | { type: 'source'; source: Mode }
  | { type: 'motion'; enabled: boolean }
  | { type: 'channel'; id: string; epoch: number; connection: ConnectionState | null };

function reducer(state: AppState, action: AppAction): AppState {
  if (action.type === 'source') {
    return state.source === action.source ? state
      : { ...state, source: action.source, epoch: state.epoch + 1, channels: {} };
  }
  if (action.type === 'motion') return { ...state, motionEnabled: action.enabled };
  if (action.epoch !== state.epoch) return state;
  if ((state.channels[action.id] ?? null) === action.connection) return state;
  const channels = { ...state.channels };
  if (action.connection === null) delete channels[action.id];
  else channels[action.id] = action.connection;
  return { ...state, channels };
}

interface CompanionContext {
  source: Mode;
  setSource(source: Mode): void;
  demoOnly: boolean;
  motionEnabled: boolean;
  setMotionEnabled(enabled: boolean): void;
  api: CompanionApi;
  connection: ConnectionState;
  epoch: number;
  reportConnection(id: string, connection: ConnectionState | null): void;
}

const Context = createContext<CompanionContext | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const demoOnly = DEFAULT_DEMO_ONLY;
  const [state, dispatch] = useReducer(reducer, {
    source: demoOnly ? 'demo' : 'real', epoch: 0, motionEnabled: true, channels: {},
  });
  const setSource = useCallback((source: Mode) => {
    if (demoOnly && source === 'real') return;
    dispatch({ type: 'source', source });
  }, [demoOnly]);
  const setMotionEnabled = useCallback((enabled: boolean) => {
    dispatch({ type: 'motion', enabled });
  }, []);
  const reportConnection = useCallback((id: string, connection: ConnectionState | null) => {
    dispatch({ type: 'channel', id, connection, epoch: state.epoch });
  }, [state.epoch]);
  const api = useMemo(() => state.source === 'demo' ? createDemoApi() : createV1Api(), [state.source]);
  const connections = Object.values(state.channels);
  const connection: ConnectionState = connections.includes('offline') ? 'offline'
    : connections.includes('error') ? 'error'
      : connections.includes('connecting') ? 'connecting'
        : connections.length > 0 ? 'online' : state.source === 'demo' ? 'online' : 'connecting';
  const value = useMemo<CompanionContext>(() => ({
    source: state.source, setSource, demoOnly, motionEnabled: state.motionEnabled,
    setMotionEnabled, api, connection, epoch: state.epoch, reportConnection,
  }), [state.source, state.motionEnabled, state.epoch, setSource, demoOnly,
    setMotionEnabled, api, connection, reportConnection]);
  // Only preferences and active requests live here; no raw media, records or tokens persist.
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useCompanion(): CompanionContext {
  const context = useContext(Context);
  if (!context) throw new Error('useCompanion must be used inside AppProvider');
  return context;
}
