import { useState } from 'react';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { SectionCard, StatusPill } from '../../components/Primitives';
import type { AuthStatus } from '../../cloud/types';
import { openPage } from '../../navigation';
import { useCloud } from '../../state/CloudProvider';

const accountLabels: Record<AuthStatus, string> = {
  signed_out: '未登录', signing_in: '正在登录', signed_in: '已登录',
  expired: '登录已失效', offline: '账号连接暂时不可用', error: '账号状态暂时不可用',
};

function ProfilePage() {
  // Public account entry reads only authentication status, never private records or principal IDs.
  const { state } = useCloud();
  const accountLabel = state.enabled ? accountLabels[state.auth.status] : '云端账号尚未配置';
  const [navigationError, setNavigationError] = useState('');
  function openAccount() {
    setNavigationError('');
    void openPage('/pages/settings/index').catch(() => setNavigationError('暂时无法打开账号与设置，请再试一次。'));
  }

  return <AppShell page="profile">
    <PageHeader eyebrow="我的 · 你的予怀空间" title="按自己的节奏，安心交流。" description="这里为成年家长和监护人保留账号与隐私入口。未登录，也可以浏览社区示例和知识分类。" />
    <View className="pc-profile-card"><View><Text className="sc-setting-name">当前账号状态</Text><Text className="sc-body-muted">这里只显示登录状态，不读取私有家庭资料，也不展示内部身份编号。</Text></View><StatusPill id="pc-account-status" tone={state.enabled && state.auth.status === 'signed_in' ? 'good' : 'quiet'}>{accountLabel}</StatusPill></View>
    <View className="pc-support-grid">
      <SectionCard title="账号与私有档案" eyebrow="主动进入后查看">
        <Text className="sc-body-muted">沿用已有登录、儿童私有档案与设置。家庭资料不会作为公开作者身份，也不是社区浏览的门槛。</Text>
        <Button id="pc-private-account" className="sc-small-button" onClick={openAccount}>账号与私有档案</Button>
        {navigationError && <View className="sc-resource-notice sc-resource-notice--error" role="status"><Text>{navigationError}</Text></View>}
      </SectionCard>
      <SectionCard title="公开社区昵称" eyebrow="未来位置 · 尚未接入">
        <View className="pc-preview-placeholder"><Text className="sc-setting-name">让你决定如何被认识</Text><Text className="sc-body-muted">公开昵称将与登录身份及儿童档案分开。当前示例作者均为合成昵称，这里尚不能设置或展示真实社区身份。</Text></View>
      </SectionCard>
      <SectionCard title="我的投稿与收藏" eyebrow="未来位置 · 尚未接入">
        <View className="pc-preview-placeholder"><Text className="sc-setting-name">目前还没有真实社区操作</Text><Text className="sc-body-muted">投稿入口仅供本地文本预览，不会发布、送审或保存云端帖子；收藏功能尚未接入。</Text></View>
      </SectionCard>
      <SectionCard title="隐私与自主选择" eyebrow="每一步都由你决定">
        <View className="pc-preview-placeholder"><Text className="sc-body-muted">社区示例不读取儿童档案、私有报告或设备信息，也不会申请摄像头与麦克风权限。</Text><Text className="sc-body-muted">分享时请避免填写孩子姓名、学校、住址及其他隐私。设备预览与账号偏好可以在账号与设置中查看说明。</Text></View>
      </SectionCard>
    </View>
  </AppShell>;
}

export default withClientErrorBoundary(ProfilePage);
