import { createGlContext } from "./gl/context";
import { OrbRenderer } from "./gl/orb";
import { logSpeechSupport, MIC_LOG_PREFIX } from "./speech/log";
import { mountApp } from "./ui/app";
import "./style.css";

logSpeechSupport();
console.info(
  `${MIC_LOG_PREFIX} Logs de voz no Console (F12). Filtre por "Thina Mic". ` +
    "Desative debug: localStorage.setItem('thina.ui.micDebug','0')",
);

const canvas = document.querySelector<HTMLCanvasElement>("#gl-canvas");
const appRoot = document.querySelector<HTMLDivElement>("#app");

if (!canvas || !appRoot) {
  throw new Error("Canvas ou #app ausente no HTML.");
}

const gl = createGlContext(canvas);
const orb = new OrbRenderer(canvas, gl);
orb.start();
const ui = mountApp(appRoot);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    ui.emergencyStop();
    orb.setPaused(true);
    console.warn(
      `${MIC_LOG_PREFIX} Esc — microfone e animação pausados. Recarregue a página se o PC ainda estiver lento.`,
    );
  }
});
