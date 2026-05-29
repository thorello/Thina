/** Peso suave por estado — u_state contínuo (0–4) interpolado no render loop. */
const GLSL_STATE = `
float stateW(float center) {
  return (1.0 - u_dormant) * (1.0 - smoothstep(0.38, 0.92, abs(u_state - center)));
}

float stateWAny(float center) {
  return 1.0 - smoothstep(0.38, 0.92, abs(u_state - center));
}

vec3 stateTint(vec3 base) {
  vec3 c = base;
  c = mix(c, vec3(0.45, 0.95, 1.0),  stateWAny(1.0) * 0.5);
  c = mix(c, vec3(0.78, 0.55, 1.0),  stateWAny(2.0) * 0.5);
  c = mix(c, vec3(0.55, 0.95, 0.82), stateWAny(3.0) * 0.5);
  c = mix(c, vec3(1.0, 0.42, 0.45),  stateWAny(4.0) * 0.65);
  return c;
}
`;

// Órbita circular uniforme em torno da origem (centro do núcleo).
export const VERT_PARTICLE = `#version 300 es
precision highp float;

layout(location = 0) in vec3 a_position;
layout(location = 1) in float a_seed;
layout(location = 2) in float a_kind;

uniform mat4  u_viewProj;
uniform float u_time;
uniform float u_orbitTime;
uniform float u_state;
uniform float u_energy;
uniform float u_audio;
uniform float u_dormant;
uniform float u_breath;
uniform vec2  u_screenOffset;

out float v_alpha;
out vec3  v_color;

${GLSL_STATE}

// Rotação no plano XZ em torno de (0,0,0) — mesma ω para todas as partículas do disco.
vec3 orbit(vec3 p) {
  if (a_kind > 2.5) return p;
  float r = length(p.xz);
  if (r < 0.001) return vec3(0.0, p.y, 0.0);
  float wThink = stateW(2.0);
  float wSpeak = stateW(3.0);
  float wListen = stateW(1.0);
  float thinkBoost = 1.0 + wThink * 1.2;
  float speakBoost = 1.0 + wSpeak * u_audio * 0.75;
  float listenBoost = 1.0 + wListen * u_audio * 0.62;
  float spin = 0.038 * (1.0 + 0.20 * u_energy) * (1.0 - u_dormant * 0.94) * thinkBoost * speakBoost * listenBoost;
  float theta = atan(p.z, p.x) + u_orbitTime * spin;
  return vec3(r * cos(theta), p.y, r * sin(theta));
}

vec3 collapseToNucleus(vec3 p) {
  float ang = a_seed * 40.0;
  vec3 core = vec3(
    cos(ang) * (0.025 + a_seed * 0.035),
    (fract(a_seed * 7.13) - 0.5) * 0.03,
    sin(ang) * (0.025 + a_seed * 0.035)
  );
  return mix(p, core, smoothstep(0.0, 1.0, u_dormant));
}

void main() {
  vec3 p = orbit(a_position);
  p = collapseToNucleus(p);
  float r = length(p.xz);

  float wSpeak = stateW(3.0);
  float wThink = stateW(2.0);
  float wListen = stateW(1.0);
  float alive = 1.0 - u_dormant;
  float breathMix = (1.0 - max(max(wSpeak, wThink * 0.88), wListen * 0.85)) * alive;

  // Respiração lenta da galáxia (atenua ao pensar/responder/ouvir)
  if (breathMix > 0.01) {
    float radialW = mix(0.12, 1.0, smoothstep(0.0, 1.35, r));
    float scale = 1.0 + 0.062 * u_breath * radialW * breathMix;
    p.xz *= scale;
    p.y *= 1.0 + 0.034 * u_breath * radialW * breathMix;
  }

  // Respondendo — ondas sonoras, vibração vocal e projeção da voz
  {
    float theta = atan(p.z, p.x);
    float radialW = mix(0.30, 1.0, smoothstep(0.04, 1.05, r));
    float envelope = smoothstep(0.04, 0.88, u_audio);

    float sonicA = sin(r * 9.0 - u_time * 10.5 + a_seed * 14.0);
    float sonicB = sin(r * 6.0 - u_time * 7.0 - theta * 1.8 + a_seed * 22.0);
    float waveFront = smoothstep(0.18, 0.92, sonicA) * 0.50
                    + smoothstep(0.12, 0.85, sonicB) * 0.38;
    float waveAmp = (0.035 + 0.075 * envelope) * wSpeak;
    p.xz *= 1.0 + waveFront * waveAmp * radialW;

    float vocal = sin(u_time * 19.0 + a_seed * 32.0) * envelope;
    vocal += sin(u_time * 12.5 + r * 5.0 + theta * 2.0) * envelope * 0.55;
    vocal += sin(u_time * 7.8 + a_seed * 18.0) * 0.25;
    p.y += vocal * 0.042 * radialW * wSpeak;

    float peak = pow(envelope, 2.2) * wSpeak;
    p.xz *= 1.0 + peak * 0.10 * radialW;
    p.y *= 1.0 + peak * 0.045 * radialW;

    float flutter = sin(theta * 9.0 + u_time * 14.0 * (0.4 + envelope * 0.6));
    flutter *= (envelope * 0.65 + 0.20) * wSpeak;
    float rNow = length(p.xz) * (1.0 + flutter * 0.028 * radialW);
    p.xz = normalize(p.xz) * rNow;
  }

  // Ouvindo — ondas concêntricas reativas à voz do utilizador
  {
    float theta = atan(p.z, p.x);
    float radialW = mix(0.28, 1.0, smoothstep(0.04, 1.05, r));
    float envelope = smoothstep(0.04, 0.88, u_audio);

    float listenA = sin(r * 11.0 - u_time * 12.0 + a_seed * 16.0);
    float listenB = sin(r * 7.5 - u_time * 8.5 - theta * 2.2 + a_seed * 20.0);
    float waveFront = smoothstep(0.16, 0.90, listenA) * 0.48
                    + smoothstep(0.10, 0.82, listenB) * 0.36;
    float waveAmp = (0.028 + 0.065 * envelope) * wListen;
    p.xz *= 1.0 + waveFront * waveAmp * radialW;

    float vocal = sin(u_time * 21.0 + a_seed * 28.0) * envelope;
    vocal += sin(u_time * 14.0 + r * 4.5 + theta * 1.6) * envelope * 0.50;
    p.y += vocal * 0.038 * radialW * wListen;

    float peak = pow(envelope, 2.0) * wListen;
    p.xz *= 1.0 + peak * 0.08 * radialW;
    p.y *= 1.0 + peak * 0.035 * radialW;
  }

  // Pensando — hélice sináptica + ondas de impulso que percorrem o disco
  {
    float theta = atan(p.z, p.x);
    float armW = mix(0.25, 1.0, smoothstep(0.08, 1.1, r));

    float helix = sin(theta * 5.0 + u_time * 3.4 + a_seed * 18.0);
    p.y += helix * 0.075 * armW * wThink;

    float waveA = sin(r * 6.5 - u_time * 4.8 + theta * 2.0 + a_seed * 22.0);
    float waveB = sin(r * 4.2 - u_time * 3.1 - theta * 1.5 + a_seed * 9.0);
    float impulse = smoothstep(0.15, 0.85, waveA) * 0.55
                  + smoothstep(0.10, 0.80, waveB) * 0.35;
    p.xz *= 1.0 + impulse * 0.05 * armW * wThink;
    p.y *= 1.0 + impulse * 0.025 * armW * wThink;

    float drift = sin(u_time * 1.6 + a_seed * 40.0 + r * 2.8);
    p.x += drift * 0.012 * armW * wThink;
    p.z += cos(u_time * 1.9 + a_seed * 31.0 + r * 2.2) * 0.012 * armW * wThink;
  }

  vec4 clip  = u_viewProj * vec4(p, 1.0);
  clip.xy   += u_screenOffset * clip.w;   // desloca para o ponto focal
  gl_Position = clip;

  // Tamanho perspectivo: usa clip.w (profundidade real)
  float depth = max(0.5, clip.w);
  float twinkle = 0.70 + 0.30 * sin(u_time * (2.0 + a_seed * 3.0) + a_seed * 40.0);
  float vis = mix(0.55 + 0.45 * u_energy, 0.35 + 0.25 * u_energy, u_dormant);

  float sz;
  if (a_kind < 0.5) {
    sz = mix(0.7, 1.1, twinkle);
  } else if (a_kind < 1.5) {
    sz = mix(0.8, 1.4, vis) * (1.0 + 0.25 * exp(-r * 2.5));
  } else {
    sz = mix(0.75, 1.3, twinkle);
  }

  {
    float synapse = pow(max(0.0, sin(u_time * 3.6 - r * 4.5 + a_seed * 35.0)), 6.0);
    sz += wThink * (0.18 + synapse * 0.55);
  }
  {
    float envelope = smoothstep(0.04, 0.88, u_audio);
    float vocalPop = pow(max(0.0, sin(u_time * 7.5 - r * 6.0 + a_seed * 28.0)), 5.0);
    sz += wSpeak * (0.32 + envelope * 0.55 + vocalPop * envelope * 0.45);
  }
  {
    float envelope = smoothstep(0.04, 0.88, u_audio);
    float listenPop = pow(max(0.0, sin(u_time * 8.5 - r * 5.5 + a_seed * 24.0)), 5.0);
    sz += wListen * (0.28 + envelope * 0.48 + listenPop * envelope * 0.38);
  }
  sz += stateW(1.0) * 0.12;

  gl_PointSize = sz * 14.0 / depth;

  // Cor por tipo
  vec3 coreCol    = vec3(1.00, 0.88, 0.58);
  vec3 armCol     = mix(vec3(0.45, 0.55, 1.0), vec3(0.72, 0.42, 0.95), a_seed);
  vec3 dustCol    = vec3(0.55, 0.68, 0.95);
  vec3 haloCol    = vec3(0.78, 0.85, 1.0);

  vec3 col;
  if (a_kind < 0.5) col = haloCol;
  else if (a_kind < 1.5) col = mix(coreCol, armCol, smoothstep(0.0, 0.32, r));
  else col = mix(armCol, dustCol, smoothstep(0.35, 2.0, r));

  {
    float twThink = 0.50 + 0.50 * sin(u_time * (4.5 + a_seed * 5.0) + a_seed * 40.0);
    twinkle = mix(twinkle, twThink, wThink);
  }
  {
    float envelope = smoothstep(0.04, 0.88, u_audio);
    float twSpeak = (0.40 + 0.60 * sin(u_time * (7.0 + a_seed * 7.0) + a_seed * 40.0));
    twSpeak *= 0.75 + 0.25 * envelope;
    twinkle = mix(twinkle, twSpeak, wSpeak);
  }
  {
    float envelope = smoothstep(0.04, 0.88, u_audio);
    float twListen = (0.42 + 0.58 * sin(u_time * (8.5 + a_seed * 6.0) + a_seed * 36.0));
    twListen *= 0.70 + 0.30 * envelope;
    twinkle = mix(twinkle, twListen, wListen);
  }
  col *= 0.65 + 0.35 * twinkle;
  col = stateTint(col);

  {
    float synapse = pow(max(0.0, sin(u_time * 2.9 - r * 3.8 + a_seed * 28.0)), 10.0);
    col *= 1.0 + synapse * 0.85 * wThink;
    col += vec3(0.35, 0.18, 0.65) * synapse * 0.45 * wThink;
  }
  {
    float envelope = smoothstep(0.04, 0.88, u_audio);
    float vocalFlash = pow(max(0.0, sin(u_time * 9.0 - r * 5.5 + a_seed * 26.0)), 9.0);
    col *= 1.0 + vocalFlash * (0.65 + 0.35 * envelope) * wSpeak;
    col += vec3(0.12, 0.62, 0.48) * vocalFlash * (0.35 + 0.40 * envelope) * wSpeak;
    col += vec3(0.18, 0.82, 0.68) * envelope * 0.18 * wSpeak;
  }
  {
    float envelope = smoothstep(0.04, 0.88, u_audio);
    float listenFlash = pow(max(0.0, sin(u_time * 10.5 - r * 4.8 + a_seed * 22.0)), 9.0);
    col *= 1.0 + listenFlash * (0.55 + 0.35 * envelope) * wListen;
    col += vec3(0.22, 0.58, 0.95) * listenFlash * (0.30 + 0.35 * envelope) * wListen;
    col += vec3(0.35, 0.78, 1.0) * envelope * 0.16 * wListen;
  }

  vec3 dHalo = vec3(0.48, 0.24, 0.36);
  vec3 dCore = vec3(0.78, 0.40, 0.52);
  vec3 dArm  = vec3(0.52, 0.20, 0.32);
  vec3 dDust = vec3(0.38, 0.18, 0.28);
  vec3 colDormant;
  if (a_kind < 0.5) colDormant = dHalo;
  else if (a_kind < 1.5) colDormant = mix(dCore, dArm, smoothstep(0.0, 0.32, r));
  else colDormant = mix(dArm, dDust, smoothstep(0.35, 2.0, r));
  colDormant *= 0.55 + 0.30 * sin(u_time * 0.45 + a_seed * 12.0);
  col = mix(col, colDormant, u_dormant);

  float fade = 1.0 - smoothstep(1.2, 1.7, r);
  if (a_kind < 0.5) fade = 0.8 * (1.0 - smoothstep(1.3, 1.8, r));
  fade = mix(fade, 1.0, u_dormant * 0.85);

  float breathBright = 1.0 + 0.10 * u_breath * alive * mix(0.35, 1.0, smoothstep(0.0, 1.2, r));
  col *= breathBright;

  v_alpha = fade * vis * breathBright;
  v_color = col;
}
`;

