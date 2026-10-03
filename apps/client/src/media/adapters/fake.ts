import { CaptureAdapterBase } from './base';
import { MediaCaptureError, type AudioChunk, type AudioInputLevel, type CameraFacing, type CameraOption, type CaptureConfig, type VideoFrame } from '../types';

export type FakePermission = 'allow' | 'deny' | 'missing' | 'late';
type Device = 'camera' | 'microphone';

/** Explicit test double. Production factories never import or select this adapter. */
export class FakeMediaCaptureAdapter extends CaptureAdapterBase {
  readonly observations = { permissionRequests: { camera: 0, microphone: 0 }, stoppedTracks: 0, activeTracks: 0, disposed: false };
  private readonly outcomes: Record<Device, FakePermission>;
  private readonly generations = { camera: 0, microphone: 0 };
  private readonly pending: { device: Device; resolve: () => void }[] = [];
  private readonly tracks = { camera: false, microphone: false };

  constructor(outcomes: Partial<Record<Device, FakePermission>> = {}, config: Partial<CaptureConfig> = {}) {
    super(config); this.outcomes = { camera: 'allow', microphone: 'allow', ...outcomes };
  }
  grantPending(device: Device): void {
    const index = this.pending.findIndex(request => request.device === device);
    if (index >= 0) this.pending.splice(index, 1)[0].resolve();
  }
  private async start(device: Device): Promise<void> {
    if (this.disposed) throw new MediaCaptureError('interrupted');
    if (this.status[device].state === 'on') return;
    const epoch = ++this.generations[device];
    this.observations.permissionRequests[device]++;
    this.device(device, { state: 'requesting', problem: null });
    if (this.outcomes[device] === 'late') await new Promise<void>(resolve => { this.pending.push({ device, resolve }); });
    else await Promise.resolve();
    if (epoch !== this.generations[device] || this.disposed) {
      // A late grant represents a real newly returned track that is immediately released.
      this.observations.stoppedTracks++; throw new MediaCaptureError('interrupted');
    }
    if (this.outcomes[device] === 'deny' || this.outcomes[device] === 'missing') {
      const denied = this.outcomes[device] === 'deny';
      const code = denied ? 'permission_denied' : 'device_missing';
      this.device(device, { state: denied ? 'denied' : 'missing', permission: denied ? 'denied' : 'unknown', problem: code });
      throw new MediaCaptureError(code);
    }
    this.tracks[device] = true; this.observations.activeTracks++;
    this.device(device, { state: 'on', permission: 'granted', problem: null });
  }
  startCamera(_facing: CameraFacing = 'user', _deviceId?: string): Promise<void> { return this.start('camera'); }
  override async listCameras(): Promise<CameraOption[]> {
    return this.status.camera.permission === 'granted' ? [{ deviceId: 'fake-camera-1', label: '合成测试摄像头' }] : [];
  }
  startMicrophone(): Promise<void> { return this.start('microphone'); }
  private stop(device: Device): void {
    this.generations[device]++;
    if (this.tracks[device]) {
      this.tracks[device] = false; this.observations.activeTracks--; this.observations.stoppedTracks++;
    }
    this.device(device, { state: 'off', problem: null });
    if (device === 'microphone') this.emitLevel({ level: 0, timestamp: Date.now() });
  }
  async stopCamera(): Promise<void> { this.stop('camera'); }
  async stopMicrophone(): Promise<void> { this.stop('microphone'); }
  async stopAll(): Promise<void> { this.stop('camera'); this.stop('microphone'); }
  frameEmitter(): (frame: VideoFrame) => void {
    const epoch = this.generations.camera;
    return frame => { if (epoch === this.generations.camera && this.status.camera.state === 'on') this.emitVideo(frame); };
  }
  audioEmitter(): (chunk: AudioChunk) => void {
    const epoch = this.generations.microphone;
    return chunk => { if (epoch === this.generations.microphone && this.status.microphone.state === 'on') this.emitAudio(chunk); };
  }
  levelEmitter(): (level: AudioInputLevel) => void {
    const epoch = this.generations.microphone;
    return level => { if (epoch === this.generations.microphone && this.status.microphone.state === 'on') this.emitLevel(level); };
  }
  end(device: Device): void {
    if (this.status[device].state !== 'on') return;
    void this.stopAll(); this.device(device, { state: 'error', problem: 'device_ended' });
  }
  bindPreview(target: unknown | null): void { this.preview(Boolean(target)); }
  previewReady(): void { /* Fake preview never opens a platform device. */ }
  previewError(_error: unknown): void { void this.stopAll(); this.device('camera', { state: 'error', problem: 'capture_failed' }); }
  async dispose(): Promise<void> {
    this.disposed = true; this.observations.disposed = true;
    await this.stopAll(); this.clearSubscribers(); this.preview(false);
  }
}
