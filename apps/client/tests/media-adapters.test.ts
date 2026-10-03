import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { encodeMonoWav } from '../src/media/processors/wav';
import { downsampleRgba, frameDimensions } from '../src/media/processors/image';
import { encodedImageMime, encodeVideoFrame } from '../src/media/processors/image-encoding';
import { WebMediaCaptureAdapter } from '../src/media/adapters/web';
import { AndroidMediaCaptureAdapter, type AndroidLifecycleDriver } from '../src/media/adapters/android';
import { FakeMediaCaptureAdapter } from '../src/media/adapters/fake';
import type { AudioChunk, AudioInputLevel, VideoFrame } from '../src/media/types';
import Taro from '@tarojs/taro';
import { WeAppMediaCaptureAdapter, type MiniMediaDriver, type MiniRecorder } from '../src/media/adapters/weapp';

vi.mock('@tarojs/taro', () => ({ default: {} }));

describe('bounded media encoding', () => {
  it('writes independently decodable mono PCM16 RIFF headers using the actual rate', () => {
    const samples = new Int16Array([0, -32768, 32767, -1]);
    const buffer = encodeMonoWav(samples, 48000);
    const view = new DataView(buffer);
    const word = (offset: number, length: number) => String.fromCharCode(...new Uint8Array(buffer, offset, length));
    expect(word(0, 4)).toBe('RIFF'); expect(word(8, 4)).toBe('WAVE'); expect(word(36, 4)).toBe('data');
    expect(view.getUint32(4, true)).toBe(buffer.byteLength - 8);
    expect(view.getUint16(20, true)).toBe(1); expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(48000); expect(view.getUint32(28, true)).toBe(96000);
    expect(view.getUint16(32, true)).toBe(2); expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(8);
    expect([0, 1, 2, 3].map(index => view.getInt16(44 + index * 2, true))).toEqual([...samples]);
  });

  it('accepts one second at 48kHz and rejects oversized/empty blocks or invalid rates', () => {
    expect(encodeMonoWav(new Int16Array(48000), 48000).byteLength).toBe(96044);
    expect(() => encodeMonoWav(new Int16Array(96000), 96000)).toThrow(/limit/);
    expect(() => encodeMonoWav(new Int16Array(), 16000)).toThrow();
    expect(() => encodeMonoWav(new Int16Array(16), Number.NaN)).toThrow();
  });

  it('bounds the longest edge without upscaling and preserves portrait frames', () => {
    expect(frameDimensions(1920, 1080)).toEqual({ width: 640, height: 360 });
    expect(frameDimensions(1080, 1920)).toEqual({ width: 360, height: 640 });
    expect(frameDimensions(320, 240)).toEqual({ width: 320, height: 240 });
    expect(() => frameDimensions(0, 240)).toThrow();
    expect(() => frameDimensions(1920.5, 1080)).toThrow();
  });

  it('validates genuine RGBA dimensions and produces an independent bounded pixel copy', () => {
    const source = new Uint8Array([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255]);
    const resized = downsampleRgba(source.buffer, 2, 2, 1);
    expect(resized.width).toBe(1); expect(resized.height).toBe(1);
    expect([...resized.data]).toEqual([255, 0, 0, 255]);
    resized.data[0] = 0;
    expect(source[0]).toBe(255);
    expect(() => downsampleRgba(new ArrayBuffer(3), 2, 2)).toThrow(/byte length/);
  });

  it('rejects PNG fallback and verifies encoded bytes before declaring JPEG or WebP', async () => {
    expect(encodedImageMime(new Uint8Array([0x89, 0x50, 0x4e, 0x47]).buffer)).toBeNull();
    const video = { videoWidth: 1280, videoHeight: 720 } as HTMLVideoElement;
    const canvas = { width: 0, height: 0, getContext: () => ({ drawImage: () => {} }),
      toBlob: (callback: BlobCallback) => callback(new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: 'image/png' })),
    } as unknown as HTMLCanvasElement;
    await expect(encodeVideoFrame(video, canvas)).rejects.toThrow(/JPEG or WebP/);
    expect(canvas.width).toBe(640); expect(canvas.height).toBe(360);
    canvas.toBlob = callback => callback(new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: 'image/jpeg' }));
    await expect(encodeVideoFrame(video, canvas)).rejects.toThrow(/declared format/);
  });
});

interface TestWorklet {
  port: { onmessage: ((event: MessageEvent) => void) | null; postMessage: Mock; close: Mock };
  onprocessorerror: (() => void) | null; connect: Mock; disconnect: Mock;
}
interface TestAudioContext {
  sampleRate: number; state: string; audioWorklet: { addModule: Mock<() => Promise<void>> };
  resume: Mock<() => Promise<void>>; close: Mock<() => Promise<void>>; destination: object;
  createMediaStreamSource: Mock<() => { connect: Mock; disconnect: Mock }>;
  createGain: Mock<() => { gain: { value: number }; connect: Mock; disconnect: Mock }>;
}

