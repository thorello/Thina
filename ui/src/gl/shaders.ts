export const VERT_PARTICLE = `#version 300 es
precision highp float;

layout(location = 0) in vec3 a_position;
layout(location = 1) in float a_seed;

uniform mat4 u_viewProj;
uniform float u_time;
uniform float u_state;
uniform float u_energy;

out float v_alpha;
out vec3 v_color;

// Simplex-ish swirl from seed
vec3 swirl(vec3 p, float t, float s) {
  float ang = t * (0.4 + s * 0.3) + s * 6.28318;
  float r = length(p.xz);
  float lift = sin(t * 1.2 + s * 10.0) * 0.15 * (1.0 + u_energy);
  p.x += cos(ang) * 0.08 * r;
  p.z += sin(ang) * 0.08 * r;
  p.y += lift;
  return p;
}

void main() {
  vec3 p = swirl(a_position, u_time, a_seed);
  float pulse = 1.0 + 0.12 * sin(u_time * 2.0 + a_seed * 20.0) * (0.5 + u_energy);
  p *= pulse;

  vec4 clip = u_viewProj * vec4(p, 1.0);
  gl_Position = clip;

  float dist = length(p);
  float sizeBase = mix(2.0, 5.5, u_energy);
  float stateBoost = 0.0;
  if (u_state > 0.5 && u_state < 1.5) sizeBase += 2.0; // listening
  if (u_state > 1.5 && u_state < 2.5) sizeBase += 1.5; // thinking
  if (u_state > 2.5 && u_state < 3.5) sizeBase += 3.0; // speaking
  gl_PointSize = sizeBase * (1.0 / max(0.2, -clip.z * 0.5));

  v_alpha = smoothstep(2.2, 0.3, dist) * (0.35 + 0.65 * u_energy);

  vec3 cIdle = vec3(0.37, 0.92, 0.83);
  vec3 cListen = vec3(0.55, 0.95, 1.0);
  vec3 cThink = vec3(0.66, 0.55, 0.98);
  vec3 cSpeak = vec3(0.4, 0.95, 0.7);
  vec3 cErr = vec3(0.98, 0.45, 0.45);

  vec3 col = cIdle;
  if (u_state > 0.5 && u_state < 1.5) col = cListen;
  else if (u_state > 1.5 && u_state < 2.5) col = cThink;
  else if (u_state > 2.5 && u_state < 3.5) col = cSpeak;
  else if (u_state > 3.5) col = cErr;

  v_color = mix(col, vec3(1.0), 0.15 * sin(a_seed * 40.0 + u_time));
}
`;

export const FRAG_PARTICLE = `#version 300 es
precision highp float;

in float v_alpha;
in vec3 v_color;
out vec4 outColor;

void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float d = length(uv);
  if (d > 0.5) discard;
  float glow = exp(-d * d * 8.0);
  outColor = vec4(v_color, v_alpha * glow);
}
`;

export const VERT_BG = `#version 300 es
precision highp float;

const vec2 positions[3] = vec2[](
  vec2(-1.0, -1.0),
  vec2(3.0, -1.0),
  vec2(-1.0, 3.0)
);

out vec2 v_uv;

void main() {
  v_uv = positions[gl_VertexID];
  gl_Position = vec4(positions[gl_VertexID], 0.0, 1.0);
}
`;

export const FRAG_BG = `#version 300 es
precision highp float;

in vec2 v_uv;
uniform float u_time;
uniform float u_state;
uniform float u_energy;
uniform vec2 u_resolution;

out vec4 outColor;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

void main() {
  vec2 uv = v_uv;
  vec2 aspect = vec2(u_resolution.x / u_resolution.y, 1.0);
  vec2 p = (uv - 0.5) * aspect;

  float t = u_time * 0.15;
  float n = noise(p * 3.0 + t) * 0.5 + noise(p * 6.0 - t * 1.3) * 0.25;

  vec3 base = vec3(0.02, 0.03, 0.07);
  vec3 accent = vec3(0.05, 0.12, 0.14);
  if (u_state > 1.5 && u_state < 2.5) accent = vec3(0.08, 0.05, 0.16);
  if (u_state > 3.5) accent = vec3(0.14, 0.04, 0.05);

  float orb = 1.0 - smoothstep(0.15, 0.55, length(p));
  float pulse = 0.5 + 0.5 * sin(u_time * (1.0 + u_energy * 2.0));
  orb *= 0.25 + 0.35 * pulse * (0.3 + u_energy);

  vec3 col = mix(base, accent, n * 0.6);
  col += vec3(0.15, 0.45, 0.42) * orb * (0.4 + u_energy);
  if (u_state > 1.5 && u_state < 2.5)
    col += vec3(0.25, 0.15, 0.45) * orb * 0.5;

  float vignette = smoothstep(1.2, 0.2, length(p));
  col *= vignette;

  outColor = vec4(col, 1.0);
}
`;
