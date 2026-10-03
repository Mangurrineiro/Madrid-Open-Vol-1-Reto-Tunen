"""
ISRIC SoilGrids 2.0 (250 m, global).

- WCS 2.0.1 de maps.isric.org: GetCoverage en GeoTIFF (EPSG:4326) sobre la caja del campo
  con margen, para clay, sand, silt, phh2o, soc, wv0033, wv1500 × 0-5/5-15/15-30 cm ×
  mean/Q0.05/Q0.95 (63 coberturas por campo, ~0,4 s cada una, cacheadas en disco).
- Respaldo si el WCS falla: VRT de files.isric.org/soilgrids/latest/data/ (no existe para
  wv0033/wv1500, ver samples2/RESUMEN2.md §6).
- El GeoTIFF del WCS no declara nodata: -32768 = sin cobertura (zonas urbanas). Además,
  un pH, un contenido de agua o una textura (clay+sand+silt) de 0 son físicamente
  imposibles y se tratan también como sin cobertura (máscara).
- 0-30 cm = media ponderada por grosor (5/30, 10/30, 15/30); low/high = cuantiles
  ponderados igual; sigma = (high - low) / 3.29.
- nFK = wv0033 - wv1500 (% vol = mm/dm). sigma_nfk = sqrt(σ33² + σ1500²) (suposición:
  errores independientes); low/high = valor ∓ 1.645·sigma.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds

from .. import cache
from .base import Source, register_source, row

WCS_URL = "https://maps.isric.org/mapserv"
VRT_URL = "https://files.isric.org/soilgrids/latest/data/{prop}/{prop}_{cov}.vrt"
PROPS = ["clay", "sand", "silt", "phh2o", "soc", "wv0033", "wv1500"]
NO_VRT = {"wv0033", "wv1500"}
DEPTHS = [("0-5cm", 5), ("5-15cm", 10), ("15-30cm", 15)]
STATS = ["mean", "Q0.05", "Q0.95"]
NODATA = -32768
MARGIN_DEG = 0.005
Z90 = 3.29  # anchura del intervalo 5–95 % en sigmas (2 × 1.645)

# parámetro común -> (propiedad SoilGrids, divisor)
SIMPLE = {"clay": ("clay", 10), "sand": ("sand", 10), "silt": ("silt", 10),
          "ph_h2o": ("phh2o", 10), "soc": ("soc", 10)}


def _wcs_params(prop: str, cov: str, bbox) -> list[tuple[str, str]]:
    return [("map", f"/map/{prop}.map"), ("SERVICE", "WCS"), ("VERSION", "2.0.1"),
            ("REQUEST", "GetCoverage"), ("COVERAGEID", cov), ("FORMAT", "image/tiff"),
            ("SUBSETTINGCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"),
            ("OUTPUTCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"),
            ("SUBSET", f"long({bbox[0]:.6f},{bbox[2]:.6f})"),
            ("SUBSET", f"lat({bbox[1]:.6f},{bbox[3]:.6f})")]


def _is_tiff(r) -> str | None:
    return None if "tiff" in r.headers.get("Content-Type", "") else f"no es GeoTIFF: {r.text[:200]}"


class Layer:
    """Una cobertura recortada: array + transform + CRS, muestreable por lon/lat."""

    def __init__(self, content: bytes, url: str, fetched_at: str, via: str):
        with MemoryFile(content) as mem, mem.open() as src:
            self.arr = src.read(1).astype("float64")
            self.transform = src.transform
            self.crs = src.crs
        self.url, self.fetched_at, self.via = url, fetched_at, via

    def sample(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """Vecino más cercano: el píxel que contiene cada punto. NaN fuera o nodata."""
        if self.crs and self.crs.to_epsg() != 4326:
            xs, ys = Transformer.from_crs("EPSG:4326", self.crs, always_xy=True).transform(lon, lat)
        else:
            xs, ys = lon, lat
        cols, rows = ~self.transform * (np.asarray(xs), np.asarray(ys))
        cols, rows = np.floor(cols).astype(int), np.floor(rows).astype(int)
        h, w = self.arr.shape
        ok = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
        out = np.full(len(lon), np.nan)
        out[ok] = self.arr[rows[ok], cols[ok]]
        out[out == NODATA] = np.nan
        return out


def _get_layer(prop: str, cov: str, bbox) -> Layer:
    try:
        c = cache.fetch("soilgrids", WCS_URL, _wcs_params(prop, cov, bbox), timeout=60, validate=_is_tiff)
        return Layer(c.content, c.url, c.fetched_at, "WCS")
    except cache.FetchError:
        if prop in NO_VRT:
            raise
    return _get_vrt_layer(prop, cov, bbox)


def _get_vrt_layer(prop: str, cov: str, bbox) -> Layer:
    """Respaldo: lee la ventana del VRT y la guarda en caché como GeoTIFF."""
    url = VRT_URL.format(prop=prop, cov=cov)
    key = f"{url}#bbox={bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f}"
    hit = cache.lookup("soilgrids", "VRT", key)
    if hit:
        return Layer(hit.content, url, hit.fetched_at, "VRT")
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT="90")
    with rasterio.Env(**env), rasterio.open("/vsicurl/" + url) as src:
        tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        xs, ys = tr.transform([bbox[0], bbox[2], bbox[0], bbox[2]], [bbox[1], bbox[1], bbox[3], bbox[3]])
        win = from_bounds(min(xs), min(ys), max(xs), max(ys), src.transform)
        win = win.round_offsets().round_lengths()
        arr = src.read(1, window=win)
        profile = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype=arr.dtype, crs=src.crs, transform=src.window_transform(win))
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(arr, 1)
        content = mem.read()
    c = cache.store("soilgrids", "VRT", key, None, content, "image/tiff")
    return Layer(content, url, c.fetched_at, "VRT")


@register_source
class SoilGrids(Source):
    name = "soilgrids"
    title = "ISRIC SoilGrids 2.0"
    parameters = ["clay", "sand", "silt", "ph_h2o", "soc", "nfk"]
    coverage = "Global (zonas urbanas enmascaradas)"
    resolution = "250 m (remuestreado a ~0,0023° por el WCS)"
    notes = ("Modelo de aprendizaje automático; media 0-30 cm ponderada por grosor; low/high = "
             "cuantiles 5/95 %. nFK = wv0033 − wv1500.")

    def fetch(self, field, parameters=None) -> list[dict]:
        params = [p for p in (parameters or self.parameters) if p in self.parameters]
        props = sorted({SIMPLE[p][0] for p in params if p in SIMPLE}
                       | ({"wv0033", "wv1500"} if "nfk" in params else set()))
        b = field.geom.bounds
        bbox = (b[0] - MARGIN_DEG, b[1] - MARGIN_DEG, b[2] + MARGIN_DEG, b[3] + MARGIN_DEG)
        g = field.grid
        n = len(g)

        jobs = [(p, f"{p}_{d}_{s}") for p in props for d, _ in DEPTHS for s in STATS]
        layers: dict[str, Layer | Exception] = {}

        def run(job):
            prop, cov = job
            try:
                return cov, _get_layer(prop, cov, bbox)
            except Exception as exc:  # noqa: BLE001 — se reporta como status=error
                return cov, exc

        with ThreadPoolExecutor(max_workers=8) as ex:
            for cov, res in ex.map(run, jobs):
                layers[cov] = res

        # Valores crudos por propiedad: raw[prop][depth][stat] = array(n)
        raw: dict[str, dict[str, dict[str, np.ndarray]]] = {}
        errors: dict[str, str] = {}
        for prop in props:
            raw[prop] = {}
            for d, _ in DEPTHS:
                raw[prop][d] = {}
                for s in STATS:
                    lay = layers[f"{prop}_{d}_{s}"]
                    if isinstance(lay, Exception):
                        errors[prop] = f"{prop}_{d}_{s}: {lay}"
                        raw[prop][d][s] = np.full(n, np.nan)
                    else:
                        raw[prop][d][s] = lay.sample(g.lon, g.lat)
            # Máscara de valores físicamente imposibles (píxeles enmascarados que llegan como 0)
            if prop in ("phh2o", "wv0033", "wv1500"):
                for d in raw[prop]:
                    m = raw[prop][d]["mean"] == 0
                    for s in STATS:
                        raw[prop][d][s][m] = np.nan
        tex = [p for p in ("clay", "sand", "silt") if p in raw]
        if len(tex) == 3:
            for d, _ in DEPTHS:
                m = (raw["clay"][d]["mean"] + raw["sand"][d]["mean"] + raw["silt"][d]["mean"]) == 0
                for p in tex:
                    for s in STATS:
                        raw[p][d][s][m] = np.nan

        def weighted(prop: str, stat: str, div: float) -> np.ndarray:
            return sum(raw[prop][d][stat] * w for d, w in DEPTHS) / 30 / div

        def prov(props_used: list[str]) -> str:
            dates = sorted({layers[f"{p}_{d}_{s}"].fetched_at[:10] for p in props_used
                            for d, _ in DEPTHS for s in STATS
                            if not isinstance(layers[f"{p}_{d}_{s}"], Exception)})
            vias = sorted({layers[f"{p}_{d}_{s}"].via for p in props_used for d, _ in DEPTHS for s in STATS
                           if not isinstance(layers[f"{p}_{d}_{s}"], Exception)})
            return (f"SoilGrids 2.0 {'/'.join(vias) or '-'} {'+'.join(props_used)}"
                    f"_{{0-5,5-15,15-30cm}}_{{mean,Q0.05,Q0.95}} · descargado {', '.join(dates) or '-'}")

        def original(props_used: list[str], i: int) -> str:
            return json.dumps({p: {d: [None if np.isnan(raw[p][d][s][i]) else int(raw[p][d][s][i])
                                       for s in STATS] for d, _ in DEPTHS} for p in props_used},
                              separators=(",", ":"))

        rows: list[dict] = []
        for param in params:
            if param == "nfk":
                used = ["wv0033", "wv1500"]
                v33, v15 = weighted("wv0033", "mean", 10), weighted("wv1500", "mean", 10)
                s33 = (weighted("wv0033", "Q0.95", 10) - weighted("wv0033", "Q0.05", 10)) / Z90
                s15 = (weighted("wv1500", "Q0.95", 10) - weighted("wv1500", "Q0.05", 10)) / Z90
                val = v33 - v15
                sig = np.sqrt(s33 ** 2 + s15 ** 2)
                low, high = val - 1.645 * sig, val + 1.645 * sig
            else:
                prop, div = SIMPLE[param]
                used = [prop]
                val = weighted(prop, "mean", div)
                low, high = weighted(prop, "Q0.05", div), weighted(prop, "Q0.95", div)
                sig = (high - low) / Z90
            err = next((errors[p] for p in used if p in errors), None)
            pv = prov(used)
            for i in range(n):
                if err and np.isnan(val[i]):
                    rows.append(row(field, i, self.name, param, status="error", original=err, provenance=pv))
                elif np.isnan(val[i]):
                    rows.append(row(field, i, self.name, param, status="no_coverage",
                                    original=original(used, i), provenance=pv))
                else:
                    rows.append(row(field, i, self.name, param, value=round(float(val[i]), 2),
                                    low=round(float(low[i]), 2), high=round(float(high[i]), 2),
                                    sigma=round(float(sig[i]), 3), original=original(used, i),
                                    provenance=pv))
        return rows