function webFixture(native?: AndroidLifecycleDriver) {
  class Track extends EventTarget {
    readyState = 'live';
    stop = vi.fn(() => { this.readyState = 'ended'; });
  }
  const tracks: Track[] = [], contexts: TestAudioContext[] = [], nodes: TestWorklet[] = [];
  const canvases: { callbacks: BlobCallback[]; element: HTMLCanvasElement }[] = [];
  const jpeg = () => new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], { type: 'image/jpeg' });
  const media = new EventTarget() as EventTarget & { getUserMedia: Mock<(constraints: MediaStreamConstraints) => Promise<MediaStream>>;
    enumerateDevices: Mock<() => Promise<{ kind: string; deviceId: string; label: string }[]>> };
  media.getUserMedia = vi.fn(async (constraints: MediaStreamConstraints) => {
    const track = new Track(); tracks.push(track);
    return { getTracks: () => [track], getVideoTracks: () => constraints.video ? [track] : [], getAudioTracks: () => constraints.audio ? [track] : [] } as unknown as MediaStream;
  });
  media.enumerateDevices = vi.fn(async () => [{ kind: 'videoinput', deviceId: 'camera-1', label: 'Device\u0000 label' }]);
  const dom = new EventTarget() as EventTarget & { hidden: boolean; createElement: (tag: string) => unknown };
  dom.hidden = false;
  dom.createElement = tag => {
    if (tag === 'video') return { srcObject: null, readyState: 2, videoWidth: 640, videoHeight: 360,
      play: vi.fn(async () => {}), pause: vi.fn(), removeAttribute: vi.fn() };
    const callbacks: BlobCallback[] = [];
    const element = { width: 0, height: 0, getContext: () => ({ drawImage: vi.fn() }),
      toBlob: (callback: BlobCallback) => callbacks.push(callback) } as unknown as HTMLCanvasElement;
    canvases.push({ callbacks, element }); return element;
  };
  const browser = new EventTarget() as EventTarget & { isSecureContext: boolean; navigator: { onLine: boolean } };
  browser.isSecureContext = true; browser.navigator = { onLine: true };
  function makeNode(): TestWorklet {
    const node = { port: { onmessage: null as ((event: MessageEvent) => void) | null, postMessage: vi.fn(), close: vi.fn() },
      onprocessorerror: null as (() => void) | null, connect: vi.fn(), disconnect: vi.fn() };
    nodes.push(node); return node;
  }
  function makeContext(): TestAudioContext {
    const context = { sampleRate: 16000, state: 'running', audioWorklet: { addModule: vi.fn(async () => {}) },
      resume: vi.fn(async () => {}), close: vi.fn(async () => { context.state = 'closed'; }), destination: {},
      createMediaStreamSource: vi.fn(() => ({ connect: vi.fn(), disconnect: vi.fn() })),
      createGain: vi.fn(() => ({ gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() })) };
    contexts.push(context); return context;
  }
  const driver = {
    mediaDevices: media as unknown as MediaDevices, document: dom as unknown as Document, window: browser as unknown as Window,
    createAudioContext: () => makeContext() as unknown as AudioContext,
    createWorklet: () => makeNode() as unknown as AudioWorkletNode,
  };
  const adapter = native ? new AndroidMediaCaptureAdapter({ framesPerSecond: 1 }, driver, native)
    : new WebMediaCaptureAdapter({ framesPerSecond: 1 }, driver);
  return { adapter, media, dom, browser, tracks, contexts, nodes, canvases, jpeg };
}

