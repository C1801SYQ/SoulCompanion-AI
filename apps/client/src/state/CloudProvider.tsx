import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { cloudConfig } from '../cloud/config';
import { createCloudAuthAdapter } from '../cloud/auth/platform';
import { createCloudApi } from '../cloud/api';
import { CloudApiTransport } from '../cloud/transport';
import { CloudStore } from '../cloud/store';
import type { CloudState } from '../cloud/store';
interface CloudContext { state: CloudState; store: CloudStore }
const Context = createContext<CloudContext | null>(null);
export function CloudProvider({ children, injectedStore }: { children: ReactNode; injectedStore?: CloudStore }) {
  const [store] = useState(() => {
    if (injectedStore) return injectedStore;
    const config = cloudConfig();
    if (!config.enabled) return new CloudStore(null, null);
    const auth = createCloudAuthAdapter(config);
    return new CloudStore(auth, createCloudApi(new CloudApiTransport(config.apiBaseUrl, auth)), false);
  });
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  useEffect(() => () => store.dispose(), [store]);
  return <Context.Provider value={{ state, store }}>{children}</Context.Provider>;
}
export function useCloud(): CloudContext { const context = useContext(Context); if (!context) throw new Error('useCloud must be used inside CloudProvider'); return context; }
