"""
BGR BÜK200 (1:200.000, toda Alemania) + perfiles FISBo.

- ArcGIS REST: capa 0 (índice de hojas) con el polígono del campo -> BLATTNUM ("CC 3926")
  -> capa de la hoja cuyo name empieza por "CC3926" (lista de capas del MapServer, cacheada).
- La hoja se consulta con el polígono del campo por POST (esriGeometryPolygon, inSR=4326).
  BÜK200 NUNCA devuelve geometría (exploracion/evidencia/samples2/RESUMEN2.md §5): con 1 unidad, valor uniforme en el campo;
  con varias, se consulta por punto en una rejilla de 100 m y cada punto de 25 m toma la
  unidad del punto consultado más cercano.
- Perfil FISBo de cada unidad (URL del campo Profile, "&amp;" -> "&"), cacheado por URL
  (= por TKLE_NR). Perfiles con Landnutzung "Acker" (si no hay, todos), ponderados por
  Flächenanteil; en cada perfil, horizontes que solapan 0-3 dm ponderados por el solape.
- clay/silt = centroide KA5, sand = 100 - clay - silt; σ_clay, σ_silt = rango/√12,
  σ_sand = √(σ_clay² + σ_silt²); a cada σ se le suma (en cuadratura) la desviación estándar
  entre perfiles.
- soc = punto medio de la clase de humus (% MO) / 1,72 × 10 (g/kg); h7 -> horizonte sin dato.
- ph_cacl2 = punto medio de la clase de acidez (low/high = límites); vacía -> sin dato.
  No se mezcla con ph_h2o.
"""

from __future__ import annotations

import html
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import shapely
from shapely.geometry import MultiPolygon

from .. import cache
from ..lookups import ka5_acidez, ka5_bodenart, ka5_humus
from .base import Source, register_source, row

BUEK_URL = "https://services.bgr.de/arcgis/rest/services/boden/buek200/MapServer"
TOP_DM = 3.0                       # topsoil 0-30 cm = 0-3 dm
POINT_STEP_M = 100.0               # rejilla de consultas por punto si hay varias unidades
MO_TO_SOC = 1 / 1.72               # materia orgánica -> carbono orgánico (factor de van Bemmelen)
SQRT12 = math.sqrt(12)

HORIZON_COLS = ["nr", "symbol", "ober_dm", "unter_dm", "stratigraphie", "herkunft", "geogenese",
                "grobboden_fraktion", "grobboden_summe", "bodenart_ka5", "humus_ka5", "carbonat_ka5",
                "gefuege", "rohdichte_lagerungsdichte", "torfart", "zersetzungsstufe",
                "substanzvolumen", "bodenaciditaet_ka5"]


def _json_ok(r) -> str | None:
    try:
        d = json.loads(r.content)
    except ValueError:
        return "respuesta no es JSON: " + r.text[:200]
    return f"error ArcGIS: {d['error']}" if isinstance(d, dict) and "error" in d else None


def _get_json(url: str, params: dict, *, post: bool = False) -> dict:
    c = cache.fetch("buek200", url, None if post else params, method="POST" if post else "GET",
                    data=params if post else None, timeout=60, validate=_json_ok)
    return json.loads(c.content)


def sheet_layers() -> list[dict]:
    return _get_json(BUEK_URL, {"f": "json"}).get("layers", [])


def sheet_layer(blattnum: str) -> dict | None:
    key = (blattnum or "").replace(" ", "").upper()
    return next((l for l in sheet_layers() if key and l["name"].upper().replace(" ", "").startswith(key)), None)


def esri_rings(geom) -> list:
    """Shapely (EPSG:4326) -> anillos Esri (exterior en sentido horario, huecos antihorario)."""
    parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    rings = []
    for p in parts:
        p = shapely.geometry.polygon.orient(p, sign=-1.0)
        rings.append([[round(x, 7), round(y, 7)] for x, y in p.exterior.coords])
        rings += [[[round(x, 7), round(y, 7)] for x, y in r.coords] for r in p.interiors]
    return rings


