"""
COMPROBACIONES 2 - últimas verificaciones sobre las APIs reales (samples2/).

Uso:
    .venv\\Scripts\\python exploracion\\evidencia\\comprobaciones2.py            # todas (1..8)
    .venv\\Scripts\\python exploracion\\evidencia\\comprobaciones2.py 1 2 3      # solo algunas

Reglas que cumple:
- Respuestas en bruto; solo se recortan geometrías largas (3 primeras coordenadas + nº de vértices),
  salvo en la comprobación 2, que guarda la geometría completa.
- Cada llamada HTTP queda en samples2/_llamadas.csv (URL exacta, HTTP, tiempo, tamaño, error).
- Timeout 20 s, máximo 3 reintentos, como mucho 4 peticiones simultáneas a nibis.lbeg.de.
"""

from __future__ import annotations

import csv
import html
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from pyproj import Geod, Transformer
from shapely.geometry import Point, shape, mapping
from shapely.ops import transform as shp_transform, unary_union
from shapely.prepared import prep

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
GEOJSON = ROOT / "reto" / "LuF-Seggerde-Dev-fields.geojson"
OUT = Path(__file__).resolve().parent / "samples2"
CALL_LOG = OUT / "_llamadas.csv"
BUEK_LAYERS = Path(__file__).resolve().parent / "samples" / "buek200" / "layers.json"

NIBIS_URL = "https://nibis.lbeg.de/net3/public/ogc.ashx"
BUEK_URL = "https://services.bgr.de/arcgis/rest/services/boden/buek200/MapServer"
SG_VRT = "https://files.isric.org/soilgrids/latest/data/{prop}/{prop}_{depth}_{stat}.vrt"

TIMEOUT = 20
MAX_RETRIES = 3
RETRY_WAITS = [10, 20, 40]  # s antes del reintento 1, 2, 3 (NIBIS: 503.2 dentro de HTTP 200)
NIBIS_SEM = threading.Semaphore(4)
ERROR_MARKERS = ("ServiceException", "Ein Fehler trat", "Error 503", "Service Busy")

TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
TO_4326 = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
FROM_4647 = Transformer.from_crs("EPSG:4647", "EPSG:4326", always_xy=True)
GEOD = Geod(ellps="GRS80")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "tunen-hackathon-soil-evidence/2.0 (research; hackathon)"})
_log_lock = threading.Lock()


# ----------------------------------------------------------------------------- utilidades
def log_call(check: str, label: str, method: str, url: str, status, seconds, size, error="",
             attempt=0, extra=""):
    with _log_lock:
        new = not CALL_LOG.exists()
        with CALL_LOG.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp", "check", "label", "method", "attempt", "status", "seconds",
                            "bytes", "error", "extra", "url"])
            w.writerow([datetime.now().isoformat(timespec="milliseconds"), check, label, method,
                        attempt, status, seconds, size, error, extra, url])


def fetch(check: str, label: str, url: str, params=None, data=None, timeout=TIMEOUT,
          retries=MAX_RETRIES, method: str | None = None) -> dict:
    """GET (o POST si data) con reintentos. Nunca lanza. Devuelve el último intento + lista de intentos."""
    method = method or ("POST" if data is not None else "GET")
    full_url = requests.Request(method, url, params=params).prepare().url
    is_nibis = "nibis.lbeg.de" in urlparse(url).netloc
    attempts = []
    rec = {}
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(RETRY_WAITS[attempt - 1])
        rec = {"url": full_url, "method": method, "status": None, "seconds": None, "bytes": 0,
               "error": "", "text": "", "content": b"", "content_type": "", "headers": {},
               "attempt": attempt}
        t0 = time.time()
        try:
            if is_nibis:
                NIBIS_SEM.acquire()
            try:
                r = SESSION.request(method, url, params=params, data=data, timeout=(timeout, timeout))
            finally:
                if is_nibis:
                    NIBIS_SEM.release()
            rec.update(status=r.status_code, bytes=len(r.content), content=r.content,
                       content_type=r.headers.get("Content-Type", ""), headers=dict(r.headers))
            try:
                rec["text"] = r.content.decode("utf-8")
            except UnicodeDecodeError:
                rec["text"] = r.content.decode(r.encoding or "latin-1", errors="replace")
            if r.status_code != 200:
                rec["error"] = f"HTTP {r.status_code}"
            elif any(m in rec["text"][:3000] for m in ERROR_MARKERS):
                rec["error"] = "service_error dentro de HTTP 200: " + rec["text"][:200].replace("\n", " ")
        except requests.RequestException as exc:
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        rec["seconds"] = round(time.time() - t0, 3)
        rl = {k: v for k, v in rec["headers"].items()
              if any(s in k.lower() for s in ("rate", "retry", "limit"))}
        log_call(check, label, method, full_url, rec["status"], rec["seconds"], rec["bytes"],
                 rec["error"], attempt, json.dumps(rl) if rl else "")
        attempts.append({k: rec[k] for k in ("attempt", "status", "seconds", "bytes", "error")})
        st = rec["status"] if rec["status"] is not None else "ERR"
        print(f"  [{check}] {label}{' (reintento %d)' % attempt if attempt else ''}: HTTP {st} | "
              f"{rec['seconds']} s | {rec['bytes']} B {('| ' + rec['error'][:120]) if rec['error'] else ''}")
        if not rec["error"]:
            break
    rec["attempts"] = attempts
    return rec


