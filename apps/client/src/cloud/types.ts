import type { RequestHandle } from '../services/types';

export type AuthStatus = 'signed_out' | 'signing_in' | 'signed_in' | 'expired' | 'offline' | 'error';
export interface AuthPrincipal { subject: string; provider: 'cloudbase_web' | 'wechat_mini' | 'fake' }
export interface AuthState { status: AuthStatus; principal: AuthPrincipal | null; epoch: number; message: string }
export interface SignInInput { username?: string; password?: string }
export interface AuthAdapter {
  signIn(input?: SignInInput): Promise<void>;
  signOut(): Promise<void>;
  getPrincipal(): AuthPrincipal | null;
  getAccessToken(): Promise<string>;
  getState(): AuthState;
  subscribeAuthState(listener: () => void): () => void;
  expire(): void;
  dispose(): void;
}
export type CloudFailure = 'unauthorized' | 'forbidden' | 'rate_limited' | 'offline' | 'server' | 'invalid' | 'cancelled' | 'not_configured';
export class CloudError extends Error {
  constructor(readonly kind: CloudFailure, readonly status?: number, readonly requestId?: string, readonly retryAfterMs?: number) {
    super(cloudErrorText(kind)); this.name = 'CloudError';
  }
}
export function cloudErrorText(kind: CloudFailure): string {
  return ({ unauthorized: '登录已失效，请重新登录。', forbidden: '当前账号无权执行这个操作。',
    rate_limited: '操作较频繁，请稍后重试。', offline: '云端暂时无法连接，本地设备仍可随时结束。',
    server: '云端服务暂时不可用，请稍后重试。', invalid: '云端响应或输入格式不符合要求。',
    cancelled: '操作已取消。', not_configured: '此构建尚未配置云端账号服务。' })[kind];
}
export interface CloudUser { id: string; display_name: string; status: string; created_at: string; updated_at: string }
export interface ChildProfile { id: string; nickname: string; status: 'active' | 'archived'; created_at: string; updated_at: string }
export type SourcePlatform = 'web' | 'wechat' | 'android_future';
export interface CloudSession { id: string; child_profile_id: string; source_platform: SourcePlatform; started_at: string; ended_at: string | null; status: 'active' | 'ended'; created_at: string }
export interface CloudEmotion { id: string; child_profile_id: string; session_id: string; timestamp: string; category: string; confidence: number; valence: number; arousal: number; source: string; created_at: string }
export interface CloudReport { id: string; child_profile_id: string; range_start: string; range_end: string; summary: string; created_at: string }
export interface CloudPage<T> { items: T[]; limit: number; offset: number; total: number }
export interface CloudApi {
  me(): RequestHandle<CloudUser>;
  updateMe(display_name: string): RequestHandle<CloudUser>;
  children(): RequestHandle<CloudPage<ChildProfile>>;
  createChild(nickname: string): RequestHandle<ChildProfile>;
  child(id: string): RequestHandle<ChildProfile>;
  updateChild(id: string, nickname: string): RequestHandle<ChildProfile>;
  archiveChild(id: string): RequestHandle<void>;
  createSession(child_profile_id: string, source_platform: SourcePlatform): RequestHandle<CloudSession>;
  endSession(id: string): RequestHandle<CloudSession>;
  sessions(child_profile_id: string): RequestHandle<CloudPage<CloudSession>>;
  emotions(child_profile_id: string): RequestHandle<CloudPage<CloudEmotion>>;
  reports(child_profile_id: string): RequestHandle<CloudPage<CloudReport>>;
  currentReport(child_profile_id: string): RequestHandle<CloudReport | null>;
}
