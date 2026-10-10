import { describe, expect, it } from 'vitest';
import { createScrollRestoreLifecycle } from '../src/community/scrollRestore';
import { createEditorState, editorForEpoch, previewEditor, updateEditor } from '../src/community/editorState';

describe('community queued scroll restoration', () => {
  it('restores only the current visible page-show frame', () => {
    const lifecycle = createScrollRestoreLifecycle();
    const firstShow = lifecycle.show();
    expect(lifecycle.isCurrent(firstShow)).toBe(true);
    lifecycle.hide();
    expect(lifecycle.isVisible()).toBe(false);
    expect(lifecycle.isCurrent(firstShow)).toBe(false);
    const secondShow = lifecycle.show();
    expect(lifecycle.isCurrent(firstShow)).toBe(false);
    expect(lifecycle.isCurrent(secondShow)).toBe(true);
  });

  it('revokes queued restoration on unmount, including any later show callback', () => {
    const lifecycle = createScrollRestoreLifecycle();
    const pendingFrame = lifecycle.show();
    lifecycle.dispose();
    expect(lifecycle.isCurrent(pendingFrame)).toBe(false);
    expect(lifecycle.isCurrent(lifecycle.show())).toBe(false);
    expect(lifecycle.isVisible()).toBe(false);
  });
});

describe('cached compose page identity boundary', () => {
  const draft = { title: '一点交流', body: '今天先听完一句话。', age: '6-8', topic: 'parent-child' };

  it('retains edits and previews within the same identity epoch', () => {
    const initial = createEditorState(1, draft);
    const edited = updateEditor(initial, 1, 'title', '一起聊聊');
    const preview = previewEditor(edited, 1);
    expect(preview.preview?.title).toBe('一起聊聊');
    expect(preview.preview?.body).toBe(draft.body);
    expect(editorForEpoch(preview, 1)).toBe(preview);
    expect(initial.draft.title).toBe(draft.title);
  });

  it('immediately masks a cached draft, preview and validation errors on account change or expiration', () => {
    const previous = previewEditor(createEditorState(1, draft), 1);
    previous.errors = { title: '旧账号的校验信息' };
    expect(editorForEpoch(previous, 2)).toEqual(createEditorState(2));
    expect(previous.preview?.title).toBe(draft.title);
  });

  it('starts new-account edits from empty rather than copying old text or labels', () => {
    const previous = createEditorState(1, draft);
    const next = updateEditor(previous, 2, 'title', '新的临时草稿');
    expect(next.draft).toEqual({ title: '新的临时草稿', body: '', age: '', topic: '' });
    expect(next.preview).toBeNull();
  });

  it('cannot validate an old account preview under a new identity and still enforces required labels', () => {
    const previous = previewEditor(createEditorState(1, draft), 1);
    const next = previewEditor(previous, 2);
    expect(next.preview).toBeNull();
    expect(Object.keys(next.errors)).toEqual(['title', 'body', 'age', 'topic']);
  });
});
