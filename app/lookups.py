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
