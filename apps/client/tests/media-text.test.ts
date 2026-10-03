import { describe, expect, it } from 'vitest';
import { deviceText, mediaProblemText, permissionText, previewText, sessionText, stoppedSessionText, stoppedText } from '../src/components/mediaText';
import { idleCaptureStatus, type MediaSessionState } from '../src/media/types';

describe('honest media status text', () => {
  it('never treats a permission grant or a pending request as an active device', () => {
    expect(deviceText('Camera', { state: 'off', permission: 'granted', problem: null })).toContain('Camera OFF');
    expect(deviceText('Mic', { state: 'requesting', permission: 'unknown', problem: null })).toBe('Mic REQUESTING · 等待权限');
    expect(deviceText('Camera', { state: 'on', permission: 'granted', problem: null })).toBe('Camera ON · 本机采集');
  });

  it('keeps denied permission visible after the device has been released', () => {
    const denied = { state: 'off', permission: 'denied', problem: null } as const;
    expect(deviceText('Camera', denied)).toContain('权限被拒绝');
    expect(permissionText(denied)).toBe('未获准');
    expect(mediaProblemText('permission_denied')).toContain('权限没有获准');
  });

  it('shows a new missing-device failure before an older denied-permission record', () => {
    expect(deviceText('Camera', { state: 'off', permission: 'denied', problem: 'device_missing' }))
      .toBe('Camera UNAVAILABLE · 未找到设备');
    expect(deviceText('Camera', { state: 'missing', permission: 'denied', problem: 'device_missing' }))
      .toBe('Camera UNAVAILABLE · 未找到设备');
  });

  it('explains unreadable devices without claiming occupation is certain', () => {
    expect(mediaProblemText('device_in_use')).toContain('可能被占用或暂时不可用');
    expect(mediaProblemText('device_in_use')).toContain('确认设备连接');
  });

  it('labels active local capture without claiming uploaded media or inference', () => {
    const state: MediaSessionState = {
      phase: 'active', capture: idleCaptureStatus(), selection: { camera: true, microphone: false, facing: 'user' },
      problem: null, stoppedReason: null, videoFrames: 1, audioChunks: 0, inputLevel: null,
    };
    expect(sessionText(state)).toBe('正在本机采集 · 未上传');
    expect(mediaProblemText(null)).toBe('');
  });

  it.each(['background', 'offline', 'source_change'] as const)(
    'makes %s stop require a new user action', reason => {
      expect(stoppedText(reason)).toMatch(/再次|主动开始/);
    },
  );

  it('explains that a late permission grant cannot resume a user cancellation', () => {
    expect(stoppedText('user')).toContain('即使稍后获准');
    expect(stoppedText('user')).toContain('不会继续');
  });

  it.each(['denied', 'missing', 'error'] as const)('distinguishes %s from an intentionally OFF device', state => {
    expect(deviceText('Camera', { state, permission: 'unknown', problem: null })).not.toContain(' OFF');
  });

  it('never claims completed cleanup when the platform cannot confirm release', () => {
    const state: MediaSessionState = {
      phase: 'error', capture: idleCaptureStatus(), selection: { camera: true, microphone: true, facing: 'user' },
      problem: 'cleanup_failed', stoppedReason: 'user', videoFrames: 0, audioChunks: 0, inputLevel: null,
    };
    expect(sessionText(state)).toContain('待确认');
    expect(previewText(state)).toContain('待确认');
    expect(stoppedSessionText(state)).toBe('');
    expect(deviceText('Camera', { state: 'error', permission: 'granted', problem: 'cleanup_failed' })).toContain('释放待确认');
    expect(stoppedSessionText({ ...state, phase: 'stopping', problem: null })).toBe('');
    expect(stoppedSessionText({ ...state, phase: 'idle', problem: null })).toContain('已停止');
  });
});
