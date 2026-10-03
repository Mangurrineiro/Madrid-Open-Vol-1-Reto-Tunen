// Terreno (módulo adicional): relieve sombreado, grupo "Terrain" del panel, tarjeta "Field terrain",
// textos del tooltip y sección del inspector. Si el backend no envía capas de terreno, nada de esto aparece.
/* global L */
import { escapeHtml, getMap } from './map2d.js';
import { ASPECT_COLORS, ASPECT_NAMES } from './palettes.js';

let bg = null;          // hillshade de toda la granja (vista de granja)
let fieldHs = null;     // hillshade del campo seleccionado (vista de campo, multiply)
let cssDone = false;

function ensureCss() {
  if (cssDone) return;
  cssDone = true;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = '/static/css/terrain.css';
  document.head.appendChild(l);
}

export const hillshadeOf = (field) => field?.layers?.find((l) => l.source === 'copernicus_dem' && l.parameter === 'hillshade'
  && l.status === 'ok' && l.png_url) || null;

/** Hay algo de terreno en los datos (capas, fondo o resumen). */
export const hasTerrain = (data) => !!data && (!!data.terrain_background || data.fields.some((f) => f.terrain || hillshadeOf(f)));

function fade(o, v) {
  if (!o) return;
  requestAnimationFrame(() => requestAnimationFrame(() => o.setOpacity(v)));
}

/** Relieve sombreado: fondo en la vista de granja, hillshade del campo (multiply) en la vista de campo. */
export function setRelief({ on, view, data, field }) {
  if (!hasTerrain(data)) return;
  ensureCss();
  const map = getMap();
  if (!map.getPane('reliefPane')) map.createPane('reliefPane').style.zIndex = 410;   // entre satélite y capas
  const info = data.terrain_background;
  if (info && !bg) {
    bg = L.imageOverlay(info.png_url, info.bounds, { pane: 'reliefPane', className: 'relief-bg', interactive: false, opacity: 0 });
    bg.addTo(map);
  }
  fade(bg, on && view === 'farm' ? 0.45 : 0);

  const hs = view === 'field' ? hillshadeOf(field) : null;
  if (fieldHs && (!hs || fieldHs._fid !== field.field_id)) {
    const old = fieldHs;
    fieldHs = null;
    old.setOpacity(0);
    setTimeout(() => old.remove(), 320);
  }
  if (hs && !fieldHs) {
    fieldHs = L.imageOverlay(hs.png_url, hs.bounds || field.bounds, { pane: 'layersPane', className: 'relief-overlay',
      interactive: false, opacity: 0 });
    fieldHs._fid = field.field_id;
    fieldHs.addTo(map);
  }
  if (fieldHs) {
    fieldHs.bringToFront();
    fade(fieldHs, on ? 0.55 : 0);
  }
}

export function resetRelief() {
  if (bg) { bg.remove(); bg = null; }
  if (fieldHs) { fieldHs.remove(); fieldHs = null; }
}

// ---------- panel ----------
export function reliefSwitch(on) {
  return `<section class="panel-section relief-row">
    <label class="switch relief-switch ${on ? 'on' : ''}" data-action="relief" id="relief-toggle">
      <span class="switch-track"><span class="switch-knob"></span></span>
      <span class="switch-label">Relief shading</span><kbd>R</kbd>
    </label></section>`;
}

export const reliefNote = () => '<div class="relief-note">Relief shading: vertical exaggeration ×3</div>';

const signed = (n) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : '0');
const r1 = (v) => (Math.round(v * 10) / 10).toFixed(1);

/** Rosa de los vientos de 8 sectores; resalta el dominante (o el centro si es "Flat"). */
function compass(dominant) {
  const cx = 34, cy = 34, r0 = 8, r1o = 27;
  const pt = (a, r) => [cx + r * Math.sin(a * Math.PI / 180), cy - r * Math.cos(a * Math.PI / 180)];
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const wedges = dirs.map((d, i) => {
    const a = i * 45;
    const [x1, y1] = pt(a - 21, r1o), [x2, y2] = pt(a + 21, r1o), [x3, y3] = pt(a + 21, r0), [x4, y4] = pt(a - 21, r0);
    const on = d === dominant;
    return `<path d="M${x4.toFixed(1)} ${y4.toFixed(1)}L${x1.toFixed(1)} ${y1.toFixed(1)}A${r1o} ${r1o} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}L${x3.toFixed(1)} ${y3.toFixed(1)}A${r0} ${r0} 0 0 0 ${x4.toFixed(1)} ${y4.toFixed(1)}Z"
      fill="${on ? ASPECT_COLORS[d] : 'rgba(255,255,255,0.08)'}" stroke="rgba(255,255,255,0.18)" stroke-width="0.6"/>`;
  }).join('');
  const flat = dominant === 'Flat';
  const [nx, ny] = pt(0, 33);
  return `<svg class="compass" viewBox="-2 -6 72 76" width="72" height="76" aria-label="Dominant aspect ${escapeHtml(dominant || '—')}">
    ${wedges}<circle cx="${cx}" cy="${cy}" r="${r0 - 1.5}" fill="${flat ? ASPECT_COLORS.Flat : 'rgba(255,255,255,0.06)'}"/>
    <text x="${nx}" y="${ny}" text-anchor="middle" font-size="8" font-weight="700" fill="currentColor">N</text></svg>`;
}

