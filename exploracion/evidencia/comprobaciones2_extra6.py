"""Comprobación 6 extra: wv0033/wv1500 no están como VRT -> ¿qué coberturas ofrece el WCS de maps.isric.org?"""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import comprobaciones2 as c

res = {}
for prop in ["wv0033", "wv1500"]:
    r = c.fetch("6", f"WCS GetCapabilities {prop}", "https://maps.isric.org/mapserv",
                {"map": f"/map/{prop}.map", "SERVICE": "WCS", "VERSION": "2.0.1", "REQUEST": "GetCapabilities"})
    ids = sorted(set(re.findall(r"<wcs:CoverageId>([^<]+)</wcs:CoverageId>", r["text"])))
    (c.OUT / "6_soilgrids" / f"wcs_capabilities_{prop}.xml").write_bytes(r["content"])
    want = [f"{prop}_{d}_{s}" for d in c.SG_DEPTHS for s in c.SG_STATS]
    res[prop] = {"_llamada": c.call_meta(r), "coverage_ids": ids,
                 "de_las_9_pedidas_existen": [w for w in want if w in ids],
                 "de_las_9_pedidas_faltan": [w for w in want if w not in ids]}
    print(prop, len(ids), "faltan:", res[prop]["de_las_9_pedidas_faltan"])
c.write_json(c.OUT / "6_soilgrids" / "wcs_wv_coberturas.json", res)

# GetCoverage real de un cuantil por propiedad sobre la caja de f82
from rasterio.io import MemoryFile
b = c.load_fields()["f82"]["geom"].bounds
for cov in ["wv0033_0-5cm_Q0.05", "wv1500_15-30cm_Q0.95"]:
    prop = cov.split("_")[0]
    params = [("map", f"/map/{prop}.map"), ("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"),
              ("COVERAGEID", cov), ("FORMAT", "image/tiff"),
              ("SUBSETTINGCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"),
              ("OUTPUTCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"),
              ("SUBSET", f"long({b[0]},{b[2]})"), ("SUBSET", f"lat({b[1]},{b[3]})")]
    r = c.fetch("6", f"WCS GetCoverage {cov} caja f82", "https://maps.isric.org/mapserv", params, timeout=60)
    info = {"_llamada": c.call_meta(r)}
    if "tiff" in r["content_type"]:
        (c.OUT / "6_soilgrids" / f"wcs_{cov}_f82.tif").write_bytes(r["content"])
        with MemoryFile(r["content"]) as m, m.open() as src:
            a = src.read(1)
            info.update(shape=list(a.shape), nodata=src.nodata, dtype=src.dtypes[0], valores=a.tolist(),
                        n_ceros=int((a == 0).sum()), n_menos32768=int((a == -32768).sum()))
    else:
        info["cuerpo"] = r["text"][:1000]
    res[cov] = info
    print(cov, {k: v for k, v in info.items() if k not in ("_llamada", "valores")})
c.write_json(c.OUT / "6_soilgrids" / "wcs_wv_coberturas.json", res)
