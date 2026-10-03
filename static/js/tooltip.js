// Tooltip que sigue al cursor sobre el campo seleccionado.
import { escapeHtml } from './map2d.js';

let el;

export function initTooltip() {
  el = document.createElement('div');
  el.id = 'cursor-tip';
  el.className = 'glass';
  document.body.appendChild(el);
}

/** html: contenido ya escapado. x, y: coordenadas de ventana. */
export function showTip(x, y, html) {
  el.innerHTML = html;
  el.classList.add('on');
  const w = el.offsetWidth, h = el.offsetHeight;
  const left = x + 18 + w > window.innerWidth ? x - w - 18 : x + 18;
  const top = Math.max(8, y - h - 14);
  el.style.transform = `translate(${left}px, ${top}px)`;
}

export function hideTip() { el && el.classList.remove('on'); }

// ---------- origen del suelo (Klassenzeichen de la Bodenschätzung, p. ej. "Sl4D") ----------
const ORIGIN = { D: 'glacial deposits (Diluvium)', Al: 'river deposits (Alluvium)', 'Lö': 'loess', Lo: 'loess',
  V: 'weathered bedrock', Vg: 'stony weathered bedrock' };

export function soilOrigin(klassenzeichen) {
  const m = String(klassenzeichen || '').match(/\d([A-Za-zÄÖÜäöü]+)$/);
  if (!m) return null;
  const code = m[1];
  if (ORIGIN[code]) return ORIGIN[code];
  const parts = code.match(/Al|Lö|Lo|Vg|V|D/g);
  return parts ? parts.map((p) => ORIGIN[p]).join(' + ') : null;
}

export const line = (label, value, cls = '') => `<div class="tip-row ${cls}"><span>${escapeHtml(label)}</span><b>${value}</b></div>`;
