/**
 * Reprodução da resposta TTS no navegador.
 * O elemento é “primado” num gesto do utilizador (clique/mic) para contornar autoplay.
 */

const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

let player: HTMLAudioElement | null = null;
let audioCtx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let mediaSource: MediaElementAudioSourceNode | null = null;
let freqBuf = new Uint8Array(0);
let timeBuf = new Uint8Array(0);
let energyRaf = 0;
let energyFn: ((e: number) => void) | null = null;
let envSmooth = 0;

function getPlayer(): HTMLAudioElement {
  if (!player) player = new Audio();
  return player;
}

function setupGraph(): void {
  if (audioCtx) return;
  const a = getPlayer();
  audioCtx = new AudioContext();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512;
  analyser.smoothingTimeConstant = 0.55;
  mediaSource = audioCtx.createMediaElementSource(a);
  mediaSource.connect(analyser);
  analyser.connect(audioCtx.destination);
  freqBuf = new Uint8Array(analyser.frequencyBinCount);
  timeBuf = new Uint8Array(analyser.fftSize);
}

/** Energia 0–1 da faixa vocal + envelope (RMS), atualizada a cada frame. */
function measureEnergy(): number {
  if (!analyser) return 0;
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

  const raw = Math.min(1, Math.max(0, rms * 3.8 + vocal * 1.4 - 0.05));
  // envelope assimétrico: sobe rápido, desce devagar
  const k = raw > envSmooth ? 0.38 : 0.11;
  envSmooth += (raw - envSmooth) * k;
  return envSmooth;
}

function startEnergyLoop(fn: (e: number) => void): void {
  stopEnergyLoop();
  energyFn = fn;
  const tick = () => {
    energyRaf = requestAnimationFrame(tick);
    fn(measureEnergy());
  };
  tick();
}

function stopEnergyLoop(): void {
  cancelAnimationFrame(energyRaf);
  energyRaf = 0;
  envSmooth = 0;
  if (energyFn) {
    energyFn(0);
    energyFn = null;
  }
}

/** Chamar no clique Enviar, ligar microfone ou wake «Tina». */
export function unlockResponseAudio(): void {
  const a = getPlayer();
  a.src = SILENT_WAV;
  void a.play().then(() => a.pause()).catch(() => {});
  setupGraph();
  void audioCtx?.resume();
}

export function playResponseAudio(
  url: string,
  onEnergy?: (e: number) => void,
): Promise<void> {
  setupGraph();
  void audioCtx?.resume();
  if (onEnergy) startEnergyLoop(onEnergy);

  const a = getPlayer();
  a.src = url;
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      a.removeEventListener("ended", onEnded);
      a.removeEventListener("error", onError);
    };
    const onEnded = () => {
      cleanup();
      stopEnergyLoop();
      resolve();
    };
    const onError = () => {
      cleanup();
      stopEnergyLoop();
      reject(new Error("Falha ao carregar o áudio"));
    };
    a.addEventListener("ended", onEnded);
    a.addEventListener("error", onError);
    void a.play().catch((err) => {
      cleanup();
      stopEnergyLoop();
      reject(err);
    });
  });
}

export function stopResponseAudio(): void {
  stopEnergyLoop();
  if (!player) return;
  player.pause();
  player.currentTime = 0;
}
