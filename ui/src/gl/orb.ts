import { mat4 } from "gl-matrix";
import { stateIndex, subscribe } from "../state/assistant";
import { createProgram } from "./context";
import {
  FRAG_BG,
  FRAG_CORE,
  FRAG_PARTICLE,
  VERT_BG,
  VERT_CORE,
  VERT_PARTICLE,
} from "./shaders";

/** Peso 0–1 do estado `center` quando o índice é contínuo. */
function blendWeight(state: number, center: number): number {
  const d = Math.abs(state - center);
  if (d >= 0.92) return 0;
  const x = 1 - d / 0.92;
  return x * x * (3 - 2 * x);
}

/** ~450 ms para cruzar entre estados adjacentes. */
const STATE_BLEND_SPEED = 2.8;

const DISK_COUNT  = 700;
const GALAXY_RADIUS = 1;
const DISK_THICKNESS = 0.1;
const NUCLEUS_RADIUS = 0.2;

/** Período da respiração da galáxia quando ativa (~5 s ciclo completo). */
const BREATH_OMEGA = (Math.PI * 2) / 5.0;

/** Inclinação da câmera em radianos (~−28° em −0.50). Mais negativo = mais de lado. */
const CAMERA_TILT_X = 0.60;
/** Distância da câmera ao centro da galáxia (eixo Z). */
const CAMERA_DISTANCE = 5.0;

type ParticleKind = 0 | 1 | 2; // halo, bulbo, disco

function diskPos(r: number, ySpread: number): [number, number, number] {
  const a = Math.random() * Math.PI * 2;
  return [r * Math.cos(a), (Math.random() - 0.5) * ySpread, r * Math.sin(a)];
}

export class OrbRenderer {
  private gl: WebGL2RenderingContext;
  private canvas: HTMLCanvasElement;
  private bgProg: WebGLProgram;
  private particleProg: WebGLProgram;
  private coreProg: WebGLProgram;
  private vao: WebGLVertexArrayObject;
  private coreVao: WebGLVertexArrayObject;
  private proj  = mat4.create();
  private view  = mat4.create();
  private viewProj = mat4.create();
  private focal = { x: 0.5, y: 0.5 };
  private stateTarget = 0;
  private stateSmooth = 0;
  private energy = 0;
  private dormantTarget = 1;
  private dormantSmooth = 1;
  private audioSmooth = 0;
  private prevDrawMs = 0;
  /** Tempo de simulação (s); avança só em draw(), não usa relógio absoluto do rAF. */
  private time = 0;
  /** Fase orbital do disco; congela em dormant e zera ao reativar. */
  private orbitTime = 0;
  private raf   = 0;
  private paused = false;
  private unsub = () => {};
  private uBg:   Record<string, WebGLUniformLocation | null> = {};
  private uPart: Record<string, WebGLUniformLocation | null> = {};
  private uCore: Record<string, WebGLUniformLocation | null> = {};

  constructor(canvas: HTMLCanvasElement, gl: WebGL2RenderingContext) {
    this.canvas = canvas;
    this.gl = gl;
    this.bgProg = createProgram(gl, VERT_BG, FRAG_BG);
    this.particleProg = createProgram(gl, VERT_PARTICLE, FRAG_PARTICLE);
    this.coreProg = createProgram(gl, VERT_CORE, FRAG_CORE);
    this.cacheUniforms();
    this.vao = this.buildGalaxy();
    this.coreVao = this.buildCoreVao();
    this.unsub = subscribe((s, e, dormant) => {
      const waking = this.dormantTarget >= 0.5 && !dormant;
      this.stateTarget = stateIndex(s);
      this.energy = e;
      this.dormantTarget = dormant ? 1 : 0;
      if (waking) this.orbitTime = 0;
    });
    this.resize();
    window.addEventListener("resize", this.onResize);
  }

