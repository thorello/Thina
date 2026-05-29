// Órbita circular uniforme em torno da origem (centro do núcleo).
export const VERT_PARTICLE = `#version 300 es
precision highp float;

layout(location = 0) in vec3 a_position;
layout(location = 1) in float a_seed;
layout(location = 2) in float a_kind;

uniform mat4  u_viewProj;
uniform float u_time;
uniform float u_state;
uniform float u_energy;
uniform float u_audio;
uniform vec2  u_screenOffset;

out float v_alpha;
out vec3  v_color;

vec3 stateTint(vec3 base) {
  vec3 c = base;
  if (u_state > 0.5 && u_state < 1.5) c = mix(base, vec3(0.45, 0.95, 1.0),  0.5);
  else if (u_state > 1.5 && u_state < 2.5) c = mix(base, vec3(0.78, 0.55, 1.0),  0.5);
  else if (u_state > 2.5 && u_state < 3.5) c = mix(base, vec3(0.55, 0.95, 0.82), 0.5);
  else if (u_state > 3.5) c = mix(base, vec3(1.0, 0.42, 0.45), 0.65);
  return c;
}

// Rotação no plano XZ em torno de (0,0,0) — mesma ω para todas as partículas do disco.
vec3 orbit(vec3 p) {
  if (a_kind > 2.5) return p;
  float r = length(p.xz);
  if (r < 0.001) return vec3(0.0, p.y, 0.0);
  float theta = atan(p.z, p.x) + u_time * (0.038 * (1.0 + 0.20 * u_energy));
  return vec3(r * cos(theta), p.y, r * sin(theta));
}

void main() {
  vec3 p = orbit(a_position);
  float r = length(p.xz);

  // Pulso radial ao falar — envelope suave + onda orgânica por partícula
  bool isSpeaking = u_state > 2.5 && u_state < 3.5;
  if (isSpeaking) {
    float radialW = mix(0.45, 1.0, smoothstep(0.05, 0.9, r));
    float envelope = smoothstep(0.08, 0.72, u_audio);
    float ripple = sin(u_time * 5.8 - r * 3.8 + a_seed * 40.0) * envelope;
    float organic = clamp(envelope + ripple * 0.09, 0.0, 1.0);
    float breathWave = (organic - 0.46) * 1.6;
    float breathAmp = 0.06 + 0.11 * envelope;
    float scale = 1.0 + breathAmp * breathWave * radialW;
    p.xz *= scale;
    p.y *= 1.0 + breathAmp * breathWave * 0.20 * radialW;
  }

  vec4 clip  = u_viewProj * vec4(p, 1.0);
  clip.xy   += u_screenOffset * clip.w;   // desloca para o ponto focal
  gl_Position = clip;

  // Tamanho perspectivo: usa clip.w (profundidade real)
  float depth = max(0.5, clip.w);
  float twinkle = 0.70 + 0.30 * sin(u_time * (2.0 + a_seed * 3.0) + a_seed * 40.0);
  float vis = 0.55 + 0.45 * u_energy;

  float sz;
  if (a_kind < 0.5) {
    sz = mix(0.7, 1.1, twinkle);
  } else if (a_kind < 1.5) {
    sz = mix(0.8, 1.4, vis) * (1.0 + 0.25 * exp(-r * 2.5));
  } else {
    sz = mix(0.75, 1.3, twinkle);
  }

  if (u_state > 0.5 && u_state < 1.5) sz += 0.25;
  if (u_state > 1.5 && u_state < 2.5) sz += 0.15;
  if (u_state > 2.5 && u_state < 3.5) sz += 0.4;

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

  col *= 0.65 + 0.35 * twinkle;
  col = stateTint(col);

  float fade = 1.0 - smoothstep(1.2, 1.7, r);
  if (a_kind < 0.5) fade = 0.8 * (1.0 - smoothstep(1.3, 1.8, r));

  v_alpha = fade * vis;
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
uniform vec2  u_screenOffset;
uniform vec2  u_resolution;

out vec2  v_uv;
out vec3  v_color;
out float v_alpha;

vec3 stateTint(vec3 base) {
  vec3 c = base;
  if (u_state > 0.5 && u_state < 1.5) c = mix(base, vec3(0.45, 0.95, 1.0),  0.5);
  else if (u_state > 1.5 && u_state < 2.5) c = mix(base, vec3(0.78, 0.55, 1.0),  0.5);
  else if (u_state > 2.5 && u_state < 3.5) c = mix(base, vec3(0.55, 0.95, 0.82), 0.5);
  else if (u_state > 3.5) c = mix(base, vec3(1.0, 0.42, 0.45), 0.65);
  return c;
}

void main() {
  bool isIdle = u_state < 0.5;
  bool isSpeaking = u_state > 2.5 && u_state < 3.5;
  float breath = 1.0;
  if (isSpeaking) {
    float envelope = smoothstep(0.08, 0.72, u_audio);
    float ripple = sin(u_time * 5.2) * envelope;
    float organic = clamp(envelope + ripple * 0.07, 0.0, 1.0);
    float breathWave = (organic - 0.46) * 1.6;
    breath = 1.0 + (0.06 + 0.10 * envelope) * breathWave;
  } else if (isIdle) {
    breath = 1.0 + 0.06 * sin(u_time * 0.72);
  }
  float vis = 0.55 + 0.45 * u_energy;

  vec4 clip = u_viewProj * vec4(0.0, 0.0, 0.0, 1.0);
  clip.xy += u_screenOffset * clip.w;
  float depth = max(0.5, clip.w);

  float radiusPx = mix(60.0, 96.0, vis) * breath;
  if (u_state > 0.5 && u_state < 1.5) radiusPx += 12.0;
  if (u_state > 1.5 && u_state < 2.5) radiusPx += 8.0;
  if (u_state > 2.5 && u_state < 3.5) radiusPx += 20.0;

  float aspect = u_resolution.x / u_resolution.y;
  vec2 corner = a_corner;
  corner.x /= aspect;
  vec2 ndc = corner * (radiusPx / u_resolution.y);
  gl_Position = clip;
  gl_Position.xy += ndc * clip.w;

  v_uv = a_corner * 0.5 + 0.5;

  // mesma paleta do bulbo no centro (kind=1, r≈0)
  float twinkle = 0.70 + 0.30 * sin(u_time * 3.5 + 20.0);
  vec3 coreCol = vec3(1.00, 0.88, 0.58);
  vec3 col = coreCol;
  col *= 0.65 + 0.35 * twinkle;
  v_color = stateTint(col);
  v_alpha = (0.50 + 0.35 * vis) * (0.80 + 0.12 * u_energy);
}
`;

