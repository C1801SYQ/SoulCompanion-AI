import { beforeEach, describe, expect, it } from 'vitest';
import { AGE_BANDS, AGE_FILTERS, TOPICS, TOPIC_FILTERS } from '../src/community/constants';
import { EXAMPLE_POSTS } from '../src/community/fixtures/posts';
import { filterCommunityPosts, findCommunityPost, validatePostDraft, countCharacters } from '../src/community/model';
import { readBrowseState, saveBrowseState, readDraft, saveDraft, resetCommunityMemory } from '../src/community/memory';

describe('public community examples', () => {
  it('defines the six age ranges and seven topics once with a separate all filter', () => {
    expect(AGE_BANDS.map(item => item.value)).toEqual(['0-2', '3-5', '6-8', '9-12', '13-15', '16-18']);
    expect(AGE_FILTERS[0].value).toBe('all');
    expect(TOPICS.map(item => item.label)).toEqual(['亲子沟通', '情绪陪伴', '习惯与生活', '入园入学', '学习与同伴', '青春期', '家长成长']);
    expect(TOPIC_FILTERS[0].value).toBe('all');
  });

  it.each(['0-2', '3-5', '6-8', '9-12', '13-15', '16-18'] as const)('filters age range %s', age => {
    const result = filterCommunityPosts(EXAMPLE_POSTS, { age, topic: 'all' });
    expect(result.length).toBeGreaterThan(0);
    expect(result.every(post => post.age === age)).toBe(true);
  });

  it.each(['parent-child', 'emotional-support', 'daily-habits', 'school-transition', 'learning-peers', 'adolescence', 'parent-growth'] as const)('filters topic %s', topic => {
    const result = filterCommunityPosts(EXAMPLE_POSTS, { age: 'all', topic });
    expect(result.length).toBeGreaterThan(0);
    expect(result.every(post => post.topic === topic)).toBe(true);
  });

  it('combines age and topic with AND, rather than broadening either filter', () => {
    const result = filterCommunityPosts(EXAMPLE_POSTS, { age: '6-8', topic: 'parent-child' });
    expect(result.length).toBeGreaterThan(0);
    expect(result.every(post => post.age === '6-8' && post.topic === 'parent-child')).toBe(true);
    expect(result.length).toBeLessThan(filterCommunityPosts(EXAMPLE_POSTS, { age: 'all', topic: 'parent-child' }).length);
  });

  it('returns a real empty result when both conditions have no match', () => {
    expect(filterCommunityPosts(EXAMPLE_POSTS, { age: '0-2', topic: 'adolescence' })).toEqual([]);
  });

  it('sorts newest first without mutating fixture order', () => {
    const original = EXAMPLE_POSTS.map(post => post.id);
    const result = filterCommunityPosts([...EXAMPLE_POSTS].reverse(), { age: 'all', topic: 'all' });
    expect(result.map(post => Date.parse(post.publishedAt))).toEqual(result.map(post => Date.parse(post.publishedAt)).sort((a, b) => b - a));
    expect(EXAMPLE_POSTS.map(post => post.id)).toEqual(original);
  });

  it('never substitutes a different post for an unknown or malicious ID', () => {
    expect(findCommunityPost(EXAMPLE_POSTS, 'missing')).toBeUndefined();
    expect(findCommunityPost(EXAMPLE_POSTS, '__proto__')).toBeUndefined();
    expect(findCommunityPost(EXAMPLE_POSTS, undefined)).toBeUndefined();
    expect(findCommunityPost(EXAMPLE_POSTS, EXAMPLE_POSTS[0].id)?.id).toBe(EXAMPLE_POSTS[0].id);
  });

  it('keeps every fixture and synthetic author explicitly labelled as an example', () => {
    expect(EXAMPLE_POSTS.length).toBeGreaterThanOrEqual(12);
    expect(new Set(EXAMPLE_POSTS.map(post => post.id)).size).toBe(EXAMPLE_POSTS.length);
    for (const post of EXAMPLE_POSTS) {
      expect(post.source).toBe('example');
      expect(post.author.source).toBe('example');
      expect(post.author.displayName).toBeTruthy();
      expect(post).not.toHaveProperty('likes');
      expect(post).not.toHaveProperty('childId');
      expect(post.author).not.toHaveProperty('uid');
    }
  });
});

