import type { RequestHandle } from '../services/types';
import type { CommunityAgeBand, CommunityTopic } from './constants';
import type { CommunityFilters } from './types';

export type CommunityMode = 'real' | 'demo';
export type ContentKind = 'post' | 'comment';
export type ContentStatus = 'pending' | 'published' | 'rejected' | 'hidden' | 'deleted';
export type ReportReason = 'privacy' | 'harassment' | 'unsafe' | 'spam' | 'other';
export type ReportStatus = 'open' | 'resolved' | 'dismissed';
export type ModerationAction = 'approve' | 'reject' | 'hide';
export type CommunityFailure = 'unauthorized' | 'forbidden' | 'not_found' | 'conflict' | 'too_large' | 'invalid' | 'rate_limited' | 'server' | 'offline' | 'cancelled' | 'not_configured';

/** Never reflects server messages, request bodies, identity IDs or credentials. */
export class CommunityError extends Error {
  constructor(readonly kind: CommunityFailure, readonly status?: number, readonly serverCode?: string,
    readonly retryAfterMs?: number, readonly requestId?: string) {
    super(({ unauthorized: '请先登录，或重新登录后继续。', forbidden: '当前账号无权查看或操作这项内容。',
      not_found: '内容已不可查看。', conflict: '内容版本或操作状态已变化，请重新读取后检查。',
      too_large: '内容超过允许长度，请缩短后重试。', invalid: '内容或响应不符合规则，请检查后重试。',
      rate_limited: '操作较频繁，请稍后重试。', server: '服务暂时不可用，操作结果可能尚未确认。',
      offline: '连接暂时中断，操作结果尚未确认。', cancelled: '操作已取消。',
      not_configured: '此构建尚未配置真实社区服务。' })[kind]);
    this.name = 'CommunityError';
  }
}

export interface PublicAuthor { id: string; nickname: string }
export interface PublicPost {
  id: string; title: string; body: string; age_band: CommunityAgeBand; topic: CommunityTopic;
  author: PublicAuthor; created_at: string; updated_at: string; published_at: string;
}
export interface PublicComment {
  id: string; post_id: string; body: string; author: PublicAuthor;
  created_at: string; updated_at: string; published_at: string;
}
export interface OwnedPost extends Omit<PublicPost, 'published_at'> { published_at: string | null; status: ContentStatus; content_revision: number }
export interface OwnedComment extends Omit<PublicComment, 'published_at'> { published_at: string | null; status: ContentStatus; content_revision: number }
export type OwnedContent = OwnedPost | OwnedComment;
export interface CommunityPage<T> { items: T[]; limit: number; next_cursor: string | null }
export interface PageQuery { limit?: number; cursor?: string | null }
export interface PostInput { title: string; body: string; age_band: CommunityAgeBand; topic: CommunityTopic }
export interface ReportInput { target_type: ContentKind; target_id: string; reason: ReportReason; detail?: string }
export interface RelationReceipt { post_id: string; kind: 'like' | 'bookmark'; active: boolean }
export interface RelationState { post_id: string; liked: boolean; bookmarked: boolean }
export interface ReviewFeedback { action: ModerationAction; reason: string; at: string; content_revision: number }
export interface Feedback { target_type: ContentKind; target_id: string; content_revision: number; status: ContentStatus; feedback: ReviewFeedback | null }
export interface ReportReceipt {
  id: string; target_type: ContentKind; target_id: string; target_revision: number; reason: ReportReason;
  detail: string; status: ReportStatus; created_at: string; handled_at: string | null;
}
/** UI audit projection excludes the protected raw actor/hash/action ID fields. */
export interface AuditPreview { action: 'create' | 'edit' | 'withdraw' | ModerationAction | 'resolve'; reason: string; at: string; target_revision: number }
export type OpsContent = OwnedContent & { kind: ContentKind; row_version: number; audit: AuditPreview[] };
export interface OpsReport extends ReportReceipt { report_revision: number; row_version: number; audit: AuditPreview[] }
export interface ActionReceipt { action_applied: boolean; action: ModerationAction | 'resolve'; applied_revision: number | null; applied_at: string | null }
export interface ContentActionResult extends ActionReceipt { content: OpsContent }
export interface ReportActionResult extends ActionReceipt { report: OpsReport }

export interface CommunityApi {
  listPosts(filters: CommunityFilters, query?: PageQuery): RequestHandle<CommunityPage<PublicPost>>;
  post(id: string): RequestHandle<PublicPost>;
  comments(postId: string, query?: PageQuery): RequestHandle<CommunityPage<PublicComment>>;
  comment(id: string): RequestHandle<PublicComment>;
  createPost(input: PostInput, key: string): RequestHandle<OwnedPost>;
  editPost(id: string, input: PostInput, expectedRevision: number): RequestHandle<OwnedPost>;
  withdrawPost(id: string, expectedRevision: number): RequestHandle<void>;
  createComment(postId: string, body: string, key: string): RequestHandle<OwnedComment>;
  withdrawComment(id: string, expectedRevision: number): RequestHandle<void>;
  myPosts(query?: PageQuery): RequestHandle<CommunityPage<OwnedPost>>;
  myComments(query?: PageQuery): RequestHandle<CommunityPage<OwnedComment>>;
  myContent(kind: ContentKind, id: string): RequestHandle<OwnedContent>;
  bookmarks(query?: PageQuery): RequestHandle<CommunityPage<PublicPost>>;
  relations(id: string): RequestHandle<RelationState>;
  feedback(kind: ContentKind, id: string): RequestHandle<Feedback>;
  setLike(id: string, active: boolean): RequestHandle<RelationReceipt>;
  setBookmark(id: string, active: boolean): RequestHandle<RelationReceipt>;
  report(input: ReportInput, key: string): RequestHandle<ReportReceipt>;
  opsQueue(status?: ContentStatus, query?: PageQuery): RequestHandle<CommunityPage<OpsContent>>;
  opsContent(kind: ContentKind, id: string): RequestHandle<OpsContent>;
  moderate(kind: ContentKind, id: string, action: ModerationAction, expectedRevision: number, reason: string, key: string): RequestHandle<ContentActionResult>;
  opsReports(status?: ReportStatus, query?: PageQuery): RequestHandle<CommunityPage<OpsReport>>;
  resolveReport(id: string, expectedRevision: number, decision: 'resolved' | 'dismissed', reason: string, key: string): RequestHandle<ReportActionResult>;
}
