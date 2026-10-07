import { describe, expect, it, vi } from 'vitest';
import { MediaSessionController } from '../src/media/MediaSessionController';
import { CloudSessionBridge } from '../src/cloud/session';
import { FakeAuthAdapter } from '../src/cloud/auth/fake';
import type { CloudApi, CloudSession } from '../src/cloud/types';
import { captureConfig, idleCaptureStatus, MediaCaptureError,
  type AudioChunk, type AudioInputLevel, type CameraFacing, type CaptureStatus, type MediaCaptureAdapter,
  type MediaProblem, type VideoFrame } from '../src/media/types';

class TestAdapter implements MediaCaptureAdapter {
  status = idleCaptureStatus();
  starts = { camera: 0, microphone: 0 };
  activeTracks = 0;
  stops = 0;
  generation = 0;
  facing: CameraFacing | undefined;
  cameraDeviceId: string | undefined;
  failure: MediaProblem | null = null;
  pendingCamera: (() => void) | null = null;
  deferCamera = false;
  cleanupFails = false;
  private statuses = new Set<(status: CaptureStatus) => void>();
  private videos = new Set<(frame: VideoFrame) => void>();
  private audios = new Set<(chunk: AudioChunk) => void>();
  private levels = new Set<(input: AudioInputLevel) => void>();
  async startCamera(facing?: CameraFacing, deviceId?: string) {
    this.starts.camera++;
    this.facing = facing;
    this.cameraDeviceId = deviceId;
    const generation = this.generation;
    this.status.camera.state = 'requesting';
    this.emitStatus();
    if (this.deferCamera) await new Promise<void>(resolve => { this.pendingCamera = resolve; });
    if (generation !== this.generation) return;
    if (this.failure) {
      this.status.camera = { state: this.failure === 'permission_denied' ? 'denied' : 'missing',
        permission: this.failure === 'permission_denied' ? 'denied' : 'unknown', problem: this.failure };
      this.emitStatus();
      throw new MediaCaptureError(this.failure);
    }
    this.activeTracks++;
    this.status.camera = { state: 'on', permission: 'granted', problem: null };
    this.emitStatus();
  }
  async startMicrophone() {
    this.starts.microphone++;
    this.activeTracks++;
    this.status.microphone = { state: 'on', permission: 'granted', problem: null };
    this.emitStatus();
  }
  async stopCamera() { this.status.camera.state = 'off'; this.emitStatus(); }
  async stopMicrophone() { this.status.microphone.state = 'off'; this.emitStatus(); }
  async stopAll() {
    this.generation++;
    this.stops++;
    this.activeTracks = 0;
    this.status.camera.state = 'off';
    this.status.microphone.state = 'off';
    this.emitStatus();
    if (this.cleanupFails) throw new Error('private platform error');
  }
  getStatus() { return this.status; }
  subscribeStatus(listener: (status: CaptureStatus) => void) {
    this.statuses.add(listener); return () => this.statuses.delete(listener);
  }
  subscribeVideoFrame(listener: (frame: VideoFrame) => void) {
    this.videos.add(listener); return () => this.videos.delete(listener);
  }
  subscribeAudioChunk(listener: (chunk: AudioChunk) => void) {
    this.audios.add(listener); return () => this.audios.delete(listener);
  }
  emitStatus() { for (const listener of this.statuses) listener(this.status); }
  emitVideo(frame: VideoFrame) { for (const listener of this.videos) listener(frame); }
  emitAudio(chunk: AudioChunk) { for (const listener of this.audios) listener(chunk); }
  subscribeAudioLevel(listener: (input: AudioInputLevel) => void) {
    this.levels.add(listener); return () => this.levels.delete(listener);
  }
  emitLevel(level: number | null) { for (const listener of this.levels) listener({ level, timestamp: Date.now() }); }
  async listCameras() { return []; }
  bindPreview() {}
  previewReady() {}
  previewError() {}
  async dispose() { await this.stopAll(); }
  subscriptions() { return this.statuses.size + this.videos.size + this.audios.size + this.levels.size; }
}

