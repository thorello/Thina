/**
 * Reprodução da resposta TTS no navegador.
 * O elemento é “primado” num gesto do utilizador (clique/mic) para contornar autoplay.
 */

const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

let player: HTMLAudioElement | null = null;

function getPlayer(): HTMLAudioElement {
  if (!player) player = new Audio();
  return player;
}

/** Chamar no clique Enviar, ligar microfone ou wake «Tina». */
export function unlockResponseAudio(): void {
  const a = getPlayer();
  a.src = SILENT_WAV;
  void a.play().then(() => a.pause()).catch(() => {});
}

export function playResponseAudio(url: string): Promise<void> {
  const a = getPlayer();
  a.src = url;
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      a.removeEventListener("ended", onEnded);
      a.removeEventListener("error", onError);
    };
    const onEnded = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error("Falha ao carregar o áudio"));
    };
    a.addEventListener("ended", onEnded);
    a.addEventListener("error", onError);
    void a.play().catch((err) => {
      cleanup();
      reject(err);
    });
  });
}

export function stopResponseAudio(): void {
  if (!player) return;
  player.pause();
  player.currentTime = 0;
}
