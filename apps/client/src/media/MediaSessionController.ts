import {
  DEFAULT_CAPTURE_CONFIG, MediaCaptureError, idleCaptureStatus,
  type AudioChunk, type AudioInputLevel, type CaptureStatus, type MediaCaptureAdapter, type MediaProblem,
  type MediaSelection, type MediaSessionContext, type MediaSessionState,
  type MediaStopReason, type VideoFrame,
} from './types';

function snapshot(status: CaptureStatus): CaptureStatus {
  return Object.freeze({
    camera: Object.freeze({ ...status.camera }),
    microphone: Object.freeze({ ...status.microphone }),
    previewMounted: status.previewMounted,
  });
}

function problemFrom(error: unknown): MediaProblem {
  return error instanceof MediaCaptureError ? error.code : 'capture_failed';
}

/** Explicit intent, lifecycle and metadata only. This controller never stores or uploads media. */
export class MediaSessionController {
  private state: MediaSessionState = Object.freeze({
    phase: 'idle', capture: snapshot(idleCaptureStatus()),
    selection: Object.freeze({ camera: true, microphone: true, facing: 'user' }),
    problem: null, stoppedReason: null, videoFrames: 0, audioChunks: 0, inputLevel: null,
  });
  private context: MediaSessionContext = { source: 'real', connection: 'connecting', visible: true };
  private readonly listeners = new Set<() => void>();
  private readonly unsubscribers: (() => void)[];
  private generation = 0;
  private cancelStart: (() => void) | null = null;
  private stopping: Promise<void> | null = null;
  private disposed = false;
  private cleanupIncomplete = false;
  private videoSequence = -1;
  private audioSequence = -1;
  private readonly startingDevices = new Set<'camera' | 'microphone'>();
  private readonly startTimeoutMs: number;

  constructor(public readonly adapter: MediaCaptureAdapter, options: { startTimeoutMs?: number } = {}) {
    this.startTimeoutMs = options.startTimeoutMs ?? 20_000;
    if (!Number.isFinite(this.startTimeoutMs) || this.startTimeoutMs < 10 || this.startTimeoutMs > 30_000) {
      throw new RangeError('Media start timeout is invalid');
    }
    this.state = Object.freeze({ ...this.state, capture: snapshot(adapter.getStatus()) });
    this.unsubscribers = [
      adapter.subscribeStatus(status => this.onStatus(status)),
      adapter.subscribeVideoFrame(frame => this.onVideo(frame)),
      adapter.subscribeAudioChunk(chunk => this.onAudio(chunk)),
      adapter.subscribeAudioLevel(input => this.onLevel(input)),
    ];
  }

  getState = (): MediaSessionState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    if (this.disposed) return () => {};
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private update(patch: Partial<MediaSessionState>): void {
    this.state = Object.freeze({ ...this.state, ...patch });
    let observerFailed = false;
    for (const listener of this.listeners) {
      try { listener(); } catch { observerFailed = true; }
    }
    // A broken view must never prevent releasing the operating system's devices.
    if (observerFailed && (this.state.phase === 'active' || this.state.phase === 'starting')) {
      this.state = Object.freeze({ ...this.state, problem: 'capture_failed' });
      void this.stop('device_error');
    }
  }

  setContext(context: MediaSessionContext): void {
    this.context = { ...context };
    if (this.state.phase !== 'active' && this.state.phase !== 'starting') return;
    if (!context.visible) void this.stop('background');
    else if (context.networkOnline === false) void this.stop('offline');
  }

