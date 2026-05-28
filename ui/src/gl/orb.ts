import { mat4 } from "gl-matrix";
import { stateIndex, subscribe } from "../state/assistant";
import { createProgram } from "./context";
import {
  FRAG_BG,
  FRAG_PARTICLE,
  VERT_BG,
  VERT_PARTICLE,
} from "./shaders";

const PARTICLE_COUNT = 900;

export class OrbRenderer {
  private gl: WebGL2RenderingContext;
  private canvas: HTMLCanvasElement;
  private bgProg: WebGLProgram;
  private particleProg: WebGLProgram;
  private vaoParticles: WebGLVertexArrayObject;
  private viewProj = mat4.create();
  private state = 0;
  private energy = 0;
  private time = 0;
  private raf = 0;
  private paused = false;
  private unsub = () => {};

  private uBg: Record<string, WebGLUniformLocation | null> = {};
  private uPart: Record<string, WebGLUniformLocation | null> = {};

  constructor(canvas: HTMLCanvasElement, gl: WebGL2RenderingContext) {
    this.canvas = canvas;
    this.gl = gl;
    this.bgProg = createProgram(gl, VERT_BG, FRAG_BG);
    this.particleProg = createProgram(gl, VERT_PARTICLE, FRAG_PARTICLE);
    this.cacheUniforms();
    this.vaoParticles = this.buildParticles();
    this.unsub = subscribe((s, e) => {
      this.state = stateIndex(s);
      this.energy = e;
    });
    this.resize();
    window.addEventListener("resize", this.onResize);
  }

  private cacheUniforms(): void {
    const gl = this.gl;
    gl.useProgram(this.bgProg);
    this.uBg = {
      time: gl.getUniformLocation(this.bgProg, "u_time"),
      state: gl.getUniformLocation(this.bgProg, "u_state"),
      energy: gl.getUniformLocation(this.bgProg, "u_energy"),
      resolution: gl.getUniformLocation(this.bgProg, "u_resolution"),
    };

    gl.useProgram(this.particleProg);
    this.uPart = {
      viewProj: gl.getUniformLocation(this.particleProg, "u_viewProj"),
      time: gl.getUniformLocation(this.particleProg, "u_time"),
      state: gl.getUniformLocation(this.particleProg, "u_state"),
      energy: gl.getUniformLocation(this.particleProg, "u_energy"),
    };
  }

  private buildParticles(): WebGLVertexArrayObject {
    const gl = this.gl;
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const seeds = new Float32Array(PARTICLE_COUNT);

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = 2 * Math.PI * u;
      const phi = Math.acos(2 * v - 1);
      const r = 0.55 + Math.random() * 0.55;
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
      seeds[i] = Math.random();
    }

    const vao = gl.createVertexArray()!;
    gl.bindVertexArray(vao);

    const bufPos = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, bufPos);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);

    const bufSeed = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, bufSeed);
    gl.bufferData(gl.ARRAY_BUFFER, seeds, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 1, gl.FLOAT, false, 0, 0);

    gl.bindVertexArray(null);
    return vao;
  }

  private onResize = (): void => {
    this.resize();
  };

  resize(): void {
    const gl = this.gl;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (w === 0 || h === 0) return;
    this.canvas.width = Math.floor(w * dpr);
    this.canvas.height = Math.floor(h * dpr);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    const aspect = w / h;
    mat4.perspective(this.viewProj, Math.PI / 4, aspect, 0.1, 50);
    const eye = mat4.create();
    mat4.translate(eye, eye, [0, 0, -2.8]);
    mat4.multiply(this.viewProj, this.viewProj, eye);
  }

  setPaused(paused: boolean): void {
    this.paused = paused;
  }

  start(): void {
    const loop = (now: number) => {
      this.raf = requestAnimationFrame(loop);
      if (this.paused || document.hidden) return;
      this.time = now * 0.001;
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

  private onVisibility = (): void => {
    this.paused = document.hidden;
  };

  /** Pulso suave durante reprodução de áudio. */
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

    const idleEnergy =
      0.15 + 0.08 * Math.sin(this.time * 1.1) + this.energy * 0.85;

    gl.useProgram(this.bgProg);
    gl.uniform1f(this.uBg.time!, this.time);
    gl.uniform1f(this.uBg.state!, this.state);
    gl.uniform1f(this.uBg.energy!, idleEnergy);
    gl.uniform2f(this.uBg.resolution!, this.canvas.width, this.canvas.height);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    gl.useProgram(this.particleProg);
    gl.uniformMatrix4fv(this.uPart.viewProj!, false, this.viewProj);
    gl.uniform1f(this.uPart.time!, this.time);
    gl.uniform1f(this.uPart.state!, this.state);
    gl.uniform1f(this.uPart.energy!, idleEnergy);

    gl.bindVertexArray(this.vaoParticles);
    gl.drawArrays(gl.POINTS, 0, PARTICLE_COUNT);
    gl.bindVertexArray(null);
  }
}

/** Simula onda de voz durante speaking. */
export function animateSpeakingEnergy(
  onEnergy: (e: number) => void,
  durationMs: number,
): () => void {
  const start = performance.now();
  let raf = 0;
  const tick = (now: number) => {
    const t = (now - start) / durationMs;
    if (t >= 1) {
      onEnergy(0);
      return;
    }
    const wave =
      0.35 +
      0.45 * Math.abs(Math.sin(now * 0.012)) +
      0.2 * Math.sin(now * 0.023);
    onEnergy(wave);
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}
