# Reglas de calidad: decisiones y evidencia

Análisis de `yellow_tripdata_2025-03` (4.145.257 filas) y `yellow_tripdata_2024-03`
(3.582.628 filas). Todas las cifras se dan como **2025-03 / 2024-03**.

## Criterio

- **Rechazo:** la fila no es un viaje válido del mes, o un campo que el modelo necesita
  (duración, distancia, zona) es imposible. Va a la cuarentena con la fila original, el
  archivo de origen y la lista de reglas violadas. Ninguna fila se borra: se tiene que
  cumplir que leídas = aceptadas + cuarentena.
- **Advertencia:** el viaje existió, pero un atributo es dudoso. La fila queda aceptada y la
  regla se marca en la columna de flags. Si el atributo dudoso entra en una métrica, la fila
  se excluye solo de esa métrica: `duracion_confiable` (sin R03 ni R18) para duración y
  velocidad, e `importe_confiable` (sin R19) para los promedios de tarifa e ingreso. Los
  conteos de viajes las incluyen siempre.
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
| R03 | Bajada igual a la subida | duración = 0 | Advertencia | 22.199 / 1.011 | En 2025, 21.481 filas son el 100 % del proveedor 7 (el 0,52 % del mes), con distancia y tarifa normales. El viaje existió; lo que falta es la duración, así que se excluye de las métricas de duración y velocidad, igual que R18. |
| R04 | Distancia en cero o negativa | `trip_distance` ≤ 0 | Advertencia | 103.722 / 87.168 | La mayoría son viajes reales con un ingreso válido: tarifa negociada, `payment_type` 0 o distancia no informada. |
| R05 | Distancia mayor al máximo | `trip_distance` > 500 | Advertencia | 168 / 95 | Hay un hueco en la cola: entre 200 y 500 mi hay 11 / 0 viajes. Todas estas filas ya las rechazan R16 o R03, así que la advertencia solo protege a un viaje real futuro. |
| R06 | Importe total negativo | `total_amount` < 0 | Rechazo | 68.686 / 44.311 | Son registros de reverso del proveedor 2, no viajes. |
| R07 | Pasajeros nulo | `passenger_count` es nulo | Advertencia | 916.663 / 426.190 | Es el bloque de `payment_type` 0 (el 22 % de 2025), con tarifas normales. Rechazarlo eliminaría un quinto del mes. |
| R08 | Pasajeros en cero | `passenger_count` = 0 | Advertencia | 22.715 / 40.372 | Es un valor que carga el conductor. El viaje y su importe siguen siendo válidos. |
| R09 | Zona inexistente | origen o destino ausente de `taxi_zone_lookup` | Rechazo | 0 / 0 | Una clave sin fila en `dim_zone` rompe el modelo estrella y el enriquecimiento por zona. |
| R10 | Zona desconocida | origen o destino en 264 | Advertencia | 13.954 / 21.396 | La 264 ("Unknown") está en la tabla, pero no es una ubicación. La 265 ("Outside of NYC") sí lo es: ver R21. |
| R11 | Duplicado exacto | `dup_n` > 1 | Rechazo | 0 / 0 | Una copia exacta contaría dos veces el mismo viaje. Hoy no hay casos. |
| R12 | Cargo de aeropuerto fuera de JFK y LaGuardia | `airport_fee` > 0 y origen fuera de 132 y 138 | Advertencia | 9.467 / 12.252 | El 94 % es East Elmhurst (zona 70), que limita con LaGuardia. Lo que se discute es un cargo, no el viaje. |
| R13 | `ratecode_id` fuera de catálogo | no nulo y fuera de 1–6 y 99 | Advertencia | 0 / 0 | Control ante códigos nuevos. |
| R14 | `payment_type` fuera de catálogo | fuera de 0–6 | Advertencia | 0 / 0 | Control ante códigos nuevos. El 0 se incluye (ver Limitaciones). |
| R15 | Pago no cobrado | `payment_type` en 3, 4 o 6 | Advertencia | 118.581 / 81.676 | El viaje existió, pero el importe no se cobró o está en disputa. |
| R16 | Velocidad imposible (propia) | duración > 0, distancia > 0 y distancia / horas > 80 | Rechazo | 1.050 / 1.241 | p999 = 46 / 48 mph. La velocidad máxima legal en NY es de 65 mph y entre 65 y 80 casi no hay filas. |
| R17 | Duración larga sin tarifa acorde (propia) | duración > 360 min y `fare_amount` < 0,35 × minutos | Rechazo | 1.364 / 1.922 | El taxímetro cobra al menos US$ 0,70 por minuto. Por encima de 6 h, la mediana es de US$ 0,011 / 0,012 por minuto. |
| R18 | Duración menor al mínimo (propia) | duración > 0 y < 60 s | Advertencia | 43.216 / 39.531 | Por debajo de 1 minuto la tarifa mediana es la bajada de bandera (US$ 3) o una tarifa fija: no son viajes medidos. Se cobraron, así que no se rechazan. |
| R19 | Tarifa negativa con total positivo (propia) | `fare_amount` < 0 y `total_amount` > 0 | Advertencia | 140.446 / 14.295 | Todas son del proveedor 2 con `payment_type` 0 (Flex Fare). Son viajes únicos, con distancia y duración normales, así que cuentan como viajes. Pero ni la tarifa ni el total son el precio: los promedios de `fare_amount` y de `total_amount` las excluyen. |
| R20 | Gemela de un reverso (propia) | misma subida, bajada, zonas, proveedor y archivo que una fila de total negativo, con el total opuesto | Rechazo | 60.463 / 38.391 | Es el cobro original de un par cobro + reverso: el reverso (R06) lo anuló. Con las dos filas en la cuarentena, el par queda junto y el ingreso no cuenta un cobro anulado. |
| R21 | Subida fuera de NYC (propia) | origen en 265 | Advertencia | 1.548 / 2.081 | El 80 % / 64 % también baja en la 265, casi siempre con tarifa negociada, distancia 0 y una tarifa mediana de US$ 68 / 59: la ubicación no quedó registrada, pero el importe es plausible. Bajar en la 265 no lleva regla. |
| R22 | Tarifa fija de JFK sin JFK (propia) | `ratecode_id` = 2 y ni origen ni destino en 132 | Advertencia | 7.559 / 8.386 | La tarifa fija rige entre JFK y Manhattan. De todos los viajes con `ratecode` 2, el 99,9 % cobra US$ 70: el código es coherente con el precio y lo dudoso es la zona. |
| R23 | Cargo del CBD fuera de catálogo (propia) | \|`cbd_congestion_fee`\| distinto de 0 y de 0,75 | Advertencia | 128 / 0 | El cargo para taxis es de US$ 0,75 por viaje desde el 5/1/2025. Aparecen 1,25, 1,50 y 0,25. El −0,75 de los reversos no cuenta. |

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
- **R03 pasó de rechazo a advertencia.** Como rechazo, mandaba a la cuarentena 22.195 / 1.007
  viajes que solo tenían R03, con US$ 565.000 / 27.000 de ingreso, y era incoherente con R18:
  las dos describen un viaje cobrado sin una duración útil. Como rechazo, además, 2025 perdía
  un proveedor entero y la comparación con 2024 quedaba sesgada (la variación de viajes en
  aeropuertos, por ejemplo, depende de los 1.404 viajes del proveedor 7 que tocan JFK o
  LaGuardia). Ahora la fila se acepta con duración 0 y `duracion_confiable` falso.

