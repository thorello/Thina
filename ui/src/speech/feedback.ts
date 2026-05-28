/**
 * Feedback multimodal ao reconhecer «Tina» (som + vibração).
 */

import { playWakeBeep, unlockWakeBeep } from "./beep";

export { unlockWakeBeep as unlockWakeFeedback };

const MIN_FEEDBACK_MS = 700;
let lastAt = 0;

/** Bip + vibração curta (se o dispositivo suportar). */
export function playWakeFeedback(): boolean {
  const now = Date.now();
  if (now - lastAt < MIN_FEEDBACK_MS) return false;
  lastAt = now;

  playWakeBeep();
  try {
    navigator.vibrate?.([35, 20, 35]);
  } catch {
    /* ignore */
  }
  return true;
}
