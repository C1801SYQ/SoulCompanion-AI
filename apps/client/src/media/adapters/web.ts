import { CaptureAdapterBase } from './base';
import { MediaCaptureError, type CameraOption, type CameraFacing, type CaptureConfig, type MediaProblem } from '../types';
import { encodeVideoFrame } from '../processors/image-encoding';
import { encodeMonoWav } from '../processors/wav';

export interface WebMediaDriver {
  mediaDevices?: MediaDevices | null;
  document?: Document | null;
  window?: Window | null;
  secureContext?: boolean;
  createAudioContext?: () => AudioContext;
  createWorklet?: (context: AudioContext, options: AudioWorkletNodeOptions) => AudioWorkletNode;
}

function problem(error: unknown): MediaProblem {
  if (error instanceof MediaCaptureError) return error.code;
  const name = error && typeof error === 'object' && 'name' in error ? String(error.name) : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'permission_denied';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'device_missing';
  if (name === 'NotReadableError') return 'device_in_use';
  if (name === 'AbortError') return 'interrupted';
  return 'capture_failed';
}

export class WebMediaCaptureAdapter extends CaptureAdapterBase {
  private readonly mediaDevices: MediaDevices | null;
  private readonly document: Document | null;
  private readonly window: Window | null;
  private readonly driver: WebMediaDriver;
  private cameraGeneration = 0;
  private audioGeneration = 0;
  private cameraStream: MediaStream | null = null;
  private microphoneStream: MediaStream | null = null;
  private previewVideo: HTMLVideoElement | null = null;
  private captureVideo: HTMLVideoElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private frameTimer: ReturnType<typeof setInterval> | null = null;
  private encodingToken: object | null = null;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private mute: GainNode | null = null;
  private readonly trackListeners = new Map<MediaStreamTrack, () => void>();
  private readonly unreleasedTracks = new Set<MediaStreamTrack>();
  private readonly unclosedContexts = new Set<AudioContext>();
  private readonly undisconnectedNodes = new Set<AudioNode>();
  private readonly unclosedPorts = new Set<MessagePort>();
  private readonly lifecycle: (() => void)[] = [];
  private cameraStopPromise: Promise<void> | null = null;
  private microphoneStopPromise: Promise<void> | null = null;
  private allStopPromise: Promise<void> | null = null;

  constructor(config: Partial<CaptureConfig> = {}, driver: WebMediaDriver = {}) {
    super(config); this.driver = driver;
    this.mediaDevices = driver.mediaDevices === undefined ? (typeof navigator === 'undefined' ? null : navigator.mediaDevices ?? null) : driver.mediaDevices;
    this.document = driver.document === undefined ? (typeof document === 'undefined' ? null : document) : driver.document;
    this.window = driver.window === undefined ? (typeof window === 'undefined' ? null : window) : driver.window;
    this.listen(this.document, 'visibilitychange', () => { if (this.document?.hidden) this.interrupt('interrupted'); });
    this.listen(this.window, 'pagehide', () => this.interrupt('interrupted'));
    this.listen(this.window, 'offline', () => this.interrupt('interrupted'));
    this.listen(this.mediaDevices, 'devicechange', () => this.interrupt('device_ended'));
  }

