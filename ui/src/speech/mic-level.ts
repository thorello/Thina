/**
 * Nível do microfone em tempo real (Web Audio) para animar a galáxia enquanto o
 * utilizador fala durante a escuta de comando.
 */

let audioCtx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let stream: MediaStream | null = null;
let source: MediaStreamAudioSourceNode | null = null;
let freqBuf = new Uint8Array(0);
let timeBuf = new Uint8Array(0);
let energyRaf = 0;
let energyFn: ((frame: MicLevelFrame) => void) | null = null;
let envSmooth = 0;
let starting: Promise<void> | null = null;

export const MIC_WAVEFORM_SAMPLES = 14;
const waveformOut = new Float32Array(MIC_WAVEFORM_SAMPLES);

export interface MicLevelFrame {
  energy: number;
  waveform: Float32Array;
}

/** Energia 0–1 + amostras temporais do microfone. */
function measureFrame(): MicLevelFrame {
  if (!analyser) {
    return { energy: 0, waveform: waveformOut };
  }
  analyser.getByteFrequencyData(freqBuf);
  analyser.getByteTimeDomainData(timeBuf);

  const vStart = 2;
  const vEnd = Math.min(45, freqBuf.length);
  let vocal = 0;
  for (let i = vStart; i < vEnd; i++) vocal += freqBuf[i];
  vocal /= (vEnd - vStart) * 255;

  let rms = 0;
  for (let i = 0; i < timeBuf.length; i++) {
    const v = (timeBuf[i] - 128) / 128;
    rms += v * v;
  }
  rms = Math.sqrt(rms / timeBuf.length);

  const raw = Math.min(1, Math.max(0, rms * 4.2 + vocal * 1.6 - 0.04));
  const k = raw > envSmooth ? 0.42 : 0.14;
  envSmooth += (raw - envSmooth) * k;

  const step = timeBuf.length / MIC_WAVEFORM_SAMPLES;
  for (let i = 0; i < MIC_WAVEFORM_SAMPLES; i++) {
    const idx = Math.min(timeBuf.length - 1, Math.floor(i * step + step * 0.5));
    waveformOut[i] = (timeBuf[idx] - 128) / 128;
  }

  return { energy: envSmooth, waveform: waveformOut };
}

function startEnergyLoop(fn: (frame: MicLevelFrame) => void): void {
  stopEnergyLoop();
  energyFn = fn;
  const tick = () => {
    energyRaf = requestAnimationFrame(tick);
    fn(measureFrame());
  };
  tick();
}

function stopEnergyLoop(): void {
  cancelAnimationFrame(energyRaf);
  energyRaf = 0;
  envSmooth = 0;
  waveformOut.fill(0);
  if (energyFn) {
    energyFn({ energy: 0, waveform: waveformOut });
    energyFn = null;
  }
}

function teardownStream(): void {
  stopEnergyLoop();
  source?.disconnect();
  source = null;
  analyser?.disconnect();
  analyser = null;
  if (stream) {
    for (const track of stream.getTracks()) track.stop();
    stream = null;
  }
}

/** Liga captura do microfone e emite energia + espectro a cada frame. */
export function startMicLevel(onFrame: (frame: MicLevelFrame) => void): Promise<void> {
  if (starting) return starting;

  starting = (async () => {
    teardownStream();
    if (!audioCtx) audioCtx = new AudioContext();
    await audioCtx.resume();

    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });

    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.45;
    freqBuf = new Uint8Array(analyser.frequencyBinCount);
    timeBuf = new Uint8Array(analyser.fftSize);

    source = audioCtx.createMediaStreamSource(stream);
    source.connect(analyser);
    startEnergyLoop(onFrame);
  })();

  return starting.finally(() => {
    starting = null;
  });
}

export function stopMicLevel(): void {
  starting = null;
  teardownStream();
}

export function isMicLevelActive(): boolean {
  return stream !== null;
}
