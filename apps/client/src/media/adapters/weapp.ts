import Taro from '@tarojs/taro';
import { CaptureAdapterBase } from './base';
import { MediaCaptureError, type CameraFacing, type CaptureConfig, type MediaProblem } from '../types';
import { downsampleRgba } from '../processors/image';
import { encodedImageMime } from '../processors/image-encoding';

type Device = 'camera' | 'microphone';
type Callback = (...args: never[]) => void;
export type MiniRecorder = Taro.RecorderManager & Partial<Record<
  'offStart' | 'offFrameRecorded' | 'offError' | 'offStop' | 'offInterruptionBegin' | 'offPause', (callback: Callback) => void>>;
export interface MiniMediaDriver {
  createCameraContext(id: string): Taro.CameraContext;
  getRecorderManager(): MiniRecorder;
  fileSystem(): Taro.FileSystemManager;
  putImage(options: Taro.canvasPutImageData.Option): Promise<unknown>;
  encodeImage(options: Taro.canvasToTempFilePath.Option): Promise<{ tempFilePath: string }>;
  onHide(listener: () => void): () => void;
  onNetwork(listener: (online: boolean) => void): () => void;
}

const defaultDriver: MiniMediaDriver = {
  createCameraContext: id => Taro.createCameraContext(id), getRecorderManager: () => Taro.getRecorderManager(),
  fileSystem: () => Taro.getFileSystemManager(),
  putImage: options => Taro.canvasPutImageData(options), encodeImage: options => Taro.canvasToTempFilePath(options),
  onHide(listener) { Taro.onAppHide(listener); return () => Taro.offAppHide(listener); },
  onNetwork(listener) {
    const changed = (result: Taro.onNetworkStatusChange.CallbackResult) => listener(result.isConnected);
    Taro.onNetworkStatusChange(changed); return () => Taro.offNetworkStatusChange(changed);
  },
};

interface RecorderLease {
  owner: WeAppMediaCaptureAdapter;
  epoch: number;
  recorder: MiniRecorder;
  stopped: Promise<void>;
  finish(): void;
  finished: boolean;
  startCalled: boolean;
  startSeen: boolean;
  cancelRequested: boolean;
  handlers: {
    start(): void; frame(value: Taro.RecorderManager.OnFrameRecordedCallbackResult): void;
    error(error: unknown): void; stop(value: Taro.RecorderManager.OnStopCallbackResult): void; interrupted(): void;
  };
}
interface RecorderHub {
  lease: RecorderLease | null;
  installed: boolean;
  failed: boolean;
  removals: (() => void)[];
  fullyRemovable: boolean;
  users: Set<WeAppMediaCaptureAdapter>;
  orphanStop: ((value: Taro.RecorderManager.OnStopCallbackResult) => void) | null;
  orphanStopping: { stopped: Promise<void>; finish(): void } | null;
}
const recorderOwners = new WeakMap<MiniRecorder, RecorderHub>();

/** One stable dispatcher per SDK singleton. A new lease waits for the prior onStop barrier. */
function recorderHub(recorder: MiniRecorder): RecorderHub {
  let hub = recorderOwners.get(recorder);
  if (!hub) {
    hub = { lease: null, installed: false, failed: false, removals: [], fullyRemovable: true, users: new Set(), orphanStop: null, orphanStopping: null };
    recorderOwners.set(recorder, hub);
  }
  if (hub.failed) throw new MediaCaptureError('unsupported');
  if (hub.installed) return hub;
  const current = hub;
  const source = recorder as unknown as Record<string, ((callback: Callback) => void) | undefined>;
  const register = (on: string, off: string, callback: Callback) => {
    if (typeof source[on] !== 'function') throw new MediaCaptureError('unsupported');
    source[on]!.call(recorder, callback);
    if (typeof source[off] === 'function') current.removals.push(() => source[off]!.call(recorder, callback));
    else current.fullyRemovable = false;
  };
  try {
    register('onStart', 'offStart', (() => {
      if (current.lease) { current.lease.handlers.start(); return; }
      // A late SDK grant still belongs to this dispatcher. Do not leave it recording.
      if (!current.orphanStopping) {
        let finish!: () => void;
        current.orphanStopping = { stopped: new Promise<void>(resolve => { finish = resolve; }), finish: () => finish() };
      }
      try { recorder.stop(); } catch { current.failed = true; }
    }) as Callback);
    register('onFrameRecorded', 'offFrameRecorded', ((frame: Taro.RecorderManager.OnFrameRecordedCallbackResult) => current.lease?.handlers.frame(frame)) as Callback);
    register('onError', 'offError', ((error: unknown) => current.lease?.handlers.error(error)) as Callback);
    register('onStop', 'offStop', ((value: Taro.RecorderManager.OnStopCallbackResult) => {
      const lease = current.lease;
      if (lease) lease.handlers.stop(value); else {
        const orphan = current.orphanStopping; current.orphanStopping = null; orphan?.finish();
        current.orphanStop?.(value);
      }
    }) as Callback);
    register('onInterruptionBegin', 'offInterruptionBegin', (() => current.lease?.handlers.interrupted()) as Callback);
    register('onPause', 'offPause', (() => current.lease?.handlers.interrupted()) as Callback);
    current.installed = true;
  } catch { current.failed = true; throw new MediaCaptureError('unsupported'); }
  return current;
}

