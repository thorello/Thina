export interface HealthInfo {
  status: string;
  service: string;
  llm_provider: string;
  llm_model: string;
  kokoro_voice: string;
  kokoro_speed: string;
  kokoro_mix_voice?: string;
  kokoro_mix_amount?: string;
  kokoro_sentiment: string;
  areas?: string[];
  ha_ok?: boolean;
  ha_url?: string;
}

export interface TtsSettings {
  voice: string;
  mix_voice: string | null;
  mix_amount: number;
  speed: number;
  sentiment: string;
  voices: string[];
}

export interface ConversarResult {
  resposta: string;
  audio_url: string;
  area_id: string;
  media_player: string;
  session_id: string;
}

export interface UiSettings {
  /** Vazio = mesmo origin (Vite proxy ou FastAPI na mesma porta). */
  apiBase: string;
  areaId: string;
  autoPlayAudio: boolean;
  wakeWordEnabled: boolean;
}

const SETTINGS_KEY = "thina.ui.settings";

const DEFAULT_AREAS = ["sala", "quarto", "cozinha"];

const DEFAULT_SETTINGS: UiSettings = {
  apiBase: "",
  areaId: "sala",
  autoPlayAudio: true,
  wakeWordEnabled: true,
};

const LEGACY_DEV_BASES = [
  "http://127.0.0.1:8080",
  "http://localhost:8080",
  "http://127.0.0.1:8081",
  "http://localhost:8081",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
];

export function loadSettings(): UiSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<UiSettings>;
    let apiBase = normalizeApiBase((parsed.apiBase ?? "").trim());
    if (isViteDev() && LEGACY_DEV_BASES.includes(apiBase)) {
      apiBase = "";
    }
    return {
      ...DEFAULT_SETTINGS,
      apiBase,
      areaId: parsed.areaId || DEFAULT_SETTINGS.areaId,
      autoPlayAudio: parsed.autoPlayAudio ?? true,
      wakeWordEnabled: parsed.wakeWordEnabled ?? false,
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(s: UiSettings): void {
  localStorage.setItem(
    SETTINGS_KEY,
    JSON.stringify({
      ...s,
      apiBase: normalizeApiBase(s.apiBase.trim()),
    }),
  );
}

function normalizeApiBase(base: string): string {
  return base.replace(/\/$/, "").replace(/\/ui$/i, "");
}

function isViteDev(): boolean {
  return (
    typeof window !== "undefined" &&
    window.location.port === "5173" &&
    (window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1")
  );
}

/** URL absoluta da API (evita /ui/v1/... quando a página está em /ui/). */
export function apiUrl(settings: UiSettings, path: string): string {
  const segment = path.startsWith("/") ? path : `/${path}`;
  const base = normalizeApiBase(settings.apiBase);
  if (base) return `${base}${segment}`;
  return new URL(segment, window.location.origin).href;
}

export async function fetchHealth(settings: UiSettings): Promise<HealthInfo> {
  const res = await fetch(apiUrl(settings, "/health"));
  if (!res.ok) throw new Error(`Health ${res.status}`);
  return res.json() as Promise<HealthInfo>;
}

export async function fetchTtsSettings(settings: UiSettings): Promise<TtsSettings> {
  const res = await fetch(apiUrl(settings, "/v1/tts/settings"));
  if (!res.ok) throw new Error(`TTS settings ${res.status}`);
  return res.json() as Promise<TtsSettings>;
}

export async function saveTtsSettings(
  settings: UiSettings,
  tts: Pick<TtsSettings, "voice" | "mix_voice" | "mix_amount" | "speed">,
): Promise<TtsSettings> {
  const res = await fetch(apiUrl(settings, "/v1/tts/settings"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      voice: tts.voice,
      mix_voice: tts.mix_voice || null,
      mix_amount: tts.mix_amount,
      speed: tts.speed,
    }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const err = (await res.json()) as { detail?: string };
      if (err.detail) detail = err.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<TtsSettings>;
}

export async function fetchAreas(settings: UiSettings): Promise<string[]> {
  try {
    const res = await fetch(apiUrl(settings, "/v1/areas"));
    if (res.ok) {
      const data = (await res.json()) as { areas: string[] };
      if (data.areas?.length) return data.areas;
    }
  } catch {
    /* fallback abaixo */
  }

  try {
    const health = await fetchHealth(settings);
    if (health.areas?.length) return health.areas;
  } catch {
    /* fallback abaixo */
  }

  return [...DEFAULT_AREAS];
}

export async function conversar(
  settings: UiSettings,
  texto: string,
  sessionId: string | null,
  novaSessao: boolean,
  signal?: AbortSignal,
): Promise<ConversarResult> {
  const body: Record<string, unknown> = {
    texto,
    area_id: settings.areaId,
    nova_sessao: novaSessao,
    /** Painel web: áudio no browser; ReSpeaker fica para o fluxo via Home Assistant. */
    reproduzir_ha: false,
  };
  if (sessionId && !novaSessao) body.session_id = sessionId;

  const res = await fetch(apiUrl(settings, "/v1/conversar"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const err = (await res.json()) as { detail?: string };
      if (err.detail) detail = err.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  return res.json() as Promise<ConversarResult>;
}

const AUDIO_PATH_RE = /^\/v1\/audio\/[^/]+\.wav$/i;

/** Usa o mesmo host/proxy da API; ignora THINA_PUBLIC_URL (só para o Home Assistant). */
export function resolveAudioUrl(settings: UiSettings, audioUrl: string): string {
  const path = extractAudioPath(audioUrl);
  if (path) return apiUrl(settings, path);

  if (audioUrl.startsWith("http")) return audioUrl;
  const segment = audioUrl.startsWith("/") ? audioUrl : `/${audioUrl}`;
  const base = normalizeApiBase(settings.apiBase);
  if (base) return `${base}${segment}`;
  return new URL(segment, window.location.origin).href;
}

function extractAudioPath(audioUrl: string): string | null {
  const raw = audioUrl.trim();
  if (!raw.includes("/v1/audio/")) return null;
  try {
    const pathname = raw.startsWith("http")
      ? new URL(raw).pathname
      : raw.startsWith("/")
        ? raw.split("?")[0]!
        : `/${raw.split("?")[0]!}`;
    return AUDIO_PATH_RE.test(pathname) ? pathname : null;
  } catch {
    return null;
  }
}
