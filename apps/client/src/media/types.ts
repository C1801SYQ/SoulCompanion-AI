export type CameraFacing = 'user' | 'environment';
export type DeviceState = 'off' | 'requesting' | 'on' | 'denied' | 'missing' | 'error';
export type PermissionState = 'unknown' | 'granted' | 'denied';
export type MediaProblem = 'permission_denied' | 'device_missing' | 'device_ended'
  | 'device_in_use' | 'unsupported' | 'insecure_context' | 'capture_failed' | 'encoding_failed'
  | 'oversize' | 'interrupted' | 'timeout' | 'cleanup_failed';

export interface DeviceCaptureStatus {
  state: DeviceState;
  permission: PermissionState;
  problem: MediaProblem | null;
}

export interface CaptureStatus {
  camera: DeviceCaptureStatus;
  microphone: DeviceCaptureStatus;
  /** A preview surface is mounted; this does not indicate an active camera or attached stream. */
  previewMounted: boolean;
}

export interface VideoFrame {
  bytes: ArrayBuffer;
  mime: 'image/jpeg' | 'image/webp';
  width: number;
  height: number;
  sequence: number;
  timestamp: number;
}

export interface AudioChunk {
  bytes: ArrayBuffer;
  mime: 'audio/wav' | 'audio/mpeg';
  sampleRate: number;
  channels: 1;
  sequence: number;
  timestamp: number;
  durationMs: number | null;
}

export interface CameraOption { deviceId: string; label: string }
export interface AudioInputLevel { level: number | null; timestamp: number }

export interface CaptureConfig {
  framesPerSecond: number;
  maxWidth: number;
  maxHeight: number;
  maxFrameBytes: number;
  maxAudioBytes: number;
  audioChunkMs: number;
}

export const DEFAULT_CAPTURE_CONFIG: Readonly<CaptureConfig> = Object.freeze({
  framesPerSecond: 2, maxWidth: 640, maxHeight: 480,
  maxFrameBytes: 200 * 1024, maxAudioBytes: 128 * 1024, audioChunkMs: 1000,
});

export function captureConfig(options: Partial<CaptureConfig> = {}): Readonly<CaptureConfig> {
  const config = { ...DEFAULT_CAPTURE_CONFIG, ...options };
  if (!Object.values(config).every(Number.isFinite)
    || config.framesPerSecond < 1 || config.framesPerSecond > 4
    || !Number.isInteger(config.maxWidth) || config.maxWidth < 16 || config.maxWidth > 640
    || !Number.isInteger(config.maxHeight) || config.maxHeight < 16 || config.maxHeight > 480
    || !Number.isInteger(config.maxFrameBytes) || config.maxFrameBytes < 1024 || config.maxFrameBytes > 200 * 1024
    || !Number.isInteger(config.maxAudioBytes) || config.maxAudioBytes < 1024 || config.maxAudioBytes > 128 * 1024
    || config.audioChunkMs < 500 || config.audioChunkMs > 2000) {
    throw new RangeError('Media capture limits are invalid');
  }
  return Object.freeze(config);
}

export function idleCaptureStatus(): CaptureStatus {
  return {
    camera: { state: 'off', permission: 'unknown', problem: null },
    microphone: { state: 'off', permission: 'unknown', problem: null },
    previewMounted: false,
  };
}

export class MediaCaptureError extends Error {
  constructor(public readonly code: MediaProblem) {
    super(code);
    this.name = 'MediaCaptureError';
  }
}

/**
 * Platform APIs and raw bytes stay behind this boundary; subscribers must not retain bytes.
 * Each adapter must invalidate device epochs synchronously on stop. Late permission grants,
 * frames, recorder callbacks and errors from older epochs must never reach subscribers or
 * change a newer run's status. Subscriber failure must not prevent resource cleanup.
 */
export interface MediaCaptureAdapter {
  startCamera(facing?: CameraFacing, deviceId?: string): Promise<void>;
  stopCamera(): Promise<void>;
  startMicrophone(): Promise<void>;
  stopMicrophone(): Promise<void>;
  stopAll(): Promise<void>;
  getStatus(): CaptureStatus;
  subscribeStatus(listener: (status: CaptureStatus) => void): () => void;
  subscribeVideoFrame(listener: (frame: VideoFrame) => void): () => void;
  subscribeAudioChunk(listener: (chunk: AudioChunk) => void): () => void;
  subscribeAudioLevel(listener: (input: AudioInputLevel) => void): () => void;
  /** Enumerate only after a user permission grant; never sends labels or identifiers anywhere. */
  listCameras(): Promise<CameraOption[]>;
  bindPreview(target: unknown | null): void;
  previewReady(): void;
  previewError(error: unknown): void;
  dispose(): Promise<void>;
}

export interface MediaSelection {
  camera: boolean;
  microphone: boolean;
  facing: CameraFacing;
  cameraDeviceId?: string;
}

export type MediaStopReason = 'user' | 'background' | 'offline' | 'source_change' | 'unmount'
  | 'device_error' | 'timeout';

export interface MediaSessionState {
  phase: 'idle' | 'starting' | 'active' | 'stopping' | 'error';
  capture: CaptureStatus;
  selection: MediaSelection;
  problem: MediaProblem | 'nothing_selected' | null;
  stoppedReason: MediaStopReason | null;
  videoFrames: number;
  audioChunks: number;
  inputLevel: number | null;
}

export interface MediaSessionContext {
  source: 'real' | 'demo';
  connection: 'connecting' | 'online' | 'offline' | 'error';
  visible: boolean;
  /** Actual transport availability, independent of an unconnected emotion service. */
  networkOnline?: boolean;
}
