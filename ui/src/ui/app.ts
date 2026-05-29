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
import { micLog } from "../speech/log";
import { startMicLevel, stopMicLevel, type MicLevelFrame } from "../speech/mic-level";
import {
  isSpeechRecognitionSupported,
  stripWakePrefix,
  WakeListener,
} from "../speech/wake";
import {
  getState,
  setDormant,
  setEnergy,
  setState,
  STATE_HINTS,
  STATE_LABELS,
  subscribe,
  type AssistantState,
} from "../state/assistant";
import { mountMicVisualizer } from "./mic-visualizer";

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
  let conversarAbort: AbortController | null = null;
  let pendingWake = false;
  let thinaActive = false;
  let micActive = false;
  /** Só mostra transcrição após «Tina» nesta escuta. */
  let micWakeUnlocked = false;
  let micStatusHint = "A ligar microfone…";
  let lastVoiceText = "";
  let suppressMicEnergyUntil = 0;

  /** Animação de onda no card — sempre que o microfone estiver ligado. */
  function isMicVizActive(): boolean {
    return micActive && wakeListener.getPhase() !== "off";
  }

  function isMicListeningVisual(): boolean {
    if (!isMicVizActive()) return false;
    const st = getState();
    return st !== "thinking" && st !== "speaking" && st !== "error";
  }

  function onMicFrame(frame: MicLevelFrame): void {
    micVisualizer.update(frame.waveform, isMicVizActive());

    const listening = isMicListeningVisual();
    if (listening) {
      micPanelEl.classList.toggle("mic-panel--listening", frame.energy > 0.06);
      micPanelEl.style.setProperty("--mic-energy", String(frame.energy));
    } else {
      micPanelEl.classList.remove("mic-panel--listening");
      micPanelEl.style.setProperty("--mic-energy", "0");
    }

    if (!micActive) return;
    if (performance.now() < suppressMicEnergyUntil) return;
    const st = getState();
    if (st === "thinking" || st === "speaking" || st === "error") return;
    setEnergy(frame.energy);
  }
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
      setMicTranscript(text);
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
          <button type="button" class="btn btn-wake" id="btn-toggle-thina" title="Liga ou desliga a Thina (microfone e sessão)">
            <span class="btn-icon" id="btn-toggle-icon">✦</span>
            <span id="btn-toggle-label">Ativar Thina</span>
          </button>
        </div>
        <ul class="hint-list">
          <li>A Thina liga o microfone ao abrir o painel (Chrome/Edge). Diga «Tina» e o pedido.</li>
          <li><strong>Ativar / Parar Thina</strong> liga ou desliga o microfone; <strong>Esc</strong> para emergência.</li>
          <li>No <strong>ReSpeaker</strong>, a ativação é pelo Home Assistant, não por esta página.</li>
        </ul>
      </section>

      <section class="panel mic-panel" id="mic-panel">
        <div class="mic-panel-head">
          <h2>Microfone <span class="mic-live-dot" id="mic-live-dot" hidden></span></h2>
        </div>
        <div class="mic-listen-viz" id="mic-listen-viz" hidden>
          <div class="mic-wave-wrap">
            <canvas class="mic-wave-canvas" id="mic-wave-canvas" aria-hidden="true"></canvas>
          </div>
          <p class="mic-listen-label" id="mic-listen-label">Aguardando «Tina»…</p>
        </div>
        <div
          class="mic-speech-area"
          id="mic-speech-area"
          role="textbox"
          aria-readonly="true"
          aria-multiline="true"
          aria-live="polite"
          data-state="idle"
        ></div>
      </section>
    </aside>

    <div class="center-col" id="galaxy-stage">
      <div class="orb-hint" id="orb-hint">
        <p>${STATE_HINTS.idle}</p>
      </div>
    </div>

    <aside class="right-col">
      <section class="panel panel-chat">
        <div class="panel-head">
          <h2>Conversa</h2>
          <div class="settings-menu">
            <button
              type="button"
              class="btn btn-gear"
              id="btn-settings"
              aria-label="Configurações"
              aria-expanded="false"
              aria-controls="settings-popover"
              title="Configurações"
            >
              <svg class="gear-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path fill="currentColor" d="M12 15.5A3.5 3.5 0 0 1 8.5 12 3.5 3.5 0 0 1 12 8.5a3.5 3.5 0 0 1 3.5 3.5 3.5 3.5 0 0 1-3.5 3.5m7.43-2.53c.04-.32.07-.64.07-.97 0-.33-.03-.66-.07-1l2.11-1.63c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.31-.61-.22l-2.49 1c-.52-.39-1.06-.73-1.69-.98l-.37-2.65A.506.506 0 0 0 14 2h-4c-.25 0-.46.18-.5.42l-.37 2.65c-.63.25-1.17.59-1.69.98l-2.49-1c-.22-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64L4.57 11c-.04.34-.07.67-.07 1 0 .33.03.65.07.97l-2.11 1.66c-.19.15-.25.42-.12.64l2 3.46c.12.22.39.3.61.22l2.49-1.01c.52.4 1.06.74 1.69.99l.37 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.37-2.65c.63-.26 1.17-.59 1.69-.99l2.49 1.01c.22.08.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.66Z"/>
              </svg>
            </button>
            <div class="settings-popover" id="settings-popover" hidden>
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
              <div class="settings-examples">
                <h3>Exemplos para a Thina</h3>
                <div class="cmd-grid" id="quick-cmds"></div>
              </div>
            </div>
          </div>
        </div>
        <div class="chat-log" id="chat-log"></div>
        <form class="input-row" id="chat-form">
          <input type="text" id="chat-input" placeholder="Fale com a Thina por texto…" autocomplete="off" />
          <button type="submit" class="btn btn-primary" id="btn-send">Enviar</button>
        </form>
      </section>
    </aside>

    <footer class="footer-bar">
      Interface WebGL · galáxia 3D sincronizada com LLM, Kokoro e Home Assistant
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
  const btnToggleThina = $("#btn-toggle-thina", root) as HTMLButtonElement;
  const btnToggleIcon = $("#btn-toggle-icon", root);
  const btnToggleLabel = $("#btn-toggle-label", root);
  const btnSend = $("#btn-send", root) as HTMLButtonElement;
  const btnSettings = $("#btn-settings", root) as HTMLButtonElement;
  const settingsPopover = $("#settings-popover", root);
  const wakeEnabledCheck = $("#wake-enabled", root) as HTMLInputElement;
  const micPanelEl = $("#mic-panel", root);
  const micSpeechAreaEl = $("#mic-speech-area", root);
  const micLiveDotEl = $("#mic-live-dot", root);
  const micListenVizEl = $("#mic-listen-viz", root);
  const micWaveCanvas = $("#mic-wave-canvas", root) as HTMLCanvasElement;
  const micListenLabelEl = $("#mic-listen-label", root);

  const micVisualizer = mountMicVisualizer(
    micListenVizEl,
    micWaveCanvas,
    micListenLabelEl,
  );

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
      setSettingsOpen(false);
    });
    quickCmds.appendChild(b);
  });

  subscribe((state, _energy, dormant) => {
    if (dormant) {
      statusPill.dataset.state = "dormant";
      statusLabel.textContent = "Parada";
      orbHint.innerHTML =
        "<p>Clique em <strong>Ativar Thina</strong> para acordar a galáxia.</p>";
      return;
    }
    statusPill.dataset.state = state;
    statusLabel.textContent = STATE_LABELS[state];
    orbHint.innerHTML = `<p>${STATE_HINTS[state]}</p>`;
  });

  function setMicStatus(text: string): void {
    micStatusHint = text;
    if (!micWakeUnlocked) renderMicSpeechArea();
  }

  function setMicTranscript(raw: string): void {
    lastVoiceText = raw;
    if (!micWakeUnlocked) return;
    renderMicSpeechArea();
  }

  function renderMicSpeechArea(): void {
    micSpeechAreaEl.dataset.state = micWakeUnlocked ? "listening" : "idle";

    if (micWakeUnlocked) {
      const display = stripWakePrefix(lastVoiceText).trim();
      if (!display) {
        micSpeechAreaEl.innerHTML =
          '<span class="mic-speech-placeholder">A ouvir o seu pedido…</span>';
      } else {
        micSpeechAreaEl.textContent = display;
      }
      micSpeechAreaEl.scrollTop = micSpeechAreaEl.scrollHeight;
      return;
    }

    const hint = micStatusHint.trim() || "Aguardando «Tina»…";
    micSpeechAreaEl.innerHTML = `<span class="mic-speech-placeholder">${escapeHtml(hint)}</span>`;
  }

  function resetMicSpeechArea(): void {
    lastVoiceText = "";
    micWakeUnlocked = false;
    micSpeechAreaEl.dataset.state = "idle";
    renderMicSpeechArea();
  }

  /** Som, vibração, orb e destaque visual ao reconhecer «Tina». */
  function showWakeFeedback(): void {
    if (!playWakeFeedback()) return;

    setMicStatus("«Tina» — pode falar o pedido");
    renderMicSpeechArea();
    micPanelEl.classList.remove("mic-panel--wake");
    void micPanelEl.offsetWidth;
    micPanelEl.classList.add("mic-panel--wake");
    statusPill.classList.remove("status-pill--wake");
    void statusPill.offsetWidth;
    statusPill.classList.add("status-pill--wake");

    stopWakePulseAnim?.();
    suppressMicEnergyUntil = performance.now() + 520;
    stopWakePulseAnim = animateSpeakingEnergy((e) => setEnergy(e), 500);

    if (getState() === "idle") setState("listening");
    orbHint.innerHTML =
      "<p><strong>«Tina» ouvida</strong> — diga o que precisa.</p>";
    pushChat("system", "«Tina» detectada — fale o pedido.");
  }

  function updateMicPhase(phase: string): void {
    micLiveDotEl.hidden = phase === "off";
    if (phase === "off") {
      micVisualizer.reset();
      micPanelEl.classList.remove("mic-panel--listening");
      micPanelEl.style.setProperty("--mic-energy", "0");
      return;
    }
    micVisualizer.update(new Float32Array(0), true);
    if (phase === "waiting_wake") {
      micListenLabelEl.textContent = micWakeUnlocked
        ? "A ouvir o pedido…"
        : "Aguardando «Tina»…";
      if (!micWakeUnlocked) setMicStatus("Aguardando «Tina»…");
    } else if (phase === "waiting_command") {
      micListenLabelEl.textContent = "A ouvir o pedido…";
      setMicStatus("A ouvir o pedido…");
    }
  }

  function applySettingsToForm(): void {
    apiBaseInput.value = settings.apiBase;
    autoPlayCheck.checked = settings.autoPlayAudio;
    wakeEnabledCheck.checked = settings.wakeWordEnabled;
    fillAreaSelect();
  }

  function resetVoiceInputPreview(): void {
    resetMicSpeechArea();
    chatInput.placeholder = "Fale com a Thina por texto…";
  }

  function updateThinaToggleUi(): void {
    if (thinaActive) {
      btnToggleThina.classList.remove("btn-wake");
      btnToggleThina.classList.add("btn-stop");
      btnToggleIcon.textContent = "■";
      btnToggleLabel.textContent = "Parar Thina";
      btnToggleThina.title = "Interrompe áudio, pedido em curso e microfone";
    } else {
      btnToggleThina.classList.remove("btn-stop");
      btnToggleThina.classList.add("btn-wake");
      btnToggleIcon.textContent = "✦";
      btnToggleLabel.textContent = "Ativar Thina";
      btnToggleThina.title = "Nova sessão e liga o microfone para «Tina»";
    }
  }

  function stopMic(quiet = false): void {
    if (!micActive) return;
    stopMicLevel();
    wakeListener.stop();
    micActive = false;
    thinaActive = false;
    micVisualizer.reset();
    micPanelEl.classList.remove("mic-panel--listening");
    micPanelEl.style.setProperty("--mic-energy", "0");
    setDormant(true);
    updateThinaToggleUi();
    resetVoiceInputPreview();
    updateMicPhase("off");
    setMicStatus("Microfone desligado.");
    setState("idle");
    if (!quiet) pushChat("system", "Microfone desligado.");
  }

  /** Liga escuta contínua da palavra «Tina». Retorna false se o browser não suportar. */
  function startMic(opts?: { quiet?: boolean }): boolean {
    if (!isSpeechRecognitionSupported()) {
      if (!opts?.quiet) {
        pushChat("system", "Microfone por voz: use Chrome ou Edge.");
      }
      return false;
    }
    if (micActive) return true;
    unlockWakeFeedback();
    unlockResponseAudio();
    micLog.clearHistory();
    resetVoiceInputPreview();
    wakeListener.start();
    void startMicLevel(onMicFrame).catch((err) => {
      micLog.warn("Analisador de microfone indisponível", {
        message: (err as Error).message,
      });
    });
    micActive = true;
    thinaActive = true;
    setDormant(false);
    updateThinaToggleUi();
    updateMicPhase("waiting_wake");
    setMicStatus(opts?.quiet ? "A pedir acesso ao microfone…" : "Aguardando «Tina»…");
    micVisualizer.update(new Float32Array(0), true);
    setState("idle");
    return true;
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
    btnToggleThina.disabled = false;
    chatInput.disabled = busy;
  }

  function setSettingsOpen(open: boolean): void {
    settingsPopover.hidden = !open;
    btnSettings.setAttribute("aria-expanded", String(open));
    btnSettings.classList.toggle("btn-gear--open", open);
  }

  function toggleSettings(): void {
    setSettingsOpen(settingsPopover.hidden);
  }

  /** Interrompe pedido, áudio, animação e microfone. */
  function stopThina(notify = true): void {
    conversarAbort?.abort();
    conversarAbort = null;
    stopSpeakAnim?.();
    stopSpeakAnim = null;
    stopWakePulseAnim?.();
    stopWakePulseAnim = null;
    stopMicLevel();
    stopResponseAudio();
    setEnergy(0);
    if (micActive) stopMic(true);
    else {
      thinaActive = false;
      setDormant(true);
      updateThinaToggleUi();
    }
    setBusy(false);
    setState("idle");
    sessionId = null;
    pendingWake = false;
    resetVoiceInputPreview();
    if (notify) {
      pushChat("system", "Thina parada.");
      setMicStatus("Parada — clique em «Ativar Thina» para voltar.");
    }
  }

  function activateThina(): void {
    sessionId = null;
    pendingWake = true;
    unlockResponseAudio();
    const micOk = startMic({ quiet: true });
    if (!micOk) {
      thinaActive = false;
      setDormant(true);
      updateThinaToggleUi();
      pushChat(
        "system",
        "Não foi possível ligar o microfone — use Chrome ou Edge.",
      );
      return;
    }
    setDormant(false);
    pushChat("system", "Thina ativa — diga «Tina» e o pedido.");
    setState("idle");
    chatInput.focus();
    chatInput.placeholder = "Ou fale: «Tina», depois o pedido…";
  }

  function toggleThina(): void {
    if (thinaActive) stopThina();
    else activateThina();
  }

  function tryAutoStartMic(): void {
    if (!settings.wakeWordEnabled || micActive) return;
    if (!isSpeechRecognitionSupported()) {
      setMicStatus("Microfone indisponível — use Chrome ou Edge.");
      return;
    }
    startMic();
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

    conversarAbort?.abort();
    conversarAbort = new AbortController();
    const { signal } = conversarAbort;

    try {
      const result = await conversar(
        settings,
        trimmed,
        sessionId,
        novaSessao,
        signal,
      );
      sessionId = result.session_id;
      pendingWake = false;
      setState("speaking");
      pushChat("thina", result.resposta);

      if (settings.autoPlayAudio && result.audio_url) {
        const src = resolveAudioUrl(settings, result.audio_url);
        const finishSpeaking = () => {
          stopSpeakAnim?.();
          setEnergy(0);
          setState("idle");
        };
        try {
          await playResponseAudio(src, (e) => setEnergy(e));
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
        stopSpeakAnim?.();
        stopSpeakAnim = animateSpeakingEnergy((e) => setEnergy(e), 1200);
        setTimeout(() => {
          stopSpeakAnim?.();
          setEnergy(0);
          setState("idle");
        }, 1200);
      } else {
        stopSpeakAnim?.();
        stopSpeakAnim = animateSpeakingEnergy((e) => setEnergy(e), 1200);
        setTimeout(() => {
          stopSpeakAnim?.();
          setEnergy(0);
          setState("idle");
        }, 1200);
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        setState("idle");
        return;
      }
      setState("error");
      pushChat("system", (e as Error).message);
      setTimeout(() => setState("idle"), 2500);
    } finally {
      conversarAbort = null;
      setBusy(false);
    }
  }

  btnToggleThina.addEventListener("click", () => toggleThina());
  btnSettings.addEventListener("click", (ev) => {
    ev.stopPropagation();
    toggleSettings();
  });
  document.addEventListener("click", (ev) => {
    if (settingsPopover.hidden) return;
    const menu = root.querySelector(".settings-menu");
    if (menu && !menu.contains(ev.target as Node)) {
      setSettingsOpen(false);
    }
  });
  settingsPopover.addEventListener("click", (ev) => ev.stopPropagation());

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
    setSettingsOpen(false);
    if (settings.wakeWordEnabled && !wasWake && !micActive) startMic();
    if (!settings.wakeWordEnabled && micActive) stopMic();
    void refreshAreas();
    void checkHealth();
  });

  applySettingsToForm();
  updateThinaToggleUi();
  renderMicSpeechArea();
  renderChat();
  void refreshAreas().then(async () => {
    await checkHealth();
    tryAutoStartMic();
  });

  return {
    emergencyStop: () => {
      stopThina(false);
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

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