export const FRAG_PARTICLE = `#version 300 es
precision highp float;

in float v_alpha;
in vec3  v_color;
out vec4 outColor;

void main() {
  vec2  uv = gl_PointCoord - 0.5;
  float d  = length(uv);
  if (d > 0.5) discard;

  float glow = exp(-d * d * 14.0) + exp(-d * d * 4.5) * 0.25;

  outColor = vec4(v_color, v_alpha * glow);
}
`;

export const VERT_CORE = `#version 300 es
precision highp float;

layout(location = 0) in vec2 a_corner;

uniform mat4  u_viewProj;
uniform float u_time;
uniform float u_state;
uniform float u_energy;
uniform float u_audio;
uniform float u_dormant;
uniform float u_breath;
uniform vec2  u_screenOffset;
uniform vec2  u_resolution;

out vec2  v_uv;
out vec3  v_color;
out float v_alpha;

${GLSL_STATE}

void main() {
  float wSpeak = stateW(3.0);
  float wThink = stateW(2.0);
  float wListen = stateW(1.0);
  float wIdle = max(0.0, 1.0 - wSpeak - wThink - wListen * 0.85);

  float breathIdle = 1.0 + 0.13 * u_breath;
  float breathThink = 1.0 + 0.09 * sin(u_time * 4.2) + 0.06 * sin(u_time * 6.8 + 1.4);
  float envelope = smoothstep(0.04, 0.88, u_audio);
  float ripple = sin(u_time * 6.5 + envelope * 2.0) * envelope;
  float organic = clamp(envelope + ripple * 0.12, 0.0, 1.0);
  float breathWave = (organic - 0.42) * 1.8;
  float vocalA = sin(u_time * 16.0) * envelope;
  float vocalB = sin(u_time * 24.0 + 0.6) * envelope * 0.45;
  float breathSpeak = 1.0 + (0.08 + 0.14 * envelope) * breathWave + vocalA * 0.04 + vocalB * 0.025;
  float listenEnv = smoothstep(0.04, 0.88, u_audio);
  float listenRipple = sin(u_time * 7.8 + listenEnv * 2.4) * listenEnv;
  float listenOrganic = clamp(listenEnv + listenRipple * 0.14, 0.0, 1.0);
  float listenWave = (listenOrganic - 0.38) * 1.6;
  float listenA = sin(u_time * 18.0) * listenEnv;
  float listenB = sin(u_time * 26.0 + 0.8) * listenEnv * 0.42;
  float breathListen = 1.0 + (0.06 + 0.12 * listenEnv) * listenWave + listenA * 0.035 + listenB * 0.022;
  float breath = breathIdle * wIdle + breathThink * wThink + breathSpeak * wSpeak + breathListen * wListen;
  if (u_dormant > 0.05) breath = mix(breath, 1.0, u_dormant);

  float vis = mix(0.55 + 0.45 * u_energy, 0.40 + 0.22 * u_energy, u_dormant);

  vec4 clip = u_viewProj * vec4(0.0, 0.0, 0.0, 1.0);
  clip.xy += u_screenOffset * clip.w;
  float depth = max(0.5, clip.w);

  float radiusPx = mix(60.0, 96.0, vis) * breath;
  radiusPx += wListen * (14.0 + listenEnv * 16.0 + listenRipple * 8.0);
  {
    float thinkPulse = sin(u_time * 3.6) * 0.5 + sin(u_time * 5.9 + 0.8) * 0.3;
    radiusPx += wThink * (14.0 + thinkPulse * 10.0);
  }
  {
    float speakPulse = sin(u_time * 5.5) * 0.5 + sin(u_time * 9.2 + 0.5) * 0.35;
    radiusPx += wSpeak * (18.0 + speakPulse * 12.0 * (0.45 + 0.55 * envelope));
  }

  float aspect = u_resolution.x / u_resolution.y;
  vec2 corner = a_corner;
  corner.x /= aspect;
  vec2 ndc = corner * (radiusPx / u_resolution.y);
  gl_Position = clip;
  gl_Position.xy += ndc * clip.w;

  v_uv = a_corner * 0.5 + 0.5;

  float twinkle = 0.70 + 0.30 * sin(u_time * 3.5 + 20.0);
  vec3 coreCol = vec3(1.00, 0.88, 0.58);
  vec3 dormantCore = vec3(0.82, 0.42, 0.55);
  vec3 col = mix(coreCol, dormantCore, u_dormant);
  col *= 0.65 + 0.35 * twinkle;
  col *= 1.0 + 0.08 * u_breath * (1.0 - u_dormant);
  col *= 1.0 + envelope * 0.22 * wSpeak;
  col *= 1.0 + listenEnv * 0.18 * wListen;
  v_color = stateTint(col);
  v_alpha = (0.50 + 0.35 * vis) * (0.80 + 0.12 * u_energy) * (1.0 + 0.06 * u_breath * (1.0 - u_dormant));
  v_alpha *= mix(1.0, 0.85 + 0.25 * envelope, wSpeak);
  v_alpha *= mix(1.0, 0.82 + 0.28 * listenEnv, wListen);
}
`;

