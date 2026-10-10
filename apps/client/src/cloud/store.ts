import type { RequestHandle } from '../services/types';
import { CloudError, type AuthAdapter, type AuthState, type ChildAgeBand, type ChildProfile, type CloudApi, type CloudCapabilities, type ParentCommunityProfile, type CloudEmotion, type CloudReport, type CloudSession, type CloudUser } from './types';

export interface CloudState {
  enabled: boolean; auth: AuthState; epoch: number; status: 'not_configured' | 'idle' | 'loading' | 'ready' | 'offline' | 'error';
  message: string; user: CloudUser | null; profiles: ChildProfile[]; selectedId: string | null;
  sessions: CloudSession[]; emotions: CloudEmotion[]; reports: CloudReport[];
  capabilities: CloudCapabilities | null; parentProfile: ParentCommunityProfile | null;
  parentProfileStatus: 'idle' | 'loading' | 'ready' | 'error' | 'unavailable';
}
const emptyFamily = { capabilities: null, parentProfile: null, parentProfileStatus: 'idle' as const };
const emptyPrivate = { user: null, profiles: [], selectedId: null, sessions: [], emotions: [], reports: [], ...emptyFamily };

/** Cancels private reads and revokes late callbacks whenever identity or selection changes. */
export class CloudStore {
  private state: CloudState;
  private listeners = new Set<() => void>();
  private pending = new Set<RequestHandle<unknown>>();
  private unsubscribe: () => void;
  private disposed = false;
  private revision = 0;
  private familyToolsEnabled = false;
  private activeMutation: object | null = null;
  constructor(readonly auth: AuthAdapter | null, readonly api: CloudApi | null, private privateReadsEnabled = true) {
    this.state = { enabled: Boolean(auth && api), auth: auth?.getState() ?? { status: 'signed_out', principal: null, epoch: 0, message: '' }, epoch: 0,
      status: auth && api ? 'idle' : 'not_configured', message: '', ...emptyPrivate };
    this.unsubscribe = auth?.subscribeAuthState(() => {
      this.invalidate();
      this.update({ ...emptyPrivate, auth: auth.getState(), status: 'idle', message: '' });
      if (auth.getState().status === 'signed_in') void this.refresh();
    }) ?? (() => undefined);
  }
  getState = (): CloudState => this.state;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  /** Public previews retain identity, but cancel private reads and invalidate late responses. */
  setPrivateReadsEnabled(enabled: boolean): void {
    this.setPageScope(enabled, this.familyToolsEnabled);
  }
  /** New family features are read only on explicit Settings entry, never public previews. */
  setFamilyToolsEnabled(enabled: boolean): void {
    this.setPageScope(this.privateReadsEnabled, enabled);
  }
  /** Update both route permissions atomically: one invalidation and at most one refresh. */
  setPageScope(privateReadsEnabled: boolean, familyToolsEnabled: boolean): void {
    if (this.disposed || this.privateReadsEnabled === privateReadsEnabled && this.familyToolsEnabled === familyToolsEnabled) return;
    this.privateReadsEnabled = privateReadsEnabled;
    this.familyToolsEnabled = familyToolsEnabled;
    this.invalidate();
    this.update({ ...emptyFamily, status: this.api ? 'idle' : 'not_configured', message: '' });
    if (privateReadsEnabled) void this.refreshPrivate(false, true);
  }
  private update(patch: Partial<CloudState>): void {
    if (this.disposed) return;
    this.state = Object.freeze({ ...this.state, ...patch });
    for (const listener of this.listeners) listener();
  }
  private invalidate(preserveMutation = false): void {
    this.revision++;
    if (!preserveMutation) this.activeMutation = null;
    for (const request of this.pending) request.cancel();
    this.pending.clear();
    this.state = { ...this.state, epoch: this.state.epoch + 1 };
  }
  private async request<T>(handle: RequestHandle<T>): Promise<T> {
    this.pending.add(handle);
    try { return await handle.promise; } finally { this.pending.delete(handle); }
  }
  private failure(error: unknown, revision: number): void {
    if (revision !== this.revision || this.disposed) return;
    const result = error instanceof CloudError ? error : new CloudError('server');
    if (result.kind === 'cancelled') return;
    this.update({ status: result.kind === 'offline' ? 'offline' : 'error', message: result.message,
      parentProfileStatus: this.state.parentProfileStatus === 'loading' ? 'error' : this.state.parentProfileStatus });
  }
  async refresh(): Promise<void> {
    await this.refreshPrivate();
  }
  private async refreshPrivate(preserveMutation = false, alreadyInvalidated = false): Promise<void> {
    if (!this.privateReadsEnabled || !this.api || this.auth?.getState().status !== 'signed_in') return;
    if (!alreadyInvalidated) this.invalidate(preserveMutation);
    const revision = this.revision;
    const previousSelection = this.state.selectedId;
    this.update({ status: 'loading', message: '', sessions: [], emotions: [], reports: [], ...emptyFamily,
      parentProfileStatus: this.familyToolsEnabled ? 'loading' : 'idle' });
    try {
      const [user, children] = await Promise.all([this.request(this.api.me()), this.request(this.api.children())]);
      if (revision !== this.revision || this.disposed) return;
      const profiles = children.items.filter(item => item.status === 'active');
      const selectedId = previousSelection && profiles.some(profile => profile.id === previousSelection) ? previousSelection : null;
      this.update({ user, profiles, selectedId });
      const familyReady = !this.familyToolsEnabled || await this.refreshFamily(revision);
      if (revision !== this.revision || this.disposed) return;
      // Never automatically select a profile; the owner chooses explicitly.
      const recordsReady = !selectedId || await this.refreshSelected(revision, selectedId, false);
      if (revision === this.revision && !this.disposed && familyReady && recordsReady) this.update({ status: 'ready' });
    } catch (error) { this.failure(error, revision); }
  }
  private async refreshFamily(revision: number): Promise<boolean> {
    if (!this.api || !this.privateReadsEnabled || !this.familyToolsEnabled) return false;
    this.update({ parentProfile: null, parentProfileStatus: 'loading' });
    try {
      const capabilities = await this.request(this.api.capabilities());
      if (revision !== this.revision || this.disposed || !this.familyToolsEnabled || !this.privateReadsEnabled) return false;
      this.update({ capabilities });
      if (!capabilities.parent_profile) { this.update({ parentProfileStatus: 'unavailable' }); return true; }
      const parentProfile = await this.request(this.api.parentProfile());
      if (revision !== this.revision || this.disposed || !this.familyToolsEnabled || !this.privateReadsEnabled) return false;
      this.update({ parentProfile, parentProfileStatus: 'ready' });
      return true;
    } catch (error) { this.failure(error, revision); return false; }
  }
  selectProfile(id: string | null): void {
    if (id !== null && !this.state.profiles.some(profile => profile.id === id && profile.status === 'active')) throw new CloudError('invalid');
    if (id === this.state.selectedId) return;
    const familyReadInterrupted = this.state.parentProfileStatus === 'loading';
    this.invalidate();
    this.update({ selectedId: id, sessions: [], emotions: [], reports: [], status: 'ready', message: '' });
    if (familyReadInterrupted) void this.refreshFamily(this.revision);
    if (id) void this.refreshSelected(this.revision, id);
  }
  private async refreshSelected(revision: number, id: string, markReady = true): Promise<boolean> {
    if (!this.privateReadsEnabled || !this.api) return false;
    try {
      const [sessions, emotions, reports] = await Promise.all([
        this.request(this.api.sessions(id)), this.request(this.api.emotions(id)), this.request(this.api.reports(id)),
      ]);
      if (revision !== this.revision || this.disposed || this.state.selectedId !== id) return false;
      this.update({ sessions: sessions.items, emotions: emotions.items, reports: reports.items,
        ...(markReady ? { status: 'ready' as const, message: '' } : {}) });
      return true;
    } catch (error) { this.failure(error, revision); return false; }
  }
  private async mutate(operation: () => RequestHandle<unknown>): Promise<boolean> {
    if (!this.privateReadsEnabled || !this.api || this.auth?.getState().status !== 'signed_in' || this.disposed || this.activeMutation || this.state.status === 'loading') return false;
    const mutation = {};
    this.activeMutation = mutation;
    const revision = this.revision;
    const authEpoch = this.auth.getState().epoch;
    const subject = this.auth.getPrincipal()?.subject;
    this.update({ status: 'loading', message: '' });
    try {
      await this.request(operation());
      if (revision !== this.revision || this.disposed || !this.privateReadsEnabled) return false;
      await this.refreshPrivate(true);
      return !this.disposed && this.privateReadsEnabled && this.auth.getState().status === 'signed_in'
        && this.auth.getState().epoch === authEpoch && this.auth.getPrincipal()?.subject === subject;
    } catch (error) { this.failure(error, revision); return false; }
    finally { if (this.activeMutation === mutation) this.activeMutation = null; }
  }
  createProfile = (nickname: string, age_band?: ChildAgeBand | null): Promise<boolean> => age_band !== undefined && !this.state.capabilities?.child_age_band ? Promise.resolve(false) : this.mutate(() => this.api!.createChild(nickname, age_band));
  updateProfile = (id: string, nickname: string, age_band?: ChildAgeBand | null): Promise<boolean> => age_band !== undefined && !this.state.capabilities?.child_age_band ? Promise.resolve(false) : this.mutate(() => this.api!.updateChild(id, nickname, age_band));
  updateParentProfile = (nickname: string): Promise<boolean> => !this.familyToolsEnabled || !this.state.capabilities?.parent_profile || this.state.parentProfileStatus !== 'ready' ? Promise.resolve(false) : this.mutate(() => this.api!.updateParentProfile(nickname));
  archiveProfile = (id: string): Promise<boolean> => this.mutate(() => this.api!.archiveChild(id));
  updateUser = (name: string): Promise<boolean> => this.mutate(() => this.api!.updateMe(name));
  endStoredSession = (id: string): Promise<boolean> => this.mutate(() => this.api!.endSession(id));
  async signIn(input: { username?: string; password?: string }): Promise<void> { await this.auth?.signIn(input); }
  async signOut(): Promise<void> { await this.auth?.signOut(); }
  dispose(): void { this.invalidate(); this.disposed = true; this.unsubscribe(); this.listeners.clear(); this.auth?.dispose(); }
}
