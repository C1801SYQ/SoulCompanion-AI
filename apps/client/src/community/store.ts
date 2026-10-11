import Taro from '@tarojs/taro';
import type { AuthAdapter } from '../cloud/types';
import type { RequestHandle } from '../services/types';
import { CommunityError } from './apiTypes';
import type { CommunityApi, CommunityMode, PublicPost } from './apiTypes';
import type { CommunityFilters } from './types';
import * as validate from './validation';

export interface CommunityFeed {
  filters: CommunityFilters; items: PublicPost[]; nextCursor: string | null;
  status: 'idle' | 'loading' | 'ready' | 'error'; loadingMore: boolean; error: CommunityError | null; truncated: boolean;
}
export interface CommunityState { mode: CommunityMode; authEpoch: number; epoch: number; feed: CommunityFeed }
export interface CommunitySnapshot { epoch: number; authEpoch: number; subject: string | null }
export interface ActionSnapshot<T> { key: string; input: T; authEpoch: number }
interface Pending { handle: RequestHandle<unknown>; slot?: string; stamp: object }
interface ActionEntry { fingerprint: string; promise: Promise<ActionSnapshot<unknown>> }
const defaultFilters = (): CommunityFilters => ({ age: 'all', topic: 'all' });
const emptyFeed = (filters = defaultFilters()): CommunityFeed => ({ filters: { ...filters }, items: [], nextCursor: null, status: 'idle', loadingMore: false, error: null, truncated: false });
const MAX_FEED = 200;
const MAX_PENDING = 32;
const MAX_ACTIONS = 24;

/** Cryptographic random action identity works in H5 and native Taro, without storage. */
export async function createCommunityActionKey(): Promise<string> {
  let bytes: Uint8Array;
  if (typeof globalThis.crypto?.getRandomValues === 'function') bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  else {
    try {
      const result = await Taro.getRandomValues({ length: 16 });
      if (!(result.randomValues instanceof ArrayBuffer) || result.randomValues.byteLength !== 16) throw new CommunityError('invalid');
      bytes = new Uint8Array(result.randomValues);
    } catch { throw new CommunityError('invalid'); }
  }
  return `pc04-${Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')}`;
}
function freezeInput<T>(input: T): { input: T; fingerprint: string } {
  let encoded: string;
  try { encoded = JSON.stringify(input); } catch { throw new CommunityError('invalid'); }
  if (typeof encoded !== 'string' || validate.utf8Bytes(encoded) > 16384) throw new CommunityError('invalid');
  const copy = JSON.parse(encoded) as T;
  const freeze = (value: unknown): void => {
    if (value !== null && typeof value === 'object') {
      for (const child of Object.values(value)) freeze(child);
      Object.freeze(value);
    }
  };
  freeze(copy);
  return { input: copy, fingerprint: encoded };
}

