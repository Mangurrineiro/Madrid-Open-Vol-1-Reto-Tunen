// Panel derecho: modo "Farm" (capas, fuente, leyenda, destacados) y modo "Field" (tarjeta del campo).
import { LAYERS, SOURCE_LABEL, SOURCE_NOTE, layerById } from './catalog.js';
import { escapeHtml } from './map2d.js';
import { gradientCss, palette, toCss } from './palettes.js';
import { reliefNote, reliefSwitch, terrainCard } from './terrain.js';

let root;
let handlers = {};

export function initPanel(el, h) {
  root = el;
  handlers = h;
  root.addEventListener('click', (ev) => {
    const t = ev.target.closest('[data-action]');
    if (!t || t.classList.contains('disabled')) return;
    handlers[t.dataset.action] && handlers[t.dataset.action](t.dataset.value);
  });
}

const BASE_SOURCES = [['soilgrids', 'SoilGrids'], ['lbeg', 'LBEG'], ['buek200', 'BÜK200']];

const layerItem = (view, compact) => (l, i) => `
    <button class="layer-item ${l.id === view.layerId ? 'active' : ''}" data-action="layer" data-value="${l.id}" title="${l.desc}">
      <span class="layer-icon">${l.icon}</span>
      <span class="layer-text"><span class="layer-name">${l.name}</span>${compact ? '' : `<span class="layer-desc">${l.desc}</span>`}</span>
      <kbd>${i + 1}</kbd>
    </button>`;

function layerList(view, compact) {
  const base = `<div class="layer-list ${compact ? 'compact' : ''}">${LAYERS.map(layerItem(view, compact)).join('')}</div>`;
  const t = view.terrain?.layers || [];
  if (!t.length) return base;
  const item = layerItem(view, compact);
  return `${base}<div class="terrain-group"><h2 class="panel-title">Terrain</h2>
    <div class="layer-list ${compact ? 'compact' : ''}">${t.map((l, i) => item(l, LAYERS.length + i)).join('')}</div></div>`;
}

const reliefTop = (view) => (view.terrain ? reliefSwitch(view.terrain.relief) : '');
const reliefFoot = (view) => (view.terrain ? reliefNote() : '');

function selectors(view, layer) {
  const subs = layer.subs ? `<div class="segmented subs">${layer.subs.map((s) => `
      <button class="${s.id === view.sub ? 'on' : ''}" data-action="sub" data-value="${s.id}">${s.label}</button>`).join('')}</div>` : '';
  const all = layer.sources(view.sub);
  const sources = `<div class="segmented sources">${all.map((s) => {
    const ok = view.sources.includes(s);
    return `<button class="${s === view.source ? 'on' : ''} ${ok ? '' : 'disabled'}" data-action="source" data-value="${s}"
      title="${ok ? (SOURCE_NOTE[s] || 'Weighted combination of all sources') : 'No data from this source here'}">${SOURCE_LABEL[s]}</button>`;
  }).join('')}</div>`;
  return subs + sources;
}

function samplingButton(view) {
  return `<button class="btn-ghost ${view.sampling ? 'on' : ''}" data-action="sampling" id="sampling-btn">
    <span class="pulse-dot"></span>Suggested sampling points<kbd>S</kbd></button>`;
}

export function renderPanel(view) {
  if (view.mode === 'field') return renderFieldPanel(view);
  const layer = layerById(view.layerId);
  const featured = (view.featured || []).map((f, i) => `
    <button class="featured-item" data-action="featured" data-value="${escapeHtml(f.field_id)}">
      <span class="featured-rank">${i + 1}</span>
      <span class="featured-text"><span class="featured-name">${escapeHtml(f.name)}</span>
        <span class="featured-why">${escapeHtml(f.reason)}</span></span>
      <span class="featured-state" title="${escapeHtml(f.state || '')}">${f.state === 'Lower Saxony' ? 'NI' : f.state === 'Saxony-Anhalt' ? 'ST' : '—'}</span>
    </button>`).join('');

  root.innerHTML = `${reliefTop(view)}
    <section class="panel-section">
      <h2 class="panel-title">Layers</h2>
      ${layerList(view, false)}
    </section>
    <section class="panel-section active-layer">
      <div class="section-head"><h3>${layer.label(view.sub, view.source)}</h3></div>
      ${layer.panelNote ? `<p class="note">${layer.panelNote}</p>` : ''}
      ${selectors(view, layer)}
      <div id="legend" class="legend"></div>${reliefFoot(view)}
    </section>
    <section class="panel-section">${samplingButton(view)}</section>
    <section class="panel-section">
      <h2 class="panel-title">Featured fields</h2>
      <div class="featured-list">${featured || '<p class="muted">No featured fields</p>'}</div>
    </section>
    ${keys(view)}`;
}

