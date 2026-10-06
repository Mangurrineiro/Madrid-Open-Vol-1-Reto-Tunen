"""
PASO 4 - BGR BÜK200 (plan B nacional: la mitad de la granja está en Sachsen-Anhalt)

ArcGIS REST MapServer. La capa 0 es el índice de hojas ("Blattschnitt"); los
suelos están en una capa por hoja (CC#### NOMBRE). Por eso:

a) layers.json: la parte "layers" (+ "tables") del MapServer.
b) fields.json: campos de la capa 0 y de la(s) capa(s) de hoja que cubren los
   puntos (nombre, alias, tipo) + relaciones/tablas si las hay.
c) Consulta en P1..P4: primero la literal sobre /0/query (para ver qué
   devuelve el índice) y luego la capa de hoja con outFields=*.

Salida: samples/buek200/{layers.json, fields.json, P1..P4.json}
"""

from __future__ import annotations

import html
import re

from common import RAW, SAMPLES, as_json, ensure_dirs, fetch, load_points, strip_geometries, write_json

OUT = SAMPLES / "buek200"
BASE = "https://services.bgr.de/arcgis/rest/services/boden/buek200/MapServer"


def query(layer_id: int, lon: float, lat: float, label: str, fields: str = "*") -> dict:
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
              "returnGeometry": "false", "f": "json"}
    return fetch("buek200", label, f"{BASE}/{layer_id}/query", params, timeout=60)


def main() -> None:
    ensure_dirs(OUT)
    pts = load_points()

    rec = fetch("buek200", "MapServer?f=pjson", BASE, {"f": "pjson"}, timeout=60)
    meta = as_json(rec) or {}
    layers = meta.get("layers", [])
    write_json(OUT / "layers.json", {"_request": rec["url"], "_seconds": rec["seconds"],
                                     "mapName": meta.get("mapName"),
                                     "serviceDescription": meta.get("serviceDescription"),
                                     "spatialReference": meta.get("spatialReference"),
                                     "layers": layers, "tables": meta.get("tables")})

    layer_meta = {}

    def describe(layer_id: int) -> dict:
        if layer_id not in layer_meta:
            r = fetch("buek200", f"layer {layer_id} ?f=pjson", f"{BASE}/{layer_id}", {"f": "pjson"})
            d = as_json(r) or {}
            layer_meta[layer_id] = {
                "_request": r["url"], "id": d.get("id"), "name": d.get("name"), "type": d.get("type"),
                "description": d.get("description"), "geometryType": d.get("geometryType"),
                "minScale": d.get("minScale"), "maxScale": d.get("maxScale"),
                "fields": [{"name": f.get("name"), "alias": f.get("alias"), "type": f.get("type"),
                            "domain": f.get("domain")} for f in d.get("fields") or []],
                "relationships": d.get("relationships"),
                "drawingInfo_renderer_field": (d.get("drawingInfo") or {}).get("renderer", {}).get("field1"),
                "renderer_sample": strip_geometries(((d.get("drawingInfo") or {}).get("renderer") or {})
                                                    .get("uniqueValueInfos", [])[:15]),
            }
        return layer_meta[layer_id]

    describe(0)
    for pid in ["P1", "P2", "P3", "P4"]:
        p = pts[pid]
        idx = query(0, p["lon"], p["lat"], f"{pid} capa 0 (Blattschnitt)")
        idx_json = as_json(idx) or {}
        feats = idx_json.get("features", [])
        sheet = feats[0]["attributes"].get("BLATTNUM", "").replace(" ", "") if feats else None
        sheet_layer = next((l for l in layers if sheet and l["name"].upper().startswith(sheet.upper())), None)
        result = {"_punto": p,
                  "consulta_capa_0": {"url": idx["url"], "http": idx["status"], "seconds": idx["seconds"],
                                      "response": strip_geometries(idx_json) if idx_json else idx["text"][:3000]},
                  "hoja": sheet, "capa_hoja": sheet_layer}
        if sheet_layer:
            describe(sheet_layer["id"])
            s = query(sheet_layer["id"], p["lon"], p["lat"], f"{pid} capa {sheet_layer['id']} ({sheet_layer['name']})")
            s_json = as_json(s)
            result["consulta_capa_hoja"] = {"url": s["url"], "http": s["status"], "seconds": s["seconds"],
                                            "response": strip_geometries(s_json) if s_json else s["text"][:3000]}
        attrs = ((result.get("consulta_capa_hoja") or {}).get("response") or {})
        attrs = attrs.get("features", [{}])[0].get("attributes") if isinstance(attrs, dict) and attrs.get("features") else None
        print(f"  {pid}: hoja={sheet} capa={sheet_layer and sheet_layer['id']} -> {attrs}")

        # Ficha de perfiles FISBo enlazada en el atributo "Profile": horizontes con
        # Bodenart (KA5), humus, acidez... por perfil y con su % de superficie.
        if attrs and attrs.get("Profile"):
            url = html.unescape(attrs["Profile"])
            pr = fetch("buek200", f"{pid} perfil FISBo", url, timeout=60)
            (RAW / f"buek200_perfil_{pid}.html").write_bytes(pr["content"])
            result["perfil_fisbo"] = {"url": pr["url"], "http": pr["status"], "seconds": pr["seconds"],
                                      "aviso_fuente": _disclaimer(pr["text"]),
                                      "perfiles": parse_profiles(pr["text"])}
        write_json(OUT / f"{pid}.json", result)

    write_json(OUT / "fields.json", layer_meta)
    print(f"\nListo -> {OUT}")


HORIZON_COLS = ["nr", "symbol", "ober_dm", "unter_dm", "stratigraphie", "herkunft", "geogenese",
                "grobboden_fraktion", "grobboden_summe", "bodenart_ka5", "humus_ka5", "carbonat_ka5",
                "gefuege", "rohdichte_lagerungsdichte", "torfart", "zersetzungsstufe",
                "substanzvolumen", "bodenaciditaet_ka5"]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xad", "")).strip()


def _disclaimer(text: str) -> str:
    m = re.search(r"Die Daten zu den Bodenprofilen.*?Kennzeichnung\.", _clean(text))
    return m.group(0) if m else ""


def parse_profiles(text: str) -> list[dict]:
    """Convierte la página FISBo en perfiles -> horizontes (columnas según la cabecera KA5)."""
    profiles = []
    for chunk in text.split('<table class="profil"')[1:]:
        head = chunk.split("</th></tr>", 1)[0]
        divs = [_clean(d) for d in re.findall(r"<div[^>]*>(.*?)</div>", head, re.S)]
        prof = {"cabecera": divs, "horizontes": []}
        for d in divs:
            if ":" in d:
                k, v = d.split(":", 1)
                prof[k.strip()] = v.strip()
        for row in re.split(r"onmouseover=", chunk)[1:]:
            cells = re.findall(r"<td>([^<]*)</td>", row)
            if len(cells) >= len(HORIZON_COLS):
                prof["horizontes"].append(dict(zip(HORIZON_COLS, [c.strip() for c in cells])))
        profiles.append(prof)
    return profiles


if __name__ == "__main__":
    main()
