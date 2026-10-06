"""
Desglose de textura en f51, hover sincronizado, incertidumbre en un panel.

  .venv\\Scripts\\python tests\\ui\\check_textura.py
"""

from __future__ import annotations

import sys

from ui_common import F51, SHOTS, open_demo, open_field, report, session, wait_idle


def main() -> int:
    fails: list[str] = []
    with session() as (page, errors):
        open_demo(page)
        open_field(page, F51)                          # vista de mapa (capa Texture)
        page.click('[data-action="breakdown"]')
        page.wait_for_selector("#breakdown-view[data-ready='1']", timeout=60_000)
        page.wait_for_timeout(700)
        print("botón:", page.inner_text('[data-action="breakdown"]'))
        for p in ("clay", "sand", "silt"):
            print(f"{p}:", page.inner_text(f'.bd-panel[data-p="{p}"] .bd-stats').replace("\n", " | ")[:120])

        # Hover sincronizado en el centro del panel de arcilla
        box = page.locator('.bd-panel[data-p="clay"] .bd-frame').bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5)
        page.wait_for_timeout(400)
        vals = page.locator(".bd-frame.cross .bd-value").all_inner_texts()
        print("hover sincronizado:", vals)
        if len(vals) != 3 or any(not v for v in vals):
            fails.append("el hover no se sincroniza en los tres paneles")
        page.screenshot(path=SHOTS / "2_2_breakdown.png")

        # Incertidumbre solo en el panel de arena
        page.click('.bd-panel[data-p="sand"]')
        page.wait_for_timeout(700)
        page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5)
        page.wait_for_timeout(300)
        unc = [page.locator(f'.bd-panel[data-p="{p}"]').get_attribute("class") for p in ("clay", "sand", "silt")]
        print("paneles:", unc, "|", page.locator(".bd-frame.cross .bd-value").all_inner_texts())
        if "unc" not in unc[1] or "unc" in unc[0] or "unc" in unc[2]:
            fails.append("la incertidumbre no es independiente por panel")
        page.screenshot(path=SHOTS / "2_2_breakdown_uncertainty.png")

        page.click('[data-action="breakdown"]')        # Back to texture classes
        page.wait_for_selector("#breakdown-view", state="detached", timeout=5_000)
        wait_idle(page, 600)
        print("de vuelta:", page.inner_text('[data-action="breakdown"]'))
        return report(errors, fails)


if __name__ == "__main__":
    sys.exit(main())