def as_json(rec):
    try:
        return json.loads(rec["text"])
    except (ValueError, TypeError):
        return None


def _flatten(coords):
    if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
        return [coords]
    out = []
    for c in coords or []:
        out += _flatten(c)
    return out


def trim_geoms(obj):
    """Recorta geometrías (GeoJSON / Esri) a sus 3 primeras coordenadas + nº total de vértices."""
    if isinstance(obj, dict):
        res = {}
        for k, v in obj.items():
            if k in ("coordinates", "rings", "paths") and isinstance(v, list):
                flat = _flatten(v)
                res[k] = {"_recortado": True, "primeras_3": flat[:3], "n_vertices": len(flat)}
            else:
                res[k] = trim_geoms(v)
        return res
    if isinstance(obj, list):
        return [trim_geoms(x) for x in obj]
    return obj


def call_meta(rec):
    return {"url": rec["url"], "method": rec["method"], "http": rec["status"], "seconds": rec["seconds"],
            "bytes": rec["bytes"], "content_type": rec["content_type"], "error": rec["error"],
            "intentos": rec["attempts"]}


def dump(path: Path, rec: dict, extra: dict | None = None, full_geometry=False):
    """Guarda meta + cuerpo (JSON parseado o texto) en path."""
    data = as_json(rec)
    body = data if data is not None else rec["text"]
    if not full_geometry:
        body = trim_geoms(body)
    out = {"_llamada": call_meta(rec), **(extra or {}), "respuesta": body}
    write_json(path, out)
    return data


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def load_fields() -> dict:
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    fields = {}
    for i, f in enumerate(gj["features"]):
        fields[f"f{i}"] = {"props": f["properties"], "geom": shape(f["geometry"])}
    return fields


def gfi_params(layers: str, lon: float, lat: float, info_format="application/geo+json",
               radius_m=50, size_px=101, feature_count=1) -> dict:
    """Mismo método que samples/: BBOX 100x100 m en EPSG:25832, píxel central."""
    x, y = TO_25832.transform(lon, lat)
    c = size_px // 2
    return {"PKGID": 24, "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
            "LAYERS": layers, "QUERY_LAYERS": layers, "STYLES": "", "CRS": "EPSG:25832",
            "BBOX": f"{x - radius_m},{y - radius_m},{x + radius_m},{y + radius_m}",
            "WIDTH": size_px, "HEIGHT": size_px, "I": c, "J": c,
            "INFO_FORMAT": info_format, "FEATURE_COUNT": feature_count}


def gfi(check, label, layers, lon, lat, **kw):
    return fetch(check, label, NIBIS_URL, gfi_params(layers, lon, lat, **kw))


def lbeg_geom_to_4326(geom: dict):
    """Detecta el CRS de una geometría LBEG por la magnitud de X y la pasa a EPSG:4326."""
    g = shape(geom)
    x0 = _flatten(geom["coordinates"])[0][0]
    if x0 > 1e7:  # 32xxxxxx.x -> EPSG:4647 (ETRS89 / UTM 32N con prefijo de zona)
        crs = "EPSG:4647 (prefijo de zona 32)"
        g4326 = shp_transform(lambda x, y, z=None: FROM_4647.transform(x, y), g)
    elif x0 > 1e5:
        crs = "EPSG:25832 (sin prefijo)"
        g4326 = shp_transform(lambda x, y, z=None: TO_4326.transform(x, y), g)
    else:
        crs = "EPSG:4326 (grados)"
        g4326 = g
    return crs, g4326


def area_ha_4326(g) -> float:
    return abs(GEOD.geometry_area_perimeter(g)[0]) / 10_000


def to25832(g):
    return shp_transform(lambda x, y, z=None: TO_25832.transform(x, y), g)


# ----------------------------------------------------------------------------- 1 praderas
PRADERA_FIELDS = [("f19", "pradera"), ("f164", "pradera"), ("f139", "pradera"),
                  ("f51", "cultivo"), ("f123", "cultivo")]


