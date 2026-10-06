"""
Utilidades compartidas por todos los scripts de evidencia.

- Rutas del proyecto (GeoJSON de entrada, carpeta samples/).
- Sesión HTTP con reintentos y User-Agent.
- fetch(): hace la petición, mide tiempo y deja traza en samples/_llamadas.csv.
- Guardado de respuestas "en bruto" (solo se recortan geometrías largas).
- Puntos estándar P1..P4 (los genera paso0_puntos.py en samples/puntos.json).
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# La consola de Windows usa cp1252 por defecto: forzamos UTF-8 (umlauts, emojis).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
GEOJSON = ROOT / "reto" / "LuF-Seggerde-Dev-fields.geojson"
SAMPLES = Path(__file__).resolve().parent / "samples"
RAW = SAMPLES / "_raw"  # ficheros grandes / auxiliares (capabilities XML, HTML de perfiles, GeoTIFF)
CALL_LOG = SAMPLES / "_llamadas.csv"
POINTS_FILE = SAMPLES / "puntos.json"

USER_AGENT = "tunen-hackathon-soil-evidence/1.0 (research; hackathon)"

# Punto de control del propio brief (cerca de Hannover): LBEG debe responder.
P1_CONTROL = {"lon": 9.715, "lat": 52.315}

# Puntos extra de control dentro de Niedersachsen, sobre tierra agrícola,
# usados solo si un punto estándar no devuelve nada en una capa LBEG.
EXTRA_CONTROL = {
    "X1": {"lon": 10.008, "lat": 52.392, "label": "Lehrte (notebook oficial del reto)"},
    "X2": {"lon": 10.95, "lat": 52.22, "label": "Helmstedt (ya probado por el equipo)"},
}


def ensure_dirs(*dirs: Path) -> None:
    for d in (SAMPLES, RAW, *dirs):
        d.mkdir(parents=True, exist_ok=True)


def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=3,  # 3 s, 6 s, 12 s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        respect_retry_after_header=True,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": USER_AGENT})
    return s


SESSION = make_session()


def prepared_url(url: str, params: dict | None = None) -> str:
    req = requests.Request("GET", url, params=params)
    return SESSION.prepare_request(req).url or url


# Cortacircuitos por host: tras N errores de conexión seguidos, las siguientes
# llamadas a ese host fallan al instante (status None, error "circuit_open").
CIRCUIT_THRESHOLD = 3
_host_failures: dict[str, int] = {}


def host_is_down(url: str) -> bool:
    return _host_failures.get(urlparse(url).netloc, 0) >= CIRCUIT_THRESHOLD


def fetch(source: str, label: str, url: str, params: dict | None = None,
          timeout: float = 90) -> dict:
    """GET con medición de tiempo. Nunca lanza: devuelve un dict con el resultado."""
    full_url = prepared_url(url, params)
    host = urlparse(url).netloc
    t0 = time.time()
    rec = {
        "source": source,
        "label": label,
        "url": full_url,
        "status": None,
        "content_type": "",
        "seconds": None,
        "bytes": 0,
        "error": "",
        "text": "",
        "content": b"",
    }
    if host_is_down(url):
        rec["error"] = f"circuit_open: {host} falló {CIRCUIT_THRESHOLD} veces seguidas, se omite la llamada"
        rec["seconds"] = 0.0
        _log_call(rec)
        print(f"  [{source}] {label}: OMITIDA ({host} caído)")
        return rec
    try:
        r = SESSION.get(url, params=params, timeout=(15, timeout))
        rec.update(
            status=r.status_code,
            content_type=r.headers.get("Content-Type", ""),
            bytes=len(r.content),
            content=r.content,
        )
        # Algunas respuestas de NIBIS no declaran charset; probamos UTF-8 primero.
        try:
            rec["text"] = r.content.decode("utf-8")
        except UnicodeDecodeError:
            rec["text"] = r.content.decode(r.encoding or "latin-1", errors="replace")
        _host_failures[host] = 0
    except requests.RequestException as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
        _host_failures[host] = _host_failures.get(host, 0) + 1
    rec["seconds"] = round(time.time() - t0, 2)
    _log_call(rec)
    status = rec["status"] if rec["status"] is not None else "ERR"
    print(f"  [{source}] {label}: HTTP {status} | {rec['seconds']} s | "
          f"{rec['bytes'] / 1024:.1f} KB {('| ' + rec['error']) if rec['error'] else ''}")
    return rec


def _log_call(rec: dict) -> None:
    ensure_dirs()
    new = not CALL_LOG.exists()
    with CALL_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "source", "label", "status", "content_type",
                        "seconds", "bytes", "error", "url"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), rec["source"],
                    rec["label"], rec["status"], rec["content_type"], rec["seconds"],
                    rec["bytes"], rec["error"], rec["url"]])


def as_json(rec: dict):
    """Intenta parsear el cuerpo como JSON. Devuelve None si no lo es."""
    try:
        return json.loads(rec["text"])
    except (ValueError, TypeError):
        return None


def strip_geometries(obj, _key: str | None = None):
    """Sustituye geometrías largas (GeoJSON o Esri) por un resumen. Lo demás, intacto."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "geometry" and isinstance(v, dict):
                out[k] = _geom_summary(v)
            elif k in ("rings", "paths", "coordinates") and isinstance(v, list):
                out[k] = f"<recortado: {_count_coords(v)} coordenadas>"
            else:
                out[k] = strip_geometries(v, k)
        return out
    if isinstance(obj, list):
        return [strip_geometries(v) for v in obj]
    return obj


