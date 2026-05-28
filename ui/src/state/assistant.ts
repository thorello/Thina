/** Estados visuais e de fluxo da Thina na interface. */

export type AssistantState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export const STATE_LABELS: Record<AssistantState, string> = {
  idle: "Aguardando",
  listening: "Ouvindo",
  thinking: "Pensando",
  speaking: "Respondendo",
  error: "Erro",
};

export const STATE_HINTS: Record<AssistantState, string> = {
  idle: 'Clique em <strong>Ouvir «Tina»</strong> ou diga «Tina» no ReSpeaker / satélite.',
  listening: "Fale seu pedido — luzes, clima, música no PC…",
  thinking: "Processando com LLM e ferramentas da casa…",
  speaking: "Sintetizando voz e enviando ao ReSpeaker…",
  error: "Verifique o servidor e as configurações.",
};

type Listener = (state: AssistantState, energy: number) => void;

let _state: AssistantState = "idle";
let _energy = 0;
const _listeners = new Set<Listener>();

export function getState(): AssistantState {
  return _state;
}

export function getEnergy(): number {
  return _energy;
}

export function setState(state: AssistantState): void {
  _state = state;
  _notify();
}

export function setEnergy(energy: number): void {
  _energy = Math.max(0, Math.min(1, energy));
  _notify();
}

export function subscribe(fn: Listener): () => void {
  _listeners.add(fn);
  fn(_state, _energy);
  return () => _listeners.delete(fn);
}

function _notify(): void {
  for (const fn of _listeners) fn(_state, _energy);
}

/** Índice numérico para o shader WebGL (idle=0 … error=4). */
export function stateIndex(state: AssistantState): number {
  const map: Record<AssistantState, number> = {
    idle: 0,
    listening: 1,
    thinking: 2,
    speaking: 3,
    error: 4,
  };
  return map[state];
}
