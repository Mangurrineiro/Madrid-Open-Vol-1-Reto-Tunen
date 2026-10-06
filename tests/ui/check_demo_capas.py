"""
Pantalla inicial → demo → 6 capas y 2 cambios de fuente, 0 errores de consola.

  .venv\\Scripts\\python tests\\ui\\check_demo_capas.py

Arranca uvicorn en el puerto 8765, abre Chromium (Playwright) a 1920×1080 y guarda capturas en
out/screens/. Sale con código 1 si hay errores de consola o falla alguna acción.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "out" / "screens"
PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
LAYERS = ["texture", "ph", "soc", "nfk", "bodenzahl", "reliability"]


def start_server() -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            if httpx.get(URL, timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("uvicorn no arrancó")


def wait_idle(page, settle_ms: int = 900) -> None:
    page.wait_for_function("window.__app && window.__app.state.idle === true", timeout=120_000)
    page.wait_for_timeout(settle_ms)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    proc = start_server()
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(1500)
            page.screenshot(path=SHOTS / "1_1_landing.png")

            page.click("#try-demo")
            page.wait_for_selector("body.farm", timeout=180_000)
            wait_idle(page, 2200)                       # vuelo del mapa + teselas
            chips = page.inner_text("#farm-chips")
            print("cabecera:", page.inner_text("#farm-name"), "|", chips.replace("\n", " · "))

            for layer in LAYERS:
                page.click(f'[data-action="layer"][data-value="{layer}"]')
                wait_idle(page)
                active = page.inner_text(".layer-item.active .layer-name")
                print(f"capa {layer}: activa='{active}', leyenda={'sí' if page.inner_html('#legend').strip() else 'NO'}")
                page.screenshot(path=SHOTS / f"1_1_farm_{layer}.png")

            # 2 cambios de fuente
            for layer, src in (("ph", "buek200"), ("texture", "lbeg")):
                page.click(f'[data-action="layer"][data-value="{layer}"]')
                wait_idle(page, 300)
                page.click(f'[data-action="source"][data-value="{src}"]')
                wait_idle(page)
                on = page.inner_text(".segmented.sources button.on")
                print(f"fuente {layer} → {src}: botón activo='{on}', título='{page.inner_text('.active-layer h3')}'")
                page.screenshot(path=SHOTS / f"1_1_farm_{layer}_{src}.png")

            # Hover sobre un campo destacado: etiqueta con nombre y hectáreas
            page.click('[data-action="source"][data-value="auto"]')
            wait_idle(page, 300)
            # Acercar sin seleccionar (el clic en un destacado abre la vista de campo)
            page.evaluate("""() => { const s = window.__app.state, f = s.byId.get(s.featured[0].field_id);
              window.__app.map.fitBounds(f.bounds, { paddingBottomRight: [420, 0] }); }""")
            page.wait_for_timeout(1400)
            xy = page.evaluate("""() => {
              const s = window.__app.state, f = s.byId.get(s.featured[0].field_id);
              const m = window.__app.map, b = L.latLngBounds(f.bounds), c = m.latLngToContainerPoint(b.getCenter());
              return [c.x, c.y];
            }""")
            page.mouse.move(xy[0], xy[1])
            page.wait_for_timeout(500)
            label = page.locator(".field-label").first.inner_text() if page.locator(".field-label").count() else ""
            print("etiqueta hover:", label.replace("\n", " "))
            page.screenshot(path=SHOTS / "1_1_hover.png")

            # Pantalla pequeña
            page.set_viewport_size({"width": 1366, "height": 768})
            page.wait_for_timeout(800)
            page.screenshot(path=SHOTS / "1_1_farm_1366.png")
            browser.close()
            if not label:
                errors.append("no aparece la etiqueta del campo al pasar el ratón")
    finally:
        proc.kill()

    print(f"\n{len(errors)} errores")
    for e in errors:
        print("  ", e)
    print(f"capturas en {SHOTS}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
