"""
PASO 1 - ISRIC SoilGrids v2.0

a) Metadatos de unidades: /properties/layers (factor de conversión d_factor,
   unidades mapeadas -> unidades objetivo) filtrado a las propiedades útiles.
b) Consulta REST completa (8 propiedades x 3 profundidades x 5 estadísticos)
   en P1 y P3 (y P2/P4 si SG_ALL_POINTS=1), con pausa entre llamadas porque
   la API tiene límite de uso.
c) Vía raster (la del notebook de mapa): metadatos del VRT/COG que se lee con
   rasterio vía /vsicurl, ventana sobre la granja y comparación píxel vs REST.

Salida: samples/soilgrids/{layers.json, layers_full.json, P1.json, P3.json, raster_info.txt}
"""

from __future__ import annotations

import os
import time

from common import RAW, SAMPLES, as_json, ensure_dirs, fetch, load_points, write_json

OUT = SAMPLES / "soilgrids"
BASE = "https://rest.isric.org/soilgrids/v2.0"
PROPS = ["clay", "sand", "silt", "phh2o", "soc", "wv0033", "wv1500", "bdod"]
DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]
VALUES = ["mean", "Q0.05", "Q0.5", "Q0.95", "uncertainty"]
PAUSE = int(os.getenv("SG_PAUSE", "60"))
ALL_POINTS = os.getenv("SG_ALL_POINTS", "0") == "1"
RASTER_URL = "https://files.isric.org/soilgrids/latest/data/{prop}/{prop}_{depth}_{stat}.vrt"
RASTER_CHECKS = [("clay", "0-5cm", "mean"), ("clay", "0-5cm", "Q0.05"), ("phh2o", "0-5cm", "mean"),
                 ("soc", "0-5cm", "mean"), ("wv0033", "0-5cm", "mean")]  # wv0033: esperado 404
WCS_URL = "https://maps.isric.org/mapserv?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage..."


def main() -> None:
    ensure_dirs(OUT)
    pts = load_points()

    # ---------- a) metadatos ----------
    print("a) Metadatos de capas SoilGrids")
    rec = fetch("soilgrids", "properties/layers", f"{BASE}/properties/layers", timeout=120)
    meta = as_json(rec)
    if meta is not None:
        write_json(OUT / "layers_full.json", meta)
        layers = meta.get("layers", meta) if isinstance(meta, dict) else meta
        keep = [l for l in layers if isinstance(l, dict)
                and (l.get("property") in PROPS or l.get("name") in PROPS)]
        write_json(OUT / "layers.json", {"_request": rec["url"], "_seconds": rec["seconds"],
                                         "layers": keep})
    else:
        (OUT / "layers_ERROR.txt").write_text(f"{rec['url']}\nHTTP {rec['status']}\n{rec['error']}\n{rec['text'][:3000]}",
                                              encoding="utf-8")

    # ---------- b) consultas por punto ----------
    targets = ["P1", "P2", "P3", "P4"] if ALL_POINTS else ["P1", "P3"]
    print(f"\nb) Consulta REST en {targets} (pausa {PAUSE} s entre llamadas)")
    rest_values = {}
    for i, pid in enumerate(targets):
        if i:
            print(f"  esperando {PAUSE} s (rate limit)...")
            time.sleep(PAUSE)
        p = pts[pid]
        params = [("lon", p["lon"]), ("lat", p["lat"])]
        params += [("property", x) for x in PROPS]
        params += [("depth", x) for x in DEPTHS]
        params += [("value", x) for x in VALUES]
        rec = fetch("soilgrids", f"query {pid}", f"{BASE}/properties/query", params=params, timeout=180)
        data = as_json(rec)
        if rec["status"] == 429 or data is None:
            print("  reintento único tras 90 s...")
            time.sleep(90)
            rec = fetch("soilgrids", f"query {pid} (reintento)", f"{BASE}/properties/query",
                        params=params, timeout=180)
            data = as_json(rec)
        wrapper = {"_punto": p, "_request_url": rec["url"], "_http": rec["status"],
                   "_seconds": rec["seconds"], "_error": rec["error"],
                   "response": data if data is not None else rec["text"][:5000]}
        write_json(OUT / f"{pid}.json", wrapper)
        if data:
            rest_values[pid] = data

    # ---------- c) vía raster ----------
    print("\nc) Vía raster (VRT en files.isric.org leído con rasterio /vsicurl)")
    (OUT / "raster_info.txt").write_text(raster_info(pts, rest_values), encoding="utf-8")
    print(f"\nListo -> {OUT}")


