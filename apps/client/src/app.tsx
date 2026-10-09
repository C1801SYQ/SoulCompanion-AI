import { useEffect, useRef, type PropsWithChildren } from 'react';
import { AppProvider } from './state/AppProvider';
import { ClientErrorBoundary } from './components/ClientErrorBoundary';
import { SessionProvider } from './state/SessionProvider';
import { CloudProvider, useCloud } from './state/CloudProvider';
import { resetCommunityMemory } from './community/memory';
import '@taroify/core/button/style';
import './design/styles.scss';
import './design/parent-community.scss';

function PreviewMemoryBoundary({ children }: PropsWithChildren) {
  const { state } = useCloud();
  const authEpoch = useRef(state.auth.epoch);
  useEffect(() => {
    if (authEpoch.current === state.auth.epoch) return;
    authEpoch.current = state.auth.epoch;
    resetCommunityMemory();
  }, [state.auth.epoch]);
  return <>{children}</>;
}

export default function App({ children }: PropsWithChildren) {
  return <AppProvider><ClientErrorBoundary><CloudProvider><PreviewMemoryBoundary><SessionProvider>{children}</SessionProvider></PreviewMemoryBoundary></CloudProvider></ClientErrorBoundary></AppProvider>;
}