def check1(fields):
    d = OUT / "1_praderas"
    resumen = []
    for fid, tipo in PRADERA_FIELDS:
        fld = fields[fid]
        c = fld["geom"].centroid
        inside = fld["geom"].contains(c)
        rec = gfi("1", f"L849 {fid} {fld['props']['fieldName']}", "L849", c.x, c.y)
        data = dump(d / f"{fid}_L849.json", rec, {
            "_campo": {"field_id": fid, "fieldName": fld["props"]["fieldName"], "tipo": tipo,
                       "centroide_lon": round(c.x, 6), "centroide_lat": round(c.y, 6),
                       "centroide_dentro_del_campo": inside}})
        feats = (data or {}).get("features", [])
        p = feats[0]["properties"] if feats else {}
        resumen.append({"field_id": fid, "fieldName": fld["props"]["fieldName"], "tipo": tipo,
                        "lon": round(c.x, 6), "lat": round(c.y, 6), "http": rec["status"],
                        "error": rec["error"], "n_features": len(feats),
                        **{k: p.get(k) for k in ("KLASSENZEICHEN", "KLASSENZEICHEN_SEP",
                                                 "KLASSENZEICHEN_KLARTEXT", "BODENZ", "ACKERZ")},
                        "tipo_BODENZ": type(p.get("BODENZ")).__name__ if p else None,
                        "tipo_ACKERZ": type(p.get("ACKERZ")).__name__ if p else None,
                        "claves": list(p.keys())})
    write_json(d / "resumen.json", resumen)


# ----------------------------------------------------------------------------- 2 geometría
GEOM_LAYERS = ["L816", "L839", "L823", "L837", "L849"]
P2 = (11.04118, 52.38258)


def check2(fields):
    d = OUT / "2_geometria"
    pt = Point(*P2)
    resumen = []
    for layer in GEOM_LAYERS:
        rec = gfi("2", f"{layer} P2 geometría completa", layer, *P2)
        data = dump(d / f"P2_{layer}_completo.json", rec, full_geometry=True)
        row = {"layer": layer, "http": rec["status"], "error": rec["error"]}
        if data:
            row["crs_propiedad_raiz"] = data.get("crs")
            feats = data.get("features", [])
            row["n_features"] = len(feats)
            if feats and feats[0].get("geometry"):
                f0 = feats[0]
                geom = f0["geometry"]
                flat = _flatten(geom["coordinates"])
                crs, g4326 = lbeg_geom_to_4326(geom)
                row.update({
                    "crs_propiedad_feature": f0.get("crs"),
                    "tipo_geometria": geom["type"], "n_vertices": len(flat),
                    "primeras_3_coordenadas_crudas": flat[:3],
                    "crs_deducido": crs, "valido": g4326.is_valid,
                    "punto_consultado_dentro": g4326.contains(pt) or g4326.buffer(1e-7).contains(pt),
                    "superficie_ha_geodesica": round(area_ha_4326(g4326), 4),
                    "superficie_ha_planar_25832": round(to25832(g4326).area / 10_000, 4),
                    "bbox_4326": [round(v, 6) for v in g4326.bounds],
                    "AREA_atributo": f0.get("properties", {}).get("AREA"),
                    "FL_NR": f0.get("properties", {}).get("FL_NR"),
                    "id_feature": f0.get("id"),
                })
                write_json(d / f"P2_{layer}_4326.geojson", {"type": "FeatureCollection", "features": [
                    {"type": "Feature", "properties": f0.get("properties"), "geometry": mapping(g4326)}]})
        resumen.append(row)
    write_json(d / "resumen.json", resumen)


# ----------------------------------------------------------------------------- 3 multicapa
def check3(fields):
    d = OUT / "3_multicapa"
    layers = ",".join(GEOM_LAYERS)
    resumen = {}
    for fmt, fc, name in [("application/geo+json", 1, "geojson_fc1"),
                          ("application/geo+json", 5, "geojson_fc5"),
                          ("text/plain", 1, "textplain_fc1")]:
        rec = gfi("3", f"multicapa {fmt} FEATURE_COUNT={fc}", layers, *P2, info_format=fmt,
                  feature_count=fc)
        data = dump(d / f"P2_multicapa_{name}.json", rec)
        info = {"http": rec["status"], "error": rec["error"], "content_type": rec["content_type"]}
        if isinstance(data, dict):
            feats = data.get("features", [])
            info["n_features"] = len(feats)
            info["claves_raiz"] = list(data.keys())
            info["features"] = [{"id": f.get("id"), "claves_feature": list(f.keys()),
                                 "claves_properties": list((f.get("properties") or {}).keys())}
                                for f in feats]
        else:
            info["texto_inicio"] = rec["text"][:1500]
        resumen[name] = info
    write_json(d / "resumen.json", resumen)


# ----------------------------------------------------------------------------- 4 cosecha
def grid_points(geom4326, step=25.0):
    g = to25832(geom4326)
    pg = prep(g)
    minx, miny, maxx, maxy = g.bounds
    pts = []
    x = minx + step / 2
    while x < maxx:
        y = miny + step / 2
        while y < maxy:
            p = Point(x, y)
            if pg.contains(p):
                pts.append(p)
            y += step
        x += step
    return g, pts


