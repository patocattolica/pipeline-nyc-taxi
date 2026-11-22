# Reglas de calidad: decisiones y evidencia

Análisis de `yellow_tripdata_2025-03` (4.145.257 filas) y `yellow_tripdata_2024-03`
(3.582.628 filas). Todas las cifras se dan como **2025-03 / 2024-03**.

## Criterio

- **Rechazo:** la fila no es un viaje válido del mes, o un campo que el modelo necesita
  (duración, distancia, zona) es imposible. Va a la cuarentena con la fila original, el
  archivo de origen y la lista de reglas violadas. Ninguna fila se borra: se tiene que
  cumplir que leídas = aceptadas + cuarentena.
- **Advertencia:** el viaje existió y su importe es válido, pero un atributo es dudoso. La
  fila queda aceptada y la regla se marca en la columna de flags.
- **Los umbrales viven en el catálogo de reglas, no en el código.** Cambiar un umbral es
  editar el catálogo y reprocesar el mes. Un viaje real que cae en una regla queda en la
  cuarentena y aparece en el reporte de calidad, así que el error se puede detectar y
  revertir.
- **Preferimos las reglas que comparan campos entre sí** (distancia contra tiempo, tarifa
  contra tiempo) a las que miran una magnitud sola, porque resisten mejor los casos
  extremos pero reales.

## Catálogo

| ID | Regla | Condición | Severidad | Filas | Justificación |
| --- | --- | --- | --- | --- | --- |
| R01 | Subida fuera del mes | subida < inicio del mes, o ≥ inicio del mes siguiente | Rechazo | 33 / 23 | El viaje pertenece a otro mes. Hay subidas en 2002 y 2007: son relojes rotos. |
| R02 | Bajada anterior a la subida | bajada < subida | Rechazo | 81 / 117 | Duración negativa: no se pueden calcular la duración ni la velocidad. |
| R03 | Bajada igual a la subida | bajada = subida | Rechazo | 22.199 / 1.011 | Sin duración no hay velocidad ni duración media. En 2025, 21.481 filas son el 100 % del proveedor 7 (el 0,52 % del mes). |
| R04 | Distancia en cero o negativa | `trip_distance` ≤ 0 | Advertencia | 103.722 / 87.168 | La mayoría son viajes reales con un ingreso válido: tarifa negociada, `payment_type` 0 o distancia no informada. |
| R05 | Distancia mayor al máximo | `trip_distance` > 500 | Advertencia | 168 / 95 | Hay un hueco en la cola: entre 200 y 500 mi hay 11 / 0 viajes. Todas estas filas ya las rechazan R16 o R03, así que la advertencia solo protege a un viaje real futuro. |
| R06 | Importe total negativo | `total_amount` < 0 | Rechazo | 68.686 / 44.311 | Son registros de reverso del proveedor 2, no viajes. |
| R07 | Pasajeros nulo | `passenger_count` es nulo | Advertencia | 916.663 / 426.190 | Es el bloque de `payment_type` 0 (el 22 % de 2025), con tarifas normales. Rechazarlo eliminaría un quinto del mes. |
| R08 | Pasajeros en cero | `passenger_count` = 0 | Advertencia | 22.715 / 40.372 | Es un valor que carga el conductor. El viaje y su importe siguen siendo válidos. |
| R09 | Zona inexistente | origen o destino ausente de `taxi_zone_lookup` | Rechazo | 0 / 0 | Una clave sin fila en `dim_zone` rompe el modelo estrella y el enriquecimiento por zona. |
| R10 | Zona desconocida | origen o destino en 264 o 265 | Advertencia | 28.415 / 35.374 | Las dos están en la tabla ("Unknown" y "Outside of NYC"). El viaje es válido, pero sin una ubicación útil. |
| R11 | Duplicado exacto | `dup_n` > 1 | Rechazo | 0 / 0 | Una copia exacta contaría dos veces el mismo viaje. Hoy no hay casos. |
| R12 | Cargo de aeropuerto fuera de JFK y LaGuardia | `airport_fee` > 0 y origen fuera de 132 y 138 | Advertencia | 9.467 / 12.252 | El 94 % es East Elmhurst (zona 70), que limita con LaGuardia. Lo que se discute es un cargo, no el viaje. |
| R13 | `ratecode_id` fuera de catálogo | no nulo y fuera de 1–6 y 99 | Advertencia | 0 / 0 | Control ante códigos nuevos. |
| R14 | `payment_type` fuera de catálogo | fuera de 0–6 | Advertencia | 0 / 0 | Control ante códigos nuevos. El 0 se incluye (ver Limitaciones). |
| R15 | Pago no cobrado | `payment_type` en 3, 4 o 6 | Advertencia | 118.581 / 81.676 | El viaje existió, pero el importe no se cobró o está en disputa. |
| R16 | Velocidad imposible (propia) | duración > 0, distancia > 0 y distancia / horas > 80 | Rechazo | 1.050 / 1.241 | p999 = 46 / 48 mph. La velocidad máxima legal en NY es de 65 mph y entre 65 y 80 casi no hay filas. |
| R17 | Duración larga sin tarifa acorde (propia) | duración > 360 min y `fare_amount` < 0,35 × minutos | Rechazo | 1.364 / 1.922 | El taxímetro cobra al menos US$ 0,70 por minuto. Por encima de 6 h, la mediana es de US$ 0,011 / 0,012 por minuto. |