describe('actual Web adapter with injected platform driver', () => {
  afterEach(() => vi.useRealTimers());
  it('does not request media on construction; explicit start and stop release both devices/context', async () => {
    const f = webFixture();
    expect(f.media.getUserMedia).not.toHaveBeenCalled(); expect(f.contexts).toHaveLength(0);
    await Promise.all([f.adapter.startCamera(), f.adapter.startMicrophone()]);
    expect(f.adapter.getStatus().camera.state).toBe('on'); expect(f.adapter.getStatus().microphone.state).toBe('on');
    expect(f.media.getUserMedia).toHaveBeenCalledTimes(2);
    await f.adapter.stopAll();
    expect(f.tracks.every(track => track.readyState === 'ended')).toBe(true);
    expect(f.contexts[0].state).toBe('closed'); expect(f.nodes[0].port.close).toHaveBeenCalledTimes(1);
    await f.adapter.dispose();
  });

  it.each(['camera', 'microphone'] as const)('does not request %s permission after a requesting observer cancels synchronously', async device => {
    const f = webFixture(); let cleanup: Promise<void> | null = null;
    f.adapter.subscribeStatus(status => { if (status[device].state === 'requesting' && !cleanup) cleanup = f.adapter.stopAll(); });
    await expect(device === 'camera' ? f.adapter.startCamera() : f.adapter.startMicrophone()).rejects.toMatchObject({ code: 'interrupted' });
    await cleanup; expect(f.media.getUserMedia).not.toHaveBeenCalled(); expect(f.contexts).toHaveLength(0); await f.adapter.dispose();
  });

  it('does not create a late camera timer after an ON observer immediately stops the device', async () => {
    vi.useFakeTimers(); const f = webFixture(); let cleanup: Promise<void> | null = null;
    f.adapter.subscribeVideoFrame(() => {});
    f.adapter.subscribeStatus(status => { if (status.camera.state === 'on' && !cleanup) cleanup = f.adapter.stopAll(); });
    await expect(f.adapter.startCamera()).rejects.toMatchObject({ code: 'interrupted' }); await cleanup;
    expect(f.tracks[0].readyState).toBe('ended'); expect(vi.getTimerCount()).toBe(0); await f.adapter.dispose();
  });

  it('retains a failed track for real cleanup retry and blocks a new acquisition', async () => {
    const f = webFixture(); await f.adapter.startCamera();
    f.tracks[0].stop.mockImplementationOnce(() => { throw new Error('private stop failure'); });
    await expect(f.adapter.stopCamera()).rejects.toMatchObject({ code: 'cleanup_failed' });
    expect(f.tracks[0].readyState).toBe('live'); expect(f.adapter.getStatus().camera.problem).toBe('cleanup_failed');
    await expect(f.adapter.startCamera()).rejects.toMatchObject({ code: 'cleanup_failed' });
    expect(f.media.getUserMedia).toHaveBeenCalledTimes(1);
    await f.adapter.stopCamera(); expect(f.tracks[0].readyState).toBe('ended');
    await f.adapter.startCamera(); expect(f.media.getUserMedia).toHaveBeenCalledTimes(2);
    await f.adapter.dispose();
  });

  it('deduplicates pending cleanup and retries a failed AudioContext.close before restart', async () => {
    const f = webFixture(); await f.adapter.startMicrophone();
    let rejectClose!: (error: unknown) => void;
    f.contexts[0].close.mockImplementationOnce(() => new Promise<void>((_, reject) => { rejectClose = reject; }));
    const first = f.adapter.stopAll(), second = f.adapter.stopAll();
    expect(first).toBe(second);
    const rejected = expect(first).rejects.toMatchObject({ code: 'cleanup_failed' });
    await Promise.resolve(); await Promise.resolve();
    await expect(f.adapter.startMicrophone()).rejects.toMatchObject({ code: 'cleanup_failed' });
    rejectClose(new Error('private close error')); await rejected;
    await expect(f.adapter.startMicrophone()).rejects.toMatchObject({ code: 'cleanup_failed' });
    await f.adapter.stopAll(); expect(f.contexts[0].close).toHaveBeenCalledTimes(2);
    await f.adapter.startMicrophone(); expect(f.contexts).toHaveLength(2);
    await f.adapter.dispose();
  });

  it('releases a late permission grant and never revives a canceled device', async () => {
    const f = webFixture(); const stream = await f.media.getUserMedia({ video: true }); f.media.getUserMedia.mockClear();
    let grant!: (stream: MediaStream) => void;
    f.media.getUserMedia.mockImplementationOnce(() => new Promise<MediaStream>(resolve => { grant = resolve; }));
    const pending = f.adapter.startCamera(), canceled = expect(pending).rejects.toMatchObject({ code: 'interrupted' });
    await f.adapter.stopAll(); grant(stream); await canceled;
    expect(f.tracks[0].readyState).toBe('ended'); expect(f.adapter.getStatus().camera.state).toBe('off');
    await f.adapter.dispose();
  });

  it('preserves the newest missing device failure after a prior denial and full cleanup', async () => {
    const f = webFixture();
    f.media.getUserMedia.mockRejectedValueOnce({ name: 'NotAllowedError' });
    await expect(f.adapter.startCamera()).rejects.toMatchObject({ code: 'permission_denied' });
    await f.adapter.stopAll(); expect(f.adapter.getStatus().camera.state).toBe('denied');
    f.media.getUserMedia.mockRejectedValueOnce({ name: 'NotFoundError' });
    await expect(f.adapter.startCamera()).rejects.toMatchObject({ code: 'device_missing' });
    await f.adapter.stopAll(); expect(f.adapter.getStatus().camera.state).toBe('missing');
    expect(f.adapter.getStatus().camera.problem).toBe('device_missing'); await f.adapter.dispose();
  });

  it.each([
    ['NotAllowedError', 'permission_denied', 'denied'],
    ['NotFoundError', 'device_missing', 'missing'],
    ['NotReadableError', 'device_in_use', 'error'],
  ])('handles a Mic-only %s without losing failure context or its created AudioContext', async (name, code, state) => {
    const f = webFixture(); f.media.getUserMedia.mockRejectedValueOnce({ name });
    await expect(f.adapter.startMicrophone()).rejects.toMatchObject({ code });
    await f.adapter.stopAll(); expect(f.adapter.getStatus().microphone).toMatchObject({ state, problem: code });
    expect(f.contexts).toHaveLength(1); expect(f.contexts[0].state).toBe('closed');
    expect(f.media.getUserMedia.mock.calls[0][0]).toMatchObject({ video: false, audio: { channelCount: 1 } });
    await f.adapter.dispose();
  });

  it('maps an unreadable camera to the visible device-unavailable problem', async () => {
    const f = webFixture(); f.media.getUserMedia.mockRejectedValueOnce({ name: 'NotReadableError' });
    await expect(f.adapter.startCamera()).rejects.toMatchObject({ code: 'device_in_use' });
    await f.adapter.stopAll(); expect(f.adapter.getStatus().camera.problem).toBe('device_in_use'); await f.adapter.dispose();
  });

  it('stops only the microphone and its audio nodes while an explicitly started camera stays active', async () => {
    const f = webFixture(); await f.adapter.startCamera(); await f.adapter.startMicrophone();
    await f.adapter.stopMicrophone();
    expect(f.adapter.getStatus().camera.state).toBe('on'); expect(f.tracks[0].readyState).toBe('live');
    expect(f.adapter.getStatus().microphone.state).toBe('off'); expect(f.tracks[1].readyState).toBe('ended');
    expect(f.contexts[0].state).toBe('closed'); expect(f.nodes[0].disconnect).toHaveBeenCalledTimes(1);
    await f.adapter.dispose(); expect(f.tracks[0].readyState).toBe('ended');
  });

  it('stops emitting WAV after the last audio subscriber leaves while clearing real PCM and acknowledging blocks', async () => {
    const f = webFixture(); const chunks: AudioChunk[] = [], levels: AudioInputLevel[] = [];
    const unsubscribe = f.adapter.subscribeAudioChunk(chunk => chunks.push(chunk)); f.adapter.subscribeAudioLevel(level => levels.push(level));
    await f.adapter.startMicrophone();
    const first = new Int16Array(16000).fill(8192);
    f.nodes[0].port.onmessage!({ data: { type: 'pcm', samples: first.buffer, sampleRate: 16000 } } as MessageEvent);
    expect(chunks).toHaveLength(1); expect(chunks[0]).toMatchObject({ mime: 'audio/wav', sampleRate: 16000, durationMs: 1000 });
    expect(new DataView(chunks[0].bytes).getUint32(24, true)).toBe(16000); expect(first.every(value => value === 0)).toBe(true);
    unsubscribe(); const second = new Int16Array(16000).fill(16384);
    f.nodes[0].port.onmessage!({ data: { type: 'pcm', samples: second.buffer, sampleRate: 16000 } } as MessageEvent);
    expect(chunks).toHaveLength(1); expect(second.every(value => value === 0)).toBe(true);
    expect(levels[levels.length - 1].level).toBe(0.5);
    expect(f.nodes[0].port.postMessage.mock.calls.filter(([value]) => value.type === 'ack')).toHaveLength(2); await f.adapter.dispose();
  });

  it('clears PCM without emitting WAV when a level observer stops capture synchronously', async () => {
    const f = webFixture(); const chunks: AudioChunk[] = []; let cleanup: Promise<void> | null = null;
    f.adapter.subscribeAudioChunk(chunk => chunks.push(chunk));
    f.adapter.subscribeAudioLevel(value => { if (value.level && !cleanup) cleanup = f.adapter.stopAll(); });
    await f.adapter.startMicrophone(); const samples = new Int16Array(16000).fill(16384);
    f.nodes[0].port.onmessage!({ data: { type: 'pcm', samples: samples.buffer, sampleRate: 16000 } } as MessageEvent);
    await cleanup; expect(chunks).toHaveLength(0); expect(samples.every(value => value === 0)).toBe(true); await f.adapter.dispose();
  });

  it('retries a failed track release on repeated disposal instead of forgetting the owned live resource', async () => {
    const f = webFixture(); await f.adapter.startMicrophone();
    f.tracks[0].stop.mockImplementationOnce(() => { throw new Error('private cleanup failure'); });
    await expect(f.adapter.dispose()).rejects.toMatchObject({ code: 'cleanup_failed' }); expect(f.tracks[0].readyState).toBe('live');
    await f.adapter.dispose(); expect(f.tracks[0].readyState).toBe('ended'); expect(f.tracks[0].stop).toHaveBeenCalledTimes(2);
  });

  it('still stops media when a lifecycle listener removal fails and retries that actual remover', async () => {
    const f = webFixture(); await f.adapter.startMicrophone();
    const remove = vi.spyOn(f.dom, 'removeEventListener'); remove.mockImplementationOnce(() => { throw new Error('private listener failure'); });
    await expect(f.adapter.dispose()).rejects.toMatchObject({ code: 'cleanup_failed' });
    expect(f.tracks[0].readyState).toBe('ended'); expect(f.contexts[0].state).toBe('closed');
    await f.adapter.dispose(); expect(remove).toHaveBeenCalledTimes(2);
  });

  it('stops on actual lifecycle events and does not restart on visible/online', async () => {
    const f = webFixture(); await Promise.all([f.adapter.startCamera(), f.adapter.startMicrophone()]);
    f.dom.hidden = true; f.dom.dispatchEvent(new Event('visibilitychange'));
    await f.adapter.stopAll(); expect(f.tracks.every(track => track.readyState === 'ended')).toBe(true);
    f.dom.hidden = false; f.dom.dispatchEvent(new Event('visibilitychange')); f.browser.dispatchEvent(new Event('online'));
    expect(f.media.getUserMedia).toHaveBeenCalledTimes(2); await f.adapter.dispose();
  });

  it('ignores old processor errors and emits actual finite RMS without retaining samples', async () => {
    const f = webFixture(); const levels: AudioInputLevel[] = [];
    const unsubscribe = f.adapter.subscribeAudioLevel(value => levels.push(value));
    await f.adapter.startMicrophone(); const oldError = f.nodes[0].onprocessorerror!;
    const samples = new Int16Array(16000).fill(16384);
    f.nodes[0].port.onmessage!({ data: { type: 'pcm', samples: samples.buffer, sampleRate: 16000 } } as MessageEvent);
    expect(levels[levels.length - 1]?.level).toBe(0.5); expect(samples.every(sample => sample === 0)).toBe(true);
    await f.adapter.stopAll(); expect(levels[levels.length - 1]?.level).toBe(0);
    await f.adapter.startMicrophone(); oldError(); expect(f.adapter.getStatus().microphone.state).toBe('on');
    unsubscribe(); const count = levels.length; await f.adapter.stopAll(); expect(levels).toHaveLength(count);
    await f.adapter.dispose();
  });

  it('never enumerates before grant and uses a selected exact ID without facing constraints', async () => {
    const f = webFixture(); expect(await f.adapter.listCameras()).toEqual([]); expect(f.media.enumerateDevices).not.toHaveBeenCalled();
    await f.adapter.startCamera(); expect(await f.adapter.listCameras()).toEqual([{ deviceId: 'camera-1', label: 'Device label' }]);
    await f.adapter.stopAll(); await f.adapter.startCamera('environment', 'camera-1');
    const constraints = f.media.getUserMedia.mock.calls[f.media.getUserMedia.mock.calls.length - 1][0];
    expect(constraints.video).toMatchObject({ deviceId: { exact: 'camera-1' } });
    expect(constraints.video).not.toHaveProperty('facingMode'); await f.adapter.dispose();
  });

  it('drops old asynchronous frames without unlocking the newer encoding or encoding without subscribers', async () => {
    vi.useFakeTimers(); const f = webFixture(); const frames: VideoFrame[] = [];
    const unsubscribe = f.adapter.subscribeVideoFrame(frame => frames.push(frame));
    await f.adapter.startCamera(); await vi.advanceTimersByTimeAsync(1000); const old = f.canvases[0].callbacks[0];
    await f.adapter.stopCamera(); await f.adapter.startCamera(); await vi.advanceTimersByTimeAsync(1000);
    old(f.jpeg()); await Promise.resolve(); await vi.advanceTimersByTimeAsync(1000);
    expect(f.canvases[1].callbacks).toHaveLength(1); expect(frames).toHaveLength(0);
    f.canvases[1].callbacks[0](f.jpeg()); await vi.advanceTimersByTimeAsync(0); expect(frames).toHaveLength(1);
    unsubscribe(); await vi.advanceTimersByTimeAsync(1000); expect(f.canvases[1].callbacks).toHaveLength(1);
    await f.adapter.dispose();
  });

  it('isolates an observer exception so device cleanup still occurs with a generic visible failure', async () => {
    const f = webFixture(); await f.adapter.startCamera();
    f.adapter.subscribeStatus(status => { if (status.camera.state === 'off') throw new Error('private observer text'); });
    await f.adapter.stopAll(); expect(f.tracks[0].readyState).toBe('ended');
    expect(JSON.stringify(f.adapter.getStatus())).not.toContain('private'); await f.adapter.dispose();
  });
});

