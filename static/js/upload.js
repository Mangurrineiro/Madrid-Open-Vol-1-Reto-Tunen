// Subida de GeoJSON: zona de arrastrar y soltar, validación en el navegador y pantalla de carga.

export function initDropzone(zone, input, onFile) {
  const accept = (f) => f && /\.(geo)?json$/i.test(f.name);
  zone.addEventListener('click', () => input.click());
  zone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  input.addEventListener('change', () => { if (input.files[0]) onFile(input.files[0]); input.value = ''; });
  for (const ev of ['dragenter', 'dragover']) {
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('over'); });
  }
  for (const ev of ['dragleave', 'drop']) {
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('over'); });
  }
  zone.addEventListener('drop', (e) => {
    const f = e.dataTransfer.files[0];
    if (!accept(f)) { setZoneMessage(zone, 'Please drop a .geojson or .json file.', true); return; }
    onFile(f);
  });
}

export function setZoneMessage(zone, text, kind = '') {
  const m = zone.querySelector('.drop-msg');
  if (!m) return;
  m.textContent = text;
  m.classList.toggle('error', kind === true || kind === 'error');
  m.classList.toggle('warning', kind === 'warning');
}

const GEOM_TYPES = ['Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon', 'GeometryCollection'];

function* coordsOf(geom) {
  if (!geom) return;
  const rings = geom.type === 'Polygon' ? geom.coordinates : geom.type === 'MultiPolygon' ? geom.coordinates.flat() : [];
  for (const r of rings) for (const p of r) yield p;
}

/**
 * Valida el texto de un archivo. Devuelve {ok, error?, warning?, fc?} con fc = FeatureCollection
 * solo con polígonos.
 */
export function validateGeojson(text) {
  let obj;
  try { obj = JSON.parse(text); } catch { return { ok: false, error: 'This file is not valid JSON.' }; }
  let features;
  if (obj?.type === 'FeatureCollection' && Array.isArray(obj.features)) features = obj.features;
  else if (obj?.type === 'Feature' && 'geometry' in obj) features = [obj];
  else if (GEOM_TYPES.includes(obj?.type)) features = [{ type: 'Feature', properties: {}, geometry: obj }];
  else return { ok: false, error: 'This file is not a GeoJSON.' };

  const polys = features.filter((f) => f && f.geometry && ['Polygon', 'MultiPolygon'].includes(f.geometry.type)
    && !(f.properties && f.properties.isArchived === true));
  if (!polys.length) {
    return { ok: false, error: 'This file contains points or lines, but we need field boundaries (polygons).' };
  }

  let outside = false;
  for (const f of polys) {
    for (const p of coordsOf(f.geometry)) {
      const [lon, lat] = p;
      if (typeof lon !== 'number' || typeof lat !== 'number' || Math.abs(lon) > 180 || Math.abs(lat) > 90
        || ((lat < 47 || lat > 56) && lon >= 47 && lon <= 56)) {
        return { ok: false, error: 'Coordinates look swapped or invalid. Expected longitude, latitude.' };
      }
      if (lon < 5.5 || lon > 15.5 || lat < 47 || lat > 55.5) outside = true;
    }
  }
  return {
    ok: true,
    fc: { type: 'FeatureCollection', features: polys },
    warning: outside ? 'Some fields are outside Germany: only global sources will be available.' : null,
  };
}

// ---------- pantalla de carga ----------
const STEPS = [
  ['Reading field boundaries', 0],
  ['Querying SoilGrids', 1.2],
  ['Querying LBEG (Lower Saxony)', 5],
  ['Querying BÜK200', 11],
  ['Combining sources and estimating uncertainty', 18],
  ['Rendering layers', 26],
];
const SLOW_S = 120;

/** Muestra la pantalla de carga y devuelve {done(), fail(msg)}. */
export function startLoading(el, { title, warning, onBack }) {
  el.innerHTML = `
    <div class="loading-card glass">
      <div class="eyebrow">Building your soil layers</div>
      <h2>${escape(title)}</h2>
      ${warning ? `<div class="loading-warning">${escape(warning)}</div>` : ''}
      <ol class="steps">${STEPS.map(([s]) => `<li><span class="step-icon"></span>${s}</li>`).join('')}</ol>
      <div class="loading-slow" hidden>Still working — public soil services can take a few minutes for new fields. Hang on…</div>
      <div class="loading-error" hidden></div>
      <button class="btn-ghost loading-back" hidden>Back to start</button>
    </div>`;
  el.classList.add('on');
  const items = [...el.querySelectorAll('.steps li')];
  const t0 = performance.now();
  const tick = () => {
    const t = (performance.now() - t0) / 1000;
    let cur = 0;
    STEPS.forEach(([, at], i) => { if (t >= at) cur = i; });
    items.forEach((li, i) => { li.className = i < cur ? 'done' : i === cur ? 'active' : ''; });
    if (t > SLOW_S) el.querySelector('.loading-slow').hidden = false;
  };
  tick();
  const timer = setInterval(tick, 250);
  el.querySelector('.loading-back').addEventListener('click', () => { el.classList.remove('on'); onBack && onBack(); });
  return {
    done() {
      clearInterval(timer);
      items.forEach((li) => { li.className = 'done'; });
      setTimeout(() => el.classList.remove('on'), 450);
    },
    fail(msg) {
      clearInterval(timer);
      const cur = items.findIndex((li) => li.className === 'active');
      if (cur >= 0) items[cur].className = 'failed';
      const e = el.querySelector('.loading-error');
      e.textContent = `Something went wrong: ${msg}`;
      e.hidden = false;
      el.querySelector('.loading-slow').hidden = true;
      el.querySelector('.loading-back').hidden = false;
    },
  };
}

const escape = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
