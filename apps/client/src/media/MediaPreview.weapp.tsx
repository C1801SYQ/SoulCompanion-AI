import { useEffect, useRef } from 'react';
import { Camera, Canvas, Text, View } from '@tarojs/components';
import type { MediaPreviewProps } from './MediaPreview.h5';

function ActiveCamera({ adapter, facing }: Pick<MediaPreviewProps, 'adapter' | 'facing'>) {
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    adapter.bindPreview({ cameraId: 'sc-device-camera', canvasId: 'sc-media-encoding' });
    return () => { live.current = false; adapter.bindPreview(null); };
  }, [adapter]);
  return <>
    <Camera id="sc-device-camera" mode="normal" frameSize="small" devicePosition={facing === 'user' ? 'front' : 'back'}
      flash="off" style={{ width: '100%', height: '240px' }}
      onInitDone={() => { if (live.current) adapter.previewReady(); }}
      onError={event => { if (live.current) adapter.previewError(event.detail); }}
      onStop={() => { if (live.current) adapter.previewError({ errMsg: 'camera stopped' }); }} />
    <Canvas canvasId="sc-media-encoding" width="640" height="480"
      style={{ position: 'fixed', left: '-10000px', top: '0px', width: '640px', height: '480px' }} />
  </>;
}

export function MediaPreview({ adapter, status, facing }: MediaPreviewProps) {
  const active = status.camera.state === 'requesting' || status.camera.state === 'on';
  return <View className="sc-preview" id="media-preview">
    {active ? <ActiveCamera key={facing} adapter={adapter} facing={facing} />
      : <><Text className="sc-preview-title">你的陪伴空间</Text><Text className="sc-preview-caption">摄像头未启用 · 没有预览画面</Text></>}
  </View>;
}