export const FRAG_CORE = `#version 300 es
precision highp float;

in vec2  v_uv;
in vec3  v_color;
in float v_alpha;

uniform float u_state;

out vec4 outColor;

vec3 stateTint(vec3 base) {
  vec3 c = base;
  if (u_state > 0.5 && u_state < 1.5) c = mix(base, vec3(0.45, 0.95, 1.0),  0.5);
  else if (u_state > 1.5 && u_state < 2.5) c = mix(base, vec3(0.78, 0.55, 1.0),  0.5);
  else if (u_state > 2.5 && u_state < 3.5) c = mix(base, vec3(0.55, 0.95, 0.82), 0.5);
  else if (u_state > 3.5) c = mix(base, vec3(1.0, 0.42, 0.45), 0.65);
  return c;
}

void main() {
  vec2 uv = v_uv - 0.5;
  float d = length(uv) * 2.0;
  if (d > 1.0) discard;

  // transição para armCol como nas partículas do bulbo/disco interno
  vec3 armCol = mix(vec3(0.45, 0.55, 1.0), vec3(0.72, 0.42, 0.95), 0.5);
  armCol = stateTint(armCol);
  vec3 col = mix(v_color, armCol, smoothstep(0.25, 0.85, d));

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
uniform vec2  u_resolution;
uniform vec2  u_center;   // UV com origem no canto inferior esquerdo

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

  // Nebulosa de fundo
  vec3 deep    = vec3(0.007, 0.005, 0.020);
  vec3 nebA    = vec3(0.10, 0.05, 0.22);
  vec3 nebB    = vec3(0.04, 0.09, 0.18);
  if (u_state > 1.5 && u_state < 2.5) { nebA = vec3(0.14, 0.04, 0.28); nebB = vec3(0.05, 0.04, 0.22); }
  if (u_state > 3.5)                  { nebA = vec3(0.22, 0.04, 0.08); nebB = vec3(0.10, 0.03, 0.06); }

  float neb = exp(-dist * dist * 2.0) * (0.4 + 0.35 * u_energy)
            + exp(-dist * 1.3) * 0.12 * sin(u_time * 0.5 + dist * 4.0);
  vec3 col = deep;
  col = mix(col, nebB, neb * 0.6);
  col = mix(col, nebA, neb * neb * 0.7);

  // Estrelas de fundo
  col += stars(p + vec2(t * 0.02,  t * 0.01),  180.0) * 0.6;
  col += stars(p - vec2(t * 0.015, t * 0.008), 260.0) * 0.4;
  col += stars(p + vec2(0.31, 0.17),            420.0) * 0.25;

  // Brilho suave do núcleo (fundo)
  bool  isIdle = u_state < 0.5;
  float breath = 1.0 + (isIdle ? 0.10 : 0.04) * sin(u_time * 0.72);
  col += vec3(1.0, 0.98, 0.88) * exp(-dist*dist*80.0) * breath * (0.14 + 0.10 * u_energy);
  col += vec3(1.0, 0.82, 0.45) * exp(-dist*dist*28.0) * breath * (0.07 + 0.06 * u_energy);
  col += vec3(0.5,  0.6, 1.0)  * exp(-dist*dist*10.0) * breath * 0.04;

  // Vignette
  col *= 1.0 - smoothstep(0.25, 1.35, dist);

  outColor = vec4(col, 1.0);
}
`;
