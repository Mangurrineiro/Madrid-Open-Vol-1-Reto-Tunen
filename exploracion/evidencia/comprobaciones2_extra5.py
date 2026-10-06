"""Comprobación 5b extra: ¿por qué la consulta por polígono no trae geometría? Variantes registradas."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import comprobaciones2 as c

fields = c.load_fields()
g = c.fields_geom = fields["f82"]["geom"]
url = f"{c.BUEK_URL}/18/query"
simp = g.simplify(0.0002, preserve_topology=True)
rings_s = [list(map(list, simp.exterior.coords))]
base = {"geometryType": "esriGeometryPolygon", "inSR": 4326, "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "OBJECTID,TKLE_NR", "returnGeometry": "true", "f": "json"}
geom_s = json.dumps({"rings": rings_s, "spatialReference": {"wkid": 4326}})
env = f"{g.bounds[0]},{g.bounds[1]},{g.bounds[2]},{g.bounds[3]}"
variants = {
    "GET_poligono_simplificado": dict(base, geometry=geom_s),
    "GET_poligono_simplificado_maxAllowableOffset": dict(base, geometry=geom_s, maxAllowableOffset=0.001),
    "GET_envelope": dict(base, geometry=env, geometryType="esriGeometryEnvelope"),
    "GET_punto_returnGeometry": dict(base, geometry=f"{g.centroid.x},{g.centroid.y}", geometryType="esriGeometryPoint"),
    "GET_punto_returnGeometry_f_geojson": dict(base, geometry=f"{g.centroid.x},{g.centroid.y}",
                                               geometryType="esriGeometryPoint", f="geojson"),
    "GET_punto_returnGeometry_outSR_25832": dict(base, geometry=f"{g.centroid.x},{g.centroid.y}",
                                                 geometryType="esriGeometryPoint", outSR=25832),
}
res = {}
for name, p in variants.items():
    r = c.fetch("5", f"f82 variante {name}", url, p)
    j = c.as_json(r) or {}
    feats = j.get("features", [])
    res[name] = {"_llamada": c.call_meta(r), "n_features": len(feats),
                 "con_geometria": [bool(f.get("geometry")) for f in feats],
                 "n_vertices": [len(c._flatten((f.get("geometry") or {}).get("rings") or (f.get("geometry") or {}).get("coordinates"))) for f in feats],
                 "respuesta": c.trim_geoms(j or r["text"][:1500])}
lay = c.fetch("5", "capa 18 ?f=pjson (capabilities)", f"{c.BUEK_URL}/18", {"f": "pjson"})
lj = c.as_json(lay) or {}
res["metadatos_capa_18"] = {k: lj.get(k) for k in ("capabilities", "maxRecordCount", "supportedQueryFormats",
                                                   "canModifyLayer", "hasZ", "extent", "advancedQueryCapabilities",
                                                   "supportsAdvancedQueries")}
srv = c.fetch("5", "MapServer ?f=pjson (capabilities)", c.BUEK_URL, {"f": "pjson"})
sj = c.as_json(srv) or {}
res["metadatos_servicio"] = {k: sj.get(k) for k in ("capabilities", "maxRecordCount", "supportedQueryFormats",
                                                    "maxSelectionCount", "currentVersion")}
c.write_json(c.OUT / "5_buek200" / "f82_variantes_geometria.json", res)
for k, v in res.items():
    print(k, {kk: vv for kk, vv in v.items() if kk not in ("respuesta", "_llamada")})
