"""Tablas fijas de lookups/*.csv (clases -> números con rango)."""

from __future__ import annotations

import csv
from functools import cache

from .config import LOOKUPS


def _num(v: str):
    v = (v or "").strip()
    return float(v) if v else None


@cache
def table(name: str, key: str) -> dict[str, dict]:
    with (LOOKUPS / f"{name}.csv").open(encoding="utf-8") as f:
        return {r[key]: {k: (_num(v) if k != key and k != "nota" and k != "bodenart" else v)
                         for k, v in r.items()} for r in csv.DictReader(f)}


def bs_feinanteil(bodenart: str) -> tuple[float | None, float | None]:
    """Rango de partículas < 0,01 mm (%) de una Bodenart de la Bodenschätzung."""
    r = table("bodenschaetzung_feinanteil", "bodenart").get(bodenart)
    return (r["feinanteil_min"], r["feinanteil_max"]) if r else (None, None)


def ka5_bodenart(cls: str) -> dict | None:
    """Centroide KA5 (clay, silt, sand) y rangos de clay/silt. Alias (fSms…) -> Ss. None si no se conoce."""
    cls = (cls or "").strip()
    alias = table("ka5_bodenart_alias", "alias").get(cls)
    if alias:
        cls = alias["bodenart"]
    return table("ka5_bodenart", "bodenart").get(cls)


def ka5_humus(cls: str) -> tuple[float, float | None] | None:
    """Rango de materia orgánica (%) de la clase de humus KA5 (h7: máximo abierto)."""
    r = table("ka5_humus", "clase").get((cls or "").strip())
    return (r["mo_min"], r["mo_max"]) if r else None


def ka5_acidez(cls: str) -> tuple[float, float] | None:
    """Rango de pH(CaCl2) de la clase de acidez KA5."""
    r = table("ka5_acidez", "clase").get((cls or "").strip())
    return (r["ph_min"], r["ph_max"]) if r else None
