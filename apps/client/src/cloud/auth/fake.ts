import { CloudError, type AuthAdapter, type AuthState } from '../types';
/** Injected by tests only. Never selected by a production platform factory. */
export class FakeAuthAdapter implements AuthAdapter {
  private state: AuthState = { status: 'signed_out', principal: null, epoch: 0, message: '' };
  private listeners = new Set<() => void>();
  constructor(private subject = 'synthetic-user', private token = 'synthetic-test-token') {}
  getState = () => this.state;
  getPrincipal = () => this.state.principal;
  subscribeAuthState = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update(status: AuthState['status']) { this.state = { status, principal: status === 'signed_in' ? { subject: this.subject, provider: 'fake' } : null, epoch: this.state.epoch + 1, message: '' }; for (const listener of this.listeners) listener(); }
  async signIn() { this.update('signed_in'); }
  async signOut() { this.update('signed_out'); }
  async getAccessToken() { if (!this.getPrincipal()) throw new CloudError('unauthorized'); return this.token; }
  expire() { this.update('expired'); }
  setAccount(subject: string, token: string) { this.subject = subject; this.token = token; this.update('signed_in'); }
  dispose() { this.listeners.clear(); }
}
