"""
PASO 2 - LBEG BK50 (WMS NIBIS, PkgId=24)

a) capas.txt: todas las capas (nombre | título | queryable), formatos de
   GetFeatureInfo y CRS soportados, leídos del GetCapabilities en vivo.
b) Respuestas reales de las capas relevantes en P1, P2, P3, P4 (+X1/X2 si un
   punto NDS no devuelve nada): URL exacta, respuesta en bruto, formato, tiempo.
   formatos_P1.txt compara INFO_FORMAT (geo+json, text/plain, text/html).
c) enlaces_doc.txt: abstracts, MetadataURL, DataURL, LegendURL de las capas
   clave, sacados del propio GetCapabilities (nada inventado).
d) descubrimiento_P1.csv / P2: qué atributos devuelve CADA capa consultable en
   un punto con datos. Sirve para encontrar pH, Corg, humus, Bodenart... en las
   capas "Methode BK50*" sin adivinar. Desactivar con LBEG_DISCOVER=0.

Salida: samples/lbeg_bk50/
"""

from __future__ import annotations

import csv
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from common import RAW, ROOT, SAMPLES, ensure_dirs, fetch, format_record_block, load_points, write_evidence
from lbeg import NIBIS_URL, PKG_ID, feature_properties, get_feature_info

OUT = SAMPLES / "lbeg_bk50"
DISCOVER = os.getenv("LBEG_DISCOVER", "1") == "1"
DISCOVER_WORKERS = int(os.getenv("LBEG_WORKERS", "2"))
DISCOVER_DELAY = float(os.getenv("LBEG_DELAY", "0.3"))  # s entre llamadas por hilo (ser amables)

# Capas candidatas para los 5 parámetros (por título en GetCapabilities).
KEY_LAYERS = {
    "L816": "BK50 - Karte (unidad de suelo: BOTYP, GEOTYP, NUTZUNG...)",
    "L839": "Nutzbare Feldkapazität des effektiven Wurzelraumes (nFKWe)",
    "L821": "Pflanzenverfügbares Bodenwasser (1991-2020)",
    "L837": "Ertragsfähigkeit (proxy de Bodenzahl)",
    "L823": "Effektive Durchwurzelungstiefe (para pasar nFKWe a mm/dm)",
    "L838": "Grundwasserstufe",
    "L846": "Kohlenstoffreiche Böden (BHK50)",
    "L2153": "Methode BK50PH (¿pH?)",
    "L2092": "Methode BK50CORG (¿carbono orgánico?)",
    "L2091": "Methode BK50CORGH (¿Corg horizonte?)",
    "L2122": "Methode BK50HUMG (¿humusgehalt?)",
    "L2124": "Methode BK50KA (¿Bodenart / Körnung?)",
    "L2088": "Methode BK50BOKLA (¿Bodenklasse?)",
    "L2186": "Methode BK50FRAK (¿fracciones granulométricas?)",
    "L2085": "Methode BK50BFT",
    "L2084": "Methode BK50BFR (Ertragsfähigkeit método)",
    "L2149": "Methode BK50NFK1M (nFK 1 m)",
    "L2148": "Methode BK50NFKH (nFK por horizonte)",
    "L2105": "Methode BK50FKWE (FK zona raíces)",
    "L2194": "Methode BK50WE (profundidad efectiva raíces)",
}
FORMATS = ["application/geo+json", "text/plain", "text/html"]
FORMAT_LAYERS = ["L816", "L839", "L837"]


