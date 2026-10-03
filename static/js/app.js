// Estado y navegación: pantalla inicial → vista de granja.
import { api } from './api.js';
import { LAYERS, availableSources, findLayer, layerById } from './catalog.js';
import { createMap, fitBounds, getMap, setFields, setOverlay, unionBounds, escapeHtml } from './map2d.js';
import { initPanel, renderFarmPanel, renderLegend } from './panel.js';
import { palette } from './palettes.js';
import { emptyGrid, renderLayer } from './renderer.js';
import { initDropzone, setZoneMessage } from './upload.js';

const $ = (s) => document.querySelector(s);

const state = {
  view: 'landing',
  data: null,              // respuesta de /soil/demo o /soil/layers
  name: '',
  layerId: 'texture',
  sub: { texture: 'classes' },
  source: {},              // layerId|sub → fuente elegida
  renderToken: 0,
  idle: true,              // false mientras se cargan grids (lo usa el test)
};
window.__app = { state };

// ---------- arranque ----------
function init() {
  window.__app.map = createMap($('#map'));
  api.farmOutline().then((fc) => {
    const pts = [];
    for (const f of fc.features) {
      if (f.properties?.isArchived) continue;
      const g = f.geometry;
      const rings = g.type === 'Polygon' ? g.coordinates : g.type === 'MultiPolygon' ? g.coordinates.flat() : [];
      for (const r of rings) for (const [lon, lat] of r) pts.push([lat, lon]);
    }
    if (pts.length) getMap().fitBounds(L.latLngBounds(pts), { padding: [20, 20] });
  }).catch(() => { /* fondo genérico */ });

  $('#try-demo').addEventListener('click', loadDemo);
  initDropzone($('#dropzone'), $('#file-input'), loadFile);
  initPanel($('#panel'), {
    layer: (id) => setLayer(id),
    sub: (id) => { state.sub[state.layerId] = id; refresh(); },
    source: (s) => { state.source[sourceKey()] = s; refresh(); },
    featured: (id) => focusField(id),
  });
  document.addEventListener('keydown', (e) => {
    if (state.view === 'landing' || e.target.closest('input, textarea')) return;
    const n = Number(e.key);
    if (n >= 1 && n <= LAYERS.length) setLayer(LAYERS[n - 1].id);
  });
}

async function loadDemo() {
  const btn = $('#try-demo');
  btn.classList.add('loading');
  btn.disabled = true;
  try {
    const data = await api.demo();
    await enterFarm(data, data.name || 'Example farm');
  } catch (err) {
    setZoneMessage($('#dropzone'), `Could not load the example farm: ${err.message}`, true);
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
}

async function loadFile(file) {
  setZoneMessage($('#dropzone'), `Reading ${file.name}…`);
  try {
    const fc = JSON.parse(await file.text());
    const data = await api.layers(fc.type === 'FeatureCollection' ? fc
      : { type: 'FeatureCollection', features: [fc.type === 'Feature' ? fc : { type: 'Feature', properties: {}, geometry: fc }] });
    await enterFarm(data, file.name.replace(/\.(geo)?json$/i, ''));
  } catch (err) {
    setZoneMessage($('#dropzone'), `Could not process the file: ${err.message}`, true);
  }
}

// ---------- vista de granja ----------
async function enterFarm(data, name) {
  if (!data.fields?.length) throw new Error('no field boundaries found');
  state.data = data;
  state.name = name;
  state.fields = data.fields;
  state.byId = new Map(data.fields.map((f) => [f.field_id, f]));
  state.featured = data.featured?.length ? data.featured : featuredFallback(data.fields);

  renderHeader();
  setFields(state.fields, { onClick: (f) => focusField(f.field_id) });
  state.view = 'farm';
  document.body.classList.add('farm');
  $('#landing').classList.add('hidden');
  setTimeout(() => $('#landing').style.setProperty('display', 'none'), 500);
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

function focusField(id) {
  const f = state.byId.get(id);
  if (!f) return;
  getMap().flyToBounds(f.bounds, { paddingTopLeft: [40, 90], paddingBottomRight: [420, 40], duration: 0.8 });
}

// ---------- capas ----------
const currentLayer = () => layerById(state.layerId);
const currentSub = () => state.sub[state.layerId] || (currentLayer().subs ? currentLayer().subs[0].id : null);
const sourceKey = () => `${state.layerId}|${currentSub() ?? ''}`;

function currentSource(avail) {
  const layer = currentLayer();
  const chosen = state.source[sourceKey()];
  if (chosen && avail.includes(chosen)) return chosen;
  const def = layer.defaultSource(currentSub());
  return avail.includes(def) ? def : (avail[0] || def);
}

function setLayer(id) {
  if (id === state.layerId) return;
  state.layerId = id;
  refresh();
}

async function refresh() {
  if (!state.fields) return;
  const layer = currentLayer();
  const sub = currentSub();
  const avail = availableSources(layer, sub, state.fields);
  const source = currentSource(avail);
  renderFarmPanel({ layerId: layer.id, sub, source, sources: avail, featured: state.featured });
  await paintAll(layer, sub, source);
}

async function paintAll(layer, sub, source) {
  const token = ++state.renderToken;
  state.idle = false;
  const total = state.fields.length;
  let done = 0;
  const cats = {};               // palette key → Set(clases)
  let missing = false;
  progress(0, total);
  renderLegend(legendModel(layer, sub, source, cats, false));

  await pool(state.fields, 8, async (f) => {
    const r = layer.resolve(f, sub, source);
    const meta = findLayer(f, r.source, r.parameter);
    let grid = null;
    try { grid = meta ? await api.grid(meta.grid_url) : null; } catch { grid = null; }
    if (token !== state.renderToken) return;
    const pal = palette(r.palette);
    const out = renderLayer(grid || emptyGrid(f.bounds), pal, f.geometry, {
      smooth: true, cacheKey: `${f.field_id}|${layer.id}|${r.source}|${r.parameter}|data`,
    });
    missing = missing || out.missing;
    if (pal.kind === 'cat' && grid) {
      const set = (cats[pal.key] ??= new Set());
      for (const row of grid.values) for (const v of row) if (v != null) set.add(v);
    }
    setOverlay(f.field_id, out.dataUrl(), f.bounds);
    progress(++done, total);
  });
  if (token !== state.renderToken) return;
  renderLegend(legendModel(layer, sub, source, cats, missing));
  state.idle = true;
}

function legendModel(layer, sub, source, cats, missing) {
  const r = layer.resolve(state.fields[0], sub, source);
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

init();
export { state, escapeHtml };
