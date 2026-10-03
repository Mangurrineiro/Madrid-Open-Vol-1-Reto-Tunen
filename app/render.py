"""
Render de una capa (campo × fuente × parámetro) a PNG coloreado + grid JSON para el hover.

- Imagen en EPSG:4326 alineada con los bounds del campo (lo que espera L.imageOverlay).
- Cada píxel se pasa a EPSG:25832 y toma el valor de su celda de 25 m de la rejilla común
  (los puntos están en floor(x/25)*25 + 12,5). Transparente fuera del polígono y sin dato.
- PNG fino (~3 m/píxel) para bordes limpios; grid JSON más grueso (~12,5 m/píxel).
- Numéricos: colormap fijo por parámetro. Texto (bodenart_bs, soil_type): categorías tab20.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

import numpy as np
import shapely
from matplotlib import colormaps
from PIL import Image

from .config import PARAMETERS, RENDERS
from .fields import TO_UTM, Field

PNG_PX_M = 3.0
GRID_PX_M = 12.5
MAX_PX = 1400


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


def _raster(field: Field, cells: np.ndarray, ix0: int, iy0: int, px_m: float):
    """Muestrea el array de celdas (filas = iy) en una imagen 4326 sobre los bounds del campo."""
    lon_w, lat_s, lon_e, lat_n = field.geom.bounds
    mid_lat = np.radians((lat_s + lat_n) / 2)
    w_m = (lon_e - lon_w) * 111_320 * np.cos(mid_lat)
    h_m = (lat_n - lat_s) * 110_574
    W = int(np.clip(np.ceil(w_m / px_m), 1, MAX_PX))
    H = int(np.clip(np.ceil(h_m / px_m), 1, MAX_PX))
    lons = lon_w + (np.arange(W) + 0.5) * (lon_e - lon_w) / W
    lats = lat_n - (np.arange(H) + 0.5) * (lat_n - lat_s) / H
    LON, LAT = np.meshgrid(lons, lats)
    inside = shapely.contains_xy(field.geom, LON.ravel(), LAT.ravel()).reshape(H, W)
    x, y = TO_UTM.transform(LON.ravel(), LAT.ravel())
    step = field.grid.step
    ix = np.floor(np.asarray(x) / step).astype(int) - ix0
    iy = np.floor(np.asarray(y) / step).astype(int) - iy0
    ok = (ix >= 0) & (ix < cells.shape[1]) & (iy >= 0) & (iy < cells.shape[0])
    out = np.full(H * W, np.nan)
    out[ok] = cells[iy[ok], ix[ok]]
    out = out.reshape(H, W)
    out[~inside] = np.nan
    return out, W, H


def _fill_border(cells: np.ndarray, exists: np.ndarray, rings: int = 2) -> np.ndarray:
    """Celdas sin punto de rejilla (borde del polígono) toman el valor de una vecina.

    Así los píxeles del borde no quedan transparentes en escalera. Las celdas con punto
    pero sin dato (no_coverage) no se tocan.
    """
    out = np.pad(cells, rings, constant_values=np.nan)
    ex = np.pad(exists, rings, constant_values=False)
    for _ in range(rings):
        cur = out.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nb = np.roll(np.roll(cur, dy, 0), dx, 1)
            take = ~ex & np.isnan(out) & ~np.isnan(nb)
            out[take] = nb[take]
    return out[rings:-rings, rings:-rings]


def render_layer(field: Field, rows: list[dict], source: str, parameter: str,
                 vmin: float | None = None, vmax: float | None = None, cmap: str | None = None) -> dict:
    meta = PARAMETERS[parameter]
    g = field.grid
    step = g.step
    ok_rows = [r for r in rows if r["status"] == "ok" and r["value"] is not None]
    numeric = all(isinstance(r["value"], (int, float)) for r in ok_rows)

    # Valores por punto -> códigos numéricos (categorías si es texto)
    categories: list[str] = []
    vals = np.full(len(g), np.nan)
    if numeric:
        for r in ok_rows:
            vals[r["point_id"]] = r["value"]
    else:
        categories = [c for c, _ in Counter(str(r["value"]) for r in ok_rows).most_common()]
        code = {c: i for i, c in enumerate(categories)}
        for r in ok_rows:
            vals[r["point_id"]] = code[str(r["value"])]

    gx = np.floor(g.x / step).astype(int)
    gy = np.floor(g.y / step).astype(int)
    ix0, iy0 = gx.min(), gy.min()
    cells = np.full((gy.max() - iy0 + 1, gx.max() - ix0 + 1), np.nan)
    cells[gy - iy0, gx - ix0] = vals
    exists = np.zeros(cells.shape, bool)
    exists[gy - iy0, gx - ix0] = True
    cells = _fill_border(cells, exists)

    # --- PNG ---
    img, W, H = _raster(field, cells, ix0, iy0, PNG_PX_M)
    if numeric:
        lo = meta["min"] if vmin is None else vmin
        hi = meta["max"] if vmax is None else vmax
        name = cmap or meta["cmap"]
        norm = np.clip((img - lo) / ((hi - lo) or 1), 0, 1)
    else:
        lo, hi, name = 0, max(len(categories) - 1, 0), "tab20"
        norm = (img % 20) / 19
    rgba = (colormaps[name](np.nan_to_num(norm)) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(np.isnan(img), 0, 235)

    # --- grid JSON (hover) ---
    gimg, GW, GH = _raster(field, cells, ix0, iy0, GRID_PX_M)
    if numeric:
        gvals = [[None if np.isnan(v) else round(float(v), 2) for v in rowv] for rowv in gimg]
    else:
        gvals = [[None if np.isnan(v) else categories[int(v)] for v in rowv] for rowv in gimg]
    lon_w, lat_s, lon_e, lat_n = field.geom.bounds
    grid = {"bounds": [[lat_s, lon_w], [lat_n, lon_e]], "width": GW, "height": GH,
            "parameter": parameter, "source": source, "unit": meta["unit"], "values": gvals}

    d = RENDERS / safe(field.field_id)
    d.mkdir(parents=True, exist_ok=True)
    base = f"{safe(source)}_{safe(parameter)}"
    Image.fromarray(rgba, "RGBA").save(d / f"{base}.png", optimize=True)
    grid_txt = json.dumps(grid, separators=(",", ":"), ensure_ascii=False)
    (d / f"{base}.json").write_text(grid_txt, encoding="utf-8")
    v = hashlib.sha1(grid_txt.encode()).hexdigest()[:10]

    colormap = {"name": name, "min": lo, "max": hi}
    if categories:
        cm = colormaps["tab20"]
        colormap["categories"] = [{"value": c, "color": "#%02x%02x%02x" % tuple(int(255 * x) for x in cm((i % 20) / 19)[:3])}
                                  for i, c in enumerate(categories)]
    return {
        "png_url": f"/renders/{safe(field.field_id)}/{base}.png?v={v}",
        "grid_url": f"/renders/{safe(field.field_id)}/{base}.json?v={v}",
        "colormap": colormap,
        "size": [W, H],
    }


def layer_stats(rows: list[dict]) -> dict:
    n = len(rows)
    ok = [r["value"] for r in rows if r["status"] == "ok" and r["value"] is not None]
    num = [v for v in ok if isinstance(v, (int, float))]
    st = {"min": None, "mean": None, "max": None,
          "coverage_pct": round(100 * len(ok) / n, 1) if n else 0.0}
    if num and len(num) == len(ok):
        st.update(min=round(min(num), 2), mean=round(float(np.mean(num)), 2), max=round(max(num), 2))
    elif ok:
        st["categories"] = dict(Counter(map(str, ok)).most_common())
    return st


def layer_status(rows: list[dict]) -> str:
    st = Counter(r["status"] for r in rows)
    if st.get("ok"):
        return "ok"
    return "no_coverage" if st.get("no_coverage") else ("error" if st.get("error") else "no_coverage")
