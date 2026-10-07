"""
Copernicus DEM GLO-30 (~30 m, global). Módulo adicional de terreno (config.ENABLE_TERRAIN).

- Localización de los COG: Earth Search STAC (colección cop-dem-glo-30, asset "data", href s3://)
  y, si falla, la URL directa del bucket público (tesela = floor de la esquina SW):
  https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N52_00_E011_00_DEM/...tif
- Una sola lectura por petición: prepare(fields) lee la caja que une todos los campos + 300 m
  (+ halo de 2 píxeles DEM) por ventana con rasterio (nunca la tesela entera), mosaico con
  rasterio.merge si cruza teselas, y guarda el recorte como GeoTIFF en data/cache/copernicus_dem.
  Cualquier recorte ya en caché que cubra la caja pedida se reutiliza sin tocar la red.
- Cálculos en EPSG:4326 sin reproyectar; píxel métrico dy = |res_lat|·111320,
  dx = res_lon·111320·cos(lat_centro). Filas N→S, por eso dz_dy = −dz_drow/dy.
  slope = atan(|∇z|); aspect = dirección hacia la que BAJA el terreno (0° = N, horario);
  clases de 45°, "Flat" si slope < 0,5°.
- Muestreo en la rejilla común: bilinear para elevation y slope; vecino más cercano para aspect.
  elevation_rel = elevation − mínimo del campo.
- Hillshade (solo PNG): rejilla 5× más fina que la común sobre los bounds exactos del campo,
  DEM interpolado bilinear, azimut 315°, altitud 45°, z-factor 3. Y un fondo de toda la caja
  de la petición, sin recortar, con fundido a transparente en los bordes.
- Las capas de terreno NO entran en derived ni en sampling_priority (derived solo combina
  clay/sand/silt/soc/nfk).
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import Counter

import numpy as np
import rasterio
import shapely
from matplotlib import colormaps
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.merge import merge

from .. import cache
from ..config import DEMO_CACHE, RENDERS
from .base import Source, register_source, row

NAME = "copernicus_dem"
STAC_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "cop-dem-glo-30"
S3_HTTPS = "https://copernicus-dem-30m.s3.amazonaws.com/"
TILE_URL = (S3_HTTPS + "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
            "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif")
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_TIMEOUT="60", GDAL_HTTP_MAX_RETRY="2")
MARGIN_M = 300.0
HALO_PX = 2
M_PER_DEG = 111_320.0
FLAT_DEG = 0.5
ASPECTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
ASPECT_COLORS = {"N": "#4575B4", "NE": "#74ADD1", "E": "#ABD9E9", "SE": "#FEE090", "S": "#FDAE61",
                 "SW": "#F46D43", "W": "#D73027", "NW": "#8073AC", "Flat": "#BDBDBD"}
ELEV_SIGMA = 2.0          # m: precisión vertical relativa declarada
HS_AZIMUTH, HS_ALTITUDE, HS_Z = 315.0, 45.0, 3.0
HS_FINE = 5               # hillshade: rejilla 5× más fina que la común
BG_FADE = 0.08            # fondo: fundido en el 8 % exterior de cada borde
SLOPE_SCALE_MIN = 3.0

# ---------- colormaps propios (registrados en matplotlib: render.py y /legend los usan) ----------
_CMAPS = {
    "tunen_elevation": ["#1B5E20", "#7CB342", "#F2D24B", "#C99A4E", "#8A5A2B"],
    "tunen_slope": ["#FFFFFF", "#FDD49E", "#EF6548", "#7F0000"],
    "tunen_acker_delta": ["#C62828", "#FFF59D", "#2E7D32"],
}
for _n, _c in _CMAPS.items():
    if _n not in colormaps:
        colormaps.register(LinearSegmentedColormap.from_list(_n, _c))


# ---------- cálculos puros (también los usa la prueba sintética) ----------
def derivatives(dem: np.ndarray, dx: float, dy: float) -> tuple[np.ndarray, np.ndarray]:
    """dz/dx (positivo hacia el este) y dz/dy (positivo hacia el norte) de un array con filas N→S."""
    dz_drow, dz_dcol = np.gradient(dem)
    return dz_dcol / dx, -dz_drow / dy


def slope_aspect(dem: np.ndarray, dx: float, dy: float) -> tuple[np.ndarray, np.ndarray]:
    dz_dx, dz_dy = derivatives(dem, dx, dy)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    aspect = (np.degrees(np.arctan2(-dz_dx, -dz_dy)) + 360) % 360
    return slope, aspect


def aspect_class(aspect_deg, slope_deg):
    """Clase de orientación (sectores de 45° centrados en cada dirección) o "Flat"."""
    a = np.asarray(aspect_deg, float)
    s = np.asarray(slope_deg, float)
    idx = (np.floor((a + 22.5) / 45).astype(int)) % 8
    out = np.array(ASPECTS, dtype=object)[idx]
    out = np.where(s < FLAT_DEG, "Flat", out)
    return out


def hillshade(dem: np.ndarray, dx: float, dy: float, azimuth: float = HS_AZIMUTH,
              altitude: float = HS_ALTITUDE, z: float = HS_Z) -> np.ndarray:
    """Hillshade estándar 0..1: cos(zen)·cos(s) + sin(zen)·sin(s)·cos(az_math − aspect_math)."""
    dz_dx, dz_dy = derivatives(dem, dx, dy)
    dz_dx, dz_dy = dz_dx * z, dz_dy * z
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect_math = np.arctan2(-dz_dy, -dz_dx)              # ángulo matemático de la dirección cuesta abajo
    zenith = np.radians(90 - altitude)
    az_math = np.radians((90 - azimuth) % 360)            # 315° (NO) → 135° matemático
    hs = np.cos(zenith) * np.cos(slope) + np.sin(zenith) * np.sin(slope) * np.cos(az_math - aspect_math)
    return np.clip(hs, 0, 1)


def bilinear(arr: np.ndarray, transform, lon, lat) -> np.ndarray:
    """Interpolación bilineal en centros de píxel; NaN fuera del array."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    c = (lon - transform.c) / transform.a - 0.5
    r = (lat - transform.f) / transform.e - 0.5
    h, w = arr.shape
    ok = (c >= 0) & (c <= w - 1) & (r >= 0) & (r <= h - 1)
    c0 = np.clip(np.floor(c).astype(int), 0, max(w - 2, 0))
    r0 = np.clip(np.floor(r).astype(int), 0, max(h - 2, 0))
    fc, fr = np.clip(c - c0, 0, 1), np.clip(r - r0, 0, 1)
    c1, r1 = np.minimum(c0 + 1, w - 1), np.minimum(r0 + 1, h - 1)
    v = (arr[r0, c0] * (1 - fc) * (1 - fr) + arr[r0, c1] * fc * (1 - fr)
         + arr[r1, c0] * (1 - fc) * fr + arr[r1, c1] * fc * fr)
    return np.where(ok, v, np.nan)