  private listen(target: EventTarget | null, event: string, listener: () => void): void {
    if (!target) return;
    target.addEventListener(event, listener);
    this.lifecycle.push(() => target.removeEventListener(event, listener));
  }
  private active(): boolean { return [this.status.camera.state, this.status.microphone.state].some(state => state === 'on' || state === 'requesting'); }
  protected interrupt(code: MediaProblem): void {
    if (!this.active()) return;
    const camera = this.status.camera.state === 'on' || this.status.camera.state === 'requesting';
    const microphone = this.status.microphone.state === 'on' || this.status.microphone.state === 'requesting';
    const cleanup = this.stopAll();
    const cameraEpoch = this.cameraGeneration, audioEpoch = this.audioGeneration;
    if (camera) this.device('camera', { state: 'error', problem: code });
    if (microphone) this.device('microphone', { state: 'error', problem: code });
    void cleanup.catch(() => {
      if (camera && cameraEpoch === this.cameraGeneration) this.device('camera', { state: 'error', problem: 'cleanup_failed' });
      if (microphone && audioEpoch === this.audioGeneration) this.device('microphone', { state: 'error', problem: 'cleanup_failed' });
    });
  }
  private available(): MediaDevices {
    if (this.disposed) throw new MediaCaptureError('interrupted');
    if (!(this.driver.secureContext ?? this.window?.isSecureContext ?? false)) throw new MediaCaptureError('insecure_context');
    if (!this.mediaDevices?.getUserMedia || !this.document) throw new MediaCaptureError('unsupported');
    if (this.document.hidden || this.window?.navigator.onLine === false) throw new MediaCaptureError('interrupted');
    return this.mediaDevices;
  }
  private watch(stream: MediaStream, device: 'camera' | 'microphone', generation: number): void {
    for (const track of stream.getTracks()) {
      const ended = () => {
        if (device === 'camera' ? generation === this.cameraGeneration && stream === this.cameraStream
          : generation === this.audioGeneration && stream === this.microphoneStream) this.interrupt('device_ended');
      };
      track.addEventListener('ended', ended); this.trackListeners.set(track, ended);
    }
  }
  private release(stream: MediaStream | null): void {
    const errors: unknown[] = [];
    for (const track of stream?.getTracks() ?? []) this.unreleasedTracks.add(track);
    for (const track of [...this.unreleasedTracks]) {
      const ended = this.trackListeners.get(track);
      if (ended) { try { track.removeEventListener('ended', ended); this.trackListeners.delete(track); } catch (error) { errors.push(error); } }
      try { track.stop(); if (!this.trackListeners.has(track)) this.unreleasedTracks.delete(track); } catch (error) { errors.push(error); }
    }
    if (errors.length) throw new MediaCaptureError('cleanup_failed');
  }
  private failed(device: 'camera' | 'microphone', code: MediaProblem): void {
    this.device(device, { state: code === 'permission_denied' ? 'denied' : code === 'device_missing' ? 'missing' : 'error',
      permission: code === 'permission_denied' ? 'denied' : this.status[device].permission, problem: code });
  }
  private startAllowed(): void {
    if (this.disposed) throw new MediaCaptureError('interrupted');
    if (this.allStopPromise || this.cameraStopPromise || this.microphoneStopPromise || this.unreleasedTracks.size
      || this.unclosedContexts.size || this.undisconnectedNodes.size || this.unclosedPorts.size) throw new MediaCaptureError('cleanup_failed');
  }