describe('WebView adapter with an injected lifecycle driver only', () => {
  it('stops Web resources on native pause/network loss and removes registered lifecycle handles', async () => {
    let pause = () => {}, state = (_active: boolean) => {}, network = (_online: boolean) => {};
    const handles = Array.from({ length: 3 }, () => ({ remove: vi.fn(async () => {}) }));
    const f = webFixture({
      onPause: async callback => { pause = callback; return handles[0]; },
      onAppStateChange: async callback => { state = callback; return handles[1]; },
      onNetworkChange: async callback => { network = callback; return handles[2]; },
    });
    await f.adapter.startMicrophone(); pause(); await f.adapter.stopAll(); expect(f.tracks[0].readyState).toBe('ended');
    state(true); network(true); expect(f.media.getUserMedia).toHaveBeenCalledTimes(1);
    await f.adapter.startCamera(); network(false); await f.adapter.stopAll(); expect(f.tracks[1].readyState).toBe('ended');
    await f.adapter.dispose(); expect(handles.every(handle => handle.remove.mock.calls.length === 1)).toBe(true);
  });

  it('removes each late lifecycle handle before disposal resolves and never opens devices', async () => {
    const grants: ((handle: { remove(): Promise<void> }) => void)[] = [];
    const register = () => new Promise<{ remove(): Promise<void> }>(resolve => { grants.push(resolve); });
    const f = webFixture({ onPause: register, onAppStateChange: register, onNetworkChange: register });
    const disposing = f.adapter.dispose(); const handles = Array.from({ length: 3 }, () => ({ remove: vi.fn(async () => {}) }));
    grants.forEach((grant, index) => grant(handles[index])); await disposing;
    expect(handles.every(handle => handle.remove.mock.calls.length === 1)).toBe(true); expect(f.media.getUserMedia).not.toHaveBeenCalled();
  });

  it('retains a failed native handle and retries its actual removal on the next disposal', async () => {
    const handles = Array.from({ length: 3 }, () => ({ remove: vi.fn(async () => {}) }));
    handles[0].remove.mockRejectedValueOnce(new Error('private native failure'));
    const f = webFixture({ onPause: async () => handles[0], onAppStateChange: async () => handles[1], onNetworkChange: async () => handles[2] });
    await expect(f.adapter.dispose()).rejects.toMatchObject({ code: 'cleanup_failed' });
    expect(handles[1].remove).toHaveBeenCalledTimes(1); expect(handles[2].remove).toHaveBeenCalledTimes(1);
    await f.adapter.dispose(); expect(handles[0].remove).toHaveBeenCalledTimes(2);
    expect(handles[1].remove).toHaveBeenCalledTimes(1); expect(f.media.getUserMedia).not.toHaveBeenCalled();
  });
});

