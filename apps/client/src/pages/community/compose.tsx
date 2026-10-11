import { useEffect, useState } from 'react';
import { useRouter } from '@tarojs/taro';
import { Input, Text, Textarea, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { ChoiceGroup, CommunityModeNote, ContentStatusLabel, PostTags } from '../../community/components';
import { AGE_BANDS, TOPICS, TITLE_LIMIT, BODY_LIMIT } from '../../community/constants';
import { readDraft, saveDraft } from '../../community/memory';
import { countCharacters } from '../../community/model';
import type { CommunityDraftInput } from '../../community/types';
import { createEditorState, editorForEpoch, previewEditor, updateEditor } from '../../community/editorState';
import { backToCommunity, openPage } from '../../navigation';
import { dismissKeyboard, textInputKeyboardProps } from '../../platform/keyboard';
import { useCloud } from '../../state/CloudProvider';
import { useCommunity } from '../../state/CommunityProvider';
import { CommunityAccountPanel, useCommunityIdentity } from '../../community/AccountPanel';
import { useCommunityBusy, useCommunityViewState } from '../../community/viewState';
import type { OwnedPost, PostInput } from '../../community/apiTypes';
import { CommunityError } from '../../community/apiTypes';
import { communityId, postInput } from '../../community/validation';
import { communityFailureText, confirmedPostText, isCancelled, isUncertainWrite } from '../../community/presentation';
import { validatePostDraft } from '../../community/model';

function DemoCommunityComposePage() {
  const { state, store } = useCloud();
  const authEpoch = state.auth.epoch;
  const [editor, setEditor] = useState(() => createEditorState(authEpoch, readDraft()));
  const { draft, preview, errors } = editorForEpoch(editor, authEpoch);
  const [navigationError, setNavigationError] = useState('');
  useEffect(() => {
    setEditor(current => editorForEpoch(current, authEpoch));
    setNavigationError('');
  }, [authEpoch]);

  function update(field: keyof CommunityDraftInput, value: string) {
    if (store.getState().auth.epoch !== authEpoch) return;
    setEditor(current => {
      if (store.getState().auth.epoch !== authEpoch) return current;
      const next = updateEditor(current, authEpoch, field, value);
      saveDraft(next.draft);
      return next;
    });
  }
  function showPreview() {
    if (store.getState().auth.epoch !== authEpoch) return;
    setEditor(current => store.getState().auth.epoch === authEpoch ? previewEditor(current, authEpoch) : current);
    void dismissKeyboard().catch(() => {
      if (store.getState().auth.epoch === authEpoch) setNavigationError('键盘暂时无法收起，仍可继续编辑或查看预览。');
    });
  }
  function back() {
    setNavigationError('');
    void backToCommunity().catch(() => setNavigationError('暂时无法返回社区，请再试一次。'));
  }
  const errorMessages = Object.values(errors).filter(Boolean);

  return <AppShell page="community-compose">
    <CommunityModeNote mode="demo" />
    <PageHeader eyebrow="予怀 · 文字投稿预览" title={preview ? '先看看，这段文字的样子。' : '留下一段想分享的日常。'} description="只体验编辑与本地预览。浏览、写作和预览都不需要儿童档案。" action={<Button id="pc-compose-back" className="pc-action" onClick={back}>← 返回社区</Button>} />
    <View className="pc-preview-note" role="note"><Text className="pc-preview-note-title">功能预览：目前不会发布到社区</Text><Text>没有云端发布、保存或后台审核。临时草稿只在当前应用内存中，刷新或重新启动后清空。</Text></View>
    <View className="pc-compose-privacy" role="note"><Text>请用自己的话分享感受，不填写孩子姓名、学校、住址、病史或他人的隐私。年龄标签由你主动选择，不会从私有儿童档案复制信息。</Text></View>
    {preview ? <View id="pc-draft-preview" className="pc-draft-preview">
      <Text className="pc-example-label">产品预览 · 未发布</Text>
      <View className="pc-draft-title" role="heading" aria-level="2"><Text>{preview.title}</Text></View>
      <View className="pc-post-meta"><Text>预览家长 · 合成展示名</Text><Text>仅当前应用内存</Text></View>
      <PostTags post={preview} />
      <Text className="pc-plain-text">{preview.body}</Text>
      <Text className="pc-form-hint">这份预览不会进入帖子列表，也不会生成真实审核状态。</Text>
      <Button id="pc-compose-edit" className="pc-action pc-action--primary" onClick={() => setEditor(current => ({ ...editorForEpoch(current, authEpoch), preview: null }))}>返回编辑</Button>
    </View> : <View className="pc-compose-form">
      <View className="pc-form-field">
        <Text className="pc-field-label">标题</Text>
        <Input id="pc-title-input" className="pc-input" {...textInputKeyboardProps} value={draft.title} maxlength={-1} placeholder="用一句话说说想分享什么" ariaLabel="投稿标题，最多 80 字" nativeProps={{ 'aria-label': '投稿标题，最多 80 字', 'aria-describedby': 'pc-title-hint', 'aria-invalid': Boolean(errors.title) }} onInput={event => update('title', event.detail.value)} />
        <Text id="pc-title-hint" className="pc-form-hint">{countCharacters(draft.title.trim())} / {TITLE_LIMIT} 字 · 按 Unicode 字符计数</Text>
        {errors.title && <Text className="pc-form-error">{errors.title}</Text>}
      </View>
      <View className="pc-form-field">
        <Text className="pc-field-label">正文</Text>
        <Textarea id="pc-body-input" className="pc-textarea" {...textInputKeyboardProps} value={draft.body} maxlength={-1} placeholder="写一点你的经历和感受，暂时只供自己预览" ariaLabel="投稿正文，最多 2000 字" nativeProps={{ 'aria-label': '投稿正文，最多 2000 字', 'aria-describedby': 'pc-body-hint', 'aria-invalid': Boolean(errors.body) }} onInput={event => update('body', event.detail.value)} />
        <Text id="pc-body-hint" className="pc-form-hint">{countCharacters(draft.body.trim())} / {BODY_LIMIT} 字 · 纯文本展示</Text>
        {errors.body && <Text className="pc-form-error">{errors.body}</Text>}
      </View>
      <ChoiceGroup label="内容适用年龄（请主动选择）" items={AGE_BANDS} selected={draft.age} onChange={age => update('age', age)} idPrefix="pc-compose-age" />
      {errors.age && <Text className="pc-form-error">{errors.age}</Text>}
      <ChoiceGroup label="交流话题（请选择）" items={TOPICS} selected={draft.topic} onChange={topic => update('topic', topic)} idPrefix="pc-compose-topic" />
      {errors.topic && <Text className="pc-form-error">{errors.topic}</Text>}
      {errorMessages.length > 0 && <View id="pc-compose-error" className="pc-form-error pc-form-error-summary" role="alert"><Text>还需要补充或调整：{errorMessages.join(' ')}</Text></View>}
      <View className="pc-compose-actions"><Button id="pc-compose-preview" className="pc-action pc-action--primary" onClick={showPreview}>查看本地预览</Button><Text className="pc-form-hint">不会发布，不会写入云端</Text></View>
    </View>}
    {navigationError && <View className="sc-inline-error" role="status"><Text>{navigationError}</Text></View>}
  </AppShell>;
}

export function RealCommunityComposePage() {
  const { state: cloud } = useCloud();
  const { state, api, store } = useCommunity();
  const editId = useRouter().params.id;
  const identity = useCommunityIdentity();
  const signedIn = cloud.auth.status === 'signed_in';
  const form = useCommunityViewState(`compose:${editId ?? 'new'}`, () => ({
    draft: { title: '', body: '', age: '', topic: '' } as CommunityDraftInput,
    preview: null as PostInput | null, errors: {} as ReturnType<typeof validatePostDraft>['errors'],
    current: null as OwnedPost | null, sent: null as OwnedPost | null,
    busy: false, loading: Boolean(editId), message: '', uncertain: false,
  }));
  const busy = useCommunityBusy(`compose:${editId ?? 'new'}`);
  const actionScope = `compose:${editId ?? 'new'}`;
  const [navigationError, setNavigationError] = useState('');
  async function loadOwned() {
    if (!editId || !form.isCurrent() || !api || !signedIn) return;
    let id: string;
    try { id = communityId(editId); } catch { form.update(value => ({ ...value, loading: false, message: '编辑链接不完整，请从我的投稿重新进入。' })); return; }
    form.update(value => ({ ...value, current: null, loading: true, message: '', preview: null }));
    const version = form.version();
    try {
      const content = await store.run(api.myContent('post', id), { private: true, key: `compose-read:${id}` });
      if (!('title' in content)) throw new CommunityError('invalid');
      form.complete(version, value => ({ ...value, current: content, loading: false, uncertain: false, draft: { title: content.title, body: content.body, age: content.age_band, topic: content.topic } }));
    } catch (error) { if (!isCancelled(error)) form.complete(version, value => ({ ...value, loading: false, message: communityFailureText(error) })); }
  }
  useEffect(() => { void loadOwned(); }, [editId, state.authEpoch, signedIn]);
  function change(field: keyof CommunityDraftInput, value: string) {
    if (!form.isCurrent() || busy.current || form.values.loading) return;
    form.update(current => ({ ...current, draft: { ...current.draft, [field]: value }, preview: null, sent: null, errors: { ...current.errors, [field]: undefined },
      message: current.uncertain ? '上次操作结果尚未确认。修改内容会成为新的投稿，请先到我的投稿核对，避免重复分享。' : '', uncertain: false }));
  }
  function preview() {
    if (!form.isCurrent() || busy.current || form.values.loading || !signedIn) return;
    const validated = validatePostDraft(form.values.draft);
    if (!validated.valid || !validated.data) { form.update(value => ({ ...value, errors: validated.errors, preview: null })); return; }
    try {
      const input = postInput({ title: validated.data.title, body: validated.data.body, age_band: validated.data.age, topic: validated.data.topic });
      form.update(value => ({ ...value, errors: {}, preview: input, message: '' }));
      void dismissKeyboard().catch(() => undefined);
    } catch (error) { form.update(value => ({ ...value, preview: null, message: communityFailureText(error) })); }
  }
  async function submit() {
    if (!form.isCurrent() || !api || busy.current || !signedIn || !form.values.preview || form.values.sent) return;
    if (identity.status !== 'ready' || !identity.profile) { form.update(value => ({ ...value, message: '请先确认并主动设置公开社区昵称。' })); return; }
    if (editId && (!form.values.current || form.values.current.status === 'deleted')) return;
    const input = form.values.preview, revision = form.values.current?.content_revision;
    busy.current = true;
    form.update(value => ({ ...value, busy: true, message: '' }));
    const version = form.version();
    try {
      let result: OwnedPost;
      if (editId && revision) result = await store.run(api.editPost(editId, input, revision), { private: true, key: actionScope });
      else {
        const action = await store.action(actionScope, input);
        if (!form.isCurrent()) return;
        result = await store.run(api.createPost(action.input, action.key), { private: true, key: actionScope });
      }
      if (!form.isCurrent()) return;
      store.clearAction(actionScope);
      form.complete(version, value => ({ ...value, busy: false, uncertain: false, sent: result, message: confirmedPostText(result.status) }));
      if (form.isCurrent()) void store.refreshFeed();
    } catch (error) {
      if (!isCancelled(error)) form.complete(version, value => ({ ...value, busy: false, uncertain: isUncertainWrite(error), message: communityFailureText(error) }));
    } finally { busy.current = false; }
  }
  async function checkEdit() {
    if (!editId || !form.isCurrent() || !api || busy.current || !form.values.preview || !form.values.current) return;
    const intended = form.values.preview, revision = form.values.current.content_revision;
    busy.current = true;
    form.update(value => ({ ...value, busy: true, message: '' }));
    const version = form.version();
    try {
      const result = await store.run(api.myContent('post', editId), { private: true, key: `compose-check:${editId}` });
      if (!('title' in result)) throw new CommunityError('invalid');
      const matches = result.content_revision === revision + 1 && result.title === intended.title && result.body === intended.body && result.age_band === intended.age_band && result.topic === intended.topic;
      form.complete(version, value => matches ? { ...value, busy: false, uncertain: false, sent: result, message: confirmedPostText(result.status) } : { ...value, busy: false, message: result.content_revision === revision ? '云端当前仍是原版本。可使用相同内容和原版本安全重试；读取结果不保证尚在途的请求一定失败。' : '当前云端版本与本次编辑不同。请重新读取并核对，不会自动覆盖其他设备的修改。' });
    } catch (error) { if (!isCancelled(error)) form.complete(version, value => ({ ...value, busy: false, message: communityFailureText(error) })); }
    finally { busy.current = false; }
  }
  function back() {
    setNavigationError('');
    void backToCommunity().catch(() => setNavigationError('暂时无法返回，请再试一次。'));
  }
  function openMine() { void openPage('/pages/community/mine').catch(() => setNavigationError('暂时无法打开我的投稿，请再试一次。')); }
  const { draft, preview: previewed, errors, loading, current, sent } = form.values;
  const disabled = form.values.busy || loading || !signedIn;
  const errorMessages = Object.values(errors).filter(Boolean);
  return <AppShell page="community-compose">
    <CommunityModeNote mode="real" />
    <PageHeader eyebrow={editId ? '予怀 · 编辑自己的投稿' : '予怀 · 文字投稿'} title={previewed ? '先看看，这段文字的样子。' : '留下一段想分享的日常。'} description="浏览无需儿童档案。投稿只使用你主动选择的公开昵称、年龄标签与话题。" action={<Button id="pc-compose-back" className="pc-action" onClick={back}>← 返回</Button>} />
    <View className="pc-compose-privacy" role="note"><Text>请不填写孩子姓名、学校、住址、病史、联系方式或他人的隐私。年龄由你主动选择，不会从私有儿童档案复制。投稿和评论均先进入人工审核。</Text></View>
    <CommunityAccountPanel identity={identity} />
    {loading && signedIn && <View role="status"><Text>正在读取本人投稿及当前版本…</Text></View>}
    {current && <View className="pc-content-status"><ContentStatusLabel status={current.status} /><Text>内容版本 {current.content_revision}。修改后重新进入待审核，旧公开正文立即撤下。</Text></View>}
    {sent ? <View id="pc-compose-submitted" className="pc-confirm-panel" role="status"><ContentStatusLabel status={sent.status} /><Text>{confirmedPostText(sent.status)}</Text><Button id="pc-compose-mine" className="pc-action" onClick={openMine}>查看我的投稿</Button></View> : current?.status === 'deleted' ? <Text>已撤回的投稿不能继续编辑，请从社区开始新的投稿。</Text> : previewed ? <View id="pc-draft-preview" className="pc-draft-preview">
      <Text className="pc-content-status">本地预览 · 尚未提交</Text>
      <View className="pc-draft-title" role="heading" aria-level="2"><Text>{previewed.title}</Text></View>
      <View className="pc-post-meta"><Text>{identity.profile?.nickname ?? '公开昵称尚未确认'}</Text><Text>预览本身不写入云端</Text></View>
      <PostTags post={{ age: previewed.age_band, topic: previewed.topic }} /><Text className="pc-plain-text">{previewed.body}</Text>
      <Text className="pc-form-hint">确认分享后点击提交审核，不会直接公开。</Text>
      {form.values.uncertain && <Text className="pc-form-hint">状态尚未确认。保持相同内容安全重试{editId ? '会携带原内容版本，不会盲目覆盖新版本' : '会使用原操作键，不会盲目新建投稿'}；也可以查看我的投稿核对。</Text>}
      <View className="pc-compose-actions"><Button id="pc-compose-submit" className="pc-action pc-action--primary" disabled={disabled || identity.status !== 'ready' || !identity.profile || Boolean(editId && !current)} onClick={() => void submit()}>{form.values.busy ? '正在提交…' : form.values.uncertain ? '使用原操作安全重试' : '提交审核'}</Button><Button id="pc-compose-edit" className="pc-action" disabled={form.values.busy} onClick={() => form.update(value => ({ ...value, preview: null }))}>返回编辑</Button></View>
      {editId && <Button id="pc-compose-check-edit" className="pc-action" disabled={form.values.busy} onClick={() => void checkEdit()}>核对本人当前版本</Button>}
      <Button className="pc-action" disabled={form.values.busy} onClick={openMine}>查看我的投稿</Button>
    </View> : <View className="pc-compose-form">
      <View className="pc-form-field"><Text className="pc-field-label">标题</Text><Input id="pc-title-input" className="pc-input" {...textInputKeyboardProps} value={draft.title} maxlength={-1} disabled={disabled} placeholder="用一句话说说想分享什么" ariaLabel="投稿标题，最多 80 字" onInput={event => change('title', event.detail.value)} /><Text className="pc-form-hint">{countCharacters(draft.title)} / {TITLE_LIMIT} 字</Text>{errors.title && <Text className="pc-form-error">{errors.title}</Text>}</View>
      <View className="pc-form-field"><Text className="pc-field-label">正文</Text><Textarea id="pc-body-input" className="pc-textarea" {...textInputKeyboardProps} value={draft.body} maxlength={-1} disabled={disabled} placeholder="写一点自己的经历和感受" ariaLabel="投稿正文，最多 2000 字" onInput={event => change('body', event.detail.value)} /><Text className="pc-form-hint">{countCharacters(draft.body)} / {BODY_LIMIT} 字 · 纯文本</Text>{errors.body && <Text className="pc-form-error">{errors.body}</Text>}</View>
      <ChoiceGroup label="内容适用年龄（请主动选择）" items={AGE_BANDS} selected={draft.age} disabled={disabled} onChange={age => change('age', age)} idPrefix="pc-compose-age" />
      <ChoiceGroup label="交流话题（请选择）" items={TOPICS} selected={draft.topic} disabled={disabled} onChange={topic => change('topic', topic)} idPrefix="pc-compose-topic" />
      {errorMessages.length > 0 && <View id="pc-compose-error" className="pc-form-error" role="alert"><Text>还需要补充或调整：{errorMessages.join(' ')}</Text></View>}
      <Button id="pc-compose-preview" className="pc-action pc-action--primary" disabled={disabled || Boolean(editId && !current)} onClick={preview}>查看本地预览</Button>
      {editId && !loading && <Button id="pc-compose-reload" className="pc-action" disabled={form.values.busy} onClick={() => void loadOwned()}>重新读取本人投稿（会替换当前编辑）</Button>}
    </View>}
    {form.values.message && <View id="pc-compose-message" className="pc-mutation-status" role="status"><Text>{form.values.message}</Text></View>}
    {navigationError && <View role="status"><Text>{navigationError}</Text></View>}
  </AppShell>;
}

function CommunityComposePage() {
  const { state } = useCommunity();
  return state.mode === 'demo' ? <DemoCommunityComposePage /> : <RealCommunityComposePage />;
}

export default withClientErrorBoundary(CommunityComposePage);