def main() -> None:
    ensure_dirs(OUT)
    pts = load_points(include_extra=True)

    # ---------- a) capabilities ----------
    print("a) GetCapabilities")
    rec = fetch("lbeg_bk50", "GetCapabilities", NIBIS_URL,
                {"PkgId": PKG_ID, "Service": "WMS", "Request": "GetCapabilities", "Version": "1.3.0"},
                timeout=120)
    content, origin = rec["content"], "en vivo"
    if rec["status"] != 200 or not content:
        # Servicio caído: usamos la copia que el equipo descargó antes (mismo endpoint).
        content = (ROOT / "exploracion" / "lbeg-bk50" / "ogc.xml").read_bytes()
        origin = f"COPIA LOCAL exploracion/lbeg-bk50/ogc.xml (en vivo falló: {rec['error'] or rec['status']})"
    (RAW / "lbeg_capabilities.xml").write_bytes(content)
    layers, formats, crs, docs = parse_capabilities(content)
    lines = [f"URL: {rec['url']}", f"Origen: {origin}",
             f"HTTP {rec['status']} | {rec['seconds']} s | {len(content) / 1024:.0f} KB", "",
             f"Formatos GetFeatureInfo: {formats}",
             f"CRS (capa raíz, primeros 15): {crs[:15]}",
             f"EPSG:25832 soportado: {'EPSG:25832' in crs}", "",
             f"{len(layers)} capas con nombre (nombre | título | queryable | grupo):"]
    lines += [f"{l['name']} | {l['title']} | {l['queryable']} | {l['group']}" for l in layers]
    (OUT / "capas.txt").write_text("\n".join(lines), encoding="utf-8")

    # ---------- c) documentación ----------
    doc_lines = ["Enlaces y textos de documentación extraídos del GetCapabilities (PkgId=24).",
                 "Solo capas clave + Bodenschätzung. Nada añadido a mano.", ""]
    for name in list(KEY_LAYERS) + ["L849"]:
        d = docs.get(name)
        if not d:
            continue
        doc_lines.append(f"### {name} | {d['title']}")
        for k in ("abstract", "keywords", "metadata", "dataurl", "legend", "attribution"):
            if d.get(k):
                doc_lines.append(f"  {k}: {d[k]}")
        doc_lines.append("")
    service = docs.get("_service", {})
    doc_lines.insert(2, f"Servicio: {service}")
    doc_lines += iso_metadata_links(docs, list(KEY_LAYERS)[:7] + ["L849"])
    (OUT / "enlaces_doc.txt").write_text("\n".join(doc_lines), encoding="utf-8")

    # ---------- b) respuestas reales ----------
    print("\nb) GetFeatureInfo en capas clave")
    for pid in ["P1", "P2", "P3", "P4"]:
        p = pts[pid]
        blocks = [f"Punto {pid}: lon={p['lon']} lat={p['lat']} | {p.get('label')} | Land: {p.get('land_nominatim')}",
                  "Método: BBOX de 100x100 m en EPSG:25832 centrado en el punto, WIDTH=HEIGHT=101, I=J=50, "
                  "WMS 1.3.0, FEATURE_COUNT=1", ""]
        summary = []
        errors = False
        for layer, desc in KEY_LAYERS.items():
            r = get_feature_info("lbeg_bk50", f"{pid} {layer}", layer, p["lon"], p["lat"])
            props = feature_properties(r)
            errors = errors or bool(r["error"])
            summary.append(f"  {layer:6} hit={str(r['hit']):5} t={r['seconds']:>6}s  {desc}  -> "
                           f"{props[0] if props else ('(sin objetos)' if r['status'] == 200 else r['error'])}")
            blocks.append(format_record_block(f"{pid} | {layer} | {desc}", r,
                                              {"INFO_FORMAT": r["info_format"], "Hit": r["hit"]}))
        header = [f"RESUMEN {pid} (atributos del primer objeto):"] + summary + [""]
        write_evidence(OUT / f"{pid}.txt", "\n".join(blocks[:3] + header + blocks[3:]), errors)

    # ---------- b2) comparación de formatos en P1 ----------
    print("\nb2) Comparación de INFO_FORMAT en P1")
    fblocks = ["Mismo punto (P1), mismas capas, distintos INFO_FORMAT.", ""]
    for layer in FORMAT_LAYERS:
        for fmt in FORMATS:
            r = get_feature_info("lbeg_bk50", f"P1 {layer} {fmt}", layer, pts["P1"]["lon"],
                                 pts["P1"]["lat"], info_format=fmt)
            fblocks.append(format_record_block(f"P1 | {layer} | {fmt}", r, {"INFO_FORMAT": fmt}))
    (OUT / "formatos_P1.txt").write_text("\n".join(fblocks), encoding="utf-8")

    # ---------- d) descubrimiento ----------
    if DISCOVER:
        queryable = [l for l in layers if l["queryable"] == "1"]
        for pid in ("P1", "P2"):
            print(f"\nd) Descubrimiento: {len(queryable)} capas consultables en {pid}")
            discover(pts[pid], pid, queryable)
    print(f"\nListo -> {OUT}")


def discover(p: dict, pid: str, layers: list[dict]) -> None:
    def one(l):
        time.sleep(DISCOVER_DELAY)
        # text/plain: sin geometría (las capas "Methode" devuelven ~1,3 MB en geo+json)
        r = get_feature_info("lbeg_discover", f"{pid} {l['name']}", l["name"], p["lon"], p["lat"],
                             info_format="text/plain", timeout=60)
        first = parse_plain(r["text"]) if r["hit"] else {}
        props = [first] if first else []
        return {
            "layer": l["name"], "title": l["title"], "group": l["group"], "http": r["status"],
            "seconds": r["seconds"], "kb": round(r["bytes"] / 1024, 1), "hit": r["hit"],
            "n_features": len(props), "attributes": "|".join(first.keys()),
            "values": "|".join(f"{k}={v}" for k, v in first.items())[:1500],
            "error": r["error"] or ("" if r["status"] == 200 else r["text"][:200]),
        }

    with ThreadPoolExecutor(max_workers=DISCOVER_WORKERS) as ex:
        rows = list(ex.map(one, layers))
    path = OUT / f"descubrimiento_{pid}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    hits = [r for r in rows if r["hit"]]
    print(f"  {len(hits)}/{len(rows)} capas devuelven objetos en {pid} -> {path.name}")


