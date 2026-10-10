import { Input, Text, View } from '@tarojs/components';
import { AccessibleButton } from './AccessibleButton';
import { EmptyState, SectionCard, StatusPill } from './Primitives';
import { useCloud } from '../state/CloudProvider';
import { useSession } from '../state/SessionProvider';
import { cloudSourcePlatform } from '../cloud/auth/platform';
import { AGE_BANDS, ageLabel } from '../community/constants';
import type { ChildAgeBand } from '../cloud/types';
import { dismissKeyboard, textInputKeyboardProps } from '../platform/keyboard';
import { useScopedForm } from '../cloud/formState';

interface AccountDraft { username: string; password: string; name: string; nickname: string; editId: string | null; ageBand: ChildAgeBand | null }
const emptyAccountDraft = (): AccountDraft => ({ username: '', password: '', name: '', nickname: '', editId: null, ageBand: null });

export function CloudAccount() {
  const { state, store } = useCloud();
  const { stop } = useSession();
  const form = useScopedForm({ authEpoch: state.auth.epoch, selectedId: state.selectedId }, () => {
    const runtime = store.getState(); return { authEpoch: runtime.auth.epoch, selectedId: runtime.selectedId };
  }, emptyAccountDraft);
  const { username, password, name, nickname, editId, ageBand } = form.values;
  const busy = state.status === 'loading' || state.auth.status === 'signing_in';
  const signedIn = state.auth.status === 'signed_in';
  function signIn() {
    if (!form.isCurrent() || busy) return;
    const input = { username, password };
    form.update(current => ({ ...current, password: '' }));
    void stop('source_change');
    void store.signIn(input);
  }
  function select(id: string | null) { if (!form.isCurrent() || busy) return; form.update(current => ({ ...current, editId: null, nickname: '', ageBand: null })); void stop('source_change'); store.selectProfile(id); }
  function logout() { if (!form.isCurrent()) return; form.update(emptyAccountDraft); void stop('source_change'); void store.signOut(); }
  async function saveProfile() {
    if (!form.isCurrent() || busy || !nickname.trim()) return;
    const version = form.version();
    const value = nickname, id = editId;
    const age = store.getState().capabilities?.child_age_band ? ageBand : undefined;
    void dismissKeyboard().catch(() => undefined);
    const saved = await (id ? store.updateProfile(id, value, age) : store.createProfile(value, age));
    if (saved) form.complete(version, current => ({ ...current, nickname: '', ageBand: null, editId: null }));
  }
  async function saveName() {
    if (!form.isCurrent() || busy || !name.trim()) return;
    const version = form.version();
    const saved = await store.updateUser(name);
    if (saved) form.complete(version, current => ({ ...current, name: '' }));
  }
  function archive(id: string) { if (!form.isCurrent() || busy) return; if (id === state.selectedId) select(null); void store.archiveProfile(id); }
  const authLabel = ({ signed_out: '未登录', signing_in: '正在登录', signed_in: '已登录', expired: '登录已失效', offline: '登录服务离线', error: '登录未完成' })[state.auth.status];
  return <SectionCard title="云端账号与私有家庭档案" eyebrow="仅当前账号可见 · 音视频仍在本机">
    <View className="sc-cloud-heading"><StatusPill id="cloud-auth-status" tone={signedIn ? 'good' : 'quiet'}>{state.enabled ? authLabel : '云端尚未配置'}</StatusPill><Text className="sc-body-muted">账号显示名称和儿童档案属于私有家庭工具，不会自动变成社区作者资料。</Text></View>
    {!state.enabled ? <EmptyState title="本地陪伴可以继续" detail="此构建未连接云端账号服务。摄像头与麦克风仍需主动开启，媒体仍留在本机。" /> : !signedIn ? <View className="sc-cloud-form">
      {cloudSourcePlatform === 'web' && <><Text className="sc-setting-name">用户名</Text><Input id="cloud-username" className="sc-cloud-input" {...textInputKeyboardProps} ariaLabel="云端用户名" value={username} maxlength={128} disabled={busy} onInput={event => form.update(current => ({ ...current, username: event.detail.value }))} /><Text className="sc-setting-name">密码</Text><Input id="cloud-password" className="sc-cloud-input" {...textInputKeyboardProps} ariaLabel="云端密码" password value={password} maxlength={256} disabled={busy} onInput={event => form.update(current => ({ ...current, password: event.detail.value }))} /></>}
      <AccessibleButton id="cloud-sign-in" className="sc-small-button" disabled={busy} onClick={signIn}>{cloudSourcePlatform === 'wechat' ? '使用微信账号登录' : '登录云端账号'}</AccessibleButton><Text className="sc-body-muted">登录信息仅用于官方认证；刷新页面后需要重新登录。</Text>
    </View> : <View>
      <View className="sc-cloud-heading"><Text id="cloud-display-name" className="sc-setting-name">{state.user?.display_name || '我的陪伴账号'}</Text><AccessibleButton id="cloud-refresh" className="sc-small-button" disabled={busy} onClick={() => { if (form.isCurrent()) void store.refresh(); }}>刷新云端资料</AccessibleButton><AccessibleButton id="cloud-sign-out" className="sc-small-button" onClick={logout}>退出登录</AccessibleButton></View>
      <View className="sc-cloud-form"><Input id="cloud-display-name-input" className="sc-cloud-input" {...textInputKeyboardProps} ariaLabel="私有账号显示名称" placeholder="修改私有账号显示名称" value={name} maxlength={64} disabled={busy} onInput={event => form.update(current => ({ ...current, name: event.detail.value }))} /><AccessibleButton id="cloud-save-name" className="sc-small-button" disabled={busy || !name.trim()} onClick={() => void saveName()}>保存私有显示名称</AccessibleButton></View>
      <Text className="sc-setting-name">私有儿童档案 · 请主动选择</Text>
      {!state.profiles.length && state.status === 'ready' && <View id="cloud-profile-empty"><EmptyState title="还没有陪伴档案" detail="只需一个昵称。创建后请主动选择档案，再开始记录云端会话。" /></View>}
      <View id="cloud-profile-list" className="sc-cloud-profiles">{state.profiles.map((profile, index) => <View key={profile.id} className="sc-cloud-profile"><AccessibleButton id={`cloud-profile-select-${index}`} className="sc-small-button" aria-pressed={state.selectedId === profile.id} disabled={busy} onClick={() => select(profile.id)}>{profile.nickname}{state.selectedId === profile.id ? ' · 已选择' : ' · 选择'}</AccessibleButton><Text>{profile.age_band ? ageLabel(profile.age_band) : '年龄段未填写'}</Text><AccessibleButton id={`cloud-profile-edit-${index}`} className="sc-small-button" disabled={busy} onClick={() => { if (!busy) form.update(current => ({ ...current, editId: profile.id, nickname: profile.nickname, ageBand: profile.age_band })); }}>修改档案</AccessibleButton><AccessibleButton id={`cloud-profile-archive-${index}`} className="sc-small-button" disabled={busy} onClick={() => archive(profile.id)}>归档</AccessibleButton></View>)}</View>
      {state.selectedId && <AccessibleButton id="cloud-profile-clear" className="sc-small-button" disabled={busy} onClick={() => select(null)}>取消档案选择</AccessibleButton>}
      <View className="sc-cloud-form"><Input id="cloud-profile-nickname" className="sc-cloud-input" {...textInputKeyboardProps} ariaLabel="私有儿童档案昵称" placeholder="私有儿童档案昵称" value={nickname} maxlength={64} disabled={busy} onInput={event => form.update(current => ({ ...current, nickname: event.detail.value }))} /></View>
      <Text className="sc-setting-name">年龄段（选填，无需精确生日）</Text>
      <View id="cloud-profile-age-options" className="sc-cloud-form" role="group" ariaLabel="私有儿童档案年龄段">
        {[{ value: null, label: '暂不填写' }, ...AGE_BANDS].map(age => <AccessibleButton key={age.value ?? 'none'} id={`cloud-profile-age-${age.value ?? 'none'}`} className="sc-small-button" aria-pressed={ageBand === age.value} disabled={busy || !state.capabilities?.child_age_band} onClick={() => { if (!busy && store.getState().capabilities?.child_age_band) form.update(current => ({ ...current, ageBand: age.value })); }}>{age.label}</AccessibleButton>)}
      </View>
      {!state.capabilities?.child_age_band && <Text id="cloud-age-unavailable" className="sc-body-muted">当前云端尚未确认年龄段功能可用；原有昵称档案仍可创建和修改。</Text>}
      <Text className="sc-body-muted">年龄段仅用于私有家庭档案，不会设置社区浏览条件或自动带入投稿。</Text>
      <View className="sc-cloud-form"><AccessibleButton id="cloud-profile-save" className="sc-small-button" disabled={busy || !nickname.trim()} onClick={() => void saveProfile()}>{editId ? '保存私有档案' : '创建档案'}</AccessibleButton>{editId && <AccessibleButton className="sc-small-button" disabled={busy} onClick={() => form.update(current => ({ ...current, editId: null, nickname: '', ageBand: null }))}>取消修改</AccessibleButton>}</View>
      <Text className="sc-setting-footnote">切换档案或退出登录会结束本地采集，并隐藏当前档案的云端资料。归档不自动删除会话记录。</Text>
    </View>}
    {(state.auth.message || state.message) && <View id="cloud-error" className="sc-inline-error" role="status"><Text>{state.auth.message || state.message}</Text></View>}
  </SectionCard>;
}
