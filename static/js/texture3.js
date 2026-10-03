// Fase 2 · Desglose de textura en tres paneles (Clay, Sand, Silt) con cursor sincronizado
// y transición independiente a la incertidumbre de cada fracción.
import { api } from './api.js';
import { findLayer } from './catalog.js';
import { escapeHtml } from './map2d.js';
import { gradientCss, palette } from './palettes.js';
import { emptyGrid, renderLayer } from './renderer.js';
import { farmScale, uncertaintyGrid, uncertaintyText } from './uncertainty.js';

const FRACTIONS = [['clay', 'Clay'], ['sand', 'Sand'], ['silt', 'Silt']];
let view = null;

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

// "Capa" mínima por fracción para reutilizar uncertainty.js
const pseudoLayer = (p) => ({ id: `bd-${p}`, name: p, uncertainty: { spread: [`${p}_disagreement`], sigma: [`${p}_sigma`], unit: '%' } });

function legendHtml(p, ref) {
  const span = p.max - p.min;
  const ticks = p.ticks.map((t) => `<span style="left:${((t - p.min) / span * 100).toFixed(1)}%">${ref ? (t * ref).toFixed(0) : t}</span>`).join('');
  return `<div class="legend-bar ${ref ? 'checker' : ''}"><div style="background:${gradientCss(p)}"></div></div><div class="legend-ticks">${ticks}</div>`;
}

/** ctx: {panel, fields, onClose()} */
export async function open(field, ctx) {
  close(true);
  const host = document.createElement('section');
  host.id = 'breakdown-view';
  host.innerHTML = `<div class="stack-bg"></div>
    <div class="bd-head">
      <div><div class="eyebrow">Texture breakdown</div><h2>${escapeHtml(field.name)}</h2>
        <p class="note">Same scale, same field boundary. Move the cursor to compare; click a panel to see where the sources disagree.</p></div>
    </div>
    <div class="bd-row">${FRACTIONS.map(([p, name]) => `
      <article class="bd-panel glass" data-p="${p}">
        <div class="bd-title"><h3>${name}</h3><span class="bd-mode">Combined</span></div>
        <div class="bd-canvas"><div class="bd-frame"><i class="bd-cross-x"></i><i class="bd-cross-y"></i><div class="bd-value"></div></div></div>
        <div class="bd-stats"><div class="skeleton"></div></div>
      </article>`).join('')}</div>`;
  document.body.appendChild(host);
  view = { host, field, ctx, panels: {} };
  requestAnimationFrame(() => host.classList.add('on'));

  const results = await Promise.all(FRACTIONS.map(async ([p, name]) => {
    const meta = findLayer(field, 'derived', p) || findLayer(field, 'soilgrids', p) || findLayer(field, 'buek200', p);
    let grid = null;
    try { grid = meta ? await api.grid(meta.grid_url) : null; } catch { grid = null; }
    const pal = palette(p);
    const data = renderLayer(grid || emptyGrid(field.bounds), pal, field.geometry, {
      smooth: true, cacheKey: `${field.field_id}|texture|${meta?.source || 'derived'}|${p}|data`,
    });
    return { p, name, meta, pal, data };
  }));
  if (!view || view.host !== host) return;

  for (const r of results) {
    const el = host.querySelector(`.bd-panel[data-p="${r.p}"]`);
    const st = r.meta?.stats || {};
    el.querySelector('.bd-stats').innerHTML = r.meta ? `
      <div class="stat-label">Mean ${r.name.toLowerCase()}</div>
      <div class="big num">${st.mean?.toFixed(1) ?? '—'}<small> %</small></div>
      <div class="minmax"><span>Min <b class="num">${st.min?.toFixed(1) ?? '—'}</b></span><span>Max <b class="num">${st.max?.toFixed(1) ?? '—'}</b></span>
        <span class="muted">${r.meta.source === 'derived' ? 'Combined' : r.meta.source}</span></div>
      <div class="bd-legend">${legendHtml(r.pal)}</div>
      <div class="bd-hint">Click to show uncertainty</div>` : '<div class="unc-na">No data for this field.</div>';
    view.panels[r.p] = { ...r, el, unc: null, on: false };
    el.addEventListener('click', () => toggle(r.p));
  }
  layout();
  view.onResize = () => layout();
  window.addEventListener('resize', view.onResize);
  host.querySelectorAll('.bd-frame').forEach((fr) => {
    fr.addEventListener('mousemove', (e) => {
      const b = fr.getBoundingClientRect();
      cross((e.clientX - b.left) / b.width, (e.clientY - b.top) / b.height);
    });
    fr.addEventListener('mouseleave', () => cross(null));
  });

  // Incertidumbre precargada para que el clic sea instantáneo
  for (const r of results) {
    const lay = pseudoLayer(r.p);
    const scale = await farmScale(lay, ctx.fields);
    const { grid, available } = await uncertaintyGrid(lay, field, scale, null);
    if (!view || view.host !== host) return;
    const render = renderLayer(grid, palette('alert'), field.geometry, { smooth: true, transform: (v) => v.u });
    const P = view.panels[r.p];
    P.unc = { render, available, ref: scale?.spread };
    const c = document.createElement('canvas');
    c.className = 'unc-c';
    c.width = render.canvas.width; c.height = render.canvas.height;
    c.getContext('2d').drawImage(render.canvas, 0, 0);
    P.el.querySelector('.bd-frame').prepend(c);
  }
  host.dataset.ready = '1';
}