### Cambio de horario

Las fechas del Parquet son hora local de Nueva York, sin zona horaria. El 10/3/2024 y el
9/3/2025 los relojes pasaron de las 2:00 a las 3:00, así que un viaje que sube a la 1:50 y
baja a las 3:10 duró 20 minutos, no 80. Restar las dos fechas tal cual sumaba esa hora.

- **Casos:** 1.360 / 1.059 viajes aceptados cruzan el salto. Con la resta directa, su
  duración mediana daba 75 minutos y la mínima 62: todos tenían 60 minutos de más.
- **Corrección:** `int_calidad` calcula la duración interpretando las dos fechas como hora de
  `America/New_York` (`at time zone`) y la expone como `duracion_seg`. Todas las reglas de
  duración (R02, R03, R16, R17 y R18) y la capa curada usan ese valor. La mediana de esos
  viajes pasó a 14,5 / 15,4 minutos. Las fechas se siguen guardando sin zona horaria.
- **Por qué no una advertencia:** no es un dato sucio sino un error de cálculo con una
  corrección exacta. Marcarlo habría obligado a excluir de la duración viajes con una
  duración calculable.
- **Otros meses:** en noviembre el reloj se atrasa, y sin esta corrección un viaje que cruza
  el cambio daría hasta 60 minutos menos, y R02 podría rechazarlo. Ver Limitaciones.

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

