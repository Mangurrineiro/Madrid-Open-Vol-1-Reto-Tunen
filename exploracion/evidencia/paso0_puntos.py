"""
PASO 0 - Puntos de prueba comunes a todas las fuentes.

Lee el GeoJSON de la granja, calcula área y centroide de cada campo y fija los
4 puntos estándar que se consultarán en TODAS las fuentes:

  P1  control dentro de Niedersachsen (lon 9.715, lat 52.315, zona del brief)
  P2  centroide de un campo de la granja dentro de Niedersachsen (si lo hay)
  P3  centroide del campo activo más grande fuera de Niedersachsen
  P4  centroide del campo activo más pequeño (>= 1 ha) fuera de Niedersachsen

"Cobertura LBEG" se decide con evidencia, no a ojo: se pregunta a la capa L816
(BK50 - Karte) de LBEG en el centroide de TODOS los campos activos. Además se
verifica el Land real (Nominatim, geocodificación inversa) de los puntos
elegidos y de los campos frontera, porque la BK50 puede dibujar polígonos
más allá de la frontera administrativa.

Salida: samples/puntos.txt (legible), samples/puntos.json (lo usan los demás
pasos) y samples/campos.csv (todos los campos).
"""

from __future__ import annotations

import csv
import json
import os
import time

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from common import (EXTRA_CONTROL, GEOJSON, P1_CONTROL, POINTS_FILE, SAMPLES, as_json,
                    ensure_dirs, fetch, write_json)
from lbeg import feature_properties, get_feature_info

# Cuántos campos activos (de oeste a este) se sondean contra LBEG. 0 = todos.
N_PROBE = int(os.getenv("N_PROBE", "0"))
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
MIN_SMALL_HA = 1.0