## Evidencia

### Tarifa del taxímetro

La tarifa estándar de la TLC (`ratecode` 1) es de **US$ 3 de bajada de bandera más US$ 0,70
por cada 1/5 de milla, o por cada minuto detenido o por debajo de 12 mph**. Eso da US$ 3,50
por milla o US$ 42 por hora. Por eso la tarifa sirve para controlar la distancia y la
duración: un viaje medido no puede durar 6 horas y costar US$ 28.

### Fechas y duración

- **Bajada en el mes siguiente:** no es un error. De 975 / 629 casos, 930 / 542 son viajes
  normales que empezaron la noche del 31. El viaje pertenece al mes de la subida, que es
  como la TLC arma los archivos. Los demás superan las 3 h y los cubre R17.
- **R02:** el proveedor 6 aparece con menos de 1 minuto negativo (relojes desincronizados);
  el proveedor 1, con hasta 37 minutos.
- **R03 y el proveedor 7:** sus viajes son normales en todo lo demás (2,4 mi y US$ 24,5 en
  promedio), pero informan la bajada igual a la subida en el 100 % de los casos. El
  proveedor solo aparece en 2025.

Duración de los viajes con bajada posterior a la subida:

| Duración | 2025-03 | 2024-03 | Millas (mediana, 2025) | Tarifa (mediana, 2025) |
| --- | --- | --- | --- | --- |
| hasta 3 h | 4.121.403 | 3.579.328 | 1,8 | US$ 13,5 |
| 3 a 6 h | 201 | 245 | 12,0 | US$ 51,3 |
| 6 a 12 h | 159 | 181 | 4,8 | US$ 28,2 |
| 12 a 23 h | 153 | 271 | 3,2 | US$ 18,4 |
| 23 a 24 h | 1.050 | 1.455 | 1,9 | US$ 14,2 |
| más de 24 h | 11 | 20 | 3,9 | US$ 17,7 |

El grupo de 23 a 24 h corresponde a un taxímetro que no se cerró: la bajada queda un día
después y unos minutos antes de la hora de la subida, con la distancia y la tarifa de un
viaje corto.

**Umbral de R17.** De las filas medidas de más de 6 h (1.247 / 1.759), solo 8 / 4 cobran
US$ 0,70 por minuto o más, y entre US$ 0,35 y US$ 0,70 no cae ninguna, así que el factor
exacto no cambia el resultado. Las 6 h funcionan como piso: entre 1 y 6 h, la relación
entre tarifa y tiempo fallaría en el 13 % de los viajes medidos (1.278 de 9.617), así que
por debajo de ese tiempo no es confiable. El viaje real más largo observado (320 mi fuera
del estado, US$ 2.200) duró 5,4 h.

### Distancia

| Medida | 2025-03 | 2024-03 |
| --- | --- | --- |
| p50 (mediana) | 1,80 | 1,75 |
| p99 | 19,42 | 19,90 |
| p999 | 28,80 | 29,30 |
| p9999 | 58,03 | 56,19 |
| media | 6,58 | 4,52 |
| máximo | 320.136,29 | 176.836,30 |
| más de 50 / 100 / 200 / 500 mi | 595 / 214 / 179 / 168 | 508 / 122 / 95 / 95 |

Unos pocos valores absurdos arrastran la media, que en 2025 es más del triple de la
mediana. Por eso se usan percentiles. La cola no es continua: los viajes reales se apagan
cerca de las 200 mi, y por encima de 500 mi aparece un grupo aparte de valores rotos.

Por tramo de distancia (2025-03):

| Millas | Viajes | Minutos (mediana) | mph (mediana) | US$ por milla (mediana) |
| --- | --- | --- | --- | --- |
| 50–100 | 381 | 85,5 | 43,2 | 5,03 |
| 100–200 | 35 | 134,2 | 53,4 | 3,10 |
| 200–1.000 | 14 | 13,8 | 831,7 | 0,21 |
| más de 1.000 | 165 | 17,0 | 259.112 | 0,00 |

La distancia sola no separa los casos reales de los rotos:

