/**
 * Palavra de ativação "Tina" — uma única instância SpeechRecognition,
 * sem recriar em loop (evita travar o browser / sistema).
 */

import { micLog } from "./log";

const WAKE_VARIANTS =
  "tina|thina|cretina|china|tinha|quina|teena|tyna|tema|dina";

const WAKE_RE = new RegExp(`\\b(${WAKE_VARIANTS})\\b`, "i");

const WAKE_STRIP_RE = new RegExp(
  `^(\\s*(ei|olá|ola|hey)\\s+)?(${WAKE_VARIANTS})\\s*[\\s,.\\-:!?]*`,
  "i",
);

/** Mínimo entre recognition.start() após onend (Chrome exige restart, mas não em rajada). */
const MIN_RESTART_MS = 1200;

export type WakePhase = "off" | "waiting_wake" | "waiting_command";

export interface WakeListenerCallbacks {
  onPhase?: (phase: WakePhase) => void;
  onWake?: () => void;
  onCommand?: (text: string, novaSessao: boolean) => void;
  onError?: (message: string) => void;
  onInterim?: (text: string, meta?: { final: string; interim: string; wake: boolean }) => void;
  onStatus?: (status: string) => void;
}

type SpeechRecognitionCtor = new () => SpeechRecognition;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function isSpeechRecognitionSupported(): boolean {
  return getRecognitionCtor() !== null;
}

export function stripWakePrefix(text: string): string {
  return text.replace(WAKE_STRIP_RE, "").trim();
}

export function containsWakeWord(text: string): boolean {
  return WAKE_RE.test(text);
}

function parseResults(ev: SpeechRecognitionEvent): {
  final: string;
  interim: string;
  combined: string;
} {
  let final = "";
  let interim = "";
  for (let i = ev.resultIndex; i < ev.results.length; i++) {
    const t = ev.results[i][0]?.transcript ?? "";
    if (ev.results[i].isFinal) final += t;
    else interim += t;
  }
  const combined = `${final} ${interim}`.trim();
  return { final: final.trim(), interim: interim.trim(), combined };
}

export class WakeListener {
  private rec: SpeechRecognition | null = null;
  private phase: WakePhase = "off";
  private expectCommand = false;
  private novaOnNextCommand = true;
  private stopping = false;
  private restartTimer: ReturnType<typeof setTimeout> | null = null;
  private lastRestartAt = 0;
  private rapidRestarts = 0;
  private lastInterimLogAt = 0;

  constructor(private readonly cb: WakeListenerCallbacks) {}

  getPhase(): WakePhase {
    return this.phase;
  }

  start(): void {
    if (!getRecognitionCtor()) {
      const msg =
        "Reconhecimento de voz não suportado. Use Chrome ou Edge e permita o microfone.";
      micLog.error(msg);
      this.cb.onError?.(msg);
      return;
    }
    this.stopping = false;
    this.novaOnNextCommand = true;
    this.expectCommand = false;
    micLog.info("Iniciando escuta (instância única)");
    this.cb.onStatus?.("Iniciando microfone…");
    this.attachRecognition();
  }

  stop(): void {
    this.stopping = true;
    this.clearRestartTimer();
    micLog.info("Escuta parada");
    this.setPhase("off");
    this.expectCommand = false;
    this.abortRec();
    this.cb.onStatus?.("Microfone desligado");
  }

