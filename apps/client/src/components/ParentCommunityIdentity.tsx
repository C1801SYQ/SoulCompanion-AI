import { Input, Text, View } from '@tarojs/components';
import { AccessibleButton } from './AccessibleButton';
import { EmptyState, SectionCard } from './Primitives';
import { useCloud } from '../state/CloudProvider';
import { parentNickname } from '../cloud/validation';
import { dismissKeyboard, textInputKeyboardProps } from '../platform/keyboard';
import { useScopedForm } from '../cloud/formState';

const emptyParentDraft = () => ({ draft: '', message: '' });

/** Explicit Settings entry only. Neither account nor child names seed this public field. */
export function ParentCommunityIdentity() {
  const { state, store } = useCloud();
  const form = useScopedForm({ authEpoch: state.auth.epoch, selectedId: null }, () => ({ authEpoch: store.getState().auth.epoch, selectedId: null }), emptyParentDraft);
  const { draft, message } = form.values;
  const signedIn = state.auth.status === 'signed_in';
  const available = signedIn && Boolean(state.capabilities?.parent_profile) && state.parentProfileStatus === 'ready';
  const busy = state.status === 'loading';
  let valid = false;
  try { parentNickname(draft); valid = true; } catch { /* Invalid drafts remain editable. */ }
  async function save() {
    if (!form.isCurrent() || !available || !valid || busy || store.getState().parentProfileStatus !== 'ready') return;
    form.update(current => ({ ...current, message: '' }));
    const version = form.version();
    void dismissKeyboard().catch(() => undefined);
    const saved = await store.updateParentProfile(draft);
    form.complete(version, current => saved ? { draft: '', message: '社区昵称已由云端确认保存。社区帖子仍为示例，真实投稿尚未开放。' } : { ...current, message: '保存未确认，输入已保留，请检查连接后重试。' });
  }
  return <SectionCard title="公开社区昵称" eyebrow="自主选择 · 与私有家庭档案分开">
    <Text className="sc-body-muted">未来社区作者只使用你主动填写的公开昵称。不会自动读取微信头像或昵称，也不会公开账号标识、电话、邮箱或孩子信息。</Text>
    {!signedIn ? <EmptyState title="登录后可设置社区昵称" detail="浏览示例社区不需要登录，也不需要创建儿童档案。" /> : !available ?
      <View id="cloud-parent-load-status" role="status">
        <EmptyState title={state.parentProfileStatus === 'loading' ? '正在读取社区资料' : state.parentProfileStatus === 'error' ? '社区昵称读取尚未确认' : state.parentProfileStatus === 'idle' ? '社区资料尚未读取' : '社区昵称暂未开放保存'}
          detail={state.parentProfileStatus === 'loading' ? '读取完成前不能保存昵称，也不会把等待中的结果当作未设置。' : state.parentProfileStatus === 'error' ? '请重试读取，确认当前账号的社区资料后再修改昵称。' : state.parentProfileStatus === 'idle' ? '请主动读取当前账号的社区资料。' : '当前云端尚未确认独立社区资料功能可用。这里不会用本地示例冒充已保存资料。'} />
        {(state.parentProfileStatus === 'error' || state.parentProfileStatus === 'idle') && <AccessibleButton id="cloud-parent-retry" className="sc-small-button" disabled={busy} onClick={() => { if (form.isCurrent()) void store.refresh(); }}>重新读取社区资料</AccessibleButton>}
      </View> : <View>
        <Text id="cloud-parent-saved-name" className="sc-setting-name">{state.parentProfile ? `已保存昵称：${state.parentProfile.nickname}` : '尚未设置公开社区昵称'}</Text>
        <View className="sc-cloud-form"><Input id="cloud-parent-nickname" className="sc-cloud-input" {...textInputKeyboardProps} ariaLabel="公开社区昵称，2 到 24 字" placeholder="主动选择一个公开昵称" value={draft} maxlength={-1} disabled={busy} onInput={event => form.update(() => ({ draft: event.detail.value, message: '' }))} /><AccessibleButton id="cloud-parent-save" className="sc-small-button" disabled={busy || !valid} onClick={() => void save()}>保存社区昵称</AccessibleButton></View>
      </View>}
    <Text className="sc-setting-footnote">2～24 个字，允许文字、数字、普通空格、·、_、-；不接受链接、换行或表情。同名昵称可以存在，昵称不是登录凭据或唯一身份。</Text>
    {message && <View id="cloud-parent-save-status" className="sc-inline-error" role="status"><Text>{message}</Text></View>}
  </SectionCard>;
}