def query_polygon(layer_id: int, geom, out_fields: str = "*") -> list[dict]:
    params = {"geometry": json.dumps({"rings": esri_rings(geom), "spatialReference": {"wkid": 4326}},
                                     separators=(",", ":")),
              "geometryType": "esriGeometryPolygon", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
              "outFields": out_fields, "returnGeometry": "false", "f": "json"}
    return [f["attributes"] for f in _get_json(f"{BUEK_URL}/{layer_id}/query", params, post=True).get("features", [])]


def query_point(layer_id: int, lon: float, lat: float) -> list[dict]:
    params = {"geometry": f"{lon:.6f},{lat:.6f}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "TKLE_NR", "returnGeometry": "false",
              "f": "json"}
    return [f["attributes"] for f in _get_json(f"{BUEK_URL}/{layer_id}/query", params).get("features", [])]


# ---------------- FISBo ----------------

def parse_profiles(text: str) -> list[dict]:
    """Página FISBo -> perfiles -> horizontes (mismo parser que exploracion/evidencia/comprobaciones2.py)."""
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
        for r in re.split(r"onmouseover=", chunk)[1:]:
            cells = re.findall(r"<td>([^<]*)</td>", r)
            if len(cells) >= len(HORIZON_COLS):
                prof["horizontes"].append(dict(zip(HORIZON_COLS, [c.strip() for c in cells])))
        profiles.append(prof)
    return profiles


def fisbo_profiles(url: str) -> tuple[list[dict], str, str]:
    url = html.unescape(url)
    c = cache.fetch("buek200", url, timeout=60,
                    validate=lambda r: None if 'class="profil"' in r.text else "FISBo sin perfiles: " + r.text[:200])
    return parse_profiles(c.content.decode("utf-8", errors="replace")), c.url, c.fetched_at


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", ".").replace("%", "").strip())
    except ValueError:
        return None


def _wmean(pairs: list[tuple[float, float]]) -> float:
    tw = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / tw


def profile_topsoil(prof: dict) -> dict:
    """Valores 0-3 dm de un perfil: cada propiedad -> (valor, σ, low, high) o None. + clases usadas."""
    acc = {k: [] for k in ("clay", "silt", "sand", "soc", "ph_cacl2")}
    classes = {"bodenart": [], "humus": [], "acidez": []}
    for h in prof["horizontes"]:
        top, bot = _num(h["ober_dm"]), _num(h["unter_dm"])
        if top is None or bot is None:
            continue
        w = min(bot, TOP_DM) - max(top, 0.0)
        if w <= 0:
            continue
        ba = ka5_bodenart(h["bodenart_ka5"])
        classes["bodenart"].append(h["bodenart_ka5"])
        if ba:
            sc = (ba["clay_max"] - ba["clay_min"]) / SQRT12
            ss = (ba["silt_max"] - ba["silt_min"]) / SQRT12
            acc["clay"].append((ba["clay"], sc, ba["clay_min"], ba["clay_max"], w))
            acc["silt"].append((ba["silt"], ss, ba["silt_min"], ba["silt_max"], w))
            acc["sand"].append((100 - ba["clay"] - ba["silt"], math.hypot(sc, ss),
                                max(0.0, 100 - ba["clay_max"] - ba["silt_max"]),
                                100 - ba["clay_min"] - ba["silt_min"], w))
        hu = ka5_humus(h["humus_ka5"])
        classes["humus"].append(h["humus_ka5"])
        if hu and hu[1] is not None:               # h7 (≥30 % MO, sin máximo) -> sin dato
            lo, hi = hu[0] * MO_TO_SOC * 10, hu[1] * MO_TO_SOC * 10
            acc["soc"].append(((lo + hi) / 2, (hi - lo) / SQRT12, lo, hi, w))
        ac = ka5_acidez(h["bodenaciditaet_ka5"])
        classes["acidez"].append(h["bodenaciditaet_ka5"])
        if ac:
            acc["ph_cacl2"].append(((ac[0] + ac[1]) / 2, (ac[1] - ac[0]) / SQRT12, ac[0], ac[1], w))
    out = {}
    for k, items in acc.items():
        if not items:
            out[k] = None
            continue
        out[k] = tuple(_wmean([(it[j], it[4]) for it in items]) for j in range(4))
    out["classes"] = classes
    return out


