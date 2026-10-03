// Fase 2 · Pila isométrica de las 6 capas del campo (CSS 3D, sin WebGL).
// Se carga con import() dinámico: si falla, la Fase 1 sigue funcionando sin el botón.
import { api } from './api.js';
import { LAYERS, findLayer } from './catalog.js';
import { escapeHtml } from './map2d.js';
import { palette } from './palettes.js';
import { emptyGrid, renderLayer, ringsOf } from './renderer.js';

const GAP = 70;                 // separación entre láminas (translateZ)
const RX = 58;
const RZ = -38;
const FLAT_SCALE = 1.22;
let view = null;                // estado de la vista abierta

ensureCss();

function ensureCss() {
  if (document.querySelector('link[data-phase2]')) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = '/static/css/phase2.css';
  l.dataset.phase2 = '1';
  document.head.appendChild(l);
}

export const isOpen = () => !!view;

/** Capa por defecto para la pila: primera fuente con dato en el campo. */
function resolveFor(field, layer) {
  const sub = layer.subs ? layer.subs[0].id : null;
  const order = [layer.defaultSource(sub), ...layer.sources(sub)];
  for (const src of order) {
    const r = layer.resolve(field, sub, src);
    const meta = findLayer(field, r.source, r.parameter);
    if (meta) return { ...r, meta, sub };
  }
  return { ...layer.resolve(field, sub, layer.defaultSource(sub)), meta: null, sub };
}

function meanText(field, layer, r) {
  if (!r.meta) return null;
  const st = r.meta.stats || {};
  if (layer.id === 'texture') {
    const cats = st.categories ? Object.keys(st.categories) : [];
    const p = palette(r.palette);
    return cats.length ? `${cats[0]} · ${p.name(cats[0])}` : null;
  }
  if (st.mean == null) return null;
  if (layer.id === 'reliability') return `${Math.round(100 * (1 - st.mean))} / 100`;
  if (layer.id === 'bodenzahl') return `${Math.round(st.mean)}`;
  if (layer.id === 'ph') return `${st.mean.toFixed(1)} ${layer.label(r.sub, r.source).replace(/^pH /, '')}`;
  return `${st.mean.toFixed(1)} ${layer.unit(r.sub, r.source)}`;
}

function noDataText(field, layer, r) {
  if (r.source === 'lbeg' || layer.id === 'bodenzahl') {
    return field.state === 'Lower Saxony' ? 'LBEG did not answer for this field' : 'No official data outside Lower Saxony';
  }
  return 'No data for this field';
}

async function buildSheets(field) {
  return Promise.all(LAYERS.map(async (layer) => {
    const r = resolveFor(field, layer);
    let grid = null;
    try { grid = r.meta ? await api.grid(r.meta.grid_url) : null; } catch { grid = null; }
    const out = renderLayer(grid || emptyGrid(field.bounds), palette(r.palette), field.geometry, {
      smooth: true, cacheKey: `${field.field_id}|${layer.id}|${r.source}|${r.parameter}|data`,
    });
    return { layer, r, out, hasData: !!grid && out.hasData, mean: meanText(field, layer, r) };
  }));
}

function copyCanvas(src) {
  const c = document.createElement('canvas');
  c.width = src.width; c.height = src.height;
  c.getContext('2d').drawImage(src, 0, 0);
  return c;
}

/** Lámina base: satélite del campo recortado con su silueta (o plano oscuro si no carga). */
function baseCanvas(field, w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const ctx = c.getContext('2d');
  const [[s, west], [n, e]] = field.bounds;
  const path = new Path2D();
  for (const ring of ringsOf(field.geometry)) {
    ring.forEach(([lon, lat], i) => {
      const x = (lon - west) / (e - west) * w, y = (n - lat) / (n - s) * h;
      i ? path.lineTo(x, y) : path.moveTo(x, y);
    });
    path.closePath();
  }
  const paint = (img) => {
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.clip(path, 'evenodd');
    ctx.fillStyle = '#1B2420';
    ctx.fillRect(0, 0, w, h);
    if (img) ctx.drawImage(img, 0, 0, w, h);
    ctx.restore();
    ctx.lineWidth = 2;
    ctx.strokeStyle = 'rgba(255,255,255,0.7)';
    ctx.stroke(path);
  };
  paint(null);
  const img = new Image();
  const size = `${Math.min(1024, w * 2)},${Math.min(1024, h * 2)}`;
  img.onload = () => paint(img);
  img.onerror = () => { /* plano oscuro con contorno */ };
  img.src = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export'
    + `?bbox=${west},${s},${e},${n}&bboxSR=4326&imageSR=4326&size=${size}&format=jpg&f=image`;
  return c;
}

