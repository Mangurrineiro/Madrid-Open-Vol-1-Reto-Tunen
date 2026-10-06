# Tunen Soil Aggregation API

Proyecto ganador del hackathon de Tunen (octubre de 2026). Un backend que unifica las fuentes de datos de
suelo alemanas detrás de una sola API y una interfaz web que pinta sus resultados sobre los campos de
una granja real (LuF Seggerde, 87 campos activos a ambos lados de la frontera entre Niedersachsen y
Sachsen-Anhalt).

![Vista de la granja](docs/img/granja.jpg)

## Qué hace

- **Recibe campos en GeoJSON** y calcula una rejilla común de 25 m por campo.
- **Consulta cinco fuentes**, cada una con su adaptador, y traduce sus valores a un idioma común
  (unidad, rango `low`/`high`, σ y valor original):

  | Fuente | Cobertura | Parámetros |
  |---|---|---|
  | ISRIC SoilGrids 2.0 (WCS) | Global, 250 m | arcilla, arena, limo, pH (agua), carbono orgánico, nFK |
  | LBEG NIBIS: BK50 + Bodenschätzung | Solo Niedersachsen | Bodenzahl, Ackerzahl, clase de la Bodenschätzung, nFK, Ertragsfähigkeit, tipo de suelo |
  | BGR BÜK200 + perfiles FISBo | Toda Alemania, 1:200.000 | arcilla, arena, limo, carbono orgánico, pH (CaCl₂) |
  | Copernicus DEM GLO-30 | Global, ~30 m | altitud, pendiente, orientación, relieve sombreado |
  | **derived** | Donde haya alguna fuente | media ponderada por 1/σ², desacuerdo entre fuentes, conflictos, prioridad de muestreo |

- **Devuelve una capa por campo × parámetro × fuente**: PNG listo para el mapa, rejilla JSON para el hover,
  estadísticas, colormap, procedencia y estado (`ok` / `no_coverage` / `error`).
- **Mide la fiabilidad**: dónde discrepan las fuentes, dónde un valor es físicamente imposible y
  qué puntos conviene muestrear en el campo.
- **Funciona sin red**: todas las respuestas externas se guardan en `data/cache/` (versionada), así que la
  demo de la granja arranca al instante tras clonar el repositorio.

## Arranque rápido

Requiere Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Abrir <http://localhost:8000> y pulsar **Try the example farm** (o subir un GeoJSON propio). La documentación
interactiva de la API está en <http://localhost:8000/docs>.

En Linux/macOS, sustituir `.venv\Scripts\python` por `.venv/bin/python`.

## API

| Método | Ruta | Qué devuelve |
|---|---|---|
| `POST` | `/soil/layers` | Capas de los campos enviados (`{"fields": FeatureCollection, "parameters"?: [...], "sources"?: [...]}`) |
| `GET` | `/soil/demo` | Lo mismo para la granja de ejemplo, más los campos destacados |
| `GET` | `/soil/fields/{id}/points` | Todos los valores por punto y fuente, con su incertidumbre |
| `GET` | `/soil/fields/{id}/sampling?k=` | Puntos de muestreo sugeridos y el motivo |
| `GET` | `/sources` | Matriz de fuentes: parámetros, cobertura, resolución y método |
| `GET` | `/parameters` | Unidad, colormap y descripción de cada parámetro |
| `POST` / `GET` | `/refresh` | Vacía la caché (de una fuente o de todas), recalcula en segundo plano y consulta el estado |

Ejemplo:

```powershell
curl -X POST http://localhost:8000/soil/layers -H "Content-Type: application/json" `
     -d '{"fields": <FeatureCollection>, "parameters": ["clay", "bodenzahl"], "sources": ["lbeg", "derived"]}'
```

Detalle del modelo de datos, los adaptadores y las respuestas en [docs/arquitectura.md](docs/arquitectura.md).

## CLI

```powershell
.venv\Scripts\python -m app.cli test "Umfeld Groß" Mittelbreite   # resumen por fuente y parámetro + CSV de la tabla larga
.venv\Scripts\python -m app.cli warm data\fields.geojson          # precarga la caché (reintenta los errores de LBEG)
.venv\Scripts\python -m app.cli refresh --source lbeg             # vacía la caché de una fuente y recalcula
```

El módulo de terreno se puede desactivar con la variable de entorno `ENABLE_TERRAIN=0`.

## Interfaz

| | |
|---|---|
| ![Pila 3D](docs/img/pila3d.jpg) | ![Inspector](docs/img/inspector.jpg) |
| ![Incertidumbre](docs/img/incertidumbre.jpg) | ![Perfil altimétrico](docs/img/perfil.jpg) |

Mapa de la granja y de cada campo con seis capas (textura, pH, carbono orgánico, agua útil, Bodenzahl y
fiabilidad), cambio de fuente, inspector por punto, mapa de incertidumbre, puntos de muestreo, pila
isométrica de capas, desglose de textura, relieve y perfil altimétrico. Ver [docs/interfaz.md](docs/interfaz.md).

## Estructura del repositorio

```
app/              API FastAPI
  sources/        un adaptador por fuente (soilgrids, lbeg, buek200, copernicus_dem, derived)
lookups/          tablas fijas de traducción de clases alemanas (KA5, Bodenschätzung) a números con rango
static/           interfaz web (HTML + módulos ES, Leaflet)
data/             fields.geojson de la granja y cache/ con todas las respuestas de las fuentes
tests/            prueba del módulo de terreno y comprobaciones de la interfaz con Playwright (tests/ui)
docs/             reto, arquitectura, fuentes, matriz de cobertura e interfaz
reto/             enunciado original, GeoJSON de la granja y notebooks oficiales del hackathon
exploracion/      pruebas iniciales: notebook de SoilGrids, pruebas de LBEG BK50 y la recogida de evidencia
```

## Documentación

- [docs/reto.md](docs/reto.md): el reto, el alcance y los criterios del jurado.
- [docs/arquitectura.md](docs/arquitectura.md): pipeline, tabla larga, adaptadores, caché y API.
- [docs/fuentes.md](docs/fuentes.md): hechos verificados de cada fuente (atributos, unidades, latencias, problemas).
- [docs/matriz_cobertura.md](docs/matriz_cobertura.md): parámetro × fuente y cómo se traduce cada uno.
- [docs/interfaz.md](docs/interfaz.md): funcionalidades de la interfaz.
- [exploracion/README.md](exploracion/README.md): cómo llegamos hasta aquí.
