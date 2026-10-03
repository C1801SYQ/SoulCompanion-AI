/** Resize dimensions while preserving aspect ratio; never upscale a device frame. */
export function frameDimensions(width: number, height: number, maxEdge = 640, maxHeight = maxEdge): { width: number; height: number } {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0
    || width > 8192 || height > 8192 || !Number.isInteger(maxEdge) || maxEdge <= 0 || maxEdge > 640
    || !Number.isInteger(maxHeight) || maxHeight <= 0 || maxHeight > 640) {
    throw new Error('Invalid image dimensions');
  }
  const scale = Math.min(1, maxEdge / width, maxHeight / height);
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** CameraFrame is genuine RGBA; create only a bounded, downsampled owned copy. */
export function downsampleRgba(data: ArrayBuffer, width: number, height: number, maxEdge = 640, maxHeight = maxEdge): {
  data: Uint8ClampedArray; width: number; height: number;
} {
  const size = frameDimensions(width, height, maxEdge, maxHeight);
  if (data.byteLength !== width * height * 4) throw new Error('Camera frame byte length does not match its dimensions');
  const source = new Uint8Array(data);
  const target = new Uint8ClampedArray(size.width * size.height * 4);
  for (let y = 0; y < size.height; y++) {
    const sourceY = Math.min(height - 1, Math.floor(y * height / size.height));
    for (let x = 0; x < size.width; x++) {
      const sourceX = Math.min(width - 1, Math.floor(x * width / size.width));
      const from = (sourceY * width + sourceX) * 4;
      const to = (y * size.width + x) * 4;
      target[to] = source[from]; target[to + 1] = source[from + 1];
      target[to + 2] = source[from + 2]; target[to + 3] = source[from + 3];
    }
  }
  return { ...size, data: target };
}