describe('temporary text post preview', () => {
  const valid = { title: '  小小的交流尝试  ', body: '  今天先听完一句话。  ', age: '6-8', topic: 'parent-child' };

  it('trims valid text while retaining actively selected labels', () => {
    const result = validatePostDraft(valid);
    expect(result.valid).toBe(true);
    expect(result.data).toEqual({ title: '小小的交流尝试', body: '今天先听完一句话。', age: '6-8', topic: 'parent-child' });
    expect(result.errors).toEqual({});
  });

  it('requires text and both explicit selections', () => {
    const result = validatePostDraft({ title: '  ', body: '\n ', age: '', topic: '' });
    expect(result.valid).toBe(false);
    expect(Object.keys(result.errors)).toEqual(['title', 'body', 'age', 'topic']);
    expect(result.data).toBeUndefined();
  });

  it.each(['all', '__proto__', 'diagnosis', '18-21'])('rejects invalid age %s', age => {
    expect(validatePostDraft({ ...valid, age }).errors.age).toBeTruthy();
  });

  it.each(['all', '__proto__', 'medical-advice'])('rejects invalid topic %s', topic => {
    expect(validatePostDraft({ ...valid, topic }).errors.topic).toBeTruthy();
  });

  it('allows exactly the character limits and rejects the next Unicode character', () => {
    expect(countCharacters('😀予怀')).toBe(3);
    expect(validatePostDraft({ ...valid, title: '😀'.repeat(80), body: '😀'.repeat(2000) }).valid).toBe(true);
    expect(validatePostDraft({ ...valid, title: '😀'.repeat(81) }).errors.title).toBeTruthy();
    expect(validatePostDraft({ ...valid, body: '😀'.repeat(2001) }).errors.body).toBeTruthy();
  });

  it('retains potentially dangerous markup as text, rather than interpreting it', () => {
    const body = '<script>alert(1)</script> javascript:alert(1)';
    expect(validatePostDraft({ ...valid, body }).data?.body).toBe(body);
  });
});

describe('in-memory browsing and draft state', () => {
  beforeEach(resetCommunityMemory);

  it('restores filters and scroll after visiting a detail page', () => {
    saveBrowseState({ age: '6-8', topic: 'parent-child', scrollTop: 612 });
    expect(readBrowseState()).toEqual({ age: '6-8', topic: 'parent-child', scrollTop: 612 });
    const copy = readBrowseState();
    copy.scrollTop = 0;
    expect(readBrowseState().scrollTop).toBe(612);
  });

  it('keeps draft state independent from browsing and returns a copy', () => {
    saveDraft({ title: '临时草稿', body: '只在本次应用内。', age: '9-12', topic: 'parent-growth' });
    expect(readDraft().title).toBe('临时草稿');
    const copy = readDraft();
    copy.title = '别的内容';
    expect(readDraft().title).toBe('临时草稿');
    expect(readBrowseState().age).toBe('all');
  });

  it('starts empty and can clear temporary state without a storage adapter', () => {
    saveDraft({ title: '草稿', body: '内容', age: '0-2', topic: 'daily-habits' });
    saveBrowseState({ age: '0-2', topic: 'daily-habits', scrollTop: 45 });
    resetCommunityMemory();
    expect(readDraft()).toEqual({ title: '', body: '', age: '', topic: '' });
    expect(readBrowseState()).toEqual({ age: 'all', topic: 'all', scrollTop: 0 });
  });
});