describe('explicit Fake adapter', () => {
  it('simulates granted/denied/missing outcomes without touching any platform API', async () => {
    const allowed = new FakeMediaCaptureAdapter(); await Promise.all([allowed.startCamera(), allowed.startMicrophone()]);
    expect(allowed.observations.activeTracks).toBe(2); await allowed.dispose(); expect(allowed.observations.activeTracks).toBe(0);
    for (const outcome of ['deny', 'missing'] as const) {
      const adapter = new FakeMediaCaptureAdapter({ camera: outcome, microphone: outcome });
      await expect(adapter.startCamera()).rejects.toMatchObject({ code: outcome === 'deny' ? 'permission_denied' : 'device_missing' });
      await expect(adapter.startMicrophone()).rejects.toMatchObject({ code: outcome === 'deny' ? 'permission_denied' : 'device_missing' });
      await adapter.dispose();
    }
  });
  it('cancels late grants and filters old frame/audio/level emitters after a new explicit run', async () => {
    const late = new FakeMediaCaptureAdapter({ camera: 'late' });
    const pending = late.startCamera(), canceled = expect(pending).rejects.toMatchObject({ code: 'interrupted' });
    await late.stopAll(); late.grantPending('camera'); await canceled; expect(late.observations.activeTracks).toBe(0); await late.dispose();
    const adapter = new FakeMediaCaptureAdapter(); const levels: AudioInputLevel[] = [];
    adapter.subscribeAudioLevel(value => levels.push(value)); await adapter.startMicrophone(); const old = adapter.levelEmitter();
    old({ level: 0.25, timestamp: Date.now() }); await adapter.stopAll(); await adapter.startMicrophone();
    const count = levels.length; old({ level: 1, timestamp: Date.now() }); expect(levels).toHaveLength(count);
    adapter.end('microphone'); expect(adapter.observations.activeTracks).toBe(0); await adapter.dispose();
  });
});