def check4(fields):
    d = OUT / "4_cosecha"
    fld = fields["f51"]
    g25832, pts = grid_points(fld["geom"])
    pts4326 = [TO_4326.transform(p.x, p.y) for p in pts]
    write_json(d / "rejilla_f51_25m.json", {"field_id": "f51", "paso_m": 25, "crs_calculo": "EPSG:25832",
                                            "n_puntos": len(pts),
                                            "puntos_lonlat": [[round(a, 6), round(b, 6)] for a, b in pts4326]})
    resumen = {"field_id": "f51", "fieldName": fld["props"]["fieldName"], "n_puntos_rejilla": len(pts),
               "area_campo_ha": round(g25832.area / 10_000, 3), "capas": {}}
    for layer in ["L849", "L816"]:
        resolved = [None] * len(pts)   # índice del polígono que resuelve cada punto
        polys, llamadas, anomalías = [], [], []
        t0 = time.time()
        while None in resolved:
            i = resolved.index(None)
            lon, lat = pts4326[i]
            rec = gfi("4", f"cosecha {layer} punto {i}", layer, lon, lat)
            data = as_json(rec) if not rec["error"] else None
            feats = (data or {}).get("features", [])
            entry = {"punto": i, "lon": round(lon, 6), "lat": round(lat, 6), "http": rec["status"],
                     "seconds": rec["seconds"], "error": rec["error"], "n_features": len(feats),
                     "url": rec["url"]}
            if feats and feats[0].get("geometry"):
                crs, g4326 = lbeg_geom_to_4326(feats[0]["geometry"])
                g25 = to25832(g4326)
                pg = prep(g25.buffer(0.01))
                newly = [j for j, r in enumerate(resolved) if r is None and pg.contains(pts[j])]
                pid = len(polys)
                for j in newly:
                    resolved[j] = pid
                if i not in newly:  # el polígono no contiene el punto consultado: evitar bucle
                    resolved[i] = pid
                    anomalías.append({"punto": i, "motivo": "polígono devuelto no contiene el punto consultado"})
                props = feats[0].get("properties") or {}
                polys.append({"poly_idx": pid, "FL_NR": props.get("FL_NR"), "crs": crs,
                              "puntos_resueltos": len(newly),
                              "area_ha": round(g25.area / 10_000, 4),
                              "area_dentro_campo_ha": round(g25.intersection(g25832).area / 10_000, 4),
                              "properties": props, "geom4326": g4326})
                entry.update(poly_idx=pid, FL_NR=props.get("FL_NR"), puntos_resueltos=len(newly))
            else:
                resolved[i] = -1
                anomalías.append({"punto": i, "motivo": "sin feature/geometría", "error": rec["error"]})
            llamadas.append(entry)
        elapsed = round(time.time() - t0, 2)
        fl = {p["FL_NR"] for p in polys}
        cobertura = unary_union([to25832(p["geom4326"]) for p in polys]) if polys else None
        resumen["capas"][layer] = {
            "llamadas": len(llamadas), "segundos_total": elapsed,
            "segundos_por_llamada_media": round(statistics.mean(e["seconds"] for e in llamadas), 3),
            "poligonos_distintos": len(polys), "FL_NR_distintos": len(fl),
            "puntos_sin_resolver_por_error": resolved.count(-1),
            "fraccion_campo_cubierta_por_poligonos": round(cobertura.intersection(g25832).area / g25832.area, 4)
            if cobertura else 0,
            "poligonos": [{k: v for k, v in p.items() if k != "geom4326"} for p in polys],
            "anomalias": anomalías,
        }
        write_json(d / f"llamadas_{layer}.json", llamadas)
        write_json(d / f"poligonos_{layer}_4326.geojson", {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"poly_idx": p["poly_idx"], **p["properties"]},
             "geometry": mapping(p["geom4326"])} for p in polys]})
    write_json(d / "resumen.json", resumen)


# ----------------------------------------------------------------------------- 5 BÜK200
BUEK_POINTS = [("P3", 11.09105, 52.35035), ("Muenchen", 11.58, 48.14), ("Koeln_rural", 6.80, 50.85),
               ("Brandenburg_rural", 13.40, 52.20), ("SH_rural", 9.80, 54.30)]
HORIZON_COLS = ["nr", "symbol", "ober_dm", "unter_dm", "stratigraphie", "herkunft", "geogenese",
                "grobboden_fraktion", "grobboden_summe", "bodenart_ka5", "humus_ka5", "carbonat_ka5",
                "gefuege", "rohdichte_lagerungsdichte", "torfart", "zersetzungsstufe",
                "substanzvolumen", "bodenaciditaet_ka5"]


