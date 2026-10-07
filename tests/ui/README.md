# Comprobaciones de la interfaz

Scripts de Playwright que arrancan la API (uvicorn en el puerto 8765), abren Chromium, recorren la interfaz,
guardan capturas en `out/screens/` y terminan con código 1 si hay errores de consola o falla alguna acción.
Usan la granja de ejemplo y su caché versionada (`data/demo/`), así que no necesitan red.

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m playwright install chromium

.venv\Scripts\python tests\ui\check_demo_capas.py
```

| Script | Comprueba |
|---|---|
| `check_demo_capas.py` | Pantalla inicial → granja de ejemplo → las 6 capas y cambios de fuente |
| `check_campo_inspector.py` | Vista de campo, tooltip en varios puntos e inspector en un punto con conflicto |
| `check_incertidumbre.py` | Incertidumbre on/off (tecla U) y puntos de muestreo en el campo y en la granja |
| `check_subida_geojson.py` | Subida de GeoJSON: puntos, coordenadas invertidas, JSON inválido, error del servidor y un archivo válido |
| `check_pila3d.py` | Pila isométrica: hover, entrar en capas y volver |
| `check_textura.py` | Desglose de textura con cursor sincronizado e incertidumbre |
| `check_recorrido_demo.py` | Recorrido completo de la demo con atajos de teclado (`1366 768` como argumentos para otra resolución) |
| `check_fallback_modulos.py` | Si fallan los módulos de las vistas 3D, el mapa sigue funcionando |
| `check_terreno.py` | Relieve, pendiente, orientación, Ackerzahl − Bodenzahl e inspector con terreno |
| `check_perfil.py` | Perfil altimétrico en un campo con relieve y en otro con Bodenzahl |

La prueba unitaria del módulo de terreno no necesita navegador ni red:

```powershell
.venv\Scripts\python tests\test_terrain.py
```