| Millas | Minutos | mph | Tarifa | Lectura |
| --- | --- | --- | --- | --- |
| 319,8 | 322 | 60 | US$ 2.200 (`ratecode` 4) | Real |
| 223,7 | 292 | 46 | US$ 450 (`ratecode` 5) | Real, tarifa negociada |
| 187,9 | 102 | 110 | US$ 48,5 | Roto |
| 403,2 | 29 | 837 | US$ 25,4 | Roto |

**Velocidad media** (solo filas con duración y distancia mayores a 0): la mediana es de
9,8 / 9,6 mph y el p999 de 46,1 / 48,4 mph. Hay 1.173 / 1.340 filas por encima de 65 mph y
1.050 / 1.241 por encima de 80. Las de más de 80 mph en 2025 se reparten así: 164 con más
de 1.000 mi (odómetro roto), 660 con menos de 1 minuto (timestamps rotos) y 226 en el
resto. Los viajes reales largos andan entre 45 y 63 mph.

**R05 frente a las demás reglas:**

| | 2025-03 | 2024-03 |
| --- | --- | --- |
| Filas de más de 500 mi | 168 | 95 |
| ... que ya rechaza R16 | 167 | 95 |
| ... que ya rechaza R03 | 1 | 0 |
| ... que solo marcaría R05 | 0 | 0 |

### Distancia en cero

Los grupos se solapan. Cifras de 2025-03:

| Grupo | Filas (aprox.) | Lectura |
| --- | --- | --- |
| `payment_type` 0, unos 15 minutos, tarifa normal | 62.000 | Viaje real sin distancia informada |
| Tarifa negociada (`ratecode` 5) | 12.000 | Precio fijo: el taxímetro no mide la distancia |
| Más de 5 min, tarifa mayor a US$ 10, zonas distintas | 48.000 | Viaje real con la distancia perdida |
| Menos de 2 min, misma zona, US$ 0 o 3, pago 2/3/4 | 30.000 | Cancelación o arranque en falso |

Las cancelaciones con importe negativo las rechaza R06, y las no cobradas las marca R15.

### Importe negativo

- Todas las filas son del proveedor 2. En 2025, por tipo de pago: 4 (disputa) 42.896,
  2 (efectivo) 17.032, 3 (sin cargo) 8.719, 1 (tarjeta) 25 y 0 (Flex Fare) 14.
- El 88 % / 87 % tiene una gemela positiva, con la misma subida, bajada y zonas y el
  mismo total con el signo cambiado: es el registro de reverso de un viaje disputado o
  reintegrado. R11 no las detecta porque no son idénticas.
- Suman US$ −1.934.751 / −1.174.208, el 1,75 % / 1,19 % del ingreso positivo.
- Las 12.645 / 6.547 filas con `airport_fee` = −1,75 están todas dentro de este grupo.

### Cargo de aeropuerto

- Valores: US$ 1,75 es el cargo vigente por subir en JFK o LaGuardia; US$ −1,75 sale de los
  reversos; US$ 6,75 (641 filas) y US$ 5,00 (150) aparecen solo en 2025; US$ 1,25 (2 filas)
  es el valor anterior.
- Con cargo y subida fuera de JFK y LaGuardia: 9.467 / 12.252 filas. El 93,7 % es East
  Elmhurst (zona 70), al lado de LaGuardia, donde la subida queda asignada a la zona vecina.
  Jackson Heights (129) va por el mismo camino.
- El proveedor 7 tiene 149 casos, todos con la bajada en JFK o LaGuardia: aplica el cargo a
  la bajada en lugar de a la subida.

### Pasajeros nulo y catálogos

- Las filas con `passenger_count` nulo son exactamente las de `payment_type` 0, y en todas
  también vienen nulos `ratecode_id`, `airport_fee` y `congestion_surcharge`.
- Valores observados: `payment_type` 0, 1, 2, 3 y 4; `ratecode_id` 1 a 6, 99 y nulo.

## Limitaciones conocidas

1. **Gemelas de los reversos.** Al rechazar la fila negativa, su gemela positiva queda
   aceptada: unos 60.000 viajes y US$ 1,9 millones en 2025 cuentan como cobrados aunque se
   revirtieron. Queda documentado y no se corrige.
2. **Proveedor 7.** R03 lo manda completo a la cuarentena, así que 2025 pierde el 0,52 % de
   sus viajes. Esto afecta la comparación de viajes totales entre los dos meses.
3. **R17.** Las 9 / 5 filas de más de 6 h con una tarifa compatible pueden ser viajes
   reales o taxímetros que quedaron prendidos. Los datos no permiten distinguirlos, así que
   se aceptan.
4. **`airport_fee` de US$ 6,75 y US$ 5,00.** No hay una tarifa conocida que los explique;
   se tratan como valores fuera de catálogo.
5. **Catálogos.** Que `payment_type` 0 sea *Flex Fare* y `ratecode_id` 99 sea "desconocido"
   está pendiente de confirmar contra el diccionario de datos de la TLC.
