// Escalas de color agronómicas (interpolación lineal entre paradas) y colores de clases.

function parseColor(c) {
  if (c.startsWith('#')) {
    const h = c.slice(1);
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 1];
  }
  const p = c.match(/rgba?\(([^)]+)\)/)[1].split(',').map(Number);
  return [p[0], p[1], p[2], p[3] ?? 1];
}

export function makeScale(stops) {
  const s = stops.map(([v, c]) => [v, parseColor(c)]);
  return (v) => {
    if (v == null || Number.isNaN(v)) return null;
    if (v <= s[0][0]) return s[0][1];
    if (v >= s[s.length - 1][0]) return s[s.length - 1][1];
    for (let i = 1; i < s.length; i++) {
      if (v <= s[i][0]) {
        const [v0, c0] = s[i - 1], [v1, c1] = s[i];
        const t = (v - v0) / (v1 - v0);
        return c0.map((x, k) => x + (c1[k] - x) * t);
      }
    }
    return null;
  };
}

const even = (min, max, colors) => colors.map((c, i) => [min + (max - min) * i / (colors.length - 1), c]);

const ALERT_STOPS = [[0, 'rgba(255,235,238,0)'], [0.3, 'rgba(255,138,128,0.55)'],
  [0.6, 'rgba(229,57,53,0.8)'], [1, 'rgba(139,0,0,0.95)']];

const NUMERIC = {
  clay: { min: 0, max: 60, unit: '%', ticks: [0, 15, 30, 45, 60], stops: even(0, 60, ['#F5EBDC', '#5A3A1E']) },
  sand: { min: 0, max: 100, unit: '%', ticks: [0, 25, 50, 75, 100], stops: even(0, 100, ['#FFF7D6', '#E8B500']) },
  silt: { min: 0, max: 100, unit: '%', ticks: [0, 25, 50, 75, 100], stops: even(0, 100, ['#F4EAD5', '#A0782C']) },
  ph: { min: 3.5, max: 9, unit: '', ticks: [3.5, 5, 6, 7, 8, 9],
    stops: [[3.5, '#B2182B'], [5.0, '#EF8A29'], [6.0, '#F2D24B'], [6.5, '#2CA25F'], [7.5, '#2CA25F'], [8.2, '#3B7DD8'], [9.0, '#6A3D9A']] },
  soc: { min: 0, max: 60, unit: 'g/kg', ticks: [0, 15, 30, 45, 60], stops: even(0, 60, ['#FFF5C9', '#C9A15B', '#5C3A1A', '#1E140A']) },
  nfk: { min: 0, max: 30, unit: 'mm/dm', ticks: [0, 10, 20, 30], stops: even(0, 30, ['#F7FBFF', '#6BAED6', '#08306B']) },
  quality: { min: 0, max: 100, unit: '', ticks: [0, 30, 50, 70, 100],
    stops: [[0, '#C62828'], [30, '#F57C00'], [50, '#FBC02D'], [70, '#7CB342'], [100, '#1B5E20']] },
  alert: { min: 0, max: 1, unit: '', ticks: [0, 0.5, 1], stops: ALERT_STOPS },
};

// Fiabilidad: el valor del grid es sampling_priority (0-1) = (100 − índice)/100 → escala de alerta.
const RELIABILITY = { min: 0, max: 1, unit: '', stops: ALERT_STOPS, ticks: [0, 0.25, 0.5, 0.75, 1],
  tickLabel: (v) => String(Math.round(100 * (1 - v))), caption: 'Reliability index (high → low)' };

// ---------- clases de textura ----------
export const BS_COLORS = { S: '#F3E3B5', Sl: '#EBCF8E', lS: '#DDB66B', SL: '#C99A4E', sL: '#B07D3A',
  L: '#93632C', LT: '#6F4520', T: '#4E2F17', Mo: '#2B2B2B' };
export const BS_NAMES = { S: 'Sand', Sl: 'Slightly loamy sand', lS: 'Loamy sand', SL: 'Strongly loamy sand',
  sL: 'Sandy loam', L: 'Loam', LT: 'Heavy loam', T: 'Clay', Mo: 'Peat' };
const BS_ORDER = Object.keys(BS_COLORS);

