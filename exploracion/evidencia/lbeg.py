"""
GetFeatureInfo contra el WMS NIBIS/LBEG (PkgId=24).

Cómo se pregunta "¿qué hay en este punto?" a un WMS: se construye un recuadro
diminuto alrededor del punto en EPSG:25832, se pide un "mapa imaginario" de
WIDTH x HEIGHT píxeles y se consulta el píxel central (I, J).
"""

from __future__ import annotations

import time

from common import fetch, to_25832

NIBIS_URL = "https://nibis.lbeg.de/net3/public/ogc.ashx"
PKG_ID = 24
NO_HIT_MARKERS = ("Keine Treffer",)


def gfi_params(layer: str, lon: float, lat: float, info_format: str = "application/geo+json",
               radius_m: float = 50, size_px: int = 101, feature_count: int = 1) -> dict:
    x, y = to_25832(lon, lat)
    centre = size_px // 2
    return {
        "PKGID": PKG_ID,
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": layer,
        "QUERY_LAYERS": layer,
        "STYLES": "",
        "CRS": "EPSG:25832",  # eje E,N (x,y) en este servicio
        "BBOX": f"{x - radius_m},{y - radius_m},{x + radius_m},{y + radius_m}",
        "WIDTH": size_px,
        "HEIGHT": size_px,
        "I": centre,
        "J": centre,
        "INFO_FORMAT": info_format,
        "FEATURE_COUNT": feature_count,
    }


# NIBIS devuelve HTTP 200 con un error dentro cuando está saturado, p.ej.
# "Error 503.2 - Concurrent request limit exceeded" (ServiceException en geo+json,
# "Ein Fehler trat beim Abfragen der Ebene ..." en text/plain).
ERROR_MARKERS = ("ServiceException", "Ein Fehler trat", "Error 503", "Service Busy")
BUSY_WAITS = [10, 20, 40]  # s de espera entre reintentos si el servidor dice "ocupado"


def get_feature_info(source: str, label: str, layer: str, lon: float, lat: float,
                     info_format: str = "application/geo+json", radius_m: float = 50,
                     timeout: float = 20) -> dict:
    params = gfi_params(layer, lon, lat, info_format, radius_m)
    for attempt, wait in enumerate([0] + BUSY_WAITS):
        if wait:
            print(f"  LBEG ocupado (503.2 dentro de HTTP 200); reintento en {wait} s...")
            time.sleep(wait)
        rec = fetch(source, label + (f" (reintento {attempt})" if attempt else ""), NIBIS_URL,
                    params, timeout=timeout)
        if not is_service_error(rec):
            break
    rec["info_format"] = info_format
    rec["radius_m"] = radius_m
    if is_service_error(rec) and not rec["error"]:
        rec["error"] = "service_error: el servidor devolvió un error dentro de HTTP 200 (ver cuerpo)"
    rec["hit"] = is_hit(rec)
    return rec


def is_service_error(rec: dict) -> bool:
    return rec["status"] == 200 and any(m in rec["text"] for m in ERROR_MARKERS)


def is_hit(rec: dict) -> bool:
    """True si la respuesta trae al menos un objeto con atributos."""
    if rec["status"] != 200 or not rec["text"].strip() or is_service_error(rec):
        return False
    if any(m in rec["text"] for m in NO_HIT_MARKERS):
        return False
    from common import as_json
    data = as_json(rec)
    if isinstance(data, dict) and "features" in data:
        return len(data["features"]) > 0
    return True


def feature_properties(rec: dict) -> list[dict]:
    from common import as_json
    data = as_json(rec)
    if isinstance(data, dict):
        return [f.get("properties") or {} for f in data.get("features", [])]
    return []