function renderFieldPanel(view) {
  const f = view.field;
  const layer = layerById(view.layerId);
  const chips = BASE_SOURCES.map(([s, n]) => {
    const has = (f.sources || []).includes(s);
    const why = has ? SOURCE_NOTE[s] : s === 'lbeg' ? 'LBEG data covers Lower Saxony only' : `No ${n} data for this field`;
    return `<span class="src-chip ${has ? 'on' : 'off'} src-${s}" title="${escapeHtml(why)}">${n}</span>`;
  }).join('');
  const u = view.uncertainty;

  root.innerHTML = `
    <section class="panel-section field-head">
      <button class="btn-back" data-action="back"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>Back to farm<kbd>B</kbd></button>
      <div class="eyebrow">Field</div>
      <h2 class="field-name">${escapeHtml(f.name)}</h2>
      <div class="field-meta"><span class="num">${f.area_ha.toFixed(1)} ha</span><span>·</span><span>${escapeHtml(f.state || '')}</span></div>
      <div class="src-chips">${chips}</div>
      ${view.phase2?.stack ? `<button class="btn-ghost stack-btn" data-action="stack">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></svg>
        Back to layer stack</button>` : ''}
    </section>${reliefTop(view)}
    <section class="panel-section">
      ${layerList(view, true)}
    </section>
    <section class="panel-section active-layer">
      <div class="section-head"><h3>${layer.label(view.sub, view.source)}</h3></div>
      ${selectors(view, layer)}
      ${view.phase2?.texture && layer.id === 'texture' ? `<button class="btn-ghost breakdown-btn ${view.phase2.breakdown ? 'on' : ''}" data-action="breakdown">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="5" width="5" height="14" rx="1"/><rect x="10" y="5" width="5" height="14" rx="1"/><rect x="17" y="5" width="4" height="14" rx="1"/></svg>
        ${view.phase2.breakdown ? 'Back to texture classes' : 'Show numeric breakdown'}</button>` : ''}
      <label class="switch ${u.on ? 'on' : ''}" data-action="uncertainty" id="unc-toggle">
        <span class="switch-track"><span class="switch-knob"></span></span>
        <span class="switch-label">Show uncertainty</span><kbd>U</kbd>
      </label>
      <div id="card" class="card">${u.on ? uncertaintyCard(view, layer) : cardHtml(view.card)}</div>
      <div id="legend" class="legend"></div>${reliefFoot(view)}
    </section>
    ${view.terrain ? terrainCard(f.terrain) : ''}
    <section class="panel-section">${samplingButton(view)}</section>
    ${keys(view)}`;
}

const KEYS = `<footer class="keys"><span><kbd>1-6</kbd> layers</span><span><kbd>U</kbd> uncertainty</span><span><kbd>S</kbd> sampling</span><span><kbd>B</kbd> back</span></footer>`;
const keys = (view) => (!view.terrain ? KEYS
  : `<footer class="keys"><span><kbd>1-${LAYERS.length + view.terrain.layers.length}</kbd> layers</span><span><kbd>U</kbd> uncertainty</span><span><kbd>R</kbd> relief</span><span><kbd>S</kbd> sampling</span><span><kbd>B</kbd> back</span></footer>`);

function uncertaintyCard(view, layer) {
  if (view.uncertainty.available === undefined) return cardHtml(null);
  const f = view.field;
  const ri = f.reliability_index;
  const col = ri == null ? 'var(--muted)' : toCss(palette('quality').color(ri));
  const s = view.uncertainty.summary;
  let dis;
  if (layer.id === 'reliability') dis = `<p class="note">${layer.panelNote}</p>`;
  else if (!view.uncertainty.available || !s) dis = `<div class="unc-na">${layer.uncertaintyNote || 'Uncertainty not available for this layer.'}</div>`;
  else {
    const label = s.kind === 'spread' ? 'Mean disagreement between sources' : 'Mean model uncertainty';
    const unit = s.unit === '%' ? `${s.dominant ? `${s.dominant} ` : ''}points` : s.unit;
    dis = `<div class="stat-label">${label}</div>
      <div class="big num">${s.kind === 'sigma' ? '± ' : ''}${s.mean.toFixed(1)} <small>${unit}</small></div>
      <p class="note where">${s.where}.</p>`;
  }
  return `
    <div class="rel-block">
      <div><div class="stat-label">Reliability index</div><div class="big num" style="color:${col}">${ri ?? '—'}<small> / 100</small></div></div>
      <div class="rel-bar wide"><i style="width:${ri ?? 0}%;background:${col}"></i></div>
    </div>
    ${dis}`;
}