/**
 * Abre la pila. ctx: {panel, onEnterLayer(layerId), onMapView(), onBackToFarm()}
 * opts.fromLayer: viene de la vista 2D de esa capa → animación inversa (de cenital a pila).
 */
export async function open(field, ctx, opts = {}) {
  close(true);
  const host = document.createElement('section');
  host.id = 'stack-view';
  host.innerHTML = `<div class="stack-bg"></div><div class="stack-stage-wrap"><div class="stack-stage"></div></div>
    <svg class="stack-lines"></svg><div class="stack-labels"></div>
    <div class="stack-hint">Drag to rotate · click a layer to open it</div>`;
  document.body.appendChild(host);
  view = { field, ctx, host, rz: RZ, sheets: [], busy: false, anchorPts: anchorPoints(field) };
  renderPanel(field, ctx, null);

  const sheets = await buildSheets(field);
  if (!view || view.host !== host) return;
  view.data = sheets;
  renderPanel(field, ctx, sheets);

  // Tamaño de lámina según el hueco disponible y la forma del campo
  const ratio = sheets[0].out.canvas.width / sheets[0].out.canvas.height;
  const availW = window.innerWidth - (ctx.panel.offsetWidth || 360) - 120;
  const availH = window.innerHeight;
  const maxW = Math.min(availW * 0.62, availH * 0.78, 620);
  let w = maxW, h = maxW / ratio;
  if (h > maxW * 1.05) { h = maxW * 1.05; w = h * ratio; }

  const stage = host.querySelector('.stage, .stack-stage');
  const base = makeSheet(baseCanvas(field, Math.round(w), Math.round(h)), w, h, -1, 'base');
  stage.appendChild(base);
  sheets.forEach((s, i) => {
    const el = makeSheet(copyCanvas(s.out.canvas), w, h, i, s.layer.id);
    if (!s.hasData) el.classList.add('nodata');
    el.addEventListener('mouseenter', () => hover(i));
    el.addEventListener('mouseleave', () => hover(null));
    el.addEventListener('click', () => { if (!view.dragged) enterLayer(s.layer.id); });
    stage.appendChild(el);
    view.sheets.push(el);
  });
  view.base = base;
  buildLabels(sheets);
  setupDrag(host);
  view.onResize = () => placeLabels();
  window.addEventListener('resize', view.onResize);

  const from = opts.fromLayer ? LAYERS.findIndex((l) => l.id === opts.fromLayer) : -1;
  if (from >= 0) {
    // Estado cenital: la lámina elegida plana y centrada, el resto invisibles
    host.classList.add('flat', 'instant');
    setStage(0, 0);
    view.sheets.forEach((el, i) => { el.classList.add('in'); setSheet(el, i, i === from ? 'flat' : 'hidden'); });
    setSheet(base, -1, 'hidden');
    host.getBoundingClientRect();
    host.classList.remove('instant');
    requestAnimationFrame(() => requestAnimationFrame(() => {
      host.classList.add('on');
      setTimeout(() => {
        host.classList.remove('flat');
        setStage(RX, view.rz);
        view.sheets.forEach((el, i) => setSheet(el, i, 'stack'));
        setSheet(base, -1, 'stack');
        setTimeout(() => host.classList.add('ready'), 650);
      }, 120);
    }));
  } else {
    setStage(RX, view.rz);
    setSheet(base, -1, 'stack');
    view.sheets.forEach((el, i) => setSheet(el, i, 'stack'));
    requestAnimationFrame(() => {
      host.classList.add('on');
      [base, ...view.sheets].forEach((el, k) => setTimeout(() => el.classList.add('in'), 120 + k * 80));
      setTimeout(() => host.classList.add('ready'), 120 + 7 * 80 + 500);
    });
  }
  const track = () => { if (!view || view.host !== host) return; placeLabels(); requestAnimationFrame(track); };
  requestAnimationFrame(track);
}

