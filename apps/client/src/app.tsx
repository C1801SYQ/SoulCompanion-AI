import type { PropsWithChildren } from 'react';
import { AppProvider } from './state/AppProvider';
import { ClientErrorBoundary } from './components/ClientErrorBoundary';
import '@taroify/core/button/style';
import './design/styles.scss';

export default function App({ children }: PropsWithChildren) {
  return <AppProvider><ClientErrorBoundary>{children}</ClientErrorBoundary></AppProvider>;
}
