"""
test_bk50_getfeatureinfo.py

Prueba manual del servicio WMS BK50 de LBEG.

Hace 3 consultas GetFeatureInfo sobre el mismo punto:

1. L816 -> BK50 - Karte
2. L839 -> nFKWe / agua disponible en zona radicular
3. L837 -> Ertragsfähigkeit / capacidad productiva

Además:
- convierte lat/lon a EPSG:25832
- construye un BBOX de 100 x 100 metros
- muestra la URL real enviada
- muestra status code y Content-Type
- imprime la respuesta recibida
- guarda cada respuesta por separado
- crea un JSON final con todo
"""

from pathlib import Path
import json

import requests
from pyproj import Transformer


# ============================================================
# 1. CONFIGURACIÓN
# ============================================================

# Servicio WMS del LBEG / NIBIS
BASE_URL = "https://nibis.lbeg.de/net3/public/ogc.ashx"

# PKGID obtenido del GetCapabilities
PKG_ID = 24

# Punto de prueba cerca de Helmstedt
LATITUDE = 52.22
LONGITUDE = 10.95

# Radio del BBOX alrededor del punto, en metros.
# 50 m a cada lado -> caja total de 100 x 100 m.
BBOX_RADIUS_METERS = 50

# Tamaño del "mapa imaginario" usado por GetFeatureInfo.
WIDTH = 101
HEIGHT = 101

# Consultamos exactamente el píxel central.
PIXEL_I = 50
PIXEL_J = 50

# Formato que queremos recibir.
INFO_FORMAT = "application/geo+json"

# Las tres capas que queremos estudiar.
LAYERS = {
    "bk50": {
        "id": "L816",
        "description": "BK50 - Karte",
        "purpose": "Información general de la unidad de suelo"
    },
    "nfkwe": {
        "id": "L839",
        "description": "Nutzbare Feldkapazität des effektiven Wurzelraumes",
        "purpose": "Agua disponible para las plantas en la zona efectiva de raíces"
    },
    "ertragsfaehigkeit": {
        "id": "L837",
        "description": "Ertragsfähigkeit",
        "purpose": "Capacidad productiva natural del suelo"
    },
    "l2186": {
        "id": "L2186",
        "description": "L2186",
        "purpose": "Consulta solicitada con LAYERS y QUERY_LAYERS en L2186"
    }
}


# Carpeta donde guardaremos las respuestas.
OUTPUT_DIR = Path(__file__).resolve().parent / "bk50_responses"
OUTPUT_DIR.mkdir(exist_ok=True)


# ============================================================
# 2. CONVERSIÓN DE COORDENADAS
# ============================================================

def convert_coordinates(lat: float, lon: float):
    """
    Convierte coordenadas GPS EPSG:4326:

        latitud / longitud

    a EPSG:25832:

        X / Y en metros.

    always_xy=True obliga a introducir:
        longitud primero
        latitud después
    """

    transformer = Transformer.from_crs(
        "EPSG:4326",
        "EPSG:25832",
        always_xy=True
    )

    x, y = transformer.transform(lon, lat)

    return x, y


# ============================================================
# 3. CREAR EL BBOX
# ============================================================

def create_bbox(x: float, y: float, radius: float):
    """
    Construye una caja alrededor del punto.

    Si radius = 50:

           y+50
             |
        +---------+
        |         |
 x-50 --|    X    |-- x+50
        |         |
        +---------+
             |
           y-50

    Devuelve:

        xmin, ymin, xmax, ymax
    """

    xmin = x - radius
    ymin = y - radius
    xmax = x + radius
    ymax = y + radius

    return xmin, ymin, xmax, ymax


# ============================================================
# 4. HACER UNA CONSULTA GETFEATUREINFO
# ============================================================

def get_feature_info(layer_id: str, x: float, y: float):
    """
    Hace una petición GetFeatureInfo a una capa determinada.

    layer_id puede ser:

        L816
        L839
        L837
    """

    xmin, ymin, xmax, ymax = create_bbox(
        x,
        y,
        BBOX_RADIUS_METERS
    )

    bbox = f"{xmin},{ymin},{xmax},{ymax}"

    params = {
        "PKGID": PKG_ID,

        # WMS
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",

        # Capa que forma parte del mapa
        "LAYERS": layer_id,

        # Capa sobre la que queremos información
        "QUERY_LAYERS": layer_id,

        # Estilo por defecto
        "STYLES": "",

        # Sistema de coordenadas
        "CRS": "EPSG:25832",

        # Zona del mapa
        "BBOX": bbox,

        # Tamaño del mapa imaginario
        "WIDTH": WIDTH,
        "HEIGHT": HEIGHT,

        # Píxel sobre el que "hacemos clic"
        "I": PIXEL_I,
        "J": PIXEL_J,

        # Formato de respuesta
        "INFO_FORMAT": INFO_FORMAT,

        # Solo queremos un elemento
        "FEATURE_COUNT": 1
    }

    response = requests.get(
        BASE_URL,
        params=params,
        timeout=30
    )

    return response, params


