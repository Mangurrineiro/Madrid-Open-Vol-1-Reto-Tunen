"""Rutas y constantes compartidas por el backend."""

from __future__ import annotations

import sys
from pathlib import Path

# La consola de Windows usa cp1252 por defecto: forzamos UTF-8 (umlauts).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "cache"            # una subcarpeta por fuente: data/cache/<source>/
RENDERS = DATA / "renders"        # PNG + grid JSON generados
LOOKUPS = ROOT / "lookups"
STATIC = ROOT / "static"
FIELDS_GEOJSON = DATA / "fields.geojson"

USER_AGENT = "tunen-hackathon-soil-api/1.0 (research; hackathon)"

GRID_STEP_M = 25.0                # rejilla común: un punto cada 25 m en EPSG:25832
CRS_WGS84 = "EPSG:4326"
CRS_UTM = "EPSG:25832"

# Parámetros comunes: unidad, rango fijo del colormap, colormap y descripción.
PARAMETERS: dict[str, dict] = {
    "clay":      {"unit": "%",     "min": 0, "max": 60,  "cmap": "YlOrBr",  "desc": "Arcilla (<2 µm), 0–30 cm"},
    "sand":      {"unit": "%",     "min": 0, "max": 100, "cmap": "YlOrBr",  "desc": "Arena (63 µm–2 mm), 0–30 cm"},
    "silt":      {"unit": "%",     "min": 0, "max": 100, "cmap": "YlOrBr",  "desc": "Limo (2–63 µm), 0–30 cm"},
    "ph_h2o":    {"unit": "-",     "min": 3, "max": 8,   "cmap": "RdYlBu",  "desc": "pH en agua, 0–30 cm"},
    "ph_cacl2":  {"unit": "-",     "min": 3, "max": 8,   "cmap": "RdYlBu",  "desc": "pH en CaCl2, 0–30 cm"},
    "soc":       {"unit": "g/kg",  "min": 0, "max": 60,  "cmap": "YlGnBu",  "desc": "Carbono orgánico, 0–30 cm"},
    "nfk":       {"unit": "mm/dm", "min": 0, "max": 30,  "cmap": "Blues",   "desc": "Capacidad de campo útil (nFK)"},
    "bodenzahl": {"unit": "0-100", "min": 0, "max": 100, "cmap": "RdYlGn",  "desc": "Bodenzahl (Bodenschätzung)"},
    "ackerzahl": {"unit": "0-100", "min": 0, "max": 100, "cmap": "RdYlGn",  "desc": "Ackerzahl (Bodenschätzung)"},
    "bodenart_bs": {"unit": "texto", "min": None, "max": None, "cmap": "tab20", "desc": "Bodenart de la Bodenschätzung"},
    "ertragsfaehigkeit": {"unit": "BFR 1-7", "min": 1, "max": 7, "cmap": "RdYlGn", "desc": "Ertragsfähigkeit BK50"},
    "soil_type": {"unit": "texto", "min": None, "max": None, "cmap": "tab20", "desc": "Tipo de suelo (BK50)"},
    # Capas de fiabilidad (fuente derived). max None = 0..máximo de la capa.
    "clay_disagreement": {"unit": "%", "min": 0, "max": None, "cmap": "magma", "desc": "Desacuerdo de arcilla entre fuentes (máx − mín)"},
    "sand_disagreement": {"unit": "%", "min": 0, "max": None, "cmap": "magma", "desc": "Desacuerdo de arena entre fuentes (máx − mín)"},
    "silt_disagreement": {"unit": "%", "min": 0, "max": None, "cmap": "magma", "desc": "Desacuerdo de limo entre fuentes (máx − mín)"},
    "soc_disagreement":  {"unit": "g/kg", "min": 0, "max": None, "cmap": "magma", "desc": "Desacuerdo de carbono orgánico entre fuentes (máx − mín)"},
    "nfk_disagreement":  {"unit": "mm/dm", "min": 0, "max": None, "cmap": "magma", "desc": "Desacuerdo de nFK entre fuentes (máx − mín)"},
    "clay_conflict": {"unit": "0/1", "min": 0, "max": 1, "cmap": "RdYlGn_r",
                      "desc": "Conflicto: arcilla SoilGrids > partículas finas máx. de la Bodenschätzung (imposible)"},
}
