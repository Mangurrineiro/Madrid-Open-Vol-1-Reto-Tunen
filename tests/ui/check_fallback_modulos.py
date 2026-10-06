"""
Si stack3d.js / texture3.js fallan, la vista de mapa funciona y los botones de las vistas 3D no aparecen.

  .venv\\Scripts\\python tests\\ui\\check_fallback_modulos.py
"""

from __future__ import annotations

import sys

from ui_common import F51, URL, report, session, wait_idle


def main() -> int:
    fails: list[str] = []
    with session() as (page, errors):
        for mod in ("stack3d.js", "texture3.js"):
            page.route(f"**/static/js/{mod}", lambda route: route.fulfill(status=500, body="boom"))
        page.goto(URL, wait_until="networkidle")
        page.click("#try-demo")
        page.wait_for_selector("body.farm", timeout=180_000)
        wait_idle(page, 1000)
        fid = page.evaluate("(n) => window.__app.state.fields.find((f) => f.name === n).field_id", F51)
        page.evaluate("(id) => window.__app.enterField(id)", fid)
        wait_idle(page, 1200)
        stack = page.locator("#stack-view").count()
        buttons = page.locator('[data-action="stack"], [data-action="breakdown"]').count()
        card = page.inner_text("#card")
        print(f"pila abierta: {stack} | botones de las vistas 3D: {buttons} | tarjeta: {card[:60]!r}")
        if stack or buttons:
            fails.append("con los módulos caídos no deberían verse la pila ni sus botones")
        if not card.strip():
            fails.append("la vista de campo no se pinta")
        page.keyboard.press("u")
        page.wait_for_timeout(700)
        if not page.evaluate("window.__app.state.uncertainty"):
            fails.append("la incertidumbre no funciona")
        # Los 500 simulados dejan errores de red en consola: son los esperados
        errors[:] = [e for e in errors if "status of 500" not in e and "stack3d" not in e and "texture3" not in e]
        return report(errors, fails)


if __name__ == "__main__":
    sys.exit(main())
