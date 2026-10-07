"""Rutas y constantes compartidas por el backend."""

from __future__ import annotations

import os
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
CACHE = DATA / "cache"            # una subcarpeta por fuente: data/cache/<source>/ (local, no se versiona)
DEMO_CACHE = DATA / "demo" / "cache"  # respuestas de la granja de ejemplo (versionadas, solo lectura)
RENDERS = DATA / "renders"        # PNG + grid JSON generados
LOOKUPS = ROOT / "lookups"
STATIC = ROOT / "static"
# Granja de ejemplo: campos sintéticos dibujados sobre parcelas agrícolas cerca de Vienenburg
# (Niedersachsen / Sachsen-Anhalt). FIELDS_GEOJSON=<ruta> la sustituye por otra granja local.
FIELDS_GEOJSON = Path(os.environ.get("FIELDS_GEOJSON") or DATA / "demo" / "example_farm.geojson")
if not FIELDS_GEOJSON.is_absolute():
    FIELDS_GEOJSON = ROOT / FIELDS_GEOJSON

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
    # Capas de app/analysis.py: clase KA5 de BÜK200, σ del modelo y prioridad de muestreo.
    "ka5_class": {"unit": "texto", "min": None, "max": None, "cmap": "tab20", "desc": "Bodenart KA5 dominante (BÜK200, horizonte superior)"},
    "clay_sigma": {"unit": "%", "min": 0, "max": None, "cmap": "magma", "desc": "σ del modelo de la arcilla combinada"},
    "sand_sigma": {"unit": "%", "min": 0, "max": None, "cmap": "magma", "desc": "σ del modelo de la arena combinada"},
    "silt_sigma": {"unit": "%", "min": 0, "max": None, "cmap": "magma", "desc": "σ del modelo del limo combinado"},
    "soc_sigma":  {"unit": "g/kg", "min": 0, "max": None, "cmap": "magma", "desc": "σ del modelo del carbono orgánico combinado"},
    "nfk_sigma":  {"unit": "mm/dm", "min": 0, "max": None, "cmap": "magma", "desc": "σ del modelo de la nFK combinada"},
    "sampling_priority": {"unit": "0-1", "min": 0, "max": 1, "cmap": "RdYlGn_r",
                          "desc": "Prioridad de muestreo: desacuerdo normalizado entre fuentes + conflicto (UI: fiabilidad = 100·(1−p))"},
}

ANALYSIS_PARAMETERS = ["ka5_class", "clay_sigma", "sand_sigma", "silt_sigma", "soc_sigma", "nfk_sigma",
                       "sampling_priority"]

# ---------- Módulo adicional de terreno (Copernicus DEM GLO-30) ----------
# Con ENABLE_TERRAIN=False (o la variable de entorno ENABLE_TERRAIN=0) no se registra la fuente
# ni se añaden parámetros ni capas de terreno.
ENABLE_TERRAIN = os.environ.get("ENABLE_TERRAIN", "1").strip().lower() not in ("0", "false", "no", "off")
TERRAIN_PARAMETERS = ["elevation", "elevation_rel", "slope", "aspect", "hillshade"]

if ENABLE_TERRAIN:
    PARAMETERS.update({
        "elevation":     {"unit": "m", "min": None, "max": None, "cmap": "tunen_elevation",
                          "desc": "Elevation above sea level (Copernicus DEM GLO-30, surface model)"},
        "elevation_rel": {"unit": "m", "min": 0, "max": None, "cmap": "tunen_elevation",
                          "desc": "Metres above the lowest point of the field"},
        "slope":         {"unit": "°", "min": 0, "max": None, "cmap": "tunen_slope",
                          "desc": "Slope in degrees (from the DEM, 2-pixel halo)"},
        "aspect":        {"unit": "texto", "min": None, "max": None, "cmap": "tab20",
                          "desc": "Direction the terrain faces (downhill): N, NE, E, SE, S, SW, W, NW or Flat (slope < 0.5°)"},
        "hillshade":     {"unit": "0-255", "min": 0, "max": 255, "cmap": "gray",
                          "desc": "Relief shading (visual only): azimuth 315°, altitude 45°, vertical exaggeration ×3"},
        "acker_delta":   {"unit": "0-100", "min": -10, "max": 10, "cmap": "tunen_acker_delta",
                          "desc": "Difference between the adjusted agricultural score (Ackerzahl) and the natural soil "
                                  "score (Bodenzahl). The adjustment reflects several site factors such as climate "
                                  "and terrain."},
    })
    ANALYSIS_PARAMETERS = ANALYSIS_PARAMETERS + ["acker_delta"]
