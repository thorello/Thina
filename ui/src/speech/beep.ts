/**
 * Bip curto ao reconhecer «Tina» — sinal para o utilizador falar o pedido.
 * Web Audio API (sem ficheiros externos).
 */

let ctx: AudioContext | null = null;

function getCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctx =
    window.AudioContext ??
    (window as Window & { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!Ctx) return null;
  if (!ctx) ctx = new Ctx();
  return ctx;
}

/** Chamar no clique que liga o microfone (desbloqueia áudio no browser). */
export function unlockWakeBeep(): void {
  const ac = getCtx();
  if (ac?.state === "suspended") void ac.resume();
}

/** Dois tons ascendentes (~150 ms) — confirmação de wake word. */
export function playWakeBeep(): void {
  const ac = getCtx();
  if (!ac) return;
  if (ac.state === "suspended") void ac.resume();

  const t0 = ac.currentTime;
  const tones = [
    { freq: 523.25, at: 0, dur: 0.09 },
    { freq: 659.25, at: 0.1, dur: 0.11 },
  ];

  for (const { freq, at, dur } of tones) {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, t0 + at);
    gain.gain.setValueAtTime(0.0001, t0 + at);
    gain.gain.exponentialRampToValueAtTime(0.12, t0 + at + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + at + dur);
    osc.connect(gain);
    gain.connect(ac.destination);
    osc.start(t0 + at);
    osc.stop(t0 + at + dur + 0.02);
  }
}