export const FRAG_CORE = `#version 300 es
precision highp float;

in vec2  v_uv;
in vec3  v_color;
in float v_alpha;

uniform float u_state;
uniform float u_dormant;
uniform float u_time;
uniform float u_audio;

out vec4 outColor;

${GLSL_STATE}

void main() {
  vec2 uv = v_uv - 0.5;
  float d = length(uv) * 2.0;
  if (d > 1.0) discard;

  vec3 armCol = mix(vec3(0.45, 0.55, 1.0), vec3(0.72, 0.42, 0.95), 0.5);
  vec3 armDormant = vec3(0.50, 0.22, 0.34);
  armCol = mix(armCol, armDormant, u_dormant);
  armCol = stateTint(armCol);
  vec3 col = mix(v_color, armCol, smoothstep(0.25, 0.85, d));

  float wThink = stateW(2.0);
  float wSpeak = stateW(3.0);
  float wListen = stateW(1.0);
  {
    float ring1 = sin(d * 10.0 - u_time * 5.5) * 0.5 + 0.5;
    float ring2 = sin(d * 14.0 - u_time * 7.2 + 1.1) * 0.5 + 0.5;
    ring1 *= smoothstep(0.15, 0.95, d) * (1.0 - smoothstep(0.85, 1.0, d));
    ring2 *= smoothstep(0.25, 0.90, d) * (1.0 - smoothstep(0.80, 1.0, d));
    col += vec3(0.55, 0.28, 0.95) * ring1 * 0.22 * wThink;
    col += vec3(0.40, 0.55, 1.0) * ring2 * 0.12 * wThink;
  }
  {
    float env = smoothstep(0.04, 0.88, u_audio);
    float ring1 = sin(d * 13.0 - u_time * 9.0) * 0.5 + 0.5;
    float ring2 = sin(d * 19.0 - u_time * 12.5 + 1.2) * 0.5 + 0.5;
    float ring3 = sin(d * 8.0 - u_time * 6.8 + 2.4) * 0.5 + 0.5;
    ring1 *= smoothstep(0.08, 0.96, d) * (1.0 - smoothstep(0.90, 1.0, d));
    ring2 *= smoothstep(0.18, 0.94, d) * (1.0 - smoothstep(0.84, 1.0, d));
    ring3 *= smoothstep(0.30, 0.88, d) * (1.0 - smoothstep(0.78, 1.0, d));
    col += vec3(0.20, 0.88, 0.62) * ring1 * (0.20 + 0.28 * env) * wSpeak;
    col += vec3(0.30, 0.95, 0.75) * ring2 * (0.12 + 0.18 * env) * wSpeak;
    col += vec3(0.45, 0.98, 0.85) * ring3 * (0.08 + 0.12 * env) * wSpeak;
  }
  {
    float env = smoothstep(0.04, 0.88, u_audio);
    float ring1 = sin(d * 12.0 - u_time * 10.5) * 0.5 + 0.5;
    float ring2 = sin(d * 17.0 - u_time * 13.0 + 1.0) * 0.5 + 0.5;
    ring1 *= smoothstep(0.10, 0.94, d) * (1.0 - smoothstep(0.88, 1.0, d));
    ring2 *= smoothstep(0.20, 0.90, d) * (1.0 - smoothstep(0.82, 1.0, d));
    col += vec3(0.28, 0.62, 0.98) * ring1 * (0.18 + 0.24 * env) * wListen;
    col += vec3(0.40, 0.78, 1.0) * ring2 * (0.10 + 0.16 * env) * wListen;
  }

  float glow = exp(-d * d * 14.0) + exp(-d * d * 4.5) * 0.25;

  outColor = vec4(col, v_alpha * glow);
}
`;

