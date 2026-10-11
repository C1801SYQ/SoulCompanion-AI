import { createContext, useContext, useEffect, useState, useSyncExternalStore, type PropsWithChildren } from 'react';
import { cloudConfig } from '../cloud/config';
import { createCommunityApi } from '../community/api';
import { CommunityTransport } from '../community/transport';
import { CommunityStore } from '../community/store';
import { useCloud } from './CloudProvider';

const CommunityContext = createContext<{
  state: ReturnType<CommunityStore['getState']>;
  store: CommunityStore;
  api: CommunityStore['api'];
} | null>(null);

/** Share the existing SDK identity; public community reads never enable family scope. */
export function CommunityProvider({ children }: PropsWithChildren) {
  const { store: cloud } = useCloud();
  const [store] = useState(() => {
    const config = cloudConfig();
    const api = config.enabled ? createCommunityApi(new CommunityTransport(config.apiBaseUrl, cloud.auth)) : null;
    return new CommunityStore(config.enabled ? 'real' : 'demo', api, cloud.auth);
  });
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  useEffect(() => () => store.dispose(), [store]);
  return <CommunityContext.Provider value={{ state, store, api: store.api }}>{children}</CommunityContext.Provider>;
}

export function useCommunity() {
  const value = useContext(CommunityContext);
  if (!value) throw new Error('CommunityProvider required');
  return value;
}
