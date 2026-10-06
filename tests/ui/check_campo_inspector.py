"""
Vista de campo f51, tooltip en 3 puntos, inspector en un punto con conflicto.

  .venv\\Scripts\\python tests\\ui\\check_campo_inspector.py
"""

from __future__ import annotations

import sys

from ui_common import F51, SHOTS, open_demo, open_field, points, report, session, to_px, wait_idle


def main() -> int:
    fails: list[str] = []
    with session() as (page, errors):
        open_demo(page)
        fid = open_field(page, F51)
        head = page.inner_text(".field-head").replace("\n", " | ")
        print("panel:", head)
        print("tarjeta:", page.inner_text("#card").replace("\n", " | "))
        if F51 not in head:
            fails.append("el panel no muestra el campo")
        page.screenshot(path=SHOTS / "1_2_field.png")

        pts = points(fid)
        for k, i in enumerate((len(pts) // 5, len(pts) // 2, 4 * len(pts) // 5)):
            x, y = to_px(page, pts[i]["lat"], pts[i]["lon"])
            page.mouse.move(x, y)
            page.wait_for_timeout(350)
            tip = page.inner_text("#cursor-tip") if page.is_visible("#cursor-tip.on") else ""
            print(f"tooltip {k + 1}:", tip.replace("\n", " | "))
            if not tip:
                fails.append(f"sin tooltip en el punto {i}")
            if k == 1:
                page.screenshot(path=SHOTS / "1_2_tooltip.png")

        # Tooltip de Bodenzahl
        page.click('[data-action="layer"][data-value="bodenzahl"]')
        wait_idle(page, 500)
        x, y = to_px(page, pts[len(pts) // 2]["lat"], pts[len(pts) // 2]["lon"])
        page.mouse.move(x, y + 1)
        page.wait_for_timeout(350)
        print("tooltip bodenzahl:", page.inner_text("#cursor-tip").replace("\n", " | "))
        print("tarjeta bodenzahl:", page.inner_text("#card").replace("\n", " | "))
        page.screenshot(path=SHOTS / "1_2_bodenzahl.png")

        # Inspector en un punto con conflicto (o el central si no hay)
        page.click('[data-action="layer"][data-value="texture"]')
        wait_idle(page, 500)
        conflict = [p for p in pts if (p.get("clay_conflict") or {}).get("value") == 1]
        p = conflict[len(conflict) // 2] if conflict else pts[len(pts) // 2]
        x, y = to_px(page, p["lat"], p["lon"])
        page.mouse.click(x, y)
        page.wait_for_selector(".inspector-popup", timeout=10_000)
        page.wait_for_timeout(700)
        txt = page.inner_text(".inspector-popup")
        print("inspector:", txt.replace("\n", " | ")[:400])
        if conflict and "Physical contradiction" not in txt:
            fails.append("el inspector no muestra el conflicto")
        page.screenshot(path=SHOTS / "1_2_inspector.png")

        page.click('[data-action="back"]')
        wait_idle(page, 800)
        if page.is_visible(".field-head"):
            fails.append("Back to farm no vuelve a la granja")
        return report(errors, fails)


if __name__ == "__main__":
    sys.exit(main())
