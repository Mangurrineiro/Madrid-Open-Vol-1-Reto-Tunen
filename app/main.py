"""
API FastAPI.

  uvicorn app.main:app --reload

POST /soil/layers   {"fields": FeatureCollection, "parameters": [...]?, "sources": [...]?}
GET  /sources       matriz de fuentes (nombre, parámetros, cobertura, resolución, notas)
GET  /parameters    unidad, rango del colormap y descripción
/renders/...        PNG y grid JSON generados
"""

from __future__ import annotations

from collections import Counter

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import PARAMETERS, RENDERS
from .fields import parse_fields
from .pipeline import run_field
from .render import layer_stats, layer_status, render_layer
from .sources import SOURCES

app = FastAPI(title="Tunen Soil Aggregation API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
RENDERS.mkdir(parents=True, exist_ok=True)
app.mount("/renders", StaticFiles(directory=RENDERS), name="renders")


class LayersRequest(BaseModel):
    fields: dict
    parameters: list[str] | None = None
    sources: list[str] | None = None


def _message(source: str, status: str, rows: list[dict]) -> str | None:
    if status == "ok":
        return None
    reason = Counter(str(r["original"]) for r in rows if r["status"] == status).most_common(1)
    reason = reason[0][0] if reason else ""
    if source == "lbeg" and status == "no_coverage":
        return "LBEG solo cubre Niedersachsen" + (f" ({reason})" if "Niedersachsen" not in reason else "")
    return reason or status


@app.post("/soil/layers")
def soil_layers(req: LayersRequest) -> dict:
    if req.fields.get("type") != "FeatureCollection":
        raise HTTPException(400, "fields debe ser un GeoJSON FeatureCollection")
    bad = [s for s in (req.sources or []) if s not in SOURCES]
    if bad:
        raise HTTPException(400, f"fuentes desconocidas: {bad}; disponibles: {list(SOURCES)}")
    bad = [p for p in (req.parameters or []) if p not in PARAMETERS]
    if bad:
        raise HTTPException(400, f"parámetros desconocidos: {bad}; disponibles: {list(PARAMETERS)}")

    out = []
    for field in parse_fields(req.fields):
        rows = run_field(field, req.sources, req.parameters)
        groups: dict[tuple[str, str], list[dict]] = {}
        for r in rows:
            groups.setdefault((r["source"], r["parameter"]), []).append(r)
        layers = []
        for (source, parameter), rs in groups.items():
            status = layer_status(rs)
            layer = {"parameter": parameter, "source": source, "unit": PARAMETERS[parameter]["unit"],
                     "status": status, "png_url": None, "grid_url": None, "stats": layer_stats(rs),
                     "colormap": None, "message": _message(source, status, rs),
                     "status_counts": dict(Counter(r["status"] for r in rs)),
                     "provenance": {
                         "source": SOURCES[source].title,
                         "detail": Counter(r["provenance"] for r in rs if r["status"] == "ok").most_common(1)[0][0]
                         if status == "ok" else rs[0]["provenance"],
                         "notes": SOURCES[source].notes,
                         "resolution": SOURCES[source].resolution,
                     }}
            if status == "ok":
                layer.update({k: v for k, v in render_layer(field, rs, source, parameter).items() if k != "size"})
            layers.append(layer)
        lon_w, lat_s, lon_e, lat_n = field.geom.bounds
        out.append({"field_id": field.field_id, "name": field.name, "area_ha": round(field.area_ha, 2),
                    "n_points": len(field.grid), "bounds": [[lat_s, lon_w], [lat_n, lon_e]],
                    "layers": layers})
    return {"fields": out}


@app.get("/sources")
def sources() -> list[dict]:
    return [s.info() for s in SOURCES.values()]


@app.get("/parameters")
def parameters() -> dict:
    return {k: {"unit": v["unit"], "colormap": {"name": v["cmap"], "min": v["min"], "max": v["max"]},
                "description": v["desc"]} for k, v in PARAMETERS.items()}
