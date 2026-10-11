import { useState } from 'react';
import { Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { SectionCard, StatusPill } from '../../components/Primitives';
import type { AuthStatus } from '../../cloud/types';
import { openPage } from '../../navigation';
import { useCloud } from '../../state/CloudProvider';
import { useCommunity } from '../../state/CommunityProvider';
import { CommunityModeNote } from '../../community/components';
import { CommunityAccountPanel, useCommunityIdentity } from '../../community/AccountPanel';

const accountLabels: Record<AuthStatus, string> = {
  signed_out: '未登录', signing_in: '正在登录', signed_in: '已登录',
  expired: '登录已失效', offline: '账号连接暂时不可用', error: '账号状态暂时不可用',
};

function DemoProfilePage() {
  // Public account entry reads only authentication status, never private records or principal IDs.
  const { state } = useCloud();
  const accountLabel = state.enabled ? accountLabels[state.auth.status] : '云端账号尚未配置';
  const [navigationError, setNavigationError] = useState('');
  function openAccount() {
    setNavigationError('');
    void openPage('/pages/settings/index').catch(() => setNavigationError('暂时无法打开账号与设置，请再试一次。'));
  }

  return <AppShell page="profile">
    <CommunityModeNote mode="demo" />
    <PageHeader eyebrow="我的 · 你的予怀空间" title="按自己的节奏，安心交流。" description="这里为成年家长和监护人保留账号与隐私入口。未登录，也可以浏览社区示例和知识分类。" />
    <View className="pc-profile-card"><View><Text className="sc-setting-name">当前账号状态</Text><Text className="sc-body-muted">这里只显示登录状态，不读取私有家庭资料，也不展示内部身份编号。</Text></View><StatusPill id="pc-account-status" tone={state.enabled && state.auth.status === 'signed_in' ? 'good' : 'quiet'}>{accountLabel}</StatusPill></View>
    <View className="pc-support-grid">
      <SectionCard title="账号与私有档案" eyebrow="主动进入后查看">
        <Text className="sc-body-muted">沿用已有登录、儿童私有档案与设置。家庭资料不会作为公开作者身份，也不是社区浏览的门槛。</Text>
        <Button id="pc-private-account" className="sc-small-button" onClick={openAccount}>账号与私有档案</Button>
        {navigationError && <View className="sc-resource-notice sc-resource-notice--error" role="status"><Text>{navigationError}</Text></View>}
      </SectionCard>
      <SectionCard title="公开社区昵称" eyebrow="自主选择 · 独立资料">
        <View className="pc-preview-placeholder"><Text className="sc-setting-name">让你决定如何被认识</Text><Text className="sc-body-muted">主动进入账号与设置后，可查看云端是否开放昵称保存。公开昵称与登录身份及儿童档案分开；当前帖子作者仍为合成示例，真实社区发布尚未开放。</Text></View>
        <Button id="pc-parent-identity" className="sc-small-button" onClick={openAccount}>查看社区昵称设置</Button>
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

function RealProfilePage() {
  const { state } = useCloud();
  const identity = useCommunityIdentity();
  const [navigationError, setNavigationError] = useState('');
  function open(url: string) {
    setNavigationError('');
    void openPage(url).catch(() => setNavigationError('暂时无法打开页面，请再试一次。'));
  }
  return <AppShell page="profile">
    <CommunityModeNote mode="real" />
    <PageHeader eyebrow="我的 · 你的予怀空间" title="按自己的节奏，安心交流。" description="成年家长和监护人的社区空间。未登录也可以浏览公开帖子，参与交流时再主动登录。" />
    <View className="pc-profile-card"><View><Text className="sc-setting-name">当前账号状态</Text><Text className="sc-body-muted">只显示登录状态和主动设置的公开昵称，不读取儿童档案、报告或内部身份编号。</Text></View><StatusPill id="pc-account-status" tone={state.auth.status === 'signed_in' ? 'good' : 'quiet'}>{accountLabels[state.auth.status]}</StatusPill></View>
    <CommunityAccountPanel identity={identity} />
    <View className="pc-support-grid">
      <SectionCard title="我的社区内容" eyebrow="仅当前账号可见">
        <Text className="sc-body-muted">查看投稿和评论的当前审核状态、反馈，编辑或撤回本人内容；收藏仅显示当前仍公开的帖子。</Text>
        <View className="pc-interactions"><Button id="pc-my-posts" className="pc-action" onClick={() => open('/pages/community/mine?tab=posts')}>我的投稿</Button><Button id="pc-my-comments" className="pc-action" onClick={() => open('/pages/community/mine?tab=comments')}>我的评论</Button><Button id="pc-my-bookmarks" className="pc-action" onClick={() => open('/pages/community/mine?tab=bookmarks')}>我的收藏</Button></View>
      </SectionCard>
      <SectionCard title="账号与私有家庭档案" eyebrow="另行主动进入后查看">
        <Text className="sc-body-muted">家庭昵称和儿童档案不会作为社区公开作者身份，也不是浏览或投稿的门槛。只在主动进入家庭工具后读取。</Text><Button id="pc-private-account" className="pc-action" onClick={() => open('/pages/settings/index')}>账号与私有档案</Button>
      </SectionCard>
      <SectionCard title="隐私与自主选择" eyebrow="由你决定分享什么">
        <Text className="sc-body-muted">社区不自动读取儿童档案或私有报告，不申请摄像头与麦克风权限。公开昵称不使用账号标识、微信 OpenID、电话、邮箱或孩子姓名。</Text><Text className="sc-body-muted">投稿与评论先经人工审核。请不分享学校、住址、联系方式及其他可以识别儿童的信息。</Text>
      </SectionCard>
    </View>
    {navigationError && <View className="sc-inline-error" role="status"><Text>{navigationError}</Text></View>}
  </AppShell>;
}

function ProfilePage() {
  const { state } = useCommunity();
  return state.mode === 'demo' ? <DemoProfilePage /> : <RealProfilePage />;
}

export default withClientErrorBoundary(ProfilePage);