/**
 * card: {kind:'num', label, unit, mean, min, max, coverage, hist:[{h,color,lo,hi}]}
 *     | {kind:'cat', items:[{value,name,pct,color}], coverage}
 *     | {kind:'quality', mean, ackerzahl, color, coverage}
 *     | {kind:'empty', message}
 */
export function cardHtml(card) {
  if (!card) return '<div class="skeleton"></div><div class="skeleton short"></div>';
  if (card.kind === 'empty') {
    return `<div class="empty-state"><i class="hatch-swatch big"></i><div><b>No data here</b><span>${escapeHtml(card.message)}</span></div></div>`;
  }
  const cov = `<span class="muted num">${card.coverage != null ? `${Math.round(card.coverage)} % coverage` : ''}</span>`;
  if (card.kind === 'quality') {
    return `<div class="quality">
        <div><div class="stat-label">Bodenzahl</div><div class="huge num" style="color:${card.color}">${Math.round(card.mean)}</div></div>
        <div><div class="stat-label">Ackerzahl</div><div class="big num">${card.ackerzahl != null ? Math.round(card.ackerzahl) : '—'}</div></div>
      </div>
      <div class="minmax"><span>Min <b class="num">${card.min}</b></span><span>Max <b class="num">${card.max}</b></span>${cov}</div>
      ${histHtml(card.hist)}`;
  }
  if (card.kind === 'cat') {
    const top = card.items[0];
    return `<div class="stat-label">Dominant class</div>
      <div class="big">${escapeHtml(top.value)} <small>${escapeHtml(top.name)}</small></div>
      <div class="cat-bars">${card.items.slice(0, 6).map((it) => `
        <div class="cat-bar"><i style="background:${toCss(it.color)}"></i><span>${escapeHtml(it.value)}</span>
          <div class="cat-track"><div style="width:${it.pct}%;background:${toCss(it.color)}"></div></div><b class="num">${Math.round(it.pct)} %</b></div>`).join('')}
      </div>
      <div class="minmax">${cov}</div>`;
  }
  return `<div class="stat-label">Mean ${escapeHtml(card.label.toLowerCase())}</div>
    <div class="big num">${card.mean}<small> ${escapeHtml(card.unit)}</small></div>
    <div class="minmax"><span>Min <b class="num">${card.min}</b></span><span>Max <b class="num">${card.max}</b></span>${cov}</div>
    ${histHtml(card.hist)}`;
}

function histHtml(hist) {
  if (!hist?.length) return '';
  const max = Math.max(...hist.map((b) => b.n), 1);
  return `<div class="hist">${hist.map((b) => `<i title="${b.lo} – ${b.hi}: ${b.n} cells" style="height:${Math.max(4, b.n / max * 100)}%;background:${toCss(b.color)}"></i>`).join('')}</div>`;
}

/**
 * model: {kind:'num', palette, unit, caption, missing} | {kind:'cat', groups:[{title, items}], missing}
 */
export function renderLegend(model) {
  const el = root && root.querySelector('#legend');
  if (!el) return;
  if (!model) { el.innerHTML = ''; return; }
  const missing = model.missing ? '<div class="legend-missing"><i class="hatch-swatch"></i>No data inside the field</div>' : '';
  if (model.kind === 'num') {
    const p = model.palette;
    const span = p.max - p.min;
    const ticks = p.ticks.map((t) => `<span style="left:${((t - p.min) / span * 100).toFixed(1)}%">${p.tickLabel ? p.tickLabel(t) : fmt(t)}</span>`).join('');
    el.innerHTML = `
      <div class="legend-caption">${model.caption || ''}${model.unit ? ` <span class="muted">(${model.unit})</span>` : ''}</div>
      <div class="legend-bar ${p.stops.some(([, c]) => c.startsWith('rgba')) ? 'checker' : ''}"><div style="background:${gradientCss(p)}"></div></div>
      <div class="legend-ticks">${ticks}</div>${missing}`;
    return;
  }
  el.innerHTML = model.groups.map((g) => `
    <div class="legend-caption">${g.title}</div>
    <div class="legend-classes">${g.items.map((it) => `
      <div class="legend-class"><i style="background:${toCss(it.color)}"></i><b>${escapeHtml(it.value)}</b><span>${escapeHtml(it.name)}</span></div>`).join('')}
    </div>`).join('') + missing + (model.groups.length ? '' : '<p class="muted">Loading classes…</p>');
}

const fmt = (v) => (Math.abs(v) >= 10 || Number.isInteger(v) ? String(Math.round(v * 10) / 10) : v.toFixed(1));

/** HTML de la tarjeta del campo según el modo (datos o incertidumbre). */
export function cardFor(view) {
  const layer = layerById(view.layerId);
  return view.uncertainty.on ? uncertaintyCard(view, layer) : cardHtml(view.card);
}