def nearest(arr: np.ndarray, transform, lon, lat):
    c = np.floor((np.asarray(lon, float) - transform.c) / transform.a).astype(int)
    r = np.floor((np.asarray(lat, float) - transform.f) / transform.e).astype(int)
    h, w = arr.shape
    ok = (c >= 0) & (c < w) & (r >= 0) & (r < h)
    out = np.full(len(c), None, dtype=object)
    out[ok] = arr[r[ok], c[ok]]
    return out


# ---------- acceso a los datos ----------
def _bbox_key(b) -> str:
    return f"{COLLECTION}#bbox={b[0]:.6f},{b[1]:.6f},{b[2]:.6f},{b[3]:.6f}"


def margin_bbox(bounds, margin_m: float = MARGIN_M) -> tuple:
    w, s, e, n = bounds
    lat_c = math.radians((s + n) / 2)
    dlat = margin_m / M_PER_DEG
    dlon = margin_m / (M_PER_DEG * math.cos(lat_c))
    return (w - dlon, s - dlat, e + dlon, n + dlat)


def _s3_to_https(href: str) -> str:
    return S3_HTTPS + href[len("s3://copernicus-dem-30m/"):] if href.startswith("s3://copernicus-dem-30m/") else href


def tile_urls_direct(bbox) -> list[str]:
    """Respaldo sin STAC: teselas de 1° que tocan la caja (floor de la esquina SW)."""
    out = []
    for lat in range(math.floor(bbox[1]), math.floor(bbox[3]) + 1):
        for lon in range(math.floor(bbox[0]), math.floor(bbox[2]) + 1):
            out.append(TILE_URL.format(ns="N" if lat >= 0 else "S", lat=abs(lat),
                                       ew="E" if lon >= 0 else "W", lon=abs(lon)))
    return out


