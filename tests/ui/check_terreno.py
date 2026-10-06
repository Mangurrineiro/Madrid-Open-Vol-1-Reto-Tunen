"""
Terreno: relieve sombreado en la granja y en f51 (Texture y Bodenzahl),
Slope, Aspect, Ackerzahl − Bodenzahl, incertidumbre de terreno, inspector y pila con hillshade.

  .venv\\Scripts\\python tests\\ui\\check_terreno.py      # capturas → out/screens/terrain_*.png
"""

from __future__ import annotations

from ui_common import F51, SHOTS, open_demo, open_field, points, report, session, to_px, wait_idle

SHOW = "Mühlenbreite (+)"      # el campo con más relieve de la granja


def main() -> int:
    fails: list[str] = []
    with session() as (page, errors):
        def shot(name: str) -> None:
            page.screenshot(path=SHOTS / f"terrain_{name}.png")

        def layer(lid: str) -> None:
            page.evaluate("(id) => window.__app.setLayer(id)", lid)
            wait_idle(page, 900)

        def hover_tip(fid: str) -> str:
            pts = points(fid)
            p = pts[len(pts) // 2]
            x, y = to_px(page, p["lat"], p["lon"])
            page.mouse.move(x, y)
            page.wait_for_timeout(250)
            page.mouse.move(x + 1, y + 1)
            page.wait_for_timeout(300)
            return page.inner_text("#cursor-tip")

        open_demo(page)
        if not page.query_selector("#relief-toggle"):
            fails.append("no aparece el interruptor Relief shading")
        if page.locator(".terrain-group .layer-item").count() != 3:
            fails.append("el grupo Terrain no tiene 3 capas")
        page.keyboard.press("r")
        page.wait_for_timeout(700)
        op = page.evaluate("() => getComputedStyle(document.querySelector('.relief-bg')).opacity")
        if abs(float(op) - 0.45) > 0.01:
            fails.append(f"fondo de relieve con opacidad {op} (esperado 0.45)")
        if not page.is_visible(".relief-note"):
            fails.append("falta la nota 'vertical exaggeration ×3'")
        shot("farm_relief")

        fid = open_field(page, F51)
        page.wait_for_timeout(600)
        st = page.evaluate("""() => { const e = document.querySelector('.relief-overlay');
          return e ? [getComputedStyle(e).opacity, getComputedStyle(e).mixBlendMode] : null; }""")
        if not st or abs(float(st[0]) - 0.55) > 0.01 or st[1] != "multiply":
            fails.append(f"hillshade del campo: {st} (esperado 0.55 / multiply)")
        if not page.query_selector(".terrain-card .compass"):
            fails.append("falta la tarjeta Field terrain con la rosa de los vientos")
        shot("f51_texture_relief")

        layer("bodenzahl")
        shot("f51_bodenzahl_relief")
        page.click("[data-action=sub][data-value=acker_delta]")
        wait_idle(page, 900)
        tip = hover_tip(fid)
        if "Bodenzahl" not in tip or "→ Ackerzahl" not in tip:
            fails.append(f"tooltip de Ackerzahl − Bodenzahl inesperado: {tip!r}")
        shot("f51_acker_delta")

        layer("slope")
        tip = hover_tip(fid)
        if not tip.startswith("Slope"):
            fails.append(f"tooltip de Slope inesperado: {tip!r}")
        shot("f51_slope")
        layer("aspect")
        tip = hover_tip(fid)
        if not ("Facing" in tip or "Flat" in tip):
            fails.append(f"tooltip de Aspect inesperado: {tip!r}")
        shot("f51_aspect")
        layer("elevation")
        tip = hover_tip(fid)
        if "Elevation" not in tip or "above field low point" not in tip:
            fails.append(f"tooltip de elevación inesperado: {tip!r}")
        shot("f51_elevation")

        page.keyboard.press("u")
        page.wait_for_timeout(600)
        if "single source" not in page.inner_text("#card"):
            fails.append("la incertidumbre de terreno no muestra la nota de fuente única")
        shot("f51_uncertainty")
        page.keyboard.press("u")
        page.wait_for_timeout(400)

        pts = points(fid)
        p = pts[len(pts) // 3]
        x, y = to_px(page, p["lat"], p["lon"])
        page.mouse.click(x, y)
        page.wait_for_selector(".inspector-popup", timeout=10_000)
        page.wait_for_timeout(500)
        txt = page.inner_text(".inspector-popup")
        if "terrain" not in txt.lower() or "Slope" not in txt:
            fails.append("el inspector no tiene la sección Terrain")
        shot("f51_inspector")
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)

        open_field(page, SHOW)
        layer("slope")
        shot("showcase_slope_relief")
        layer("texture")
        shot("showcase_texture_relief")

        open_field(page, SHOW, stack=True)
        page.wait_for_timeout(1200)
        shot("showcase_stack")
    return report(errors, fails)


if __name__ == "__main__":
    raise SystemExit(main())
