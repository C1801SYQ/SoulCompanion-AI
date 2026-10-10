import { validatePostDraft } from './model';
import type { CommunityDraftErrors, CommunityDraftInput, ValidCommunityDraft } from './types';

export interface CommunityEditorState {
  authEpoch: number;
  draft: CommunityDraftInput;
  preview: ValidCommunityDraft | null;
  errors: CommunityDraftErrors;
}
export function createEditorState(authEpoch: number, draft: CommunityDraftInput = { title: '', body: '', age: '', topic: '' }): CommunityEditorState {
  return { authEpoch, draft: { ...draft }, preview: null, errors: {} };
}
/** Cached Mini Program pages must never render a previous account's draft or preview. */
export function editorForEpoch(editor: CommunityEditorState, authEpoch: number): CommunityEditorState {
  return editor.authEpoch === authEpoch ? editor : createEditorState(authEpoch);
}
export function updateEditor(editor: CommunityEditorState, authEpoch: number, field: keyof CommunityDraftInput, value: string): CommunityEditorState {
  const current = editorForEpoch(editor, authEpoch);
  return { ...current, draft: { ...current.draft, [field]: value }, errors: { ...current.errors, [field]: undefined } };
}
export function previewEditor(editor: CommunityEditorState, authEpoch: number): CommunityEditorState {
  const current = editorForEpoch(editor, authEpoch);
  const result = validatePostDraft(current.draft);
  return { ...current, errors: result.errors, preview: result.valid && result.data ? result.data : null };
}
