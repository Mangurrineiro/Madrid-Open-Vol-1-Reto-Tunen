// Mapa Leaflet: satélite Esri, una imagen por campo (canvas del renderizador) y siluetas interactivas.
/* global L */

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ESRI_ATTR = 'Imagery © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community';

let map;
const overlays = new Map();     // field_id → L.imageOverlay
const shapes = new Map();       // field_id → L.GeoJSON (hover/clic)

export function createMap(el) {
  map = L.map(el, { zoomControl: false, zoomSnap: 0.25, zoomDelta: 0.5, preferCanvas: false, attributionControl: true });
  map.attributionControl.setPrefix(false);
  L.tileLayer(ESRI, { maxZoom: 20, maxNativeZoom: 19, attribution: ESRI_ATTR }).addTo(map);
  L.control.zoom({ position: 'bottomleft' }).addTo(map);
  map.createPane('layersPane').style.zIndex = 420;
  map.createPane('fieldsPane').style.zIndex = 450;
  map.setView([52.37, 11.05], 12);
  return map;
}

export const getMap = () => map;

/** bounds [[s,w],[n,e]] que cubre todos los campos. */
export function unionBounds(fields) {
  const b = L.latLngBounds(fields.map((f) => f.bounds[0]).concat(fields.map((f) => f.bounds[1])));
  return b;
}

export function fitBounds(bounds, { animate = true, duration = 1.2, padRight = 380 } = {}) {
  const opts = { paddingTopLeft: [40, 90], paddingBottomRight: [padRight + 40, 40] };
  if (animate) map.flyToBounds(bounds, { ...opts, duration, easeLinearity: 0.2 });
  else map.fitBounds(bounds, opts);
}

/** Siluetas interactivas por campo: resaltado, etiqueta con nombre y hectáreas, clic. */
export function setFields(fields, { onClick } = {}) {
  for (const s of shapes.values()) s.remove();
  for (const o of overlays.values()) o.remove();
  shapes.clear(); overlays.clear();
  for (const f of fields) {
    const layer = L.geoJSON(f.geometry, {
      pane: 'fieldsPane',
      style: { color: '#7CB342', weight: 0, opacity: 0, fillColor: '#ffffff', fillOpacity: 0 },
    });
    layer.bindTooltip(`<b>${escapeHtml(f.name)}</b><span>${f.area_ha.toFixed(1)} ha</span>`,
      { sticky: true, direction: 'top', offset: [0, -10], className: 'field-label', opacity: 1 });
    layer.on('mouseover', () => layer.setStyle({ weight: 3, opacity: 1, fillOpacity: 0.06 }));
    layer.on('mouseout', () => layer.setStyle({ weight: 0, opacity: 0, fillOpacity: 0 }));
    layer.on('click', () => onClick && onClick(f));
    layer.addTo(map);
    shapes.set(f.field_id, layer);
  }
}

/** Pone (o sustituye) la imagen de un campo. */
export function setOverlay(fieldId, url, bounds) {
  const o = overlays.get(fieldId);
  if (o) { o.setUrl(url); return o; }
  const n = L.imageOverlay(url, bounds, { pane: 'layersPane', className: 'soil-overlay', interactive: false });
  n.addTo(map);
  overlays.set(fieldId, n);
  return n;
}

export const overlayOf = (id) => overlays.get(id);
export const shapeOf = (id) => shapes.get(id);

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
