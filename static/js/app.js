// Estado y navegación: pantalla inicial → granja → campo (datos / incertidumbre, muestreo, inspector).
/* global L */
import { api } from './api.js';
import { LAYERS, availableSources, findLayer, installAckerDelta, layerById, terrainLayers } from './catalog.js';
import { closeInspector, nearestPoint, openInspector } from './inspector.js';
import {
  clearUncertainty, createMap, escapeHtml, fitBounds, getMap, setFields, setOverlay, setSelected,
  setUncertaintyOverlay, showSampling, showUncertainty, unionBounds,
} from './map2d.js';
import { cardFor, cardHtml, initPanel, renderLegend, renderPanel } from './panel.js';
import { BS_NAMES, KA5_NAMES, bsName, palette, toCss } from './palettes.js';
import { cellValue, clearRenderCache, emptyGrid, pointInRings, renderLayer, ringsOf } from './renderer.js';
import { hideTip, initTooltip, showTip, soilOrigin } from './tooltip.js';
import { farmScale, resetScales, summarize, uncertaintyGrid, uncertaintyText } from './uncertainty.js';
import { initDropzone, setZoneMessage, startLoading, validateGeojson } from './upload.js';
import { ackerLine, hasTerrain, resetRelief, setRelief, terrainTip } from './terrain.js';
import * as profile from './profile.js';

const $ = (s) => document.querySelector(s);
const DROP_HINT = 'Field boundaries as Polygon or MultiPolygon · .geojson or .json';

const state = {
  view: 'landing',         // landing | farm | field
  data: null,
  name: '',
  fields: [],
  byId: new Map(),
  featured: [],
  layerId: 'texture',
  sub: { texture: 'classes' },
  source: {},              // "layerId|sub" → fuente elegida
  selected: null,
  uncertainty: false,
  sampling: false,
  renders: new Map(),      // field_id → resultado del renderizador (capa activa)
  grids: new Map(),        // field_id → grid de la capa activa
  unc: null,               // {render, available, summary, scale} del campo seleccionado
  card: null,
  extras: null,            // grids auxiliares del campo seleccionado (tooltip)
  points: null,            // puntos del campo seleccionado (inspector)
  renderToken: 0,
  idle: true,              // false mientras se cargan grids (lo usan los tests)
  terrain: [],             // capas de terreno disponibles (vacío sin el módulo de terreno)
  relief: false,           // "Relief shading"
};
window.__app = { state };

// ---------- Vistas 3D (opcionales): si un módulo falla, el mapa sigue y sus botones no aparecen ----------
const views3d = {};
async function loadViews3d() {
  try { views3d.stack = await import('./stack3d.js'); } catch (err) { console.warn('stack3d.js no disponible', err); }
  try { views3d.texture = await import('./texture3.js'); } catch (err) { console.warn('texture3.js no disponible', err); }
}
const stackOpen = () => !!views3d.stack?.isOpen();
const breakdownOpen = () => !!views3d.texture?.isOpen();
const stackCtx = () => ({
  panel: $('#panel'),
  onEnterLayer: (id) => { state.layerId = id; refresh(); },
  onMapView: () => { views3d.stack.close(); refresh(); },
});
const textureCtx = () => ({ panel: $('#panel'), fields: state.fields, onClose: () => refresh() });
function openStack(fromLayer) {
  if (!views3d.stack || state.view !== 'field') return;
  if (breakdownOpen()) views3d.texture.close(true);
  closeInspector();
  profile.close();
  hideTip();
  views3d.stack.open(state.byId.get(state.selected), stackCtx(), { fromLayer });
}
function toggleBreakdown() {
  if (!views3d.texture || state.view !== 'field') return;
  if (breakdownOpen()) { views3d.texture.close(); return; }
  closeInspector();
  hideTip();
  views3d.texture.open(state.byId.get(state.selected), textureCtx());
  renderPanel(panelView());
  if (state.card) { setCard(cardHtml(state.card)); if (state.lastLegend) renderLegend(state.lastLegend); }
}