  setFocalFromElement(el: HTMLElement | null): void {
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    if (vw <= 0 || vh <= 0) return;
    this.focal.x = (rect.left + rect.width  * 0.5) / vw;
    this.focal.y = 1.0 - (rect.top  + rect.height * 0.5) / vh;
  }

  private cacheUniforms(): void {
    const gl = this.gl;
    gl.useProgram(this.bgProg);
    this.uBg = {
      time:       gl.getUniformLocation(this.bgProg, "u_time"),
      state:      gl.getUniformLocation(this.bgProg, "u_state"),
      energy:     gl.getUniformLocation(this.bgProg, "u_energy"),
      audio:      gl.getUniformLocation(this.bgProg, "u_audio"),
      dormant:    gl.getUniformLocation(this.bgProg, "u_dormant"),
      breath:     gl.getUniformLocation(this.bgProg, "u_breath"),
      resolution: gl.getUniformLocation(this.bgProg, "u_resolution"),
      center:     gl.getUniformLocation(this.bgProg, "u_center"),
    };
    gl.useProgram(this.particleProg);
    this.uPart = {
      viewProj:     gl.getUniformLocation(this.particleProg, "u_viewProj"),
      time:         gl.getUniformLocation(this.particleProg, "u_time"),
      orbitTime:    gl.getUniformLocation(this.particleProg, "u_orbitTime"),
      state:        gl.getUniformLocation(this.particleProg, "u_state"),
      energy:       gl.getUniformLocation(this.particleProg, "u_energy"),
      dormant:      gl.getUniformLocation(this.particleProg, "u_dormant"),
      breath:       gl.getUniformLocation(this.particleProg, "u_breath"),
      audio:        gl.getUniformLocation(this.particleProg, "u_audio"),
      screenOffset: gl.getUniformLocation(this.particleProg, "u_screenOffset"),
    };
    gl.useProgram(this.coreProg);
    this.uCore = {
      viewProj:     gl.getUniformLocation(this.coreProg, "u_viewProj"),
      time:         gl.getUniformLocation(this.coreProg, "u_time"),
      state:        gl.getUniformLocation(this.coreProg, "u_state"),
      energy:       gl.getUniformLocation(this.coreProg, "u_energy"),
      dormant:      gl.getUniformLocation(this.coreProg, "u_dormant"),
      breath:       gl.getUniformLocation(this.coreProg, "u_breath"),
      audio:        gl.getUniformLocation(this.coreProg, "u_audio"),
      screenOffset: gl.getUniformLocation(this.coreProg, "u_screenOffset"),
      resolution:   gl.getUniformLocation(this.coreProg, "u_resolution"),
    };
  }

  private buildGalaxy(): WebGLVertexArrayObject {
    const gl = this.gl;
    const positions = new Float32Array(DISK_COUNT * 3);
    const seeds     = new Float32Array(DISK_COUNT);
    const kinds     = new Float32Array(DISK_COUNT);

    for (let i = 0; i < DISK_COUNT; i++) {
      const roll = Math.random();
      let kind: ParticleKind;
      let x = 0, y = 0, z = 0;

      if (roll < 0.65) {
        kind = 2;
        const r = NUCLEUS_RADIUS + 0.02 + Math.pow(Math.random(), 0.55) * GALAXY_RADIUS;
        const ySpread = DISK_THICKNESS * (1.0 - (r / GALAXY_RADIUS) * 0.4);
        [x, y, z] = diskPos(r, ySpread);
      } else if (roll < 0.85) {
        kind = 1;
        const r = NUCLEUS_RADIUS + Math.pow(Math.random(), 1.8) * 0.35;
        [x, y, z] = diskPos(r, DISK_THICKNESS * 0.6);
      } else {
        kind = 0;
        const r = 0.28 + Math.pow(Math.random(), 0.8) * (GALAXY_RADIUS * 0.92);
        [x, y, z] = diskPos(r, DISK_THICKNESS * 0.4);
      }

      positions[i * 3]     = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;
      seeds[i] = Math.random();
      kinds[i] = kind;
    }

    const vao = gl.createVertexArray()!;
    gl.bindVertexArray(vao);

    function uploadAttr(data: Float32Array, loc: number, size: number) {
      const buf = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    }
    uploadAttr(positions, 0, 3);
    uploadAttr(seeds,     1, 1);
    uploadAttr(kinds,     2, 1);

    gl.bindVertexArray(null);
    return vao;
  }

