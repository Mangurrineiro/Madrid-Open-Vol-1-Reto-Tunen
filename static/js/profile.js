// Perfil altimétrico (módulo de terreno): dos clics dentro del campo → gráfico SVG bajo el mapa con
// la elevación cada 10 m sobre el grid "elevation" y, si existe, la Bodenzahl a lo largo de la misma línea.
/* global L */
import { api } from './api.js';
import { findLayer } from './catalog.js';
import { escapeHtml, getMap } from './map2d.js';
import { palette, toCss } from './palettes.js';
import { cellValue, pointInRings, ringsOf } from './renderer.js';

const STEP_M = 10;
const NS = 'http://www.w3.org/2000/svg';

let st = null;        // {field, mode:'pick'|'shown', pts:[latlng], layer:L.LayerGroup, hover:L.CircleMarker, el}

export const isPicking = () => st?.mode === 'pick';
export const isOpen = () => !!st;

/** Hay grid de elevación para este campo (el botón solo aparece entonces). */
export const canProfile = (field) => !!field && !!findLayer(field, 'copernicus_dem', 'elevation');

export function start(field) {
  close();
  const map = getMap();
  st = { field, mode: 'pick', pts: [], layer: L.layerGroup().addTo(map), hover: null, el: panel() };
  map.getContainer().classList.add('profile-picking');
  // El panel del perfil ocupa la parte baja del mapa: encuadrar el campo por encima
  const pw = document.querySelector('#panel')?.offsetWidth || 360;
  map.flyToBounds(field.bounds, { paddingTopLeft: [60, 140], paddingBottomRight: [pw + 80, 300], duration: 0.6 });
  hint('Click two points inside the field to draw the elevation profile');
}

export function close() {
  if (!st) return;
  st.layer.remove();
  st.el.remove();
  getMap().getContainer().classList.remove('profile-picking');
  st = null;
  document.querySelectorAll('[data-action="profile"]').forEach((b) => b.classList.remove('on'));
}