def tile_urls(bbox) -> tuple[list[str], str]:
    """(URLs https de los COG, vía) con STAC cacheado; respaldo: patrón directo del bucket."""
    body = json.dumps({"collections": [COLLECTION], "bbox": [round(x, 6) for x in bbox], "limit": 10},
                      sort_keys=True).encode()
    hit = cache.lookup(NAME, "POST", STAC_URL, body)
    try:
        if hit is None:
            r = cache.client().post(STAC_URL, content=body, headers={"Content-Type": "application/json"},
                                    timeout=30)
            if r.status_code != 200:
                raise cache.FetchError(f"STAC HTTP {r.status_code}")
            feats = r.json().get("features") or []
            if not feats:
                raise cache.FetchError("STAC sin items")
            hit = cache.store(NAME, "POST", STAC_URL, body, r.content, "application/geo+json")
        hrefs = [_s3_to_https(f["assets"]["data"]["href"]) for f in hit.json()["features"]
                 if "data" in f.get("assets", {})]
        if hrefs:
            return hrefs, "Earth Search STAC"
    except Exception:  # noqa: BLE001 — se usa el patrón directo
        pass
    return tile_urls_direct(bbox), "S3 directo"


class DEM:
    """Recorte del DEM (filas N→S, EPSG:4326) con pendiente y orientación ya calculadas."""

    def __init__(self, content: bytes, meta: dict):
        with MemoryFile(content) as mem, mem.open() as src:
            arr = src.read(1).astype("float64")
            if src.nodata is not None:
                arr[arr == src.nodata] = np.nan
            self.transform = src.transform
            self.bounds = tuple(src.bounds)
        self.arr = arr
        self.meta = meta
        lat_c = math.radians((self.bounds[1] + self.bounds[3]) / 2)
        self.dy = abs(self.transform.e) * M_PER_DEG
        self.dx = self.transform.a * M_PER_DEG * math.cos(lat_c)
        self.slope, self.aspect = slope_aspect(self.arr, self.dx, self.dy)
        self.aspect_cls = aspect_class(self.aspect, self.slope)

    def covers(self, bbox) -> bool:
        b = self.bounds
        return b[0] <= bbox[0] and b[1] <= bbox[1] and b[2] >= bbox[2] and b[3] >= bbox[3]

    def provenance(self) -> str:
        tiles = "+".join(sorted(u.rsplit("/", 1)[-1].replace("Copernicus_DSM_COG_10_", "").replace("_DEM.tif", "")
                                for u in self.meta.get("tiles", [])))
        return (f"Copernicus DEM GLO-30 ({self.meta.get('via', '-')}, COG {tiles or '-'}) · "
                f"descargado {self.meta.get('fetched_at', '-')[:10]}")


def _read_window(bbox) -> tuple[bytes, dict]:
    urls, via = tile_urls(bbox)
    with rasterio.Env(**GDAL_ENV):
        srcs = []
        try:
            for u in urls:
                srcs.append(rasterio.open("/vsicurl/" + u))
            ref = srcs[0]
            hx, hy = HALO_PX * ref.res[0], HALO_PX * ref.res[1]
            win = (bbox[0] - hx, bbox[1] - hy, bbox[2] + hx, bbox[3] + hy)
            # merge lee solo la ventana de cada tesela y hace el mosaico si cruza varias
            arr, transform = merge(srcs, bounds=win, nodata=-9999.0, dtype="float32")
        finally:
            for s in srcs:
                s.close()
    profile = dict(driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=1, dtype="float32",
                   crs="EPSG:4326", transform=transform, nodata=-9999.0, compress="deflate")
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(arr[0], 1)
        content = mem.read()
    return content, {"via": via, "tiles": urls}


_LOCK = threading.Lock()
_MEM: list[DEM] = []