  private buildCoreVao(): WebGLVertexArrayObject {
    const gl = this.gl;
    const corners = new Float32Array([
      -1, -1,  1, -1,  -1, 1,  1, 1,
    ]);
    const vao = gl.createVertexArray()!;
    gl.bindVertexArray(vao);
    const buf = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, corners, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
    return vao;
  }

  private onResize = () => this.resize();

  resize(): void {
    const gl = this.gl;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (w === 0 || h === 0) return;
    this.canvas.width  = Math.floor(w * dpr);
    this.canvas.height = Math.floor(h * dpr);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    mat4.perspective(this.proj, Math.PI / 3.5, w / h, 0.1, 50.0);
  }

  private updateView(): void {
    mat4.identity(this.view);
    // Ordem correta: translate ANTES de rotateX
    // → origem do mundo projeta ao centro da tela após offset
    mat4.translate(this.view, this.view, [0, 0, -CAMERA_DISTANCE]);
    mat4.rotateX(this.view, this.view, CAMERA_TILT_X);
    mat4.multiply(this.viewProj, this.proj, this.view);
  }

  private screenOffsetNdc(): [number, number] {
    return [
      2.0 * (this.focal.x - 0.5),
      2.0 * (this.focal.y - 0.5),
    ];
  }

  setPaused(p: boolean): void {
    if (this.paused && !p) this.prevDrawMs = 0;
    this.paused = p;
  }

  start(): void {
    const loop = () => {
      this.raf = requestAnimationFrame(loop);
      if (this.paused || document.hidden) return;
      this.draw();
    };
    this.raf = requestAnimationFrame(loop);
    document.addEventListener("visibilitychange", this.onVisibility);
  }

  stop(): void {
    cancelAnimationFrame(this.raf);
    document.removeEventListener("visibilitychange", this.onVisibility);
    window.removeEventListener("resize", this.onResize);
    this.unsub();
  }

  private onVisibility = () => {
    if (!document.hidden) this.prevDrawMs = 0;
  };

  bumpEnergy(target: number): void {
    const step = () => {
      this.energy += (target - this.energy) * 0.08;
      if (Math.abs(target - this.energy) > 0.01) requestAnimationFrame(step);
    };
    step();
  }