def parse_profiles(text: str) -> list[dict]:
    """Mismo parser que paso4_buek200.py: página FISBo -> perfiles -> horizontes."""
    import re

    def clean(s):
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xad", "")).strip()

    profiles = []
    for chunk in text.split('<table class="profil"')[1:]:
        head = chunk.split("</th></tr>", 1)[0]
        divs = [clean(x) for x in re.findall(r"<div[^>]*>(.*?)</div>", head, re.S)]
        prof = {"cabecera": divs, "horizontes": []}
        for x in divs:
            if ":" in x:
                k, v = x.split(":", 1)
                prof[k.strip()] = v.strip()
        for row in re.split(r"onmouseover=", chunk)[1:]:
            cells = re.findall(r"<td>([^<]*)</td>", row)
            if len(cells) >= len(HORIZON_COLS):
                prof["horizontes"].append(dict(zip(HORIZON_COLS, [c.strip() for c in cells])))
        profiles.append(prof)
    return profiles


def fisbo(check, label, url, d: Path, name: str):
    url = html.unescape(url)
    rec = fetch(check, label, url, timeout=TIMEOUT)
    (d / "_html").mkdir(parents=True, exist_ok=True)
    (d / "_html" / f"{name}.html").write_bytes(rec["content"])
    profs = parse_profiles(rec["text"]) if not rec["error"] else []
    return {"_llamada": call_meta(rec), "html_guardado": f"_html/{name}.html", "n_perfiles": len(profs),
            "perfiles": profs}


def profile_stats(all_profiles: list[dict]) -> dict:
    n_prof = len(all_profiles)
    hz = [h for p in all_profiles for h in p["horizontes"]]
    top = [p["horizontes"][0] for p in all_profiles if p["horizontes"]]

    def frac_empty(rows, k):
        return f"{sum(1 for h in rows if not h.get(k))}/{len(rows)}"

    return {
        "n_perfiles": n_prof, "n_horizontes": len(hz),
        "perfiles_sin_horizontes": sum(1 for p in all_profiles if not p["horizontes"]),
        "perfiles_con_Landnutzung": f"{sum(1 for p in all_profiles if p.get('Landnutzung'))}/{n_prof}",
        "claves_cabecera_vistas": sorted({k for p in all_profiles for k in p if k not in ("cabecera", "horizontes")}),
        "horizontes_vacios": {k: frac_empty(hz, k) for k in ("bodenart_ka5", "humus_ka5", "bodenaciditaet_ka5",
                                                             "carbonat_ka5")},
        "horizonte_superior_vacios": {k: frac_empty(top, k) for k in ("bodenart_ka5", "humus_ka5",
                                                                      "bodenaciditaet_ka5", "carbonat_ka5")},
    }