def _geom_summary(g: dict) -> dict:
    coords = g.get("coordinates", g.get("rings", g.get("paths")))
    return {
        "type": g.get("type", "esri"),
        "_recortado": f"{_count_coords(coords) if coords is not None else 0} coordenadas",
    }


def _count_coords(v) -> int:
    if isinstance(v, list) and v and isinstance(v[0], (int, float)):
        return 1
    if isinstance(v, list):
        return sum(_count_coords(x) for x in v)
    return 0


def body_for_dump(rec: dict) -> str:
    """Cuerpo listo para guardar: JSON bonito y sin geometrías, o el texto tal cual."""
    data = as_json(rec)
    if data is not None:
        return json.dumps(strip_geometries(data), indent=2, ensure_ascii=False)
    return rec["text"]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def format_record_block(title: str, rec: dict, extra: dict | None = None) -> str:
    """Bloque de texto legible con la URL exacta, formato, tiempo y respuesta en bruto."""
    lines = [
        "=" * 100,
        title,
        "=" * 100,
        f"URL:           {rec['url']}",
        f"HTTP:          {rec['status']}",
        f"Content-Type:  {rec['content_type']}",
        f"Tiempo:        {rec['seconds']} s",
        f"Tamaño:        {rec['bytes'] / 1024:.1f} KB (antes de recortar geometrías)",
    ]
    for k, v in (extra or {}).items():
        lines.append(f"{k + ':':<15}{v}")
    if rec["error"]:
        lines.append(f"ERROR:         {rec['error']}")
    lines += ["--- respuesta en bruto (solo geometrías recortadas) ---", body_for_dump(rec), ""]
    return "\n".join(lines)


def load_points(include_extra: bool = False) -> dict[str, dict]:
    if not POINTS_FILE.exists():
        sys.exit("Falta samples/puntos.json: ejecuta antes paso0_puntos.py")
    pts = {p["id"]: p for p in json.loads(POINTS_FILE.read_text(encoding="utf-8"))["points"]}
    if include_extra:
        for pid, p in EXTRA_CONTROL.items():
            pts[pid] = {"id": pid, **p}
    return pts


def to_25832(lon: float, lat: float) -> tuple[float, float]:
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    return tr.transform(lon, lat)


def write_evidence(path: Path, text: str, had_errors: bool) -> Path:
    """Guarda evidencia sin machacar una versión buena anterior con una ejecución fallida.

    Si hubo errores de red/servidor y ya existe el fichero, se escribe en <nombre>_FALLO.txt.
    """
    if had_errors and path.exists():
        path = path.with_name(f"{path.stem}_FALLO{path.suffix}")
        print(f"  ! errores en esta ejecución: se conserva la evidencia anterior, fallo en {path.name}")
    else:
        path.with_name(f"{path.stem}_FALLO{path.suffix}").unlink(missing_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
