// Inspector: clic en un punto del campo → tarjeta con los valores de cada fuente en el punto más cercano.
/* global L */
import { escapeHtml, getMap } from './map2d.js';
import { KA5_NAMES, bsName, palette, toCss } from './palettes.js';
import { soilOrigin } from './tooltip.js';

let popup = null;
let marker = null;

const ROWS = [
  ['Clay', '%', { soilgrids: ['clay', 'soilgrids'], buek200: ['clay', 'buek200'], derived: ['clay', 'derived'] }],
  ['Sand', '%', { soilgrids: ['sand', 'soilgrids'], buek200: ['sand', 'buek200'], derived: ['sand', 'derived'] }],
  ['Silt', '%', { soilgrids: ['silt', 'soilgrids'], buek200: ['silt', 'buek200'], derived: ['silt', 'derived'] }],
  ['pH', '', { soilgrids: ['ph_h2o', 'soilgrids', 'H₂O'], buek200: ['ph_cacl2', 'buek200', 'CaCl₂'] }],
  ['Organic carbon', 'g/kg', { soilgrids: ['soc', 'soilgrids'], buek200: ['soc', 'buek200'], derived: ['soc', 'derived'] }],
  ['nFK', 'mm/dm', { soilgrids: ['nfk', 'soilgrids'], lbeg: ['nfk', 'lbeg'], derived: ['nfk', 'derived'] }],
  ['Bodenzahl', '', { lbeg: ['bodenzahl', 'lbeg'], derived: ['bodenzahl', 'derived'] }],
];
const COLS = [['soilgrids', 'SoilGrids'], ['lbeg', 'LBEG'], ['buek200', 'BÜK200'], ['derived', 'Combined']];

/** Punto de la rejilla más cercano (distancia equirrectangular). */
export function nearestPoint(points, lat, lon) {
  const k = Math.cos(lat * Math.PI / 180);
  let best = null, bd = Infinity;
  for (const p of points) {
    const d = ((p.lon - lon) * k) ** 2 + (p.lat - lat) ** 2;
    if (d < bd) { bd = d; best = p; }
  }
  return best;
}

const fmt = (v) => (v == null ? '—' : Number.isInteger(v) || Math.abs(v) >= 100 ? String(Math.round(v)) : (Math.round(v * 10) / 10).toFixed(1));

export function openInspector(point, field) {
  closeInspector();
  const map = getMap();
  const table = ROWS.map(([label, unit, cells]) => `
    <tr><th>${label}${unit ? ` <small>${unit}</small>` : ''}</th>${COLS.map(([src]) => {
      const c = cells[src];
      const v = c ? point.values[c[0]]?.[c[1]] : null;
      return `<td class="${src === 'derived' ? 'combined' : ''} ${v == null ? 'empty' : ''}">${fmt(v)}${v != null && c[2] ? `<sup>${c[2]}</sup>` : ''}</td>`;
    }).join('')}</tr>`).join('');

  const cl = point.classes || {};
  const origin = soilOrigin(point.klassenzeichen);
  const classes = `
    <div class="insp-classes">
      <div><span>Soil assessment</span><b>${cl.bodenart_bs ? `${escapeHtml(cl.bodenart_bs)} · ${escapeHtml(bsName(cl.bodenart_bs))}` : '—'}</b></div>
      <div><span>KA5 class</span><b>${cl.ka5_class ? `${escapeHtml(cl.ka5_class)} · ${escapeHtml(KA5_NAMES[cl.ka5_class] || '')}` : '—'}</b></div>
      <div><span>Soil type</span><b>${cl.soil_type ? escapeHtml(cl.soil_type) : '—'}</b></div>
      ${origin ? `<div><span>Parent material</span><b>${escapeHtml(origin)}</b></div>` : ''}
    </div>`;

  const cc = point.clay_conflict;
  const conflict = cc && cc.value > 0 ? `
    <div class="insp-conflict">
      <b>Physical contradiction</b>
      SoilGrids reports ${fmt(cc.soilgrids_clay)} % clay, but the official soil assessment class
      (${escapeHtml(cc.bodenart_bs)}) allows at most ${fmt(cc.feinanteil_max)} % fine particles.
    </div>` : '';

  const ri = point.reliability_index;
  const riColor = ri == null ? 'transparent' : toCss(palette('quality').color(ri));
  const reliability = `
    <div class="insp-rel">
      <span>Reliability index</span>
      <div class="rel-bar"><i style="width:${ri ?? 0}%;background:${riColor}"></i></div>
      <b style="color:${riColor}">${ri ?? '—'}</b>
    </div>`;

  const html = `
    <div class="insp-head"><b>${escapeHtml(field.name)}</b><span>Point ${point.point_id} · ${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}</span></div>
    <table class="insp-table"><thead><tr><th></th>${COLS.map(([, n]) => `<th>${n}</th>`).join('')}</tr></thead><tbody>${table}</tbody></table>
    ${classes}${conflict}${reliability}`;

  marker = L.circleMarker([point.lat, point.lon], { radius: 6, color: '#fff', weight: 2, fillColor: '#7CB342', fillOpacity: 1, pane: 'samplesPane' }).addTo(map);
  popup = L.popup({ className: 'inspector-popup', maxWidth: 440, minWidth: 380, autoPanPaddingTopLeft: [20, 120],
    autoPanPaddingBottomRight: [420, 20], offset: [0, -6] })
    .setLatLng([point.lat, point.lon]).setContent(html).openOn(map);
  popup.on('remove', () => { if (marker) { marker.remove(); marker = null; } });
}

export function closeInspector() {
  if (popup) { getMap().closePopup(popup); popup = null; }
  if (marker) { marker.remove(); marker = null; }
}