def main() -> None:
    ensure_dirs()
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True).transform
    to_wgs = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True).transform

    fields = []
    for i, feat in enumerate(gj["features"]):
        geom = shape(feat["geometry"])
        g_utm = transform(to_utm, geom)
        c = g_utm.centroid
        inside = g_utm.contains(c)
        if not inside:  # campo cóncavo: el centroide cae fuera, usamos un punto interior
            c = g_utm.representative_point()
        lon, lat = to_wgs(c.x, c.y)
        p = feat.get("properties") or {}
        fields.append({
            "field_id": f"f{i}",
            "plotId": p.get("plotId"),
            "fieldName": p.get("fieldName"),
            "isArchived": p.get("isArchived"),
            "area_attr_ha": p.get("area"),
            "area_ha": round(g_utm.area / 10_000, 4),
            "geom_type": geom.geom_type,
            "lon": round(lon, 5),
            "lat": round(lat, 5),
            "punto": "centroide" if inside else "representative_point",
            "_geom": geom,
        })

    all_geom = unary_union([f["_geom"] for f in fields])
    bounds = [round(b, 6) for b in all_geom.bounds]
    active = [f for f in fields if f["isArchived"] is False]

    print(f"{len(fields)} campos ({len(active)} activos). bbox granja: {bounds}")

    # --- Sondeo de cobertura LBEG en los campos activos (oeste -> este) ---
    to_probe = sorted(active, key=lambda f: f["lon"])
    if N_PROBE:
        to_probe = to_probe[:N_PROBE]
    print(f"\nSondeando cobertura LBEG (L816) en {len(to_probe)} campos activos...")
    probes = []
    for f in to_probe:
        rec = get_feature_info("paso0", f"L816 {f['field_id']} {f['fieldName']}", "L816",
                               f["lon"], f["lat"])
        props = feature_properties(rec)
        # None = no sabemos (error de red), distinto de False (LBEG responde "nada aquí")
        f["lbeg_l816_hit"] = None if rec["error"] else rec["hit"]
        probes.append({
            "field_id": f["field_id"], "fieldName": f["fieldName"], "lon": f["lon"], "lat": f["lat"],
            "http": rec["status"], "segundos": rec["seconds"], "hit": f["lbeg_l816_hit"],
            "BOTYP": props[0].get("BOTYP") if props else None,
            "error": rec["error"],
        })

    unknown = [f for f in active if f.get("lbeg_l816_hit") is None]
    if unknown:
        # LBEG caído: decidimos por el Land administrativo (Nominatim) para no bloquearnos.
        print(f"\nLBEG no respondió para {len(unknown)} campos -> fallback por Land (Nominatim)...")
        for f in unknown:
            rec = fetch("paso0", f"nominatim {f['field_id']}", NOMINATIM,
                        {"lat": f["lat"], "lon": f["lon"], "format": "jsonv2", "zoom": 5}, timeout=30)
            state = (as_json(rec) or {}).get("address", {}).get("state")
            f["lbeg_l816_hit"] = (state == "Niedersachsen") if state else None
            f["fallback_nominatim"] = state
            for pr in probes:
                if pr["field_id"] == f["field_id"]:
                    pr["hit"], pr["fallback_nominatim"] = f["lbeg_l816_hit"], state
            time.sleep(1.1)

    nds = [f for f in active if f.get("lbeg_l816_hit")]
    probed_outside = [f for f in active if f.get("lbeg_l816_hit") is False]
    outside = probed_outside
    if not outside:
        # LBEG responde en toda la granja: P3/P4 siguen siendo grande/pequeño, pero
        # se marca para que la matriz lo recoja (cobertura más allá de la frontera?).
        outside = [f for f in active if f not in nds] or active

    points = [{
        "id": "P1", "lon": P1_CONTROL["lon"], "lat": P1_CONTROL["lat"],
        "label": "Control dentro de Niedersachsen (zona del ejemplo del brief, cerca de Hannover)",
        "field_id": None, "fieldName": None, "area_ha": None, "in_nds": True,
    }]

    if nds:
        f = max(nds, key=lambda f: f["area_ha"])
        points.append(_pt("P2", f, "Campo de la granja DENTRO de Niedersachsen (L816 responde)", True))
        p2_note = f"Hay {len(nds)} campo(s) activos de la granja con cobertura LBEG."
    else:
        fb = EXTRA_CONTROL["X2"]
        points.append({
            "id": "P2", "lon": fb["lon"], "lat": fb["lat"],
            "label": "NINGÚN campo de la granja tiene cobertura LBEG -> fallback Helmstedt (NDS, cerca de la granja)",
            "field_id": None, "fieldName": None, "area_ha": None, "in_nds": True,
        })
        p2_note = "NINGÚN campo activo de la granja responde en LBEG L816 (fuera de Niedersachsen)."

    big = max(outside, key=lambda f: f["area_ha"])
    small_pool = [f for f in outside if f["area_ha"] >= MIN_SMALL_HA and f is not big] or outside
    small = min(small_pool, key=lambda f: f["area_ha"])
    sin_cob = bool(probed_outside)
    points.append(_pt("P3", big, "Campo activo MÁS GRANDE " +
                      ("SIN cobertura LBEG" if sin_cob else "(LBEG cubre toda la granja)"), not sin_cob))
    points.append(_pt("P4", small, f"Campo activo MÁS PEQUEÑO (>= {MIN_SMALL_HA} ha) " +
                      ("SIN cobertura LBEG" if sin_cob else "(LBEG cubre toda la granja)"), not sin_cob))

    # --- Land real (independiente de LBEG) ---
    print("\nVerificando el Land administrativo con Nominatim...")
    border = []
    if nds and probed_outside:  # el último campo con cobertura y el primero sin ella
        border = [max(nds, key=lambda f: f["lon"]), min(probed_outside, key=lambda f: f["lon"])]
    check = [(p["id"], p["lon"], p["lat"]) for p in points]
    check += [(f"{f['field_id']} (frontera)", f["lon"], f["lat"]) for f in border]
    states = {}
    for pid, lon, lat in check:
        rec = fetch("paso0", f"nominatim {pid}", NOMINATIM,
                    {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10, "accept-language": "de"},
                    timeout=30)
        addr = (as_json(rec) or {}).get("address", {})
        states[pid] = f"{addr.get('state')} / {addr.get('county')} / " \
                      f"{addr.get('village') or addr.get('town') or addr.get('municipality') or addr.get('city')}"
        time.sleep(1.1)  # política de uso de Nominatim: 1 petición/s
    for p in points:
        p["land_nominatim"] = states.get(p["id"])

    write_json(POINTS_FILE, {"farm_bbox_lonlat": bounds, "points": points,
                             "lbeg_probe": probes, "nota_p2": p2_note, "land_nominatim": states})

    # --- campos.csv ---
    cols = ["field_id", "plotId", "fieldName", "isArchived", "area_attr_ha", "area_ha",
            "geom_type", "lon", "lat", "punto", "lbeg_l816_hit"]
    with (SAMPLES / "campos.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for f in fields:
            w.writerow({k: f.get(k) for k in cols})

    # --- puntos.txt (resumen legible) ---
    out = []
    out.append(f"{len(fields)} campos ({len(active)} activos, {len(fields) - len(active)} archivados)")
    out.append(f"columnas: {list(gj['features'][0]['properties'].keys()) + ['geometry']}")
    out.append(f"bbox granja (lon_min, lat_min, lon_max, lat_max): {bounds}")
    out.append(f"tipos de geometría: {sorted({f['geom_type'] for f in fields})}")
    out.append("")
    out.append("Campos ACTIVOS ordenados por área (ha calculada en EPSG:25832):")
    out.append(f"{'field_id':8} {'fieldName':28} {'area_ha':>8} {'area_attr':>9} {'lon':>9} {'lat':>9} punto")
    for f in sorted(active, key=lambda f: -f["area_ha"]):
        out.append(f"{f['field_id']:8} {str(f['fieldName'])[:28]:28} {f['area_ha']:8.2f} "
                   f"{str(f['area_attr_ha']):>9} {f['lon']:9.5f} {f['lat']:9.5f} {f['punto']}")
    out.append("")
    out.append(f"Sondeo de cobertura LBEG (capa L816 BK50-Karte) en {len(probes)} campos activos (oeste -> este):")
    for p in probes:
        out.append(f"  {p['field_id']:6} {str(p['fieldName'])[:26]:26} lon={p['lon']:.5f} lat={p['lat']:.5f} "
                   f"HTTP={p['http']} hit={p['hit']} BOTYP={p['BOTYP']} t={p['segundos']}s {p['error'][:80]}"
                   + (f" [fallback Land: {p['fallback_nominatim']}]" if p.get('fallback_nominatim') else ""))
    out.append(f"  -> {p2_note}")
    out.append(f"  -> con cobertura LBEG: {len(nds)} | sin cobertura: {len(probed_outside)} | no sondeados: "
               f"{len(active) - len(probes)}")
    out.append("")
    out.append("Land administrativo según Nominatim/OSM (independiente de LBEG):")
    for k, v in states.items():
        out.append(f"  {k}: {v}")
    out.append("")
    out.append("PUNTOS ESTÁNDAR (usar los mismos en todas las fuentes):")
    for p in points:
        extra = f" | {p['fieldName']} ({p['field_id']}, {p['area_ha']} ha)" if p["field_id"] else ""
        out.append(f"  {p['id']}: lon={p['lon']:.5f} lat={p['lat']:.5f} | {p['label']}{extra} "
                   f"| Land: {p.get('land_nominatim')}")
    out.append("")
    out.append("Puntos extra de control en Niedersachsen (solo si un punto estándar no devuelve nada en LBEG):")
    for pid, p in EXTRA_CONTROL.items():
        out.append(f"  {pid}: lon={p['lon']} lat={p['lat']} | {p['label']}")
    text = "\n".join(out)
    (SAMPLES / "puntos.txt").write_text(text, encoding="utf-8")
    print("\n" + text)


def _pt(pid: str, f: dict, label: str, in_nds: bool) -> dict:
    return {"id": pid, "lon": f["lon"], "lat": f["lat"], "label": label,
            "field_id": f["field_id"], "fieldName": f["fieldName"],
            "area_ha": f["area_ha"], "in_nds": in_nds}


if __name__ == "__main__":
    main()
