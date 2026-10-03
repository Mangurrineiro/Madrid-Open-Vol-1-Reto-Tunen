// Panel derecho (modo "Farm"): capas, selector de fuente, leyenda y campos destacados.
import { LAYERS, SOURCE_LABEL, SOURCE_NOTE } from './catalog.js';
import { escapeHtml } from './map2d.js';
import { gradientCss, toCss } from './palettes.js';

let root;
let handlers = {};

export function initPanel(el, h) {
  root = el;
  handlers = h;
  root.addEventListener('click', (ev) => {
    const t = ev.target.closest('[data-action]');
    if (!t) return;
    const { action, value } = t.dataset;
    if (t.classList.contains('disabled')) return;
    handlers[action] && handlers[action](value);
  });
}

/**
 * view: {layerId, sub, source, sources: [...disponibles], featured: [...], fields}
 */
export function renderFarmPanel(view) {
  const layer = LAYERS.find((l) => l.id === view.layerId);
  const items = LAYERS.map((l, i) => `
    <button class="layer-item ${l.id === view.layerId ? 'active' : ''}" data-action="layer" data-value="${l.id}">
      <span class="layer-icon">${l.icon}</span>
      <span class="layer-text"><span class="layer-name">${l.name}</span><span class="layer-desc">${l.desc}</span></span>
      <kbd>${i + 1}</kbd>
    </button>`).join('');

  const subs = layer.subs ? `<div class="segmented subs">${layer.subs.map((s) => `
      <button class="${s.id === view.sub ? 'on' : ''}" data-action="sub" data-value="${s.id}">${s.label}</button>`).join('')}</div>` : '';

  const all = layer.sources(view.sub);
  const sources = `<div class="segmented sources">${all.map((s) => {
    const ok = view.sources.includes(s);
    return `<button class="${s === view.source ? 'on' : ''} ${ok ? '' : 'disabled'}" data-action="source" data-value="${s}"
      title="${ok ? (SOURCE_NOTE[s] || 'Weighted combination of all sources') : 'No data from this source on these fields'}">${SOURCE_LABEL[s]}</button>`;
  }).join('')}</div>`;

  const featured = (view.featured || []).map((f, i) => `
    <button class="featured-item" data-action="featured" data-value="${escapeHtml(f.field_id)}">
      <span class="featured-rank">${i + 1}</span>
      <span class="featured-text"><span class="featured-name">${escapeHtml(f.name)}</span>
        <span class="featured-why">${escapeHtml(f.reason)}</span></span>
      <span class="featured-state">${f.state === 'Lower Saxony' ? 'NI' : f.state === 'Saxony-Anhalt' ? 'ST' : '—'}</span>
    </button>`).join('');

  root.innerHTML = `
    <section class="panel-section">
      <h2 class="panel-title">Layers</h2>
      <div class="layer-list">${items}</div>
    </section>
    <section class="panel-section active-layer">
      <div class="section-head"><h3>${layer.label(view.sub, view.source)}</h3>
        <span class="muted">${layer.panelNote ? '' : 'Source'}</span></div>
      ${layer.panelNote ? `<p class="note">${layer.panelNote}</p>` : ''}
      ${subs}
      ${sources}
      <div id="legend" class="legend"></div>
    </section>
    <section class="panel-section">
      <h2 class="panel-title">Featured fields</h2>
      <div class="featured-list">${featured || '<p class="muted">No featured fields</p>'}</div>
    </section>`;
}

/**
 * model: {kind:'num', palette, unit, caption} | {kind:'cat', groups:[{title, items:[{value,name,color}]}]}
 */
export function renderLegend(model) {
  const el = root && root.querySelector('#legend');
  if (!el) return;
  if (!model) { el.innerHTML = ''; return; }
  if (model.kind === 'num') {
    const p = model.palette;
    const span = p.max - p.min;
    const ticks = p.ticks.map((t) => `<span style="left:${((t - p.min) / span * 100).toFixed(1)}%">${p.tickLabel ? p.tickLabel(t) : fmt(t)}</span>`).join('');
    el.innerHTML = `
      <div class="legend-caption">${model.caption || ''}${model.unit ? ` <span class="muted">(${model.unit})</span>` : ''}</div>
      <div class="legend-bar ${p.key === 'reliability' || p.key === 'alert' ? 'checker' : ''}"><div style="background:${gradientCss(p)}"></div></div>
      <div class="legend-ticks">${ticks}</div>
      ${model.missing ? '<div class="legend-missing"><i class="hatch-swatch"></i>No data inside the field</div>' : ''}`;
    return;
  }
  el.innerHTML = model.groups.map((g) => `
    <div class="legend-caption">${g.title}</div>
    <div class="legend-classes">${g.items.map((it) => `
      <div class="legend-class"><i style="background:${toCss(it.color)}"></i><b>${escapeHtml(it.value)}</b><span>${escapeHtml(it.name)}</span></div>`).join('')}
    </div>`).join('') +
    (model.missing ? '<div class="legend-missing"><i class="hatch-swatch"></i>No data inside the field</div>' : '') +
    (model.groups.length ? '' : '<p class="muted">Loading classes…</p>');
}

const fmt = (v) => (Math.abs(v) >= 10 || Number.isInteger(v) ? String(Math.round(v * 10) / 10) : v.toFixed(1));
