import type { AuthAdapter, CloudApi, CloudSession, SourcePlatform } from './types';
import { CloudError } from './types';
export interface MetadataState { status: 'local_only' | 'creating' | 'active' | 'ending' | 'ended' | 'create_unconfirmed' | 'end_unconfirmed'; sessionId: string | null; message: string }
interface Attempt { generation: number; subject: string; authEpoch: number; childId: string; ended: boolean; createFailed: boolean; session: CloudSession | null; api: CloudApi }
/** Watches lifecycle metadata only; it never subscribes to camera frames or microphone bytes. */
export class CloudSessionBridge {
  private state: MetadataState = { status: 'local_only', sessionId: null, message: '' };
  private listeners = new Set<() => void>();
  private attempt: Attempt | null = null;
  private generation = 0;
  private disposed = false;
  constructor(private readonly auth: AuthAdapter | null, private readonly api: CloudApi | null, private readonly platform: SourcePlatform) {}
  getState = (): MetadataState => this.state;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private publish(attempt: Attempt | null, patch: Partial<MetadataState>): void {
    if (this.disposed || (attempt && (attempt.generation !== this.generation || !this.valid(attempt)))) return;
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
  private valid(attempt: Attempt): boolean { return this.auth?.getState().status === 'signed_in' && this.auth.getState().epoch === attempt.authEpoch && this.auth.getPrincipal()?.subject === attempt.subject; }
  begin(childId: string | null): void {
    this.end();
    const principal = this.auth?.getPrincipal();
    if (!principal || !this.api || !childId) { this.publish(null, { status: 'local_only', sessionId: null, message: '仅本地预览；登录并选择档案后可记录会话起止时间。' }); return; }
    const attempt: Attempt = { generation: ++this.generation, subject: principal.subject, authEpoch: this.auth!.getState().epoch, childId, ended: false, createFailed: false, session: null, api: this.api };
    this.attempt = attempt;
    this.publish(attempt, { status: 'creating', sessionId: null, message: '正在记录云端会话起止时间；音视频仍留在本机。' });
    void attempt.api.createSession(childId, this.platform).promise.then(session => {
      attempt.session = session;
      if (!this.valid(attempt)) {
        if (attempt.generation === this.generation) this.publish(null, { status: 'end_unconfirmed', sessionId: null, message: '本地设备已停止；原账号的云端结束状态未确认，请重新登录后检查会话。' });
        return;
      }
      if (attempt.ended) { void this.close(attempt); return; }
      this.publish(attempt, { status: 'active', sessionId: session.id, message: '仅同步会话起止时间；没有上传音视频或设备信息。' });
    }).catch(() => {
      attempt.createFailed = true;
      this.publish(attempt, { status: attempt.ended ? 'end_unconfirmed' : 'create_unconfirmed', sessionId: null, message: '云端会话创建未确认。本地预览仍可结束；稍后检查云端会话列表。' });
    });
  }
  end(): void {
    const attempt = this.attempt;
    if (!attempt || attempt.ended) return;
    attempt.ended = true;
    if (attempt.session) void this.close(attempt);
    else this.publish(attempt, { status: attempt.createFailed ? 'end_unconfirmed' : 'ending', message: attempt.createFailed ? '本机已停止；云端起止状态未确认，请在设置中刷新资料并检查云端会话。' : '本地设备正在停止；云端起止时间等待确认。' });
  }
  private async close(attempt: Attempt): Promise<void> {
    if (!attempt.session) return;
    if (!this.valid(attempt)) { this.publish(null, { status: 'end_unconfirmed', sessionId: null, message: '本机已停止；原账号的云端结束状态未确认。重新登录后可检查并结束会话。' }); return; }
    this.publish(attempt, { status: 'ending', message: '本机已停止；正在确认云端会话结束。' });
    try { const result = await attempt.api.endSession(attempt.session.id).promise; if (result.status !== 'ended') throw new CloudError('invalid'); this.publish(attempt, { status: 'ended', sessionId: result.id, message: '云端会话起止时间已确认。音视频没有上传。' }); }
    catch { this.publish(attempt, { status: 'end_unconfirmed', message: '本机已停止；云端会话结束未确认，请在网络恢复后检查或重试。' }); }
  }
  retryEnd(): void { if (this.attempt?.ended && this.attempt.session) void this.close(this.attempt); }
  clearPrivate(): void {
    const unconfirmed = Boolean(this.attempt) && this.state.status !== 'ended';
    this.end(); ++this.generation; this.attempt = null;
    this.publish(null, { status: unconfirmed ? 'end_unconfirmed' : 'local_only', sessionId: null,
      message: unconfirmed ? '本机已停止，当前云端资料已隐藏；原账号或档案的云端结束状态未确认，请重新选择后检查会话列表。' : '当前云端资料已隐藏。本地采集需要再次主动开始。' });
  }
  dispose(): void { this.end(); this.disposed = true; this.listeners.clear(); }
}