function makeSheet(canvas, w, h, i, id) {
  const el = document.createElement('div');
  el.className = `sheet sheet-${id}`;
  el.style.width = `${w}px`;
  el.style.height = `${h}px`;
  el.style.left = `${-w / 2}px`;
  el.style.top = `${-h / 2}px`;
  el.dataset.index = i;
  canvas.className = 'sheet-canvas';
  el.appendChild(canvas);
  for (const [fx, fy] of view.anchorPts) {
    const a = document.createElement('i');
    a.className = 'sheet-anchor';
    a.style.left = `${fx * 100}%`;
    a.style.top = `${fy * 100}%`;
    el.appendChild(a);
  }
  return el;
}

/** Vértices de la silueta (fracciones del lienzo) candidatos a anclar la línea de la etiqueta. */
function anchorPoints(field) {
  const [[s, w], [n, e]] = field.bounds;
  const pts = [];
  for (const ring of ringsOf(field.geometry)) {
    const step = Math.max(1, Math.floor(ring.length / 24));
    for (let i = 0; i < ring.length; i += step) pts.push([(ring[i][0] - w) / (e - w), (n - ring[i][1]) / (n - s)]);
  }
  return pts;
}

/** Punto de anclaje en pantalla: el vértice que queda más a la derecha. */
function anchorOf(sheet) {
  let best = null;
  for (const a of sheet.querySelectorAll('.sheet-anchor')) {
    const r = a.getBoundingClientRect();
    if (!best || r.left > best.x) best = { x: r.left, y: r.top };
  }
  return best;
}

function zOf(i) { return (i + 1) * GAP - 3 * GAP; }

function setSheet(el, i, mode, lift = 0) {
  if (mode === 'flat') { el.style.transform = `translateZ(0px) scale(${FLAT_SCALE})`; el.style.opacity = '1'; return; }
  if (mode === 'hidden') { el.style.transform = `translateZ(${zOf(i)}px)`; el.style.opacity = '0'; return; }
  el.style.transform = `translateZ(${zOf(i) + lift}px)`;
  el.style.opacity = '';
}

function setStage(rx, rz) {
  const st = view.host.querySelector('.stack-stage');
  st.style.transform = `rotateX(${rx}deg) rotateZ(${rz}deg)`;
}

function hover(idx) {
  if (!view || view.busy) return;
  view.hovered = idx;
  view.sheets.forEach((el, i) => {
    setSheet(el, i, 'stack', i === idx ? 20 : 0);
    el.classList.toggle('dim', idx != null && i !== idx);
  });
  view.host.querySelectorAll('.stack-label').forEach((l, i) => {
    l.classList.toggle('dim', idx != null && i !== idx);
    l.classList.toggle('hot', i === idx);
  });
  view.ctx.panel.querySelectorAll('[data-stack]').forEach((b) => b.classList.toggle('hot', idx != null && b.dataset.stack === LAYERS[idx].id));
}

function buildLabels(sheets) {
  const box = view.host.querySelector('.stack-labels');
  box.innerHTML = sheets.map((s) => `
    <button class="stack-label ${s.hasData ? '' : 'nodata'}" data-layer="${s.layer.id}">
      <span class="sl-name">${s.layer.name}</span>
      <span class="sl-value">${s.hasData ? escapeHtml(s.mean ?? '—') : escapeHtml(noDataText(view.field, s.layer, s.r))}</span>
    </button>`).join('');
  box.querySelectorAll('.stack-label').forEach((el, i) => {
    el.addEventListener('mouseenter', () => hover(i));
    el.addEventListener('mouseleave', () => hover(null));
    el.addEventListener('click', () => enterLayer(sheets[i].layer.id));
  });
}

/** Etiquetas 2D a la derecha, unidas con una línea al borde derecho de cada lámina. */
function placeLabels() {
  if (!view?.sheets.length) return;
  const host = view.host;
  const labels = [...host.querySelectorAll('.stack-label')];
  const anchors = view.sheets.map(anchorOf);
  const panelW = view.ctx.panel.offsetWidth || 360;
  const maxX = Math.max(...anchors.map((a) => a.x));
  const x = Math.min(maxX + 70, window.innerWidth - panelW - 250);
  let lines = '';
  let prevY = -Infinity;
  for (let i = labels.length - 1; i >= 0; i--) {            // la lámina de arriba primero
    const a = anchors[i];
    const ay = a.y;
    const y = Math.max(ay, prevY + 48);
    prevY = y;
    const l = labels[i];
    l.style.transform = `translate(${x}px, ${y - l.offsetHeight / 2}px)`;
    const cls = l.classList.contains('hot') ? 'hot' : l.classList.contains('dim') ? 'dim' : '';
    lines += `<line x1="${a.x}" y1="${ay}" x2="${x - 6}" y2="${y}" class="${cls}"/><circle cx="${a.x}" cy="${ay}" r="3" class="${cls}"/>`;
  }
  host.querySelector('.stack-lines').innerHTML = lines;
}

