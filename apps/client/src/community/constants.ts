/** Content suitability labels, never a health, ability or diagnosis classification. */
export const AGE_BANDS = [
  { value: '0-2', label: '0～2 岁' },
  { value: '3-5', label: '3～5 岁' },
  { value: '6-8', label: '6～8 岁' },
  { value: '9-12', label: '9～12 岁' },
  { value: '13-15', label: '13～15 岁' },
  { value: '16-18', label: '16～18 岁' },
] as const;

export const TOPICS = [
  { value: 'parent-child', label: '亲子沟通' },
  { value: 'emotional-support', label: '情绪陪伴' },
  { value: 'daily-habits', label: '习惯与生活' },
  { value: 'school-transition', label: '入园入学' },
  { value: 'learning-peers', label: '学习与同伴' },
  { value: 'adolescence', label: '青春期' },
  { value: 'parent-growth', label: '家长成长' },
] as const;

export type CommunityAgeBand = typeof AGE_BANDS[number]['value'];
export type CommunityTopic = typeof TOPICS[number]['value'];
export type CommunityAgeFilter = CommunityAgeBand | 'all';
export type CommunityTopicFilter = CommunityTopic | 'all';

export const AGE_FILTERS = [{ value: 'all', label: '全部' }, ...AGE_BANDS] as const;
export const TOPIC_FILTERS = [{ value: 'all', label: '全部' }, ...TOPICS] as const;
export const TITLE_LIMIT = 80;
export const BODY_LIMIT = 2000;

export function ageLabel(value: CommunityAgeBand): string {
  return AGE_BANDS.find(item => item.value === value)?.label ?? '年龄段未选择';
}

export function topicLabel(value: CommunityTopic): string {
  return TOPICS.find(item => item.value === value)?.label ?? '话题未选择';
}