  async start(selection: MediaSelection): Promise<void> {
    if (this.disposed || this.stopping || this.state.phase === 'starting' || this.state.phase === 'active'
      || this.state.phase === 'stopping') return;
    if (this.cleanupIncomplete) {
      this.update({ problem: 'cleanup_failed' });
      return;
    }
    if (!this.context.visible || this.context.networkOnline === false) {
      this.update({ problem: 'interrupted' });
      return;
    }
    if (!selection.camera && !selection.microphone) {
      this.update({ problem: 'nothing_selected' });
      return;
    }
    if (selection.facing !== 'user' && selection.facing !== 'environment') {
      this.update({ problem: 'capture_failed' });
      return;
    }
    if (selection.cameraDeviceId !== undefined && (typeof selection.cameraDeviceId !== 'string'
      || selection.cameraDeviceId.length === 0 || selection.cameraDeviceId.length > 512
      || /[\u0000-\u001f\u007f]/.test(selection.cameraDeviceId))) {
      this.update({ problem: 'capture_failed' });
      return;
    }
    const current = ++this.generation;
    this.videoSequence = -1;
    this.audioSequence = -1;
    this.startingDevices.clear();
    this.update({ phase: 'starting', selection: Object.freeze({ ...selection }),
      problem: null, stoppedReason: null, videoFrames: 0, audioChunks: 0, inputLevel: null });
    if (current !== this.generation) return;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    const canceled = new Promise<'canceled'>(resolve => { this.cancelStart = () => resolve('canceled'); });
    const timedOut = new Promise<'timeout'>(resolve => {
      deadline = setTimeout(() => resolve('timeout'), this.startTimeoutMs);
    });
    try {
      // Start both requested devices during the same user action. Each adapter owns late-grant cleanup.
      const tasks: Promise<void>[] = [];
      const request = (device: 'camera' | 'microphone', operation: () => Promise<void>): void => {
        if (current !== this.generation || this.disposed) return;
        // A status broadcast also includes other devices' previous failures. Only devices
        // requested in this attempt can cancel it, and cancellation revokes the next request.
        this.startingDevices.add(device);
        try { tasks.push(operation()); } catch (error) { tasks.push(Promise.reject(error)); }
      };
      if (selection.camera) request('camera', () => this.adapter.startCamera(selection.facing, selection.cameraDeviceId));
      if (selection.microphone) request('microphone', () => this.adapter.startMicrophone());
      const started = Promise.all(tasks).then(() => 'started' as const);
      const outcome = await Promise.race([started, canceled, timedOut]);
      if (this.disposed || current !== this.generation || outcome === 'canceled') return;
      if (outcome === 'timeout') {
        this.update({ problem: 'timeout' });
        await this.stop('timeout');
        return;
      }
      const capture = this.adapter.getStatus();
      if ((selection.camera && capture.camera.state !== 'on')
        || (selection.microphone && capture.microphone.state !== 'on')) {
        throw new MediaCaptureError('capture_failed');
      }
      this.update({ phase: 'active', capture: snapshot(capture) });
    } catch (error) {
      if (current === this.generation && !this.disposed) {
        this.update({ problem: problemFrom(error) });
        await this.stop('device_error');
      }
    } finally {
      if (deadline !== undefined) clearTimeout(deadline);
      if (current === this.generation) this.cancelStart = null;
    }
  }

  stop(reason: MediaStopReason = 'user'): Promise<void> {
    // Revoke intent synchronously, even while an OS permission prompt remains unanswered.
    ++this.generation;
    this.cancelStart?.();
    this.cancelStart = null;
    if (this.stopping) return this.stopping;
    const failed = reason === 'device_error' || reason === 'timeout';
    const failedCapture = this.state.capture;
    const cleanup = Promise.resolve().then(() => this.adapter.stopAll()).then(() => {
      let capture = snapshot(this.adapter.getStatus());
      if ([capture.camera.state, capture.microphone.state].some(state => state === 'on' || state === 'requesting')) {
        throw new MediaCaptureError('cleanup_failed');
      }
      if (failed) {
        // Resource release does not turn a refused permission or missing device into plain OFF.
        const failureState = (device: 'camera' | 'microphone') => {
          const previous = failedCapture[device];
          return ['denied', 'missing', 'error'].includes(previous.state) && previous.problem
            ? { ...capture[device], state: previous.state, problem: previous.problem }
            : capture[device];
        };
        capture = snapshot({ ...capture, camera: failureState('camera'), microphone: failureState('microphone') });
      }
      this.cleanupIncomplete = false;
      this.update({ phase: failed ? 'error' : 'idle', capture });
    }).catch(() => {
      this.cleanupIncomplete = true;
      // Keep the last known status when the platform cannot confirm cleanup.
      this.update({ phase: 'error', problem: 'cleanup_failed' });
    }).finally(() => { this.stopping = null; });
    this.stopping = cleanup;
    this.update({ phase: 'stopping', stoppedReason: reason, problem: failed ? this.state.problem : null, inputLevel: null });
    return cleanup;
  }

