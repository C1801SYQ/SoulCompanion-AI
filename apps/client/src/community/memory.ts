import type { CommunityBrowseState, CommunityDraftInput } from './types';

const emptyBrowse = (): CommunityBrowseState => ({ age: 'all', topic: 'all', scrollTop: 0 });
const emptyDraft = (): CommunityDraftInput => ({ title: '', body: '', age: '', topic: '' });
let browse = emptyBrowse();
let draft = emptyDraft();

/** Process memory only: no Taro storage, browser storage, private records or cloud access. */
export function readBrowseState(): CommunityBrowseState { return { ...browse }; }
export function saveBrowseState(value: CommunityBrowseState): void { browse = { ...value }; }
export function readDraft(): CommunityDraftInput { return { ...draft }; }
export function saveDraft(value: CommunityDraftInput): void { draft = { ...value }; }
export function resetCommunityMemory(): void { browse = emptyBrowse(); draft = emptyDraft(); }