  private attachRecognition(): void {
    this.abortRec();
    const Ctor = getRecognitionCtor()!;
    this.rec = new Ctor();
    this.rec.lang = "pt-BR";
    this.rec.continuous = true;
    this.rec.interimResults = true;
    this.setPhase(this.expectCommand ? "waiting_command" : "waiting_wake");

    this.rec.onstart = () => {
      this.rapidRestarts = 0;
      micLog.info("onstart — microfone ativo");
      this.cb.onStatus?.(
        this.expectCommand ? "Diga o pedido…" : "Microfone ativo — diga «Tina»",
      );
    };

    this.rec.onresult = (ev: SpeechRecognitionEvent) => {
      const { final, interim, combined } = parseResults(ev);
      if (!combined) return;

      const now = Date.now();
      if (now - this.lastInterimLogAt > 400) {
        this.lastInterimLogAt = now;
        micLog.debug("onresult", {
          expectCommand: this.expectCommand,
          final,
          interim,
          combined,
          wake: containsWakeWord(combined),
        });
      }

      if (!this.expectCommand) {
        this.handleWakePhase(combined, final, interim);
      } else {
        this.handleCommandPhase(combined, final);
      }
    };

    this.rec.onerror = (ev: SpeechRecognitionErrorEvent) => {
      if (this.stopping) return;
      micLog.warn("onerror", { error: ev.error, message: ev.message });
      if (ev.error === "no-speech") {
        this.cb.onStatus?.("Silêncio — pode falar");
        return;
      }
      if (ev.error === "aborted") return;
      if (ev.error === "not-allowed") {
        this.cb.onError?.("Microfone bloqueado nas definições do browser.");
        this.stop();
        return;
      }
      this.scheduleRecognitionRestart("erro");
    };

    this.rec.onend = () => {
      if (this.stopping || this.phase === "off") return;
      micLog.debug("onend — reagendar start");
      this.scheduleRecognitionRestart("onend");
    };

    this.tryStart("inicial");
  }

  private handleWakePhase(
    combined: string,
    final: string,
    interim: string,
  ): void {
    const wake = containsWakeWord(combined);
    this.cb.onInterim?.(combined, { final, interim, wake });

    if (!wake) {
      this.cb.onStatus?.(`Ouvi: «${combined.slice(0, 40)}»`);
      return;
    }

    const rest = stripWakePrefix(combined);
    micLog.info("Wake detectada", { rest });
    this.cb.onWake?.();

    if (rest.length >= 3) {
      this.dispatchCommand(rest);
      return;
    }

    this.expectCommand = true;
    this.setPhase("waiting_command");
    this.cb.onStatus?.("«Tina» OK — diga o pedido");
  }

  private handleCommandPhase(combined: string, final: string): void {
    this.cb.onInterim?.(combined, { final, interim: "", wake: false });
    const text = (final || combined).trim();
    if (text.length < 2) return;

    const cmd = stripWakePrefix(text).trim();
    if (cmd.length >= 2) {
      this.dispatchCommand(cmd);
    }
  }

  private dispatchCommand(cmd: string): void {
    micLog.info("Comando", { cmd });
    this.cb.onCommand?.(cmd, this.novaOnNextCommand);
    this.novaOnNextCommand = false;
    this.expectCommand = false;
    this.setPhase("waiting_wake");
    this.cb.onStatus?.("Aguardando «Tina»…");
  }

  private scheduleRecognitionRestart(reason: string): void {
    if (this.stopping || this.phase === "off") return;

    this.rapidRestarts += 1;
    if (this.rapidRestarts > 8) {
      micLog.error("Muitos restarts seguidos — microfone pausado", { reason });
      this.cb.onError?.(
        "Microfone pausado (loop detectado). Clique «Ouvir Tina» de novo.",
      );
      this.stop();
      return;
    }

    const now = Date.now();
    const wait = Math.max(MIN_RESTART_MS, MIN_RESTART_MS * this.rapidRestarts * 0.3);
    const delay = Math.max(wait - (now - this.lastRestartAt), 300);

    this.clearRestartTimer();
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (this.stopping || this.phase === "off") return;
      this.lastRestartAt = Date.now();
      this.tryStart(reason);
    }, delay);
  }

  private tryStart(reason: string): void {
    if (!this.rec || this.stopping) return;
    try {
      this.rec.start();
      micLog.debug("start()", { reason });
    } catch (e) {
      const err = e as Error;
      if (err.name === "InvalidStateError") {
        micLog.debug("start() ignorado (já a correr)");
        return;
      }
      micLog.error("start() falhou", { reason, message: err.message });
      this.scheduleRecognitionRestart("start-fail");
    }
  }

  private clearRestartTimer(): void {
    if (this.restartTimer !== null) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
  }

  private abortRec(): void {
    this.clearRestartTimer();
    if (!this.rec) return;
    try {
      this.rec.onstart = null;
      this.rec.onresult = null;
      this.rec.onend = null;
      this.rec.onerror = null;
      this.rec.stop();
    } catch {
      /* ignore */
    }
    this.rec = null;
  }

  private setPhase(phase: WakePhase): void {
    if (this.phase !== phase) {
      micLog.info(`Fase → ${phase}`);
    }
    this.phase = phase;
    this.cb.onPhase?.(phase);
  }
}