function miniProblem(error: unknown): MediaProblem {
  if (error instanceof MediaCaptureError) return error.code;
  const value = error && typeof error === 'object' && 'errMsg' in error ? String(error.errMsg).toLowerCase() : '';
  if (/auth deny|denied|permission|authorize/.test(value)) return 'permission_denied';
  if (/not found|no device/.test(value)) return 'device_missing';
  if (/already running|busy|occupied/.test(value)) return 'device_in_use';
  return 'capture_failed';
}
function deadline<T>(pending: Promise<T>, ms = 5000): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new MediaCaptureError('cleanup_failed')), ms);
    pending.then(value => { clearTimeout(timer); resolve(value); }, error => { clearTimeout(timer); reject(error); });
  });
}

/** MP3 chunks are sequential fragments. Inspect a real MPEG frame header for its rate. */
export function mp3SampleRate(buffer: ArrayBuffer): number | null {
  const bytes = new Uint8Array(buffer);
  for (let index = 0; index + 3 < bytes.length; index++) {
    if (bytes[index] !== 0xff || (bytes[index + 1] & 0xe0) !== 0xe0) continue;
    const version = (bytes[index + 1] >> 3) & 3, layer = (bytes[index + 1] >> 1) & 3;
    const bitrate = bytes[index + 2] >> 4, rate = (bytes[index + 2] >> 2) & 3;
    if (version === 1 || layer !== 1 || bitrate === 0 || bitrate === 15 || rate === 3 || (bytes[index + 3] >> 6) !== 3) continue;
    return [44100, 48000, 32000][rate] / (version === 3 ? 1 : version === 2 ? 2 : 4);
  }
  return null;
}

/** WeChat-only platform boundary. No camera component exists before explicit Start. */
export class WeAppMediaCaptureAdapter extends CaptureAdapterBase {
  private cameraEpoch = 0;
  private audioEpoch = 0;
  private previewTarget: { cameraId: string; canvasId: string } | null = null;
  private cameraRequest: { epoch: number; resolve(): void; reject(error: unknown): void } | null = null;
  private cameraListener: Taro.CameraFrameListener | null = null;
  private readonly ownedListeners = new Set<Taro.CameraFrameListener>();
  private readonly ownedTemps = new Set<string>();
  private readonly cameraTemps = new Set<string>();
  private readonly audioTemps = new Set<string>();
  private readonly tempDeletes = new Map<string, Promise<void>>();
  private readonly recorders = new Set<MiniRecorder>();
  private encodingToken: object | null = null;
  private readonly encodingJobs = new Set<Promise<void>>();
  private lastFrameAt = 0;
  private audioRequest: { epoch: number; resolve(): void; reject(error: unknown): void } | null = null;
  private lease: RecorderLease | null = null;
  private audioRate: number | null = null;
  private cameraStop: Promise<void> | null = null;
  private audioStop: Promise<void> | null = null;
  private allStop: Promise<void> | null = null;
  private readonly removals: (() => void)[] = [];

