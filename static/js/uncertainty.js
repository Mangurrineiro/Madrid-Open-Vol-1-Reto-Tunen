// Incertidumbre por píxel de una capa: desacuerdo entre fuentes ({p}_disagreement = spread) o,
// si falta, σ del modelo ({p}_sigma). Normalizada por el percentil 98 de toda la granja.
import { api } from './api.js';
import { findLayer } from './catalog.js';
import { emptyGrid } from './renderer.js';

const scales = new Map();          // layerId → {spread, sigma} (p98)
const PARAM_NAME = { clay: 'clay', sand: 'sand', silt: 'silt', soc: 'organic carbon', nfk: 'nFK' };

const paramOf = (name) => name.replace(/_(disagreement|sigma)$/, '');

async function gridsOf(field, names) {
  return Promise.all(names.map(async (n) => {
    const meta = findLayer(field, 'derived', n);
    if (!meta) return null;
    try { return await api.grid(meta.grid_url); } catch { return null; }
  }));
}

/** Máximo por celda entre varios grids (y de qué parámetro sale). */
function cellMax(grids, names, r, c) {
  let best = null, who = null;
  grids.forEach((g, i) => {
    const v = g?.values[r]?.[c];
    if (v != null && (best == null || v > best)) { best = v; who = paramOf(names[i]); }
  });
  return best == null ? null : [best, who];
}

/** Grid crudo: cada celda {raw, kind:'spread'|'sigma', param} o null. */
async function rawGrid(layer, field) {
  const spec = layer.uncertainty;
  if (!spec) return null;
  const [sp, sg] = await Promise.all([gridsOf(field, spec.spread), gridsOf(field, spec.sigma)]);
  const tpl = sp.find(Boolean) || sg.find(Boolean);
  if (!tpl) return null;
  const values = tpl.values.map((row, r) => row.map((_, c) => {
    const a = cellMax(sp, spec.spread, r, c);
    if (a) return { raw: a[0], kind: 'spread', param: a[1] };
    const b = cellMax(sg, spec.sigma, r, c);
    return b ? { raw: b[0], kind: 'sigma', param: b[1] } : null;
  }));
  return { bounds: tpl.bounds, width: tpl.width, height: tpl.height, values };
}

function p98(arr) {
  if (!arr.length) return 1;
  arr.sort((a, b) => a - b);
  return arr[Math.min(arr.length - 1, Math.floor(0.98 * (arr.length - 1)))] || 1;
}

/** p98 de spread y σ en toda la granja (una vez por capa). */
export async function farmScale(layer, fields) {
  if (!layer.uncertainty) return null;
  if (scales.has(layer.id)) return scales.get(layer.id);
  const p = (async () => {
    const spread = [], sigma = [];
    for (const g of await Promise.all(fields.map((f) => rawGrid(layer, f)))) {
      if (!g) continue;
      for (const row of g.values) for (const v of row) if (v) (v.kind === 'spread' ? spread : sigma).push(v.raw);
    }
    return { spread: p98(spread), sigma: p98(sigma) };
  })();
  scales.set(layer.id, p);
  return p;
}

export function resetScales() { scales.clear(); }

/**
 * Grid de incertidumbre para el renderizador: valores {u (0-1 para el color), raw, kind, param}.
 * Capas sin incertidumbre → grid vacío (rayado). Fiabilidad → la propia prioridad de muestreo.
 */
export async function uncertaintyGrid(layer, field, scale, dataGrid) {
  if (layer.id === 'reliability' && dataGrid) {
    return { available: true, grid: { ...dataGrid, values: dataGrid.values.map((row) => row.map((v) => (v == null ? null
      : { u: v, raw: Math.round(100 * (1 - v)), kind: 'reliability', param: null }))) } };
  }
  const g = layer.uncertainty ? await rawGrid(layer, field) : null;
  if (!g || !scale) return { grid: emptyGrid(field.bounds), available: false };
  for (const row of g.values) {
    row.forEach((v) => { if (v) v.u = Math.min(1, v.raw / (v.kind === 'spread' ? scale.spread : scale.sigma)); });
  }
  return { grid: g, available: true };
}

/** Resumen para el panel: media del desacuerdo, parámetro dominante y frase de dónde se concentra. */
export function summarize(grid, layer) {
  const cells = [];
  grid.values.forEach((row, r) => row.forEach((v, c) => { if (v) cells.push({ ...v, r, c }); }));
  if (!cells.length) return null;
  const spread = cells.filter((v) => v.kind === 'spread');
  const use = spread.length ? spread : cells;
  const mean = use.reduce((a, v) => a + v.raw, 0) / use.length;
  const counts = {};
  for (const v of use) counts[v.param] = (counts[v.param] || 0) + 1;
  const dominant = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0];

  const sorted = [...use].sort((a, b) => b.raw - a.raw);
  const top = sorted.slice(0, Math.max(1, Math.round(use.length * 0.15)));
  const spreadRange = sorted[0].raw - sorted[sorted.length - 1].raw;
  let where;
  if (use.length < 4 || spreadRange < 0.15 * Math.max(mean, 1e-6)) where = 'Disagreement is fairly even across the field';
  else {
    const W = grid.width, H = grid.height;
    const dx = top.reduce((a, v) => a + v.c, 0) / top.length / W - 0.5;
    const dy = 0.5 - top.reduce((a, v) => a + v.r, 0) / top.length / H;
    const ns = dy > 0.12 ? 'north' : dy < -0.12 ? 'south' : '';
    const ew = dx > 0.12 ? 'east' : dx < -0.12 ? 'west' : '';
    where = ns && ew ? `Our sources disagree most in the ${ns}-${ew} corner`
      : ns || ew ? `Our sources disagree most in the ${ns || ew}ern part of the field`
        : 'Our sources disagree most in the centre of the field';
  }
  return { mean, kind: spread.length ? 'spread' : 'sigma', dominant, where, unit: layer.uncertainty?.unit || '' };
}

/** Texto del tooltip para una celda de incertidumbre. */
export function uncertaintyText(layer, v) {
  if (!layer.uncertainty && layer.id !== 'reliability') return 'Uncertainty not available for this layer';
  if (!v) return 'No uncertainty estimate at this point';
  if (v.kind === 'reliability') return `Reliability index ${v.raw} / 100`;
  const unit = layer.uncertainty.unit;
  if (v.kind === 'spread') {
    return unit === '%' ? `Sources disagree by ${v.raw.toFixed(1)} ${PARAM_NAME[v.param]} points`
      : `Sources disagree by ${v.raw.toFixed(1)} ${unit} (${PARAM_NAME[v.param]})`;
  }
  return `Model uncertainty ± ${v.raw.toFixed(1)} ${unit === '%' ? `% ${PARAM_NAME[v.param]}` : unit}`;
}
