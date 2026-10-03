import { useCallback, useEffect } from 'react';
import { Text, View } from '@tarojs/components';
import type { CameraFacing, CaptureStatus, MediaCaptureAdapter } from './types';

export interface MediaPreviewProps { adapter: MediaCaptureAdapter; status: CaptureStatus; facing: CameraFacing }

export function MediaPreview({ adapter, status }: MediaPreviewProps) {
  const bind = useCallback((target: HTMLVideoElement | null) => adapter.bindPreview(target), [adapter]);
  useEffect(() => () => adapter.bindPreview(null), [adapter]);
  const mounted = status.camera.state === 'requesting' || status.camera.state === 'on';
  return <View className="sc-preview" id="media-preview">
    {mounted ? <video id="media-preview-video" ref={bind} autoPlay muted playsInline
      aria-label="本次摄像头预览" style={{ display: 'block', width: '100%', maxHeight: '360px', objectFit: 'contain' }}
      onLoadedMetadata={() => adapter.previewReady()} onError={event => adapter.previewError(event)} />
      : <><View className="sc-preview-outline" ariaHidden><View className="sc-preview-person" /></View>
        <Text className="sc-preview-title">你的陪伴空间</Text><Text className="sc-preview-caption">摄像头未启用 · 没有预览画面</Text></>}
  </View>;
}
