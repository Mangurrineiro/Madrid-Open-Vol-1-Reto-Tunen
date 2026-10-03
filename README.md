# Tunen Soil Aggregation API

Proyecto del hackathon Tunen (octubre de 2026) para unificar datos de suelo de distintas fuentes alemanas y mostrarlos por campo de una granja. El repositorio contiene el enunciado, datos de ejemplo, documentación de arquitectura y scripts de exploración de las fuentes. La API y la interfaz descritas en los documentos están planificadas; todavía no están implementadas.

## Por dónde empezar

- [CLAUDE.md](CLAUDE.md): contexto y decisiones del proyecto para Claude Code.
- [docs/00_reto.md](docs/00_reto.md): alcance y criterios del reto.
- [docs/01_arquitectura.md](docs/01_arquitectura.md): diseño propuesto de la API y el flujo de datos.
- [docs/02_fuentes.md](docs/02_fuentes.md): fuentes de datos y resultados comprobados.
- [docs/04_plan.md](docs/04_plan.md): fases y trabajo pendiente.
- [evidencia/README.md](evidencia/README.md): cómo ejecutar las pruebas de las fuentes.

Los datos de la granja y los notebooks de partida están en `enunciado y datos/`. Los resultados de exploración están en `samples/` y `samples2/`.

## Preparar el entorno local

Se usa Python 3.12. Desde la raíz del proyecto:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r evidencia\requirements.txt
```

Los entornos virtuales y archivos de configuración local quedan excluidos de Git.
