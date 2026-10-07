# Evidencia de las fuentes de suelo

Scripts que consultan cada fuente real **en los mismos puntos** (P1–P4) y guardan las respuestas en bruto.
De aquí salieron la matriz de cobertura, las tablas de `lookups/` y los hechos de
[`docs/fuentes.md`](../../docs/fuentes.md).

## Cómo ejecutarlo

Desde la raíz del repositorio, con las dependencias de `requirements.txt`:

```powershell
# todo (6-10 min; SoilGrids espera 60 s entre llamadas por su límite de uso)
.venv\Scripts\python exploracion\evidencia\run_all.py

# solo algunos pasos (el 0 tiene que haberse ejecutado antes)
.venv\Scripts\python exploracion\evidencia\run_all.py 2 3

# segunda ronda de comprobaciones (salida en samples2/)
.venv\Scripts\python exploracion\evidencia\comprobaciones2.py
```

Resultado en `samples/` (ronda 1) y `samples2/` (ronda 2). `samples/_raw/` guarda lo pesado (capabilities XML,
HTML de perfiles, GeoTIFF).

> [!NOTE]
> Los scripts leen el GeoJSON de la granja del reto (`reto/`), que no se publica, y tampoco se publican
> `samples/` ni `samples2/`, porque contienen polígonos, puntos y respuestas de esos campos. Los hallazgos
> están resumidos en [`docs/fuentes.md`](../../docs/fuentes.md).

## Ronda 1: qué hace cada paso

| Paso | Script | Produce | Responde a |
|---|---|---|---|
| 0 | `paso0_puntos.py` | `puntos.txt`, `puntos.json`, `campos.csv` | Campos de la granja, bbox, cobertura LBEG campo a campo, Land real (Nominatim) y los 4 puntos P1–P4 |
| 1 | `paso1_soilgrids.py` | `soilgrids/layers.json`, `P1.json`, `P3.json`, `raster_info.txt` | Unidades/d_factor, consulta completa (8 props × 3 prof. × 5 estadísticos), vía raster VRT + WCS (agua 33/1500 kPa) y comparación píxel vs REST |
| 2 | `paso2_lbeg_bk50.py` | `lbeg_bk50/capas.txt`, `P1..P4.txt`, `formatos_P1.txt`, `enlaces_doc.txt`, `descubrimiento_P1/P2.csv` | Capas del WMS, respuestas en bruto con URL y tiempo, comparación de INFO_FORMAT, enlaces de documentación (abstracts + fichas ISO), y barrido de TODAS las capas consultables para ver qué atributos devuelve cada una |
| 3 | `paso3_bodenschaetzung.py` | `bodenschaetzung/P1..P4.txt`, `resumen.txt` | Capa L849: Klassenzeichen real, BODENZ/ACKERZ como campos separados, comportamiento fuera de cobertura |
| 4 | `paso4_buek200.py` | `buek200/layers.json`, `fields.json`, `P1..P4.json` | Índice de hojas (capa 0) → capa de la hoja → atributos; además descarga y parsea la ficha de perfiles FISBo (horizontes con Bodenart, humus, acidez KA5) |
| 5 | `paso5_resumen.py` | `RESUMEN.md` | Índice, estadísticas de latencia/errores por fuente (de `_llamadas.csv`) |

Cada petición HTTP queda registrada en `samples/_llamadas.csv` (URL exacta, HTTP, segundos, bytes, error).

## Ronda 2: comprobaciones para el diseño del backend

`comprobaciones2.py` (y sus anexos `comprobaciones2_extra4/5/6.py`) responde a las preguntas que decidieron
el diseño de los adaptadores; el resumen está en `samples2/RESUMEN2.md`:

1. Bodenschätzung en praderas frente a cultivo.
2. Geometría que devuelve LBEG.
3. Varias capas en una sola llamada GetFeatureInfo.
4. Cosecha de polígonos en el campo f51 (Umfeld Groß).
5. BÜK200 en cualquier punto de Alemania (y por qué no devuelve geometría).
6. SoilGrids por ráster para cualquier caja (wv0033/wv1500 solo por WCS).
7. LBEG fuera de cobertura.
8. Estabilidad de LBEG con concurrencia.

## Variables de entorno (ronda 1)

| Variable | Por defecto | Efecto |
|---|---|---|
| `SG_PAUSE` | 60 | Pausa entre consultas REST a SoilGrids |
| `SG_ALL_POINTS` | 0 | `1` = consultar SoilGrids también en P2 y P4 |
| `LBEG_DISCOVER` | 1 | `0` = saltar el barrido de las ~175 capas LBEG |
| `LBEG_WORKERS` | 2 | Concurrencia del barrido |
| `LBEG_DELAY` | 0.3 | Pausa (s) entre llamadas del barrido, por hilo |
| `N_PROBE` | 0 | Nº de campos sondeados contra LBEG en el paso 0 (0 = todos) |

## Archivos de apoyo

- `common.py`: rutas, sesión HTTP con reintentos, `fetch()` con log, recorte de geometrías, puntos.
- `lbeg.py`: GetFeatureInfo contra NIBIS (bbox 100 m en EPSG:25832, píxel central).