def raster_info(pts: dict, rest_values: dict) -> str:
    import json

    out = ["Vía raster de SoilGrids (la que usa el notebook Prueba-SoilGrids.ipynb):",
           "URL patrón: " + RASTER_URL,
           "Lectura: rasterio.open('/vsicurl/' + url) con GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR", ""]
    try:
        import numpy as np
        import rasterio
        from pyproj import Transformer
        from rasterio.windows import from_bounds
    except ImportError as exc:
        return "\n".join(out + [f"rasterio no disponible: {exc}"])

    bbox = json.loads((SAMPLES / "puntos.json").read_text(encoding="utf-8"))["farm_bbox_lonlat"]
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_CONNECTTIMEOUT="15",
               GDAL_HTTP_TIMEOUT="90", GDAL_HTTP_MAX_RETRY="2")
    with rasterio.Env(**env):
        for prop, depth, stat in RASTER_CHECKS:
            url = RASTER_URL.format(prop=prop, depth=depth, stat=stat)
            out.append("=" * 90)
            out.append(f"{prop} {depth} {stat}: {url}")
            t0 = time.time()
            try:
                with rasterio.open("/vsicurl/" + url) as src:
                    out.append(f"crs:     {src.crs.to_string() if src.crs else None}")
                    out.append(f"wkt:     {src.crs.to_wkt()[:300] if src.crs else None}...")
                    out.append(f"res:     {src.res}")
                    out.append(f"bounds:  {src.bounds}")
                    out.append(f"nodata:  {src.nodata}")
                    out.append(f"dtypes:  {src.dtypes}")
                    out.append(f"shape:   {src.shape}")
                    out.append(f"scales/offsets: {src.scales} / {src.offsets}")
                    out.append(f"tags:    {src.tags()}")
                    out.append(f"read(1)[:5,:5] (esquina del mapa global, normalmente nodata):\n"
                               f"{src.read(1, window=((0, 5), (0, 5)))}")

                    tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                    xs, ys = tr.transform([bbox[0], bbox[2], bbox[0], bbox[2]],
                                          [bbox[1], bbox[1], bbox[3], bbox[3]])
                    win = from_bounds(min(xs), min(ys), max(xs), max(ys), src.transform)
                    win = win.round_offsets().round_lengths()
                    arr = src.read(1, window=win, masked=True)
                    out.append(f"ventana granja (bbox {bbox}): {arr.shape} píxeles "
                               f"(~{abs(src.res[0]):.0f} m), min={arr.min()} max={arr.max()} "
                               f"mean={float(arr.mean()):.1f} (unidades mapeadas, sin dividir)")
                    out.append(f"valores ventana:\n{np.ma.filled(arr, -1)}")

                    for pid in ("P1", "P2", "P3", "P4"):
                        p = pts[pid]
                        x, y = tr.transform(p["lon"], p["lat"])
                        v = next(src.sample([(x, y)]))[0]
                        rest = _rest_value(rest_values.get(pid), prop, depth, stat)
                        out.append(f"  píxel en {pid} ({p['lon']}, {p['lat']}): {v}"
                                   + (f" | REST: {rest}" if rest is not None else ""))
                out.append(f"tiempo total: {time.time() - t0:.1f} s")
            except Exception as exc:
                out.append(f"ERROR: {type(exc).__name__}: {exc} ({time.time() - t0:.1f} s)")
    out += wcs_info(pts, rest_values, bbox)
    return "\n".join(out)


def wcs_info(pts: dict, rest_values: dict, bbox: list) -> list[str]:
    """Agua a 33/1500 kPa NO está en files.isric.org/latest/data -> se pide por WCS."""
    import rasterio
    from rasterio.io import MemoryFile

    out = ["", "=" * 90,
           "WCS 2.0.1 de maps.isric.org (necesario para wv0033 / wv1500, que no existen como VRT):",
           f"  URL patrón: {WCS_URL}"]
    for prop, cov in [("wv0033", "wv0033_0-5cm_mean"), ("wv1500", "wv1500_0-5cm_mean"),
                      ("clay", "clay_0-5cm_mean")]:
        params = {"map": f"/map/{prop}.map", "SERVICE": "WCS", "VERSION": "2.0.1",
                  "REQUEST": "GetCoverage", "COVERAGEID": cov, "FORMAT": "image/tiff",
                  "SUBSETTINGCRS": "http://www.opengis.net/def/crs/EPSG/0/4326",
                  "OUTPUTCRS": "http://www.opengis.net/def/crs/EPSG/0/4326"}
        sub = [("SUBSET", f"long({bbox[0] - 0.005},{bbox[2] + 0.005})"),
               ("SUBSET", f"lat({bbox[1] - 0.005},{bbox[3] + 0.005})")]
        rec = fetch("soilgrids", f"WCS {cov}", "https://maps.isric.org/mapserv",
                    params=list(params.items()) + sub, timeout=120)
        out.append("-" * 90)
        out.append(f"{cov}: HTTP {rec['status']} | {rec['content_type']} | {rec['seconds']} s | "
                   f"{rec['bytes']} B\n  URL: {rec['url']}")
        if "tiff" not in rec["content_type"]:
            out.append(f"  respuesta: {rec['text'][:800]}")
            continue
        (RAW / f"soilgrids_wcs_{cov}.tif").write_bytes(rec["content"])
        with MemoryFile(rec["content"]) as mem, mem.open() as src:
            arr = src.read(1)
            out.append(f"  crs={src.crs} res={src.res} shape={src.shape} nodata={src.nodata} "
                       f"dtype={src.dtypes[0]}")
            out.append(f"  OJO: nodata no declarado; los píxeles enmascarados llegan como 0 "
                       f"(n ceros = {int((arr == 0).sum())} de {arr.size})")
            out.append(f"  valores (unidades mapeadas):\n{arr}")
            for pid in ("P1", "P2", "P3", "P4"):
                p = pts[pid]
                if not (bbox[0] - 0.01 <= p["lon"] <= bbox[2] + 0.01):
                    continue
                v = next(src.sample([(p["lon"], p["lat"])]))[0]
                rest = _rest_value(rest_values.get(pid), prop, "0-5cm", "mean")
                out.append(f"  píxel en {pid}: {v}" + (f" | REST: {rest}" if rest is not None else ""))
    return out


def _rest_value(data, prop, depth, stat):
    if not data:
        return None
    for layer in data.get("properties", {}).get("layers", []):
        if layer.get("name") == prop:
            for d in layer.get("depths", []):
                if d.get("label") == depth:
                    return d.get("values", {}).get(stat)
    return None


if __name__ == "__main__":
    main()