def _cached_covering(bbox) -> DEM | None:
    """Un recorte ya en caché (memoria o disco) que cubra la caja: sin red."""
    for d in _MEM:
        if d.covers(bbox):
            return d
    folders = [cache.cache_dir(NAME), DEMO_CACHE / NAME]
    for meta_path in (m for f in folders if f.exists() for m in f.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("method") != "DEM" or "#bbox=" not in meta["url"]:
                continue
            b = [float(x) for x in meta["url"].split("#bbox=")[1].split(",")]
        except (ValueError, KeyError, OSError):
            continue
        tol = 2e-6                         # la clave guarda la caja con 6 decimales
        if b[0] <= bbox[0] + tol and b[1] <= bbox[1] + tol and b[2] >= bbox[2] - tol and b[3] >= bbox[3] - tol:
            info = json.loads(meta.get("body") or "{}")
            dem = DEM(meta_path.with_suffix(".bin").read_bytes(), {**info, "fetched_at": meta["fetched_at"]})
            _MEM.append(dem)
            return dem
    return None


def load_dem(bbox) -> DEM:
    with _LOCK:
        hit = _cached_covering(bbox)
        if hit:
            return hit
        content, info = _read_window(bbox)
        c = cache.store(NAME, "DEM", _bbox_key(bbox), json.dumps(info).encode(), content, "image/tiff")
        dem = DEM(content, {**info, "fetched_at": c.fetched_at})
        _MEM.append(dem)
        return dem


# ---------- PNG ----------
def _png(path, rgba: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)
    return hashlib.sha1(rgba.tobytes()).hexdigest()[:10]


def _gray_rgba(hs: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    g = np.nan_to_num(hs * 255, nan=0).astype(np.uint8)
    return np.dstack([g, g, g, alpha.astype(np.uint8)])


def render_field_hillshade(field, dem: DEM) -> dict:
    """PNG de hillshade del campo: mismos bounds exactos que sus capas, rejilla 5× más fina."""
    from ..render import MAX_PX, safe

    lon_w, lat_s, lon_e, lat_n = field.geom.bounds
    lat_c = math.radians((lat_s + lat_n) / 2)
    px_m = field.grid.step / HS_FINE
    W = int(np.clip(np.ceil((lon_e - lon_w) * M_PER_DEG * math.cos(lat_c) / px_m), 2, MAX_PX))
    H = int(np.clip(np.ceil((lat_n - lat_s) * M_PER_DEG / px_m), 2, MAX_PX))
    lons = lon_w + (np.arange(W) + 0.5) * (lon_e - lon_w) / W
    lats = lat_n - (np.arange(H) + 0.5) * (lat_n - lat_s) / H
    LON, LAT = np.meshgrid(lons, lats)
    z = bilinear(dem.arr, dem.transform, LON.ravel(), LAT.ravel()).reshape(H, W)
    dx = (lon_e - lon_w) / W * M_PER_DEG * math.cos(lat_c)
    dy = (lat_n - lat_s) / H * M_PER_DEG
    hs = hillshade(z, dx, dy)
    inside = shapely.contains_xy(field.geom, LON.ravel(), LAT.ravel()).reshape(H, W)
    alpha = np.where(inside & ~np.isnan(hs), 255, 0)
    base = f"{NAME}_hillshade"
    d = RENDERS / safe(field.field_id)
    v = _png(d / f"{base}.png", _gray_rgba(hs, alpha))
    return {"png_url": f"/renders/{safe(field.field_id)}/{base}.png?v={v}", "size": [W, H]}


def render_background(dem: DEM, bbox) -> dict:
    """Hillshade de toda la caja de la petición, sin recortar, con fundido en los bordes."""
    hs = hillshade(dem.arr, dem.dx, dem.dy)
    H, W = hs.shape
    fy = np.minimum(np.arange(H), np.arange(H)[::-1]) / max(H * BG_FADE, 1)
    fx = np.minimum(np.arange(W), np.arange(W)[::-1]) / max(W * BG_FADE, 1)
    fade = np.clip(np.minimum.outer(fy, fx), 0, 1)
    fade = fade * fade * (3 - 2 * fade)                   # smoothstep
    alpha = np.where(np.isnan(hs), 0, 255 * fade)
    name = f"{NAME}_background_{hashlib.sha1(_bbox_key(dem.bounds).encode()).hexdigest()[:8]}.png"
    v = _png(RENDERS / "_terrain" / name, _gray_rgba(hs, alpha))
    b = dem.bounds
    return {"png_url": f"/renders/_terrain/{name}?v={v}", "bounds": [[b[1], b[0]], [b[3], b[2]]]}


# ---------- fuente ----------
DESCRIPTION = ("Copernicus DEM GLO-30 is a digital surface model: elevation may include vegetation and "
               "buildings, especially at field edges.")
METHOD_NOTES = [
    "Stated accuracy: absolute vertical < 4 m (90 %), relative vertical < 2 m on slopes ≤ 20 %.",
    "Slope and aspect computed from the DEM with 2-pixel halo; hillshade uses vertical exaggeration ×3.",
]


@register_source
class CopernicusDEM(Source):
    name = NAME
    title = "Copernicus DEM GLO-30"
    display_name = "Copernicus DEM GLO-30"
    parameters = ["elevation", "elevation_rel", "slope", "aspect", "hillshade"]
    coverage = "Global"
    resolution = "~30 m"
    notes = DESCRIPTION + " " + " ".join(METHOD_NOTES)
    terrain = True            # no entra en la fusión derived ni en sampling_priority

    def __init__(self):
        self.dem: DEM | None = None
        self.error: str | None = None
        self.ranges: dict = {}
        self.background: dict | None = None

    def info(self) -> dict:
        return {**super().info(), "display_name": self.display_name, "description": DESCRIPTION,
                "method_notes": METHOD_NOTES}

    # Una sola lectura para toda la petición
    def prepare(self, fields) -> None:
        self.dem, self.error, self.ranges, self.background = None, None, {}, None
        if not fields:
            return
        b = np.array([f.geom.bounds for f in fields])
        bbox = margin_bbox((b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()))
        try:
            self.dem = load_dem(bbox)
        except Exception as exc:  # noqa: BLE001 — filas status=error
            self.error = f"Copernicus DEM no disponible: {type(exc).__name__}: {exc}"
            return
        elev, slope = [], []
        for f in fields:
            g = f.grid
            elev.append(bilinear(self.dem.arr, self.dem.transform, g.lon, g.lat))
            slope.append(bilinear(self.dem.slope, self.dem.transform, g.lon, g.lat))
        e, s = np.concatenate(elev), np.concatenate(slope)
        if np.any(~np.isnan(e)):
            self.ranges = {"elevation": (round(float(np.nanmin(e)), 1), round(float(np.nanmax(e)), 1)),
                           "slope": (0.0, max(SLOPE_SCALE_MIN, round(float(np.nanpercentile(s, 98)), 1)))}
        try:
            self.background = render_background(self.dem, bbox)
        except Exception:  # noqa: BLE001 — el fondo es opcional
            self.background = None

    def _dem_for(self, field) -> DEM:
        bbox = margin_bbox(field.geom.bounds, 0)
        if self.dem is not None and self.dem.covers(bbox):
            return self.dem
        if self.error and self.dem is None:
            raise cache.FetchError(self.error)
        return load_dem(margin_bbox(field.geom.bounds))

    def fetch(self, field, parameters=None) -> list[dict]:
        params = [p for p in (parameters or self.parameters) if p in self.parameters and p != "hillshade"]
        g = field.grid
        n = len(g)
        try:
            dem = self._dem_for(field)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc) if isinstance(exc, cache.FetchError) else f"{type(exc).__name__}: {exc}"
            return [row(field, i, self.name, p, status="error", original=msg, provenance="Copernicus DEM GLO-30")
                    for p in params for i in range(n)]
        elev = bilinear(dem.arr, dem.transform, g.lon, g.lat)
        slope = bilinear(dem.slope, dem.transform, g.lon, g.lat)
        asp_deg = bilinear(dem.aspect, dem.transform, g.lon, g.lat)
        asp_cls = nearest(dem.aspect_cls, dem.transform, g.lon, g.lat)
        low = float(np.nanmin(elev)) if np.any(~np.isnan(elev)) else np.nan
        pv = dem.provenance()
        rows: list[dict] = []
        for p in params:
            for i in range(n):
                e = elev[i]
                if p in ("elevation", "elevation_rel"):
                    if np.isnan(e):
                        rows.append(row(field, i, self.name, p, status="no_coverage", original=None, provenance=pv))
                        continue
                    v = e if p == "elevation" else e - low
                    rows.append(row(field, i, self.name, p, value=round(float(v), 1), sigma=ELEV_SIGMA,
                                    original=json.dumps({"dem_m": round(float(e), 3)}), provenance=pv))
                elif p == "slope":
                    if np.isnan(slope[i]):
                        rows.append(row(field, i, self.name, p, status="no_coverage", original=None, provenance=pv))
                        continue
                    rows.append(row(field, i, self.name, p, value=round(float(slope[i]), 1),
                                    original=json.dumps({"slope_deg": round(float(slope[i]), 3)}), provenance=pv))
                elif p == "aspect":
                    if asp_cls[i] is None:
                        rows.append(row(field, i, self.name, p, status="no_coverage", original=None, provenance=pv))
                        continue
                    rows.append(row(field, i, self.name, p, value=str(asp_cls[i]),
                                    original=json.dumps({"aspect_deg": None if np.isnan(asp_deg[i])
                                                         else round(float(asp_deg[i]), 1),
                                                         "slope_deg": None if np.isnan(slope[i])
                                                         else round(float(slope[i]), 3)}),
                                    provenance=pv))
        return rows

    # ---------- presentación ----------
    def render_opts(self, parameter: str, rows: list[dict]) -> dict:
        """vmin/vmax de granja (si prepare() los calculó) o del propio campo; paleta de aspect."""
        if parameter == "aspect":
            return {"palette": ASPECT_COLORS}
        vals = [r["value"] for r in rows if r["status"] == "ok" and isinstance(r["value"], (int, float))]
        if parameter == "elevation":
            lo, hi = self.ranges.get("elevation") or ((min(vals), max(vals)) if vals else (0, 1))
            return {"vmin": lo, "vmax": hi if hi > lo else lo + 1}
        if parameter == "slope":
            _, hi = self.ranges.get("slope") or (0, max(SLOPE_SCALE_MIN, float(np.percentile(vals, 98)) if vals else 0))
            return {"vmin": 0, "vmax": hi}
        return {}

    def hillshade_layer(self, field) -> dict | None:
        try:
            dem = self._dem_for(field)
            r = render_field_hillshade(field, dem)
        except Exception as exc:  # noqa: BLE001
            return {"parameter": "hillshade", "source": self.name, "unit": "0-255", "status": "error",
                    "png_url": None, "grid_url": None, "colormap": None, "message": str(exc)}
        lon_w, lat_s, lon_e, lat_n = field.geom.bounds
        return {"parameter": "hillshade", "source": self.name, "unit": "0-255", "status": "ok",
                "png_url": r["png_url"], "grid_url": None,
                "colormap": {"name": "gray", "min": 0, "max": 255},
                "bounds": [[lat_s, lon_w], [lat_n, lon_e]], "message": None,
                "provenance": {"source": self.title, "detail": dem.provenance() + " · hillshade 315°/45°, z ×3",
                               "notes": self.notes, "resolution": f"{field.grid.step / HS_FINE:g} m (DEM bilinear)"}}


EDGE_BUFFER_M = 40.0      # franja del borde excluida de las estadísticas de pendiente (setos/árboles en el DSM)
MIN_INTERIOR = 10         # con menos puntos interiores se usan todos


def terrain_summary(rows: list[dict], field=None) -> dict | None:
    """Resumen de terreno de un campo.

    Pendiente: slope_mean y slope_p95 (no el máximo) sin la franja de EDGE_BUFFER_M m del borde, porque el DSM
    convierte setos y árboles del linde en pendiente aparente. Los valores sin filtrar quedan en *_all.
    Si el campo es tan estrecho que quedan menos de MIN_INTERIOR puntos interiores, se usan todos.
    """
    def ok(p):
        return [r for r in rows if r["source"] == NAME and r["parameter"] == p
                and r["status"] == "ok" and r["value"] is not None]
    er, sr, ar = ok("elevation"), ok("slope"), ok("aspect")
    if not er:
        return None
    e = np.array([r["value"] for r in er], float)
    s = np.array([r["value"] for r in sr], float)
    a = [r["value"] for r in ar]
    s_in, buffer_m = s, None
    if field is not None and len(sr):
        g = field.grid
        pid = np.array([r["point_id"] for r in sr])
        d = shapely.distance(field.geom_utm.boundary, shapely.points(g.x[pid], g.y[pid]))
        inner = d >= EDGE_BUFFER_M
        if inner.sum() >= MIN_INTERIOR:
            s_in, buffer_m = s[inner], EDGE_BUFFER_M

    def r1(v):
        return round(float(v), 1)
    return {"elev_min": r1(e.min()), "elev_max": r1(e.max()), "elev_mean": r1(e.mean()),
            "local_relief": r1(e.max() - e.min()),
            "slope_mean": r1(s_in.mean()) if len(s_in) else None,
            "slope_p95": r1(np.percentile(s_in, 95)) if len(s_in) else None,
            "slope_mean_all": r1(s.mean()) if len(s) else None,
            "slope_p95_all": r1(np.percentile(s, 95)) if len(s) else None,
            "slope_edge_buffer_m": buffer_m,
            "dominant_aspect": Counter(a).most_common(1)[0][0] if a else None}