def unit_values(profiles: list[dict]) -> tuple[dict, dict]:
    """Combina los perfiles de una unidad. Devuelve ({param: (v, σ, low, high) | None}, resumen)."""
    acker = [p for p in profiles if "acker" in p.get("Landnutzung", "").lower()]
    used = acker or profiles
    tops = []
    for p in used:
        share = _num(p.get("Flächenanteil", "")) or 0.0
        tops.append((p, profile_topsoil(p), share if share > 0 else 1.0))
    vals = {}
    for k in ("clay", "silt", "sand", "soc", "ph_cacl2"):
        items = [(t[k], w) for _, t, w in tops if t[k] is not None]
        if not items:
            vals[k] = None
            continue
        tw = sum(w for _, w in items)
        v = sum(x[0] * w for x, w in items) / tw
        sig_in = sum(x[1] * w for x, w in items) / tw
        sd_between = math.sqrt(sum(w * (x[0] - v) ** 2 for x, w in items) / tw)
        lo = sum(x[2] * w for x, w in items) / tw
        hi = sum(x[3] * w for x, w in items) / tw
        vals[k] = (v, math.hypot(sig_in, sd_between), lo, hi)
    summary = {"perfiles_usados": len(used), "perfiles_total": len(profiles),
               "filtro": "Acker" if acker else "todos (ninguno de Acker)",
               "perfiles": [{"anteil": w, "landnutzung": p.get("Landnutzung", "")[:40],
                             "bodenart": t["classes"]["bodenart"], "humus": t["classes"]["humus"],
                             "acidez": t["classes"]["acidez"]} for p, t, w in tops]}
    return vals, summary


