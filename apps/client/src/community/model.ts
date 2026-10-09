import { AGE_BANDS, TOPICS, TITLE_LIMIT, BODY_LIMIT } from './constants';
import type { CommunityAgeBand, CommunityTopic } from './constants';
import type { CommunityDraftErrors, CommunityDraftInput, CommunityFilters, CommunityPostPreview, ValidCommunityDraft } from './types';

export function filterCommunityPosts(posts: readonly CommunityPostPreview[], filters: CommunityFilters): CommunityPostPreview[] {
  return posts.filter(post => (filters.age === 'all' || post.age === filters.age)
    && (filters.topic === 'all' || post.topic === filters.topic))
    .sort((left, right) => Date.parse(right.publishedAt) - Date.parse(left.publishedAt));
}

export function findCommunityPost(posts: readonly CommunityPostPreview[], id: string | undefined): CommunityPostPreview | undefined {
  return posts.find(post => post.id === id);
}

export function countCharacters(value: string): number {
  return Array.from(value).length;
}

export function validatePostDraft(input: CommunityDraftInput): {
  valid: boolean; errors: CommunityDraftErrors; data?: ValidCommunityDraft;
} {
  const title = input.title.trim();
  const body = input.body.trim();
  const errors: CommunityDraftErrors = {};
  if (!title) errors.title = '请写一个标题。';
  else if (countCharacters(title) > TITLE_LIMIT) errors.title = `标题最多 ${TITLE_LIMIT} 字，请缩短一点。`;
  if (!body) errors.body = '请写一点正文内容。';
  else if (countCharacters(body) > BODY_LIMIT) errors.body = `正文最多 ${BODY_LIMIT} 字，请缩短一点。`;
  if (!AGE_BANDS.some(item => item.value === input.age)) errors.age = '请主动选择一个内容适用年龄段。';
  if (!TOPICS.some(item => item.value === input.topic)) errors.topic = '请选择一个话题。';
  if (Object.keys(errors).length) return { valid: false, errors };
  return { valid: true, errors, data: { title, body, age: input.age as CommunityAgeBand, topic: input.topic as CommunityTopic } };
}
