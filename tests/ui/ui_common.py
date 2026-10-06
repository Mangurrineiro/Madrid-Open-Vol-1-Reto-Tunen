"""Utilidades compartidas por los tests de UI (Playwright)."""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "out" / "screens"
PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
F51 = "Umfeld Groß"
F82 = "Mittelbreite"


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


@contextmanager
def session(width: int = 1920, height: int = 1080):
    """(page, errors): servidor + Chromium; errors acumula errores de consola y de página."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    proc = start_server()
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            yield page, errors
            browser.close()
    finally:
        proc.kill()


def wait_idle(page, settle_ms: int = 900) -> None:
    page.wait_for_function("window.__app && window.__app.state.idle === true", timeout=180_000)
    page.wait_for_timeout(settle_ms)


def open_demo(page) -> None:
    page.goto(URL, wait_until="networkidle")
    page.click("#try-demo")
    page.wait_for_selector("body.farm", timeout=180_000)
    wait_idle(page, 1800)


def field_id(page, name: str) -> str:
    return page.evaluate("(n) => window.__app.state.fields.find((f) => f.name === n).field_id", name)


def open_field(page, name: str, stack: bool = False) -> str:
    """Abre el campo. Se abre en la pila 3D; stack=False pasa a la vista de mapa."""
    fid = field_id(page, name)
    page.evaluate("(id) => window.__app.enterField(id)", fid)
    page.wait_for_timeout(300)
    if stack:
        page.wait_for_selector("#stack-view.ready", timeout=60_000)
        page.wait_for_timeout(400)
        return fid
    page.wait_for_timeout(500)
    page.evaluate("() => window.__app.closeStack && window.__app.closeStack()")
    wait_idle(page, 1300)
    return fid


def to_px(page, lat: float, lon: float) -> tuple[float, float]:
    xy = page.evaluate("([lat, lon]) => { const p = window.__app.map.latLngToContainerPoint([lat, lon]); return [p.x, p.y]; }",
                       [lat, lon])
    return xy[0], xy[1]


def points(fid: str) -> list[dict]:
    return httpx.get(f"{URL}soil/fields/{fid}/points", timeout=60).json()["points"]


def report(errors: list[str], extra: list[str] | None = None) -> int:
    errs = errors + (extra or [])
    print(f"\n{len(errs)} errores")
    for e in errs:
        print("  ", e)
    print(f"capturas en {SHOTS}")
    return 1 if errs else 0
