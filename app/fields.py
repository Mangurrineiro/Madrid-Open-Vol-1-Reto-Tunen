"""
Campos de entrada y rejilla común.

- Entrada: GeoJSON FeatureCollection; se ignoran los campos con isArchived == true.
- field_id = plotId (o fieldName si no hay plotId). Polygon y MultiPolygon.
- Rejilla: centros de píxel cada 25 m en EPSG:25832 (alineados a múltiplos de 25 m),
  quedándonos con los que caen dentro del polígono. Si ninguno cae dentro,
  se usa representative_point().
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

from .config import CRS_UTM, CRS_WGS84, GRID_STEP_M

TO_UTM = Transformer.from_crs(CRS_WGS84, CRS_UTM, always_xy=True)
TO_WGS = Transformer.from_crs(CRS_UTM, CRS_WGS84, always_xy=True)


@dataclass
class Grid:
    point_id: np.ndarray   # int
    x: np.ndarray          # EPSG:25832
    y: np.ndarray
    lon: np.ndarray        # EPSG:4326
    lat: np.ndarray
    step: float = GRID_STEP_M

    def __len__(self) -> int:
        return len(self.point_id)


@dataclass
class Field:
    field_id: str
    name: str
    geom: object            # shapely, EPSG:4326
    geom_utm: object        # shapely, EPSG:25832
    properties: dict = field(default_factory=dict)
    _grid: Grid | None = None

    @property
    def area_ha(self) -> float:
        return self.geom_utm.area / 10_000

    @property
    def grid(self) -> Grid:
        if self._grid is None:
            self._grid = make_grid(self.geom_utm)
        return self._grid


def make_grid(geom_utm, step: float = GRID_STEP_M) -> Grid:
    minx, miny, maxx, maxy = geom_utm.bounds
    xs = np.arange(np.floor(minx / step) * step + step / 2, maxx, step)
    ys = np.arange(np.floor(miny / step) * step + step / 2, maxy, step)
    gx, gy = np.meshgrid(xs, ys[::-1])           # filas de norte a sur
    gx, gy = gx.ravel(), gy.ravel()
    inside = shapely.contains_xy(geom_utm, gx, gy)
    gx, gy = gx[inside], gy[inside]
    if len(gx) == 0:
        p = geom_utm.representative_point()
        gx, gy = np.array([p.x]), np.array([p.y])
    lon, lat = TO_WGS.transform(gx, gy)
    return Grid(np.arange(len(gx)), gx, gy, np.asarray(lon), np.asarray(lat), step)


def parse_fields(fc: dict) -> list[Field]:
    out = []
    for i, feat in enumerate(fc.get("features", [])):
        props = feat.get("properties") or {}
        if props.get("isArchived") is True:
            continue
        geom = feat.get("geometry")
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        g = shape(geom)
        if not g.is_valid:
            g = g.buffer(0)
        fid = str(props.get("plotId") or props.get("fieldName") or f"field_{i}")
        name = str(props.get("fieldName") or fid)
        out.append(Field(fid, name, g, shp_transform(TO_UTM.transform, g), props))
    return out


def load_fields(path: Path) -> list[Field]:
    return parse_fields(json.loads(Path(path).read_text(encoding="utf-8")))


def find_field(fields: list[Field], key: str) -> Field:
    """Busca por field_id o por nombre exacto (útil en CLI/pruebas)."""
    for f in fields:
        if key in (f.field_id, f.name):
            return f
    raise KeyError(f"Campo no encontrado: {key}")