function setupDrag(host) {
  let start = null;
  host.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.stack-label')) return;
    start = { x: e.clientX, rz: view.rz };
    view.dragged = false;
  });
  window.addEventListener('pointermove', view.onMove = (e) => {
    if (!start || !view) return;
    const dx = e.clientX - start.x;
    if (Math.abs(dx) > 4) view.dragged = true;
    view.rz = Math.max(RZ - 25, Math.min(RZ + 25, start.rz + dx * 0.12));
    host.classList.add('dragging');
    setStage(RX, view.rz);
  });
  window.addEventListener('pointerup', view.onUp = () => {
    start = null;
    host.classList.remove('dragging');
    setTimeout(() => { if (view) view.dragged = false; }, 0);
  });
}

/** Lámina → vista cenital (600 ms) → fundido a la vista 2D con esa capa activa. */
export function enterLayer(layerId) {
  if (!view || view.busy) return;
  view.busy = true;
  hover(null);
  const idx = LAYERS.findIndex((l) => l.id === layerId);
  const { host, ctx } = view;
  host.classList.add('flat');
  setStage(0, 0);
  view.sheets.forEach((el, i) => setSheet(el, i, i === idx ? 'flat' : 'hidden'));
  setSheet(view.base, -1, 'hidden');
  setTimeout(() => {
    ctx.onEnterLayer(layerId);
    host.classList.remove('on');
    setTimeout(() => close(true), 380);
  }, 620);
}

export function close(immediate = false) {
  if (!view) return;
  const v = view;
  view = null;
  window.removeEventListener('resize', v.onResize);
  if (v.onMove) window.removeEventListener('pointermove', v.onMove);
  if (v.onUp) window.removeEventListener('pointerup', v.onUp);
  v.ctx.panel.removeEventListener('click', v.onPanelClick);
  if (immediate) v.host.remove();
  else { v.host.classList.remove('on'); setTimeout(() => v.host.remove(), 400); }
}

// ---------- panel en modo "Layer stack" ----------
function renderPanel(field, ctx, sheets) {
  const rows = LAYERS.map((l, i) => {
    const s = sheets?.[i];
    const val = !s ? '<span class="skeleton-inline"></span>'
      : s.hasData ? escapeHtml(s.mean ?? '—') : `<span class="muted">${escapeHtml(noDataText(field, l, s.r))}</span>`;
    return `<button class="stack-row" data-stack="${l.id}">
      <span class="layer-icon">${l.icon}</span>
      <span class="layer-text"><span class="layer-name">${l.name}</span><span class="stack-val num">${val}</span></span>
      <kbd>${i + 1}</kbd></button>`;
  }).reverse().join('');
  ctx.panel.innerHTML = `
    <section class="panel-section field-head">
      <button class="btn-back" data-action="back"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>Back to farm<kbd>B</kbd></button>
      <div class="eyebrow">Layer stack</div>
      <h2 class="field-name">${escapeHtml(field.name)}</h2>
      <div class="field-meta"><span class="num">${field.area_ha.toFixed(1)} ha</span><span>·</span><span>${escapeHtml(field.state || '')}</span></div>
    </section>
    <section class="panel-section">
      <button class="btn-ghost" data-stack-action="map">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/></svg>
        Map view<kbd>M</kbd></button>
    </section>
    <section class="panel-section">
      <h2 class="panel-title">Six layers of this field</h2>
      <div class="stack-list">${rows}</div>
      <p class="note stack-note">Each sheet is one soil layer, clipped to the real field boundary. Click one to open it on the map.</p>
    </section>`;
  if (!view) return;
  ctx.panel.removeEventListener('click', view.onPanelClick);
  view.onPanelClick = (e) => {
    const row = e.target.closest('[data-stack]');
    if (row) { enterLayer(row.dataset.stack); return; }
    if (e.target.closest('[data-stack-action="map"]')) ctx.onMapView();
  };
  ctx.panel.addEventListener('click', view.onPanelClick);
  ctx.panel.querySelectorAll('[data-stack]').forEach((b) => {
    const i = LAYERS.findIndex((l) => l.id === b.dataset.stack);
    b.addEventListener('mouseenter', () => hover(i));
    b.addEventListener('mouseleave', () => hover(null));
  });
}
