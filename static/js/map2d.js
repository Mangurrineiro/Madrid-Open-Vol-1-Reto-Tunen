// Mapa Leaflet: satélite Esri, una imagen por campo (canvas del renderizador) y siluetas interactivas.
/* global L */

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ESRI_ATTR = 'Imagery © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community';

let map;
const overlays = new Map();     // field_id → L.imageOverlay (datos)
const shapes = new Map();       // field_id → L.GeoJSON (hover/clic)
let uncOverlay = null;          // incertidumbre del campo seleccionado
let selectedId = null;
let sampleLayer = null;

export function createMap(el) {
  map = L.map(el, { zoomControl: false, zoomSnap: 0.25, zoomDelta: 0.5, attributionControl: true });
  map.attributionControl.setPrefix(false);
  L.tileLayer(ESRI, { maxZoom: 20, maxNativeZoom: 19, attribution: ESRI_ATTR }).addTo(map);
  L.control.zoom({ position: 'bottomleft' }).addTo(map);
  map.createPane('layersPane').style.zIndex = 420;
  map.createPane('fieldsPane').style.zIndex = 450;
  map.createPane('samplesPane').style.zIndex = 640;
  map.setView([52.37, 11.05], 12);
  return map;
}

export const getMap = () => map;

/** bounds [[s,w],[n,e]] que cubre todos los campos. */
export function unionBounds(fields) {
  return L.latLngBounds(fields.map((f) => f.bounds[0]).concat(fields.map((f) => f.bounds[1])));
}

const PAD = () => ({ paddingTopLeft: [40, 130], paddingBottomRight: [(document.querySelector('#panel')?.offsetWidth || 360) + 60, 40] });

export function fitBounds(bounds, { animate = true, duration = 1.2 } = {}) {
  if (animate) map.flyToBounds(bounds, { ...PAD(), duration, easeLinearity: 0.2 });
  else map.fitBounds(bounds, PAD());
}

const labelHtml = (f) => `<b>${escapeHtml(f.name)}</b><span>${f.area_ha.toFixed(1)} ha</span>`;
const LABEL_OPTS = { sticky: true, direction: 'top', offset: [0, -10], className: 'field-label', opacity: 1 };

/** Siluetas interactivas por campo: resaltado, etiqueta con nombre y hectáreas, clic (campo, latlng). */
export function setFields(fields, { onClick } = {}) {
  for (const s of shapes.values()) s.remove();
  for (const o of overlays.values()) o.remove();
  shapes.clear(); overlays.clear();
  clearUncertainty();
  selectedId = null;
  for (const f of fields) {
    const layer = L.geoJSON(f.geometry, {
      pane: 'fieldsPane',
      style: { color: '#7CB342', weight: 0, opacity: 0, fillColor: '#ffffff', fillOpacity: 0 },
    });
    layer.bindTooltip(labelHtml(f), LABEL_OPTS);
    layer.on('mouseover', () => {
      if (f.field_id === selectedId) layer.closeTooltip();     // el seleccionado usa el tooltip de valores
      else layer.setStyle({ weight: 3, opacity: 1, fillOpacity: 0.06 });
    });
    layer.on('mouseout', () => layer.setStyle({ weight: 0, opacity: 0, fillOpacity: 0 }));
    layer.on('click', (e) => { L.DomEvent.stopPropagation(e); onClick && onClick(f, e.latlng); });
    layer.addTo(map);
    shapes.set(f.field_id, layer);
  }
}

/** Selección de campo: el resto se atenúa; el seleccionado pierde la etiqueta (usa el tooltip de valores). */
export function setSelected(id) {
  selectedId = id;
  for (const [fid, o] of overlays) o.setOpacity(id && fid !== id ? 0.25 : 1);
  const s = id && shapes.get(id);
  if (s) { s.closeTooltip(); s.setStyle({ weight: 0, opacity: 0, fillOpacity: 0 }); }
}

/** Pone (o sustituye) la imagen de un campo. */
export function setOverlay(fieldId, url, bounds) {
  const o = overlays.get(fieldId);
  if (o) { o.setUrl(url); return o; }
  const n = L.imageOverlay(url, bounds, { pane: 'layersPane', className: 'soil-overlay', interactive: false,
    opacity: selectedId && selectedId !== fieldId ? 0.25 : 1 });
  n.addTo(map);
  overlays.set(fieldId, n);
  return n;
}

/** Imagen de incertidumbre del campo seleccionado, superpuesta a la de datos. */
export function setUncertaintyOverlay(fieldId, url, bounds, visible) {
  if (uncOverlay && uncOverlay._fid !== fieldId) clearUncertainty();
  if (!uncOverlay) {
    uncOverlay = L.imageOverlay(url, bounds, { pane: 'layersPane', className: 'soil-overlay unc-overlay', interactive: false, opacity: 0 });
    uncOverlay._fid = fieldId;
    uncOverlay.addTo(map);
  } else uncOverlay.setUrl(url);
  showUncertainty(fieldId, visible);
}

/** Transición datos ↔ incertidumbre: solo opacity y filter (Leaflet usa transform para posicionar). */
export function showUncertainty(fieldId, on) {
  const data = overlays.get(fieldId)?.getElement();
  if (data) {
    data.style.opacity = on ? '0' : '1';
    data.style.filter = on ? 'blur(2px) saturate(0.6)' : 'none';
  }
  const el = uncOverlay?.getElement();
  if (el) requestAnimationFrame(() => { el.style.opacity = on ? '1' : '0'; });
}

export function clearUncertainty() {
  if (uncOverlay) {
    const data = overlays.get(uncOverlay._fid)?.getElement();
    if (data) { data.style.filter = 'none'; }
    uncOverlay.remove();
    uncOverlay = null;
  }
}

/** Marcadores de muestreo pulsantes y numerados; tooltip con el motivo. */
export function showSampling(points) {
  if (sampleLayer) { sampleLayer.remove(); sampleLayer = null; }
  if (!points?.length) return;
  sampleLayer = L.layerGroup(points.map((p, i) => L.marker([p.lat, p.lon], {
    pane: 'samplesPane',
    icon: L.divIcon({ className: 'sample-marker', html: `<span class="pulse"></span><span class="dot">${p.rank}</span>`,
      iconSize: [30, 30], iconAnchor: [15, 15] }),
  }).bindTooltip(`<b>Sampling point ${p.rank}${p.fieldName ? ` · ${escapeHtml(p.fieldName)}` : ''}</b><span>${escapeHtml(p.reason)}</span>`,
    { direction: 'top', offset: [0, -14], className: 'field-label sample-tip', opacity: 1 })
    .on('add', function () { this.getElement().style.animationDelay = `${(i % 12) * 40}ms`; })));
  sampleLayer.addTo(map);
}

export const overlayOf = (id) => overlays.get(id);
export const shapeOf = (id) => shapes.get(id);

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