function miniFixture() {
  const callbacks: { start?: () => void; frame?: Taro.RecorderManager.OnFrameRecordedCallback;
    error?: Taro.RecorderManager.OnErrorCallback; stop?: Taro.RecorderManager.OnStopCallback; interrupted?: () => void; pause?: () => void } = {};
  const recorder = {
    onStart: vi.fn((callback: () => void) => { callbacks.start = callback; }),
    onFrameRecorded: vi.fn((callback: Taro.RecorderManager.OnFrameRecordedCallback) => { callbacks.frame = callback; }),
    onError: vi.fn((callback: Taro.RecorderManager.OnErrorCallback) => { callbacks.error = callback; }),
    onStop: vi.fn((callback: Taro.RecorderManager.OnStopCallback) => { callbacks.stop = callback; }),
    onInterruptionBegin: vi.fn((callback: () => void) => { callbacks.interrupted = callback; }),
    onPause: vi.fn((callback: () => void) => { callbacks.pause = callback; }),
    start: vi.fn(() => callbacks.start?.()),
    stop: vi.fn(() => callbacks.stop?.({ tempFilePath: '/owned-recorder-temp.mp3', duration: 1000, fileSize: 16 })),
  };
  const cameraCallbacks: Taro.CameraContext.OnCameraFrameCallback[] = [];
  const listener = { start: vi.fn((options: Taro.CameraFrameListener.StartOption) => options.success?.({ errMsg: 'ok' })),
    stop: vi.fn((options: Taro.CameraFrameListener.StopOption) => options.success?.({ errMsg: 'ok' })) };
  const unlink = vi.fn((options: Taro.FileSystemManager.UnlinkOption) => options.success?.({ errMsg: 'ok' }));
  const fileSystem = { unlink, readFile: vi.fn((options: Taro.FileSystemManager.ReadFileOption) => options.success?.({
    data: new Uint8Array([0xff, 0xd8, 0xff, 0xe0]).buffer, errMsg: 'ok' })) };
  const putImage = vi.fn(async (_options: Taro.canvasPutImageData.Option) => {});
  const encodeImage = vi.fn(async () => ({ tempFilePath: '/owned-camera-temp.jpg' }));
  const removeHide = vi.fn(), removeNetwork = vi.fn();
  let hidden: () => void = () => {}, network: (online: boolean) => void = () => {};
  const driver: MiniMediaDriver = {
    getRecorderManager: () => recorder as unknown as MiniRecorder,
    createCameraContext: () => ({ onCameraFrame: (callback: Taro.CameraContext.OnCameraFrameCallback) => { cameraCallbacks.push(callback); return listener; } } as unknown as Taro.CameraContext),
    fileSystem: () => fileSystem as unknown as Taro.FileSystemManager,
    putImage, encodeImage,
    onHide: callback => { hidden = callback; return removeHide; }, onNetwork: callback => { network = callback; return removeNetwork; },
  };
  const adapter = new WeAppMediaCaptureAdapter({}, driver);
  return { adapter, driver, recorder, callbacks, cameraCallbacks, listener, fileSystem, putImage, encodeImage, unlink, removeHide, removeNetwork,
    hide: () => hidden(), offline: () => network(false) };
}