**R18: viajes de menos de 1 minuto.** R02 y R03 cubren la duración negativa y la nula,
pero ninguna regla miraba la duración positiva y muy corta. Viajes aceptados con menos de
2 minutos (antes de R18):

| Duración | Viajes 2025 / 2024 | Con distancia 0 | Millas (promedio) | Tarifa (mediana) | Tarifa negociada (`ratecode` 5) |
| --- | --- | --- | --- | --- | --- |
| menos de 30 s | 27.545 / 25.108 | 76 % / 79 % | 0,01 | US$ 20 / 19 | 44 % / 41 % |
| 30 a 60 s | 7.590 / 7.406 | 46 % / 47 % | 0,08 | US$ 3 | 17 % / 16 % |
| 1 a 2 min | 27.233 / 26.246 | 10 % / 9 % | 0,31 | US$ 4,40 | 4 % / 3 % |

- **El corte está en 1 minuto.** Por debajo de 30 s no hay distancia y la tarifa es fija
  o negociada, cargada a mano: son cobros sin un viaje medido. Entre 30 y 60 s la mediana
  es US$ 3, la bajada de bandera: el taxímetro arrancó y se cortó. Desde 1 minuto son
  viajes cortos reales, con la tarifa que da el taxímetro.
- **Advertencia y no rechazo.** El cobro existió: las aceptadas con R18 suman US$ 1,45 /
  1,31 millones. Rechazarlas sacaría ingreso real de las preguntas de dinero. Es el mismo
  criterio que R04 y R15.
- **Cómo se usa.** Las métricas de duración y velocidad excluyen las filas con R18 y las de
  ingreso las incluyen. El efecto en la duración media de las aceptadas es chico: 15,67 →
  15,81 min en 2025 y 16,02 → 16,17 min en 2024.
- De las 43.216 / 39.531 filas con R18, 35.135 / 32.514 quedan aceptadas (las demás tienen
  otra regla de rechazo, sobre todo R06), y 28.640 / 26.656 también tienen distancia 0
  (R04).

**R19: tarifa negativa con total positivo.** R06 rechaza el total negativo, pero ninguna
regla miraba la tarifa negativa cuando el total es positivo. Hay 140.446 / 14.295 casos, y
140.407 / 14.293 quedan aceptados (los demás tienen otra regla de rechazo).

- **Todos son del proveedor 2 con `payment_type` 0** (Flex Fare). En 2025 suman US$ −598.836
  de tarifa y US$ 633.431 de total en las aceptadas. Son casi 10 veces más que en 2024.
- **No son reversos.** Un reverso (R06 y R20) es un par: el cobro original y una fila con el
  total negativo. Las filas de R19 tienen el total positivo y no tienen gemela: solo 5 de
  140.446 comparten subida, bajada, zonas y proveedor con otra fila. El tipo de pago también
  es otro: los reversos son sobre todo disputas (4), efectivo (2) y sin cargo (3); R19 es solo
  Flex Fare (0).
- **De dónde sale la tarifa negativa.** En 2025, en 137.631 de las 140.446 filas, la tarifa
  es la suma de los recargos con el signo cambiado: −4,75 = −(0,50 de MTA + 1,00 de mejora +
  0,75 de CBD + 2,50 de congestión), −4,00 sin el cargo del CBD, −1,50 con solo los dos
  primeros. Los recargos van en sus columnas y la tarifa los compensa, así que los
  componentes suman cero. En 2024 la forma es otra: solo 64 filas siguen ese patrón, con una
  tarifa mediana de −1.