def check5(fields):
    d = OUT / "5_buek200"
    layers = json.loads(BUEK_LAYERS.read_text(encoding="utf-8"))["layers"]
    resumen = {"puntos": [], "f82_poligono": None}
    all_profiles = []

    def sheet_layer(blattnum):
        key = (blattnum or "").replace(" ", "").upper()
        return next((l for l in layers if key and l["name"].upper().replace(" ", "").startswith(key)), None)

    for name, lon, lat in BUEK_POINTS:
        res = {"punto": name, "lon": lon, "lat": lat}
        idx = fetch("5", f"{name} capa 0", f"{BUEK_URL}/0/query", {
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false", "f": "json"})
        idx_j = as_json(idx) or {}
        feats = idx_j.get("features", [])
        res["capa0"] = {"_llamada": call_meta(idx), "respuesta": trim_geoms(idx_j or idx["text"][:2000])}
        res["hojas_devueltas"] = [f["attributes"].get("BLATTNUM") for f in feats]
        blatt = feats[0]["attributes"].get("BLATTNUM") if feats else None
        sl = sheet_layer(blatt)
        res["hoja"], res["capa_hoja"] = blatt, sl
        res["mapeo_ok"] = sl is not None
        if sl:
            q = fetch("5", f"{name} capa {sl['id']} ({sl['name']})", f"{BUEK_URL}/{sl['id']}/query", {
                "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false",
                "f": "json"})
            qj = as_json(q) or {}
            res["consulta_hoja"] = {"_llamada": call_meta(q), "respuesta": trim_geoms(qj or q["text"][:2000])}
            sf = qj.get("features", [])
            res["n_unidades"] = len(sf)
            attrs = sf[0]["attributes"] if sf else {}
            res["atributos"] = attrs
            if attrs.get("Profile"):
                pf = fisbo("5", f"{name} perfil FISBo", attrs["Profile"], d, f"perfil_{name}")
                res["perfil_fisbo"] = pf
                all_profiles += pf["perfiles"]
        write_json(d / f"punto_{name}.json", res)
        resumen["puntos"].append({k: res.get(k) for k in ("punto", "lon", "lat", "hojas_devueltas", "hoja",
                                                           "mapeo_ok", "n_unidades")}
                                 | {"capa_id": sl and sl["id"], "capa_nombre": sl and sl["name"],
                                    "Legende": res.get("atributos", {}).get("Legende"),
                                    "n_perfiles": (res.get("perfil_fisbo") or {}).get("n_perfiles"),
                                    "fisbo_stats": profile_stats(res["perfil_fisbo"]["perfiles"])
                                    if res.get("perfil_fisbo") else None})

    # b) polígono del campo f82
    fld = fields["f82"]
    geom = fld["geom"]
    poly = geom if geom.geom_type == "Polygon" else max(geom.geoms, key=lambda g: g.area)
    rings = [list(map(list, poly.exterior.coords))] + [list(map(list, r.coords)) for r in poly.interiors]
    c = geom.centroid
    idx = fetch("5", "f82 capa 0 (centroide)", f"{BUEK_URL}/0/query", {
        "geometry": f"{c.x},{c.y}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "BLATTNUM", "returnGeometry": "false", "f": "json"})
    blatt = ((as_json(idx) or {}).get("features") or [{}])[0].get("attributes", {}).get("BLATTNUM")
    sl = sheet_layer(blatt)
    params = {"geometry": json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}}),
              "geometryType": "esriGeometryPolygon", "inSR": 4326, "outSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "true", "f": "json"}
    url = f"{BUEK_URL}/{sl['id']}/query"
    get_url = requests.Request("GET", url, params=params).prepare().url
    # URLs muy largas fallan en IIS/ArcGIS: si pasa de ~4000 caracteres se usa POST (mismos parámetros)
    q = fetch("5", f"f82 polígono capa {sl['id']}", url, data=params) if len(get_url) > 4000 else \
        fetch("5", f"f82 polígono capa {sl['id']}", url, params)
    qj = as_json(q) or {}
    feats = qj.get("features", [])
    units = []
    union_parts = []
    field25 = to25832(geom)
    for f in feats:
        a = f["attributes"]
        g = None
        if f.get("geometry", {}).get("rings"):
            from shapely.geometry import Polygon
            from shapely.validation import make_valid
            g = make_valid(unary_union([Polygon(r) for r in f["geometry"]["rings"]]))
            union_parts.append(to25832(g))
        units.append({"OBJECTID": a.get("OBJECTID"), "TKLE_NR": a.get("TKLE_NR"), "Legende": a.get("Legende"),
                      "LEG_TEXT": a.get("LEG_TEXT"), "Profile": a.get("Profile"),
                      "n_vertices": len(_flatten(f.get("geometry", {}).get("rings"))),
                      "area_dentro_campo_ha": round(to25832(g).intersection(field25).area / 10_000, 4) if g else None})
    union = unary_union(union_parts) if union_parts else None
    pf_stats = []
    for u in units:
        if u["Profile"]:
            pf = fisbo("5", f"f82 perfil FISBo TKLE {u['TKLE_NR']}", u["Profile"], d, f"perfil_f82_{u['TKLE_NR']}")
            all_profiles += pf["perfiles"]
            u["n_perfiles"] = pf["n_perfiles"]
            pf_stats.append({"TKLE_NR": u["TKLE_NR"], **pf})
    # Contraste independiente: unidades distintas en una rejilla de 100 m dentro del campo (consulta por punto)
    _, gpts = grid_points(geom, step=100)
    seen = {}
    for i, p in enumerate(gpts):
        lon, lat = TO_4326.transform(p.x, p.y)
        r = fetch("5", f"f82 contraste punto {i}", url, {
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "OBJECTID,TKLE_NR,Legende",
            "returnGeometry": "false", "f": "json"})
        for f in (as_json(r) or {}).get("features", []):
            seen.setdefault(f["attributes"]["OBJECTID"], f["attributes"])
    out_b = {"field_id": "f82", "fieldName": fld["props"]["fieldName"], "n_vertices_poligono_enviado": len(_flatten(rings)),
             "hoja": blatt, "capa_hoja": sl, "metodo_http": q["method"], "longitud_url_get": len(get_url),
             "_llamada": call_meta(q), "n_unidades": len(feats), "unidades": units,
             "fraccion_campo_cubierta_por_union": round(union.intersection(field25).area / field25.area, 4) if union else None,
             "contraste_rejilla_100m": {"n_puntos": len(gpts), "OBJECTID_distintos": sorted(seen),
                                       "unidades": list(seen.values()),
                                       "todas_incluidas_en_consulta_poligono":
                                           set(seen) <= {u["OBJECTID"] for u in units}},
             "respuesta": trim_geoms(qj or q["text"][:3000])}
    write_json(d / "f82_poligono.json", out_b)
    write_json(d / "f82_perfiles_fisbo.json", pf_stats)
    write_json(d / "f82_unidades_4326.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": f["attributes"],
         "geometry": {"type": "Polygon", "coordinates": f["geometry"]["rings"]}} for f in feats if f.get("geometry")]})
    resumen["f82_poligono"] = {k: out_b[k] for k in ("hoja", "metodo_http", "longitud_url_get", "n_unidades",
                                                     "fraccion_campo_cubierta_por_union", "contraste_rejilla_100m")}
    resumen["f82_poligono"]["unidades"] = units
    resumen["fisbo_stats_global"] = profile_stats(all_profiles)
    write_json(d / "resumen.json", resumen)


