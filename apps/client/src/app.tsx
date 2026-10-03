import type { PropsWithChildren } from 'react';
import { AppProvider } from './state/AppProvider';
import { ClientErrorBoundary } from './components/ClientErrorBoundary';
import { SessionProvider } from './state/SessionProvider';
import '@taroify/core/button/style';
import './design/styles.scss';

export default function App({ children }: PropsWithChildren) {
  return <AppProvider><ClientErrorBoundary><SessionProvider>{children}</SessionProvider></ClientErrorBoundary></AppProvider>;
}
