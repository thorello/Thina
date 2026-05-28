/** Logs do microfone / Web Speech API — prefixo único no DevTools. */

export const MIC_LOG_PREFIX = "[Thina Mic]";

export type MicLogLevel = "debug" | "info" | "warn" | "error";

export interface MicLogEntry {
  time: string;
  level: MicLogLevel;
  message: string;
  data?: unknown;
}

type LogSink = (entry: MicLogEntry) => void;

const sinks: LogSink[] = [];
const history: MicLogEntry[] = [];
const MAX_HISTORY = 80;

function enabled(level: MicLogLevel): boolean {
  if (level !== "debug") return true;
  try {
    if (localStorage.getItem("thina.ui.micDebug") === "0") return false;
  } catch {
    /* ignore */
  }
  return true;
}

function emit(level: MicLogLevel, message: string, data?: unknown): void {
  const entry: MicLogEntry = {
    time: new Date().toLocaleTimeString("pt-BR", { hour12: false }),
    level,
    message,
    data,
  };
  history.push(entry);
  if (history.length > MAX_HISTORY) history.shift();

  if (!enabled(level)) return;

  const tag = `${MIC_LOG_PREFIX} ${entry.time}`;
  const payload = data !== undefined ? [tag, message, data] : [tag, message];
  switch (level) {
    case "debug":
      console.debug(...payload);
      break;
    case "info":
      console.info(...payload);
      break;
    case "warn":
      console.warn(...payload);
      break;
    case "error":
      console.error(...payload);
      break;
  }

  for (const sink of sinks) sink(entry);
}

/** UI: só info/warn/error (debug só no Console — evita travar o DOM). */
export function subscribeMicLogUi(sink: LogSink): () => void {
  const wrapped: LogSink = (entry) => {
    if (entry.level === "debug") return;
    sink(entry);
  };
  return micLog.subscribe(wrapped);
}

export const micLog = {
  debug: (message: string, data?: unknown) => emit("debug", message, data),
  info: (message: string, data?: unknown) => emit("info", message, data),
  warn: (message: string, data?: unknown) => emit("warn", message, data),
  error: (message: string, data?: unknown) => emit("error", message, data),
  subscribe: (sink: LogSink) => {
    sinks.push(sink);
    return () => {
      const i = sinks.indexOf(sink);
      if (i >= 0) sinks.splice(i, 1);
    };
  },
  getHistory: () => [...history],
  clearHistory: () => {
    history.length = 0;
  },
};

export function logSpeechSupport(): void {
  const w = window as Window & {
    SpeechRecognition?: unknown;
    webkitSpeechRecognition?: unknown;
  };
  micLog.info("Ambiente de voz", {
    speechRecognition: !!(w.SpeechRecognition ?? w.webkitSpeechRecognition),
    userAgent: navigator.userAgent.slice(0, 80),
    secureContext: window.isSecureContext,
    protocol: location.protocol,
  });
  if (!window.isSecureContext && location.hostname !== "localhost") {
    micLog.warn(
      "Microfone em páginas HTTP (não localhost) costuma ser bloqueado. Use https ou localhost.",
    );
  }
}
