"""
PASO 5 - Resumen

samples/RESUMEN.md: índice de ficheros, estadísticas de llamadas por fuente
(nº, errores, latencia media/máx) y hallazgos automáticos por punto.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict

from common import CALL_LOG, SAMPLES


def main() -> None:
    lines = ["# Evidencia de fuentes de suelo - resumen automático", "",
             "Generado por `exploracion/evidencia/run_all.py`. Todo lo que hay en esta carpeta es respuesta real",
             "de las APIs (solo se recortan geometrías largas). Ver `exploracion/evidencia/README.md`.", ""]

    pts = json.loads((SAMPLES / "puntos.json").read_text(encoding="utf-8"))
    lines += ["## Puntos estándar", "", "| id | lon | lat | descripción | Land (Nominatim) |",
              "|---|---|---|---|---|"]
    for p in pts["points"]:
        lines.append(f"| {p['id']} | {p['lon']} | {p['lat']} | {p['label']} "
                     f"{('- ' + str(p['fieldName'])) if p.get('fieldName') else ''} | {p.get('land_nominatim')} |")
    lines += ["", f"- {pts.get('nota_p2')}",
              f"- Campos activos con cobertura LBEG: {sum(1 for x in pts['lbeg_probe'] if x['hit'])} de "
              f"{len(pts['lbeg_probe'])}", ""]

    if CALL_LOG.exists():
        stats = defaultdict(list)
        errors = defaultdict(int)
        with CALL_LOG.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["seconds"]:
                    stats[row["source"]].append(float(row["seconds"]))
                if row["error"] or (row["status"] and row["status"] != "200"):
                    errors[row["source"]] += 1
        lines += ["## Llamadas HTTP (de `_llamadas.csv`)", "",
                  "| fuente | nº llamadas | errores/no-200 | media s | mediana s | máx s |", "|---|---|---|---|---|---|"]
        for src, secs in sorted(stats.items()):
            lines.append(f"| {src} | {len(secs)} | {errors[src]} | {statistics.mean(secs):.2f} | "
                         f"{statistics.median(secs):.2f} | {max(secs):.2f} |")
        lines.append("")

    lines += ["## Ficheros", ""]
    for path in sorted(SAMPLES.rglob("*")):
        if path.is_file() and "_raw" not in path.parts:
            lines.append(f"- `{path.relative_to(SAMPLES).as_posix()}` ({path.stat().st_size / 1024:.1f} KB)")
    lines += ["", "Ficheros grandes en `samples/_raw/`:", ""]
    for path in sorted((SAMPLES / "_raw").glob("*")):
        lines.append(f"- `_raw/{path.name}` ({path.stat().st_size / 1024:.1f} KB)")

    (SAMPLES / "RESUMEN.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
