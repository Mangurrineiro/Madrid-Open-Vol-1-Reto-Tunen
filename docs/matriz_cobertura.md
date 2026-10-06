# Matriz de cobertura (parámetro × fuente)

Qué aporta cada fuente a cada parámetro, de qué atributo sale y cómo se traduce a la unidad común. La API la
expone resumida en `GET /sources`. Todos los parámetros de suelo se refieren al topsoil (0–30 cm).

## Matriz

| Parámetro | SoilGrids 2.0 | LBEG BK50 | LBEG Bodenschätzung | BGR BÜK200 + FISBo | derived |
|---|---|---|---|---|---|
| **Arcilla / arena / limo** (%) | `clay`, `sand`, `silt` (g/kg ÷ 10) · 0-5/5-15/15-30 cm ponderado a 0–30 · low/high = Q05/Q95 | — (el WMS no trae Bodenart) | Clase (`KLASSENZEICHEN`: S, Sl, lS…) → rango de partículas < 0,01 mm (`bodenart_bs`); no se convierte a arcilla | Bodenart KA5 del horizonte 0–3 dm → centroide (`ka5_bodenart.csv`); σ = rango/√12 + dispersión entre perfiles | Media ponderada 1/σ², normalizada a 100 % |
| **pH** | `phh2o` ÷ 10 (pH en agua) | — | — | Clase de acidez KA5 → punto medio (`ka5_acidez.csv`), **pH en CaCl₂** (no se mezcla con pH en agua) | — |
| **Carbono orgánico** (g/kg) | `soc` (dg/kg ÷ 10) | — | — | Clase de humus h0–h7 → % MO → ÷ 1,72 × 10 (`ka5_humus.csv`) | Media ponderada 1/σ² |
| **nFK** (mm/dm) | `wv0033` − `wv1500` (WCS); σ = √(σ33² + σ1500²) | `NFKWE` (L839) / (`WE` (L823) / 10); σ = 2 mm/dm (supuesta) | — | — | Media ponderada 1/σ² |
| **Bodenzahl** (0–100) | — | Proxy: Ertragsfähigkeit BFR 1–7 (L837), capa propia | `BODENZ` (int); además `ACKERZ` (string → número) | — | Valor de la Bodenschätzung |
| Otras capas | — | Tipo de suelo (L816), Ertragsfähigkeit | Ackerzahl, clase de la Bodenschätzung | Clase KA5 dominante (`ka5_class`) | Desacuerdo, σ del modelo, `clay_conflict`, prioridad de muestreo |
| **Cobertura** | Global (zonas urbanas enmascaradas) | Solo Niedersachsen (40 de 87 campos) | Solo Niedersachsen (huecos en pueblos y caminos) | Toda Alemania | Donde haya alguna fuente |
| **Resolución** | 250 m | 1:50.000 | 1:5.000 | 1:200.000 (sin geometría) | Rejilla de 25 m |
| **Latencia** | ~0,4 s por cobertura WCS (REST por punto ~35 s, descartado) | ~0,15 s por llamada, con cuelgues y 503.2 | Misma llamada que BK50 | ~0,3 s por punto + ficha FISBo por unidad | Sin llamadas |

Copernicus DEM GLO-30 (módulo de terreno) aporta altitud, pendiente, orientación y relieve; no se combina con
las fuentes de suelo.

## Tipos de solapamiento

- **Mismo concepto, distinta definición**: textura (SoilGrids corta arena/limo en 50 µm, KA5 en 63 µm; la
  Bodenschätzung habla de "partículas finas" < 0,01 mm), nFK (SoilGrids a 33 kPa frente a la capacidad de
  campo alemana a pF 1,8 ≈ 6 kPa), pH en agua frente a pH en CaCl₂.
- **Sustituto (proxy)**: Ertragsfähigkeit (BFR 1–7) frente a Bodenzahl; humus KA5 frente a carbono orgánico.
- **Distinta resolución**: SoilGrids 250 m (un campo = 1–2 píxeles) frente a BK50 1:50k, Bodenschätzung 1:5k
  y BÜK200 1:200k.
- **Distinta cobertura**: LBEG solo cubre Niedersachsen y la granja está partida por la frontera → `no_coverage`
  en Sachsen-Anhalt, donde BÜK200 y SoilGrids son las únicas fuentes.
- **Fuentes no independientes**: SoilGrids y OpenLandMap son modelos de aprendizaje automático con datos de
  entrenamiento parecidos (OpenLandMap no se incorporó).

## Conflictos detectados

`clay_conflict` marca los puntos donde la arcilla de SoilGrids supera el máximo de partículas finas que admite
la clase de la Bodenschätzung (la arcilla es parte de esas partículas finas): una incoherencia física entre
fuentes que se usa para priorizar dónde muestrear.
