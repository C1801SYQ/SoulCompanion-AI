import { captureConfig, idleCaptureStatus, type AudioChunk, type AudioInputLevel, type CameraOption, type CameraFacing, type CaptureConfig,
  type CaptureStatus, type DeviceCaptureStatus, type MediaCaptureAdapter, type VideoFrame } from '../types';

export abstract class CaptureAdapterBase implements MediaCaptureAdapter {
  protected status = idleCaptureStatus();
  protected readonly config: Readonly<CaptureConfig>;
  protected readonly statusListeners = new Set<(status: CaptureStatus) => void>();
  protected readonly videoListeners = new Set<(frame: VideoFrame) => void>();
  protected readonly audioListeners = new Set<(chunk: AudioChunk) => void>();
  protected readonly levelListeners = new Set<(level: AudioInputLevel) => void>();
  protected disposed = false;
  protected videoSequence = 0;
  protected audioSequence = 0;
  private reportingObserverFailure = false;
  private startVersion = 0;

  constructor(config: Partial<CaptureConfig> = {}) { this.config = captureConfig(config); }
  getStatus(): CaptureStatus { return { ...this.status, camera: { ...this.status.camera }, microphone: { ...this.status.microphone } }; }
  subscribeStatus(listener: (status: CaptureStatus) => void): () => void {
    this.statusListeners.add(listener);
    try { listener(this.getStatus()); } catch { this.statusListeners.delete(listener); this.observerFailure(); }
    return () => { this.statusListeners.delete(listener); };
  }
  subscribeVideoFrame(listener: (frame: VideoFrame) => void): () => void {
    this.videoListeners.add(listener); return () => { this.videoListeners.delete(listener); };
  }
  subscribeAudioChunk(listener: (chunk: AudioChunk) => void): () => void {
    this.audioListeners.add(listener); return () => { this.audioListeners.delete(listener); };
  }
  subscribeAudioLevel(listener: (level: AudioInputLevel) => void): () => void {
    this.levelListeners.add(listener); return () => { this.levelListeners.delete(listener); };
  }
  async listCameras(): Promise<CameraOption[]> { return []; }
  protected publish(): void {
    for (const listener of [...this.statusListeners]) {
      try { listener(this.getStatus()); } catch { this.statusListeners.delete(listener); this.observerFailure(); }
    }
  }
  protected emitVideo(frame: VideoFrame): void {
    for (const listener of [...this.videoListeners]) {
      try { listener(frame); } catch { this.videoListeners.delete(listener); this.observerFailure(); return; }
    }
  }
  protected emitAudio(chunk: AudioChunk): void {
    for (const listener of [...this.audioListeners]) {
      try { listener(chunk); } catch { this.audioListeners.delete(listener); this.observerFailure(); return; }
    }
  }
  protected emitLevel(level: AudioInputLevel): void {
    for (const listener of [...this.levelListeners]) {
      try { listener(level); } catch { this.levelListeners.delete(listener); this.observerFailure(); return; }
    }
  }
  private observerFailure(): void {
    if (this.reportingObserverFailure || this.disposed) return;
    this.reportingObserverFailure = true;
    const cleanup = this.stopAll();
    const version = this.startVersion;
    this.status = { ...this.status, camera: { ...this.status.camera, state: 'error', problem: 'capture_failed' },
      microphone: { ...this.status.microphone, state: 'error', problem: 'capture_failed' } };
    this.publish();
    void cleanup.catch(() => {
      if (version !== this.startVersion || this.disposed) return;
      this.status = { ...this.status, camera: { ...this.status.camera, state: 'error', problem: 'cleanup_failed' },
        microphone: { ...this.status.microphone, state: 'error', problem: 'cleanup_failed' } };
      this.publish();
    }).finally(() => { this.reportingObserverFailure = false; });
  }
  protected device(device: 'camera' | 'microphone', update: Partial<DeviceCaptureStatus>): void {
    if (update.state === 'requesting' && this.status[device].state !== 'requesting') this.startVersion++;
    this.status = { ...this.status, [device]: { ...this.status[device], ...update } }; this.publish();
  }
  protected preview(mounted: boolean): void {
    if (this.status.previewMounted === mounted) return;
    this.status = { ...this.status, previewMounted: mounted }; this.publish();
  }
  protected clearSubscribers(): void { this.statusListeners.clear(); this.videoListeners.clear(); this.audioListeners.clear(); this.levelListeners.clear(); }
  abstract startCamera(facing?: CameraFacing, deviceId?: string): Promise<void>;
  abstract stopCamera(): Promise<void>;
  abstract startMicrophone(): Promise<void>;
  abstract stopMicrophone(): Promise<void>;
  abstract stopAll(): Promise<void>;
  abstract bindPreview(target: unknown | null): void;
  abstract previewReady(): void;
  abstract previewError(error: unknown): void;
  abstract dispose(): Promise<void>;
}
