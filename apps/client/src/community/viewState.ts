import { useScopedForm } from '../cloud/formState';
import { useCommunity } from '../state/CommunityProvider';
import type { Feedback, OwnedContent } from './apiTypes';

export const VISIBLE_PAGE_LIMIT = 200;

/** A page's private inputs/results are synchronously masked on identity or mode change. */
export function useCommunityViewState<T>(pageKey: string, empty: () => T) {
  const { state, store } = useCommunity();
  return useScopedForm({ authEpoch: state.authEpoch, selectedId: `${state.mode}:${pageKey}` }, () => ({
    authEpoch: store.getState().authEpoch, selectedId: `${store.getState().mode}:${pageKey}`,
  }), empty);
}

/** An old request's finally block can only unlock its own account/page scope. */
export function useCommunityBusy(pageKey: string) {
  const { state } = useCommunity();
  const scope = `${state.mode}:${state.authEpoch}:${pageKey}`;
  const owner = useRef({ scope, lock: { current: false } });
  if (owner.current.scope !== scope) owner.current = { scope, lock: { current: false } };
  return owner.current.lock;
}

export function appendContentPage<T extends { id: string }>(old: readonly T[], incoming: readonly T[]): T[] {
  const items = new Map(old.map(item => [item.id, item]));
  for (const item of incoming) items.set(item.id, item);
  return [...items.values()].slice(0, VISIBLE_PAGE_LIMIT);
}

/** Never attach new-version moderation feedback to an older cached body. */
export function feedbackMatchesContent(feedback: Feedback, content: OwnedContent): boolean {
  return feedback.target_type === ('title' in content ? 'post' : 'comment') && feedback.target_id === content.id && feedback.content_revision === content.content_revision && feedback.status === content.status;
}
import { useRef } from 'react';
