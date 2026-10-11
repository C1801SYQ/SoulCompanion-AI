import { useEffect, useId } from 'react';
import { useDidShow } from '@tarojs/taro';
import { Input, Text, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../components/AccessibleButton';
import { EmptyState, SectionCard, StatusPill } from '../components/Primitives';
import { cloudSourcePlatform } from '../cloud/auth/platform';
import { parentNickname } from '../cloud/validation';
import type { ParentCommunityProfile } from '../cloud/types';
import { useScopedForm } from '../cloud/formState';
import { useCloud } from '../state/CloudProvider';
import { useCommunity } from '../state/CommunityProvider';
import { dismissKeyboard, textInputKeyboardProps } from '../platform/keyboard';
import { communityFailureText, isCancelled } from './presentation';
import { useCommunityBusy } from './viewState';

const emptyIdentity = () => ({ profile: null as ParentCommunityProfile | null, status: 'idle' as 'idle' | 'loading' | 'ready' | 'error', draft: '', message: '', saving: false });

/** Reads only the independent public parent profile; never opens the family data scope. */
export function useCommunityIdentity(enabled = true) {
  const cloud = useCloud();
  const community = useCommunity();
  const signedIn = cloud.state.auth.status === 'signed_in';
  const key = `${community.state.mode}:${enabled}:${signedIn}`;
  const form = useScopedForm({ authEpoch: cloud.state.auth.epoch, selectedId: key }, () => ({
    authEpoch: cloud.store.getState().auth.epoch,
    selectedId: `${community.store.getState().mode}:${enabled}:${cloud.store.getState().auth.status === 'signed_in'}`,
  }), emptyIdentity);
  const ownerId = useId().replace(/[^A-Za-z0-9:_-]/g, '');
  const saveBusy = useCommunityBusy(`public-parent-save:${ownerId}:${enabled}`);
  async function reload() {
    if (!form.isCurrent() || saveBusy.current || !enabled || !signedIn || community.state.mode !== 'real' || !cloud.store.api) return;
    form.update(value => ({ ...value, status: 'loading', profile: null, message: '' }));
    const version = form.version();
    try {
      const profile = await community.store.run(cloud.store.api.parentProfile(), { private: true, key: `public-parent-profile:${ownerId}` });
      form.complete(version, value => ({ ...value, profile, status: 'ready' }));
    } catch (error) {
      if (isCancelled(error)) return;
      form.complete(version, value => ({ ...value, profile: null, status: 'error', message: communityFailureText(error) }));
    }
  }
  useEffect(() => { void reload(); }, [enabled, signedIn, cloud.state.auth.epoch, community.state.mode]);
  useDidShow(() => { void reload(); });
  async function save() {
    if (!form.isCurrent() || saveBusy.current || !signedIn || !cloud.store.api || form.values.status !== 'ready' || community.state.mode !== 'real') return;
    let nickname: string;
    try { nickname = parentNickname(form.values.draft); } catch (error) { form.update(value => ({ ...value, message: communityFailureText(error) })); return; }
    saveBusy.current = true;
    form.update(value => ({ ...value, saving: true, message: '' }));
    const version = form.version();
    void dismissKeyboard().catch(() => undefined);
    try {
      const profile = await community.store.run(cloud.store.api.updateParentProfile(nickname), { private: true, key: `public-parent-save:${ownerId}` });
      form.complete(version, value => ({ ...value, profile, draft: '', saving: false, message: '公开社区昵称已由云端确认保存。' }));
    } catch (error) {
      if (!isCancelled(error)) form.complete(version, value => ({ ...value, saving: false, message: `${communityFailureText(error)} 保存尚未确认，请重新读取昵称后核对。` }));
    } finally { saveBusy.current = false; }
  }
  return { ...form.values, signedIn, reload, save, setDraft: (draft: string) => form.update(value => ({ ...value, draft, message: '' })) };
}

export type CommunityIdentity = ReturnType<typeof useCommunityIdentity>;

/** Uses the existing official CloudBase sign-in adapter without refreshing private family data. */
export function CommunityAccountPanel({ identity, compact = false }: { identity?: CommunityIdentity; compact?: boolean }) {
  const cloud = useCloud();
  const community = useCommunity();
  const form = useScopedForm({ authEpoch: cloud.state.auth.epoch, selectedId: community.state.mode }, () => ({
    authEpoch: cloud.store.getState().auth.epoch, selectedId: community.store.getState().mode,
  }), () => ({ username: '', password: '', message: '', busy: false }));
  const busyRef = useCommunityBusy('account-auth');
  const signedIn = cloud.state.auth.status === 'signed_in';
  const busy = cloud.state.auth.status === 'signing_in' || form.values.busy;
  async function signIn() {
    if (!form.isCurrent() || busyRef.current || !cloud.state.enabled || cloud.state.auth.status === 'signing_in' || signedIn || community.state.mode !== 'real') return;
    busyRef.current = true;
    const input = { username: form.values.username, password: form.values.password };
    form.update(value => ({ ...value, password: '', message: '', busy: true }));
    const version = form.version();
    void dismissKeyboard().catch(() => undefined);
    try { await cloud.store.signIn(input); }
    catch (error) { form.complete(version, value => ({ ...value, busy: false, message: communityFailureText(error) })); }
    finally { busyRef.current = false; form.complete(version, value => ({ ...value, password: '', busy: false })); }
  }
  async function signOut() {
    if (!form.isCurrent() || busyRef.current) return;
    busyRef.current = true;
    form.update(() => ({ username: '', password: '', message: '', busy: false }));
    try { await cloud.store.signOut(); }
    catch (error) { if (form.isCurrent()) form.update(value => ({ ...value, message: communityFailureText(error) })); }
    finally { busyRef.current = false; }
  }
  return <SectionCard title={compact ? '登录后参与交流' : '家长账号与公开社区昵称'} eyebrow="官方 CloudBase 身份 · 与家庭档案分开">
    <View className="pc-account-panel">
      <StatusPill id="pc-community-auth" tone={signedIn ? 'good' : 'quiet'}>{signedIn ? '已登录' : cloud.state.auth.status === 'expired' ? '登录已失效' : busy ? '正在登录' : '未登录'}</StatusPill>
      {!signedIn ? !cloud.state.enabled ? <EmptyState title="账号服务尚未配置" detail="公开浏览仍可继续，这里不会创建本地假账号。" /> : <View className="sc-cloud-form">
        {cloudSourcePlatform === 'web' && <>
          <Input id="pc-community-username" className="sc-cloud-input" {...textInputKeyboardProps} ariaLabel="云端用户名" placeholder="云端用户名" maxlength={128} value={form.values.username} disabled={busy} onInput={event => form.update(value => ({ ...value, username: event.detail.value }))} />
          <Input id="pc-community-password" className="sc-cloud-input" {...textInputKeyboardProps} ariaLabel="云端密码" placeholder="密码" password maxlength={256} value={form.values.password} disabled={busy} onInput={event => form.update(value => ({ ...value, password: event.detail.value }))} />
        </>}
        <Button id="pc-community-sign-in" className="pc-action pc-action--primary" disabled={busy} onClick={() => void signIn()}>{cloudSourcePlatform === 'wechat' ? '使用微信账号登录' : '登录家长账号'}</Button>
      </View> : <Button id="pc-community-sign-out" className="pc-action" onClick={() => void signOut()}>退出登录</Button>}
      <Text className="sc-body-muted">未登录也可以浏览公开社区。登录不会要求儿童档案，不读取微信个人头像昵称；密码与令牌不会保存到页面草稿。</Text>
      {(form.values.message || cloud.state.auth.message) && <View className="sc-inline-error" role="status"><Text>{form.values.message || cloud.state.auth.message}</Text></View>}
      {signedIn && identity && <View>
        {identity.status !== 'ready' ? <View id="pc-community-identity-status" role="status"><Text>{identity.status === 'loading' ? '正在确认公开社区资料…' : '公开昵称尚未确认，确认前不能投稿。'}</Text><Button id="pc-community-identity-retry" className="pc-action" disabled={identity.status === 'loading' || identity.saving} onClick={() => void identity.reload()}>重新读取公开昵称</Button></View> : <>
          <Text id="pc-community-nickname-saved" className="sc-setting-name">{identity.profile ? `公开昵称：${identity.profile.nickname}` : '尚未设置公开社区昵称'}</Text>
          <View className="sc-cloud-form"><Input id="pc-community-nickname" className="sc-cloud-input" {...textInputKeyboardProps} ariaLabel="公开社区昵称，2 到 24 字" placeholder="主动选择一个公开昵称" maxlength={-1} value={identity.draft} disabled={identity.saving} onInput={event => identity.setDraft(event.detail.value)} /><Button id="pc-community-nickname-save" className="pc-action" disabled={identity.saving || !identity.draft.trim()} onClick={() => void identity.save()}>保存公开昵称</Button></View>
        </>}
        <Text className="sc-body-muted">2～24 字，允许文字、数字、普通空格、·、_、-；不接受链接、换行或表情。同名昵称可以存在，昵称不是登录凭据。请不要使用孩子姓名。</Text>
        {identity.message && <View id="pc-community-nickname-message" className="sc-inline-error" role="status"><Text>{identity.message}</Text></View>}
      </View>}
    </View>
  </SectionCard>;
}
