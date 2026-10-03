"""
derived: una fuente más, calculada a partir de las filas de las demás (sin llamadas externas).

- clay, sand, silt, soc, nfk: media ponderada con w = 1/σ² de las fuentes con status ok y σ > 0;
  σ_modelo = 1/√Σw; low/high = valor ∓ 1,645·σ.
- <param>_disagreement = máx − mín entre fuentes (no_coverage si hay menos de 2).
- Textura: clay + sand + silt se normalizan a 100 al final (σ y rango escalan igual).
- bodenzahl: el valor de la Bodenschätzung (LBEG) tal cual.
- clay_conflict = 1 donde la arcilla de SoilGrids supera el máximo de partículas finas
  (< 0,01 mm) de la clase de Bodenschätzung (físicamente imposible: la arcilla es parte de
  esas partículas finas); 0 si no; no_coverage si falta alguna de las dos.
"""

from __future__ import annotations

import json
import math

from .base import Source, register_source, row

COMBINED = ["clay", "sand", "silt", "soc", "nfk"]
TEXTURE = ["clay", "sand", "silt"]
Z90 = 1.645


@register_source
class Derived(Source):
    name = "derived"
    title = "Derivado (combinación de fuentes)"
    parameters = COMBINED + ["bodenzahl"] + [f"{p}_disagreement" for p in COMBINED] + ["clay_conflict"]
    coverage = "Donde haya al menos una fuente"
    resolution = "Rejilla común de 25 m"
    notes = ("Media ponderada por 1/σ² de las fuentes con dato; σ del modelo = 1/√Σw. Desacuerdo = máx − mín "
             "entre fuentes. Textura normalizada a 100 %. clay_conflict marca arcilla de SoilGrids imposible "
             "según la clase de la Bodenschätzung.")
    needs = ["soilgrids", "lbeg", "buek200"]      # fuentes base que consume

    def fetch(self, field, parameters=None, base_rows: list[dict] | None = None) -> list[dict]:
        wanted = set(parameters or self.parameters)
        # Si se pide "clay", también van su desacuerdo y el conflicto (capas de fiabilidad)
        wanted |= {f"{p}_disagreement" for p in COMBINED if p in wanted}
        if "clay" in wanted:
            wanted.add("clay_conflict")
        need_base = wanted | ({"clay", "sand", "silt"} if wanted & set(TEXTURE) else set())

        by_point: dict[int, dict[str, list[dict]]] = {}
        for r in base_rows or []:
            by_point.setdefault(r["point_id"], {}).setdefault(r["parameter"], []).append(r)

        rows: list[dict] = []
        for i in range(len(field.grid)):
            pr = by_point.get(i, {})
            combo = {p: self._combine(pr.get(p, [])) for p in COMBINED if p in need_base}
            # Normalización de textura a 100 %
            if all(combo.get(p) and combo[p]["value"] is not None for p in TEXTURE):
                total = sum(combo[p]["value"] for p in TEXTURE)
                if total > 0:
                    k = 100 / total
                    for p in TEXTURE:
                        combo[p]["value"] *= k
                        combo[p]["sigma"] *= k
                        combo[p]["norm"] = round(k, 4)
            for p in COMBINED:
                c = combo.get(p)
                if p in wanted and c is not None:
                    rows.append(self._row(field, i, p, c))
                if f"{p}_disagreement" in wanted and c is not None:
                    rows.append(self._disagreement_row(field, i, p, c))
            if "bodenzahl" in wanted:
                rows.append(self._bodenzahl(field, i, pr.get("bodenzahl", [])))
            if "clay_conflict" in wanted:
                rows.append(self._conflict(field, i, pr))
        return rows

    # ---------- combinación ----------
    @staticmethod
    def _combine(rs: list[dict]) -> dict:
        ok = [r for r in rs if r["status"] == "ok" and isinstance(r["value"], (int, float))
              and r["sigma"] not in (None, 0)]
        if not ok:
            return {"value": None, "sources": {}, "why": "ninguna fuente con dato y σ"}
        w = [1 / r["sigma"] ** 2 for r in ok]
        v = sum(wi * r["value"] for wi, r in zip(w, ok)) / sum(w)
        vals = [r["value"] for r in ok]
        return {"value": v, "sigma": 1 / math.sqrt(sum(w)),
                "disagreement": (max(vals) - min(vals)) if len(ok) >= 2 else None,
                "sources": {r["source"]: [r["value"], r["sigma"], round(wi / sum(w), 3)] for r, wi in zip(ok, w)}}

    def _row(self, field, i, p, c):
        if c["value"] is None:
            return row(field, i, self.name, p, status="no_coverage", original=c["why"], provenance=self._prov(c))
        v, s = c["value"], c["sigma"]
        orig = {"fuentes {valor, σ, peso}": c["sources"]} | ({"factor_normalizacion": c["norm"]} if "norm" in c else {})
        return row(field, i, self.name, p, value=round(v, 2), sigma=round(s, 3), low=round(v - Z90 * s, 2),
                   high=round(v + Z90 * s, 2), original=json.dumps(orig, ensure_ascii=False, separators=(",", ":")),
                   provenance=self._prov(c))

    def _disagreement_row(self, field, i, p, c):
        par = f"{p}_disagreement"
        if c.get("disagreement") is None:
            return row(field, i, self.name, par, status="no_coverage",
                       original=f"menos de 2 fuentes con dato ({', '.join(c['sources']) or 'ninguna'})",
                       provenance=self._prov(c))
        return row(field, i, self.name, par, value=round(c["disagreement"], 2),
                   original=json.dumps({k: v[0] for k, v in c["sources"].items()}, separators=(",", ":")),
                   provenance=self._prov(c))

    @staticmethod
    def _prov(c) -> str:
        return f"derived: media 1/σ² de {'+'.join(sorted(c['sources'])) or '-'}"

    def _bodenzahl(self, field, i, rs):
        r = next((r for r in rs if r["source"] == "lbeg"), None)
        if r is None or r["status"] != "ok":
            return row(field, i, self.name, "bodenzahl", status=r["status"] if r else "no_coverage",
                       original=r["original"] if r else "sin Bodenschätzung (LBEG) en este punto",
                       provenance="derived = LBEG Bodenschätzung")
        return row(field, i, self.name, "bodenzahl", value=r["value"], original=r["original"],
                   provenance=f"derived = {r['provenance']}")

    def _conflict(self, field, i, pr):
        sg = next((r for r in pr.get("clay", []) if r["source"] == "soilgrids" and r["status"] == "ok"), None)
        bs = next((r for r in pr.get("bodenart_bs", []) if r["status"] == "ok" and r["high"] is not None), None)
        prov = "derived: SoilGrids clay vs. Bodenschätzung (partículas < 0,01 mm)"
        if sg is None or bs is None:
            why = "falta " + " y ".join(x for x, r in (("SoilGrids clay", sg), ("Bodenschätzung", bs)) if r is None)
            return row(field, i, self.name, "clay_conflict", status="no_coverage", original=why, provenance=prov)
        conflict = int(sg["value"] > bs["high"])
        orig = {"soilgrids_clay": sg["value"], "bodenart_bs": bs["value"], "feinanteil_max": bs["high"]}
        return row(field, i, self.name, "clay_conflict", value=conflict,
                   original=json.dumps(orig, ensure_ascii=False, separators=(",", ":")), provenance=prov)