describe('actual WeChat adapter with the on-only SDK-shaped driver', () => {
  afterEach(() => vi.useRealTimers());
  it('starts only explicitly and reuses the singleton through two sessions without off* or listener growth', async () => {
    const f = miniFixture(); expect(f.recorder.start).not.toHaveBeenCalled();
    await f.adapter.startMicrophone(); expect(f.adapter.getStatus().microphone.state).toBe('on');
    await f.adapter.stopAll(); await f.adapter.startMicrophone();
    expect(f.adapter.getStatus().microphone.state).toBe('on'); expect(f.recorder.start).toHaveBeenCalledTimes(2);
    expect(f.recorder.onStart).toHaveBeenCalledTimes(1); expect(f.recorder.onFrameRecorded).toHaveBeenCalledTimes(1);
    await f.adapter.dispose(); expect(f.unlink).toHaveBeenCalled();
  });

  it('publishes natural recorder termination, stops the other device and removes the owned full temporary file', async () => {
    const f = miniFixture(); const camera = f.adapter.startCamera();
    f.adapter.bindPreview({ cameraId: 'camera', canvasId: 'canvas' }); f.adapter.previewReady(); await camera;
    await f.adapter.startMicrophone();
    f.callbacks.stop!({ tempFilePath: '/owned-natural-stop.mp3', duration: 60000, fileSize: 240000 });
    await f.adapter.stopAll();
    expect(f.adapter.getStatus().microphone.state).toBe('error');
    expect(f.adapter.getStatus().microphone.problem).toBe('device_ended'); expect(f.listener.stop).toHaveBeenCalled();
    expect(f.unlink.mock.calls.some(([options]) => options.filePath === '/owned-natural-stop.mp3')).toBe(true);
    await f.adapter.dispose();
  });

  it('emits genuine MP3 fragments using inspected rate and unknown input level instead of a fabricated WAV/RMS', async () => {
    const f = miniFixture(); const chunks: { mime: string; sampleRate: number }[] = [], levels: AudioInputLevel[] = [];
    f.adapter.subscribeAudioChunk(chunk => chunks.push(chunk)); f.adapter.subscribeAudioLevel(level => levels.push(level));
    await f.adapter.startMicrophone();
    f.callbacks.frame!({ frameBuffer: new Uint8Array([0xff, 0xf3, 0x48, 0xc4, 0, 0, 0, 0]).buffer, isLastFrame: false });
    expect(chunks).toMatchObject([{ mime: 'audio/mpeg', sampleRate: 16000 }]); expect(levels[levels.length - 1].level).toBeNull();
    await f.adapter.dispose();
  });

  it('encodes real RGBA only for subscribers, bounds portrait dimensions and deletes only API-returned owned temp paths', async () => {
    const f = miniFixture(); const frames: VideoFrame[] = [];
    const camera = f.adapter.startCamera(); f.adapter.bindPreview({ cameraId: 'camera', canvasId: 'canvas' }); f.adapter.previewReady(); await camera;
    const raw = new ArrayBuffer(1080 * 1920 * 4);
    f.cameraCallbacks[0]({ width: 1080, height: 1920, data: raw }); expect(f.putImage).not.toHaveBeenCalled();
    f.adapter.subscribeVideoFrame(frame => frames.push(frame)); f.cameraCallbacks[0]({ width: 1080, height: 1920, data: raw });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(frames).toMatchObject([{ mime: 'image/jpeg', width: 270, height: 480 }]);
    expect(f.unlink.mock.calls.every(([options]) => options.filePath === '/owned-camera-temp.jpg')).toBe(true);
    await f.adapter.dispose();
  });

  it('keeps a failed owned-temp deletion for the next real stop retry and blocks restart', async () => {
    const f = miniFixture(); await f.adapter.startMicrophone();
    f.unlink.mockImplementationOnce(options => options.fail?.({ errMsg: 'fail' }));
    await expect(f.adapter.stopAll()).rejects.toMatchObject({ code: 'cleanup_failed' });
    await expect(f.adapter.startMicrophone()).rejects.toMatchObject({ code: 'cleanup_failed' });
    await f.adapter.stopAll(); expect(f.unlink).toHaveBeenCalledTimes(2);
    await f.adapter.startMicrophone(); await f.adapter.dispose();
  });

  it('keeps a canceled pending lease until the late grant is stopped and never auto-resumes', async () => {
    const f = miniFixture(); f.recorder.start.mockImplementationOnce(() => {});
    const requested = f.adapter.startMicrophone(), canceled = expect(requested).rejects.toMatchObject({ code: 'interrupted' });
    const stopped = f.adapter.stopAll(); await canceled; await Promise.resolve();
    await expect(f.adapter.startMicrophone()).rejects.toMatchObject({ code: 'cleanup_failed' });
    expect(f.recorder.start).toHaveBeenCalledTimes(1);
    f.callbacks.start!(); await stopped;
    expect(f.recorder.stop).toHaveBeenCalledTimes(2); expect(f.adapter.getStatus().microphone.state).toBe('off');
    await f.adapter.startMicrophone(); expect(f.recorder.start).toHaveBeenCalledTimes(2); await f.adapter.dispose();
  });

  it('stops an orphan late SDK start and waits for its terminal callback before another lease', async () => {
    const f = miniFixture(); await f.adapter.startMicrophone(); await f.adapter.stopAll();
    f.recorder.stop.mockImplementationOnce(() => {}); f.callbacks.start!();
    await expect(f.adapter.startMicrophone()).rejects.toMatchObject({ code: 'cleanup_failed' });
    const stopped = f.adapter.stopAll();
    f.callbacks.stop!({ tempFilePath: '/owned-orphan.mp3', duration: 1, fileSize: 16 }); await stopped;
    expect(f.unlink.mock.calls.some(([options]) => options.filePath === '/owned-orphan.mp3')).toBe(true);
    await f.adapter.startMicrophone(); await f.adapter.dispose();
  });

  it('stops a late native camera-listener start again after cancellation without reviving the preview', async () => {
    const f = miniFixture(); let grant!: () => void;
    f.listener.start.mockImplementationOnce(options => { grant = () => options.success?.({ errMsg: 'ok' }); });
    const camera = f.adapter.startCamera(), canceled = expect(camera).rejects.toMatchObject({ code: 'interrupted' });
    f.adapter.bindPreview({ cameraId: 'camera', canvasId: 'canvas' }); f.adapter.previewReady();
    await f.adapter.stopCamera(); await canceled; expect(f.listener.stop).toHaveBeenCalledTimes(1);
    grant(); await Promise.resolve(); expect(f.listener.stop).toHaveBeenCalledTimes(2);
    expect(f.adapter.getStatus().camera.state).toBe('off'); await f.adapter.dispose();
  });

  it('keeps camera temp ownership separate while stopping only the microphone', async () => {
    const f = miniFixture(); f.adapter.subscribeVideoFrame(() => {});
    const camera = f.adapter.startCamera(); f.adapter.bindPreview({ cameraId: 'camera', canvasId: 'canvas' }); f.adapter.previewReady(); await camera;
    await f.adapter.startMicrophone();
    let read!: () => void;
    f.fileSystem.readFile.mockImplementationOnce(options => { read = () => options.success?.({ data: new Uint8Array([0xff, 0xd8, 0xff]).buffer, errMsg: 'ok' }); });
    f.cameraCallbacks[0]({ width: 1, height: 1, data: new ArrayBuffer(4) });
    await Promise.resolve(); await Promise.resolve(); await f.adapter.stopMicrophone();
    expect(f.adapter.getStatus().camera.state).toBe('on'); expect(f.listener.stop).not.toHaveBeenCalled();
    expect(f.unlink.mock.calls.some(([options]) => options.filePath === '/owned-camera-temp.jpg')).toBe(false);
    read(); await new Promise(resolve => setTimeout(resolve, 0));
    expect(f.unlink.mock.calls.some(([options]) => options.filePath === '/owned-camera-temp.jpg')).toBe(true); await f.adapter.dispose();
  });

  it('keeps an orphan terminal barrier owned after disposal times out and retries cleanup', async () => {
    vi.useFakeTimers(); const f = miniFixture(); await f.adapter.startMicrophone(); await f.adapter.stopAll();
    f.recorder.stop.mockImplementationOnce(() => {}); f.callbacks.start!();
    const disposing = f.adapter.dispose(), failed = expect(disposing).rejects.toMatchObject({ code: 'cleanup_failed' });
    await vi.advanceTimersByTimeAsync(5000); await failed;
    const retry = f.adapter.dispose(); f.callbacks.stop!({ tempFilePath: '/owned-late-terminal.mp3', duration: 1, fileSize: 16 }); await retry;
    expect(f.unlink.mock.calls.some(([options]) => options.filePath === '/owned-late-terminal.mp3')).toBe(true);
    expect(f.removeHide).toHaveBeenCalledTimes(1); expect(f.recorder.onStart).toHaveBeenCalledTimes(1);
  });

  it('still stops recording when lifecycle unsubscribe fails and retries only the failed remover', async () => {
    const f = miniFixture(); await f.adapter.startMicrophone(); f.removeHide.mockImplementationOnce(() => { throw new Error('private unsubscribe failure'); });
    await expect(f.adapter.dispose()).rejects.toMatchObject({ code: 'cleanup_failed' });
    expect(f.recorder.stop).toHaveBeenCalledTimes(1); expect(f.removeNetwork).toHaveBeenCalledTimes(1);
    await f.adapter.dispose(); expect(f.removeHide).toHaveBeenCalledTimes(2); expect(f.removeNetwork).toHaveBeenCalledTimes(1);
  });
});