def parse_plain(text: str) -> dict:
    """Primer objeto de una respuesta text/plain de NIBIS ('CLAVE<TAB>:valor' por línea)."""
    out = {}
    for line in text.split("# 2")[0].splitlines():
        if "\t:" in line:
            k, v = line.split("\t:", 1)
            out[k.strip()] = v.strip()
    return out


def iso_metadata_links(docs: dict, layers: list[str]) -> list[str]:
    """Descarga la ficha ISO de cada capa y extrae URLs y textos de linaje/propósito."""
    out = ["", "#" * 90, "Fichas de metadatos ISO (MetadataURL) de las capas clave", "#" * 90]
    for name in layers:
        url = (docs.get(name) or {}).get("metadata", "").split(" ; ")[0]
        if not url:
            continue
        rec = fetch("lbeg_bk50", f"ISO metadata {name}", url, timeout=60)
        (RAW / f"lbeg_iso_{name}.xml").write_bytes(rec["content"])
        txt = rec["text"]
        urls = sorted({u.rstrip(".,)") for u in re.findall(r"https?://[^\s<\"']+", txt)
                       if "opengis.net" not in u and "isotc211" not in u and "w3.org" not in u})
        out.append(f"\n### {name} | {docs[name]['title']} | {url} (HTTP {rec['status']})")
        for tag in ("purpose", "statement", "supplementalInformation", "useLimitation", "otherConstraints"):
            for m in re.findall(rf"<gmd:{tag}>\s*<gco:CharacterString>(.*?)</gco:CharacterString>", txt, re.S):
                out.append(f"  {tag}: {re.sub(r'\s+', ' ', m)[:1200]}")
        for m in re.findall(r"<gmd:denominator>\s*<gco:Integer>(\d+)", txt):
            out.append(f"  escala (denominator): 1:{m}")
        for m in re.findall(r"<gmd:dateStamp>\s*<gco:Date(?:Time)?>([^<]+)", txt):
            out.append(f"  dateStamp: {m}")
        out += [f"  url: {u}" for u in urls]
    return out


def parse_capabilities(content: bytes):
    root = ET.fromstring(content)
    for el in root.iter():
        el.tag = el.tag.split("}")[-1]

    def text(el, tag):
        c = el.find(tag)
        return (c.text or "").strip() if c is not None and c.text else ""

    def href(el):
        for c in el.iter("OnlineResource"):
            for k, v in c.attrib.items():
                if k.endswith("href"):
                    return v
        return ""

    gfi = root.find(".//Request/GetFeatureInfo")
    formats = [f.text for f in gfi.findall("Format")] if gfi is not None else []
    top = root.find(".//Capability/Layer")
    crs = [c.text for c in top.findall("CRS")] if top is not None else []

    layers, docs = [], {}
    svc = root.find("Service")
    if svc is not None:
        docs["_service"] = {k: text(svc, k) for k in ("Title", "Abstract", "Fees", "AccessConstraints")}

    def walk(el, group):
        name, title = text(el, "Name"), text(el, "Title")
        if name:
            layers.append({"name": name, "title": title, "queryable": el.get("queryable", "0"),
                           "group": group})
            d = {"title": title, "abstract": re.sub(r"\s+", " ", text(el, "Abstract"))[:1500]}
            kw = el.find("KeywordList")
            if kw is not None:
                d["keywords"] = ", ".join(k.text or "" for k in kw.findall("Keyword"))
            d["metadata"] = " ; ".join(href(m) for m in el.findall("MetadataURL"))
            d["dataurl"] = " ; ".join(href(m) for m in el.findall("DataURL"))
            d["legend"] = " ; ".join(href(s.find("LegendURL")) for s in el.findall("Style")
                                     if s.find("LegendURL") is not None)
            att = el.find("Attribution")
            d["attribution"] = f"{text(att, 'Title')} {href(att)}".strip() if att is not None else ""
            docs[name] = d
        for c in el.findall("Layer"):
            walk(c, title if not name else group)

    if top is not None:
        walk(top, "")
    return layers, formats, crs, docs


if __name__ == "__main__":
    main()
