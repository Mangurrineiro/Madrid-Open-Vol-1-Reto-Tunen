"""
Terreno: perfil altimétrico en
Mühlenbreite (+) (más relieve, Sachsen-Anhalt: sin Bodenzahl) y f51 (Niedersachsen: con Bodenzahl).

  .venv\\Scripts\\python tests\\ui\\check_perfil.py   # capturas → out/screens/terrain_profile_*.png
"""

from __future__ import annotations

from ui_common import F51, SHOTS, open_demo, open_field, points, report, session, to_px

SHOW = "Mühlenbreite (+)"


def far_pair(pts: list[dict]) -> tuple[dict, dict]:
    """Los dos puntos de la rejilla más separados en latitud (línea N-S a través del campo)."""
    s = sorted(pts, key=lambda p: p["lat"])
    return s[2], s[-3]


def main() -> int:
    fails: list[str] = []
    with session() as (page, errors):
        open_demo(page)

        def run(name: str, expect_bz: bool) -> None:
            fid = open_field(page, name)
            if not page.query_selector("[data-action=profile]"):
                fails.append(f"{name}: no aparece el botón Draw elevation profile")
                return
            page.click("[data-action=profile]")
            page.wait_for_selector("#profile-panel .pf-hint", timeout=5_000)
            page.wait_for_timeout(1000)                       # el mapa reencuadra el campo
            # clic fuera del campo → aviso, no punto
            x0, y0 = to_px(page, *[v + 0.02 for v in (points(fid)[0]["lat"], points(fid)[0]["lon"])])
            if 0 < x0 < 1400 and 0 < y0 < 1000:
                page.mouse.click(x0, y0)
                page.wait_for_timeout(200)
                if "outside" not in page.inner_text("#profile-panel"):
                    fails.append(f"{name}: un clic fuera del campo no avisa")
            a, b = far_pair(points(fid))
            for p in (a, b):
                x, y = to_px(page, p["lat"], p["lon"])
                page.mouse.click(x, y)
                page.wait_for_timeout(250)
            page.wait_for_selector("#profile-panel .pf-svg", timeout=15_000)
            svg = page.locator("#profile-panel .pf-svg")
            box = svg.bounding_box()
            page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + 40)
            page.wait_for_timeout(400)
            if not page.inner_text("#profile-panel .pf-sub").startswith("A → B"):
                fails.append(f"{name}: falta el resumen del perfil")
            has_bz = "Bodenzahl" in page.inner_text("#profile-panel")
            if has_bz != expect_bz:
                fails.append(f"{name}: serie de Bodenzahl {'ausente' if expect_bz else 'inesperada'}")
            if page.locator(".profile-pin").count() != 2:
                fails.append(f"{name}: no se dibujan los marcadores A y B")
            page.screenshot(path=SHOTS / f"terrain_profile_{'showcase' if name == SHOW else 'f51'}.png")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            if page.query_selector("#profile-panel"):
                fails.append(f"{name}: Escape no cierra el perfil")

        run(SHOW, expect_bz=False)
        run(F51, expect_bz=True)
    return report(errors, fails)


if __name__ == "__main__":
    raise SystemExit(main())
