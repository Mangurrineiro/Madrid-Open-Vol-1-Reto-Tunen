"""
Incertidumbre on/off en 3 capas (con tecla U), tooltip de incertidumbre,
puntos de muestreo en el campo y en la granja.

  .venv\\Scripts\\python tests\\ui\\check_incertidumbre.py
"""

from __future__ import annotations

import sys

from ui_common import F51, SHOTS, open_demo, open_field, points, report, session, to_px, wait_idle


def main() -> int:
    fails: list[str] = []
    with session() as (page, errors):
        open_demo(page)
        fid = open_field(page, F51)
        pts = points(fid)
        mid = pts[len(pts) // 3]

        for i, layer in enumerate(("texture", "soc", "ph")):
            page.click(f'[data-action="layer"][data-value="{layer}"]')
            wait_idle(page, 500)
            if i == 1:
                page.keyboard.press("u")              # atajo de teclado
            else:
                page.click("#unc-toggle")
            page.wait_for_timeout(700)               # transición de 450 ms
            on = page.evaluate("window.__app.state.uncertainty")
            x, y = to_px(page, mid["lat"], mid["lon"])
            page.mouse.move(x, y)
            page.wait_for_timeout(350)
            tip = page.inner_text("#cursor-tip").replace("\n", " | ")
            card = page.inner_text("#card").replace("\n", " | ")
            print(f"{layer}: uncertainty={on} | tooltip: {tip} | card: {card}")
            if not on:
                fails.append(f"{layer}: no se activa la incertidumbre")
            if layer == "texture":
                page.screenshot(path=SHOTS / "1_3_uncertainty.png")
            if layer == "soc":
                page.screenshot(path=SHOTS / "1_3_uncertainty_soc.png")
            if layer == "ph" and "not available" not in tip.lower():
                fails.append("pH debería decir que no hay incertidumbre")
            page.click("#unc-toggle")
            page.wait_for_timeout(600)
            if page.evaluate("window.__app.state.uncertainty"):
                fails.append(f"{layer}: no se desactiva la incertidumbre")

        # Muestreo en el campo
        page.click('[data-action="layer"][data-value="reliability"]')
        wait_idle(page, 500)
        page.click("#sampling-btn")
        page.wait_for_timeout(900)
        n = page.locator(".sample-marker").count()
        page.locator(".sample-marker").first.hover()
        page.wait_for_timeout(400)
        reason = page.locator(".sample-tip").first.inner_text() if page.locator(".sample-tip").count() else ""
        print(f"muestreo campo: {n} marcadores | {reason.replace(chr(10), ' | ')}")
        if not n or not reason:
            fails.append("no hay marcadores de muestreo o motivo")
        page.mouse.move(5, 600)
        page.screenshot(path=SHOTS / "1_3_sampling.png")

        # Muestreo en la granja
        page.keyboard.press("b")
        wait_idle(page, 1400)
        n_farm = page.locator(".sample-marker").count()
        print(f"muestreo granja: {n_farm} marcadores")
        if n_farm <= n:
            fails.append("en la granja deberían verse los puntos de todos los campos")
        page.screenshot(path=SHOTS / "1_3_sampling_farm.png")
        return report(errors, fails)


if __name__ == "__main__":
    sys.exit(main())