# ============================================================
# 5. INTERPRETAR LA RESPUESTA
# ============================================================

def parse_response(response):
    """
    Intenta interpretar la respuesta como JSON.

    Si el servidor por algún motivo devuelve HTML/XML/texto,
    no rompe el programa: guarda el contenido como texto.
    """

    content_type = response.headers.get("Content-Type", "")

    try:
        data = response.json()

        return {
            "format": "json",
            "content_type": content_type,
            "data": data
        }

    except ValueError:

        return {
            "format": "text",
            "content_type": content_type,
            "data": response.text
        }


# ============================================================
# 6. MOSTRAR LA RESPUESTA DE FORMA ENTENDIBLE
# ============================================================

def print_response(name, layer_config, response, parsed):
    """
    Imprime información útil para entender exactamente
    cómo responde la API.
    """

    print("\n")
    print("=" * 80)
    print(f"CONSULTA: {name}")
    print("=" * 80)

    print(f"Capa técnica: {layer_config['id']}")
    print(f"Descripción: {layer_config['description']}")
    print(f"Objetivo: {layer_config['purpose']}")

    print("\n--- HTTP ---")

    print("Status code:")
    print(response.status_code)

    print("\nContent-Type:")
    print(parsed["content_type"])

    print("\nURL REAL ENVIADA:")
    print(response.url)

    print("\n--- RESPUESTA ---")

    if parsed["format"] == "json":

        print(
            json.dumps(
                parsed["data"],
                indent=4,
                ensure_ascii=False
            )
        )

    else:

        print(parsed["data"])

    print("=" * 80)


# ============================================================
# 7. GUARDAR CADA RESPUESTA
# ============================================================

def save_response(name, result):
    """
    Guarda la respuesta completa de cada capa.

    Ejemplo:

        bk50_responses/bk50.json
        bk50_responses/nfkwe.json
        bk50_responses/ertragsfaehigkeit.json
    """

    file_path = OUTPUT_DIR / f"{name}.json"

    with open(
        file_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=4,
            ensure_ascii=False
        )

    print(f"\nGuardado en: {file_path}")


# ============================================================
# 8. PROGRAMA PRINCIPAL
# ============================================================

def main():

    print("=" * 80)
    print("LBEG BK50 - TEST GETFEATUREINFO")
    print("=" * 80)

    print("\nCoordenadas originales:")

    print(f"Latitud:  {LATITUDE}")
    print(f"Longitud: {LONGITUDE}")

    # --------------------------------------------------------
    # Convertimos coordenadas
    # --------------------------------------------------------

    x, y = convert_coordinates(
        LATITUDE,
        LONGITUDE
    )

    print("\nCoordenadas transformadas a EPSG:25832:")

    print(f"X: {x:.3f}")
    print(f"Y: {y:.3f}")

    # --------------------------------------------------------
    # Estructura donde guardaremos todas las respuestas
    # --------------------------------------------------------

    complete_result = {

        "input": {

            "latitude": LATITUDE,
            "longitude": LONGITUDE,

            "source_crs": "EPSG:4326",

            "query_crs": "EPSG:25832",

            "x": x,
            "y": y,

            "bbox_radius_meters": BBOX_RADIUS_METERS
        },

        "wms": {

            "base_url": BASE_URL,
            "pkg_id": PKG_ID,
            "version": "1.3.0",
            "request": "GetFeatureInfo",
            "info_format": INFO_FORMAT
        },

        "queries": {}
    }

    # --------------------------------------------------------
    # Ejecutamos las tres consultas
    # --------------------------------------------------------

    for name, layer_config in LAYERS.items():

        layer_id = layer_config["id"]

        response, params = get_feature_info(
            layer_id,
            x,
            y
        )

        parsed = parse_response(response)

        # Mostramos todo por consola.
        print_response(
            name,
            layer_config,
            response,
            parsed
        )

        # Creamos una estructura completa para estudiar la API.
        result = {

            "layer": {
                "id": layer_id,
                "description": layer_config["description"],
                "purpose": layer_config["purpose"]
            },

            "request": {
                "url": response.url,
                "params": params
            },

            "response": {
                "status_code": response.status_code,
                "content_type": parsed["content_type"],
                "detected_format": parsed["format"],
                "body": parsed["data"]
            }
        }

        # Guardamos respuesta individual.
        save_response(
            name,
            result
        )

        # Añadimos al resultado global.
        complete_result["queries"][name] = result

    # --------------------------------------------------------
    # Guardamos las tres juntas
    # --------------------------------------------------------

    complete_file = OUTPUT_DIR / "all_responses.json"

    with open(
        complete_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            complete_result,
            file,
            indent=4,
            ensure_ascii=False
        )

    print("\n")
    print("=" * 80)
    print("FINALIZADO")
    print("=" * 80)

    print("\nJSON conjunto:")
    print(complete_file)


if __name__ == "__main__":
    main()
