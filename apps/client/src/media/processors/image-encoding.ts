import { frameDimensions } from './image';

export type EncodedImageMime = 'image/jpeg' | 'image/webp';

export function encodedImageMime(buffer: ArrayBuffer): EncodedImageMime | null {
  const bytes = new Uint8Array(buffer);
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg';
  if (bytes.length >= 12 && String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF'
    && String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP') return 'image/webp';
  return null;
}

/** Canvas encoding is real; never relabel a browser's PNG fallback as JPEG. */
export async function encodeVideoFrame(video: HTMLVideoElement, canvas: HTMLCanvasElement,
  maxBytes = 200 * 1024, maxEdge = 640, maxHeight = maxEdge): Promise<{
    bytes: ArrayBuffer; mimeType: EncodedImageMime; width: number; height: number;
  }> {
  const size = frameDimensions(video.videoWidth, video.videoHeight, maxEdge, maxHeight);
  canvas.width = size.width; canvas.height = size.height;
  const context = canvas.getContext('2d', { alpha: false });
  if (!context) throw new Error('Image encoding is unavailable');
  context.drawImage(video, 0, 0, size.width, size.height);
  for (const mimeType of ['image/jpeg', 'image/webp'] as const) {
    for (const quality of [0.75, 0.5, 0.3]) {
      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, mimeType, quality));
      if (!blob || blob.type !== mimeType) break;
      if (blob.size > maxBytes) continue;
      const bytes = await blob.arrayBuffer();
      if (!bytes.byteLength || bytes.byteLength > maxBytes || encodedImageMime(bytes) !== mimeType) {
        throw new Error('Image encoding did not produce its declared format');
      }
      return { ...size, bytes, mimeType };
    }
  }
  throw new Error('No bounded JPEG or WebP encoding is available');
}