# ----------------------------------------------------------------------------- 6 SoilGrids
SG_PROPS = ["clay", "sand", "silt", "phh2o", "soc", "wv0033", "wv1500"]
SG_DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]
SG_STATS = ["mean", "Q0.05", "Q0.95"]


def check6(fields):
    import numpy as np
    import rasterio
    import math
    from rasterio.windows import Window, from_bounds

    d = OUT / "6_soilgrids"
    f82 = fields["f82"]["geom"]
    mx, my = TO_25832.transform(11.58, 48.14)
    munich = shp_transform(lambda x, y, z=None: TO_4326.transform(x, y),
                           Point(mx, my).buffer(500, cap_style=3))  # cuadrado de 1 km² en 25832
    boxes = {"f82_Mittelbreite": f82.bounds, "Muenchen_1km2": munich.bounds}
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_CONNECTTIMEOUT="20",
               GDAL_HTTP_TIMEOUT="20", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="3")
    # ¿qué propiedades publica files.isric.org/latest/data/? (listado HTML del directorio)
    import re
    listado = {}
    for sub in ["", "wv0033/", "wv1500/"]:
        r = fetch("6", f"listado latest/data/{sub}", "https://files.isric.org/soilgrids/latest/data/" + sub, retries=1)
        listado[sub or "/"] = {"http": r["status"], "error": r["error"],
                               "entradas": sorted(set(re.findall(r'href="([^"?/][^"]*)"', r["text"])))}
    write_json(d / "listado_directorios.json", listado)
    rows = []
    t_all = time.time()
    with rasterio.Env(**env):
        for prop in SG_PROPS:
            for depth in SG_DEPTHS:
                for stat in SG_STATS:
                    url = SG_VRT.format(prop=prop, depth=depth, stat=stat)
                    head = fetch("6", f"HEAD {prop}_{depth}_{stat}.vrt", url, retries=0, method="HEAD")  # existe el VRT?
                    row = {"prop": prop, "depth": depth, "stat": stat, "url": url,
                           "vrt_http": head["status"], "vrt_content_length": head["headers"].get("Content-Length")}
                    t0 = time.time()
                    try:
                        with rasterio.open("/vsicurl/" + url) as src:
                            row.update(crs=src.crs.to_string()[:80] if src.crs else None, res=src.res,
                                       nodata=src.nodata, dtype=src.dtypes[0])
                            tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                            for bname, (x0, y0, x1, y1) in boxes.items():
                                tb = time.time()
                                xs, ys = tr.transform([x0, x1, x0, x1], [y0, y0, y1, y1])
                                w = from_bounds(min(xs), min(ys), max(xs), max(ys), src.transform)
                                c0, r0 = math.floor(w.col_off), math.floor(w.row_off)
                                win = Window(c0, r0, math.ceil(w.col_off + w.width) - c0,
                                             math.ceil(w.row_off + w.height) - r0)
                                arr = src.read(1, window=win)
                                nd = int((arr == -32768).sum()) + (int((arr == src.nodata).sum())
                                                                    if src.nodata not in (None, -32768) else 0)
                                valid = arr[(arr != -32768) & (arr != (src.nodata if src.nodata is not None else -32768))]
                                row[bname] = {"shape": list(arr.shape), "n_pixeles": int(arr.size),
                                              "n_nodata_-32768": int((arr == -32768).sum()), "n_nodata_total": nd,
                                              "min": int(valid.min()) if valid.size else None,
                                              "max": int(valid.max()) if valid.size else None,
                                              "media": round(float(valid.mean()), 2) if valid.size else None,
                                              "valores": arr.tolist() if arr.size <= 100 else "omitido (>100 px)",
                                              "segundos": round(time.time() - tb, 2)}
                        row["ok"] = True
                    except Exception as exc:
                        row["ok"] = False
                        row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                    row["segundos_capa"] = round(time.time() - t0, 2)
                    log_call("6", f"rasterio {prop}_{depth}_{stat}", "VSICURL", url,
                             "ok" if row["ok"] else "fail", row["segundos_capa"], "", row.get("error", ""))
                    print(f"  [6] {prop} {depth} {stat}: {'OK' if row['ok'] else row['error'][:100]} "
                          f"({row['segundos_capa']} s)")
                    rows.append(row)
    total = round(time.time() - t_all, 1)
    ok = [r for r in rows if r["ok"]]
    resumen = {"cajas_lonlat": {k: [round(v, 6) for v in b] for k, b in boxes.items()},
               "combinaciones": len(rows), "ok": len(ok),
               "fallidas": [f"{r['prop']}_{r['depth']}_{r['stat']}: {r.get('error')}" for r in rows if not r["ok"]],
               "segundos_total": total,
               "segundos_por_capa": {"media": round(statistics.mean(r["segundos_capa"] for r in rows), 2),
                                     "min": min(r["segundos_capa"] for r in rows),
                                     "max": max(r["segundos_capa"] for r in rows)},
               "capas_con_nodata": [f"{r['prop']}_{r['depth']}_{r['stat']} {b}: {r[b]['n_nodata_total']}/{r[b]['n_pixeles']}"
                                    for r in ok for b in boxes if r[b]["n_nodata_total"]]}
    write_json(d / "resultados.json", rows)
    write_json(d / "resumen.json", resumen)


