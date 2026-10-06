# Interfaz

Aplicación web en `static/` (HTML + módulos ES, sin compilación), servida por la propia API en
<http://localhost:8000>. Solo consume la API; nunca llama a las fuentes directamente. Los textos de la
interfaz están en inglés.

## Recorrido

1. **Pantalla inicial**: probar la granja de ejemplo o arrastrar un GeoJSON propio. La subida se valida en el
   navegador (geometrías que no son polígonos, coordenadas invertidas, JSON inválido) antes de enviarla a
   `POST /soil/layers`.
2. **Vista de granja** (`GET /soil/demo`): todos los campos sobre imagen de satélite, con la capa activa y los
   campos destacados (los de mayor desacuerdo entre fuentes, al menos uno por Land).

   ![Granja](img/granja.jpg)

3. **Vista de campo**: al entrar en un campo se abre la **pila isométrica** de sus seis capas recortadas con la
   silueta real del campo; se puede girar y entrar en cualquier capa.

   ![Pila 3D](img/pila3d.jpg)

4. **Capa en el mapa**: la rejilla JSON de la capa (`grid_url`) se pinta en un canvas con la paleta agronómica
   y se recorta con la silueta del campo. Leyenda, selector de fuente y tooltip con el valor bajo el cursor.

## Capas

| Capa | Subcapas | Fuentes |
|---|---|---|
| Texture | clases, arcilla, arena, limo | Clases: Combined (Bodenschätzung de LBEG si el campo la tiene; si no, clase KA5 de BÜK200), LBEG o BÜK200. Porcentajes: derived, SoilGrids, BÜK200 |
| pH | — | SoilGrids (agua), BÜK200 (CaCl₂, estimación por clase) |
| Organic carbon | — | derived, SoilGrids, BÜK200 |
| Plant-available water (nFK) | — | derived, SoilGrids, LBEG |
| Soil quality | Bodenzahl, Ackerzahl − Bodenzahl | LBEG (Bodenschätzung) |
| Reliability | — | Índice 0–100 a partir de la prioridad de muestreo |
| Relative elevation, Slope, Aspect | — | Copernicus DEM GLO-30 |

## Fiabilidad y muestreo

- **Inspector** (clic en un punto): todos los valores de todas las fuentes en ese punto, su incertidumbre y
  los conflictos (`GET /soil/fields/{id}/points`).

  ![Inspector](img/inspector.jpg)

- **Incertidumbre** (tecla U): superpone el desacuerdo entre fuentes (o, si falta, la σ del modelo) sobre la capa
  activa, normalizado por el percentil 98 de la granja. En pH y Bodenzahl no se calcula: no hay fuentes comparables.

  ![Incertidumbre](img/incertidumbre.jpg)

- **Muestreo** (tecla S): puntos donde conviene tomar una muestra física y por qué
  (`GET /soil/fields/{id}/sampling`). En la granja se muestran todos los campos como puntos pequeños; el
  número y el motivo van en el tooltip.

  ![Muestreo](img/muestreo.jpg)

- **Desglose de textura** (tecla B en la capa Texture): tres paneles sincronizados de arcilla, arena y limo.

  ![Desglose de textura](img/textura.jpg)

## Terreno

- **Relieve sombreado** (tecla R) en la granja y en el campo; en el campo se combina con la capa activa.
- **Perfil altimétrico** (tecla P): dos clics dentro del campo dibujan el perfil de altitud y, si existe, de
  Bodenzahl a lo largo de la línea. Los tramos fuera del campo quedan como hueco.

  ![Relieve](img/relieve.jpg)
  ![Perfil altimétrico](img/perfil.jpg)

## Atajos de teclado

| Tecla | Acción |
|---|---|
| 1–6 | Capas de suelo (7–9: capas de terreno) |
| U / S | Incertidumbre / puntos de muestreo |
| R | Relieve sombreado |
| P | Perfil altimétrico |
| M | Pasar de la pila 3D al mapa |
| B / Esc | Volver a la granja (o cerrar el desglose / perfil) |

## Módulos

| Fichero | Función |
|---|---|
| `js/app.js` | Estado, navegación entre vistas y atajos |
| `js/api.js` | Llamadas a la API |
| `js/catalog.js` | Catálogo de capas, subcapas y fuentes |
| `js/map2d.js`, `js/renderer.js` | Mapa Leaflet y pintado de las capas recortadas al campo |
| `js/panel.js`, `js/tooltip.js`, `js/inspector.js` | Panel lateral, tooltip y inspector por punto |
| `js/uncertainty.js` | Capa de incertidumbre y puntos de muestreo |
| `js/upload.js` | Subida y validación de GeoJSON |
| `js/palettes.js` | Paletas y nombres de las clases de suelo |
| `js/stack3d.js`, `js/texture3.js` | Pila isométrica y desglose de textura (carga dinámica: si fallan, el mapa sigue funcionando) |
| `js/terrain.js`, `js/profile.js` | Relieve, capas de terreno y perfil altimétrico |

Las comprobaciones automáticas de la interfaz están en [`tests/ui/`](../tests/ui/README.md).
