"""
Pila isométrica en f51 y f82, hover, entrar en 2 capas y volver a la pila.

  .venv\\Scripts\\python tests\\ui\\check_pila3d.py
"""

from __future__ import annotations

import sys

from ui_common import F51, F82, SHOTS, open_demo, open_field, report, session, wait_idle


def enter_and_back(page, how: str, layer: str, fails: list[str], shot_mid: str | None = None) -> None:
    if how == "label":
        page.click(f'.stack-label[data-layer="{layer}"]')
    else:
        page.click(f'#panel [data-stack="{layer}"]')
    if shot_mid:
        page.wait_for_timeout(280)                       # mitad de la animación de 600 ms
        page.screenshot(path=SHOTS / shot_mid)
    page.wait_for_selector("#stack-view", state="detached", timeout=10_000)
    wait_idle(page, 900)
    active = page.evaluate("window.__app.state.layerId")
    print(f"entrar en {layer} ({how}): capa activa = {active}, panel de campo = {page.is_visible('.field-head #card, #card')}")
    if active != layer:
        fails.append(f"no se activó la capa {layer}")
    page.screenshot(path=SHOTS / f"2_1_layer_{layer}.png")
    page.click('[data-action="stack"]')
    page.wait_for_selector("#stack-view.ready", timeout=10_000)
    page.wait_for_timeout(500)


def main() -> int:
    fails: list[str] = []
    with session() as (page, errors):
        open_demo(page)
        open_field(page, F51, stack=True)
        n = page.locator("#stack-view .sheet").count()
        labels = page.locator(".stack-label").all_inner_texts()
        print(f"f51: {n} láminas (6 + base) | etiquetas: {[t.replace(chr(10), ': ') for t in labels]}")
        if n != 7:
            fails.append(f"se esperaban 7 láminas, hay {n}")
        page.screenshot(path=SHOTS / "2_1_stack_f51.png")

        # Hover sobre una lámina: se eleva y las demás se atenúan
        page.hover('.stack-label[data-layer="soc"]')
        page.wait_for_timeout(500)
        dim = page.locator(".sheet.dim").count()
        print(f"hover: {dim} láminas atenuadas")
        if dim != 5:
            fails.append("el hover no atenúa las demás láminas")
        page.screenshot(path=SHOTS / "2_1_stack_hover.png")
        page.mouse.move(10, 900)

        # Rotación con arrastre
        page.mouse.move(500, 600)
        page.mouse.down()
        page.mouse.move(700, 600, steps=8)
        page.mouse.up()
        page.wait_for_timeout(300)
        rz = page.evaluate("document.querySelector('.stack-stage').style.transform")
        print("tras arrastrar:", rz)

        enter_and_back(page, "label", "ph", fails, shot_mid="2_1_transition.png")
        enter_and_back(page, "panel", "bodenzahl", fails)

        page.keyboard.press("b")
        wait_idle(page, 1200)
        open_field(page, F82, stack=True)
        labels = page.locator(".stack-label").all_inner_texts()
        print(f"f82: etiquetas: {[t.replace(chr(10), ': ') for t in labels]}")
        page.screenshot(path=SHOTS / "2_1_stack_f82.png")
        return report(errors, fails)


if __name__ == "__main__":
    sys.exit(main())
