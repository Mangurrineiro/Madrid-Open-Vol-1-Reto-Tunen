"""
Subida de GeoJSON propio.
Archivo con puntos, con coordenadas invertidas, JSON inválido, fallo del servidor (simulado)
y un archivo válido de 2 campos (uno en Niedersachsen y otro en Sachsen-Anhalt).

  .venv\\Scripts\\python tests\\ui\\check_subida_geojson.py
"""

from __future__ import annotations

import json
import sys

from ui_common import F51, ROOT, SHOTS, URL, report, session, wait_idle

FILES = ROOT / "out" / "test_files"


def make_files() -> dict:
    FILES.mkdir(parents=True, exist_ok=True)
    fc = json.loads((ROOT / "data" / "fields.geojson").read_text(encoding="utf-8"))
    active = [f for f in fc["features"] if not f["properties"].get("isArchived")]
    f51 = next(f for f in active if f["properties"]["fieldName"] == F51)
    sys.path.insert(0, str(ROOT))
    from app.analysis import federal_state
    from app.fields import parse_fields
    sa_id = next(f.field_id for f in parse_fields(fc) if federal_state(f, False) == "Saxony-Anhalt")
    sa = next(f for f in active if f["properties"]["plotId"] == sa_id)

    def swap(geom):
        return {"type": geom["type"], "coordinates": [[[p[1], p[0]] for p in ring] for ring in geom["coordinates"]]}

    files = {
        "points.geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [11.04, 52.38]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[11.04, 52.38], [11.05, 52.39]]}}]},
        "swapped.geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"fieldName": "Swapped"}, "geometry": swap(f51["geometry"])}]},
        "two_fields.geojson": {"type": "FeatureCollection", "features": [f51, sa]},
    }
    out = {}
    for name, obj in files.items():
        (FILES / name).write_text(json.dumps(obj), encoding="utf-8")
        out[name] = FILES / name
    (FILES / "broken.json").write_text('{"type": "FeatureCollection", "features": [', encoding="utf-8")
    out["broken.json"] = FILES / "broken.json"
    return out


def drop_msg(page) -> str:
    return page.inner_text("#dropzone .drop-msg")


def main() -> int:
    files = make_files()
    fails: list[str] = []
    expected = {
        "broken.json": "not valid JSON",
        "points.geojson": "points or lines",
        "swapped.geojson": "swapped",
    }
    with session() as (page, errors):
        page.goto(URL, wait_until="networkidle")
        for name, needle in expected.items():
            page.set_input_files("#file-input", str(files[name]))
            page.wait_for_timeout(400)
            msg = drop_msg(page)
            print(f"{name}: {msg}")
            if needle not in msg:
                fails.append(f"{name}: mensaje inesperado '{msg}'")
            page.screenshot(path=SHOTS / f"1_4_{name.split('.')[0]}.png")

        # Fallo del servidor (simulado) → error claro y botón para volver
        page.route("**/soil/layers", lambda route: route.fulfill(status=500, content_type="application/json",
                                                                  body=json.dumps({"detail": "Internal Server Error"})))
        page.set_input_files("#file-input", str(files["two_fields.geojson"]))
        page.wait_for_selector(".loading-error:not([hidden])", timeout=10_000)
        print("error servidor:", page.inner_text(".loading-error"))
        page.screenshot(path=SHOTS / "1_4_server_error.png")
        page.click(".loading-back")
        page.wait_for_timeout(500)
        page.unroute("**/soil/layers")
        # El 500 simulado deja un error de red en consola: es el esperado
        errors[:] = [e for e in errors if "status of 500" not in e]

        # Archivo válido
        page.set_input_files("#file-input", str(files["two_fields.geojson"]))
        page.wait_for_selector("#loading.on", timeout=5_000)
        page.wait_for_timeout(500)
        page.screenshot(path=SHOTS / "1_4_loading.png")
        page.wait_for_selector("body.farm", timeout=300_000)
        wait_idle(page, 2000)
        name = page.inner_text("#farm-name")
        chips = page.inner_text("#farm-chips").replace("\n", " · ")
        print("resultado:", name, "|", chips)
        if "2 fields" not in chips or "2 federal states" not in chips:
            fails.append(f"cabecera inesperada: {chips}")
        page.screenshot(path=SHOTS / "1_4_result.png")
        return report(errors, fails)


if __name__ == "__main__":
    sys.exit(main())