  override async listCameras(): Promise<CameraOption[]> {
    if (this.status.camera.permission !== 'granted' || !this.mediaDevices?.enumerateDevices || this.disposed) return [];
    const cameras = await this.mediaDevices.enumerateDevices();
    if (this.disposed || this.status.camera.permission !== 'granted') return [];
    return cameras.filter(device => device.kind === 'videoinput' && device.deviceId.length > 0 && device.deviceId.length <= 512)
      .slice(0, 16).map((device, index) => ({ deviceId: device.deviceId,
        label: device.label.replace(/[\u0000-\u001f\u007f-\u009f]/g, '').slice(0, 80) || `摄像头 ${index + 1}` }));
  }
  async startCamera(facing: CameraFacing = 'user', deviceId?: string): Promise<void> {
    this.startAllowed();
    if ((facing !== 'user' && facing !== 'environment') || (deviceId !== undefined
      && (!deviceId.length || deviceId.length > 512 || /[\u0000-\u001f\u007f-\u009f]/.test(deviceId)))) throw new MediaCaptureError('device_missing');
    if (this.status.camera.state === 'on') return;
    if (this.status.camera.state === 'requesting') throw new MediaCaptureError('capture_failed');
    const generation = ++this.cameraGeneration;
    this.device('camera', { state: 'requesting', problem: null });
    let acquired: MediaStream | null = null;
    try {
      if (generation !== this.cameraGeneration || this.disposed) throw new MediaCaptureError('interrupted');
      acquired = await this.available().getUserMedia({ audio: false,
        video: { ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: facing } }),
          width: { ideal: this.config.maxWidth }, height: { ideal: this.config.maxHeight } } });
      if (generation !== this.cameraGeneration || this.disposed) { this.release(acquired); acquired = null; throw new MediaCaptureError('interrupted'); }
      if (!acquired.getVideoTracks().length) throw new MediaCaptureError('device_missing');
      this.cameraStream = acquired; this.watch(acquired, 'camera', generation);
      const video = this.document!.createElement('video');
      video.muted = true; video.playsInline = true; video.autoplay = true; video.srcObject = acquired;
      this.captureVideo = video; this.canvas = this.document!.createElement('canvas');
      this.attachPreview();
      await video.play();
      if (generation !== this.cameraGeneration || this.disposed) throw new MediaCaptureError('interrupted');
      this.device('camera', { state: 'on', permission: 'granted', problem: null });
      if (generation !== this.cameraGeneration || this.disposed) throw new MediaCaptureError('interrupted');
      this.frameTimer = setInterval(() => { void this.frame(generation); }, 1000 / this.config.framesPerSecond);
    } catch (error) {
      const code = problem(error);
      if (generation === this.cameraGeneration) {
        const managed = acquired === this.cameraStream;
        try { await this.stopCamera(); } catch { if (this.cameraGeneration === generation + 1) this.failed('camera', 'cleanup_failed'); throw new MediaCaptureError('cleanup_failed'); }
        if (acquired && !managed) this.release(acquired);
        if (this.cameraGeneration === generation + 1) this.failed('camera', code);
      }
      throw new MediaCaptureError(code);
    }
  }
  private async frame(generation: number): Promise<void> {
    if (!this.videoListeners.size || this.encodingToken || generation !== this.cameraGeneration || !this.captureVideo || !this.canvas || this.captureVideo.readyState < 2) return;
    const token = {}, video = this.captureVideo, canvas = this.canvas;
    this.encodingToken = token;
    try {
      const image = await encodeVideoFrame(video, canvas, this.config.maxFrameBytes, this.config.maxWidth, this.config.maxHeight);
      if (generation !== this.cameraGeneration || this.disposed) return;
      const frame = { bytes: image.bytes, mime: image.mimeType, width: image.width, height: image.height,
        sequence: ++this.videoSequence, timestamp: Date.now() };
      this.emitVideo(frame);
    } catch {
      if (generation === this.cameraGeneration) this.interrupt('encoding_failed');
    } finally { if (this.encodingToken === token) this.encodingToken = null; }
  }
  private attachPreview(): void {
    if (!this.previewVideo) return;
    if (this.previewVideo.srcObject !== this.cameraStream) this.previewVideo.srcObject = this.cameraStream;
    this.previewVideo.muted = true; this.previewVideo.playsInline = true;
    if (this.cameraStream) {
      const generation = this.cameraGeneration, stream = this.cameraStream, video = this.previewVideo;
      void video.play().catch(() => {
        if (generation === this.cameraGeneration && stream === this.cameraStream && video === this.previewVideo) this.interrupt('capture_failed');
      });
    }
  }
  bindPreview(target: unknown | null): void {
    if (this.previewVideo) { this.previewVideo.pause(); this.previewVideo.srcObject = null; }
    this.previewVideo = target && typeof (target as HTMLVideoElement).play === 'function' ? target as HTMLVideoElement : null;
    this.preview(Boolean(this.previewVideo)); this.attachPreview();
  }
  previewReady(): void { this.attachPreview(); }
  previewError(_error: unknown): void { this.interrupt('capture_failed'); }
  stopCamera(): Promise<void> {
    ++this.cameraGeneration;
    this.encodingToken = null;
    if (this.frameTimer !== null) { clearInterval(this.frameTimer); this.frameTimer = null; }
    if (this.cameraStopPromise) return this.cameraStopPromise;
    const pending = Promise.resolve().then(() => this.cleanupCamera());
    this.cameraStopPromise = pending;
    void pending.then(() => { if (this.cameraStopPromise === pending) this.cameraStopPromise = null; },
      () => { if (this.cameraStopPromise === pending) this.cameraStopPromise = null; });
    return pending;
  }
  private async cleanupCamera(): Promise<void> {
    const terminal = this.status.camera;
    const stream = this.cameraStream; this.cameraStream = null;
    const errors: unknown[] = [];
    for (const video of [this.captureVideo, this.previewVideo]) {
      try { video?.pause(); } catch (error) { errors.push(error); }
      try { if (video) { video.srcObject = null; video.removeAttribute('src'); } } catch (error) { errors.push(error); }
    }
    this.captureVideo = null;
    try { if (this.canvas) { this.canvas.width = 0; this.canvas.height = 0; } } catch (error) { errors.push(error); }
    this.canvas = null;
    try { this.release(stream); } catch (error) { errors.push(error); }
    this.device('camera', errors.length ? { state: 'error', problem: 'cleanup_failed' }
      : terminal.problem && terminal.problem !== 'cleanup_failed' ? terminal : { state: 'off', problem: null });
    if (errors.length) throw new MediaCaptureError('cleanup_failed');
  }

  async startMicrophone(): Promise<void> {
    this.startAllowed();
    if (this.status.microphone.state === 'on') return;
    if (this.status.microphone.state === 'requesting') throw new MediaCaptureError('capture_failed');
    const generation = ++this.audioGeneration;
    this.device('microphone', { state: 'requesting', problem: null });
    let acquired: MediaStream | null = null;
    try {
      if (generation !== this.audioGeneration || this.disposed) throw new MediaCaptureError('interrupted');
      const devices = this.available();
      // Creation and resume run in the explicit Start gesture, before the OS prompt awaits.
      const context = this.driver.createAudioContext ? this.driver.createAudioContext() : new AudioContext({ sampleRate: 16000 });
      this.context = context;
      const resumed = context.resume().then(() => null, () => new MediaCaptureError('capture_failed'));
      acquired = await devices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true }, video: false });
      if (generation !== this.audioGeneration || this.disposed) { this.release(acquired); acquired = null; throw new MediaCaptureError('interrupted'); }
      if (!acquired.getAudioTracks().length) throw new MediaCaptureError('device_missing');
      this.microphoneStream = acquired; this.watch(acquired, 'microphone', generation);
      const frames = Math.round(context.sampleRate * this.config.audioChunkMs / 1000);
      if (!Number.isInteger(context.sampleRate) || 44 + frames * 2 > this.config.maxAudioBytes) throw new MediaCaptureError('unsupported');
      if (!context.audioWorklet) throw new MediaCaptureError('unsupported');
      await context.audioWorklet.addModule(new URL('../processors/pcm-worklet.js', import.meta.url).href);
      if (generation !== this.audioGeneration || this.disposed) throw new MediaCaptureError('interrupted');
      const options: AudioWorkletNodeOptions = { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
        processorOptions: { chunkMs: this.config.audioChunkMs, maxBytes: this.config.maxAudioBytes } };
      const node = this.driver.createWorklet ? this.driver.createWorklet(context, options) : new AudioWorkletNode(context, 'soulcompanion-pcm', options);
      this.worklet = node;
      node.onprocessorerror = () => { if (generation === this.audioGeneration && !this.disposed) this.interrupt('capture_failed'); };
      node.port.onmessage = event => {
        if (generation !== this.audioGeneration || this.disposed) return;
        try {
          if (event.data?.type === 'overflow') { this.interrupt('oversize'); return; }
          if (event.data?.type !== 'pcm' || !(event.data.samples instanceof ArrayBuffer) || event.data.sampleRate !== context.sampleRate
            || event.data.samples.byteLength !== frames * 2) throw new MediaCaptureError('encoding_failed');
          const samples = new Int16Array(event.data.samples);
          try {
            let sum = 0;
            for (const value of samples) sum += (value / 32768) ** 2;
            this.emitLevel({ level: Math.max(0, Math.min(1, Math.sqrt(sum / samples.length))), timestamp: Date.now() });
            if (generation !== this.audioGeneration || this.disposed) return;
            const bytes = this.audioListeners.size ? encodeMonoWav(samples, context.sampleRate, this.config.maxAudioBytes) : null;
            if (bytes && generation === this.audioGeneration && !this.disposed) this.emitAudio({ bytes, mime: 'audio/wav', channels: 1,
              sampleRate: context.sampleRate, durationMs: frames / context.sampleRate * 1000, sequence: ++this.audioSequence, timestamp: Date.now() });
          } finally { samples.fill(0); }
          if (generation === this.audioGeneration && !this.disposed) node.port.postMessage({ type: 'ack' });
        } catch { this.interrupt('encoding_failed'); }
      };
      this.source = context.createMediaStreamSource(acquired); this.mute = context.createGain(); this.mute.gain.value = 0;
      this.source.connect(node); node.connect(this.mute); this.mute.connect(context.destination);
      const resumeError = await resumed;
      if (resumeError) throw resumeError;
      if (generation !== this.audioGeneration || this.disposed) throw new MediaCaptureError('interrupted');
      this.device('microphone', { state: 'on', permission: 'granted', problem: null });
      if (generation !== this.audioGeneration || this.disposed) throw new MediaCaptureError('interrupted');
    } catch (error) {
      const code = problem(error);
      if (generation === this.audioGeneration) {
        const managed = acquired === this.microphoneStream;
        try { await this.stopMicrophone(); } catch { if (this.audioGeneration === generation + 1) this.failed('microphone', 'cleanup_failed'); throw new MediaCaptureError('cleanup_failed'); }
        if (acquired && !managed) this.release(acquired);
        if (this.audioGeneration === generation + 1) this.failed('microphone', code);
      }
      throw new MediaCaptureError(code);
    }
  }
  stopMicrophone(): Promise<void> {
    ++this.audioGeneration;
    this.emitLevel({ level: 0, timestamp: Date.now() });
    if (this.microphoneStopPromise) return this.microphoneStopPromise;
    const pending = Promise.resolve().then(() => this.cleanupMicrophone());
    this.microphoneStopPromise = pending;
    void pending.then(() => { if (this.microphoneStopPromise === pending) this.microphoneStopPromise = null; },
      () => { if (this.microphoneStopPromise === pending) this.microphoneStopPromise = null; });
    return pending;
  }
  private async cleanupMicrophone(): Promise<void> {
    const terminal = this.status.microphone;
    const errors: unknown[] = [];
    const stream = this.microphoneStream; this.microphoneStream = null;
    const context = this.context; this.context = null;
    if (context) this.unclosedContexts.add(context);
    if (this.worklet) {
      this.worklet.port.onmessage = null; this.worklet.onprocessorerror = null;
      this.unclosedPorts.add(this.worklet.port);
      try { this.worklet.port.postMessage({ type: 'stop' }); } catch (error) { errors.push(error); }
    }
    for (const node of [this.source, this.worklet, this.mute]) { if (node) this.undisconnectedNodes.add(node); }
    for (const port of [...this.unclosedPorts]) { try { port.close(); this.unclosedPorts.delete(port); } catch (error) { errors.push(error); } }
    for (const node of [...this.undisconnectedNodes]) { try { node.disconnect(); this.undisconnectedNodes.delete(node); } catch (error) { errors.push(error); } }
    this.source = null; this.worklet = null; this.mute = null;
    try { this.release(stream); } catch (error) { errors.push(error); }
    for (const owned of [...this.unclosedContexts]) {
      try { if (owned.state !== 'closed') await owned.close(); this.unclosedContexts.delete(owned); } catch (error) { errors.push(error); }
    }
    this.device('microphone', errors.length ? { state: 'error', problem: 'cleanup_failed' }
      : terminal.problem && terminal.problem !== 'cleanup_failed' ? terminal : { state: 'off', problem: null });
    if (errors.length) throw new MediaCaptureError('cleanup_failed');
  }
  stopAll(): Promise<void> {
    if (this.allStopPromise) return this.allStopPromise;
    const pending = Promise.allSettled([this.stopCamera(), this.stopMicrophone()]).then(results => {
      if (results.some(result => result.status === 'rejected')) throw new MediaCaptureError('cleanup_failed');
    });
    this.allStopPromise = pending;
    void pending.then(() => { if (this.allStopPromise === pending) this.allStopPromise = null; },
      () => { if (this.allStopPromise === pending) this.allStopPromise = null; });
    return pending;
  }
  async dispose(): Promise<void> {
    this.disposed = true;
    const errors: unknown[] = [];
    for (const remove of [...this.lifecycle]) {
      try { remove(); this.lifecycle.splice(this.lifecycle.indexOf(remove), 1); } catch (error) { errors.push(error); }
    }
    try { await this.stopAll(); } catch (error) { errors.push(error); }
    try { this.bindPreview(null); } catch (error) { errors.push(error); }
    this.clearSubscribers();
    if (errors.length) throw new MediaCaptureError('cleanup_failed');
  }
}
