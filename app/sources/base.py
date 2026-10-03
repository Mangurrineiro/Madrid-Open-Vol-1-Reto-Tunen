"""
Interfaz común de los adaptadores y fila de la tabla larga.

Tabla larga (una fila por punto, fuente y parámetro):
field_id, point_id, lon, lat, source, parameter, value, unit, low, high, sigma,
original, status ("ok" | "no_coverage" | "error"), provenance
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import PARAMETERS

if TYPE_CHECKING:
    from ..fields import Field

SOURCES: dict[str, "Source"] = {}

COLUMNS = ["field_id", "point_id", "lon", "lat", "source", "parameter", "value", "unit",
           "low", "high", "sigma", "original", "status", "provenance"]


class Source:
    name: str = ""
    title: str = ""
    parameters: list[str] = []
    coverage: str = ""
    resolution: str = ""
    notes: str = ""

    def fetch(self, field: "Field", parameters: list[str] | None = None) -> list[dict]:
        raise NotImplementedError

    def info(self) -> dict:
        return {"name": self.name, "title": self.title, "parameters": self.parameters,
                "coverage": self.coverage, "resolution": self.resolution, "notes": self.notes}


def register_source(cls):
    inst = cls()
    SOURCES[inst.name] = inst
    return cls


def row(field: "Field", i: int, source: str, parameter: str, *, value: Any = None,
        low: float | None = None, high: float | None = None, sigma: float | None = None,
        original: Any = None, status: str = "ok", provenance: str = "") -> dict:
    g = field.grid
    return {
        "field_id": field.field_id, "point_id": int(g.point_id[i]),
        "lon": round(float(g.lon[i]), 7), "lat": round(float(g.lat[i]), 7),
        "source": source, "parameter": parameter, "value": value,
        "unit": PARAMETERS[parameter]["unit"], "low": low, "high": high, "sigma": sigma,
        "original": original, "status": status, "provenance": provenance,
    }