  constructor(config: Partial<CaptureConfig> = {}, private readonly driver: MiniMediaDriver = defaultDriver) {
    super(config);
    this.removals.push(driver.onHide(() => this.interrupt('interrupted')),
      driver.onNetwork(online => { if (!online) this.interrupt('interrupted'); }));
  }
  private fail(device: Device, code: MediaProblem): void {
    this.device(device, { state: code === 'permission_denied' ? 'denied' : code === 'device_missing' ? 'missing' : 'error',
      permission: code === 'permission_denied' ? 'denied' : this.status[device].permission, problem: code });
  }
  private interrupt(code: MediaProblem): void {
    const camera = this.status.camera.state === 'on' || this.status.camera.state === 'requesting';
    const microphone = this.status.microphone.state === 'on' || this.status.microphone.state === 'requesting';
    if (!camera && !microphone) return;
    const cleanup = this.stopAll(), cameraEpoch = this.cameraEpoch, audioEpoch = this.audioEpoch;
    if (camera) this.fail('camera', code); if (microphone) this.fail('microphone', code);
    void cleanup.catch(() => {
      if (cameraEpoch === this.cameraEpoch && camera) this.fail('camera', 'cleanup_failed');
      if (audioEpoch === this.audioEpoch && microphone) this.fail('microphone', 'cleanup_failed');
    });
  }
  async startCamera(facing: CameraFacing = 'user', deviceId?: string): Promise<void> {
    if (this.status.camera.state === 'on') return;
    // Microphone can already be active; only retired camera resources block this operation.
    if (this.disposed) throw new MediaCaptureError('interrupted');
    if (this.cameraStop || this.allStop || this.ownedListeners.size || this.encodingJobs.size || this.ownedTemps.size) throw new MediaCaptureError('cleanup_failed');
    if (deviceId || (facing !== 'user' && facing !== 'environment')) throw new MediaCaptureError('unsupported');
    if (this.cameraRequest) throw new MediaCaptureError('capture_failed');
    const epoch = ++this.cameraEpoch;
    const requested = new Promise<void>((resolve, reject) => { this.cameraRequest = { epoch, resolve, reject }; });
    this.device('camera', { state: 'requesting', problem: null });
    return requested;
  }
  bindPreview(target: unknown | null): void {
    const value = target as { cameraId?: unknown; canvasId?: unknown } | null;
    this.previewTarget = value && typeof value.cameraId === 'string' && typeof value.canvasId === 'string'
      ? { cameraId: value.cameraId, canvasId: value.canvasId } : null;
    this.preview(Boolean(this.previewTarget));
  }
  previewReady(): void {
    const request = this.cameraRequest, target = this.previewTarget;
    if (!request || !target || request.epoch !== this.cameraEpoch || this.disposed || this.cameraListener) return;
    try {
      const context = this.driver.createCameraContext(target.cameraId);
      const listener = context.onCameraFrame(frame => this.cameraFrame(frame, request.epoch, target.canvasId));
      this.cameraListener = listener; this.ownedListeners.add(listener);
      listener.start({ success: () => {
        if (request.epoch !== this.cameraEpoch || this.disposed) {
          // A late native listener start must be stopped even after its first Stop.
          this.ownedListeners.add(listener);
          void this.stopListener(listener).catch(() => {
            if (this.cameraEpoch === request.epoch + 1) this.fail('camera', 'cleanup_failed');
          });
          return;
        }
        this.cameraRequest = null; this.device('camera', { state: 'on', permission: 'granted', problem: null }); request.resolve();
      }, fail: error => {
        if (request.epoch !== this.cameraEpoch) return;
        this.cameraRequest = null; request.reject(new MediaCaptureError(miniProblem(error))); this.interrupt(miniProblem(error));
      } });
    } catch (error) { this.previewError(error); }
  }
  previewError(error: unknown): void {
    const request = this.cameraRequest; this.cameraRequest = null;
    request?.reject(new MediaCaptureError(miniProblem(error)));
    this.interrupt(miniProblem(error));
  }
  private cameraFrame(frame: Taro.CameraContext.OnCameraFrameCallbackResult, epoch: number, canvasId: string): void {
    const now = Date.now();
    if (epoch !== this.cameraEpoch || this.disposed || this.status.camera.state !== 'on' || !this.videoListeners.size
      || this.encodingToken || now - this.lastFrameAt < 1000 / this.config.framesPerSecond) return;
    this.lastFrameAt = now;
    const token = {}; this.encodingToken = token;
    const job = this.encodeFrame(frame, epoch, canvasId).finally(() => {
      if (this.encodingToken === token) this.encodingToken = null; this.encodingJobs.delete(job);
    });
    this.encodingJobs.add(job);
    void job.catch(() => { if (epoch === this.cameraEpoch) this.interrupt('encoding_failed'); });
  }
  private async encodeFrame(frame: Taro.CameraContext.OnCameraFrameCallbackResult, epoch: number, canvasId: string): Promise<void> {
    const small = downsampleRgba(frame.data, frame.width, frame.height, this.config.maxWidth, this.config.maxHeight);
    await this.driver.putImage({ canvasId, data: small.data, width: small.width, height: small.height, x: 0, y: 0 });
    if (epoch !== this.cameraEpoch || this.disposed) { small.data.fill(0); return; }
    const encoded = await this.driver.encodeImage({ canvasId, fileType: 'jpg', quality: 0.6,
      x: 0, y: 0, width: small.width, height: small.height, destWidth: small.width, destHeight: small.height });
    small.data.fill(0);
    this.ownedTemps.add(encoded.tempFilePath); this.cameraTemps.add(encoded.tempFilePath);
    try {
      if (epoch !== this.cameraEpoch || this.disposed) return;
      const bytes = await new Promise<ArrayBuffer>((resolve, reject) => this.driver.fileSystem().readFile({ filePath: encoded.tempFilePath,
        success: result => typeof result.data === 'string' ? reject(new MediaCaptureError('encoding_failed')) : resolve(result.data), fail: reject }));
      if (bytes.byteLength > this.config.maxFrameBytes || !bytes.byteLength) throw new MediaCaptureError('oversize');
      if (encodedImageMime(bytes) !== 'image/jpeg') throw new MediaCaptureError('encoding_failed');
      if (epoch === this.cameraEpoch && !this.disposed) this.emitVideo({ bytes, mime: 'image/jpeg', width: small.width, height: small.height,
        sequence: ++this.videoSequence, timestamp: Date.now() });
    } finally { await this.deleteTemp(encoded.tempFilePath); }
  }
  private async deleteTemp(path: string): Promise<void> {
    if (!this.ownedTemps.has(path)) return;
    if (this.tempDeletes.has(path)) return this.tempDeletes.get(path)!;
    const pending = new Promise<void>((resolve, reject) => this.driver.fileSystem().unlink({ filePath: path,
      success: () => { this.ownedTemps.delete(path); this.cameraTemps.delete(path); this.audioTemps.delete(path); resolve(); }, fail: () => reject(new MediaCaptureError('cleanup_failed')) }));
    this.tempDeletes.set(path, pending);
    void pending.then(() => { if (this.tempDeletes.get(path) === pending) this.tempDeletes.delete(path); },
      () => { if (this.tempDeletes.get(path) === pending) this.tempDeletes.delete(path); });
    return pending;
  }
  private stopListener(listener: Taro.CameraFrameListener): Promise<void> {
    return deadline(new Promise<void>((resolve, reject) => {
      listener.stop({ success: () => { this.ownedListeners.delete(listener); resolve(); }, fail: () => reject(new MediaCaptureError('cleanup_failed')) });
    }));
  }
  stopCamera(): Promise<void> {
    ++this.cameraEpoch; this.encodingToken = null;
    this.cameraRequest?.reject(new MediaCaptureError('interrupted')); this.cameraRequest = null;
    if (this.cameraStop) return this.cameraStop;
    const pending = Promise.resolve().then(async () => {
      const terminal = this.status.camera;
      this.cameraListener = null; this.device('camera', terminal.problem && terminal.problem !== 'cleanup_failed' ? terminal : { state: 'off', problem: null });
      const results = await Promise.allSettled([...this.ownedListeners].map(listener => this.stopListener(listener)));
      const drained = await Promise.allSettled([...this.encodingJobs].map(job => deadline(job)));
      // A failed encoding cleanup remains owned for the next explicit Stop.
      if (this.ownedListeners.size || this.encodingJobs.size || drained.some(result => result.status === 'rejected' && this.cameraTemps.size > 0)) {
        this.fail('camera', 'cleanup_failed'); throw new MediaCaptureError('cleanup_failed');
      }
      const deletes = await Promise.allSettled([...this.cameraTemps].map(path => this.deleteTemp(path)));
      if (results.some(result => result.status === 'rejected') || deletes.some(result => result.status === 'rejected')) {
        this.fail('camera', 'cleanup_failed'); throw new MediaCaptureError('cleanup_failed');
      }
    });
    this.cameraStop = pending;
    void pending.then(() => { if (this.cameraStop === pending) this.cameraStop = null; }, () => { if (this.cameraStop === pending) this.cameraStop = null; });
    return pending;
  }

