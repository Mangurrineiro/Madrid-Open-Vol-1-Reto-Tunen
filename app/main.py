"""
API FastAPI.

  uvicorn app.main:app --reload

POST /soil/layers   {"fields": FeatureCollection, "parameters": [...]?, "sources": [...]?}
GET  /sources       matriz de fuentes (nombre, parámetros, cobertura, resolución, notas)
GET  /parameters    unidad, rango del colormap y descripción
POST /refresh       {"source": X?, "fields": FeatureCollection?} vacía la caché y recalcula
GET  /refresh       estado del último refresco
GET  /              UI (static/index.html);  GET /fields.geojson  campos de la granja
/renders/...        PNG y grid JSON generados
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cache
from .config import FIELDS_GEOJSON, PARAMETERS, RENDERS, STATIC
from .fields import parse_fields
from .pipeline import run_field
from .render import layer_stats, layer_status, render_layer
from .sources import SOURCES

app = FastAPI(title="Tunen Soil Aggregation API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
RENDERS.mkdir(parents=True, exist_ok=True)
app.mount("/renders", StaticFiles(directory=RENDERS), name="renders")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/fields.geojson", include_in_schema=False)
def fields_geojson():
    return FileResponse(FIELDS_GEOJSON, media_type="application/geo+json")


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
                if parameter.endswith("_disagreement"):
                    layer["stats"]["n_sources_max"] = max(
                        (len(json.loads(r["original"])) for r in rs if r["status"] == "ok"), default=0)
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


@app.get("/legend/{cmap}.png", include_in_schema=False)
def legend(cmap: str):
    """Barra de color horizontal del colormap (la misma que usan los PNG)."""
    import io

    import numpy as np
    from matplotlib import colormaps
    from PIL import Image

    if cmap not in colormaps:
        raise HTTPException(404, f"colormap desconocido: {cmap}")
    rgba = (colormaps[cmap](np.linspace(0, 1, 256))[None, :, :] * 255).astype("uint8").repeat(12, 0)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


class RefreshRequest(BaseModel):
    source: str | None = None
    fields: dict | None = None


REFRESH = {"state": "idle"}
_refresh_lock = threading.Lock()


@app.post("/refresh")
def refresh(req: RefreshRequest) -> dict:
    """Vacía la caché de una fuente (o de todas) y recalcula en segundo plano.

    La caché anterior se conserva en data/cache/_stale/ y se reutiliza si la red falla.
    """
    if req.source and req.source not in SOURCES:
        raise HTTPException(400, f"fuente desconocida: {req.source}; disponibles: {list(SOURCES)}")
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(409, "ya hay un refresco en curso (GET /refresh)")
    try:
        fc = req.fields or json.loads(FIELDS_GEOJSON.read_text(encoding="utf-8"))
        fields = parse_fields(fc)
        cleared = cache.clear(req.source)
    except Exception:
        _refresh_lock.release()
        raise
    sources = [req.source] if req.source and req.source != "derived" else None
    REFRESH.clear()
    REFRESH.update(state="running", source=req.source or "todas", cleared=cleared, total=len(fields),
                   done=0, errors={}, started=time.strftime("%H:%M:%S"))

    def job():
        try:
            for f in fields:
                rows = run_field(f, sources)
                n_err = sum(r["status"] == "error" for r in rows)
                if n_err:
                    REFRESH["errors"][f.field_id] = n_err
                REFRESH["done"] += 1
            REFRESH["state"] = "done"
        except Exception as exc:  # noqa: BLE001
            REFRESH.update(state="failed", error=repr(exc))
        finally:
            REFRESH["finished"] = time.strftime("%H:%M:%S")
            _refresh_lock.release()

    threading.Thread(target=job, daemon=True).start()
    return dict(REFRESH)


@app.get("/refresh")
def refresh_status() -> dict:
    return dict(REFRESH)