@register_source
class BUEK200(Source):
    name = "buek200"
    title = "BGR BÜK200 + perfiles FISBo"
    parameters = ["clay", "sand", "silt", "soc", "ph_cacl2"]
    coverage = "Toda Alemania"
    resolution = "Unidades 1:200.000 (sin geometría: valor por unidad; varias unidades -> rejilla de 100 m)"
    notes = ("Clases KA5 de los perfiles FISBo de la unidad (Acker, ponderados por Flächenanteil, horizontes "
             "0-3 dm) -> centroide de textura, punto medio de humus (/1,72) y de acidez. σ = rango/√12 + "
             "dispersión entre perfiles. pH en CaCl2: no comparable con pH en agua.")

    def fetch(self, field, parameters=None) -> list[dict]:
        params = [p for p in (parameters or self.parameters) if p in self.parameters]
        g = field.grid
        n = len(g)
        try:
            unit_of_point, units, layer = self._units(field)
        except cache.FetchError as exc:
            return [row(field, i, self.name, p, status="error", original=f"BÜK200: {exc}",
                        provenance=f"BGR BÜK200 {BUEK_URL}") for i in range(n) for p in params]

        # Valores por unidad (TKLE_NR) desde FISBo
        per_unit: dict = {}
        for tk, attrs in units.items():
            prov = f"BGR BÜK200 capa {layer['id']} {layer['name']} · TKLE_NR {tk} · Legende {attrs.get('Legende')}"
            if not attrs.get("Profile"):
                per_unit[tk] = ("no_coverage", "unidad sin perfil FISBo", prov)
                continue
            try:
                profiles, url, fetched = fisbo_profiles(attrs["Profile"])
            except cache.FetchError as exc:
                per_unit[tk] = ("error", f"FISBo: {exc}", prov)
                continue
            vals, summary = unit_values(profiles)
            summary.update({"TKLE_NR": tk, "Legende": attrs.get("Legende"), "LEG_TEXT": attrs.get("LEG_TEXT")})
            per_unit[tk] = ("ok", vals, f"{prov} · FISBo {url} · descargado {fetched[:10]}", summary)

        rows = []
        for i in range(n):
            tk = unit_of_point[i]
            for p in params:
                if tk is None:
                    rows.append(row(field, i, self.name, p, status="no_coverage",
                                    original="BÜK200 sin unidad en este punto", provenance=f"BGR BÜK200 {BUEK_URL}"))
                    continue
                u = per_unit[tk]
                if u[0] != "ok":
                    rows.append(row(field, i, self.name, p, status=u[0], original=u[1], provenance=u[2]))
                    continue
                v = u[1][p]
                orig = json.dumps(u[3], ensure_ascii=False, separators=(",", ":"))
                if v is None:
                    rows.append(row(field, i, self.name, p, status="no_coverage", original=orig, provenance=u[2]))
                else:
                    rows.append(row(field, i, self.name, p, value=round(v[0], 2), sigma=round(v[1], 3),
                                    low=round(v[2], 2), high=round(v[3], 2), original=orig, provenance=u[2]))
        return rows

    def _units(self, field):
        """Unidad (TKLE_NR) de cada punto de la rejilla, atributos por unidad y capa de la hoja."""
        g = field.grid
        sheets = [a.get("BLATTNUM") for a in query_polygon(0, field.geom, "BLATTNUM")]
        units: dict = {}
        layer = None
        for s in sheets:                                 # un campo puede tocar 2 hojas
            lay = sheet_layer(s)
            if not lay:
                continue
            layer = layer or lay
            for a in query_polygon(lay["id"], field.geom):
                if a.get("TKLE_NR") is not None:
                    units.setdefault(a["TKLE_NR"], a | {"_layer": lay["id"]})
        if not units or layer is None:
            return [None] * len(g), {}, layer or {"id": "-", "name": "-"}
        if len(units) == 1:
            tk = next(iter(units))
            return [tk] * len(g), units, layer

        # Varias unidades: consulta por punto en rejilla de 100 m y vecino más cercano
        cell = np.floor(g.x / POINT_STEP_M).astype(int) * 100_000 + np.floor(g.y / POINT_STEP_M).astype(int)
        probes = []
        for c in np.unique(cell):
            idx = np.flatnonzero(cell == c)
            cx = (np.floor(g.x[idx[0]] / POINT_STEP_M) + 0.5) * POINT_STEP_M
            cy = (np.floor(g.y[idx[0]] / POINT_STEP_M) + 0.5) * POINT_STEP_M
            probes.append(idx[np.argmin((g.x[idx] - cx) ** 2 + (g.y[idx] - cy) ** 2)])
        lay_ids = sorted({u["_layer"] for u in units.values()})

        def probe(i):
            for lid in lay_ids:
                hits = [a["TKLE_NR"] for a in query_point(lid, g.lon[i], g.lat[i]) if a.get("TKLE_NR") in units]
                if hits:
                    return hits[0]
            return None

        with ThreadPoolExecutor(max_workers=4) as ex:
            found = list(ex.map(probe, probes))
        ok = [(i, tk) for i, tk in zip(probes, found) if tk is not None]
        if not ok:
            return [None] * len(g), units, layer
        px = np.array([g.x[i] for i, _ in ok])
        py = np.array([g.y[i] for i, _ in ok])
        nearest = np.argmin((g.x[:, None] - px[None, :]) ** 2 + (g.y[:, None] - py[None, :]) ** 2, axis=1)
        return [ok[k][1] for k in nearest], units, layer
