"""
LBEG NIBIS (Niedersachsen): BK50 + Bodenschätzung en UNA llamada GetFeatureInfo.

- QUERY_LAYERS = L816 (BK50 Karte), L839 (nFKWe), L823 (WE), L837 (Ertragsfähigkeit),
  L849 (Bodenschätzung). Cada feature se identifica por sus atributos, nunca por posición
  (si una capa no tiene objeto, desaparece y el orden ya no sirve; exploracion/evidencia/samples2/RESUMEN2.md §3).
- Las geometrías llegan en EPSG:4647 (declarado en geometry.crs) -> se pasan a 25832.
  Por capa solo vale la feature cuyo polígono CONTIENE el punto (tolerancia del WMS,
  RESUMEN2.md §4: a veces devuelve el vecino).
- Cosecha: tras cada llamada, cada polígono devuelto se asigna a todos los puntos de la
  rejilla que contiene. Solo se consultan puntos sin resolver. Las 4 capas BK50 comparten
  polígono (mismo FL_NR) -> grupo "bk50"; L849 -> grupo "bs".
- Respuesta vacía -> no_coverage. Fuera de Niedersachsen (p. ej. Sachsen-Anhalt) LBEG devuelve
  features: [] pero puede tardar >80 s: los puntos a más de 100 m de Niedersachsen (límite
  oficial BKG VG250, cacheado) son no_coverage sin ninguna llamada.
- 503.2 dentro de HTTP 200 (ServiceException) -> error, no se cachea. Timeout 20 s,
  reintentos tras 10/20/40 s, máx. 4 peticiones simultáneas, cortacircuitos tras 3 fallos
  seguidos (se reabre a los 120 s).
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

from .. import cache
from ..lookups import bs_feinanteil
from ..regions import land_utm
from .base import Source, register_source, row

NIBIS_URL = "https://nibis.lbeg.de/net3/public/ogc.ashx"
LAYERS = "L816,L839,L823,L837,L849"
TIMEOUT = 20
WAITS = [10, 20, 40]
MAX_PARALLEL = 4
BORDER_M = 100                    # margen en la frontera de Niedersachsen: ahí sí se pregunta
NFK_SIGMA = 2.0                   # mm/dm — suposición documentada (no viene en el WMS)
ERROR_MARKERS = ("ServiceException", "Ein Fehler trat", "Error 503", "Service Busy")

# atributo distintivo -> capa
SIGNATURE = [("BOTYP", "L816"), ("NFKWE", "L839"), ("WEKLASSE", "L823"), ("BFR", "L837"),
             ("KLASSENZEICHEN", "L849")]
GROUP = {"L816": "bk50", "L839": "bk50", "L823": "bk50", "L837": "bk50", "L849": "bs"}
LAYER_TITLE = {"L816": "BK50 Karte", "L839": "BK50 nFKWe", "L823": "BK50 Wurzelraum (WE)",
               "L837": "BK50 Ertragsfähigkeit", "L849": "Bodenschätzung (BS5)"}

_TO_UTM: dict[int, Transformer] = {}


def _transformer(epsg: int) -> Transformer:
    if epsg not in _TO_UTM:
        _TO_UTM[epsg] = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:25832", always_xy=True)
    return _TO_UTM[epsg]


class Breaker:
    """Cortacircuitos: tras 3 fallos seguidos no se llama durante 120 s."""

    def __init__(self, threshold: int = 3, cooldown: float = 120):
        self.threshold, self.cooldown = threshold, cooldown
        self.fails, self.opened_at = 0, 0.0
        self.lock = threading.Lock()

    def is_open(self) -> bool:
        with self.lock:
            if self.fails < self.threshold:
                return False
            if time.time() - self.opened_at > self.cooldown:
                self.fails = self.threshold - 1      # semiabierto: un intento más
                return False
            return True

    def record(self, ok: bool) -> None:
        with self.lock:
            if ok:
                self.fails = 0
            else:
                self.fails += 1
                if self.fails >= self.threshold:
                    self.opened_at = time.time()


BREAKER = Breaker()
_SEM = threading.Semaphore(MAX_PARALLEL)


def _params(x: float, y: float) -> dict:
    return {"PKGID": 24, "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
            "LAYERS": LAYERS, "QUERY_LAYERS": LAYERS, "STYLES": "", "CRS": "EPSG:25832",
            "BBOX": f"{x - 50:.2f},{y - 50:.2f},{x + 50:.2f},{y + 50:.2f}",
            "WIDTH": 101, "HEIGHT": 101, "I": 50, "J": 50,
            "INFO_FORMAT": "application/geo+json", "FEATURE_COUNT": 5}


def _validate(r) -> str | None:
    head = r.content[:3000].decode("utf-8", errors="replace")
    if any(m in head for m in ERROR_MARKERS):
        return "service_error (503.2 u otro error dentro de HTTP 200): " + head[:200]
    try:
        _decode(r.content)
    except ValueError:
        return "respuesta no es JSON: " + head[:200]
    return None


def _decode(content: bytes) -> dict:
    try:
        return json.loads(content.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(content.decode("cp1252"))


def query_point(x: float, y: float) -> tuple[dict | None, str, str]:
    """Una llamada GetFeatureInfo multicapa. Devuelve (geojson | None, url, fecha | error)."""
    params = _params(x, y)
    url = cache.full_url(NIBIS_URL, params)
    hit = cache.lookup("lbeg", "GET", url)
    if hit:
        return _decode(hit.content), url, hit.fetched_at
    last = ""
    for wait in [0] + WAITS:
        if BREAKER.is_open():
            return None, url, "circuit_open: LBEG falló 3 veces seguidas"
        if wait:
            time.sleep(wait)
        with _SEM:
            try:
                c = cache.fetch("lbeg", NIBIS_URL, params, timeout=TIMEOUT, validate=_validate)
                BREAKER.record(True)
                return _decode(c.content), url, c.fetched_at
            except cache.FetchError as exc:
                last = str(exc)
        BREAKER.record(False)
        print(f"  [lbeg] fallo en ({x:.0f}, {y:.0f}): {last[:160]}", flush=True)
    old = cache.recover_stale("lbeg", "GET", url)       # versión anterior a un /refresh
    if old:
        return _decode(old.content), url, old.fetched_at
    return None, url, last


def parse_features(fc: dict) -> list[dict]:
    """Features -> [{layer, props, geom (25832)}] identificando la capa por sus atributos."""
    out = []
    for f in fc.get("features", []):
        props = f.get("properties") or {}
        layer = next((lay for attr, lay in SIGNATURE if attr in props), None)
        g = f.get("geometry")
        if not layer or not g:
            continue
        epsg = ((g.get("crs") or {}).get("properties") or {}).get("code", 4647)
        geom = shp_transform(_transformer(int(epsg)).transform, shape(g))
        out.append({"layer": layer, "props": props, "geom": geom})
    return out


@register_source
class LBEG(Source):
    name = "lbeg"
    title = "LBEG NIBIS: BK50 + Bodenschätzung"
    parameters = ["bodenzahl", "ackerzahl", "bodenart_bs", "nfk", "ertragsfaehigkeit", "soil_type"]
    coverage = "Solo Niedersachsen"
    resolution = "Polígonos 1:50.000 (BK50) y parcelas de la Bodenschätzung (1:5.000)"
    notes = ("GetFeatureInfo multicapa con cosecha de polígonos. nFK = NFKWE / (WE/10) mm/dm "
             f"(σ = {NFK_SIGMA} mm/dm, supuesta). La Bodenart de la Bodenschätzung no se convierte a "
             "arcilla: se da su rango de partículas < 0,01 mm.")

    def fetch(self, field, parameters=None) -> list[dict]:
        params = [p for p in (parameters or self.parameters) if p in self.parameters]
        g = field.grid
        n = len(g)
        # resultado por grupo y punto: dict(feature) | ("no_coverage"|"error", detalle)
        res = {"bk50": [None] * n, "bs": [None] * n}
        polys = {"bk50": {}, "bs": {}}          # FL_NR -> feature (con todas sus capas)
        calls = {"n": 0, "urls": [], "dates": set()}

        def unresolved() -> np.ndarray:
            return np.array([i for i in range(n) if res["bk50"][i] is None or res["bs"][i] is None], dtype=int)

        def harvest(i: int, fc: dict | None, url: str, info: str) -> None:
            calls["n"] += 1
            if fc is None:                       # error de servicio
                for grp in res:
                    if res[grp][i] is None:
                        res[grp][i] = ("error", info)
                return
            calls["dates"].add(info[:10])
            feats = parse_features(fc)
            for grp in ("bk50", "bs"):
                # Agrupa las capas por polígono (FL_NR); BK50 comparte FL_NR entre sus 4 capas
                by_fl: dict = {}
                for f in feats:
                    if GROUP[f["layer"]] != grp:
                        continue
                    key = (f["props"].get("FL_NR"), round(f["geom"].area))
                    unit = by_fl.setdefault(key, {"geom": f["geom"], "layers": {}, "url": url, "date": info[:10]})
                    unit["layers"][f["layer"]] = f["props"]
                for key, unit in by_fl.items():
                    known = polys[grp].setdefault(key, unit)
                    known["layers"].update(unit["layers"])
                    unit = known
                    todo = np.array([j for j in range(n) if res[grp][j] is None], dtype=int)
                    if len(todo):
                        inside = shapely.contains_xy(unit["geom"], g.x[todo], g.y[todo])
                        for j in todo[inside]:
                            res[grp][j] = unit
                if res[grp][i] is None:          # ningún polígono contiene el punto
                    res[grp][i] = ("no_coverage", "LBEG no devuelve polígono que contenga el punto"
                                   if feats else "LBEG sin datos en este punto (features vacías)")

        def run_batch(idx: list[int]) -> bool:
            """Lanza hasta 4 consultas en paralelo. False si todas cayeron en el cortacircuitos."""
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
                results = list(ex.map(lambda i: query_point(g.x[i], g.y[i]), idx))
            for i, (fc, url, info) in zip(idx, results):
                harvest(i, fc, url, info)
            return not all(fc is None and info.startswith("circuit_open") for fc, _, info in results)

        # 1) Cobertura geográfica: fuera de Niedersachsen (VG250, margen 100 m) no se pregunta.
        nds = land_utm("Niedersachsen")
        if nds is not None:
            near = shapely.contains_xy(nds.buffer(BORDER_M), g.x, g.y)
            for j in np.flatnonzero(~near):
                for grp in res:
                    res[grp][j] = ("no_coverage", "Fuera de Niedersachsen (LBEG solo cubre Niedersachsen; "
                                                  "límite BKG VG250)")
        # 2) Cosecha: lotes de hasta 4 puntos sin resolver, lo más separados posible
        while len(todo := unresolved()):
            if not run_batch(_spread(g, list(todo), min(MAX_PARALLEL, len(todo)))):
                for grp in res:                   # LBEG caído: no seguir martilleando
                    for j in unresolved():
                        if res[grp][j] is None:
                            res[grp][j] = ("error", "circuit_open: LBEG falló 3 veces seguidas")
                break

        self.last_stats = {"calls": calls["n"], "polygons_bs": len(polys["bs"]),
                           "polygons_bk50": len(polys["bk50"])}
        return self._rows(field, params, res, calls)

    def _rows(self, field, params, res, calls) -> list[dict]:
        rows = []
        today = date.today().isoformat()
        for i in range(len(field.grid)):
            for p in params:
                grp = "bs" if p in ("bodenzahl", "ackerzahl", "bodenart_bs") else "bk50"
                unit = res[grp][i]
                if isinstance(unit, tuple):
                    rows.append(row(field, i, self.name, p, status=unit[0], original=unit[1],
                                    provenance=f"LBEG NIBIS WMS {LAYERS} · {today}"))
                    continue
                rows.append(self._value(field, i, p, unit))
        return rows

    def _value(self, field, i: int, p: str, unit: dict) -> dict:
        L = unit["layers"]

        def prov(*layers):
            fl = next((L[x].get("FL_NR") for x in layers if x in L), None)
            names = ", ".join(f"{x} {LAYER_TITLE[x]}" for x in layers)
            return f"LBEG NIBIS WMS {names} · FL_NR {fl} · descargado {unit['date']}"

        def missing(layer):
            return row(field, i, self.name, p, status="no_coverage",
                       original=f"capa {layer} sin objeto en este polígono", provenance=prov(layer))

        if p in ("bodenzahl", "ackerzahl", "bodenart_bs"):
            if "L849" not in L:
                return missing("L849")
            a = L["L849"]
            orig = json.dumps({k: a.get(k) for k in ("KLASSENZEICHEN", "KLASSENZEICHEN_SEP", "BODENZ", "ACKERZ")},
                              ensure_ascii=False)
            if p == "bodenzahl":
                v = a.get("BODENZ")
                return row(field, i, self.name, p, value=int(v) if v is not None else None, original=orig,
                           provenance=prov("L849"), status="ok" if v is not None else "no_coverage")
            if p == "ackerzahl":
                v = a.get("ACKERZ")
                try:
                    v = int(str(v).strip())
                except (TypeError, ValueError):
                    return row(field, i, self.name, p, status="no_coverage", original=orig, provenance=prov("L849"))
                return row(field, i, self.name, p, value=v, original=orig, provenance=prov("L849"))
            sep = a.get("KLASSENZEICHEN_SEP") or ""
            ba = sep.split(";")[0].strip() if sep else None
            if not ba:
                return row(field, i, self.name, p, status="no_coverage", original=orig, provenance=prov("L849"))
            lo, hi = bs_feinanteil(ba)
            return row(field, i, self.name, p, value=ba, low=lo, high=hi, original=orig, provenance=prov("L849"))

        if p == "nfk":
            if "L839" not in L or "L823" not in L:
                return missing("L839/L823")
            nfkwe, we = L["L839"].get("NFKWE"), L["L823"].get("WE")
            orig = json.dumps({"NFKWE": nfkwe, "WE": we})
            if not nfkwe or not we:
                return row(field, i, self.name, p, status="no_coverage", original=orig, provenance=prov("L839", "L823"))
            v = nfkwe / (we / 10)
            return row(field, i, self.name, p, value=round(v, 2), low=round(v - 1.645 * NFK_SIGMA, 2),
                       high=round(v + 1.645 * NFK_SIGMA, 2), sigma=NFK_SIGMA, original=orig,
                       provenance=prov("L839", "L823"))
        if p == "ertragsfaehigkeit":
            if "L837" not in L:
                return missing("L837")
            v = L["L837"].get("BFR")
            return row(field, i, self.name, p, value=v, original=json.dumps({"BFR": v}), provenance=prov("L837"),
                       status="ok" if v is not None else "no_coverage")
        if p == "soil_type":
            if "L816" not in L:
                return missing("L816")
            a = L["L816"]
            return row(field, i, self.name, p, value=a.get("BOTYP_KLARTEXT"),
                       original=json.dumps({"BOTYP": a.get("BOTYP"), "BOTYP_KLARTEXT": a.get("BOTYP_KLARTEXT")},
                                           ensure_ascii=False), provenance=prov("L816"))
        raise ValueError(p)


def _spread(g, idx: list[int], k: int) -> list[int]:
    """Elige k puntos de idx lo más separados posible (farthest point sampling, determinista)."""
    idx = list(idx)
    xs, ys = g.x[idx], g.y[idx]
    cx, cy = xs.mean(), ys.mean()
    first = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))   # empieza por el más central
    chosen = [first]
    d = (xs - xs[first]) ** 2 + (ys - ys[first]) ** 2
    while len(chosen) < k:
        nxt = int(np.argmax(d))
        if d[nxt] == 0:
            break
        chosen.append(nxt)
        d = np.minimum(d, (xs - xs[nxt]) ** 2 + (ys - ys[nxt]) ** 2)
    return [idx[c] for c in chosen]
