# Exploración

Las pruebas que hicimos antes de construir la API, en el orden en que se hicieron. No forman parte del
producto, pero de aquí salieron las decisiones de diseño y los hechos de [`docs/fuentes.md`](../docs/fuentes.md).

## 1. SoilGrids por parcela — `soilgrids/Prueba-SoilGrids.ipynb`

Notebook (Google Colab) que empieza consultando la API REST de SoilGrids en un punto y pasa a leer el ráster
VRT de ISRIC recortado a cada parcela: arcilla, arena, limo, pH y carbono orgánico, media 0–30 cm ponderada
por espesor y una primera estimación de nFK.

**Aprendido**: la REST tarda ~35 s por llamada y tiene límite de uso; el ráster es la vía viable para
campos enteros.

## 2. LBEG BK50 — `lbeg-bk50/`

Pruebas manuales del WMS de NIBIS (LBEG) con GetFeatureInfo:

- `test_bk50_getfeatureinfo.py`: tres consultas sobre el mismo punto (L816 BK50 Karte, L839 nFKWe,
  L837 Ertragsfähigkeit) con BBOX de 100 × 100 m en EPSG:25832. Respuestas en `bk50_responses/`.
- `run_l2186_getfeatureinfo.py`: consulta de una capa "Methode BK50" (L2186).
- `ogc.xml`: GetCapabilities del servicio (175 capas).
- `Bodenzahl - Bodenschätzung.json`: respuesta de ejemplo de la capa de la Bodenschätzung (L849).

**Aprendido**: la BK50 en este WMS no trae textura, pH ni carbono orgánico; las capas "Methode" solo
devuelven el ámbito del método, no valores; la Bodenschätzung sí da Bodenzahl y Klassenzeichen.

## 3. Evidencia sistemática — `evidencia/`

Scripts que consultan todas las fuentes en los mismos cuatro puntos y guardan las respuestas en bruto
(`samples/`), más una segunda ronda de comprobaciones dirigidas al diseño del backend (`samples2/`).
Detalle en [`evidencia/README.md`](evidencia/README.md).

**Aprendido**:

- La granja cruza la frontera: LBEG solo cubre los 40 campos de Niedersachsen; para los 47 de
  Sachsen-Anhalt hacía falta BÜK200.
- LBEG devuelve errores `503.2` dentro de respuestas HTTP 200 y tiene cuelgues largos → caché en disco,
  validación del cuerpo y reintentos.
- Una sola llamada GetFeatureInfo puede pedir varias capas, y cada polígono devuelto cubre muchos puntos de la
  rejilla ("cosecha"), lo que reduce las llamadas a una fracción.
- BÜK200 no devuelve geometría: valor por unidad de leyenda, con perfiles FISBo para obtener las clases KA5.
- `wv0033`/`wv1500` de SoilGrids no existen como VRT: solo por WCS.

Con todo esto se diseñaron los adaptadores de `app/sources/` y las tablas de `lookups/`.

Las rutas de los scripts son relativas a su propia carpeta o a la raíz del repositorio; se ejecutan desde la
raíz con las dependencias de `requirements.txt`.
