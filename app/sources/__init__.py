"""
Registro de fuentes. Añadir una fuente = un fichero nuevo en esta carpeta con una
clase decorada con @register_source (y su import abajo).
"""

from __future__ import annotations

from .base import SOURCES, Source, register_source, row  # noqa: F401

# Importar los módulos registra sus fuentes.
from . import buek200, derived, lbeg, soilgrids  # noqa: F401,E402