/** Clic en el mapa en modo selección. Devuelve true si lo ha consumido. */
export function addPoint(latlng) {
  if (!isPicking()) return false;
  if (!pointInRings(latlng.lng, latlng.lat, ringsOf(st.field.geometry))) {
    hint('That point is outside the field — click inside the field boundary', true);
    return true;
  }
  st.pts.push(latlng);
  const label = st.pts.length === 1 ? 'A' : 'B';
  L.marker(latlng, { pane: 'samplesPane', interactive: false,
    icon: L.divIcon({ className: 'profile-pin', html: `<span>${label}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] }) })
    .addTo(st.layer);
  if (st.pts.length === 1) { hint('Now click the end point (B)'); return true; }
  L.polyline(st.pts, { pane: 'samplesPane', color: '#fff', weight: 2.5, dashArray: '6 5', interactive: false }).addTo(st.layer);
  st.mode = 'shown';
  getMap().getContainer().classList.remove('profile-picking');
  draw();
  return true;
}

// ---------- panel inferior ----------
function panel() {
  const el = document.createElement('section');
  el.id = 'profile-panel';
  el.className = 'glass';
  el.innerHTML = '<div class="pf-head"><b>Elevation profile</b><span class="pf-sub"></span><button class="pf-close" title="Close (Esc)">×</button></div><div class="pf-body"></div>';
  el.querySelector('.pf-close').addEventListener('click', close);
  document.body.appendChild(el);
  return el;
}

function hint(text, warn = false) {
  st.el.querySelector('.pf-body').innerHTML = `<div class="pf-hint ${warn ? 'warn' : ''}">${escapeHtml(text)}</div>`;
}

/** Muestras cada 10 m de A a B: {d (m), lat, lon}. */
function samples(a, b) {
  const k = Math.cos((a.lat + b.lat) / 2 * Math.PI / 180);
  const dx = (b.lng - a.lng) * 111320 * k, dy = (b.lat - a.lat) * 110574;
  const D = Math.hypot(dx, dy);
  const n = Math.max(1, Math.floor(D / STEP_M));
  const out = [];
  for (let i = 0; i <= n; i++) {
    const d = Math.min(D, i * STEP_M);
    out.push({ d, lat: a.lat + (b.lat - a.lat) * d / D, lon: a.lng + (b.lng - a.lng) * d / D });
  }
  if (out[out.length - 1].d < D) out.push({ d: D, lat: b.lat, lon: b.lng });
  return { pts: out, D };
}

async function gridOf(field, source, parameter) {
  const m = findLayer(field, source, parameter);
  try { return m ? await api.grid(m.grid_url) : null; } catch { return null; }
}

async function draw() {
  const s = st;
  const [a, b] = s.pts;
  s.el.querySelector('.pf-body').innerHTML = '<div class="pf-hint">Sampling…</div>';
  const [elev, bz] = await Promise.all([gridOf(s.field, 'copernicus_dem', 'elevation'), gridOf(s.field, 'lbeg', 'bodenzahl')]);
  if (st !== s) return;
  const { pts, D } = samples(a, b);
  const rings = ringsOf(s.field.geometry);
  for (const p of pts) {
    p.out = !pointInRings(p.lon, p.lat, rings);
    p.z = p.out ? null : cellValue(elev, p.lat, p.lon);
    p.bz = p.out ? null : cellValue(bz, p.lat, p.lon);
  }
  const zs = pts.map((p) => p.z).filter((v) => v != null);
  if (!zs.length) { hint('No elevation data along this line', true); return; }
  const hasBz = pts.some((p) => p.bz != null);
  const zmin = Math.min(...zs), zmax = Math.max(...zs);
  s.el.querySelector('.pf-sub').textContent = `A → B · ${Math.round(D)} m · ${(zmax - zmin).toFixed(1)} m of relief`
    + ` · lowest ${Math.round(zmin)} m, highest ${Math.round(zmax)} m`;
  s.el.classList.toggle('with-bz', hasBz);
  chart(s, pts, D, hasBz);
}

function niceStep(span, n) {
  const raw = span / n;
  const p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((x) => x >= raw) || raw;
}

function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

/** Trazos de una serie con huecos (null) como varios subpaths. */
function pathOf(pts, key, x, y) {
  let d = '', pen = false;
  for (const p of pts) {
    if (p[key] == null) { pen = false; continue; }
    d += `${pen ? 'L' : 'M'}${x(p.d).toFixed(1)} ${y(p[key]).toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** Tramos contiguos con dato (la línea puede salir del campo si es cóncavo). */
function runs(pts, key) {
  const out = [];
  let cur = [];
  for (const p of pts) {
    if (p[key] == null) { if (cur.length) out.push(cur); cur = []; } else cur.push(p);
  }
  if (cur.length) out.push(cur);
  return out;
}

function chart(s, pts, D, hasBz) {
  const body = s.el.querySelector('.pf-body');
  body.innerHTML = '';
  const W = Math.max(320, body.clientWidth);
  const ML = 46, MR = 14, H1 = 120, GAP = 26, H2 = hasBz ? 54 : 0, MB = 22;
  const H = 8 + H1 + (hasBz ? GAP + H2 : 0) + MB;
  const svg = el('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'pf-svg' }, body);
  const x = (d) => ML + (W - ML - MR) * d / (D || 1);

  // --- elevación ---
  const zs = pts.map((p) => p.z).filter((v) => v != null);
  let lo = Math.min(...zs), hi = Math.max(...zs);
  if (hi - lo < 2) { const c = (hi + lo) / 2; lo = c - 1; hi = c + 1; }
  const pad = (hi - lo) * 0.12;
  lo -= pad; hi += pad;
  const top1 = 8;
  const y = (z) => top1 + H1 * (1 - (z - lo) / (hi - lo));
  const defs = el('defs', {}, svg);
  const grad = el('linearGradient', { id: 'pf-grad', x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
  el('stop', { offset: '0%', 'stop-color': '#C99A4E', 'stop-opacity': 0.55 }, grad);
  el('stop', { offset: '100%', 'stop-color': '#1B5E20', 'stop-opacity': 0.08 }, grad);
  const ystep = niceStep(hi - lo, 3);
  for (let t = Math.ceil(lo / ystep) * ystep; t <= hi; t += ystep) {
    el('line', { x1: ML, x2: W - MR, y1: y(t), y2: y(t), class: 'pf-grid' }, svg);
    el('text', { x: ML - 6, y: y(t) + 3.5, class: 'pf-tick', 'text-anchor': 'end' }, svg).textContent = `${+t.toFixed(1)} m`;
  }
  const line = pathOf(pts, 'z', x, y);
  const area = runs(pts, 'z').map((run) => {
    const x0 = x(run[0].d).toFixed(1), x1 = x(run[run.length - 1].d).toFixed(1);
    return `M${x0} ${top1 + H1}${run.map((p) => `L${x(p.d).toFixed(1)} ${y(p.z).toFixed(1)}`).join('')}L${x1} ${top1 + H1}Z`;
  }).join('');
  el('path', { d: area, fill: 'url(#pf-grad)' }, svg);
  el('path', { d: line, class: 'pf-line' }, svg);

  // --- Bodenzahl (segunda serie) ---
  let yb = null;
  if (hasBz) {
    const top2 = top1 + H1 + GAP;
    const bs = pts.map((p) => p.bz).filter((v) => v != null);
    let blo = Math.min(...bs), bhi = Math.max(...bs);
    if (bhi - blo < 10) { const c = (bhi + blo) / 2; blo = Math.max(0, c - 5); bhi = Math.min(100, blo + 10); }
    yb = (v) => top2 + H2 * (1 - (v - blo) / (bhi - blo || 1));
    el('text', { x: ML, y: top2 - 8, class: 'pf-label' }, svg).textContent = 'Bodenzahl along the line';
    for (const t of [blo, bhi]) {
      el('line', { x1: ML, x2: W - MR, y1: yb(t), y2: yb(t), class: 'pf-grid' }, svg);
      el('text', { x: ML - 6, y: yb(t) + 3.5, class: 'pf-tick', 'text-anchor': 'end' }, svg).textContent = String(Math.round(t));
    }
    const q = palette('quality');
    for (let i = 1; i < pts.length; i++) {
      const p0 = pts[i - 1], p1 = pts[i];
      if (p0.bz == null || p1.bz == null) continue;
      el('line', { x1: x(p0.d), x2: x(p1.d), y1: yb(p0.bz), y2: yb(p1.bz), stroke: toCss(q.color((p0.bz + p1.bz) / 2)),
        'stroke-width': 3, 'stroke-linecap': 'round' }, svg);
    }
  }

  // --- eje de distancia ---
  const xstep = niceStep(D, 6);
  const base = H - MB;
  for (let d = 0; d <= D + 1e-6; d += xstep) {
    el('text', { x: x(d), y: base + 15, class: 'pf-tick', 'text-anchor': 'middle' }, svg).textContent = `${Math.round(d)} m`;
  }
  el('text', { x: ML, y: top1 + 10, class: 'pf-ab' }, svg).textContent = 'A';
  el('text', { x: W - MR, y: top1 + 10, class: 'pf-ab', 'text-anchor': 'end' }, svg).textContent = 'B';

  // --- lectura al pasar el ratón: guía + marcador en el mapa ---
  const guide = el('line', { y1: top1, y2: base, class: 'pf-guide', visibility: 'hidden' }, svg);
  const dot = el('circle', { r: 4, class: 'pf-dot', visibility: 'hidden' }, svg);
  const read = el('text', { y: top1 + 12, class: 'pf-read', visibility: 'hidden' }, svg);
  svg.addEventListener('mousemove', (ev) => {
    const r = svg.getBoundingClientRect();
    const d = Math.max(0, Math.min(D, (ev.clientX - r.left - ML) / (W - ML - MR) * D));
    const p = pts.reduce((a, b) => (Math.abs(b.d - d) < Math.abs(a.d - d) ? b : a));
    const px = x(p.d);
    guide.setAttribute('x1', px); guide.setAttribute('x2', px); guide.setAttribute('visibility', 'visible');
    if (p.z != null) { dot.setAttribute('cx', px); dot.setAttribute('cy', y(p.z)); dot.setAttribute('visibility', 'visible'); } else dot.setAttribute('visibility', 'hidden');
    const right = px > W * 0.7;
    read.setAttribute('x', right ? px - 8 : px + 8);
    read.setAttribute('text-anchor', right ? 'end' : 'start');
    read.textContent = `${Math.round(p.d)} m · ${p.z != null ? `${p.z.toFixed(1)} m` : p.out ? 'outside the field' : 'no data'}${p.bz != null ? ` · Bodenzahl ${Math.round(p.bz)}` : ''}`;
    read.setAttribute('visibility', 'visible');
    if (!s.hover) s.hover = L.circleMarker([p.lat, p.lon], { pane: 'samplesPane', radius: 6, color: '#fff', weight: 2, fillColor: '#C99A4E', fillOpacity: 1, interactive: false }).addTo(s.layer);
    else s.hover.setLatLng([p.lat, p.lon]);
  });
  svg.addEventListener('mouseleave', () => {
    for (const e of [guide, dot, read]) e.setAttribute('visibility', 'hidden');
    if (s.hover) { s.hover.remove(); s.hover = null; }
  });
}
