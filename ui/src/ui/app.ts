import {
  conversar,
  fetchAreas,
  fetchHealth,
  loadSettings,
  resolveAudioUrl,
  saveSettings,
  type HealthInfo,
  type UiSettings,
} from "../api/client";
import { animateSpeakingEnergy } from "../gl/orb";
import { playWakeFeedback, unlockWakeFeedback } from "../speech/feedback";
import {
  playResponseAudio,
  stopResponseAudio,
  unlockResponseAudio,
} from "../speech/response-audio";
import { micLog, subscribeMicLogUi, type MicLogEntry } from "../speech/log";
import {
  isSpeechRecognitionSupported,
  WakeListener,
} from "../speech/wake";
import {
  getState,
  setEnergy,
  setState,
  STATE_HINTS,
  STATE_LABELS,
  subscribe,
  type AssistantState,
} from "../state/assistant";

type ChatRole = "user" | "thina" | "system";

interface ChatMessage {
  role: ChatRole;
  text: string;
}

export interface ThinaUiControls {
  /** Para emergência: Esc, ou se o PC ficar lento. */
  emergencyStop: () => void;
}

export function mountApp(root: HTMLElement): ThinaUiControls {
  let settings = loadSettings();
  let sessionId: string | null = null;
  let areas: string[] = ["sala", "quarto", "cozinha"];
  let health: HealthInfo | null = null;
  let stopSpeakAnim: (() => void) | null = null;
  let stopWakePulseAnim: (() => void) | null = null;
  let pendingWake = false;
  let micActive = false;
  /** Só mostra transcrição / placeholder de voz após «Tina» nesta escuta. */
  let micWakeUnlocked = false;
  const wakeListener = new WakeListener({
    onPhase: (phase) => {
      if (phase === "waiting_wake") {
        setState("idle");
        if (micActive) resetVoiceInputPreview();
      }
      if (phase === "waiting_command") setState("listening");
      updateMicPhase(phase);
    },
    onWake: () => {
      pendingWake = true;
      micWakeUnlocked = true;
      unlockResponseAudio();
      showWakeFeedback();
    },
    onCommand: (text, novaSessao) => {
      micLog.info("UI: enviando comando para Thina", { text, novaSessao });
      void sendMessage(text, novaSessao || pendingWake);
    },
    onInterim: (text, meta) => {
      if (meta?.wake) micWakeUnlocked = true;
      if (!micWakeUnlocked && wakeListener.getPhase() === "waiting_wake") {
        return;
      }
      setMicTranscript(text, meta?.wake ?? false);
      if (
        micWakeUnlocked &&
        (getState() === "idle" || getState() === "listening")
      ) {
        chatInput.placeholder = text.slice(0, 60) + (text.length > 60 ? "…" : "");
      }
    },
    onStatus: (status) => setMicStatus(status),
    onError: (msg) => {
      setMicStatus(`Erro: ${msg}`);
      pushChat("system", msg);
    },
  });
  const chat: ChatMessage[] = [];

  root.innerHTML = `
    <header class="header-bar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true"></div>
        <div>
          <h1>Thina</h1>
          <p>Assistente de voz residencial · IA + casa inteligente</p>
        </div>
      </div>
      <div class="status-pill" data-state="idle" id="status-pill">
        <span class="status-dot"></span>
        <span id="status-label">${STATE_LABELS.idle}</span>
      </div>
    </header>

    <aside class="left-col">
      <section class="panel">
        <h2>Comandos</h2>
        <div class="cmd-grid">
          <button type="button" class="btn btn-wake" id="btn-wake" title="Como dizer Tina de novo">
            <span class="btn-icon">✦</span> Ativar Thina (Tina)
          </button>
          <button type="button" class="btn" id="btn-keep" title="Manter session_id e histórico">
            <span class="btn-icon">◎</span> Manter conversa ativa
          </button>
          <button type="button" class="btn btn-primary" id="btn-mic">
            <span class="btn-icon">🎤</span> <span id="btn-mic-label">Ouvir «Tina»</span>
          </button>
          <button type="button" class="btn" id="btn-health">
            <span class="btn-icon">↻</span> Verificar servidor
          </button>
        </div>
        <ul class="hint-list">
          <li><strong>Ouvir «Tina»</strong> — microfone (Chrome/Edge). <strong>Esc</strong> para parar tudo.</li>
          <li><strong>Ativar</strong> — nova sessão e liga o microfone para ouvir «Tina».</li>
          <li>No <strong>ReSpeaker</strong>, a ativação é pelo Home Assistant, não por esta página.</li>
        </ul>
      </section>

      <section class="panel mic-panel" id="mic-panel">
        <h2>Microfone <span class="mic-live-dot" id="mic-live-dot" hidden></span></h2>
        <p class="mic-status" id="mic-status">Clique em «Ouvir Tina» para começar.</p>
        <div class="mic-transcript" id="mic-transcript" aria-live="polite">
          <span class="mic-transcript-muted">Após «Tina», o que disser aparece aqui…</span>
        </div>
        <p class="mic-wake-flag" id="mic-wake-flag" hidden>✦ «Tina» reconhecida</p>
        <details class="mic-log-details" open>
          <summary>Log (também no Console F12 → filtre «Thina Mic»)</summary>
          <pre class="mic-log-view" id="mic-log-view"></pre>
        </details>
      </section>

      <section class="panel">
        <h2>Exemplos para a Thina</h2>
        <div class="cmd-grid" id="quick-cmds"></div>
      </section>
    </aside>

    <div class="center-col">
      <div class="orb-hint" id="orb-hint">
        <p>${STATE_HINTS.idle}</p>
      </div>
    </div>

    <aside class="right-col">
      <section class="panel" style="flex:1;display:flex;flex-direction:column;min-height:0">
        <h2>Conversa</h2>
        <div class="chat-log" id="chat-log"></div>
        <form class="input-row" id="chat-form">
          <input type="text" id="chat-input" placeholder="Fale com a Thina por texto…" autocomplete="off" />
          <button type="submit" class="btn btn-primary" id="btn-send">Enviar</button>
        </form>
      </section>

      <section class="panel">
        <h2>Configurações</h2>
        <form class="settings-form" id="settings-form">
          <div class="field">
            <label for="api-base">URL do servidor Thina</label>
            <input type="text" id="api-base" placeholder="(vazio) mesmo host — recomendado no npm run dev" />
          </div>
          <div class="field">
            <label for="area-id">Cômodo (area_id)</label>
            <select id="area-id"></select>
          </div>
          <label class="field-check">
            <input type="checkbox" id="auto-play" checked />
            Reproduzir áudio da resposta no navegador
          </label>
          <label class="field-check">
            <input type="checkbox" id="wake-enabled" />
            Ligar microfone ao abrir o painel
          </label>
          <button type="submit" class="btn btn-primary">Salvar configurações</button>
        </form>
        <div class="health-grid" id="health-grid" hidden></div>
      </section>
    </aside>

    <footer class="footer-bar">
      Interface WebGL · estados sincronizados com LLM, Kokoro e Home Assistant
    </footer>
  `;

  const statusPill = $("#status-pill", root);
  const statusLabel = $("#status-label", root);
  const orbHint = $("#orb-hint", root);
  const chatLog = $("#chat-log", root);
  const chatInput = $("#chat-input", root) as HTMLInputElement;
  const chatForm = $("#chat-form", root) as HTMLFormElement;
  const quickCmds = $("#quick-cmds", root);
  const apiBaseInput = $("#api-base", root) as HTMLInputElement;
  const areaSelect = $("#area-id", root) as HTMLSelectElement;
  const autoPlayCheck = $("#auto-play", root) as HTMLInputElement;
  const healthGrid = $("#health-grid", root);
  const btnWake = $("#btn-wake", root) as HTMLButtonElement;
  const btnKeep = $("#btn-keep", root) as HTMLButtonElement;
  const btnHealth = $("#btn-health", root) as HTMLButtonElement;
  const btnSend = $("#btn-send", root) as HTMLButtonElement;
  const btnMic = $("#btn-mic", root) as HTMLButtonElement;
  const btnMicLabel = $("#btn-mic-label", root);
  const wakeEnabledCheck = $("#wake-enabled", root) as HTMLInputElement;
  const micPanelEl = $("#mic-panel", root);
  const micStatusEl = $("#mic-status", root);
  const micTranscriptEl = $("#mic-transcript", root);
  const micWakeFlagEl = $("#mic-wake-flag", root);
  const micLogViewEl = $("#mic-log-view", root);
  const micLiveDotEl = $("#mic-live-dot", root);

  const quickExamples = [
    "Acende a luz da sala",
    "Qual a temperatura lá fora?",
    "Abre o Spotify no PC",
    "Bom dia, como está o tempo?",
  ];

  quickExamples.forEach((text) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn";
    b.textContent = text;
    b.addEventListener("click", () => {
      chatInput.value = text;
      chatInput.focus();
    });
    quickCmds.appendChild(b);
  });

  subscribe((state) => {
    statusPill.dataset.state = state;
    statusLabel.textContent = STATE_LABELS[state];
    orbHint.innerHTML = `<p>${STATE_HINTS[state]}</p>`;
  });

  function appendMicLogLine(entry: MicLogEntry): void {
    const line = `[${entry.time}] ${entry.level.toUpperCase()} ${entry.message}`;
    const extra = entry.data ? ` ${JSON.stringify(entry.data)}` : "";
    const row = document.createElement("div");
    row.className = `mic-log-line mic-log-${entry.level}`;
    row.textContent = line + extra;
    micLogViewEl.appendChild(row);
    while (micLogViewEl.childNodes.length > 40) {
      micLogViewEl.removeChild(micLogViewEl.firstChild!);
    }
    micLogViewEl.scrollTop = micLogViewEl.scrollHeight;
  }

  subscribeMicLogUi(appendMicLogLine);

  function setMicStatus(text: string): void {
    micStatusEl.textContent = text;
  }

  function setMicTranscript(text: string, wake: boolean): void {
    micTranscriptEl.innerHTML = "";
    if (!text.trim()) {
      const muted = document.createElement("span");
      muted.className = "mic-transcript-muted";
      muted.textContent = "Após «Tina», o que disser aparece aqui…";
      micTranscriptEl.appendChild(muted);
      return;
    }
    const span = document.createElement("span");
    span.textContent = text;
    if (wake) span.className = "mic-transcript-wake";
    micTranscriptEl.appendChild(span);
  }

  function setMicWakeHit(on: boolean): void {
    micWakeFlagEl.hidden = !on;
    micWakeFlagEl.classList.toggle("mic-wake-flag--on", on);
  }

  /** Som, vibração, orb e destaque visual ao reconhecer «Tina». */
  function showWakeFeedback(): void {
    if (!playWakeFeedback()) return;

    setMicWakeHit(true);
    setMicStatus("✦ «Tina» — pode falar o pedido");
    micPanelEl.classList.remove("mic-panel--wake");
    void micPanelEl.offsetWidth;
    micPanelEl.classList.add("mic-panel--wake");
    statusPill.classList.remove("status-pill--wake");
    void statusPill.offsetWidth;
    statusPill.classList.add("status-pill--wake");

    stopWakePulseAnim?.();
    stopWakePulseAnim = animateSpeakingEnergy((e) => setEnergy(e), 500);

    if (getState() === "idle") setState("listening");
    orbHint.innerHTML =
      "<p><strong>«Tina» ouvida</strong> — diga o que precisa.</p>";
    pushChat("system", "«Tina» detectada — fale o pedido.");
  }

  function updateMicPhase(phase: string): void {
    micLiveDotEl.hidden = phase === "off";
    if (phase === "off") setMicWakeHit(false);
  }

  function applySettingsToForm(): void {
    apiBaseInput.value = settings.apiBase;
    autoPlayCheck.checked = settings.autoPlayAudio;
    wakeEnabledCheck.checked = settings.wakeWordEnabled;
    if (!isSpeechRecognitionSupported()) {
      btnMic.disabled = true;
      btnMic.title = "Use Chrome ou Edge para reconhecimento de voz";
    }
    fillAreaSelect();
  }

  function resetVoiceInputPreview(): void {
    micWakeUnlocked = false;
    setMicTranscript("", false);
    chatInput.placeholder = "Fale com a Thina por texto…";
  }

  function stopMic(): void {
    if (!micActive) return;
    wakeListener.stop();
    micActive = false;
    resetVoiceInputPreview();
    btnMicLabel.textContent = "Ouvir «Tina»";
    btnMic.classList.remove("btn-wake");
    updateMicPhase("off");
    setMicStatus("Microfone desligado.");
    setState("idle");
    pushChat("system", "Microfone desligado.");
  }

  /** Liga escuta contínua da palavra «Tina». Retorna false se o browser não suportar. */
  function startMic(): boolean {
    if (!isSpeechRecognitionSupported()) {
      pushChat("system", "Microfone por voz: use Chrome ou Edge.");
      return false;
    }
    if (micActive) return true;
    unlockWakeFeedback();
    unlockResponseAudio();
    micLog.clearHistory();
    micLogViewEl.textContent = "";
    resetVoiceInputPreview();
    setMicWakeHit(false);
    wakeListener.start();
    micActive = true;
    btnMicLabel.textContent = "Parar de ouvir";
    btnMic.classList.add("btn-wake");
    updateMicPhase("waiting_wake");
    setMicStatus("A pedir acesso ao microfone…");
    pushChat("system", "Aguardando «Tina»… Abra F12 e filtre «Thina Mic» se nada aparecer.");
    setState("idle");
    return true;
  }

  function toggleMic(): void {
    if (micActive) stopMic();
    else startMic();
  }

  function fillAreaSelect(): void {
    areaSelect.innerHTML = "";
    for (const id of areas) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      if (id === settings.areaId) opt.selected = true;
      areaSelect.appendChild(opt);
    }
  }

  function renderChat(): void {
    chatLog.innerHTML = "";
    for (const msg of chat) {
      const el = document.createElement("div");
      el.className = `bubble bubble-${msg.role}`;
      if (msg.role !== "system") {
        const label = document.createElement("span");
        label.className = "bubble-label";
        label.textContent = msg.role === "user" ? "Você" : "Thina";
        el.appendChild(label);
      }
      const body = document.createElement("span");
      body.textContent = msg.text;
      el.appendChild(body);
      chatLog.appendChild(el);
    }
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function pushChat(role: ChatRole, text: string): void {
    chat.push({ role, text });
    renderChat();
  }

  function setBusy(busy: boolean): void {
    btnSend.disabled = busy;
    btnWake.disabled = busy;
    if (!micActive) btnMic.disabled = busy;
    chatInput.disabled = busy;
  }

  async function refreshAreas(): Promise<void> {
    areas = await fetchAreas(settings);
    if (health?.areas?.length) areas = health.areas;
    fillAreaSelect();
  }

  async function checkHealth(): Promise<void> {
    setState("thinking");
    try {
      health = await fetchHealth(settings);
      if (health.areas?.length) {
        areas = health.areas;
        fillAreaSelect();
      }
      setState("idle");
      const haNote =
        health.ha_ok === false
          ? ` · HA offline (${health.ha_url ?? "?"}) — painel usa só áudio do browser`
          : health.ha_ok
            ? " · HA OK"
            : "";
      pushChat(
        "system",
        `Servidor OK · ${health.llm_provider} / ${health.llm_model}${haNote}`,
      );
      renderHealth(health);
    } catch (e) {
      setState("error");
      pushChat(
        "system",
        `Servidor indisponível: ${(e as Error).message}. ` +
          "Inicie o Thina (uvicorn) e confira THINA_PORT no .env — no dev o Vite faz proxy para essa porta.",
      );
      healthGrid.hidden = true;
    }
  }

  function renderHealth(h: HealthInfo): void {
    healthGrid.hidden = false;
    const haLabel =
      h.ha_ok === true
        ? "ligado"
        : h.ha_ok === false
          ? "offline"
          : "—";
    healthGrid.innerHTML = `
      <div class="health-item"><span>LLM</span>${h.llm_provider}</div>
      <div class="health-item"><span>Modelo</span>${h.llm_model}</div>
      <div class="health-item"><span>Voz</span>${h.kokoro_voice}</div>
      <div class="health-item"><span>Velocidade</span>${h.kokoro_speed}</div>
      <div class="health-item"><span>Home Assistant</span>${haLabel}</div>
    `;
  }

  async function sendMessage(text: string, novaSessao: boolean): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed) return;

    unlockResponseAudio();

    setBusy(true);
    setState(novaSessao ? "listening" : getState() === "idle" ? "listening" : getState());
    pushChat("user", trimmed);
    chatInput.value = "";

    await new Promise((r) => setTimeout(r, 200));
    setState("thinking");

    try {
      const result = await conversar(settings, trimmed, sessionId, novaSessao);
      sessionId = result.session_id;
      pendingWake = false;
      setState("speaking");
      pushChat("thina", result.resposta);

      if (settings.autoPlayAudio && result.audio_url) {
        stopSpeakAnim?.();
        stopSpeakAnim = animateSpeakingEnergy((e) => setEnergy(e), 8000);
        const src = resolveAudioUrl(settings, result.audio_url);
        const finishSpeaking = () => {
          stopSpeakAnim?.();
          setEnergy(0);
          setState("idle");
        };
        try {
          await playResponseAudio(src);
          finishSpeaking();
        } catch {
          pushChat(
            "system",
            "Não foi possível reproduzir o áudio no navegador. " +
              "Confira se o servidor Thina está acessível e se «Reproduzir áudio» está ligado.",
          );
          finishSpeaking();
        }
      } else if (!settings.autoPlayAudio) {
        pushChat("system", "Reprodução no navegador desligada nas configurações.");
        setTimeout(() => setState("idle"), 1200);
      } else {
        setTimeout(() => setState("idle"), 1200);
      }
    } catch (e) {
      setState("error");
      pushChat("system", (e as Error).message);
      setTimeout(() => setState("idle"), 2500);
    } finally {
      setBusy(false);
    }
  }

  btnWake.addEventListener("click", () => {
    sessionId = null;
    pendingWake = true;
    const micOk = startMic();
    pushChat(
      "system",
      micOk
        ? "Nova sessão — microfone ligado. Diga «Tina» e o pedido."
        : "Nova sessão — digite o pedido ou use «Ouvir Tina» (Chrome/Edge).",
    );
    setState("idle");
    chatInput.focus();
    chatInput.placeholder = micOk
      ? "Ou fale: «Tina», depois o pedido…"
      : 'Diga seu pedido após "Tina"…';
  });

  btnKeep.addEventListener("click", () => {
    pushChat(
      "system",
      sessionId
        ? `Conversa mantida · sessão ${sessionId.slice(0, 8)}…`
        : "Envie uma mensagem para iniciar a sessão.",
    );
    setState("idle");
    chatInput.placeholder = "Continue a conversa…";
    chatInput.focus();
  });

  btnHealth.addEventListener("click", () => void checkHealth());
  btnMic.addEventListener("click", () => toggleMic());

  chatForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    unlockResponseAudio();
    void sendMessage(chatInput.value, pendingWake);
  });

  $("#settings-form", root).addEventListener("submit", (ev) => {
    ev.preventDefault();
    const wasWake = settings.wakeWordEnabled;
    settings = {
      apiBase: apiBaseInput.value.trim(),
      areaId: areaSelect.value,
      autoPlayAudio: autoPlayCheck.checked,
      wakeWordEnabled: wakeEnabledCheck.checked,
    };
    saveSettings(settings);
    pushChat("system", "Configurações salvas.");
    if (settings.wakeWordEnabled && !wasWake && !micActive) startMic();
    if (!settings.wakeWordEnabled && micActive) stopMic();
    void refreshAreas();
    void checkHealth();
  });

  applySettingsToForm();
  renderChat();
  void refreshAreas().then(() => checkHealth());

  pushChat(
    "system",
    "Painel pronto. Clique em «Ouvir Tina» ou digite abaixo. Reinicie o servidor Thina se /v1/areas falhar.",
  );

  return {
    emergencyStop: () => {
      if (micActive) stopMic();
      stopResponseAudio();
      setMicStatus("Parado (Esc / emergência)");
      micLog.warn("Parada de emergência");
    },
  };
}

function $(id: string, root: ParentNode): HTMLElement {
  const el = root.querySelector(id);
  if (!el) throw new Error(`Elemento ${id} não encontrado`);
  return el as HTMLElement;
}