  private onStatus(status: CaptureStatus): void {
    if (this.disposed) return;
    this.update({ capture: snapshot(status) });
    if (this.state.phase !== 'starting' && this.state.phase !== 'active') return;
    const devices = [
      ...(this.state.selection.camera && (this.state.phase === 'active' || this.startingDevices.has('camera')) ? [status.camera] : []),
      ...(this.state.selection.microphone && (this.state.phase === 'active' || this.startingDevices.has('microphone')) ? [status.microphone] : []),
    ];
    const failure = devices.find(device => device.state === 'denied' || device.state === 'missing'
      || device.state === 'error' || (this.state.phase === 'active' && device.state === 'off'));
    if (failure) {
      this.update({ problem: failure.problem ?? 'device_ended' });
      void this.stop('device_error');
    }
  }

  private onVideo(frame: VideoFrame): void {
    if (this.disposed || this.state.phase !== 'active' || !this.state.selection.camera
      || this.state.capture.camera.state !== 'on') return;
    if (!this.validPacket(frame) || !['image/jpeg', 'image/webp'].includes(frame.mime)
      || frame.bytes.byteLength > DEFAULT_CAPTURE_CONFIG.maxFrameBytes
      || !Number.isInteger(frame.width) || frame.width < 1 || frame.width > DEFAULT_CAPTURE_CONFIG.maxWidth
      || !Number.isInteger(frame.height) || frame.height < 1 || frame.height > DEFAULT_CAPTURE_CONFIG.maxHeight) {
      this.update({ problem: 'encoding_failed' });
      void this.stop('device_error');
      return;
    }
    if (frame.sequence <= this.videoSequence) return;
    this.videoSequence = frame.sequence;
    this.update({ videoFrames: Math.min(Number.MAX_SAFE_INTEGER, this.state.videoFrames + 1) });
  }

  private onAudio(chunk: AudioChunk): void {
    if (this.disposed || this.state.phase !== 'active' || !this.state.selection.microphone
      || this.state.capture.microphone.state !== 'on') return;
    if (!this.validPacket(chunk) || !['audio/wav', 'audio/mpeg'].includes(chunk.mime)
      || chunk.bytes.byteLength > DEFAULT_CAPTURE_CONFIG.maxAudioBytes
      || !Number.isInteger(chunk.sampleRate) || chunk.sampleRate < 8000 || chunk.sampleRate > 96000
      || chunk.channels !== 1 || (chunk.durationMs !== null
        && (!Number.isFinite(chunk.durationMs) || chunk.durationMs <= 0 || chunk.durationMs > 5000))) {
      this.update({ problem: 'encoding_failed' });
      void this.stop('device_error');
      return;
    }
    if (chunk.sequence <= this.audioSequence) return;
    this.audioSequence = chunk.sequence;
    this.update({ audioChunks: Math.min(Number.MAX_SAFE_INTEGER, this.state.audioChunks + 1) });
  }

  private onLevel(input: AudioInputLevel): void {
    if (this.disposed || this.state.phase !== 'active' || !this.state.selection.microphone
      || this.state.capture.microphone.state !== 'on') return;
    if (!Number.isFinite(input.timestamp) || Math.abs(Date.now() - input.timestamp) > 30_000
      || (input.level !== null && (!Number.isFinite(input.level) || input.level < 0 || input.level > 1))) {
      this.update({ problem: 'encoding_failed' });
      void this.stop('device_error');
      return;
    }
    this.update({ inputLevel: input.level });
  }

  private validPacket(packet: VideoFrame | AudioChunk): boolean {
    return packet.bytes instanceof ArrayBuffer && packet.bytes.byteLength > 0
      && Number.isSafeInteger(packet.sequence) && packet.sequence >= 0
      && Number.isFinite(packet.timestamp) && Math.abs(Date.now() - packet.timestamp) <= 30_000;
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    for (const unsubscribe of this.unsubscribers) unsubscribe();
    try {
      await this.stop('unmount');
    } finally {
      try { await this.adapter.dispose(); }
      catch { this.update({ phase: 'error', problem: 'cleanup_failed' }); }
      finally { this.listeners.clear(); }
    }
  }
}