/** Mismo tamaño de canvas en los tres paneles, ajustado al hueco disponible. */
function layout() {
  const panels = Object.values(view.panels);
  if (!panels.length) return;
  const box = panels[0].el.querySelector('.bd-canvas').getBoundingClientRect();
  const c0 = panels[0].data.canvas;
  const ratio = c0.width / c0.height;
  let w = box.width, h = w / ratio;
  if (h > box.height) { h = box.height; w = h * ratio; }
  for (const P of panels) {
    const fr = P.el.querySelector('.bd-frame');
    fr.style.width = `${w}px`;
    fr.style.height = `${h}px`;
    if (!fr.querySelector('canvas.data-c')) {
      const c = document.createElement('canvas');
      c.className = 'data-c';
      c.width = P.data.canvas.width; c.height = P.data.canvas.height;
      c.getContext('2d').drawImage(P.data.canvas, 0, 0);
      fr.prepend(c);
    }
  }
}

/** Cruz sincronizada: misma posición relativa en los tres paneles y su valor. */
function cross(fx, fy) {
  for (const P of Object.values(view.panels)) {
    const fr = P.el.querySelector('.bd-frame');
    if (fx == null) { fr.classList.remove('cross'); continue; }
    fr.classList.add('cross');
    fr.querySelector('.bd-cross-x').style.top = `${fy * 100}%`;
    fr.querySelector('.bd-cross-y').style.left = `${fx * 100}%`;
    const [[s, w], [n, e]] = P.data.bounds;
    const lat = n - fy * (n - s), lon = w + fx * (e - w);
    let txt;
    if (P.on) {
      txt = P.unc?.available ? uncertaintyText(pseudoLayer(P.p), P.unc.render.getValue(lat, lon)) : 'Uncertainty not available';
    } else {
      const v = P.data.getValue(lat, lon);
      txt = v == null ? 'Outside the field' : `${P.name} ${v.toFixed(1)} %`;
    }
    fr.querySelector('.bd-value').textContent = txt;
  }
}

function toggle(p) {
  const P = view?.panels[p];
  if (!P || !P.meta) return;
  P.on = !P.on;
  P.el.classList.toggle('unc', P.on);
  P.el.querySelector('.bd-mode').textContent = P.on ? 'Disagreement' : 'Combined';
  const lg = P.el.querySelector('.bd-legend');
  if (lg) lg.innerHTML = P.on && P.unc?.available ? legendHtml(palette('alert'), P.unc.ref) : legendHtml(P.pal);
  const hint = P.el.querySelector('.bd-hint');
  if (hint) hint.textContent = P.on ? 'Disagreement between sources, in % points · click to go back' : 'Click to show uncertainty';
}

export function close(immediate = false) {
  if (!view) return;
  const v = view;
  view = null;
  window.removeEventListener('resize', v.onResize);
  if (immediate) v.host.remove();
  else { v.host.classList.remove('on'); setTimeout(() => v.host.remove(), 420); }
  if (!immediate) v.ctx.onClose && v.ctx.onClose();
}