export const VERT_BG = `#version 300 es
precision highp float;
const vec2 pos[3] = vec2[](
  vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0)
);
out vec2 v_uv;
void main() {
  v_uv = pos[gl_VertexID];
  gl_Position = vec4(pos[gl_VertexID], 0.0, 1.0);
}
`;

export const FRAG_BG = `#version 300 es
precision highp float;

in  vec2  v_uv;
out vec4  outColor;

uniform float u_time;
uniform float u_state;
uniform float u_energy;
uniform float u_audio;
uniform float u_dormant;
uniform float u_breath;
uniform vec2  u_resolution;
uniform vec2  u_center;   // UV com origem no canto inferior esquerdo

${GLSL_STATE}

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

float stars(vec2 uv, float sc) {
  vec2 id = floor(uv * sc);
  vec2 f  = fract(uv * sc);
  float n = hash(id);
  float s = smoothstep(0.990, 1.0, n);
  float d = length(f - vec2(hash(id + 0.1), hash(id + 0.7)));
  return s * exp(-d * 110.0);
}

void main() {
  // p centrado em u_center, corrigido por aspect
  vec2  uv     = gl_FragCoord.xy / u_resolution;
  float aspect = u_resolution.x / u_resolution.y;
  vec2  p      = (uv - u_center) * vec2(aspect, 1.0);
  float dist   = length(p);
  float t      = u_time * 0.04;

  // Nebulosa de fundo (ativa vs parada)
  vec3 deep    = vec3(0.007, 0.005, 0.020);
  vec3 nebA    = vec3(0.10, 0.05, 0.22);
  vec3 nebB    = vec3(0.04, 0.09, 0.18);
  float wThink = stateWAny(2.0);
  float wSpeak = stateWAny(3.0);
  float wListen = stateWAny(1.0);
  float wError = stateWAny(4.0);
  nebA = mix(nebA, vec3(0.16, 0.05, 0.32), wThink);
  nebB = mix(nebB, vec3(0.06, 0.05, 0.26), wThink);
  nebA = mix(nebA, vec3(0.06, 0.12, 0.22), wListen);
  nebB = mix(nebB, vec3(0.03, 0.08, 0.16), wListen);
  nebA = mix(nebA, vec3(0.04, 0.14, 0.18), wSpeak);
  nebB = mix(nebB, vec3(0.02, 0.10, 0.14), wSpeak);
  nebA = mix(nebA, vec3(0.22, 0.04, 0.08), wError);
  nebB = mix(nebB, vec3(0.10, 0.03, 0.06), wError);

  vec3 deepD   = vec3(0.014, 0.003, 0.010);
  vec3 nebAd   = vec3(0.20, 0.05, 0.12);
  vec3 nebBd   = vec3(0.08, 0.02, 0.06);
  deep = mix(deep, deepD, u_dormant);
  nebA = mix(nebA, nebAd, u_dormant);
  nebB = mix(nebB, nebBd, u_dormant);

  float alive = 1.0 - u_dormant;
  float distBreath = dist / (1.0 + 0.055 * u_breath * alive);
  float neb = exp(-distBreath * distBreath * 2.0) * (0.4 + 0.35 * u_energy * alive)
            + exp(-distBreath * 1.3) * 0.12 * sin(u_time * 0.5 + distBreath * 4.0) * alive;
  neb *= 1.0 + 0.16 * u_breath * alive;
  {
    float angle = atan(p.y, p.x);
    float swirl = sin(angle * 4.0 + u_time * 1.8 - dist * 5.0) * 0.5 + 0.5;
    neb *= 1.0 + 0.35 * swirl * alive * stateW(2.0);
  }
  {
    float angle = atan(p.y, p.x);
    float env = smoothstep(0.04, 0.88, u_audio);
    float aurora = sin(angle * 3.0 + u_time * 2.4 - dist * 4.5) * 0.5 + 0.5;
    aurora *= sin(dist * 6.0 - u_time * 3.8) * 0.5 + 0.5;
    neb *= 1.0 + (0.28 + 0.32 * env) * aurora * alive * stateW(3.0);
  }
  {
    float angle = atan(p.y, p.x);
    float env = smoothstep(0.04, 0.88, u_audio);
    float aurora = sin(angle * 3.5 + u_time * 2.8 - dist * 5.0) * 0.5 + 0.5;
    aurora *= sin(dist * 7.0 - u_time * 4.2) * 0.5 + 0.5;
    neb *= 1.0 + (0.22 + 0.38 * env) * aurora * alive * stateW(1.0);
  }
  vec3 col = deep;
  col = mix(col, nebB, neb * 0.6);
  col = mix(col, nebA, neb * neb * 0.7);

  {
    float ripple = sin(dist * 14.0 - u_time * 4.2) * 0.5 + 0.5;
    ripple *= exp(-dist * 2.8) * alive * stateW(2.0);
    col += vec3(0.45, 0.22, 0.78) * ripple * 0.10;
    float ripple2 = sin(dist * 9.0 - u_time * 2.6 + 2.0) * 0.5 + 0.5;
    ripple2 *= exp(-dist * 3.5) * alive * stateW(2.0);
    col += vec3(0.30, 0.40, 0.95) * ripple2 * 0.06;
  }

  {
    float env = smoothstep(0.04, 0.88, u_audio);
    float sonic = sin(dist * 16.0 - u_time * 10.0) * 0.5 + 0.5;
    sonic *= exp(-dist * 2.2) * alive * stateW(3.0);
    col += vec3(0.15, 0.72, 0.55) * sonic * (0.08 + 0.14 * env);
    float sonic2 = sin(dist * 11.0 - u_time * 7.5 + 1.8) * 0.5 + 0.5;
    sonic2 *= exp(-dist * 3.0) * alive * stateW(3.0);
    col += vec3(0.22, 0.85, 0.68) * sonic2 * (0.05 + 0.10 * env);
  }

  {
    float env = smoothstep(0.04, 0.88, u_audio);
    float sonic = sin(dist * 15.0 - u_time * 11.0) * 0.5 + 0.5;
    sonic *= exp(-dist * 2.4) * alive * stateW(1.0);
    col += vec3(0.20, 0.55, 0.95) * sonic * (0.07 + 0.12 * env);
    float sonic2 = sin(dist * 10.0 - u_time * 8.0 + 1.5) * 0.5 + 0.5;
    sonic2 *= exp(-dist * 3.2) * alive * stateW(1.0);
    col += vec3(0.32, 0.72, 1.0) * sonic2 * (0.04 + 0.09 * env);
  }

  // Estrelas de fundo (mais frias e fracas quando parada)
  float starMul = mix(1.0, 0.42, u_dormant);
  vec3 starTint = mix(vec3(1.0), vec3(0.85, 0.55, 0.65), u_dormant);
  col += stars(p + vec2(t * 0.02,  t * 0.01),  180.0) * 0.6 * starMul * starTint;
  col += stars(p - vec2(t * 0.015, t * 0.008), 260.0) * 0.4 * starMul * starTint;
  col += stars(p + vec2(0.31, 0.17),            420.0) * 0.25 * starMul * starTint;

  // Brilho suave do núcleo (fundo) — pulsa com a respiração quando ativa
  float corePulseIdle = 1.0 + 0.14 * u_breath * alive;
  float corePulseThink = 1.0 + 0.20 * sin(u_time * 3.8) + 0.12 * sin(u_time * 6.3 + 0.7);
  float envGlow = smoothstep(0.04, 0.88, u_audio);
  float corePulseSpeak = 1.0 + 0.18 * sin(u_time * 5.2) * (0.5 + 0.5 * envGlow)
                           + 0.14 * sin(u_time * 8.8 + 0.5) * envGlow
                           + 0.08 * sin(u_time * 14.0) * envGlow;
  float corePulseListen = 1.0 + 0.16 * sin(u_time * 6.0) * (0.5 + 0.5 * envGlow)
                            + 0.12 * sin(u_time * 9.5 + 0.6) * envGlow
                            + 0.07 * sin(u_time * 15.0) * envGlow;
  float corePulse = corePulseIdle * max(0.0, 1.0 - wThink - wSpeak - wListen * 0.85)
                  + corePulseThink * stateW(2.0)
                  + corePulseSpeak * stateW(3.0)
                  + corePulseListen * stateW(1.0);
  vec3 glowA = mix(vec3(1.0, 0.98, 0.88), vec3(0.95, 0.55, 0.62), u_dormant);
  vec3 glowB = mix(vec3(1.0, 0.82, 0.45), vec3(0.72, 0.28, 0.38), u_dormant);
  vec3 glowC = mix(vec3(0.5, 0.6, 1.0),  vec3(0.45, 0.18, 0.28), u_dormant);
  glowB = mix(glowB, vec3(0.35, 0.95, 0.72), stateW(3.0) * 0.55);
  glowB = mix(glowB, vec3(0.42, 0.78, 1.0), stateW(1.0) * 0.48);
  glowC = mix(glowC, vec3(0.25, 0.82, 0.62), stateW(3.0) * 0.45);
  glowC = mix(glowC, vec3(0.30, 0.62, 0.98), stateW(1.0) * 0.42);
  float glowStr = mix(1.0 + 0.12 * u_breath * alive, 1.35, u_dormant);
  col += glowA * exp(-distBreath*distBreath*80.0) * corePulse * (0.14 + 0.10 * u_energy) * glowStr;
  col += glowB * exp(-distBreath*distBreath*28.0) * corePulse * (0.07 + 0.06 * u_energy) * glowStr;
  col += glowC * exp(-distBreath*distBreath*10.0) * corePulse * 0.04 * glowStr;

  // Vignette
  col *= 1.0 - smoothstep(0.25, 1.35, dist);

  outColor = vec4(col, 1.0);
}
`;