# ----------------------------------------------------------------------------- 7 fuera de cobertura
def check7(fields):
    d = OUT / "7_fuera_cobertura"
    resumen = []
    for layer in ["L816", "L849"]:
        rec = gfi("7", f"{layer} München", layer, 11.58, 48.14)
        data = dump(d / f"Muenchen_{layer}.json", rec)
        resumen.append({"layer": layer, "http": rec["status"], "seconds": rec["seconds"], "error": rec["error"],
                        "n_features": len((data or {}).get("features", [])) if isinstance(data, dict) else None,
                        "cuerpo": rec["text"][:500]})
    write_json(d / "resumen.json", resumen)


# ----------------------------------------------------------------------------- 8 estabilidad
def check8(fields):
    d = OUT / "8_estabilidad"
    _, pts = grid_points(fields["f51"]["geom"], step=25)
    step = max(1, len(pts) // 50)
    sel = [pts[i * step] for i in range(50)]
    sel4326 = [TO_4326.transform(p.x, p.y) for p in sel]

    def one(i):
        lon, lat = sel4326[i]
        rec = gfi("8", f"estabilidad L849 #{i}", "L849", lon, lat)
        data = as_json(rec) if not rec["error"] else None
        return {"i": i, "lon": round(lon, 6), "lat": round(lat, 6), "http": rec["status"],
                "seconds_ultimo_intento": rec["seconds"], "intentos": rec["attempts"],
                "fallo_primer_intento": bool(rec["attempts"][0]["error"]), "fallo_final": bool(rec["error"]),
                "error": rec["error"], "n_features": len((data or {}).get("features", [])),
                "FL_NR": (((data or {}).get("features") or [{}])[0].get("properties") or {}).get("FL_NR"),
                "headers_ultimo": {k: v for k, v in rec["headers"].items()},
                "cuerpo_si_error": rec["text"][:500] if rec["error"] else ""}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(one, range(50)))
    wall = round(time.time() - t0, 2)
    times = [a["seconds"] for r in res for a in r["intentos"]]
    first = [r["intentos"][0]["seconds"] for r in res]
    resumen = {"n_peticiones": 50, "concurrencia": 4, "segundos_reloj_total": wall,
               "fallos_primer_intento": sum(r["fallo_primer_intento"] for r in res),
               "fallos_finales": sum(r["fallo_final"] for r in res),
               "intentos_totales": len(times),
               "tiempo_primer_intento": {"media": round(statistics.mean(first), 3),
                                         "mediana": round(statistics.median(first), 3), "max": max(first),
                                         "min": min(first)},
               "tiempo_todos_intentos": {"media": round(statistics.mean(times), 3), "max": max(times)},
               "errores": [{"i": r["i"], "intentos": r["intentos"], "cuerpo": r["cuerpo_si_error"]}
                           for r in res if r["fallo_primer_intento"]],
               "cabeceras_de_limite_vistas": sorted({k for r in res for k in r["headers_ultimo"]
                                                     if any(s in k.lower() for s in ("rate", "retry", "limit"))}),
               "cabeceras_ejemplo": res[0]["headers_ultimo"],
               "sin_features": sum(1 for r in res if not r["fallo_final"] and r["n_features"] == 0),
               "FL_NR_distintos": len({r["FL_NR"] for r in res if r["FL_NR"]})}
    write_json(d / "peticiones.json", res)
    write_json(d / "resumen.json", resumen)


CHECKS = {"1": check1, "2": check2, "3": check3, "4": check4, "5": check5, "6": check6, "7": check7, "8": check8}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    fields = load_fields()
    for k in sys.argv[1:] or list(CHECKS):
        print(f"\n===== Comprobación {k} =====")
        t = time.time()
        try:
            CHECKS[k](fields)
        except Exception as exc:  # que una comprobación rota no tumbe las demás
            import traceback
            traceback.print_exc()
            (OUT / f"_ERROR_comprobacion_{k}.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"===== {k} terminada en {time.time() - t:.1f} s")
