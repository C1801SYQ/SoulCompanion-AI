/** One bounded mono PCM16 WAV block. The header always uses the actual capture rate. */
export function encodeMonoWav(samples: Int16Array, sampleRate: number, maxBytes = 128 * 1024): ArrayBuffer {
  if (!Number.isInteger(sampleRate) || sampleRate < 8000 || sampleRate > 192000) {
    throw new Error('Unsupported audio sample rate');
  }
  const length = 44 + samples.length * 2;
  if (!samples.length || length > maxBytes) throw new Error('Audio block exceeds its byte limit');
  const buffer = new ArrayBuffer(length);
  const view = new DataView(buffer);
  const word = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index++) view.setUint8(offset + index, value.charCodeAt(index));
  };
  word(0, 'RIFF'); view.setUint32(4, length - 8, true); word(8, 'WAVE');
  word(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  word(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index++) view.setInt16(44 + index * 2, samples[index], true);
  return buffer;
}
