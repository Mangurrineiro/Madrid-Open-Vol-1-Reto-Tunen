// Llamadas al backend con caché en memoria (una promesa por URL).
const mem = new Map();

async function json(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* cuerpo no JSON */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return r.json();
}

function cached(key, fn) {
  if (!mem.has(key)) {
    const p = fn();
    mem.set(key, p);
    p.catch(() => mem.delete(key));
  }
  return mem.get(key);
}

export const api = {
  demo: () => cached('demo', () => json('/soil/demo')),
  farmOutline: () => cached('fields.geojson', () => json('/fields.geojson')),
  layers: (fc) => json('/soil/layers', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fields: fc }),
  }),
  grid: (url) => cached(url, () => json(url)),
  points: (id) => cached(`points:${id}`, () => json(`/soil/fields/${encodeURIComponent(id)}/points`)),
  sampling: (id) => cached(`sampling:${id}`, () => json(`/soil/fields/${encodeURIComponent(id)}/sampling`)),
};
