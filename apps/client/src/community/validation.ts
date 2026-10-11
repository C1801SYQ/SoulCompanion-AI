import { AGE_BANDS, TOPICS } from './constants';
import { parentNickname } from '../cloud/validation';
import type { CommunityAgeBand, CommunityTopic } from './constants';
import { CommunityError } from './apiTypes';
import type { AuditPreview, CommunityPage, ContentActionResult, ContentKind, ContentStatus, Feedback, OpsContent, OpsReport,
  OwnedComment, OwnedPost, PostInput, PublicAuthor, PublicComment, PublicPost, RelationReceipt, RelationState,
  ReportActionResult, ReportInput, ReportReceipt, ReportStatus, ModerationAction } from './apiTypes';

export const CONTENT_STATUSES = ['pending', 'published', 'rejected', 'hidden', 'deleted'] as const;
export const REPORT_REASONS = ['privacy', 'harassment', 'unsafe', 'spam', 'other'] as const;
export const REPORT_STATUSES = ['open', 'resolved', 'dismissed'] as const;
const invalid = (): never => { throw new CommunityError('invalid'); };
export function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
}
export function choice<T extends string>(value: unknown, allowed: readonly T[]): T { return allowed.includes(value as T) ? value as T : invalid(); }
export function revision(value: unknown): number { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1 ? value : invalid(); }
export function boolean(value: unknown): boolean { return typeof value === 'boolean' ? value : invalid(); }
export function communityId(value: unknown): string {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) ? value : invalid();
}
export function utf8Bytes(value: string): number {
  let result = 0;
  for (const char of value) {
    const code = char.codePointAt(0)!;
    if (code >= 0xd800 && code <= 0xdfff) invalid();
    result += code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4;
  }
  return result;
}
/** Mirrors PC03 plain_text before trimming; no dangerous text is silently removed. */
export function plainText(value: unknown, maximum: number, options: { multiline?: boolean; minimum?: number } = {}): string {
  if (typeof value !== 'string' || /\p{C}/u.test(options.multiline ? value.replace(/\n/g, '') : value)) invalid();
  const result = (value as string).normalize('NFC').trim();
  const length = Array.from(result).length;
  if (length < (options.minimum ?? 1) || length > maximum || utf8Bytes(result) > maximum * 4
    || /<\s*\/?\s*[A-Za-z]|javascript\s*:|data\s*:\s*(?:text\/html|application\/)/i.test(result)) invalid();
  return result;
}
export function timestamp(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(value)) invalid();
  const result = value as string;
  const parsed = Date.parse(result);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 23) !== result.slice(0, 23)) invalid();
  return result;
}
export function cursor(value: unknown): string | null { return value === null ? null : typeof value === 'string' && /^[A-Za-z0-9_-]{1,1024}$/.test(value) ? value : invalid(); }
export function requestKey(value: unknown): string { return typeof value === 'string' && /^[A-Za-z0-9._:-]{1,64}$/.test(value) ? value : invalid(); }
export function age(value: unknown): CommunityAgeBand { return choice(value, AGE_BANDS.map(item => item.value)); }
export function topic(value: unknown): CommunityTopic { return choice(value, TOPICS.map(item => item.value)); }
export function postInput(value: unknown): PostInput {
  const v = object(value);
  return { title: plainText(v.title, 80), body: plainText(v.body, 2000, { multiline: true }), age_band: age(v.age_band), topic: topic(v.topic) };
}
export function reportInput(value: unknown): ReportInput {
  const v = object(value), reason = choice(v.reason, REPORT_REASONS), detail = plainText(v.detail ?? '', 500, { multiline: true, minimum: reason === 'other' ? 1 : 0 });
  return { target_type: choice(v.target_type, ['post', 'comment']), target_id: communityId(v.target_id), reason, detail };
}
function author(value: unknown): PublicAuthor {
  const v = object(value);
  let nickname: string;
  try { nickname = parentNickname(typeof v.nickname === 'string' ? v.nickname : invalid()); } catch { return invalid(); }
  if (nickname !== v.nickname) invalid();
  return { id: communityId(v.id), nickname };
}
function common(value: unknown, owned: boolean) {
  const v = object(value), created_at = timestamp(v.created_at), updated_at = timestamp(v.updated_at);
  const published_at = owned && v.published_at === null ? null : timestamp(v.published_at);
  if (updated_at < created_at || published_at !== null && (published_at < created_at || published_at > updated_at)) invalid();
  return { id: communityId(v.id), author: author(v.author), created_at, updated_at, published_at };
}
function canonicalText(value: unknown, maximum: number, multiline = false, minimum = 1): string {
  const result = plainText(value, maximum, { multiline, minimum });
  return result === value ? result : invalid();
}
export function publicPost(value: unknown): PublicPost {
  const v = object(value), c = common(v, false);
  return { ...c, published_at: c.published_at!, title: canonicalText(v.title, 80), body: canonicalText(v.body, 2000, true), age_band: age(v.age_band), topic: topic(v.topic) };
}
export function publicComment(value: unknown): PublicComment {
  const v = object(value), c = common(v, false);
  return { ...c, published_at: c.published_at!, post_id: communityId(v.post_id), body: canonicalText(v.body, 1000, true) };
}
function ownedState(v: Record<string, unknown>, publishedAt: string | null) {
  const status = choice(v.status, CONTENT_STATUSES);
  if ((status === 'published') !== (publishedAt !== null)) invalid();
  return { status, content_revision: revision(v.content_revision) };
}
export function ownedPost(value: unknown): OwnedPost {
  const v = object(value), c = common(v, true);
  return { ...c, ...ownedState(v, c.published_at), title: canonicalText(v.title, 80), body: canonicalText(v.body, 2000, true), age_band: age(v.age_band), topic: topic(v.topic) };
}
export function ownedComment(value: unknown): OwnedComment {
  const v = object(value), c = common(v, true);
  return { ...c, ...ownedState(v, c.published_at), post_id: communityId(v.post_id), body: canonicalText(v.body, 1000, true) };
}
export function page<T>(parse: (value: unknown) => T): (value: unknown) => CommunityPage<T> {
  return value => {
    const v = object(value), limit = revision(v.limit);
    if (limit > 50 || !Array.isArray(v.items) || v.items.length > limit) invalid();
    const items = (v.items as unknown[]).map(parse);
    const ids = items.map(item => object(item).id);
    if (new Set(ids).size !== ids.length) invalid();
    return { items, limit, next_cursor: cursor(v.next_cursor) };
  };
}
export function relationReceipt(value: unknown): RelationReceipt { const v = object(value); return { post_id: communityId(v.post_id), kind: choice(v.kind, ['like', 'bookmark']), active: boolean(v.active) }; }
export function relations(value: unknown): RelationState { const v = object(value); return { post_id: communityId(v.post_id), liked: boolean(v.liked), bookmarked: boolean(v.bookmarked) }; }
export function feedback(value: unknown): Feedback {
  const v = object(value), content_revision = revision(v.content_revision), raw = v.feedback === null ? null : object(v.feedback);
  const review = raw === null ? null : { action: choice(raw.action, ['approve', 'reject', 'hide'] as const), reason: canonicalText(raw.reason, 200), at: timestamp(raw.at), content_revision: revision(raw.content_revision) };
  if (review && review.content_revision !== content_revision) invalid();
  return { target_type: choice(v.target_type, ['post', 'comment']), target_id: communityId(v.target_id), content_revision, status: choice(v.status, CONTENT_STATUSES), feedback: review };
}
export function reportReceipt(value: unknown): ReportReceipt {
  const v = object(value), status = choice(v.status, REPORT_STATUSES), handled_at = v.handled_at === null ? null : timestamp(v.handled_at), created_at = timestamp(v.created_at);
  if ((status === 'open') !== (handled_at === null) || handled_at !== null && handled_at < created_at) invalid();
  const reason = choice(v.reason, REPORT_REASONS), detail = canonicalText(v.detail, 500, true, reason === 'other' ? 1 : 0);
  return { id: communityId(v.id), target_type: choice(v.target_type, ['post', 'comment']), target_id: communityId(v.target_id), target_revision: revision(v.target_revision), reason, detail, status, created_at, handled_at };
}
function audit(value: unknown): AuditPreview[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 32) invalid();
  return (value as unknown[]).map(item => {
    const v = object(item);
    return { action: choice(v.action, ['create', 'edit', 'withdraw', 'approve', 'reject', 'hide', 'resolve'] as const), reason: canonicalText(v.reason, 200, false, 0), at: timestamp(v.at), target_revision: revision(v.target_revision) };
  });
}
export function opsContent(value: unknown): OpsContent {
  const v = object(value), kind = choice(v.kind, ['post', 'comment'] as const);
  return { ...(kind === 'post' ? ownedPost(v) : ownedComment(v)), kind, row_version: revision(v.row_version), audit: audit(v.audit) };
}
export function opsReport(value: unknown): OpsReport { const v = object(value); return { ...reportReceipt(v), report_revision: revision(v.report_revision), row_version: revision(v.row_version), audit: audit(v.audit) }; }
function actionReceipt(v: Record<string, unknown>) {
  const action_applied = boolean(v.action_applied), applied_revision = v.applied_revision === null ? null : revision(v.applied_revision), applied_at = v.applied_at === null ? null : timestamp(v.applied_at);
  if (action_applied !== (applied_revision !== null && applied_at !== null) || !action_applied && (applied_revision !== null || applied_at !== null)) invalid();
  return { action_applied, action: choice(v.action, ['approve', 'reject', 'hide', 'resolve'] as const), applied_revision, applied_at };
}
export function contentAction(value: unknown): ContentActionResult { const v = object(value), result = actionReceipt(v); if (result.action === 'resolve') invalid(); return { ...result, content: opsContent(v.content) }; }
export function reportAction(value: unknown): ReportActionResult { const v = object(value), result = actionReceipt(v); if (result.action !== 'resolve') invalid(); return { ...result, report: opsReport(v.report) }; }
export function kind(value: unknown): ContentKind { return choice(value, ['post', 'comment']); }
export function status(value: unknown): ContentStatus { return choice(value, CONTENT_STATUSES); }
export function reportStatus(value: unknown): ReportStatus { return choice(value, REPORT_STATUSES); }
export function moderationAction(value: unknown): ModerationAction { return choice(value, ['approve', 'reject', 'hide']); }