// ---------- arranque ----------
function init() {
  window.__app.map = createMap($('#map'));
  initTooltip();
  api.farmOutline().then((fc) => {
    const pts = [];
    for (const f of fc.features) {
      if (f.properties?.isArchived) continue;
      for (const r of ringsOf(f.geometry)) for (const [lon, lat] of r) pts.push([lat, lon]);
    }
    if (pts.length && state.view === 'landing') getMap().fitBounds(L.latLngBounds(pts), { padding: [20, 20] });
  }).catch(() => { /* fondo genérico */ });

  $('#try-demo').addEventListener('click', loadDemo);
  $('#new-file').addEventListener('click', backToLanding);
  initDropzone($('#dropzone'), $('#file-input'), loadFile);
  initPanel($('#panel'), {
    layer: (id) => setLayer(id),
    sub: (id) => { state.sub[state.layerId] = id; refresh(); },
    source: (s) => { state.source[sourceKey()] = s; refresh(); },
    featured: (id) => enterField(id),
    back: () => backToFarm(),
    uncertainty: () => toggleUncertainty(),
    sampling: () => toggleSampling(),
    stack: () => openStack(state.layerId),
    breakdown: () => toggleBreakdown(),
    relief: () => toggleRelief(),
    profile: () => toggleProfile(),
  });
  loadViews3d();
  getMap().on('mousemove', onMouseMove);
  getMap().on('mouseout', hideTip);
  getMap().on('click', (e) => {
    if (profile.addPoint(e.latlng)) return;                 // perfil: clic fuera del campo → aviso
    if (state.view === 'field') closeInspector();
  });
  document.addEventListener('keydown', onKey);
}

