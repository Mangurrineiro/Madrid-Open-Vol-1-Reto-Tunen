"""
Prueba sintética del módulo de terreno (sin red):

  .venv\\Scripts\\python tests\\test_terrain.py

Plano que sube hacia el este → aspect "W"; hacia el norte → "S"; horizontal → "Flat".
Además, el hillshade (luz del NO) ilumina más una ladera que mira al NO que una que mira al SE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sources.copernicus_dem import aspect_class, hillshade, slope_aspect  # noqa: E402

DX = DY = 30.0
rows, cols = np.mgrid[0:20, 0:20].astype(float)   # filas N→S


def clase(dem: np.ndarray) -> str:
    s, a = slope_aspect(dem, DX, DY)
    return str(aspect_class(a[10, 10], s[10, 10]))


east_up = cols * 3.0                 # sube hacia el este (columna creciente)
north_up = (19 - rows) * 3.0         # sube hacia el norte (fila 0 = norte)
flat = np.full((20, 20), 50.0)

checks = {
    "sube al este → W": clase(east_up) == "W",
    "sube al norte → S": clase(north_up) == "S",
    "horizontal → Flat": clase(flat) == "Flat",
    "pendiente del plano = atan(3/30)": abs(slope_aspect(east_up, DX, DY)[0][10, 10] - np.degrees(np.arctan(0.1))) < 1e-6,
    # ladera que mira al NO (sube hacia el SE) más iluminada que la que mira al SE
    "hillshade NO > SE": hillshade(cols * 3 + rows * 3, DX, DY)[10, 10] > hillshade(-(cols * 3 + rows * 3), DX, DY)[10, 10],
}
for k, ok in checks.items():
    print(f"  {'OK ' if ok else 'FALLO'} {k}")
sys.exit(0 if all(checks.values()) else 1)
