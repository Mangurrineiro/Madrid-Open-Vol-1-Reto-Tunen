"""
Recorrido completo de la demo como serie de capturas, con atajos de teclado.
landing → granja → campo destacado → pila → capa → incertidumbre → muestreo → desglose.

  .venv\\Scripts\\python tests\\ui\\check_recorrido_demo.py           # 1920×1080 → out/screens/demo_tour/
  .venv\\Scripts\\python tests\\ui\\check_recorrido_demo.py 1366 768  # → out/screens/demo_tour_1366/
"""

from __future__ import annotations

import sys

from ui_common import SHOTS, URL, report, session, wait_idle


def overlaps(page) -> list[str]:
    """Elementos flotantes que se pisan (cabecera, panel, vistas 3D, inspector)."""
    return page.evaluate("""() => {
      const r = (s) => { const e = document.querySelector(s); if (!e || !e.offsetParent && getComputedStyle(e).position !== 'fixed') return null;
        const b = e.getBoundingClientRect(); return b.width && b.height && getComputedStyle(e).opacity > 0.05 ? b : null; };
      const hit = (a, b) => a && b && a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
      const out = [];
      const panel = r('#panel'), header = r('#farm-header');
      for (const s of ['.stack-label', '.bd-panel', '.bd-head', '.inspector-popup', '.leaflet-control-zoom']) {
        document.querySelectorAll(s).forEach((e, i) => {
          const b = e.getBoundingClientRect();
          if (getComputedStyle(e).opacity < 0.05 || !b.width) return;
          if (hit(b, panel)) out.push(`${s}[${i}] pisa el panel`);
          if (hit(b, header)) out.push(`${s}[${i}] pisa la cabecera`);
        });
      }
      if (hit(panel, header)) out.push('la cabecera pisa el panel');
      if (document.querySelector('#panel').scrollWidth > document.querySelector('#panel').clientWidth + 1) out.push('scroll horizontal en el panel');
      return out;
    }""")


def main() -> int:
    w, h = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (1920, 1080)
    d = SHOTS / ("demo_tour" if w == 1920 else f"demo_tour_{w}")
    d.mkdir(parents=True, exist_ok=True)
    fails: list[str] = []
    with session(w, h) as (page, errors):
        def shot(name: str) -> None:
            page.screenshot(path=d / f"{name}.png")
            for o in overlaps(page):
                fails.append(f"{name}: {o}")

        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot("01_landing")

        page.click("#try-demo")
        page.wait_for_selector("body.farm", timeout=180_000)
        wait_idle(page, 2200)
        shot("02_farm")

        page.click(".featured-item")                         # campo destacado → la pila entra
        page.wait_for_timeout(650)
        shot("03_featured_field")
        page.wait_for_selector("#stack-view.ready", timeout=60_000)
        page.wait_for_timeout(500)
        shot("04_stack")

        page.keyboard.press("4")                             # nFK desde la pila
        page.wait_for_selector("#stack-view", state="detached", timeout=10_000)
        wait_idle(page, 1000)
        if page.evaluate("window.__app.state.layerId") != "nfk":
            fails.append("la tecla 4 no abre la capa nFK desde la pila")
        shot("05_layer")

        page.keyboard.press("u")
        page.wait_for_timeout(900)
        shot("06_uncertainty")

        page.keyboard.press("u")
        page.keyboard.press("s")
        page.wait_for_timeout(900)
        page.locator(".sample-marker").first.hover()
        page.wait_for_timeout(400)
        shot("07_sampling")
        page.keyboard.press("s")

        page.keyboard.press("1")
        wait_idle(page, 600)
        page.click('[data-action="breakdown"]')
        page.wait_for_selector("#breakdown-view[data-ready='1']", timeout=60_000)
        page.wait_for_timeout(700)
        box = page.locator('.bd-panel[data-p="clay"] .bd-frame').bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.55)
        page.wait_for_timeout(300)
        shot("08_breakdown")

        # Atajos de vuelta: B cierra el desglose, B vuelve a la granja
        page.keyboard.press("b")
        page.wait_for_timeout(600)
        page.keyboard.press("b")
        wait_idle(page, 1200)
        if page.evaluate("window.__app.state.view") != "farm":
            fails.append("B no vuelve a la granja")
        shot("09_back_to_farm")
        print("capturas:", sorted(p.name for p in d.glob("*.png")))
        return report(errors, fails)


if __name__ == "__main__":
    sys.exit(main())
