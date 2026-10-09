import { Component, type ComponentType, type PropsWithChildren } from 'react';
import Taro from '@tarojs/taro';
import { Text, View } from '@tarojs/components';
import { AccessibleButton } from './AccessibleButton';

interface BoundaryState {
  failed: boolean;
  navigationFailed: boolean;
}

export class ClientErrorBoundary extends Component<PropsWithChildren, BoundaryState> {
  state: BoundaryState = { failed: false, navigationFailed: false };

  static getDerivedStateFromError(_error: unknown): BoundaryState {
    return { failed: true, navigationFailed: false };
  }

  private retry = () => {
    this.setState({ failed: false, navigationFailed: false });
  };

  private goHome = () => {
    void Taro.reLaunch({ url: '/pages/community/index' })
      .then(this.retry)
      .catch(() => this.setState({ navigationFailed: true }));
  };

  render() {
    if (!this.state.failed) return this.props.children;
    return <View className="sc-recovery" role="main">
      <View className="sc-recovery-card" id="client-error-boundary">
        <Text className="sc-eyebrow">予怀</Text>
        <View className="sc-page-title" role="heading" aria-level="1"><Text>页面暂时遇到一点问题</Text></View>
        <Text className="sc-body-muted">这次没有显示成功。可以重试当前页面，或回到首页继续。</Text>
        <View className="sc-recovery-actions"><AccessibleButton id="client-error-retry" className="sc-recovery-primary" onClick={this.retry}>重试当前页面</AccessibleButton><AccessibleButton id="client-error-home" className="sc-small-button" onClick={this.goHome}>回到首页</AccessibleButton></View>
        {this.state.navigationFailed && <View role="status"><Text className="sc-inline-error">暂时无法返回首页，请重试当前页面。</Text></View>}
      </View>
    </View>;
  }
}

/** Place our recoverable boundary below Taro's page wrapper, which otherwise swallows render errors. */
export function withClientErrorBoundary(Page: ComponentType): ComponentType {
  function GuardedPage() {
    return <ClientErrorBoundary><Page /></ClientErrorBoundary>;
  }
  GuardedPage.displayName = `Guarded(${Page.displayName || Page.name || 'Page'})`;
  return GuardedPage;
}