/** Tarjeta "Field terrain" (resumen del backend: field.terrain). */
export function terrainCard(t) {
  if (!t) return '';
  const row = (k, v) => `<div class="tr-row"><span>${k}</span><b class="num">${v}</b></div>`;
  return `<section class="panel-section terrain-card">
    <h2 class="panel-title">Field terrain</h2>
    <div class="tr-body">
      <div class="tr-rows">
        ${row('Elevation', `${Math.round(t.elev_min)}–${Math.round(t.elev_max)} m`)}
        ${row('Local relief', `${r1(t.local_relief)} m`)}
        ${row('Mean slope', t.slope_mean != null ? `${r1(t.slope_mean)}°` : '—')}
        ${row('Slope (95th pct)', t.slope_p95 != null ? `${r1(t.slope_p95)}°` : '—')}
        ${row('Dominant aspect', escapeHtml(ASPECT_NAMES[t.dominant_aspect] || t.dominant_aspect || '—'))}
      </div>
      ${compass(t.dominant_aspect)}
    </div>
    <p class="note tr-note">${t.slope_edge_buffer_m
    ? `Slope figures leave out a ${t.slope_edge_buffer_m} m strip along the field edge, where hedges and trees in the surface model add apparent slope (whole field: mean ${r1(t.slope_mean_all)}°, 95th pct ${r1(t.slope_p95_all)}°).`
    : 'Surface model: trees and hedges at field edges can add apparent slope.'}</p>
  </section>`;
}

// ---------- tooltip ----------
/** Tooltip de las capas de terreno. elevAbs: elevación absoluta en el punto (grid "elevation"). */
export function terrainTip(layerId, v, elevAbs) {
  if (layerId === 'elevation') {
    const abs = elevAbs != null ? `Elevation <b>${Math.round(elevAbs)} m</b> · ` : '';
    return `<div class="tip-main">${abs}<b>${r1(v)} m</b> above field low point</div>`;
  }
  if (layerId === 'slope') return `<div class="tip-main">Slope <b>${r1(v)}°</b></div>`;
  if (layerId === 'aspect') {
    return `<div class="tip-main"><span class="swatch" style="background:${ASPECT_COLORS[v] || '#BDBDBD'}"></span>${v === 'Flat' ? '<b>Flat</b> terrain' : `Facing <b>${escapeHtml(v)}</b>`}</div>`;
  }
  return null;
}

/** "Bodenzahl 68 → Ackerzahl 61 (−7)" */
export function ackerLine(bz, az) {
  if (bz == null || az == null) return null;
  return `Bodenzahl ${Math.round(bz)} → Ackerzahl ${Math.round(az)} (${signed(Math.round(az - bz))})`;
}

// ---------- inspector ----------
export function terrainInspector(point) {
  if (!('elevation' in point) && !('acker_delta' in point)) return '';
  const rows = [];
  if (point.elevation != null) {
    rows.push(['Elevation', `${Math.round(point.elevation)} m${point.elevation_rel != null ? ` · ${r1(point.elevation_rel)} m above field low point` : ''}`]);
  }
  if (point.slope != null) rows.push(['Slope', `${r1(point.slope)}°`]);
  if (point.aspect != null) rows.push(['Aspect', point.aspect === 'Flat' ? 'Flat' : `Facing ${escapeHtml(point.aspect)}`]);
  const line = point.acker_delta != null ? ackerLine(point.values?.bodenzahl?.lbeg, point.values?.ackerzahl?.lbeg) : null;
  if (line) rows.push(['Soil score', line]);
  if (!rows.length) return '';
  return `<div class="insp-terrain"><div class="insp-terrain-title">Terrain</div>
    ${rows.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('')}</div>`;
}
