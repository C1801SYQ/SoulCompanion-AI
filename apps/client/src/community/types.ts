import type { CommunityAgeBand, CommunityAgeFilter, CommunityTopic, CommunityTopicFilter } from './constants';

/** Public display DTO: deliberately excludes identity tokens and private family fields. */
export interface CommunityAuthorPreview {
  displayName: string;
  source: 'example';
}

export interface CommunityPostPreview {
  id: string;
  title: string;
  summary: string;
  body: string;
  author: CommunityAuthorPreview;
  publishedAt: string;
  age: CommunityAgeBand;
  topic: CommunityTopic;
  source: 'example';
}

export interface CommunityFilters {
  age: CommunityAgeFilter;
  topic: CommunityTopicFilter;
}

export interface CommunityBrowseState extends CommunityFilters {
  scrollTop: number;
}

/** Raw text from controls; validation is required before making a local preview. */
export interface CommunityDraftInput {
  title: string;
  body: string;
  age: string;
  topic: string;
}

export interface ValidCommunityDraft {
  title: string;
  body: string;
  age: CommunityAgeBand;
  topic: CommunityTopic;
}

export type CommunityDraftErrors = Partial<Record<keyof CommunityDraftInput, string>>;