- **El total tampoco es el precio.** El total medio es de US$ 4,51, contra US$ 25,63 de un
  Flex Fare con tarifa positiva, y el 96 % está por debajo de US$ 10. Crece algo con la
  distancia (US$ 3,59 de mediana hasta 5 mi, US$ 10 por encima de 15 mi), pero muy por debajo
  de lo que cuesta ese viaje. Las filas aparecen los 31 días, repartidas parejo: es una forma
  sistemática de cargar ciertos viajes, no una falla puntual.
- **Hipótesis (la TLC no lo documenta):** en Flex Fare el precio se cierra de antemano en la
  aplicación e incluye los recargos. El registro del taxímetro deja los recargos y los
  compensa en la tarifa, y el precio cobrado por la aplicación no llega a la fila.
- **Advertencia y no rechazo:** la distancia y la duración son las de un viaje normal (2,2 mi
  y 15 min de mediana), así que el viaje existió y cuenta en los viajes.
- **Cómo se usa.** `importe_confiable` es falso para estas filas. Los promedios de tarifa
  (preguntas e y f) y de ingreso (pregunta b) las excluyen; los conteos y las sumas, no.
  Efecto en 2025: la tarifa media de f pasaba de US$ 18,47 a 19,29, y el ingreso promedio de
  b, de US$ 27,18 a 27,99 en el mes y de 33,75 a 35,31 a las 5 de la mañana. Las bajas que
  mostraban f y b entre 2024 y 2025 venían de estas filas. Las cifras actuales, con todas las
  reglas, están en `RESULTADOS.md`.
- El umbral (0) está en el catálogo: la regla compara la tarifa y el total contra ese valor.

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

**R20: la gemela positiva.** Los pares son exactamente uno a uno: 60.463 / 38.391 negativas
tienen una sola gemela, y cada gemela una sola negativa. Las dos filas del par tienen el mismo
proveedor y, salvo en un caso, el mismo tipo de pago. Las gemelas suman US$ 1.718.199 /
1.019.158.

- **Rechazo:** el cobro original se anuló, así que el importe no es válido. Con la gemela en
  la cuarentena, el par queda completo ahí y el ingreso del modelo no cuenta un cobro que se
  revirtió, sin filtrar nada en las métricas.
- **Clave del par:** archivo, proveedor, subida, bajada, origen, destino y el total con el
  signo cambiado. `int_calidad` arma la lista de claves de las negativas con `distinct`, así
  que el join no puede duplicar viajes; si lo hiciera, la reconciliación fallaría.
- **Efecto:** 60.445 / 38.370 filas tienen R20 como única regla de rechazo. Las disputas
  (`payment_type` 4) aceptadas pasan de 48.615 / 31.385 a 11.016 / 8.329, porque la mayoría
  eran cobros que se revirtieron. Las subidas en JFK pierden 9.049 / 4.661 viajes.

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

1. **Reversos sin gemela.** R20 rechaza la gemela de 60.463 / 38.391 reversos. El 12 % / 13 %
   de las filas negativas no tiene gemela en el archivo: si su cobro original quedó en otro
   mes o cambió algún campo, ese cobro sigue aceptado.
2. **Proveedor 7.** Sus viajes no traen duración (R03). Cuentan como viajes y en el ingreso,
   pero no entran en las métricas de duración ni de velocidad.
3. **Cambio de horario en noviembre.** Cuando el reloj se atrasa, la hora entre la 1:00 y las
   2:00 pasa dos veces, y una fecha sin zona horaria no dice cuál de las dos era. La duración
   de un viaje que empieza o termina en esa hora puede quedar con 60 minutos de error. En
   marzo no pasa: la hora que se saltea no tiene subidas.
4. **R19.** No se sabe cuánto se cobró por esos viajes: el ingreso total los cuenta con su
   total registrado (US$ 4,51 de media), que es menor que el precio real.
5. **R17.** Las 9 / 5 filas de más de 6 h con una tarifa compatible pueden ser viajes
   reales o taxímetros que quedaron prendidos. Los datos no permiten distinguirlos, así que
   se aceptan.
6. **`airport_fee` de US$ 6,75 y US$ 5,00.** No hay una tarifa conocida que los explique;
   se tratan como valores fuera de catálogo.
7. **Catálogos.** Que `payment_type` 0 sea *Flex Fare* y `ratecode_id` 99 sea "desconocido"
   está pendiente de confirmar contra el diccionario de datos de la TLC.
