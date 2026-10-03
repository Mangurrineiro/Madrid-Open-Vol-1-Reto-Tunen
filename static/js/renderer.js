// Renderizador único: grid (filas norte→sur) → canvas ×8 recortado con la silueta del campo.
import { hatchPattern } from './palettes.js';

const SCALE = 8;
const CELL_M = 12.5;                 // resolución del grid JSON del backend
const cache = new Map();

/** Anillos [[lon,lat],...] de un Polygon o MultiPolygon. */
export function ringsOf(geometry) {
  if (!geometry) return [];
  if (geometry.type === 'Polygon') return geometry.coordinates;
  if (geometry.type === 'MultiPolygon') return geometry.coordinates.flat();
  return [];
}

/** Punto dentro (regla par-impar sobre todos los anillos: huecos y multipolígonos). */
export function pointInRings(lon, lat, rings) {
  let inside = false;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

/** Grid vacío (todo sin dato) con la resolución del backend, para campos sin capa. */
export function emptyGrid(bounds) {
  const [[s, w], [n, e]] = bounds;
  const mid = (s + n) / 2 * Math.PI / 180;
  const W = Math.max(1, Math.ceil((e - w) * 111320 * Math.cos(mid) / CELL_M));
  const H = Math.max(1, Math.ceil((n - s) * 110574 / CELL_M));
  return { bounds, width: W, height: H, values: Array.from({ length: H }, () => Array(W).fill(null)) };
}

/**
 * Las celdas del borde cuyo centro cae fuera del polígono vienen a null: toman el valor de
 * una vecina (como _fill_border del backend). Las de dentro sin dato se quedan null (rayado).
 */
function prepare(grid, rings) {
  const { width: W, height: H, values } = grid;
  const [[s, w], [n, e]] = grid.bounds;
  const inside = new Uint8Array(W * H);
  const vals = values.map((r) => r.slice());
  for (let r = 0; r < H; r++) {
    const lat = n - (r + 0.5) * (n - s) / H;
    for (let c = 0; c < W; c++) {
      const lon = w + (c + 0.5) * (e - w) / W;
      inside[r * W + c] = pointInRings(lon, lat, rings) ? 1 : 0;
    }
  }
  for (let pass = 0; pass < 2; pass++) {
    const cur = vals.map((r) => r.slice());
    for (let r = 0; r < H; r++) {
      for (let c = 0; c < W; c++) {
        if (inside[r * W + c] || cur[r][c] != null) continue;
        for (const [dr, dc] of [[0, 1], [0, -1], [1, 0], [-1, 0], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
          const v = cur[r + dr]?.[c + dc];
          if (v != null) { vals[r][c] = v; break; }
        }
      }
    }
  }
  return { vals, inside };
}

/**
 * renderLayer(grid, palette, fieldGeometry, options) → {canvas, getValue(lat, lon), dataUrl(), bounds}
 * options: {smooth, cacheKey, transform(v) → valor a colorear}
 */
export function renderLayer(grid, palette, fieldGeometry, options = {}) {
  const key = options.cacheKey;
  if (key && cache.has(key)) return cache.get(key);

  const rings = ringsOf(fieldGeometry);
  const { width: W, height: H } = grid;
  const [[s, w], [n, e]] = grid.bounds;
  const { vals, inside } = prepare(grid, rings);
  const tf = options.transform || ((v) => v);

  // Celdas a 1 px: color y máscara de "sin dato dentro del campo"
  const small = document.createElement('canvas');
  small.width = W; small.height = H;
  const sctx = small.getContext('2d');
  const img = sctx.createImageData(W, H);
  const mask = document.createElement('canvas');
  mask.width = W; mask.height = H;
  const mctx = mask.getContext('2d');
  const mimg = mctx.createImageData(W, H);
  let anyMissing = false;
  for (let r = 0; r < H; r++) {
    for (let c = 0; c < W; c++) {
      const v = vals[r][c];
      const k = (r * W + c) * 4;
      const col = v == null ? null : palette.color(tf(v));
      if (col) {
        img.data[k] = col[0]; img.data[k + 1] = col[1]; img.data[k + 2] = col[2];
        img.data[k + 3] = Math.round(255 * col[3]);
      } else if (v == null && inside[r * W + c]) {
        mimg.data[k + 3] = 255;
        anyMissing = true;
      }
    }
  }
  sctx.putImageData(img, 0, 0);
  mctx.putImageData(mimg, 0, 0);

  const canvas = document.createElement('canvas');
  canvas.width = W * SCALE; canvas.height = H * SCALE;
  const ctx = canvas.getContext('2d');
  const toPx = ([lon, lat]) => [(lon - w) / (e - w) * canvas.width, (n - lat) / (n - s) * canvas.height];
  const path = new Path2D();
  for (const ring of rings) {
    ring.forEach((pt, i) => { const [x, y] = toPx(pt); i ? path.lineTo(x, y) : path.moveTo(x, y); });
    path.closePath();
  }

  ctx.save();
  if (rings.length) ctx.clip(path, 'evenodd');
  if (anyMissing) {
    const hatch = document.createElement('canvas');
    hatch.width = canvas.width; hatch.height = canvas.height;
    const hctx = hatch.getContext('2d');
    hctx.fillStyle = hatchPattern(hctx);
    hctx.fillRect(0, 0, hatch.width, hatch.height);
    hctx.globalCompositeOperation = 'destination-in';
    hctx.imageSmoothingEnabled = false;
    hctx.drawImage(mask, 0, 0, hatch.width, hatch.height);
    ctx.drawImage(hatch, 0, 0);
  }
  ctx.imageSmoothingEnabled = !!options.smooth && palette.kind === 'num';
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(small, 0, 0, canvas.width, canvas.height);
  ctx.restore();

  ctx.lineWidth = 1.5;
  ctx.strokeStyle = 'rgba(255,255,255,0.85)';
  ctx.lineJoin = 'round';
  ctx.stroke(path);

  let url = null;
  const out = {
    canvas,
    bounds: grid.bounds,
    hasData: vals.some((r) => r.some((v) => v != null)),
    missing: anyMissing,
    dataUrl: () => (url ??= canvas.toDataURL('image/png')),
    getValue(lat, lon) {
      if (lat < s || lat > n || lon < w || lon > e) return null;
      if (rings.length && !pointInRings(lon, lat, rings)) return null;
      const r = Math.min(H - 1, Math.floor((n - lat) / (n - s) * H));
      const c = Math.min(W - 1, Math.floor((lon - w) / (e - w) * W));
      return vals[r][c];
    },
  };
  if (key) cache.set(key, out);
  return out;
}
