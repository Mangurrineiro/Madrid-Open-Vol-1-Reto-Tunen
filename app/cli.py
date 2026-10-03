"""
CLI.

  python -m app.cli test "Umfeld Groß" Mittelbreite [--source soilgrids]
      Ejecuta las fuentes sobre esos campos (por nombre o plotId), imprime un resumen
      por parámetro y guarda la tabla larga en data/out/<campo>.csv

  python -m app.cli warm data/fields.geojson [--source X] [--passes 3] [--wait 180]
      Precarga la caché de todos los campos activos. Los campos con filas en error
      (p. ej. timeouts de LBEG, que no se cachean) se reintentan en pasadas sucesivas.

  python -m app.cli refresh [--source X] [--geojson data/fields.geojson]
      Vacía la caché de una fuente (o de todas; queda en data/cache/_stale/ como respaldo)
      y vuelve a precargar.
"""

from __future__ import annotations

import argparse
import time
from collections import Counter

import numpy as np

from . import cache
from .config import DATA, FIELDS_GEOJSON
from .fields import find_field, load_fields
from .pipeline import run_field, write_csv
from .sources import SOURCES


def summarize(rows: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["source"], r["parameter"]), []).append(r)
    print(f"  {'fuente':<11}{'parámetro':<20}{'unidad':<8}{'n':>5}  status{'':<22}"
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
        print(f"  {src:<11}{par:<20}{rs[0]['unit']:<8}{len(rs):>5}  {sts:<28}{stats}")


def cmd_test(args) -> None:
    fields = load_fields(args.geojson)
    for key in args.fields:
        f = find_field(fields, key)
        print(f"\n=== {f.name} ({f.field_id}) · {f.area_ha:.2f} ha · {len(f.grid)} puntos de rejilla ===")
        t0 = time.time()
        rows = run_field(f, args.source or None)
        print(f"  {len(rows)} filas en {time.time() - t0:.1f} s")
        summarize(rows)
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


def _wait_breaker() -> None:
    """En precarga no conviene fallar rápido: si LBEG abrió el cortacircuitos, se espera a que se enfríe."""
    from .sources.lbeg import BREAKER
    if BREAKER.is_open():
        left = BREAKER.opened_at + BREAKER.cooldown - time.time() + 1
        print(f"  LBEG con cortacircuitos abierto: esperando {left:.0f} s…", flush=True)
        time.sleep(max(left, 0))


def warm(geojson, sources: list[str] | None, passes: int = 3, wait: float = 180) -> dict:
    fields = load_fields(geojson)
    todo = fields
    totals: Counter = Counter()
    for k in range(1, passes + 1):
        print(f"\n--- pasada {k}/{passes}: {len(todo)} campos ---", flush=True)
        failed = []
        totals = Counter() if k == 1 else totals
        t0 = time.time()
        for j, f in enumerate(todo, 1):
            _wait_breaker()
            t = time.time()
            try:
                rows = run_field(f, sources)
            except Exception as exc:  # noqa: BLE001 — se reintenta en la siguiente pasada
                print(f"  {j}/{len(todo)} {f.name}: EXCEPCIÓN {exc!r}", flush=True)
                failed.append(f)
                continue
            st = Counter((r["source"], r["status"]) for r in rows)
            if k == 1:
                totals.update(st)
            errs = {s: n for (s, status), n in st.items() if status == "error"}
            if errs:
                failed.append(f)
            print(f"  {j}/{len(todo)} {f.name[:28]:<28} {time.time() - t:5.1f} s"
                  + (f"  errores: {errs}" if errs else ""), flush=True)
        print(f"  pasada {k}: {time.time() - t0:.0f} s, {len(failed)} campos con errores", flush=True)
        if not failed:
            break
        todo = failed
        if k < passes:
            print(f"  esperando {wait:.0f} s antes de reintentar…", flush=True)
            time.sleep(wait)
    print("\nResumen (primera pasada, filas por fuente y status):")
    for (s, status), n in sorted(totals.items()):
        print(f"  {s:<10} {status:<12} {n}")
    print(f"Campos que siguen con errores: {[f.name for f in todo] if failed else 'ninguno'}")
    return {"failed": [f.field_id for f in failed]}


def cmd_warm(args) -> None:
    warm(args.geojson, args.source or None, args.passes, args.wait)


def cmd_refresh(args) -> None:
    if args.source and args.source not in SOURCES:
        raise SystemExit(f"fuente desconocida: {args.source}; disponibles: {list(SOURCES)}")
    cleared = cache.clear(args.source)
    print(f"Caché vaciada (respaldo en data/cache/_stale/): {cleared or 'nada que vaciar'}")
    src = [args.source] if args.source and args.source != "derived" else None
    warm(args.geojson, src, args.passes, args.wait)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("test", help="ejecuta fuentes sobre campos y resume")
    t.add_argument("fields", nargs="+")
    t.add_argument("--source", action="append")
    t.add_argument("--geojson", default=FIELDS_GEOJSON)
    t.set_defaults(func=cmd_test)

    w = sub.add_parser("warm", help="precarga la caché de todos los campos")
    w.add_argument("geojson", nargs="?", default=FIELDS_GEOJSON)
    w.add_argument("--source", action="append")
    w.add_argument("--passes", type=int, default=3)
    w.add_argument("--wait", type=float, default=180)
    w.set_defaults(func=cmd_warm)

    r = sub.add_parser("refresh", help="vacía la caché (de una fuente o todas) y recalcula")
    r.add_argument("--source")
    r.add_argument("--geojson", default=FIELDS_GEOJSON)
    r.add_argument("--passes", type=int, default=3)
    r.add_argument("--wait", type=float, default=180)
    r.set_defaults(func=cmd_refresh)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
