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
    """Filas de la tabla larga para un campo. "derived" consume las filas de las fuentes base
    (que se calculan aunque no se hayan pedido, pero solo se devuelven si se pidieron)."""
    wanted = sources or list(SOURCES)
    derived = SOURCES.get("derived")
    run_derived = derived is not None and "derived" in wanted and \
        (not parameters or set(parameters) & set(derived.parameters))
    base_needed = [s for s in wanted if s != "derived"]
    if run_derived:
        base_needed += [s for s in derived.needs if s not in base_needed]

    rows: list[dict] = []
    base_rows: list[dict] = []
    for name in base_needed:
        src = SOURCES[name]
        # Las fuentes base que solo alimentan a derived se calculan con todos sus parámetros
        params = parameters if name in wanted else None
        if params and not set(params) & set(src.parameters):
            if name in wanted and not run_derived:
                continue
            params = None
        r = src.fetch(field, params)
        base_rows += r
        if name in wanted:
            rows += [x for x in r if not parameters or x["parameter"] in parameters]
    if run_derived:
        rows += derived.fetch(field, parameters, base_rows=base_rows)
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                        for k, v in r.items()})