  async startMicrophone(): Promise<void> {
    if (this.status.microphone.state === 'on') return;
    if (this.disposed) throw new MediaCaptureError('interrupted');
    if (this.audioStop || this.allStop || this.lease || this.ownedTemps.size) throw new MediaCaptureError('cleanup_failed');
    const recorder = this.driver.getRecorderManager();
    const hub = recorderHub(recorder);
    if (hub.lease || hub.orphanStopping) throw new MediaCaptureError('cleanup_failed');
    hub.users.add(this); this.recorders.add(recorder);
    const epoch = ++this.audioEpoch;
    let finish!: () => void;
    const lease: RecorderLease = { owner: this, epoch, recorder, stopped: new Promise<void>(resolve => { finish = resolve; }),
      finish: () => finish(), finished: false, startCalled: false, startSeen: false, cancelRequested: false, handlers: {
        start: () => {}, frame: () => {}, error: () => {}, stop: () => {}, interrupted: () => {},
      } };
    this.lease = lease; hub.lease = lease; this.audioRate = null;
    const requested = new Promise<void>((resolve, reject) => { this.audioRequest = { epoch, resolve, reject }; });
    const current = () => this.lease === lease && epoch === this.audioEpoch && !this.disposed;
    const interrupted = () => { if (current()) this.interrupt('interrupted'); };
    try {
      lease.handlers.start = () => {
        lease.startSeen = true;
        if (!current()) { if (!lease.finished) recorder.stop(); return; }
        const request = this.audioRequest; this.audioRequest = null;
        this.device('microphone', { state: 'on', permission: 'granted', problem: null });
        this.emitLevel({ level: null, timestamp: Date.now() }); request?.resolve();
      };
      lease.handlers.frame = (frame: Taro.RecorderManager.OnFrameRecordedCallbackResult) => {
        if (!current() || this.status.microphone.state !== 'on') return;
        if (!frame.frameBuffer.byteLength || frame.frameBuffer.byteLength > this.config.maxAudioBytes) { this.interrupt('oversize'); return; }
        this.emitLevel({ level: null, timestamp: Date.now() });
        if (!this.audioListeners.size) return;
        this.audioRate ??= mp3SampleRate(frame.frameBuffer);
        if (!this.audioRate) { this.interrupt('encoding_failed'); return; }
        this.emitAudio({ bytes: frame.frameBuffer, mime: 'audio/mpeg', sampleRate: this.audioRate, channels: 1,
          durationMs: null, sequence: ++this.audioSequence, timestamp: Date.now() });
      };
      lease.handlers.error = (error: unknown) => {
        if (current()) {
          this.audioRequest?.reject(new MediaCaptureError(miniProblem(error))); this.audioRequest = null;
          if (this.status.microphone.state === 'on') { this.interrupt(miniProblem(error)); return; }
          this.fail('microphone', miniProblem(error));
        }
        this.finishLease(lease);
      };
      lease.handlers.stop = (result: Taro.RecorderManager.OnStopCallbackResult) => {
        const wasCurrent = current();
        if (result.tempFilePath) { this.ownedTemps.add(result.tempFilePath); this.audioTemps.add(result.tempFilePath); }
        // stop() may report before a pending permission grant. Keep that lease until
        // late onStart is explicitly stopped, or onError confirms acquisition failed.
        if (!(lease.cancelRequested && lease.startCalled && !lease.startSeen)) this.finishLease(lease);
        if (wasCurrent) this.interrupt('device_ended');
        // The active Stop owns its one deletion attempt; failure remains retryable.
        if (result.tempFilePath && !this.audioStop) void this.deleteTemp(result.tempFilePath).catch(() => {
          if (epoch === this.audioEpoch) this.fail('microphone', 'cleanup_failed');
        });
      };
      lease.handlers.interrupted = interrupted;
      hub.orphanStop = result => {
        if (!result.tempFilePath) return;
        this.ownedTemps.add(result.tempFilePath); this.audioTemps.add(result.tempFilePath);
        void this.deleteTemp(result.tempFilePath).catch(() => {
          if (!this.disposed && this.lease === null) this.fail('microphone', 'cleanup_failed');
        });
      };
      this.device('microphone', { state: 'requesting', problem: null });
      if (current()) {
        lease.startCalled = true;
        recorder.start({ duration: 600000, format: 'mp3', frameSize: 8, sampleRate: 16000, numberOfChannels: 1, encodeBitRate: 32000 });
      } else this.finishLease(lease);
    } catch (error) {
      this.audioRequest?.reject(new MediaCaptureError(miniProblem(error))); this.audioRequest = null;
      this.finishLease(lease); this.fail('microphone', miniProblem(error));
    }
    return requested;
  }
  private finishLease(lease: RecorderLease): void {
    if (lease.finished) return;
    lease.finished = true;
    const owner = recorderOwners.get(lease.recorder);
    if (owner?.lease === lease) owner.lease = null;
    if (this.lease === lease) this.lease = null;
    lease.finish();
  }
  stopMicrophone(): Promise<void> {
    ++this.audioEpoch; this.emitLevel({ level: 0, timestamp: Date.now() });
    this.audioRequest?.reject(new MediaCaptureError('interrupted')); this.audioRequest = null;
    if (this.audioStop) return this.audioStop;
    const pending = Promise.resolve().then(async () => {
      const lease = this.lease;
      const terminal = this.status.microphone;
      this.device('microphone', terminal.problem && terminal.problem !== 'cleanup_failed' ? terminal : { state: 'off', problem: null });
      if (lease && !lease.finished) {
        lease.cancelRequested = true;
        if (lease.startCalled) lease.recorder.stop(); else this.finishLease(lease);
        await deadline(lease.stopped);
      }
      for (const recorder of this.recorders) {
        const orphan = recorderOwners.get(recorder)?.orphanStopping;
        if (orphan) await deadline(orphan.stopped);
      }
      const deletes = await Promise.allSettled([...this.audioTemps].map(path => this.deleteTemp(path)));
      if (deletes.some(result => result.status === 'rejected')) throw new MediaCaptureError('cleanup_failed');
    }).catch(error => { this.fail('microphone', 'cleanup_failed'); throw error; });
    this.audioStop = pending;
    void pending.then(() => { if (this.audioStop === pending) this.audioStop = null; }, () => { if (this.audioStop === pending) this.audioStop = null; });
    return pending;
  }
  stopAll(): Promise<void> {
    if (this.allStop) return this.allStop;
    const pending = Promise.allSettled([this.stopCamera(), this.stopMicrophone()]).then(results => {
      if (results.some(result => result.status === 'rejected')) throw new MediaCaptureError('cleanup_failed');
    });
    this.allStop = pending;
    void pending.then(() => { if (this.allStop === pending) this.allStop = null; }, () => { if (this.allStop === pending) this.allStop = null; });
    return pending;
  }
  async dispose(): Promise<void> {
    this.disposed = true;
    const errors: unknown[] = [];
    for (const remove of [...this.removals]) {
      try { remove(); this.removals.splice(this.removals.indexOf(remove), 1); } catch (error) { errors.push(error); }
    }
    try { await this.stopAll(); } catch (error) { errors.push(error); }
    this.bindPreview(null); this.clearSubscribers();
    for (const recorder of [...this.recorders]) {
      const hub = recorderOwners.get(recorder);
      // Keep dispatchers and ownership while terminal device cleanup is pending.
      if (hub?.lease?.owner === this || hub?.orphanStopping) continue;
      if (hub) {
        hub.users.delete(this);
        if (!hub.users.size && !hub.lease && hub.fullyRemovable) {
          for (const remove of [...hub.removals]) {
            try { remove(); hub.removals.splice(hub.removals.indexOf(remove), 1); } catch (error) { errors.push(error); }
          }
          if (hub.removals.length) continue;
          hub.installed = false; hub.orphanStop = null;
        }
      }
      this.recorders.delete(recorder);
    }
    if (errors.length) throw new MediaCaptureError('cleanup_failed');
  }
}
