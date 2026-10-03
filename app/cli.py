"""
CLI.

  python -m app.cli test "Umfeld Groß" Mittelbreite [--source soilgrids]
      Ejecuta las fuentes sobre esos campos (por nombre o plotId), imprime un resumen
      por parámetro y guarda la tabla larga en data/out/<campo>.csv
"""

from __future__ import annotations

import argparse
import time
from collections import Counter

import numpy as np

from .config import DATA, FIELDS_GEOJSON
from .fields import find_field, load_fields
from .pipeline import run_field, write_csv


def summarize(rows: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["source"], r["parameter"]), []).append(r)
    print(f"  {'fuente':<11}{'parámetro':<18}{'unidad':<8}{'n':>5}  status{'':<22}"
          f"{'min':>8}{'media':>8}{'max':>8}{'σ media':>9}")
    for (src, par), rs in groups.items():
        st = Counter(r["status"] for r in rs)
        vals = [r["value"] for r in rs if r["status"] == "ok" and isinstance(r["value"], (int, float))]
        sig = [r["sigma"] for r in rs if r["status"] == "ok" and r["sigma"] is not None]
        sts = ", ".join(f"{k}={v}" for k, v in st.items())
        if vals:
            stats = f"{min(vals):>8.2f}{np.mean(vals):>8.2f}{max(vals):>8.2f}"
            stats += f"{np.mean(sig):>9.3f}" if sig else f"{'-':>9}"
        else:
            txt = Counter(str(r["value"]) for r in rs if r["status"] == "ok")
            stats = "  " + ", ".join(f"{k}×{v}" for k, v in txt.most_common(4)) if txt else ""
        print(f"  {src:<11}{par:<18}{rs[0]['unit']:<8}{len(rs):>5}  {sts:<28}{stats}")


def cmd_test(args) -> None:
    fields = load_fields(args.geojson)
    for key in args.fields:
        f = find_field(fields, key)
        print(f"\n=== {f.name} ({f.field_id}) · {f.area_ha:.2f} ha · {len(f.grid)} puntos de rejilla ===")
        t0 = time.time()
        rows = run_field(f, args.source or None)
        print(f"  {len(rows)} filas en {time.time() - t0:.1f} s")
        summarize(rows)
        from .sources import SOURCES
        for name, src in SOURCES.items():
            if getattr(src, "last_stats", None) and (not args.source or name in args.source):
                print(f"  {name}: {src.last_stats}")
                src.last_stats = None
        ex = next((r for r in rows if r["status"] == "ok"), rows[0] if rows else None)
        if ex:
            print(f"  ejemplo de fila: {ex}")
        out = DATA / "out" / f"{f.name.replace(' ', '_')}.csv"
        write_csv(rows, out)
        print(f"  tabla larga -> {out.relative_to(DATA.parent)}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("test", help="ejecuta fuentes sobre campos y resume")
    t.add_argument("fields", nargs="+")
    t.add_argument("--source", action="append")
    t.add_argument("--geojson", default=FIELDS_GEOJSON)
    t.set_defaults(func=cmd_test)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
