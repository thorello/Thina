export interface MicVisualizer {
  update(waveform: Float32Array, active: boolean): void;
  reset(): void;
}

const HISTORY = 512;

export function mountMicVisualizer(
  root: HTMLElement,
  canvas: HTMLCanvasElement,
  labelEl: HTMLElement,
): MicVisualizer {
  const canvasCtx = canvas.getContext("2d");
  if (!canvasCtx) throw new Error("Canvas 2D indisponível");
  const ctx = canvasCtx;

  const history = new Float32Array(HISTORY);
  let peak = 0;
  let raf = 0;
  let dirty = false;
  let active = false;

  function resize(): void {
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    dirty = true;
  }

  const ro = new ResizeObserver(() => resize());
  ro.observe(canvas);
  resize();

  function pushWaveform(samples: Float32Array): void {
    const n = samples.length;
    if (n <= 0) return;
    history.copyWithin(0, n);
    for (let i = 0; i < n; i++) {
      history[HISTORY - n + i] = samples[i];
      const a = Math.abs(samples[i]);
      if (a > peak) peak = a;
    }
    peak *= 0.992;
    dirty = true;
  }

  function draw(): void {
    raf = 0;
    if (!dirty || !active) return;
    dirty = false;

    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (w < 1 || h < 1) return;

    const mid = h * 0.5;
    const amp = h * 0.4;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgba(0, 0, 0, 0.42)";
    ctx.fillRect(0, 0, w, h);

    ctx.strokeStyle = "rgba(94, 234, 212, 0.07)";
    ctx.lineWidth = 1;
    for (let y = 0; y <= h; y += 14) {
      ctx.beginPath();
      ctx.moveTo(0, y + 0.5);
      ctx.lineTo(w, y + 0.5);
      ctx.stroke();
    }
    for (let x = 0; x <= w; x += 22) {
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, h);
      ctx.stroke();
    }

    ctx.strokeStyle = "rgba(94, 234, 212, 0.22)";
    ctx.beginPath();
    ctx.moveTo(0, mid + 0.5);
    ctx.lineTo(w, mid + 0.5);
    ctx.stroke();

    const drawTrace = (
      sign: number,
      color: string,
      glow: string,
      width: number,
    ) => {
      ctx.beginPath();
      for (let i = 0; i < HISTORY; i++) {
        const x = (i / (HISTORY - 1)) * w;
        const y = mid + sign * history[i] * amp;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.shadowColor = glow;
      ctx.shadowBlur = 10;
      ctx.stroke();
      ctx.shadowBlur = 0;
    };

    drawTrace(-1, "rgba(94, 234, 212, 0.95)", "#5eead4", 1.8);
    drawTrace(1, "rgba(167, 139, 250, 0.82)", "#a78bfa", 1.5);

    const last = history[HISTORY - 1];
    const sweepX = w - 3;
    ctx.fillStyle = "#ecfdf5";
    ctx.beginPath();
    ctx.arc(sweepX, mid - last * amp, 2.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(196, 181, 253, 0.95)";
    ctx.beginPath();
    ctx.arc(sweepX, mid + last * amp, 2.2, 0, Math.PI * 2);
    ctx.fill();

    root.style.setProperty("--mic-peak", String(Math.min(1, peak * 1.6)));
  }

  function scheduleDraw(): void {
    if (raf) return;
    raf = requestAnimationFrame(draw);
  }

  return {
    update(waveform, isActive) {
      active = isActive;
      root.hidden = !isActive;
      root.classList.toggle("mic-listen-viz--active", isActive);
      if (!isActive) return;

      if (waveform.length > 0) pushWaveform(waveform);
      dirty = true;
      scheduleDraw();
    },
    reset() {
      active = false;
      history.fill(0);
      peak = 0;
      root.style.setProperty("--mic-peak", "0");
      root.hidden = true;
      root.classList.remove("mic-listen-viz--active");
      labelEl.textContent = "Ouvindo";
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      dirty = false;
      if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    },
  };
}
