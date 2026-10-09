import { useState } from 'react';
import { Input, Text, Textarea, View } from '@tarojs/components';
import { AccessibleButton as Button } from '../../components/AccessibleButton';
import { AppShell, PageHeader } from '../../components/AppShell';
import { withClientErrorBoundary } from '../../components/ClientErrorBoundary';
import { ChoiceGroup, PostTags } from '../../community/components';
import { AGE_BANDS, TOPICS, TITLE_LIMIT, BODY_LIMIT } from '../../community/constants';
import { readDraft, saveDraft } from '../../community/memory';
import { countCharacters, validatePostDraft } from '../../community/model';
import type { CommunityDraftErrors, CommunityDraftInput, ValidCommunityDraft } from '../../community/types';
import { backToCommunity } from '../../navigation';

function CommunityComposePage() {
  const [draft, setDraft] = useState(readDraft);
  const [preview, setPreview] = useState<ValidCommunityDraft | null>(null);
  const [errors, setErrors] = useState<CommunityDraftErrors>({});
  const [navigationError, setNavigationError] = useState('');

  function update(field: keyof CommunityDraftInput, value: string) {
    setDraft(current => {
      const next = { ...current, [field]: value };
      saveDraft(next);
      return next;
    });
    setErrors(current => ({ ...current, [field]: undefined }));
  }
  function showPreview() {
    const result = validatePostDraft(draft);
    setErrors(result.errors);
    if (result.valid && result.data) setPreview(result.data);
  }
  function back() {
    setNavigationError('');
    void backToCommunity().catch(() => setNavigationError('暂时无法返回社区，请再试一次。'));
  }
  const errorMessages = Object.values(errors).filter(Boolean);

  return <AppShell page="community-compose">
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
      <Button id="pc-compose-edit" className="pc-action pc-action--primary" onClick={() => setPreview(null)}>返回编辑</Button>
    </View> : <View className="pc-compose-form">
      <View className="pc-form-field">
        <Text className="pc-field-label">标题</Text>
        <Input id="pc-title-input" className="pc-input" value={draft.title} maxlength={-1} placeholder="用一句话说说想分享什么" ariaLabel="投稿标题，最多 80 字" nativeProps={{ 'aria-label': '投稿标题，最多 80 字', 'aria-describedby': 'pc-title-hint', 'aria-invalid': Boolean(errors.title) }} onInput={event => update('title', event.detail.value)} />
        <Text id="pc-title-hint" className="pc-form-hint">{countCharacters(draft.title.trim())} / {TITLE_LIMIT} 字 · 按 Unicode 字符计数</Text>
        {errors.title && <Text className="pc-form-error">{errors.title}</Text>}
      </View>
      <View className="pc-form-field">
        <Text className="pc-field-label">正文</Text>
        <Textarea id="pc-body-input" className="pc-textarea" value={draft.body} maxlength={-1} placeholder="写一点你的经历和感受，暂时只供自己预览" ariaLabel="投稿正文，最多 2000 字" nativeProps={{ 'aria-label': '投稿正文，最多 2000 字', 'aria-describedby': 'pc-body-hint', 'aria-invalid': Boolean(errors.body) }} onInput={event => update('body', event.detail.value)} />
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

export default withClientErrorBoundary(CommunityComposePage);
