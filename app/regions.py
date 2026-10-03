"""
Límites de los Länder (BKG VG250, WFS oficial), cacheados en disco.

Sirve para saber de antemano si un punto cae en Niedersachsen (cobertura de LBEG) sin
preguntar a NIBIS, que fuera de cobertura puede tardar >80 s en devolver features: [].
"""

from __future__ import annotations

import json
from functools import cache as memo

from shapely.geometry import shape
from shapely.ops import transform as shp_transform, unary_union

from . import cache
from .fields import TO_UTM

VG250_WFS = "https://sgx.geodatenzentrum.de/wfs_vg250"
VG250_PARAMS = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
                "TYPENAMES": "vg250:vg250_lan", "OUTPUTFORMAT": "application/json",
                "SRSNAME": "EPSG:4326", "COUNT": "50"}


@memo
def land_utm(name: str):
    """Geometría (EPSG:25832) de un Land, solo superficie terrestre (gf = 4). None si no hay red ni caché."""
    try:
        c = cache.fetch("regions", VG250_WFS, VG250_PARAMS, timeout=90,
                        validate=lambda r: None if "json" in r.headers.get("Content-Type", "") else r.text[:200])
    except cache.FetchError as exc:
        print(f"  [regions] VG250 no disponible: {exc}")
        return None
    feats = [f for f in json.loads(c.content)["features"]
             if f["properties"].get("gen") == name and f["properties"].get("gf") == 4]
    if not feats:
        return None
    return shp_transform(TO_UTM.transform, unary_union([shape(f["geometry"]) for f in feats]))
