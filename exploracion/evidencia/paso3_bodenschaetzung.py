"""
PASO 3 - LBEG Bodenschätzung (capa L849 "BS5 - Bodenzahl der Bodenschätzung")

Mismo WMS que la BK50 (PkgId=24). Se consulta en P1..P4 con geo+json y
text/plain. Si un punto de Niedersachsen no devuelve nada (las parcelas de la
Bodenschätzung son pequeñas y hay huecos: pueblos, caminos, bosque), se
reintenta con un recuadro mayor (píxel más grueso) y en los puntos extra X1/X2.

Lo que interesa: un Klassenzeichen real tal como llega (ej. "sL 3 Lö 78/80")
y si Bodenzahl / Ackerzahl vienen como campos separados o solo dentro del código.

Salida: samples/bodenschaetzung/{P1..P4.txt, X1/X2.txt si hacen falta, resumen.txt}
"""

from __future__ import annotations

import json
import re
import shutil

from common import ROOT, SAMPLES, ensure_dirs, format_record_block, load_points, write_evidence
from lbeg import feature_properties, get_feature_info

OUT = SAMPLES / "bodenschaetzung"
LAYER = "L849"
RADII = [50, 250, 1000]  # m alrededor del punto -> píxel de ~1, 5 y 20 m
# Klassenzeichen tal como llega del WMS, p.ej. "lS3Lo" o "S5D" (Bodenart + Zustandsstufe + Entstehung)
KLASSEN_RE = re.compile(r"^[a-zA-Z]{1,4}\s?\d\s?[A-Za-zÖöÄäÜü]{1,4}$")


def main() -> None:
    ensure_dirs(OUT)
    pts = load_points(include_extra=True)
    summary = ["Bodenschätzung (L849) - resumen por punto", ""]
    nds_hits = 0
    for pid in ["P1", "P2", "P3", "P4", "X1", "X2"]:
        if pid.startswith("X") and nds_hits >= 1:
            continue  # los puntos extra solo si P1/P2 no dieron nada
        p = pts[pid]
        blocks = [f"Punto {pid}: lon={p['lon']} lat={p['lat']} | {p.get('label')} | "
                  f"Land: {p.get('land_nominatim', 'NDS (control)')}", ""]
        hit_props = None
        errors = False
        for radius in RADII:
            for fmt in ("application/geo+json", "text/plain"):
                r = get_feature_info("bodenschaetzung", f"{pid} {LAYER} r={radius} {fmt}", LAYER,
                                     p["lon"], p["lat"], info_format=fmt, radius_m=radius)
                blocks.append(format_record_block(
                    f"{pid} | {LAYER} | radio {radius} m | {fmt}", r,
                    {"INFO_FORMAT": fmt, "Radio BBOX": f"{radius} m (píxel ~{2 * radius / 101:.1f} m)",
                     "Hit": r["hit"]}))
                errors = errors or bool(r["error"])
                if fmt == "application/geo+json" and r["hit"]:
                    hit_props = feature_properties(r)
            if hit_props or p.get("in_nds") is False:
                break  # fuera de NDS basta con el radio pequeño para probar "sin cobertura"
        if hit_props and pid in ("P1", "P2"):
            nds_hits += 1
        write_evidence(OUT / f"{pid}.txt", "\n".join(blocks), errors and not hit_props)

        estado = "CON datos" if hit_props else ("ERROR del servidor (ver _llamadas.csv)" if errors else "sin datos")
        summary.append(f"{pid} ({p.get('label')}): {estado}")
        if hit_props:
            props = hit_props[0]
            summary.append(f"  campos devueltos: {list(props.keys())}")
            summary.append(f"  valores: {props}")
            klass = [v for v in props.values() if isinstance(v, str) and KLASSEN_RE.search(v)]
            summary.append(f"  Klassenzeichen detectado (patrón Bodenart+Stufe+Entstehung): {klass or 'ninguno'}")
            num = {k: f"{v!r} ({type(v).__name__})" for k, v in props.items()
                   if re.search(r"BODENZ|ACKERZ|GRUENL|WERT", k, re.I)}
            summary.append(f"  Bodenzahl/Ackerzahl como campos separados (valor y tipo JSON): {num or 'no'}")
        summary.append("")
    summary += team_extras()
    (OUT / "resumen.txt").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary))


def team_extras() -> list[str]:
    """Incorpora consultas manuales del equipo a L849 guardadas en exploracion/lbeg-bk50/Bodenzahl*.json."""
    out = []
    for i, src in enumerate(sorted((ROOT / "exploracion" / "lbeg-bk50").glob("Bodenzahl*.json")), 1):
        data = json.loads(src.read_text(encoding="utf-8"))
        name = (data.get("point") or {}).get("name") or f"extra_{i}"
        shutil.copyfile(src, OUT / f"extra_equipo_{name}.json")
        pt = data.get("point") or {}
        out += ["", f"EXTRA (consulta manual del equipo, capa {(data.get('layer') or {}).get('id')}):",
                f"  fichero: bodenschaetzung/extra_equipo_{name}.json | punto lon={pt.get('lon')} lat={pt.get('lat')}"]
        for f in (data.get("response") or {}).get("features", []):
            p = f.get("properties") or {}
            out.append(f"  KLASSENZEICHEN={p.get('KLASSENZEICHEN')!r} | SEP={p.get('KLASSENZEICHEN_SEP')!r} | "
                       f"BODENZ={p.get('BODENZ')!r} | ACKERZ={p.get('ACKERZ')!r} | "
                       f"KLARTEXT={p.get('KLASSENZEICHEN_KLARTEXT')!r}")
    return out


if __name__ == "__main__":
    main()
