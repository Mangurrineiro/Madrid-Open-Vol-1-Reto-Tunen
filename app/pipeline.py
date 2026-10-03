"""Ejecuta las fuentes sobre los campos y devuelve la tabla larga."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .fields import Field
from .sources import SOURCES
from .sources.base import COLUMNS


def run_field(field: Field, sources: list[str] | None = None,
              parameters: list[str] | None = None) -> list[dict]:
    rows: list[dict] = []
    for name in sources or list(SOURCES):
        src = SOURCES[name]
        if parameters and not set(parameters) & set(src.parameters):
            continue
        rows += src.fetch(field, parameters)
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                        for k, v in r.items()})
