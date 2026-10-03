/* Static AudioWorklet asset: at most one pending block and one bounded accumulation. */
class SoulCompanionPcmProcessor extends AudioWorkletProcessor {
  constructor(options = {}) {
    super();
    this.running = true;
    this.pending = false;
    this.offset = 0;
    this.rate = sampleRate;
    const duration = options.processorOptions?.chunkMs ?? 1000;
    const maxBytes = options.processorOptions?.maxBytes ?? 128 * 1024;
    const frames = Math.round(this.rate * duration / 1000);
    if (!Number.isInteger(this.rate) || this.rate < 8000 || !Number.isFinite(duration)
      || duration < 250 || duration > 2000 || !Number.isInteger(maxBytes) || maxBytes > 128 * 1024
      || frames <= 0 || 44 + frames * 2 > maxBytes) {
      throw new Error('Audio worklet sample rate exceeds the bounded one-second format');
    }
    this.frames = frames;
    this.samples = new Int16Array(this.frames);
    this.port.onmessage = event => {
      if (event.data?.type === 'ack') this.pending = false;
      if (event.data?.type === 'stop') {
        this.running = false;
        this.samples.fill(0);
        this.offset = 0;
      }
    };
  }

  process(inputs) {
    if (!this.running) return false;
    const channels = inputs[0];
    if (!channels?.length || !channels[0]?.length) return true;
    const frames = channels[0].length;
    for (let index = 0; index < frames; index++) {
      let value = 0;
      for (const channel of channels) value += channel[index] || 0;
      value = Math.max(-1, Math.min(1, value / channels.length));
      this.samples[this.offset++] = Math.round(value < 0 ? value * 32768 : value * 32767);
      if (this.offset < this.samples.length) continue;
      if (this.pending) {
        this.running = false;
        this.samples.fill(0);
        this.offset = 0;
        this.port.postMessage({ type: 'overflow' });
        return false;
      }
      const buffer = this.samples.buffer;
      this.port.postMessage({ type: 'pcm', samples: buffer, sampleRate: this.rate }, [buffer]);
      this.pending = true;
      this.samples = new Int16Array(this.frames);
      this.offset = 0;
    }
    return true;
  }
}

registerProcessor('soulcompanion-pcm', SoulCompanionPcmProcessor);