  private draw(): void {
    const gl = this.gl;
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    const nowMs = performance.now();
    const dt = this.prevDrawMs ? Math.min(0.05, (nowMs - this.prevDrawMs) / 1000) : 0.016;
    this.prevDrawMs = nowMs;
    this.time += dt;

    const stateK = 1 - Math.exp(-STATE_BLEND_SPEED * dt);
    this.stateSmooth += (this.stateTarget - this.stateSmooth) * stateK;
    const state = this.stateSmooth;

    const wSpeaking = blendWeight(state, 3);
    const wThinking = blendWeight(state, 2);
    const wListening = blendWeight(state, 1);
    const wActiveMotion = Math.min(
      1,
      wSpeaking + wThinking * 0.88 + wListening * Math.min(1, this.audioSmooth * 1.15),
    );

    const wAudioReact = Math.min(1, wSpeaking + wListening * 0.92);
    const audioTarget = this.energy * wAudioReact;
    const smoothK = audioTarget > this.audioSmooth ? 16 : 3.6;
    this.audioSmooth += (audioTarget - this.audioSmooth) * (1 - Math.exp(-smoothK * dt));

    const dormantK = 1 - Math.exp(-3.2 * dt);
    this.dormantSmooth +=
      (this.dormantTarget - this.dormantSmooth) * dormantK;
    const dormant = this.dormantSmooth;
    const alive = 1.0 - dormant;
    if (alive > 0.01) this.orbitTime += dt;
    const breath = alive * Math.sin(this.time * BREATH_OMEGA);

    const idleBreath = (1 - wActiveMotion) * breath * 0.14;
    const thinkBoost = wThinking * (
      0.14 + 0.10 * Math.sin(this.time * 3.6)
           + 0.06 * Math.sin(this.time * 5.8 + 0.9)
    );
    const listenEnergy = 0.44 + this.audioSmooth * 0.62;
    const speakEnergy = 0.42 + this.audioSmooth * 0.68;
    const baseEnergy = 0.50 + idleBreath;
    let energy = baseEnergy * (1 - wSpeaking - wListening)
               + listenEnergy * wListening
               + speakEnergy * wSpeaking
               + thinkBoost;
    energy *= 0.45 + alive * 0.55;
    const audio = this.audioSmooth;

    this.updateView();
    const [offX, offY] = this.screenOffsetNdc();

    // Fundo
    gl.useProgram(this.bgProg);
    gl.uniform1f(this.uBg.time!,        this.time);
    gl.uniform1f(this.uBg.state!,       state);
    gl.uniform1f(this.uBg.energy!,      energy);
    gl.uniform1f(this.uBg.audio!,       audio);
    gl.uniform1f(this.uBg.dormant!,     dormant);
    gl.uniform1f(this.uBg.breath!,      breath);
    gl.uniform2f(this.uBg.resolution!,  this.canvas.width, this.canvas.height);
    gl.uniform2f(this.uBg.center!,      this.focal.x, this.focal.y);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    // Partículas (blend aditivo)
    gl.depthMask(false);
    gl.useProgram(this.particleProg);
    gl.uniformMatrix4fv(this.uPart.viewProj!,     false, this.viewProj);
    gl.uniform1f(this.uPart.time!,        this.time);
    gl.uniform1f(this.uPart.orbitTime!,  this.orbitTime);
    gl.uniform1f(this.uPart.state!,       state);
    gl.uniform1f(this.uPart.energy!,      energy);
    gl.uniform1f(this.uPart.dormant!,     dormant);
    gl.uniform1f(this.uPart.breath!,      breath);
    gl.uniform1f(this.uPart.audio!,       audio);
    gl.uniform2f(this.uPart.screenOffset!, offX, offY);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.POINTS, 0, DISK_COUNT);
    gl.bindVertexArray(null);

    // Núcleo — sprite branco no centro
    gl.useProgram(this.coreProg);
    gl.uniformMatrix4fv(this.uCore.viewProj!,     false, this.viewProj);
    gl.uniform1f(this.uCore.time!,        this.time);
    gl.uniform1f(this.uCore.state!,       state);
    gl.uniform1f(this.uCore.energy!,      energy);
    gl.uniform1f(this.uCore.dormant!,     dormant);
    gl.uniform1f(this.uCore.breath!,      breath);
    gl.uniform1f(this.uCore.audio!,       audio);
    gl.uniform2f(this.uCore.screenOffset!, offX, offY);
    gl.uniform2f(this.uCore.resolution!,  this.canvas.width, this.canvas.height);
    gl.bindVertexArray(this.coreVao);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);
    gl.depthMask(true);
  }
}

export function animateSpeakingEnergy(
  onEnergy: (e: number) => void,
  durationMs: number,
): () => void {
  const start = performance.now();
  let raf = 0;
  const tick = (now: number) => {
    const t = (now - start) / durationMs;
    if (t >= 1) { onEnergy(0); return; }
    const syllable = Math.abs(Math.sin(now * 0.011));
    const formant = 0.5 + 0.5 * Math.sin(now * 0.019 + 1.2);
    const burst = Math.pow(Math.max(0, Math.sin(now * 0.028)), 3.0);
    const wave = 0.28 + 0.38 * syllable + 0.22 * formant + 0.18 * burst;
    onEnergy(Math.min(1, wave));
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}
