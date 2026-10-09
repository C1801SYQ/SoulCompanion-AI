import type { RequestHandle } from '../services/types';
import { CloudError, type AuthAdapter, type AuthState, type ChildProfile, type CloudApi, type CloudEmotion, type CloudReport, type CloudSession, type CloudUser } from './types';

export interface CloudState {
  enabled: boolean; auth: AuthState; epoch: number; status: 'not_configured' | 'idle' | 'loading' | 'ready' | 'offline' | 'error';
  message: string; user: CloudUser | null; profiles: ChildProfile[]; selectedId: string | null;
  sessions: CloudSession[]; emotions: CloudEmotion[]; reports: CloudReport[];
}
const emptyPrivate = { user: null, profiles: [], selectedId: null, sessions: [], emotions: [], reports: [] };

/** Cancels private reads and revokes late callbacks whenever identity or selection changes. */
export class CloudStore {
  private state: CloudState;
  private listeners = new Set<() => void>();
  private pending = new Set<RequestHandle<unknown>>();
  private unsubscribe: () => void;
  private disposed = false;
  private revision = 0;
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
    if (this.disposed || this.privateReadsEnabled === enabled) return;
    this.privateReadsEnabled = enabled;
    this.invalidate();
    this.update({ status: this.api ? 'idle' : 'not_configured', message: '' });
    if (enabled) void this.refresh();
  }
  private update(patch: Partial<CloudState>): void {
    if (this.disposed) return;
    this.state = Object.freeze({ ...this.state, ...patch });
    for (const listener of this.listeners) listener();
  }
  private invalidate(): void {
    this.revision++;
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
    this.update({ status: result.kind === 'offline' ? 'offline' : 'error', message: result.message });
  }
  async refresh(): Promise<void> {
    if (!this.privateReadsEnabled || !this.api || this.auth?.getState().status !== 'signed_in') return;
    this.invalidate();
    const revision = this.revision;
    const previousSelection = this.state.selectedId;
    this.update({ status: 'loading', message: '', sessions: [], emotions: [], reports: [] });
    try {
      const [user, children] = await Promise.all([this.request(this.api.me()), this.request(this.api.children())]);
      if (revision !== this.revision || this.disposed) return;
      const profiles = children.items.filter(item => item.status === 'active');
      const selectedId = previousSelection && profiles.some(profile => profile.id === previousSelection) ? previousSelection : null;
      this.update({ user, profiles, selectedId, status: 'ready' });
      // Never automatically select a profile; the owner chooses explicitly.
      if (selectedId) await this.refreshSelected(revision, selectedId);
    } catch (error) { this.failure(error, revision); }
  }
  selectProfile(id: string | null): void {
    if (id !== null && !this.state.profiles.some(profile => profile.id === id && profile.status === 'active')) throw new CloudError('invalid');
    if (id === this.state.selectedId) return;
    this.invalidate();
    this.update({ selectedId: id, sessions: [], emotions: [], reports: [], status: 'ready', message: '' });
    if (id) void this.refreshSelected(this.revision, id);
  }
  private async refreshSelected(revision: number, id: string): Promise<void> {
    if (!this.privateReadsEnabled || !this.api) return;
    try {
      const [sessions, emotions, reports] = await Promise.all([
        this.request(this.api.sessions(id)), this.request(this.api.emotions(id)), this.request(this.api.reports(id)),
      ]);
      if (revision !== this.revision || this.disposed || this.state.selectedId !== id) return;
      this.update({ sessions: sessions.items, emotions: emotions.items, reports: reports.items, status: 'ready', message: '' });
    } catch (error) { this.failure(error, revision); }
  }
  private async mutate(operation: () => RequestHandle<unknown>): Promise<void> {
    if (!this.privateReadsEnabled) throw new CloudError('forbidden');
    if (!this.api || this.auth?.getState().status !== 'signed_in') return;
    const revision = this.revision;
    this.update({ status: 'loading', message: '' });
    try {
      await this.request(operation());
      if (revision === this.revision) await this.refresh();
    } catch (error) { this.failure(error, revision); }
  }
  createProfile = (nickname: string): Promise<void> => this.mutate(() => this.api!.createChild(nickname));
  updateProfile = (id: string, nickname: string): Promise<void> => this.mutate(() => this.api!.updateChild(id, nickname));
  archiveProfile = (id: string): Promise<void> => this.mutate(() => this.api!.archiveChild(id));
  updateUser = (name: string): Promise<void> => this.mutate(() => this.api!.updateMe(name));
  endStoredSession = (id: string): Promise<void> => this.mutate(() => this.api!.endSession(id));
  async signIn(input: { username?: string; password?: string }): Promise<void> { await this.auth?.signIn(input); }
  async signOut(): Promise<void> { await this.auth?.signOut(); }
  dispose(): void { this.invalidate(); this.disposed = true; this.unsubscribe(); this.listeners.clear(); this.auth?.dispose(); }
}
