"""
Consulta unica GetFeatureInfo para la capa L2186 del WMS NIBIS/LBEG.

Uso:
    python run_l2186_getfeatureinfo.py

Opcional por variables de entorno:
    set LBEG_LAT=52.22
    set LBEG_LON=10.95
    set LBEG_TIMEOUT=120
    set LBEG_INFO_FORMAT=application/geo+json
"""

from __future__ import annotations

from pathlib import Path
import json
import os
import time

import requests
from pyproj import Transformer


BASE_URL = "https://nibis.lbeg.de/net3/public/ogc.ashx"
PKG_ID = 24
LAYER_ID = "L2186"

LATITUDE = float(os.getenv("LBEG_LAT", "52.22"))
LONGITUDE = float(os.getenv("LBEG_LON", "10.95"))
BBOX_RADIUS_METERS = 50

WIDTH = 101
HEIGHT = 101
PIXEL_I = 50
PIXEL_J = 50

INFO_FORMAT = os.getenv("LBEG_INFO_FORMAT", "application/geo+json")
CONNECT_TIMEOUT = 10
READ_TIMEOUT = int(os.getenv("LBEG_TIMEOUT", "120"))
MAX_ATTEMPTS = 4

OUTPUT_DIR = Path(__file__).resolve().parent / "bk50_responses"
OUTPUT_DIR.mkdir(exist_ok=True)


def convert_coordinates(lat: float, lon: float) -> tuple[float, float]:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    return transformer.transform(lon, lat)


def create_bbox(x: float, y: float, radius: float) -> str:
    xmin = x - radius
    ymin = y - radius
    xmax = x + radius
    ymax = y + radius
    return f"{xmin},{ymin},{xmax},{ymax}"


def build_params() -> dict[str, object]:
    x, y = convert_coordinates(LATITUDE, LONGITUDE)

    return {
        "PKGID": PKG_ID,
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": LAYER_ID,
        "QUERY_LAYERS": LAYER_ID,
        "STYLES": "",
        "CRS": "EPSG:25832",
        "BBOX": create_bbox(x, y, BBOX_RADIUS_METERS),
        "WIDTH": WIDTH,
        "HEIGHT": HEIGHT,
        "I": PIXEL_I,
        "J": PIXEL_J,
        "INFO_FORMAT": INFO_FORMAT,
        "FEATURE_COUNT": 1,
    }


def prepared_url(session: requests.Session, params: dict[str, object]) -> str:
    request = requests.Request("GET", BASE_URL, params=params)
    return session.prepare_request(request).url or BASE_URL


def request_with_retries(
    session: requests.Session,
    params: dict[str, object],
) -> requests.Response:
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\nIntento {attempt}/{MAX_ATTEMPTS}...")

        try:
            response = session.get(
                BASE_URL,
                params=params,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )

            if response.status_code in {429, 500, 502, 503, 504}:
                print(f"Servidor respondio HTTP {response.status_code}.")
                if attempt < MAX_ATTEMPTS:
                    wait_seconds = 5 * attempt
                    print(f"Reintentando en {wait_seconds} s...")
                    time.sleep(wait_seconds)
                    continue

            return response

        except requests.exceptions.ReadTimeout as exc:
            last_error = exc
            print(f"Timeout leyendo respuesta tras {READ_TIMEOUT} s.")

        except requests.exceptions.ConnectTimeout as exc:
            last_error = exc
            print(f"Timeout conectando tras {CONNECT_TIMEOUT} s.")

        except requests.exceptions.RequestException as exc:
            last_error = exc
            print(f"Error de red: {exc}")

        if attempt < MAX_ATTEMPTS:
            wait_seconds = 5 * attempt
            print(f"Reintentando en {wait_seconds} s...")
            time.sleep(wait_seconds)

    raise RuntimeError(f"No se pudo obtener respuesta de LBEG/NIBIS: {last_error}")


def save_response(response: requests.Response, params: dict[str, object]) -> None:
    content_type = response.headers.get("Content-Type", "")
    metadata_file = OUTPUT_DIR / "l2186_metadata.json"

    try:
        parsed_body = response.json()
        body_format = "json"
        body_file = OUTPUT_DIR / "l2186_response.geojson"
        body_file.write_text(
            json.dumps(parsed_body, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except ValueError:
        parsed_body = response.text[:2000]
        body_format = "text"
        body_file = OUTPUT_DIR / "l2186_response.txt"
        body_file.write_text(response.text, encoding="utf-8", errors="replace")

    metadata = {
        "layer": LAYER_ID,
        "coordinates": {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "crs": "EPSG:4326",
        },
        "request": {
            "url": response.url,
            "params": params,
            "timeout": {
                "connect_seconds": CONNECT_TIMEOUT,
                "read_seconds": READ_TIMEOUT,
            },
        },
        "response": {
            "status_code": response.status_code,
            "content_type": content_type,
            "detected_format": body_format,
            "headers": dict(response.headers),
            "body_preview": parsed_body,
            "saved_body_file": str(body_file),
        },
    }

    metadata_file.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\nRespuesta guardada en: {body_file}")
    print(f"Metadata guardada en: {metadata_file}")


def print_diagnosis(response: requests.Response) -> None:
    print("\n" + "=" * 80)
    print("DIAGNOSTICO")
    print("=" * 80)
    print(f"HTTP status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type', '')}")

    if response.status_code == 200:
        print("OK: el servidor respondio.")
    elif response.status_code == 403:
        print("Posible bloqueo/capado: HTTP 403 Forbidden.")
    elif response.status_code == 429:
        print("Posible rate limit/capado: HTTP 429 Too Many Requests.")
    elif response.status_code >= 500:
        print("Problema del servidor LBEG/NIBIS o consulta demasiado pesada.")
    else:
        print("Respuesta no esperada. Revisa el archivo de metadata.")

    preview = response.text[:700].replace("\n", " ")
    if preview:
        print("\nPreview:")
        print(preview)


def main() -> None:
    params = build_params()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 LBEG-BK50-test/1.0 "
                "(manual GetFeatureInfo check)"
            ),
            "Accept": "application/geo+json, application/json, text/plain, */*",
        }
    )

    print("=" * 80)
    print("LBEG/NIBIS GetFeatureInfo - L2186")
    print("=" * 80)
    print(f"Lat/Lon: {LATITUDE}, {LONGITUDE}")
    print(f"INFO_FORMAT: {INFO_FORMAT}")
    print(f"Read timeout: {READ_TIMEOUT} s")
    print("\nURL que se enviara:")
    print(prepared_url(session, params))

    response = request_with_retries(session, params)
    print_diagnosis(response)
    save_response(response, params)


if __name__ == "__main__":
    main()
