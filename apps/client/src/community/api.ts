import { CommunityTransport } from './transport';
import { CommunityError } from './apiTypes';
import type { CommunityApi, ContentKind, PageQuery, OwnedContent } from './apiTypes';
import type { CommunityFilters } from './types';
import * as parse from './validation';

/** Prefix, target pluralization, query encoding and DTO projection live only here. */
export function createCommunityApi(transport: CommunityTransport): CommunityApi {
  const path = (value: string) => `/api/v2${value}`;
  const target = (kind: ContentKind) => `${parse.kind(kind)}s`;
  const query = (value: PageQuery = {}, extras: Record<string, string> = {}) => {
    const entries: [string, string][] = Object.entries(extras);
    if (value.limit !== undefined) { const limit = parse.revision(value.limit); if (limit > 50) throw new CommunityError('invalid'); entries.push(['limit', String(limit)]); }
    if (value.cursor !== undefined && value.cursor !== null) entries.push(['cursor', parse.cursor(value.cursor)!]);
    return entries.length ? `?${entries.map(([key, v]) => `${key}=${encodeURIComponent(v)}`).join('&')}` : '';
  };
  const filters = (value: CommunityFilters) => {
    const extras: Record<string, string> = {};
    if (value.age !== 'all') extras.age_band = parse.age(value.age);
    if (value.topic !== 'all') extras.topic = parse.topic(value.topic);
    return extras;
  };
  const id = parse.communityId;
  const sameId = <T extends { id: string }>(identifier: string, parser: (value: unknown) => T) => (value: unknown): T => {
    const result = parser(value); if (result.id !== identifier) throw new Error('Invalid community target'); return result;
  };
  return {
    listPosts: (f, q) => transport.request('GET', path(`/community/posts${query(q, filters(f))}`), value => {
      const result = parse.page(parse.publicPost)(value);
      for (let index = 0; index < result.items.length; index++) {
        const current = result.items[index], previous = result.items[index - 1];
        if (f.age !== 'all' && current.age_band !== f.age || f.topic !== 'all' && current.topic !== f.topic
          || previous && (previous.published_at < current.published_at || previous.published_at === current.published_at && previous.id < current.id)) throw new CommunityError('invalid');
      }
      return result;
    }),
    post: identifier => transport.request('GET', path(`/community/posts/${id(identifier)}`), sameId(identifier, parse.publicPost)),
    comments: (identifier, q) => transport.request('GET', path(`/community/posts/${id(identifier)}/comments${query(q)}`), parse.page(value => {
      const result = parse.publicComment(value); if (result.post_id !== identifier) throw new Error('Invalid comment parent'); return result;
    })),
    comment: identifier => transport.request('GET', path(`/community/comments/${id(identifier)}`), sameId(identifier, parse.publicComment)),
    createPost: (input, key) => transport.request('POST', path('/community/posts'), parse.ownedPost, { ...parse.postInput(input) }, parse.requestKey(key)),
    editPost: (identifier, input, expectedRevision) => transport.request('PATCH', path(`/community/posts/${id(identifier)}`), value => {
      const result = sameId(identifier, parse.ownedPost)(value);
      if (result.content_revision !== expectedRevision + 1 || result.status !== 'pending') throw new CommunityError('invalid');
      return result;
    }, { ...parse.postInput(input), expected_revision: parse.revision(expectedRevision) }),
    withdrawPost: (identifier, expectedRevision) => transport.request('DELETE', path(`/community/posts/${id(identifier)}?expected_revision=${parse.revision(expectedRevision)}`), () => undefined),
    createComment: (identifier, body, key) => transport.request('POST', path(`/community/posts/${id(identifier)}/comments`), value => {
      const result = parse.ownedComment(value); if (result.post_id !== identifier) throw new Error('Invalid comment parent'); return result;
    }, { body: parse.plainText(body, 1000, { multiline: true }) }, parse.requestKey(key)),
    withdrawComment: (identifier, expectedRevision) => transport.request('DELETE', path(`/community/comments/${id(identifier)}?expected_revision=${parse.revision(expectedRevision)}`), () => undefined),
    myPosts: q => transport.request('GET', path(`/me/community/posts${query(q)}`), parse.page(parse.ownedPost)),
    myComments: q => transport.request('GET', path(`/me/community/comments${query(q)}`), parse.page(parse.ownedComment)),
    myContent: (kind, identifier) => transport.request('GET', path(`/me/community/${target(kind)}/${id(identifier)}`), sameId<OwnedContent>(identifier, kind === 'post' ? parse.ownedPost : parse.ownedComment)),
    bookmarks: q => transport.request('GET', path(`/me/community/bookmarks${query(q)}`), parse.page(parse.publicPost)),
    relations: identifier => transport.request('GET', path(`/me/community/posts/${id(identifier)}/relations`), value => {
      const result = parse.relations(value); if (result.post_id !== identifier) throw new Error('Invalid relationship target'); return result;
    }),
    feedback: (kind, identifier) => transport.request('GET', path(`/me/community/${target(kind)}/${id(identifier)}/feedback`), value => {
      const result = parse.feedback(value); if (result.target_id !== identifier || result.target_type !== kind) throw new Error('Invalid feedback target'); return result;
    }),
    setLike: (identifier, active) => transport.request(parse.boolean(active) ? 'PUT' : 'DELETE', path(`/community/posts/${id(identifier)}/like`), value => {
      const result = parse.relationReceipt(value); if (result.post_id !== identifier || result.kind !== 'like' || result.active !== active) throw new Error('Invalid relation confirmation'); return result;
    }),
    setBookmark: (identifier, active) => transport.request(parse.boolean(active) ? 'PUT' : 'DELETE', path(`/community/posts/${id(identifier)}/bookmark`), value => {
      const result = parse.relationReceipt(value); if (result.post_id !== identifier || result.kind !== 'bookmark' || result.active !== active) throw new Error('Invalid relation confirmation'); return result;
    }),
    report: (input, key) => transport.request('POST', path('/community/content-reports'), value => {
      const result = parse.reportReceipt(value); if (result.target_id !== input.target_id || result.target_type !== input.target_type) throw new Error('Invalid report target'); return result;
    }, { ...parse.reportInput(input) }, parse.requestKey(key)),
    opsQueue: (status = 'pending', q) => transport.request('GET', path(`/ops/moderation${query(q, { status: parse.status(status) })}`), parse.page(parse.opsContent)),
    opsContent: (kind, identifier) => transport.request('GET', path(`/ops/moderation/${target(kind)}/${id(identifier)}`), value => {
      const result = parse.opsContent(value); if (result.id !== identifier || result.kind !== kind) throw new Error('Invalid moderation target'); return result;
    }),
    moderate: (kind, identifier, action, expectedRevision, reason, key) => transport.request('POST', path(`/ops/moderation/${target(kind)}/${id(identifier)}/${parse.moderationAction(action)}`), value => {
      const result = parse.contentAction(value); if (result.content.id !== identifier || result.content.kind !== kind || result.action !== action) throw new Error('Invalid moderation confirmation'); return result;
    }, { expected_revision: parse.revision(expectedRevision), reason: parse.plainText(reason, 200) }, parse.requestKey(key)),
    opsReports: (status = 'open', q) => transport.request('GET', path(`/ops/content-reports${query(q, { status: parse.reportStatus(status) })}`), parse.page(parse.opsReport)),
    resolveReport: (identifier, expectedRevision, decision, reason, key) => transport.request('POST', path(`/ops/content-reports/${id(identifier)}/resolve`), value => {
      const result = parse.reportAction(value); if (result.report.id !== identifier) throw new Error('Invalid report confirmation'); return result;
    }, { expected_revision: parse.revision(expectedRevision), decision: parse.choice(decision, ['resolved', 'dismissed']), reason: parse.plainText(reason, 200) }, parse.requestKey(key)),
  };
}