function onKey(e) {
  if (state.view === 'landing' || e.target.closest('input, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  const n = Number(e.key);
  if (stackOpen()) {
    if (n >= 1 && n <= LAYERS.length) views3d.stack.enterLayer(LAYERS[n - 1].id);
    else if (k === 'm') stackCtx().onMapView();
    else if (k === 'b' || k === 'escape') backToFarm();
    return;
  }
  if (breakdownOpen() && (k === 'b' || k === 'escape')) { views3d.texture.close(); return; }
  if (k === 'escape' && profile.isOpen()) { profile.close(); return; }
  if (k === 'p' && state.view === 'field') { toggleProfile(); return; }
  if (n >= 1 && n <= LAYERS.length) setLayer(LAYERS[n - 1].id);
  else if (n > LAYERS.length && n <= LAYERS.length + state.terrain.length) setLayer(state.terrain[n - LAYERS.length - 1].id);
  else if (k === 'r' && state.terrain.length) toggleRelief();
  else if (k === 'u') toggleUncertainty();
  else if (k === 's') toggleSampling();
  else if ((k === 'b' || k === 'escape') && state.view === 'field') backToFarm();
}

// ---------- entrada de datos ----------
async function loadDemo() {
  const btn = $('#try-demo');
  btn.classList.add('loading');
  btn.disabled = true;
  try {
    const data = await api.demo();
    await enterFarm(data, data.name || 'Example farm');
  } catch (err) {
    setZoneMessage($('#dropzone'), `Could not load the example farm: ${err.message}`, 'error');
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
}

async function loadFile(file) {
  const zone = $('#dropzone');
  let text;
  try { text = await file.text(); } catch { setZoneMessage(zone, 'This file could not be read.', 'error'); return; }
  const v = validateGeojson(text);
  if (!v.ok) { setZoneMessage(zone, v.error, 'error'); return; }
  setZoneMessage(zone, v.warning || `${v.fc.features.length} field boundaries found`, v.warning ? 'warning' : '');
  const name = file.name.replace(/\.(geo)?json$/i, '');
  const n = v.fc.features.length;
  const loading = startLoading($('#loading'), {
    title: `${name} · ${n} field${n === 1 ? '' : 's'}`,
    warning: v.warning,
    onBack: () => setZoneMessage(zone, DROP_HINT),
  });
  try {
    const data = await api.layers(v.fc);
    if (!data.fields?.length) throw new Error('the server found no usable field boundaries in this file');
    loading.done();
    await enterFarm(data, name);
  } catch (err) {
    loading.fail(err.message);
  }
}

function backToLanding() {
  if (stackOpen()) views3d.stack.close(true);
  if (breakdownOpen()) views3d.texture.close(true);
  closeInspector();
  hideTip();
  clearUncertainty();
  setSelected(null);
  state.sampling = false;
  showSampling([]);
  Object.assign(state, { view: 'landing', selected: null, uncertainty: false, relief: false });
  resetRelief();
  profile.close();
  document.body.classList.remove('farm', 'field-mode', 'unc-mode', 'relief-on');
  const l = $('#landing');
  l.style.removeProperty('display');
  requestAnimationFrame(() => l.classList.remove('hidden'));
  setZoneMessage($('#dropzone'), DROP_HINT);
}

// ---------- vista de granja ----------
async function enterFarm(data, name) {
  if (!data.fields?.length) throw new Error('no field boundaries found');
  clearRenderCache();
  resetScales();
  Object.assign(state, {
    data, name, fields: data.fields, byId: new Map(data.fields.map((f) => [f.field_id, f])),
    featured: data.featured?.length ? data.featured : featuredFallback(data.fields),
    selected: null, uncertainty: false, sampling: false, unc: null, card: null, extras: null, points: null,
  });
  profile.close();
  installAckerDelta(state.fields);
  state.terrain = terrainLayers(state.fields);
  if (layerById(state.layerId)?.terrain && !state.terrain.includes(layerById(state.layerId))) state.layerId = 'texture';
  resetRelief();
  applyRelief();
  state.renders.clear();
  state.grids.clear();
  showSampling([]);
  renderHeader();
  setFields(state.fields, { onClick: onFieldClick });
  state.view = 'farm';
  document.body.classList.add('farm');
  document.body.classList.remove('field-mode', 'unc-mode');
  $('#landing').classList.add('hidden');
  setTimeout(() => { if (state.view !== 'landing') $('#landing').style.setProperty('display', 'none'); }, 500);
  fitBounds(unionBounds(state.fields), { duration: 1.4 });
  await refresh();
}

function renderHeader() {
  const states = new Set(state.fields.map((f) => f.state).filter(Boolean));
  const sources = new Set(state.fields.flatMap((f) => f.sources || []));
  const n = state.fields.length;
  $('#farm-name').textContent = state.name;
  $('#farm-chips').innerHTML = [
    `${n} field${n === 1 ? '' : 's'}`,
    `${states.size} federal state${states.size === 1 ? '' : 's'}`,
    `${sources.size} data source${sources.size === 1 ? '' : 's'}`,
  ].map((t) => `<span class="chip">${t}</span>`).join('');
}

function featuredFallback(fields) {
  return [...fields].filter((f) => f.reliability_index != null)
    .sort((a, b) => a.reliability_index - b.reliability_index).slice(0, 5)
    .map((f) => ({ field_id: f.field_id, name: f.name, state: f.state, reliability_index: f.reliability_index,
      reason: `Reliability index ${f.reliability_index}: sources disagree` }));
}

function backToFarm() {
  if (state.view !== 'field') return;
  if (stackOpen()) views3d.stack.close();
  if (breakdownOpen()) views3d.texture.close(true);
  closeInspector();
  hideTip();
  clearUncertainty();
  profile.close();
  Object.assign(state, { view: 'farm', selected: null, uncertainty: false, unc: null, card: null, extras: null, points: null });
  setSelected(null);
  document.body.classList.remove('field-mode', 'unc-mode');
  applyRelief();
  fitBounds(unionBounds(state.fields), { duration: 0.9 });
  updateSampling();
  refresh();
}

// ---------- vista de campo ----------
function onFieldClick(f, latlng) {
  if (state.view === 'field' && profile.addPoint(latlng)) return;
  if (state.view === 'field' && state.selected === f.field_id) openInspectorAt(latlng);
  else enterField(f.field_id);
}

async function enterField(id) {
  const f = state.byId.get(id);
  if (!f) return;
  closeInspector();
  clearUncertainty();
  if (profile.isOpen() && state.selected !== id) profile.close();
  Object.assign(state, { view: 'field', selected: id, unc: null, card: null, extras: null, points: null });
  setSelected(id);
  document.body.classList.add('field-mode');
  document.body.classList.toggle('unc-mode', state.uncertainty);
  getMap().flyToBounds(f.bounds, { paddingTopLeft: [60, 150], paddingBottomRight: [($('#panel').offsetWidth || 360) + 80, 60],
    duration: 0.8 });
  updateSampling();
  loadFieldExtras(f);
  applyRelief();
  if (breakdownOpen()) views3d.texture.close(true);
  const done = refresh();
  if (views3d.stack) views3d.stack.open(f, stackCtx());
  await done;
}

/** Grids auxiliares para el tooltip (fracciones derived, Ackerzahl) y puntos para el inspector. */
async function loadFieldExtras(f) {
  const want = [['derived', 'clay'], ['derived', 'sand'], ['derived', 'silt'], ['lbeg', 'ackerzahl'],
    ['copernicus_dem', 'elevation'], ['lbeg', 'bodenzahl']];          // los dos últimos: solo con terreno
  const grids = await Promise.all(want.map(async ([s, p]) => {
    const m = findLayer(f, s, p);
    try { return m ? await api.grid(m.grid_url) : null; } catch { return null; }
  }));
  if (state.selected !== f.field_id) return;
  state.extras = { clay: grids[0], sand: grids[1], silt: grids[2], ackerzahl: grids[3], elevation: grids[4], bodenzahl: grids[5] };
  try {
    const pts = await api.points(f.field_id);
    if (state.selected === f.field_id) state.points = pts.points;
  } catch { /* el inspector lo reintenta al hacer clic */ }
}

async function openInspectorAt(latlng) {
  const f = state.byId.get(state.selected);
  let pts = state.points;
  if (!pts) {
    try { pts = (await api.points(f.field_id)).points; state.points = pts; } catch { return; }
  }
  const p = nearestPoint(pts, latlng.lat, latlng.lng);
  hideTip();
  if (p) openInspector(p, f);
}

// ---------- capas ----------
const currentLayer = () => layerById(state.layerId);
const currentSub = () => state.sub[state.layerId] || (currentLayer().subs ? currentLayer().subs[0].id : null);
const sourceKey = () => `${state.layerId}|${currentSub() ?? ''}`;

function currentSource(avail) {
  const chosen = state.source[sourceKey()];
  if (chosen && avail.includes(chosen)) return chosen;
  const def = currentLayer().defaultSource(currentSub());
  return avail.includes(def) ? def : (avail[0] || def);
}

function setLayer(id) {
  if (id === state.layerId || !state.fields.length) return;
  state.layerId = id;
  refresh();
}

function panelView() {
  const layer = currentLayer();
  const sub = currentSub();
  const field = state.byId.get(state.selected);
  const source = currentSource(availableSources(layer, sub, state.fields));
  return {
    mode: state.view === 'field' ? 'field' : 'farm', layerId: layer.id, sub, source,
    sources: availableSources(layer, sub, field ? [field] : state.fields), featured: state.featured,
    field, sampling: state.sampling, card: state.card,
    uncertainty: { on: state.uncertainty, available: state.unc?.available, summary: state.unc?.summary },
    views3d: { stack: !!views3d.stack, texture: !!views3d.texture, breakdown: breakdownOpen() },
    terrain: hasTerrain(state.data) ? { layers: state.terrain, relief: state.relief,
      profile: state.view === 'field' && profile.canProfile(field), profileOpen: profile.isOpen() } : null,
  };
}

// ---------- relieve sombreado (módulo de terreno) ----------
function applyRelief() {
  setRelief({ on: state.relief, view: state.view, data: state.data, field: state.byId.get(state.selected) });
}

function toggleProfile() {
  if (state.view !== 'field' || stackOpen() || breakdownOpen()) return;
  const f = state.byId.get(state.selected);
  if (!profile.canProfile(f)) return;
  if (profile.isOpen()) profile.close();
  else {
    closeInspector();
    profile.start(f);
    document.querySelectorAll('[data-action="profile"]').forEach((b) => b.classList.add('on'));
  }
}

function toggleRelief() {
  if (state.view === 'landing' || !hasTerrain(state.data)) return;
  state.relief = !state.relief;
  document.querySelectorAll('#relief-toggle').forEach((el) => el.classList.toggle('on', state.relief));
  document.body.classList.toggle('relief-on', state.relief);
  applyRelief();
}

async function refresh() {
  if (!state.fields.length || state.view === 'landing') return;
  if (breakdownOpen() && state.layerId !== 'texture') views3d.texture.close(true);
  const view = panelView();
  const layer = currentLayer();
  hideTip();
  state.card = null;
  state.unc = null;
  renderPanel({ ...view, card: null });
  await paintAll(layer, view.sub, view.source);
  if (state.view === 'field') await updateField(layer, view);
}

async function paintAll(layer, sub, source) {
  const token = ++state.renderToken;
  state.idle = false;
  const total = state.fields.length;
  let done = 0;
  const cats = {};
  let missing = false;
  progress(0, total);
  if (state.view !== 'field') renderLegend(legendModel(layer, sub, source, cats, false));

  // El campo seleccionado primero
  const order = state.selected
    ? [state.byId.get(state.selected), ...state.fields.filter((f) => f.field_id !== state.selected)] : state.fields;
  await pool(order, 8, async (f) => {
    const r = layer.resolve(f, sub, source);
    const meta = findLayer(f, r.source, r.parameter);
    let grid = null;
    try { grid = meta ? await api.grid(meta.grid_url) : null; } catch { grid = null; }
    if (token !== state.renderToken) return;
    const pal = palette(r.palette);
    const out = renderLayer(grid || emptyGrid(f.bounds), pal, f.geometry, {
      smooth: true, cacheKey: `${f.field_id}|${layer.id}|${r.source}|${r.parameter}|data`,
    });
    state.renders.set(f.field_id, out);
    state.grids.set(f.field_id, grid);
    const counts = !state.selected || f.field_id === state.selected;
    if (counts) missing = missing || out.missing;
    if (pal.kind === 'cat' && grid && counts) {
      const set = (cats[pal.key] ??= new Set());
      for (const row of grid.values) for (const v of row) if (v != null) set.add(v);
    }
    setOverlay(f.field_id, out.dataUrl(), f.bounds);
    progress(++done, total);
  });
  if (token !== state.renderToken) return;
  state.lastLegend = legendModel(layer, sub, source, cats, missing);
  if (!(state.view === 'field' && state.uncertainty)) renderLegend(state.lastLegend);
  if (state.view !== 'field') state.idle = true;
}

function legendModel(layer, sub, source, cats, missing) {
  const ref = state.selected ? state.byId.get(state.selected) : state.fields[0];
  const r = layer.resolve(ref, sub, source);
  const pal = palette(r.palette);
  if (pal.kind === 'num') {
    return { kind: 'num', palette: pal, unit: layer.unit(sub, source), caption: pal.caption || layer.label(sub, source), missing };
  }
  const keys = sub === 'classes' && source === 'auto' ? ['bs', 'ka5'] : [r.palette];
  const groups = keys.filter((k) => cats[k]?.size).map((k) => {
    const p = palette(k);
    return { title: p.title, items: [...cats[k]].sort(p.sort).map((v) => ({ value: v, name: p.name(v), color: p.color(v) })) };
  });
  return { kind: 'cat', groups, missing };
}

// ---------- tarjeta del campo e incertidumbre ----------
async function updateField(layer, view) {
  const token = state.renderToken;
  const f = state.byId.get(state.selected);
  state.card = fieldCard(layer, view, f);
  if (!state.uncertainty) setCard(cardHtml(state.card));

  // Incertidumbre precargada (opacidad 0) para que el interruptor sea instantáneo
  if (layer.terrain) {                 // terreno: una sola fuente, sin mapa de incertidumbre
    state.unc = { render: null, available: false, scale: null, summary: null };
    if (state.uncertainty) applyUncertaintyPanel();
    state.idle = true;
    return;
  }
  const scale = await farmScale(layer, state.fields);
  const { grid, available } = await uncertaintyGrid(layer, f, scale, state.grids.get(f.field_id));
  if (token !== state.renderToken || state.selected !== f.field_id) return;
  const pal = layer.id === 'reliability' ? palette('reliability') : palette('alert');
  const render = renderLayer(grid, pal, f.geometry, { smooth: true, transform: (v) => v.u });
  state.unc = { render, available, scale, summary: available && layer.id !== 'reliability' ? summarize(grid, layer) : null };
  setUncertaintyOverlay(f.field_id, render.dataUrl(), f.bounds, state.uncertainty);
  if (state.uncertainty) applyUncertaintyPanel();
  state.idle = true;
}

function setCard(html) {
  const el = $('#card');
  if (el) el.innerHTML = html;
}

const r1 = (v) => (v == null ? '—' : (Math.round(v * 10) / 10).toFixed(1));

function fieldCard(layer, view, f) {
  const r = layer.resolve(f, view.sub, view.source);
  const meta = findLayer(f, r.source, r.parameter);
  const grid = state.grids.get(f.field_id);
  if (!meta || !grid) {
    return { kind: 'empty', message: r.source === 'lbeg' ? (f.state === 'Lower Saxony'
      ? 'LBEG did not return data for this field (service unavailable).' : 'No official data outside Lower Saxony.')
      : 'No data from this source for this field.' };
  }
  const pal = palette(r.palette);
  const vals = grid.values.flat().filter((v) => v != null);
  const coverage = meta.stats?.coverage_pct;
  if (pal.kind === 'cat') {
    const counts = {};
    for (const v of vals) counts[v] = (counts[v] || 0) + 1;
    const items = Object.entries(counts).sort((a, b) => b[1] - a[1])
      .map(([v, n]) => ({ value: v, name: pal.name(v), pct: 100 * n / vals.length, color: pal.color(v) }));
    return { kind: 'cat', items, coverage };
  }
  const disp = layer.display || ((v) => v);
  const colorOf = (dv) => pal.color(layer.display ? 1 - dv / 100 : dv);
  const st = meta.stats || {};
  let [mean, min, max] = [st.mean, st.min, st.max];
  if (layer.display) [mean, min, max] = [disp(st.mean), disp(st.max), disp(st.min)];
  const hist = histogram(vals.map(disp), colorOf);
  if (layer.id === 'bodenzahl' && view.sub !== 'acker_delta') {
    const ack = findLayer(f, 'lbeg', 'ackerzahl');
    return { kind: 'quality', mean, min: Math.round(min), max: Math.round(max), coverage, hist,
      color: toCss(palette('quality').color(mean)), ackerzahl: ack?.stats?.mean };
  }
  const dec = layer.id === 'ph' ? 2 : 1;
  const fx = (v) => (layer.display ? String(Math.round(v)) : v.toFixed(dec));
  return { kind: 'num', label: layer.label(view.sub, view.source), unit: layer.unit(view.sub, view.source),
    mean: fx(mean), min: fx(min), max: fx(max), coverage, hist };
}

function histogram(vals, colorOf, nb = 12) {
  if (!vals.length) return [];
  let lo = Infinity, hi = -Infinity;
  for (const v of vals) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const w = (hi - lo) / nb || 1;
  const bins = Array.from({ length: nb }, (_, i) => ({ n: 0, lo: r1(lo + i * w), hi: r1(lo + (i + 1) * w),
    color: colorOf(lo + (i + 0.5) * w) }));
  for (const v of vals) bins[Math.min(nb - 1, Math.floor((v - lo) / w))].n++;
  return hi === lo ? [bins[0]] : bins;
}

function toggleUncertainty() {
  if (state.view !== 'field' || stackOpen() || breakdownOpen()) return;
  state.uncertainty = !state.uncertainty;
  $('#unc-toggle')?.classList.toggle('on', state.uncertainty);
  document.body.classList.toggle('unc-mode', state.uncertainty);
  if (!currentLayer().terrain) showUncertainty(state.selected, state.uncertainty);
  hideTip();
  if (state.uncertainty) applyUncertaintyPanel();
  else {
    setCard(cardHtml(state.card));
    if (state.lastLegend) renderLegend(state.lastLegend);
  }
}

function applyUncertaintyPanel() {
  const view = panelView();
  const layer = currentLayer();
  setCard(state.unc ? cardFor(view) : cardHtml(null));
  const sc = state.unc?.scale;
  if (layer.terrain) {
    if (state.lastLegend) renderLegend(state.lastLegend);
  } else if (layer.id === 'reliability') {
    renderLegend({ kind: 'num', palette: palette('reliability'), caption: 'Reliability index (high → low)' });
  } else if (state.unc?.available && sc) {
    const kind = state.unc.summary?.kind || 'spread';
    const ref = kind === 'spread' ? sc.spread : sc.sigma;
    const pal = { ...palette('alert'), ticks: [0, 0.25, 0.5, 0.75, 1], tickLabel: (t) => (t * ref).toFixed(1) };
    renderLegend({ kind: 'num', palette: pal, unit: layer.uncertainty.unit,
      caption: kind === 'spread' ? 'Disagreement between sources' : 'Model uncertainty' });
  } else {
    renderLegend({ kind: 'num', palette: palette('alert'), caption: 'Uncertainty not available', missing: true });
  }
}

// ---------- tooltip ----------
function onMouseMove(e) {
  if (state.view !== 'field' || stackOpen() || breakdownOpen()) return;
  const f = state.byId.get(state.selected);
  const { lat, lng } = e.latlng;
  const overPopup = e.originalEvent?.target?.closest?.('.leaflet-popup, .sample-marker');
  if (!f || overPopup || !pointInRings(lng, lat, ringsOf(f.geometry))) { hideTip(); return; }
  const layer = currentLayer();
  let html;
  if (state.uncertainty && layer.terrain) {
    html = `<div class="tip-main">${escapeHtml(layer.uncertaintyNote)}</div>`;
  } else if (state.uncertainty) {
    const ok = state.unc?.available;
    const v = ok ? state.unc.render.getValue(lat, lng) : null;
    html = `<div class="tip-title">${escapeHtml(layer.name)} · uncertainty</div>
      <div class="tip-main">${escapeHtml(ok ? uncertaintyText(layer, v) : 'Uncertainty not available for this layer')}</div>`;
  } else {
    html = valueTip(layer, currentSub(), state.renders.get(f.field_id)?.getValue(lat, lng), lat, lng);
  }
  showTip(e.originalEvent.clientX, e.originalEvent.clientY, html);
}

function valueTip(layer, sub, v, lat, lng) {
  if (v == null) return '<div class="tip-main muted">No data at this point</div>';
  const src = panelView().source;
  const ex = state.extras || {};
  if (layer.id === 'texture' && sub === 'classes') {
    const isBs = !KA5_NAMES[v] && (!!BS_NAMES[v] || bsName(v) !== v || /Mo|\//.test(v));
    const name = isBs ? bsName(v) : (KA5_NAMES[v] || '');
    const pt = state.points ? nearestPoint(state.points, lat, lng) : null;
    const parts = ['clay', 'sand', 'silt'].map((p) => [p, pt?.values[p]?.derived ?? cellValue(ex[p], lat, lng)])
      .filter(([, x]) => x != null);
    return `<div class="tip-title">${isBs ? 'Soil assessment class' : 'KA5 texture class'}</div>
      <div class="tip-main"><span class="swatch" style="background:${toCss(palette(isBs ? 'bs' : 'ka5').color(v))}"></span><b>${escapeHtml(v)}</b> ${escapeHtml(name)}</div>
      ${parts.length ? `<div class="tip-sub">${parts.map(([p, x]) => `${p[0].toUpperCase() + p.slice(1)} ${Math.round(x)} %`).join(' · ')}</div>` : ''}`;
  }
  if (layer.terrain) return terrainTip(layer.id, v, cellValue(ex.elevation, lat, lng));
  if (layer.id === 'bodenzahl' && sub === 'acker_delta') {
    const line = ackerLine(cellValue(ex.bodenzahl, lat, lng), cellValue(ex.ackerzahl, lat, lng));
    return `<div class="tip-title">Ackerzahl − Bodenzahl</div><div class="tip-main"><b>${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(Math.round(v))}</b></div>
      ${line ? `<div class="tip-sub">${line}</div>` : ''}`;
  }
  if (layer.id === 'bodenzahl') {
    const ack = cellValue(ex.ackerzahl, lat, lng);
    const p = state.points ? nearestPoint(state.points, lat, lng) : null;
    const origin = p ? soilOrigin(p.klassenzeichen) : null;
    return `<div class="tip-main">Bodenzahl <b style="color:${toCss(palette('quality').color(v))}">${Math.round(v)}</b> · Ackerzahl <b>${ack != null ? Math.round(ack) : '—'}</b></div>
      ${origin ? `<div class="tip-sub">Formed on ${escapeHtml(origin)} · ${escapeHtml(p.klassenzeichen)}</div>` : ''}`;
  }
  if (layer.id === 'reliability') return `<div class="tip-main">Reliability index <b>${layer.display(v)}</b> / 100</div>`;
  const dec = layer.id === 'ph' ? 2 : 1;
  const unit = layer.unit(sub, src);
  return `<div class="tip-title">${escapeHtml(layer.label(sub, src))}</div><div class="tip-main"><b>${v.toFixed(dec)}</b> ${escapeHtml(unit)}</div>`;
}

// ---------- muestreo ----------
function toggleSampling() {
  if (state.view === 'landing') return;
  state.sampling = !state.sampling;
  $('#sampling-btn')?.classList.toggle('on', state.sampling);
  updateSampling();
}

function updateSampling() {
  if (!state.sampling) { showSampling([]); return; }
  if (state.view === 'field') {
    const f = state.byId.get(state.selected);
    if (f.sampling) showSampling(f.sampling);
    else api.sampling(f.field_id).then((r) => state.sampling && state.selected === f.field_id && showSampling(r.points)).catch(() => {});
  } else {
    showSampling(state.fields.flatMap((f) => (f.sampling || []).map((p) => ({ ...p, fieldName: f.name }))), { compact: true });
  }
}

// ---------- utilidades ----------
function progress(done, total) {
  const bar = $('#progress');
  bar.style.width = `${total ? (done / total) * 100 : 0}%`;
  bar.classList.toggle('done', done >= total);
}

async function pool(items, n, fn) {
  let i = 0;
  const workers = Array.from({ length: Math.min(n, items.length) }, async () => {
    while (i < items.length) await fn(items[i++]);
  });
  await Promise.all(workers);
}

window.__app.enterField = enterField;
window.__app.setLayer = setLayer;
window.__app.toggleUncertainty = toggleUncertainty;
window.__app.views3d = views3d;
window.__app.closeStack = () => { if (stackOpen()) stackCtx().onMapView(); };
init();