const selection = { camera: true, microphone: true, facing: 'user' as const };
const online = { source: 'real' as const, connection: 'online' as const, visible: true };
function setup(options?: { startTimeoutMs?: number }) {
  const adapter = new TestAdapter();
  const controller = new MediaSessionController(adapter, options);
  controller.setContext(online);
  return { adapter, controller };
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
function frame(sequence = 0): VideoFrame {
  return { bytes: new ArrayBuffer(16), mime: 'image/jpeg', width: 320, height: 240,
    sequence, timestamp: Date.now() };
}
function audio(sequence = 0): AudioChunk {
  return { bytes: new ArrayBuffer(128), mime: 'audio/wav', sampleRate: 16000,
    channels: 1, sequence, timestamp: Date.now(), durationMs: 1000 };
}

describe('explicit media session lifecycle', () => {
  it('creates no device request until explicit start, then stops both devices', async () => {
    const { adapter, controller } = setup();
    expect(adapter.starts).toEqual({ camera: 0, microphone: 0 });
    await controller.start(selection);
    expect(controller.getState().phase).toBe('active');
    expect(adapter.activeTracks).toBe(2);
    await controller.stop();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().phase).toBe('idle');
  });
  it.each(['permission_denied', 'device_missing'] as const)('releases microphone when camera returns %s', async failure => {
    const { adapter, controller } = setup();
    adapter.failure = failure;
    await controller.start(selection);
    await tick();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState()).toMatchObject({ phase: 'error', problem: failure });
    expect(controller.getState().capture.camera.state).toBe(failure === 'permission_denied' ? 'denied' : 'missing');
  });
  it('preserves the latest missing-device state after a preceding refused permission and full cleanup', async () => {
    const { adapter, controller } = setup();
    adapter.failure = 'permission_denied';
    await controller.start(selection);
    await tick();
    adapter.failure = 'device_missing';
    await controller.start(selection);
    await tick();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState()).toMatchObject({ phase: 'error', problem: 'device_missing',
      capture: { camera: { state: 'missing', problem: 'device_missing' } } });
  });
  it('stops an unanswered permission prompt and rejects a late grant without waiting for the user', async () => {
    const { adapter, controller } = setup();
    adapter.deferCamera = true;
    const starting = controller.start(selection);
    expect(controller.getState().phase).toBe('starting');
    await controller.stop();
    await starting;
    expect(controller.getState().phase).toBe('idle');
    expect(adapter.activeTracks).toBe(0);
    adapter.pendingCamera?.();
    await tick();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().phase).toBe('idle');
  });
  it('does not duplicate tracks when start is clicked twice', async () => {
    const { adapter, controller } = setup();
    await Promise.all([controller.start(selection), controller.start(selection)]);
    expect(adapter.starts).toEqual({ camera: 1, microphone: 1 });
    await controller.dispose();
  });
  it.each([
    ['error', 'interrupted', 'granted'],
    ['denied', 'permission_denied', 'denied'],
    ['missing', 'device_missing', 'unknown'],
  ] as const)('allows a fresh explicit Start after the previous microphone was %s', async (state, problem, permission) => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    await controller.stop('background');
    adapter.status.microphone = { state, problem, permission };
    adapter.emitStatus();
    expect(adapter.starts).toEqual({ camera: 1, microphone: 1 });
    expect(adapter.activeTracks).toBe(0);
    await controller.start(selection);
    expect(controller.getState()).toMatchObject({ phase: 'active', problem: null });
    expect(adapter.starts).toEqual({ camera: 2, microphone: 2 });
    expect(adapter.activeTracks).toBe(2);
    await controller.dispose();
  });
  it('does not request the next device after a synchronous selected-device failure revokes Start', async () => {
    const { adapter, controller } = setup();
    adapter.failure = 'permission_denied';
    await controller.start(selection);
    await tick();
    expect(adapter.starts).toEqual({ camera: 1, microphone: 0 });
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState()).toMatchObject({ phase: 'error', problem: 'permission_denied' });
  });
  it('releases devices even if a view subscriber throws during stop', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    controller.subscribe(() => { throw new Error('private view failure'); });
    await controller.stop();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().phase).toBe('idle');
  });
  it('does not open devices if a view subscriber fails when start is requested', async () => {
    const { adapter, controller } = setup();
    controller.subscribe(() => { throw new Error('private view failure'); });
    await controller.start(selection);
    await tick();
    expect(adapter.starts).toEqual({ camera: 0, microphone: 0 });
    expect(controller.getState()).toMatchObject({ phase: 'error', problem: 'capture_failed' });
  });
  it('blocks reentrant starts and shares cleanup during a synchronous stopping notification', async () => {
    const { adapter, controller } = setup();
    await controller.start({ ...selection, microphone: false });
    let nestedStop: Promise<void> | undefined;
    let notified = 0;
    controller.subscribe(() => {
      if (controller.getState().phase !== 'stopping') return;
      notified++;
      void controller.start({ ...selection, camera: false });
      nestedStop = controller.stop();
    });
    const stopping = controller.stop();
    expect(nestedStop).toBe(stopping);
    await stopping;
    expect(notified).toBeLessThan(5);
    expect(adapter.starts).toEqual({ camera: 1, microphone: 0 });
    expect(adapter.stops).toBe(1);
    expect(adapter.activeTracks).toBe(0);
  });
  it.each([
    [{ ...online, visible: false }, 'background'],
    [{ ...online, networkOnline: false }, 'offline'],
  ] as const)('stops on a lifecycle change and does not resume automatically', async (context, reason) => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    controller.setContext(context);
    await tick();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().stoppedReason).toBe(reason);
    controller.setContext(online);
    await tick();
    expect(adapter.starts).toEqual({ camera: 1, microphone: 1 });
    await controller.start(selection);
    expect(adapter.starts).toEqual({ camera: 2, microphone: 2 });
    await controller.dispose();
  });
  it('keeps local capture independent of emotion-service checks and synthetic data', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    controller.setContext({ ...online, connection: 'connecting' });
    expect(controller.getState().phase).toBe('active');
    controller.setContext({ ...online, source: 'demo', connection: 'offline' });
    expect(controller.getState().phase).toBe('active');
    expect(adapter.activeTracks).toBe(2);
    await controller.dispose();
  });
  it('blocks a hidden page, actual network loss and empty selection without device requests', async () => {
    const { adapter, controller } = setup();
    for (const context of [{ ...online, networkOnline: false }, { ...online, visible: false }]) {
      controller.setContext(context);
      await controller.start(selection);
    }
    controller.setContext(online);
    await controller.start({ ...selection, camera: false, microphone: false });
    expect(controller.getState().problem).toBe('nothing_selected');
    expect(adapter.starts).toEqual({ camera: 0, microphone: 0 });
  });
  it('allows explicit local capture in DEMO_ONLY without an emotion backend', async () => {
    const { adapter, controller } = setup();
    controller.setContext({ ...online, source: 'demo', connection: 'offline' });
    await controller.start(selection);
    expect(adapter.activeTracks).toBe(2);
    expect(controller.getState().phase).toBe('active');
    await controller.stop('source_change');
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().stoppedReason).toBe('source_change');
  });
  it('allows microphone only and preserves the chosen camera facing on another explicit start', async () => {
    const { adapter, controller } = setup();
    await controller.start({ ...selection, camera: false });
    expect(adapter.starts).toEqual({ camera: 0, microphone: 1 });
    await controller.stop();
    await controller.start({ ...selection, microphone: false, facing: 'environment' });
    expect(adapter.facing).toBe('environment');
    expect(adapter.starts).toEqual({ camera: 1, microphone: 1 });
    await controller.dispose();
  });
  it('passes a selected camera only on the next explicit start after the old stream is released', async () => {
    const { adapter, controller } = setup();
    await controller.start({ ...selection, microphone: false });
    await controller.stop();
    expect(adapter.activeTracks).toBe(0);
    await controller.start({ ...selection, microphone: false, cameraDeviceId: 'chosen-camera' });
    expect(adapter.cameraDeviceId).toBe('chosen-camera');
    expect(adapter.activeTracks).toBe(1);
    await controller.dispose();
  });
  it.each(['', 'x'.repeat(513), 'camera\u0000private'])('rejects invalid camera constraints without requesting devices', async cameraDeviceId => {
    const { adapter, controller } = setup();
    await controller.start({ ...selection, cameraDeviceId });
    expect(adapter.starts).toEqual({ camera: 0, microphone: 0 });
    expect(controller.getState().problem).toBe('capture_failed');
  });
  it('ends the whole session when a selected device disconnects', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    adapter.status.camera = { state: 'error', permission: 'granted', problem: 'device_ended' };
    adapter.emitStatus();
    await tick();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().problem).toBe('device_ended');
  });
  it('times out an unanswered permission prompt and still releases other devices', async () => {
    vi.useFakeTimers();
    try {
      const { adapter, controller } = setup({ startTimeoutMs: 100 });
      adapter.deferCamera = true;
      const starting = controller.start(selection);
      await vi.advanceTimersByTimeAsync(100);
      await starting;
      expect(adapter.activeTracks).toBe(0);
      expect(controller.getState()).toMatchObject({ phase: 'error', problem: 'timeout' });
      adapter.pendingCamera?.();
      await tick();
      expect(adapter.activeTracks).toBe(0);
    } finally { vi.useRealTimers(); }
  });
  it('reports cleanup failure without displaying sensitive platform errors', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    adapter.cleanupFails = true;
    await controller.stop();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState()).toMatchObject({ phase: 'error', problem: 'cleanup_failed' });
    expect(JSON.stringify(controller.getState())).not.toContain('private platform error');
  });
  it('blocks new device requests after failed cleanup until a later stop confirms release', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    adapter.cleanupFails = true;
    await controller.stop();
    await controller.start(selection);
    expect(adapter.starts).toEqual({ camera: 1, microphone: 1 });
    adapter.cleanupFails = false;
    await controller.stop();
    await controller.start(selection);
    expect(adapter.starts).toEqual({ camera: 2, microphone: 2 });
    await controller.dispose();
  });
  it('contains a post-cleanup status read failure and does not permit another start', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    const getStatus = adapter.getStatus.bind(adapter);
    adapter.getStatus = () => { throw new Error('private status failure'); };
    await expect(controller.stop()).resolves.toBeUndefined();
    expect(controller.getState()).toMatchObject({ phase: 'error', problem: 'cleanup_failed' });
    await controller.start(selection);
    expect(adapter.starts).toEqual({ camera: 1, microphone: 1 });
    adapter.getStatus = getStatus;
    await controller.stop();
    await controller.start(selection);
    expect(adapter.starts).toEqual({ camera: 2, microphone: 2 });
    await controller.dispose();
  });
  it('requires actual inactive device status before permitting restart after a partial release', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    const stopAll = adapter.stopAll.bind(adapter);
    adapter.stopAll = async () => { adapter.activeTracks = 1; };
    await controller.stop();
    expect(adapter.activeTracks).toBe(1);
    expect(controller.getState()).toMatchObject({ phase: 'error', problem: 'cleanup_failed' });
    await controller.start(selection);
    expect(adapter.starts).toEqual({ camera: 1, microphone: 1 });
    adapter.stopAll = stopAll;
    await controller.stop();
    await controller.start(selection);
    expect(adapter.activeTracks).toBe(2);
    await controller.dispose();
  });
  it('removes all subscriptions on unmount and prevents another start', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    await controller.dispose();
    expect(adapter.subscriptions()).toBe(0);
    expect(adapter.activeTracks).toBe(0);
    await controller.start(selection);
    expect(adapter.starts).toEqual({ camera: 1, microphone: 1 });
  });
});

