import { useEffect } from 'react';
import { Text, Textarea, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../components/AccessibleButton';
import { EmptyState, SectionCard } from '../components/Primitives';
import { useCloud } from '../state/CloudProvider';
import { useCommunity } from '../state/CommunityProvider';
import { dismissKeyboard, textInputKeyboardProps } from '../platform/keyboard';
import { CommunityError, type ContentKind, type PublicComment, type PublicPost, type RelationState, type ReportReason } from './apiTypes';
import { ChoiceGroup } from './components';
import { CommunityAccountPanel, useCommunityIdentity } from './AccountPanel';
import { appendContentPage, useCommunityBusy, useCommunityViewState, VISIBLE_PAGE_LIMIT } from './viewState';
import { communityFailureText, confirmedPostText, isCancelled, isUncertainWrite, isUnavailable, publicTime } from './presentation';
import { plainText, reportInput } from './validation';
import { countCharacters } from './model';

const REPORT_CHOICES: readonly { value: ReportReason; label: string }[] = [
  { value: 'privacy', label: '隐私与可识别信息' }, { value: 'harassment', label: '骚扰或攻击' },
  { value: 'unsafe', label: '危险内容' }, { value: 'spam', label: '广告或垃圾内容' }, { value: 'other', label: '其他问题' },
];

export function ReportForm({ kind, id, onUnavailable }: { kind: ContentKind; id: string; onUnavailable: () => void }) {
  const { state: cloud } = useCloud();
  const { api, store } = useCommunity();
  const form = useCommunityViewState(`report:${kind}:${id}`, () => ({ open: false, reason: 'privacy' as ReportReason, detail: '', busy: false, message: '', sent: false, uncertain: false }));
  const busy = useCommunityBusy(`report:${kind}:${id}`);
  const scope = `report:${kind}:${id}`;
  async function submit() {
    if (!form.isCurrent() || !api || busy.current || cloud.auth.status !== 'signed_in' || form.values.sent) return;
    let input;
    try { input = reportInput({ target_type: kind, target_id: id, reason: form.values.reason, detail: form.values.detail }); }
    catch (error) { form.update(value => ({ ...value, message: communityFailureText(error) })); return; }
    busy.current = true;
    form.update(value => ({ ...value, busy: true, message: '' }));
    const version = form.version();
    try {
      const action = await store.action(scope, input);
      if (!form.isCurrent()) return;
      await store.run(api.report(action.input, action.key), { private: true, key: scope });
      if (!form.isCurrent()) return;
      store.clearAction(scope);
      form.complete(version, value => ({ ...value, busy: false, sent: true, uncertain: false, message: '举报已提交。' }));
    } catch (error) {
      if (!isCancelled(error)) form.complete(version, value => ({ ...value, busy: false, uncertain: isUncertainWrite(error), message: communityFailureText(error) }));
      if (form.isCurrent() && isUnavailable(error)) onUnavailable();
    } finally { busy.current = false; }
  }
  return <View className="pc-confirm-panel">
    {!form.values.open ? <Button id={`pc-report-${kind}-${id}`} className="pc-action" onClick={() => form.update(value => ({ ...value, open: true }))}>举报{kind === 'post' ? '帖子' : '评论'}</Button> : <>
      <Text className="sc-setting-name">帮助我们留意内容边界</Text>
      {cloud.auth.status !== 'signed_in' ? <CommunityAccountPanel compact /> : <>
        <ChoiceGroup label="举报原因" items={REPORT_CHOICES} selected={form.values.reason} disabled={form.values.busy || form.values.sent} idPrefix={`pc-report-reason-${kind}-${id}`} onChange={reason => form.update(value => ({ ...value, reason, message: '', uncertain: false }))} />
        <Textarea id={`pc-report-detail-${kind}-${id}`} className="pc-textarea" {...textInputKeyboardProps} value={form.values.detail} maxlength={-1} disabled={form.values.busy || form.values.sent} ariaLabel="举报补充说明，最多 500 字" placeholder="可补充具体问题；其他原因需要说明。避免复制儿童或他人的隐私。" onInput={event => form.update(value => ({ ...value, detail: event.detail.value, message: '', uncertain: false }))} />
        <Text className="pc-form-hint">{countCharacters(form.values.detail)} / 500 字。举报信息不公开给被举报者。</Text>
        {form.values.uncertain && <Text className="pc-form-hint">结果尚未确认。保持相同原因和说明再试，会使用原操作键；修改内容会开始新的操作。</Text>}
        <Button id={`pc-report-submit-${kind}-${id}`} className="pc-action" disabled={form.values.busy || form.values.sent} onClick={() => void submit()}>{form.values.busy ? '正在提交…' : form.values.uncertain ? '使用原操作安全重试' : '提交举报'}</Button>
      </>}
      {form.values.message && <View role="status" className="pc-mutation-status"><Text>{form.values.message}</Text></View>}
      <Button className="pc-action" disabled={form.values.busy} onClick={() => form.update(value => ({ ...value, open: false }))}>收起举报</Button>
    </>}
  </View>;
}

export function PostRelations({ post, onUnavailable }: { post: PublicPost; onUnavailable: () => void }) {
  const { state: cloud } = useCloud();
  const { api, store, state } = useCommunity();
  const form = useCommunityViewState(`relations:${post.id}`, () => ({ value: null as RelationState | null, status: 'idle' as 'idle' | 'loading' | 'ready' | 'error', busy: false, message: '' }));
  const busy = useCommunityBusy(`relations:${post.id}`);
  async function read() {
    if (!form.isCurrent() || !api || cloud.auth.status !== 'signed_in' || busy.current) return;
    form.update(value => ({ ...value, value: null, status: 'loading', message: '' }));
    const version = form.version();
    try {
      const value = await store.run(api.relations(post.id), { private: true, key: `relations-read:${post.id}` });
      form.complete(version, previous => ({ ...previous, value, status: 'ready' }));
    } catch (error) {
      if (!isCancelled(error)) form.complete(version, value => ({ ...value, value: null, status: 'error', message: communityFailureText(error) }));
      // A missing optional read route and a hidden post both return 404. Recheck public
      // visibility anonymously before clearing the parent's entire detail snapshot.
      if (form.isCurrent() && isUnavailable(error)) {
        try { await store.run(api.post(post.id), { key: `relations-parent:${post.id}` }); }
        catch (visibilityError) { if (form.isCurrent() && isUnavailable(visibilityError)) onUnavailable(); }
      }
    }
  }
  useEffect(() => { void read(); }, [post.id, state.authEpoch, cloud.auth.status]);
  async function set(kind: 'like' | 'bookmark') {
    if (!form.isCurrent() || !api || busy.current || !form.values.value || form.values.status !== 'ready' || cloud.auth.status !== 'signed_in') return;
    const current = form.values.value;
    const active = !(kind === 'like' ? current.liked : current.bookmarked);
    busy.current = true;
    form.update(value => ({ ...value, busy: true, message: '' }));
    const version = form.version();
    try {
      const receipt = await store.run(kind === 'like' ? api.setLike(post.id, active) : api.setBookmark(post.id, active), { private: true, key: `relations-write:${post.id}` });
      if (receipt.post_id !== post.id || receipt.kind !== kind || receipt.active !== active) throw new CommunityError('invalid');
      form.complete(version, value => ({ ...value, busy: false, value: { ...current, ...(kind === 'like' ? { liked: receipt.active } : { bookmarked: receipt.active }) }, message: `${kind === 'like' ? '点赞' : '收藏'}状态已由云端确认。` }));
    } catch (error) {
      if (!isCancelled(error)) form.complete(version, value => ({ ...value, busy: false, value: null, status: 'error', message: `${communityFailureText(error)} 请先重新读取当前互动状态，页面不会假设已保存。` }));
      if (form.isCurrent() && isUnavailable(error)) onUnavailable();
    } finally { busy.current = false; }
  }
  if (cloud.auth.status !== 'signed_in') return <View className="pc-interactions"><Text className="sc-body-muted">登录后可以点赞、收藏或举报。公开阅读不需要登录。</Text><CommunityAccountPanel compact /></View>;
  return <View className="pc-interactions">
    {form.values.status !== 'ready' ? <View role="status"><Text>{form.values.status === 'loading' ? '正在读取当前互动状态…' : '当前互动状态尚未确认。'}</Text><Button id="pc-relations-retry" className="pc-action" disabled={form.values.status === 'loading' || form.values.busy} onClick={() => void read()}>重新读取互动状态</Button></View> : <>
      <Button id="pc-post-like" className="pc-action" aria-pressed={form.values.value?.liked} disabled={form.values.busy} onClick={() => void set('like')}>{form.values.value?.liked ? '已点赞 · 取消' : '点赞'}</Button>
      <Button id="pc-post-bookmark" className="pc-action" aria-pressed={form.values.value?.bookmarked} disabled={form.values.busy} onClick={() => void set('bookmark')}>{form.values.value?.bookmarked ? '已收藏 · 取消' : '收藏'}</Button>
    </>}
    {form.values.message && <View id="pc-relations-message" role="status"><Text>{form.values.message}</Text></View>}
  </View>;
}

export function CommentPanel({ post, onUnavailable }: { post: PublicPost; onUnavailable: () => void }) {
  const { state: cloud } = useCloud();
  const { api, store, state } = useCommunity();
  const readForm = useCommunityViewState(`comments:${post.id}`, () => ({ items: [] as PublicComment[], cursor: null as string | null, status: 'idle' as 'idle' | 'loading' | 'ready' | 'error', message: '', truncated: false }));
  const writeForm = useCommunityViewState(`comment-draft:${post.id}`, () => ({ open: false, body: '', busy: false, message: '', uncertain: false }));
  const identity = useCommunityIdentity(writeForm.values.open);
  const writeBusy = useCommunityBusy(`comment-write:${post.id}`), readBusy = useCommunityBusy(`comment-read:${post.id}`);
  const actionScope = `comment:${post.id}`;
  async function load(more = false) {
    if (!readForm.isCurrent() || !api || readBusy.current || more && (!readForm.values.cursor || readForm.values.truncated)) return;
    readBusy.current = true;
    const previous = readForm.values;
    readForm.update(value => ({ ...value, status: 'loading', message: '', ...(!more ? { items: [], cursor: null, truncated: false } : {}) }));
    const version = readForm.version();
    try {
      const page = await store.run(api.comments(post.id, { limit: 20, cursor: more ? previous.cursor : null }), { key: `comments:${post.id}` });
      if (more && page.next_cursor === previous.cursor) throw new CommunityError('invalid');
      const items = appendContentPage(more ? previous.items : [], page.items);
      const truncated = items.length >= VISIBLE_PAGE_LIMIT && page.next_cursor !== null;
      readForm.complete(version, value => ({ ...value, items, cursor: truncated ? null : page.next_cursor, status: 'ready', truncated }));
    } catch (error) {
      if (!isCancelled(error)) readForm.complete(version, value => ({ ...value, items: [], cursor: null, status: 'error', message: communityFailureText(error) }));
      if (readForm.isCurrent() && isUnavailable(error)) onUnavailable();
    } finally { readBusy.current = false; }
  }
  useEffect(() => { void load(); }, [post.id, state.authEpoch]);
  async function submit() {
    if (!writeForm.isCurrent() || !api || writeBusy.current || cloud.auth.status !== 'signed_in') return;
    if (identity.status !== 'ready' || !identity.profile) { writeForm.update(value => ({ ...value, message: '请先确认并设置公开社区昵称。' })); return; }
    let body: string;
    try { body = plainText(writeForm.values.body, 1000, { multiline: true }); }
    catch (error) { writeForm.update(value => ({ ...value, message: communityFailureText(error) })); return; }
    writeBusy.current = true;
    writeForm.update(value => ({ ...value, busy: true, message: '' }));
    const version = writeForm.version();
    void dismissKeyboard().catch(() => undefined);
    try {
      const action = await store.action(actionScope, { body });
      if (!writeForm.isCurrent()) return;
      const result = await store.run(api.createComment(post.id, action.input.body, action.key), { private: true, key: actionScope });
      if (!writeForm.isCurrent()) return;
      store.clearAction(actionScope);
      writeForm.complete(version, value => ({ ...value, busy: false, body: '', uncertain: false, message: result.status === 'pending' ? '评论已提交审核，暂时不会公开展示。' : confirmedPostText(result.status).replace('投稿', '评论') }));
    } catch (error) {
      if (!isCancelled(error)) writeForm.complete(version, value => ({ ...value, busy: false, uncertain: isUncertainWrite(error), message: communityFailureText(error) }));
      if (writeForm.isCurrent() && isUnavailable(error)) onUnavailable();
    } finally { writeBusy.current = false; }
  }
  return <SectionCard title="评论与交流" eyebrow="一级评论 · 人工审核后公开">
    <Text className="sc-body-muted">只显示当前已审核评论。请不填写孩子姓名、学校、住址、联系方式或其他隐私。</Text>
    <Button id="pc-comments-refresh" className="pc-action" disabled={readForm.values.status === 'loading'} onClick={() => void load()}>刷新公开评论</Button>
    {readForm.values.status === 'loading' && <View role="status"><Text>正在读取评论…</Text></View>}
    {readForm.values.message && <View role="status"><Text>{readForm.values.message}</Text></View>}
    {readForm.values.status === 'ready' && readForm.values.items.length === 0 && <EmptyState title="还没有公开评论" detail="新的评论先进入待审核，不会直接出现在这里。" />}
    <View className="pc-comment-list">{readForm.values.items.map(comment => <View className="pc-comment-card" key={comment.id} data-comment-id={comment.id}><Text className="sc-setting-name">{comment.author.nickname}</Text><Text className="pc-plain-text">{comment.body}</Text><Text className="pc-form-hint">{publicTime(comment.published_at)}</Text><ReportForm kind="comment" id={comment.id} onUnavailable={() => { void load(); }} /></View>)}</View>
    {readForm.values.cursor && <Button id="pc-comments-more" className="pc-action" disabled={readForm.values.status === 'loading'} onClick={() => void load(true)}>加载更多评论</Button>}
    {readForm.values.truncated && <Text className="pc-form-hint">本次最多显示 200 条评论，请刷新继续。</Text>}
    {!writeForm.values.open ? <Button id="pc-comment-open" className="pc-action pc-action--primary" onClick={() => writeForm.update(value => ({ ...value, open: true }))}>写一条评论</Button> : <View className="pc-comment-form">
      <CommunityAccountPanel compact identity={identity} />
      {cloud.auth.status === 'signed_in' && <>
        <Textarea id="pc-comment-input" className="pc-textarea" {...textInputKeyboardProps} ariaLabel="评论正文，最多 1000 字" placeholder="写一点经历或感受，提交后先等待审核" maxlength={-1} value={writeForm.values.body} disabled={writeForm.values.busy} onInput={event => writeForm.update(value => ({ ...value, body: event.detail.value, message: '', uncertain: false }))} />
        <Text className="pc-form-hint">{countCharacters(writeForm.values.body)} / 1000 字 · 纯文本</Text>
        {writeForm.values.uncertain && <Text className="pc-form-hint">结果尚未确认。保持相同正文安全重试会使用原操作键；也可以到我的评论核对。</Text>}
        <Button id="pc-comment-submit" className="pc-action pc-action--primary" disabled={writeForm.values.busy || identity.status !== 'ready' || !identity.profile} onClick={() => void submit()}>{writeForm.values.busy ? '正在提交…' : writeForm.values.uncertain ? '使用原操作安全重试' : '提交评论审核'}</Button>
      </>}
      {writeForm.values.message && <View id="pc-comment-message" role="status" className="pc-mutation-status"><Text>{writeForm.values.message}</Text></View>}
    </View>}
  </SectionCard>;
}
