"""
Análisis sobre la tabla larga de un campo (sin llamadas externas). Lo consume la UI.

- extra_rows: capas adicionales a partir de las filas ya calculadas
    · ka5_class (buek200): clase KA5 de Bodenart dominante de la unidad BÜK200 (horizonte
      superior de los perfiles usados, ponderado por Flächenanteil).
    · <p>_sigma (derived): σ del modelo de la media ponderada (ya estaba en la fila de derived).
    · sampling_priority (derived, 0-1): media de los desacuerdos normalizados por una escala
      de referencia (min(1, d/ref)) más clay_conflict (0/1) como un componente más.
      La UI muestra reliability_index = 100·(1 − sampling_priority).
- sampling_points: k puntos de mayor prioridad separados entre sí, con el motivo.
- point_table: todos los valores por punto y fuente (inspector de la UI).
- field_summary / featured: resumen por campo y los campos más interesantes de la granja.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict

import numpy as np

from .config import ENABLE_TERRAIN
from .regions import land_utm
from .sources.base import row

COMBINED = ["clay", "sand", "silt", "soc", "nfk"]
# Escala de referencia del desacuerdo (máx − mín) a partir de la cual se considera "total".
# ≈ 1,5 × la mediana de la granja de ejemplo: un campo típico queda a media escala.
DISAGREEMENT_REF = {"clay": 15.0, "sand": 40.0, "silt": 25.0, "soc": 30.0, "nfk": 10.0}
LABEL = {"clay": "clay points", "sand": "sand points", "silt": "silt points",
         "soc": "g/kg organic carbon", "nfk": "mm/dm plant-available water"}


def _by_point(rows: list[dict]) -> dict[int, dict[tuple[str, str], dict]]:
    out: dict[int, dict] = defaultdict(dict)
    for r in rows:
        out[r["point_id"]][(r["source"], r["parameter"])] = r
    return out


def _ok(r: dict | None):
    return r is not None and r["status"] == "ok" and r["value"] is not None


def _ka5_dominant(original: str) -> str | None:
    try:
        perfiles = json.loads(original)["perfiles"]
    except (ValueError, KeyError, TypeError):
        return None
    acc: dict[str, float] = defaultdict(float)
    for p in perfiles:
        ba = next((b for b in p.get("bodenart") or [] if b), None)
        if ba:
            acc[ba] += p.get("anteil") or 1.0
    return max(acc, key=acc.get) if acc else None


def _priority(pr: dict) -> tuple[float | None, dict]:
    """(prioridad 0-1 | None, componentes {param: valor normalizado})."""
    comp = {}
    for p, ref in DISAGREEMENT_REF.items():
        r = pr.get(("derived", f"{p}_disagreement"))
        if _ok(r):
            comp[p] = min(1.0, r["value"] / ref)
    r = pr.get(("derived", "clay_conflict"))
    if _ok(r):
        comp["clay_conflict"] = float(r["value"])
    if not comp:
        return None, comp
    return sum(comp.values()) / len(comp), comp


def extra_rows(field, rows: list[dict]) -> list[dict]:
    by_point = _by_point(rows)
    has_buek = any(r["source"] == "buek200" for r in rows)
    has_derived = any(r["source"] == "derived" for r in rows)
    has_lbeg = ENABLE_TERRAIN and any(r["source"] == "lbeg" and r["parameter"] in ("bodenzahl", "ackerzahl")
                                      for r in rows)
    out = []
    for i in range(len(field.grid)):
        pr = by_point.get(i, {})
        if has_lbeg:
            out.append(_acker_delta(field, i, pr))
        if has_buek:
            ref = next((pr[("buek200", p)] for p in ("clay", "sand", "silt", "soc", "ph_cacl2")
                        if ("buek200", p) in pr), None)
            ka5 = _ka5_dominant(ref["original"]) if ref is not None and ref["status"] == "ok" else None
            if ka5:
                out.append(row(field, i, "buek200", "ka5_class", value=ka5, original=ref["original"],
                               provenance=ref["provenance"] + " · Bodenart KA5 dominante (horizonte superior)"))
            else:
                out.append(row(field, i, "buek200", "ka5_class", status=ref["status"] if ref else "no_coverage",
                               original=ref["original"] if ref else "sin BÜK200 en este punto",
                               provenance=ref["provenance"] if ref else "BGR BÜK200"))
        if not has_derived:
            continue
        for p in COMBINED:
            r = pr.get(("derived", p))
            if r is None:
                continue
            if _ok(r) and r["sigma"] is not None:
                out.append(row(field, i, "derived", f"{p}_sigma", value=r["sigma"], original=r["original"],
                               provenance=r["provenance"] + " · σ = 1/√Σw"))
            else:
                out.append(row(field, i, "derived", f"{p}_sigma", status=r["status"] if r["status"] != "ok"
                               else "no_coverage", original=r["original"], provenance=r["provenance"]))
        prio, comp = _priority(pr)
        prov = "derived: media de min(1, desacuerdo/ref) " + json.dumps(DISAGREEMENT_REF) + " y clay_conflict"
        if prio is None:
            out.append(row(field, i, "derived", "sampling_priority", status="no_coverage",
                           original="ningún desacuerdo calculable (menos de 2 fuentes)", provenance=prov))
        else:
            out.append(row(field, i, "derived", "sampling_priority", value=round(prio, 3),
                           original=json.dumps({k: round(v, 3) for k, v in comp.items()}), provenance=prov))
    return out


def _acker_delta(field, i: int, pr: dict) -> dict:
    """acker_delta (lbeg, presentación) = Ackerzahl − Bodenzahl donde existen ambos."""
    a, b = pr.get(("lbeg", "ackerzahl")), pr.get(("lbeg", "bodenzahl"))
    prov = "LBEG Bodenschätzung (L849): ACKERZ − BODENZ"
    if _ok(a) and _ok(b):
        return row(field, i, "lbeg", "acker_delta", value=a["value"] - b["value"],
                   original=json.dumps({"ackerzahl": a["value"], "bodenzahl": b["value"]}), provenance=prov)
    ref = a or b
    status = "error" if ref is not None and ref["status"] == "error" else "no_coverage"
    return row(field, i, "lbeg", "acker_delta", status=status,
               original=ref["original"] if ref else "sin Bodenschätzung en este punto", provenance=prov)


# ---------- puntos de muestreo ----------
def _reason(pr: dict, comp: dict) -> tuple[str, str]:
    if comp.get("clay_conflict") == 1.0:
        r = pr[("derived", "clay_conflict")]
        o = json.loads(r["original"])
        return "clay_conflict", (f"Physical contradiction: SoilGrids reports {o['soilgrids_clay']:.0f} % clay, but the "
                                 f"soil assessment class {o['bodenart_bs']} allows at most {o['feinanteil_max']:.0f} % "
                                 f"fine particles")
    best = max((p for p in comp if p in DISAGREEMENT_REF), key=lambda p: comp[p], default=None)
    if best is None:
        return "-", "Highest uncertainty in this field"
    d = pr[("derived", f"{best}_disagreement")]["value"]
    return best, f"Sources disagree by {d:.1f} {LABEL[best]}"


def sampling_points(field, rows: list[dict], k: int | None = None) -> list[dict]:
    """Los k puntos de mayor prioridad, separados al menos min_d metros (se relaja si no caben)."""
    by_point = _by_point(rows)
    g = field.grid
    cand = []
    for i in range(len(g)):
        prio, comp = _priority(by_point.get(i, {}))
        if prio is not None:
            cand.append((prio, i, comp))
    if not cand:
        return []
    if k is None:
        k = int(np.clip(round(field.area_ha / 8) + 1, 2, 5))
    cand.sort(key=lambda c: (-c[0], c[1]))
    min_d = max(75.0, math.sqrt(field.geom_utm.area / k) * 0.6)
    chosen: list[tuple] = []
    while len(chosen) < min(k, len(cand)) and min_d >= 10:
        for c in cand:
            if len(chosen) >= k:
                break
            if c in chosen:
                continue
            if all(math.hypot(g.x[c[1]] - g.x[o[1]], g.y[c[1]] - g.y[o[1]]) >= min_d for o in chosen):
                chosen.append(c)
        min_d /= 2
    out = []
    for rank, (prio, i, comp) in enumerate(chosen, 1):
        param, reason = _reason(by_point[i], comp)
        out.append({"rank": rank, "point_id": i, "lon": round(float(g.lon[i]), 7), "lat": round(float(g.lat[i]), 7),
                    "priority": round(prio, 3), "reliability_index": round(100 * (1 - prio)),
                    "reason_parameter": param, "reason": reason})
    return out


# ---------- inspector ----------
POINT_PARAMS = ["clay", "sand", "silt", "ph_h2o", "ph_cacl2", "soc", "nfk", "bodenzahl", "ackerzahl"]
POINT_TEXT = ["bodenart_bs", "ka5_class", "soil_type"]
TERRAIN_POINT = [("copernicus_dem", "elevation"), ("copernicus_dem", "elevation_rel"),
                 ("copernicus_dem", "slope"), ("copernicus_dem", "aspect"), ("lbeg", "acker_delta")]


def point_table(field, rows: list[dict]) -> list[dict]:
    by_point = _by_point(rows)
    g = field.grid
    terrain = [k for k in TERRAIN_POINT if any((r["source"], r["parameter"]) == k for r in rows)]
    out = []
    for i in range(len(g)):
        pr = by_point.get(i, {})
        values: dict[str, dict] = {}
        for (src, par), r in pr.items():
            if par in POINT_PARAMS and _ok(r):
                values.setdefault(par, {})[src] = r["value"]
        uncertainty = {}
        for p in COMBINED:
            d, s = pr.get(("derived", f"{p}_disagreement")), pr.get(("derived", p))
            uncertainty[p] = {"spread": d["value"] if _ok(d) else None,
                              "sigma": s["sigma"] if _ok(s) else None}
        classes = {}
        for p in POINT_TEXT:
            r = next((r for (src, par), r in pr.items() if par == p and _ok(r)), None)
            classes[p] = r["value"] if r else None
        bs = pr.get(("lbeg", "bodenart_bs"))
        klassenzeichen = None
        if bs is not None and isinstance(bs["original"], str) and bs["original"].startswith("{"):
            klassenzeichen = json.loads(bs["original"]).get("KLASSENZEICHEN")
        conflict = None
        c = pr.get(("derived", "clay_conflict"))
        if _ok(c):
            o = json.loads(c["original"])
            conflict = {"value": c["value"], "soilgrids_clay": o["soilgrids_clay"],
                        "bodenart_bs": o["bodenart_bs"], "feinanteil_max": o["feinanteil_max"]}
        prio, _ = _priority(pr)
        out.append({"point_id": i, "lon": round(float(g.lon[i]), 7), "lat": round(float(g.lat[i]), 7),
                    "values": values, "uncertainty": uncertainty, "classes": classes,
                    "klassenzeichen": klassenzeichen, "clay_conflict": conflict,
                    "sampling_priority": None if prio is None else round(prio, 3),
                    "reliability_index": None if prio is None else round(100 * (1 - prio))})
        for k in terrain:                  # módulo de terreno: solo si existen sus filas
            out[-1][k[1]] = pr[k]["value"] if _ok(pr.get(k)) else None
    return out


# ---------- resumen de granja ----------
def field_summary(field, rows: list[dict]) -> dict:
    """Fuentes con dato, estado federal (por cobertura LBEG) y puntuación de 'interés'."""
    have = defaultdict(int)
    for r in rows:
        if r["status"] == "ok" and r["source"] not in ("derived", "copernicus_dem"):
            have[r["source"]] += 1
    sources = sorted(have)
    prios = [r["value"] for r in rows if r["parameter"] == "sampling_priority" and _ok(r)]
    conflicts = [r["value"] for r in rows if r["parameter"] == "clay_conflict" and _ok(r)]
    mean_prio = float(np.mean(prios)) if prios else None
    conflict_share = float(np.mean(conflicts)) if conflicts else 0.0
    return {"state": federal_state(field, "lbeg" in have),
            "sources": sources,
            "reliability_index": None if mean_prio is None else round(100 * (1 - mean_prio)),
            "conflict_share": round(conflict_share, 3),
            "_score": (mean_prio or 0) + 0.5 * conflict_share + 0.02 * math.log1p(field.area_ha)}


def federal_state(field, has_lbeg: bool) -> str:
    """Land del centroide (VG250 en caché); sin VG250, por la cobertura de LBEG."""
    nds = land_utm("Niedersachsen")
    if nds is None:
        return "Lower Saxony" if has_lbeg else "Saxony-Anhalt"
    if nds.intersects(field.geom_utm.centroid):
        return "Lower Saxony"
    sa = land_utm("Sachsen-Anhalt")
    return "Saxony-Anhalt" if sa is None or sa.intersects(field.geom_utm.centroid) else "Other"


def featured(summaries: list[dict], n: int = 5) -> list[dict]:
    """Los n campos más interesantes: mezcla de ambos estados, ordenados por desacuerdo/conflicto."""
    ranked = sorted(summaries, key=lambda s: -s["_score"])
    out, states = [], set()
    for s in ranked:                       # primero el mejor de cada estado
        if s["state"] not in states:
            out.append(s)
            states.add(s["state"])
    for s in ranked:
        if len(out) >= n:
            break
        if s not in out:
            out.append(s)
    out.sort(key=lambda s: -s["_score"])
    res = []
    for s in out[:n]:
        if s["conflict_share"] > 0.2:
            why = f"Physical contradiction in {s['conflict_share'] * 100:.0f} % of the field"
        else:
            why = f"Reliability index {s['reliability_index']}: sources disagree"
        res.append({"field_id": s["field_id"], "name": s["name"], "state": s["state"],
                    "reliability_index": s["reliability_index"], "reason": why})
    return res