describe('bounded metadata without media retention', () => {
  it('reports actual normalized microphone input and clears it on stop without emotion claims', async () => {
    const { adapter, controller } = setup();
    expect(controller.getState().inputLevel).toBeNull();
    await controller.start(selection);
    adapter.emitLevel(0);
    expect(controller.getState().inputLevel).toBe(0);
    adapter.emitLevel(0.42);
    expect(controller.getState().inputLevel).toBe(0.42);
    await controller.stop();
    adapter.emitLevel(0.8);
    expect(controller.getState().inputLevel).toBeNull();
  });
  it('rejects unbounded input-level metadata and stops the microphone', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    adapter.emitLevel(Infinity);
    await tick();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().problem).toBe('encoding_failed');
  });
  it('counts encoded packets once, ignores stale sequence numbers and stores no raw bytes', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    adapter.emitVideo(frame(1)); adapter.emitVideo(frame(1)); adapter.emitVideo(frame(0));
    adapter.emitAudio(audio(1)); adapter.emitAudio(audio(1));
    expect(controller.getState()).toMatchObject({ videoFrames: 1, audioChunks: 1 });
    expect(Object.keys(controller.getState())).not.toContain('bytes');
    expect(JSON.stringify(controller.getState())).not.toMatch(/image\/jpeg|audio\/wav/);
    await controller.stop();
    adapter.emitVideo(frame(2)); adapter.emitAudio(audio(2));
    expect(controller.getState()).toMatchObject({ videoFrames: 1, audioChunks: 1 });
  });
  it.each([
    { ...frame(), bytes: new ArrayBuffer(200 * 1024 + 1) },
    { ...frame(), width: 641 },
    { ...frame(), timestamp: Date.now() - 60_000 },
    { ...frame(), sequence: NaN },
    { ...frame(), mime: 'image/png' },
  ])('rejects invalid or oversized video packets and stops capture', async invalid => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    adapter.emitVideo(invalid as VideoFrame);
    await tick();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState()).toMatchObject({ videoFrames: 0, problem: 'encoding_failed' });
  });
  it('rejects oversized audio and retains no chunk queue', async () => {
    const { adapter, controller } = setup();
    await controller.start(selection);
    adapter.emitAudio({ ...audio(), bytes: new ArrayBuffer(128 * 1024 + 1) });
    await tick();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().audioChunks).toBe(0);
  });
  it('keeps snapshots immutable when the adapter changes its own status', () => {
    const { adapter, controller } = setup();
    const previous = controller.getState();
    adapter.status.camera.state = 'requesting';
    adapter.emitStatus();
    expect(previous.capture.camera.state).toBe('off');
    expect(controller.getState().capture.camera.state).toBe('requesting');
  });
  it.each(['user', 'background', 'offline', 'device_error', 'cleanup_failure'] as const)('local %s stop releases devices while cloud confirmation is pending', async reason => {
    const { adapter, controller } = setup();
    const auth = new FakeAuthAdapter(); await auth.signIn();
    const id = '11111111-1111-4111-8111-111111111111';
    const metadata: CloudSession = { id, child_profile_id: id, source_platform: 'web', started_at: '2026-10-07T01:00:00Z', ended_at: null, status: 'active', created_at: '2026-10-07T01:00:00Z' };
    let confirm!: (value: CloudSession) => void;
    const api = { createSession: vi.fn(() => ({ promise: Promise.resolve(metadata), cancel: vi.fn() })),
      endSession: vi.fn(() => ({ promise: new Promise<CloudSession>(resolve => { confirm = resolve; }), cancel: vi.fn() })) } as unknown as CloudApi;
    const bridge = new CloudSessionBridge(auth, api, 'web');
    let phase = controller.getState().phase;
    controller.subscribe(() => { const next = controller.getState().phase; if (next === phase) return; phase = next; if (next === 'active') bridge.begin(id); else bridge.end(); });
    await controller.start(selection); await tick();
    adapter.emitVideo(frame()); adapter.emitAudio(audio());
    expect(api.createSession).toHaveBeenCalledWith(id, 'web');
    if (reason === 'background') controller.setContext({ ...online, visible: false });
    else if (reason === 'offline') controller.setContext({ ...online, networkOnline: false });
    else if (reason === 'device_error') { adapter.status.camera.state = 'off'; adapter.emitStatus(); }
    else { adapter.cleanupFails = reason === 'cleanup_failure'; await controller.stop(); }
    for (let index = 0; index < 12; index++) await Promise.resolve();
    expect(adapter.activeTracks).toBe(0);
    expect(controller.getState().phase).toBe(reason === 'device_error' || reason === 'cleanup_failure' ? 'error' : 'idle');
    expect(bridge.getState().status).toBe('ending');
    expect(api.endSession).toHaveBeenCalledWith(id);
    confirm({ ...metadata, status: 'ended', ended_at: '2026-10-07T01:01:00Z' }); await tick();
    expect(bridge.getState().status).toBe('ended');
  });
  it.each([{ framesPerSecond: 5 }, { maxWidth: 2000 }, { maxAudioBytes: Infinity },
    { audioChunkMs: 6000 }, { audioChunkMs: 250 }, { maxHeight: NaN }])('refuses unbounded capture configuration', invalid => {
    expect(() => captureConfig(invalid)).toThrow(RangeError);
  });
});