/** Community identity and data never enable the private family provider's route scope. */
export class CommunityStore {
  private state: CommunityState;
  private listeners = new Set<() => void>();
  private pending = new Set<Pending>();
  private slots = new Map<string, object>();
  private actions = new Map<string, ActionEntry>();
  private unsubscribe: () => void;
  private disposed = false;
  private feedVersion = 0;
  constructor(readonly mode: CommunityMode, readonly api: CommunityApi | null, readonly auth: AuthAdapter | null,
    private readonly keyFactory: () => Promise<string> = createCommunityActionKey) {
    this.state = Object.freeze({ mode, authEpoch: auth?.getState().epoch ?? 0, epoch: 0, feed: emptyFeed() });
    this.unsubscribe = auth?.subscribeAuthState(() => {
      this.cancelAll();
      this.actions.clear();
      this.feedVersion++;
      // No retained owner/ops/relationship data; public list is revalidated on return.
      this.update({ authEpoch: auth.getState().epoch, epoch: this.state.epoch + 1, feed: emptyFeed(this.state.feed.filters) });
    }) ?? (() => undefined);
  }
  getState = (): CommunityState => this.state;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update(patch: Partial<CommunityState>): void {
    if (this.disposed) return;
    this.state = Object.freeze({ ...this.state, ...patch });
    for (const listener of this.listeners) listener();
  }
  private updateFeed(patch: Partial<CommunityFeed>): void { this.update({ feed: Object.freeze({ ...this.state.feed, ...patch }) }); }
  capture = (): CommunitySnapshot => ({ epoch: this.state.epoch, authEpoch: this.auth?.getState().epoch ?? 0, subject: this.auth?.getPrincipal()?.subject ?? null });
  isCurrent = (snapshot: CommunitySnapshot): boolean => !this.disposed && snapshot.epoch === this.state.epoch
    && snapshot.authEpoch === (this.auth?.getState().epoch ?? 0) && snapshot.subject === (this.auth?.getPrincipal()?.subject ?? null);
  private cancelAll(): void {
    for (const request of this.pending) request.handle.cancel();
    this.pending.clear(); this.slots.clear();
  }
  /** Each named request slot is latest-wins. Mutations should use unique, locked slots. */
  async run<T>(handle: RequestHandle<T>, options: { private?: boolean; key?: string } = {}): Promise<T> {
    if (this.disposed || this.mode !== 'real') { handle.cancel(); void handle.promise.catch(() => undefined); throw new CommunityError('cancelled'); }
    if (options.private && this.auth?.getState().status !== 'signed_in') { handle.cancel(); void handle.promise.catch(() => undefined); throw new CommunityError('unauthorized', 401); }
    if (this.pending.size >= MAX_PENDING) { handle.cancel(); void handle.promise.catch(() => undefined); throw new CommunityError('rate_limited'); }
    const snapshot = this.capture(), stamp = {};
    if (options.key) {
      if (options.key.length > 160) { handle.cancel(); void handle.promise.catch(() => undefined); throw new CommunityError('invalid'); }
      for (const previous of this.pending) if (previous.slot === options.key) previous.handle.cancel();
      this.slots.set(options.key, stamp);
    }
    const pending: Pending = { handle: handle as RequestHandle<unknown>, slot: options.key, stamp };
    this.pending.add(pending);
    const current = () => this.isCurrent(snapshot) && (!options.key || this.slots.get(options.key) === stamp);
    try {
      const result = await handle.promise;
      if (!current()) throw new CommunityError('cancelled');
      return result;
    } catch (error) {
      if (!current()) throw new CommunityError('cancelled');
      if (error instanceof CommunityError) throw error;
      const known = error as { kind?: string; status?: number } | null;
      if (known?.kind === 'unauthorized') throw new CommunityError('unauthorized', 401);
      if (known?.kind === 'offline') throw new CommunityError('offline');
      if (known?.kind === 'cancelled') throw new CommunityError('cancelled');
      throw new CommunityError('invalid', typeof known?.status === 'number' ? known.status : undefined);
    } finally {
      this.pending.delete(pending);
      if (options.key && this.slots.get(options.key) === stamp) this.slots.delete(options.key);
    }
  }
  /** Same immutable input retains a key after timeout/503; new input creates a new action. */
  async action<T>(scope: string, input: T): Promise<ActionSnapshot<T>> {
    if (this.disposed || this.mode !== 'real' || this.auth?.getState().status !== 'signed_in') throw new CommunityError('unauthorized', 401);
    if (!/^[A-Za-z0-9._:-]{1,160}$/.test(scope)) throw new CommunityError('invalid');
    const frozen = freezeInput(input), old = this.actions.get(scope);
    if (old?.fingerprint === frozen.fingerprint) return old.promise as Promise<ActionSnapshot<T>>;
    if (!old && this.actions.size >= MAX_ACTIONS) throw new CommunityError('rate_limited');
    const snapshot = this.capture();
    const entry: ActionEntry = { fingerprint: frozen.fingerprint, promise: Promise.resolve(undefined as unknown as ActionSnapshot<unknown>) };
    const promise = Promise.resolve().then(this.keyFactory).then(key => {
      if (!this.isCurrent(snapshot) || this.actions.get(scope) !== entry) throw new CommunityError('cancelled');
      return Object.freeze({ key: validate.requestKey(key), input: frozen.input, authEpoch: snapshot.authEpoch });
    }).catch(error => {
      if (this.actions.get(scope) === entry) this.actions.delete(scope);
      throw error instanceof CommunityError ? error : new CommunityError('invalid');
    });
    entry.promise = promise;
    this.actions.set(scope, entry);
    return promise;
  }
  clearAction(scope: string): void { this.actions.delete(scope); }
  async setFilters(filters: CommunityFilters): Promise<void> {
    if (filters.age !== 'all') validate.age(filters.age);
    if (filters.topic !== 'all') validate.topic(filters.topic);
    this.updateFeed({ filters: { ...filters } });
    await this.refreshFeed();
  }
  async refreshFeed(): Promise<void> {
    const version = ++this.feedVersion;
    const filters = { ...this.state.feed.filters };
    this.update({ feed: { ...emptyFeed(filters), status: this.mode === 'demo' ? 'ready' : 'loading' } });
    if (this.mode === 'demo') return;
    if (!this.api) { this.updateFeed({ status: 'error', error: new CommunityError('not_configured') }); return; }
    try {
      const result = await this.run(this.api.listPosts(filters, { limit: 20 }), { key: 'community-feed' });
      if (version !== this.feedVersion || this.disposed) return;
      this.updateFeed({ items: result.items, nextCursor: result.next_cursor, status: 'ready', error: null });
    } catch (error) {
      if (version !== this.feedVersion || this.disposed) return;
      if (error instanceof CommunityError && error.kind === 'cancelled') return;
      this.updateFeed({ status: 'error', error: error instanceof CommunityError ? error : new CommunityError('invalid') });
    }
  }
  async loadMore(): Promise<void> {
    const feed = this.state.feed;
    if (this.mode !== 'real' || !this.api || feed.status === 'loading' || feed.loadingMore || !feed.nextCursor || feed.truncated) return;
    const version = this.feedVersion, previousCursor = feed.nextCursor;
    this.updateFeed({ loadingMore: true, error: null });
    try {
      const result = await this.run(this.api.listPosts(feed.filters, { limit: 20, cursor: previousCursor }), { key: 'community-feed' });
      if (version !== this.feedVersion || this.disposed) return;
      if (result.next_cursor === previousCursor) throw new CommunityError('invalid');
      const items = [...this.state.feed.items], seen = new Set(items.map(item => item.id));
      for (const item of result.items) if (!seen.has(item.id)) { items.push(item); seen.add(item.id); }
      const truncated = items.length >= MAX_FEED && result.next_cursor !== null || items.length > MAX_FEED;
      this.updateFeed({ items: items.slice(0, MAX_FEED), nextCursor: truncated ? null : result.next_cursor, status: 'ready', loadingMore: false, error: null, truncated });
    } catch (error) {
      if (version !== this.feedVersion || this.disposed) return;
      this.updateFeed({ loadingMore: false, error: error instanceof CommunityError ? error : new CommunityError('invalid') });
    }
  }
  dispose(): void { this.cancelAll(); this.actions.clear(); this.unsubscribe(); this.disposed = true; this.listeners.clear(); }
}