describe('AudioWorklet bounded accumulation', () => {
  function processor(sampleRate: number) {
    const messages: { type: string; samples?: ArrayBuffer; sampleRate?: number }[] = [];
    type Processor = { port: { onmessage: (event: { data: { type: string } }) => void };
      process(inputs: Float32Array[][]): boolean };
    let ProcessorType: new () => Processor;
    runInNewContext(readFileSync(new URL('../src/media/processors/pcm-worklet.js', import.meta.url), 'utf8'), {
      sampleRate, AudioWorkletProcessor: class { port = { postMessage: (message: typeof messages[number]) => messages.push(message) }; },
      registerProcessor: (_name: string, type: new () => Processor) => { ProcessorType = type; },
    });
    return { instance: new ProcessorType!(), messages };
  }

  it('accumulates by actual sample count and handles variable input quanta/channel mixing', () => {
    const { instance, messages } = processor(16000);
    instance.process([[new Float32Array(10000).fill(1), new Float32Array(10000).fill(-1)]]);
    expect(messages).toHaveLength(0);
    instance.process([[new Float32Array(6000).fill(-1)]]);
    expect(messages).toHaveLength(1);
    expect(messages[0].sampleRate).toBe(16000);
    const pcm = new Int16Array(messages[0].samples!);
    expect(pcm).toHaveLength(16000); expect(pcm[0]).toBe(0); expect(pcm[15999]).toBe(-32768);
  });

  it('stops on unacknowledged backpressure instead of queueing unlimited audio', () => {
    const { instance, messages } = processor(8000);
    expect(instance.process([[new Float32Array(8000)]])).toBe(true);
    expect(instance.process([[new Float32Array(8000)]])).toBe(false);
    expect(messages.map(message => message.type)).toEqual(['pcm', 'overflow']);
    expect(instance.process([[new Float32Array(8000)]])).toBe(false);
  });

  it('acknowledges each block and stops processing after the cleanup message', () => {
    const { instance, messages } = processor(8000);
    instance.process([[new Float32Array(8000)]]);
    instance.port.onmessage({ data: { type: 'ack' } });
    expect(instance.process([[new Float32Array(8000)]])).toBe(true);
    expect(messages).toHaveLength(2);
    instance.port.onmessage({ data: { type: 'stop' } });
    expect(instance.process([[new Float32Array(8000)]])).toBe(false);
    expect(messages).toHaveLength(2);
  });
});
