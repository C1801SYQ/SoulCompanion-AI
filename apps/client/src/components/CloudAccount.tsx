import { useEffect, useState } from 'react';
import { Input, Text, View } from '@tarojs/components';
import { AccessibleButton } from './AccessibleButton';
import { EmptyState, SectionCard, StatusPill } from './Primitives';
import { useCloud } from '../state/CloudProvider';
import { useSession } from '../state/SessionProvider';
import { cloudSourcePlatform } from '../cloud/auth/platform';

export function CloudAccount() {
  const { state, store } = useCloud();
  const { stop } = useSession();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [nickname, setNickname] = useState('');
  const [editId, setEditId] = useState<string | null>(null);
  useEffect(() => { setPassword(''); setName(''); setNickname(''); setEditId(null); }, [state.auth.epoch, state.selectedId]);
  const busy = state.status === 'loading' || state.auth.status === 'signing_in';
  const signedIn = state.auth.status === 'signed_in';
  function signIn() {
    const input = { username, password };
    setPassword('');
    void stop('source_change');
    void store.signIn(input);
  }
  function select(id: string | null) { void stop('source_change'); store.selectProfile(id); setEditId(null); setNickname(''); }
  function logout() { void stop('source_change'); setPassword(''); setUsername(''); setName(''); setNickname(''); setEditId(null); void store.signOut(); }
  function saveProfile() { const value = nickname; setNickname(''); const id = editId; setEditId(null); void (id ? store.updateProfile(id, value) : store.createProfile(value)); }
  function archive(id: string) { if (id === state.selectedId) select(null); void store.archiveProfile(id); }
  const authLabel = ({ signed_out: '未登录', signing_in: '正在登录', signed_in: '已登录', expired: '登录已失效', offline: '登录服务离线', error: '登录未完成' })[state.auth.status];
  return <SectionCard title="云端账号与档案" eyebrow="账号边界 · 音视频仍在本机">
    <View className="sc-cloud-heading"><StatusPill id="cloud-auth-status" tone={signedIn ? 'good' : 'quiet'}>{state.enabled ? authLabel : '云端尚未配置'}</StatusPill><Text className="sc-body-muted">只同步账号、档案昵称与会话起止时间。</Text></View>
    {!state.enabled ? <EmptyState title="本地陪伴可以继续" detail="此构建未连接云端账号服务。摄像头与麦克风仍需主动开启，媒体仍留在本机。" /> : !signedIn ? <View className="sc-cloud-form">
      {cloudSourcePlatform === 'web' && <><Text className="sc-setting-name">用户名</Text><Input id="cloud-username" className="sc-cloud-input" ariaLabel="云端用户名" value={username} maxlength={128} disabled={busy} onInput={event => setUsername(event.detail.value)} /><Text className="sc-setting-name">密码</Text><Input id="cloud-password" className="sc-cloud-input" ariaLabel="云端密码" password value={password} maxlength={256} disabled={busy} onInput={event => setPassword(event.detail.value)} /></>}
      <AccessibleButton id="cloud-sign-in" className="sc-small-button" disabled={busy} onClick={signIn}>{cloudSourcePlatform === 'wechat' ? '使用微信账号登录' : '登录云端账号'}</AccessibleButton><Text className="sc-body-muted">登录信息仅用于官方认证；刷新页面后需要重新登录。</Text>
    </View> : <View>
      <View className="sc-cloud-heading"><Text id="cloud-display-name" className="sc-setting-name">{state.user?.display_name || '我的陪伴账号'}</Text><AccessibleButton id="cloud-refresh" className="sc-small-button" disabled={busy} onClick={() => void store.refresh()}>刷新云端资料</AccessibleButton><AccessibleButton id="cloud-sign-out" className="sc-small-button" onClick={logout}>退出登录</AccessibleButton></View>
      <View className="sc-cloud-form"><Input id="cloud-display-name-input" className="sc-cloud-input" ariaLabel="账号显示名称" placeholder="修改账号显示名称" value={name} maxlength={64} disabled={busy} onInput={event => setName(event.detail.value)} /><AccessibleButton id="cloud-save-name" className="sc-small-button" disabled={busy || !name.trim()} onClick={() => { const value = name; setName(''); void store.updateUser(value); }}>保存显示名称</AccessibleButton></View>
      <Text className="sc-setting-name">陪伴档案 · 请主动选择</Text>
      {!state.profiles.length && state.status === 'ready' && <View id="cloud-profile-empty"><EmptyState title="还没有陪伴档案" detail="只需一个昵称。创建后请主动选择档案，再开始记录云端会话。" /></View>}
      <View id="cloud-profile-list" className="sc-cloud-profiles">{state.profiles.map((profile, index) => <View key={profile.id} className="sc-cloud-profile"><AccessibleButton id={`cloud-profile-select-${index}`} className="sc-small-button" aria-pressed={state.selectedId === profile.id} disabled={busy} onClick={() => select(profile.id)}>{profile.nickname}{state.selectedId === profile.id ? ' · 已选择' : ' · 选择'}</AccessibleButton><AccessibleButton id={`cloud-profile-edit-${index}`} className="sc-small-button" disabled={busy} onClick={() => { setEditId(profile.id); setNickname(profile.nickname); }}>修改昵称</AccessibleButton><AccessibleButton id={`cloud-profile-archive-${index}`} className="sc-small-button" disabled={busy} onClick={() => archive(profile.id)}>归档</AccessibleButton></View>)}</View>
      {state.selectedId && <AccessibleButton id="cloud-profile-clear" className="sc-small-button" disabled={busy} onClick={() => select(null)}>取消档案选择</AccessibleButton>}
      <View className="sc-cloud-form"><Input id="cloud-profile-nickname" className="sc-cloud-input" ariaLabel="陪伴档案昵称" placeholder="陪伴档案昵称" value={nickname} maxlength={64} disabled={busy} onInput={event => setNickname(event.detail.value)} /><AccessibleButton id="cloud-profile-save" className="sc-small-button" disabled={busy || !nickname.trim()} onClick={saveProfile}>{editId ? '保存档案昵称' : '创建档案'}</AccessibleButton>{editId && <AccessibleButton className="sc-small-button" onClick={() => { setEditId(null); setNickname(''); }}>取消修改</AccessibleButton>}</View>
      <Text className="sc-setting-footnote">切换档案或退出登录会结束本地采集，并隐藏当前档案的云端资料。归档不自动删除会话记录。</Text>
    </View>}
    {(state.auth.message || state.message) && <View id="cloud-error" className="sc-inline-error" role="status"><Text>{state.auth.message || state.message}</Text></View>}
  </SectionCard>;
}