const KA5_GROUPS = {
  S: { from: '#F3E3B5', to: '#DDB66B', order: ['Ss', 'gS', 'mS', 'mSgs', 'fS', 'mSfs', 'fSms', 'fSgs', 'Su2', 'Sl2',
    'St2', 'Su3', 'Sl3', 'Su4', 'Slu', 'Sl4', 'St3'] },
  U: { from: '#D9C27A', to: '#A8893A', order: ['Uu', 'Us', 'Uls', 'Ut2', 'Ut3', 'Ut4'] },
  L: { from: '#C98A4A', to: '#8A5A2B', order: ['Ls2', 'Ls3', 'Ls4', 'Lu', 'Lt2', 'Lts', 'Lt3'] },
  T: { from: '#6F4520', to: '#3E2412', order: ['Ts4', 'Ts3', 'Uts', 'Tu4', 'Ts2', 'Tu3', 'Tl', 'Tu2', 'Tt'] },
};
const KA5_GROUP_NAME = { S: 'Sands', U: 'Silts', L: 'Loams', T: 'Clays' };
export const KA5_NAMES = {
  Ss: 'Pure sand', gS: 'Coarse sand', mS: 'Medium sand', fS: 'Fine sand', mSgs: 'Medium sand, coarse-sandy',
  mSfs: 'Medium sand, fine-sandy', fSms: 'Fine sand, medium-sandy', fSgs: 'Fine sand, coarse-sandy',
  Su2: 'Slightly silty sand', Su3: 'Moderately silty sand', Su4: 'Strongly silty sand', Sl2: 'Slightly loamy sand',
  Sl3: 'Moderately loamy sand', Sl4: 'Strongly loamy sand', Slu: 'Silty loamy sand', St2: 'Slightly clayey sand',
  St3: 'Moderately clayey sand', Uu: 'Pure silt', Us: 'Sandy silt', Uls: 'Sandy loamy silt', Ut2: 'Slightly clayey silt',
  Ut3: 'Moderately clayey silt', Ut4: 'Strongly clayey silt', Ls2: 'Slightly sandy loam', Ls3: 'Moderately sandy loam',
  Ls4: 'Strongly sandy loam', Lu: 'Silty loam', Lt2: 'Slightly clayey loam', Lt3: 'Moderately clayey loam',
  Lts: 'Sandy clayey loam', Tt: 'Pure clay', Tl: 'Loamy clay', Tu2: 'Slightly silty clay', Tu3: 'Moderately silty clay',
  Tu4: 'Strongly silty clay', Ts2: 'Slightly sandy clay', Ts3: 'Moderately sandy clay', Ts4: 'Strongly sandy clay',
  Uts: 'Clayey silt (sandy)',
};

function hash01(s) {
  let h = 2166136261;
  for (const ch of s) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 1000) / 999;
}

function mixHex(a, b, t) {
  const A = parseColor(a), B = parseColor(b);
  return [0, 1, 2].map((k) => A[k] + (B[k] - A[k]) * t).concat(1);
}

export function ka5Group(cls) {
  const m = String(cls).match(/[SULT]/);
  return m ? m[0] : null;
}

const ka5Cache = new Map();
export function ka5Color(cls) {
  if (ka5Cache.has(cls)) return ka5Cache.get(cls);
  const g = ka5Group(cls);
  let c;
  if (!g || /^H|^Mo/.test(cls)) c = parseColor('#2B2B2B');
  else {
    const grp = KA5_GROUPS[g];
    const i = grp.order.indexOf(cls);
    const t = i >= 0 ? i / (grp.order.length - 1) : hash01(cls);
    c = mixHex(grp.from, grp.to, t);
  }
  ka5Cache.set(cls, c);
  return c;
}

export function bsColor(cls) {
  return BS_COLORS[cls] ? parseColor(BS_COLORS[cls]) : mixHex('#B9A27A', '#5A4630', hash01(String(cls)));
}

export const toCss = (c) => c ? `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${c[3].toFixed(3)})` : 'transparent';

// ---------- API pública ----------
const built = new Map();
/** Paleta por clave: {kind:'num'|'cat', color(v)->[r,g,b,a]|null, ...} */
export function palette(key) {
  if (built.has(key)) return built.get(key);
  let p;
  if (key === 'bs') {
    p = { kind: 'cat', key, color: (v) => v == null ? null : bsColor(v), title: 'German soil assessment classes',
      name: (v) => BS_NAMES[v] || v, sort: (a, b) => (BS_ORDER.indexOf(a) + 99 * (BS_ORDER.indexOf(a) < 0)) - (BS_ORDER.indexOf(b) + 99 * (BS_ORDER.indexOf(b) < 0)) };
  } else if (key === 'ka5') {
    const rank = (c) => { const g = ka5Group(c); const gi = 'SULT'.indexOf(g); const o = g ? KA5_GROUPS[g].order.indexOf(c) : 99; return (gi < 0 ? 9 : gi) * 100 + (o < 0 ? 50 : o); };
    p = { kind: 'cat', key, color: (v) => v == null ? null : ka5Color(v), title: 'KA5 texture classes',
      name: (v) => KA5_NAMES[v] || `${KA5_GROUP_NAME[ka5Group(v)] || 'Other'} (${v})`, sort: (a, b) => rank(a) - rank(b) };
  } else if (key === 'reliability') {
    p = { kind: 'num', key, ...RELIABILITY, color: makeScale(RELIABILITY.stops) };
  } else {
    const d = NUMERIC[key];
    if (!d) throw new Error(`Unknown palette ${key}`);
    p = { kind: 'num', key, ...d, color: makeScale(d.stops) };
  }
  built.set(key, p);
  return p;
}

/** CSS linear-gradient de una paleta numérica (para leyendas). */
export function gradientCss(p, dir = 'to right') {
  const span = p.max - p.min;
  const parts = p.stops.map(([v, c]) => `${toCss(parseColor(c))} ${((v - p.min) / span * 100).toFixed(1)}%`);
  return `linear-gradient(${dir}, ${parts.join(', ')})`;
}

/** Patrón rayado diagonal para "sin dato dentro del campo". */
let hatchTile = null;
export function hatchPattern(ctx) {
  if (!hatchTile) {
    hatchTile = document.createElement('canvas');
    hatchTile.width = hatchTile.height = 10;
    const h = hatchTile.getContext('2d');
    h.strokeStyle = 'rgba(255,255,255,0.18)';
    h.lineWidth = 1.5;
    h.beginPath();
    h.moveTo(-2, 12); h.lineTo(12, -2);
    h.moveTo(-2, 2); h.lineTo(2, -2);
    h.moveTo(8, 12); h.lineTo(12, 8);
    h.stroke();
  }
  return ctx.createPattern(hatchTile, 'repeat');
}
