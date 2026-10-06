"""Comprobación 4 extra: análisis de las anomalías de la cosecha (polígono que no contiene el punto consultado)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import comprobaciones2 as c
from shapely.geometry import Point, shape

d = c.OUT / "4_cosecha"
fields = c.load_fields()
field25 = c.to25832(fields["f51"]["geom"])
out = {}
for layer in ["L849", "L816"]:
    calls = json.loads((d / f"llamadas_{layer}.json").read_text(encoding="utf-8"))
    polys = [(f["properties"]["poly_idx"], f["properties"].get("FL_NR"), c.to25832(shape(f["geometry"])))
             for f in json.loads((d / f"poligonos_{layer}_4326.geojson").read_text(encoding="utf-8"))["features"]]
    rows = []
    for e in calls:
        p = Point(*c.TO_25832.transform(e["lon"], e["lat"]))
        own = next(g for i, fl, g in polys if i == e.get("poly_idx"))
        if own.buffer(0.01).contains(p):
            continue
        inside_any = [fl for i, fl, g in polys if g.buffer(0.01).contains(p)]
        rows.append({"punto": e["punto"], "lon": e["lon"], "lat": e["lat"], "FL_NR_devuelto": e.get("FL_NR"),
                     "distancia_m_al_poligono_devuelto": round(own.distance(p), 2),
                     "distancia_m_al_borde_del_campo": round(field25.exterior.distance(p), 2),
                     "contenido_en_algun_poligono_cosechado(FL_NR)": inside_any})
    union = __import__("shapely.ops", fromlist=["unary_union"]).unary_union([g for _, _, g in polys])
    hueco = field25.difference(union)
    out[layer] = {"anomalias": rows, "superficie_campo_sin_poligono_ha": round(hueco.area / 1e4, 4)}
c.write_json(d / "anomalias.json", out)
print(json.dumps(out, indent=1, ensure_ascii=False))
