# Pipeline NYC Taxi

Este repositorio es nuestro examen de Fundamentos de Ingeniería de Datos (UTN-FRT). Lo hicimos
entre los dos, Patricio Cattolica y Federico Nacusse. Armamos un pipeline batch que toma los
viajes de taxi amarillo de Nueva York de un mes y del mismo mes del año anterior. Los
descargamos, los validamos, separamos los que no sirven, escribimos una capa curada en
Parquet, armamos un modelo estrella y respondemos seis preguntas de negocio. Nuestro mes
asignado es **marzo de 2025** y lo comparamos con **marzo de 2024**.

Las respuestas están en [`RESULTADOS.md`](RESULTADOS.md). La evidencia detrás de cada regla de
calidad está en [`reglas.md`](reglas.md). En [`docs/decisiones.md`](docs/decisiones.md) fuimos
anotando cada decisión que tomamos, con las mediciones que la justifican.

## Cómo correrlo

Solo hace falta tener Docker (con Compose), Make y Python 3.11. Pusimos Postgres en un
contenedor y dejamos que las dependencias de Python se instalen solas en un entorno virtual,
para que cualquiera pueda correrlo sin configurar nada. Desde una copia nueva del repositorio
alcanza con:

```bash
git clone https://github.com/patocattolica/pipeline-nyc-taxi.git
cd pipeline-nyc-taxi
make all MES=2025-03
```

La primera vez, Make copia `.env.example` a `.env` (son las credenciales del Postgres local,
que solo escucha en 127.0.0.1), crea el entorno `.venv-dlt` con las versiones que fijamos en
`requirements.lock` y levanta el contenedor. Después le pasa la corrida a Dagster, que baja los
dos meses y corre todas las etapas. Si cualquier etapa falla, `make` termina con un código
distinto de 0.

También dejamos comandos para revisar lo que pasó. `make conteos MES=2025-03` muestra el
reporte de calidad, las filas del modelo y el hash de cada archivo curado; es lo que usamos
para comparar dos corridas. `make ui` abre la interfaz de Dagster en http://localhost:3000, con
el grafo de etapas y el historial de corridas. `make test` corre los tests de Python.

## Cómo lo armamos

El recorrido es siempre el mismo y corre dos veces, primero para el mes asignado y después para
el de comparación:

```text
descarga -> ingesta (dlt) -> staging -> calidad -> curada (Parquet) -> modelo y preguntas
```

Para la **descarga** escribimos un script propio (`src/pipeline/descarga.py`) que deja el
archivo de la TLC tal cual en `data/raw/yellow/year=AAAA/month=MM/`. Calculamos su SHA-256 y lo
anotamos en `ingestion_log`, junto con la URL, las filas, los bytes, la fecha y el estado. Si el
archivo ya está y el hash coincide con el de la última descarga buena, no lo volvemos a bajar.
Ante una falla de red reintentamos tres veces, esperando 2, 4 y 8 segundos, y si no hay caso
registramos el error y salimos con código 1. La tabla de zonas pasa por el mismo control, así
que se baja una sola vez.

La **ingesta** (`src/pipeline/ingesta.py`) lleva el Parquet a Postgres con dlt. Antes de cargar
comparamos el esquema del archivo contra el contrato y, al terminar, verificamos que la base
tenga exactamente las filas del archivo. Cada mes se reemplaza entero por su `source_file`, así
que volver a cargarlo no duplica nada ni toca el otro mes. Elegimos dlt después de medirlo
contra PyAirbyte, que era nuestro diseño original: con PyAirbyte un mes tardaba unos 15 minutos
y había que partirlo en trozos para que entrara en memoria; con dlt carga entero en 74 segundos
y usa menos de 1 GB.

Todo lo que sigue lo escribimos en SQL con **dbt**. El staging solo renombra y convierte tipos.
La calidad evalúa las reglas sobre cada viaje y lo manda a aceptados o a cuarentena. La capa
curada calcula las columnas derivadas y suma los nombres de zona. El modelo y las preguntas
leen solo de ahí. A **DuckDB** le dejamos un único paso: lee la vista curada de Postgres y
escribe el Parquet particionado, con la memoria limitada a 512 MB.

Para orquestar las etapas usamos **Dagster** (`src/orquestacion/definitions.py`). Cada etapa
propia es un asset que llama al script como un proceso aparte, y cada modelo de dbt es un asset
con sus tests como controles. A Make le dejamos la preparación: valida el mes, crea el entorno,
levanta Postgres y le pasa el mes a Dagster.

## Esquema

Definimos el contrato en [`contracts/yellow_schema.yaml`](contracts/yellow_schema.yaml). Para
cada una de las 20 columnas dice cómo se llama en el archivo, cómo se llama en snake_case (por
ejemplo, `PULocationID` pasa a `pu_location_id`), qué tipo trae el Parquet y qué tipo va en
Postgres. Los importes y la distancia los guardamos en `numeric(10,2)` porque es dinero y
queremos sumas exactas; antes de fijarlo medimos los máximos para estar seguros de que
entraban.

Antes de cargar cada archivo, leemos su esquema y lo comparamos con el contrato. Si falta una
columna o alguna viene con otro tipo, cortamos ahí, antes de escribir nada, y salimos con error.
Si aparece una columna que el contrato no conoce, avisamos y seguimos sin cargarla. Para
nosotros agregarla es una decisión que tiene que quedar escrita en el contrato, no algo que pase
solo.

La columna `cbd_congestion_fee` no existe en los archivos de 2024, porque el cargo de congestión
empezó a cobrarse el 5 de enero de 2025. En 2024 decidimos cargarla como **nula** y no como 0: un
0 diría que se cobró un cargo de cero dólares, cuando en realidad el cargo no existía. En el
contrato le pusimos una fecha de inicio. Antes de esa fecha que falte es lo esperado; después,
que falte es un error.

## Calidad

Definimos 23 reglas en un catálogo, [`seeds/reglas_calidad.csv`](seeds/reglas_calidad.csv), cada
una con su descripción, su severidad y su umbral. Dejamos los umbrales ahí y no en el código:
cambiar uno es editar el CSV y volver a correr. La tabla completa, con cuántas filas toca cada
regla y por qué la definimos así, está en `reglas.md`.

Para cada regla nos hicimos la misma pregunta: ¿el viaje existió? Si la respuesta es no, o si
falta algo sin lo que el modelo no puede funcionar, mandamos la fila a la cuarentena. Así pasa
con un viaje que termina antes de empezar o que va a 800 millas por hora. Si el viaje existió
pero algún dato es dudoso, dejamos la fila y la marcamos en `flags`. Por ejemplo, casi un
millón de viajes de 2025 vienen sin cantidad de pasajeros. Son todos los pedidos por
aplicación, con tarifas normales, y rechazarlos habría borrado un quinto del mes.

A veces una advertencia sí afecta un cálculo. En esos casos la fila sigue contando como viaje,
pero la sacamos de esa métrica. Los viajes de duración cero (R03) no entran en la duración
media. Los de tarifa negativa (R19) no entran en la tarifa media.

Varias reglas son propias: las encontramos explorando los datos. La que más nos gusta es R17:
el taxímetro cobra por lo menos US$ 0,70 por minuto, así que un viaje medido de más de seis
horas no puede costar US$ 28, que es lo que muestran los taxímetros que quedaron prendidos.
Otra es R20. Cuando se revierte un cobro, el proveedor deja dos filas: el cobro y su reverso en
negativo. Rechazando solo el negativo, seguíamos contando como ingreso un cobro que se había
anulado. Ahora las dos filas del par van juntas a la cuarentena.

Las filas rechazadas van a `trips_cuarentena` con la fila original, el archivo del que vienen y
la lista de reglas que violaron. Por mes, el reporte de calidad muestra filas leídas, aceptadas,
en cuarentena y cuántas toca cada regla. La **reconciliación** la hicimos como un test de dbt:
si las leídas no son exactamente aceptadas más cuarentena, el test falla, la capa curada no se
escribe y el pipeline termina con error. Las leídas las tomamos de la tabla cruda y no del
staging, así el control no depende de lo mismo que está controlando. En el estado actual cuadra
en los dos meses:

| Mes | Leídas | Aceptadas | Cuarentena | Diferencia |
| --- | --- | --- | --- | --- |
| 2024-03 | 3.582.628 | 3.496.670 | 85.958 | 0 |
| 2025-03 | 4.145.257 | 4.013.620 | 131.637 | 0 |

## Capa curada

Escribimos la capa curada en `data/curated/yellow/year=AAAA/month=MM/trips.parquet`. Tiene los
viajes aceptados con la duración en minutos, la velocidad media, la fecha, la hora y el día de
la semana de la subida, la propina como porcentaje de la tarifa, y el barrio y la zona de origen
y destino. Las derivadas las calculamos en dbt, para tenerlas junto al resto del SQL y con
tests. La duración la calculamos con la zona horaria de Nueva York: sin eso, el cambio de
horario de marzo les sumaba una hora a más de mil viajes.

Cada mes es un archivo con nombre fijo, que escribimos primero a un temporal y renombramos al
final, así que reprocesar un mes reemplaza solo su archivo. Como lo escribimos siempre en el
mismo orden, la misma entrada da el mismo archivo byte a byte, y eso nos permite comparar
corridas por el hash. Por ejemplo, reprocesamos solo 2024-03: se reescribió el archivo de 2024
y el de 2025 quedó intacto.

```text
antes:   year=2024/month=03  23:17:24  3.496.670 filas  75cce5ab…
         year=2025/month=03  23:17:05  4.013.620 filas  dade5352…
después: year=2024/month=03  23:20:05  3.496.670 filas  75cce5ab…
         year=2025/month=03  23:17:05  4.013.620 filas  dade5352…
```

## Modelo

Armamos el modelo estrella en `sql/modelo/` y escribimos cada pregunta en su propio archivo en
`sql/preguntas/`.

| Tabla | Granularidad |
| --- | --- |
| `fact_trips` | Una fila por viaje aceptado |
| `dim_zone` | Una fila por zona de la TLC (265, incluidas la 264 "Unknown" y la 265 "Outside of NYC") |
| `dim_date` | Una fila por día de cada mes cargado, haya viajes o no |
| `agg_zone_hour` | Una fila por zona de origen, fecha y hora con al menos un viaje |

`dim_date` toma los meses de la ruta del archivo y no de la fecha de subida, porque encontramos
filas con fechas absurdas, como diciembre de 2002. En `agg_zone_hour` guardamos, además de los
promedios, los conteos que hacen falta para ponderarlos, así nadie termina promediando
promedios. A `fact_trips` le agregamos dos columnas, `duracion_confiable` e
`importe_confiable`, que aplican las advertencias a las métricas sin tener que buscar texto en
`flags`.

## Tiempo y memoria

En nuestra máquina (8 núcleos y 14 GB de RAM), `make all MES=2025-03` tardó **6 minutos y 13
segundos** con los datos ya descargados. Desde cero, con la descarga y el entorno nuevo, tarda
unos 14 minutos. Casi todo ese tiempo se lo lleva la evaluación de las reglas de calidad sobre
los 7,7 millones de filas.

Lo medimos con `/usr/bin/time -v`, y el pico de memoria (*Maximum resident set size*) fue de
**691 MiB**. Ese valor es el del proceso más grande y no incluye a Postgres, que corre en Docker:
al contenedor lo medimos aparte con `docker stats` y llegó a 1,48 GiB, contra el tope de
1,5 GiB que le fijamos en `compose.yaml`. En total, el pipeline queda en unos 2,5 GB, con margen
para una notebook de 8 GB. Para lograrlo, cada etapa corre como un proceso aparte que libera su
memoria al terminar, la ingesta lee el archivo de a lotes y DuckDB tiene la memoria acotada.

## Tests

`make test` corre 19 tests de pytest sobre la descarga, la ingesta, la capa curada y la
orquestación. Los tests de dbt, 65 en total, corren dentro de `make all`. Los tres que pide la
consigna son estos:
- **Regla de calidad sobre datos sintéticos:** `reglas_propias_en_el_borde` y los otros unit
  tests de `sql/calidad/calidad.yml` prueban cada umbral justo a un lado y al otro.
- **Idempotencia de la ingesta:** `test_segunda_corrida_no_descarga` y
  `test_saltea_solo_si_hash_y_filas_coinciden`.
- **Reconciliación:** `reconciliacion_detecta_filas_perdidas` arma un mes que cuadra y otro al
  que le falta una fila.

## Limitaciones conocidas

Hay cosas que sabemos que no resolvimos. Que el tipo de pago 0 sea *Flex Fare* y que el
`ratecode_id` 99 sea "desconocido" lo dedujimos de los datos, y nos falta confirmarlo contra el
diccionario de la TLC. Algunos reversos no tienen su cobro original en el mismo archivo, así que
ese cobro sigue contando como ingreso. Los viajes con tarifa negativa (R19) cuentan en el
ingreso total con un importe menor al real, porque no sabemos cuánto se cobró de verdad. En
noviembre, cuando el reloj se atrasa, una hora pasa dos veces y una fecha sin zona horaria no
dice cuál de las dos era; en marzo no pasa.

Del lado del pipeline, nuestra descarga no le pregunta nada al servidor: si la TLC republicara
un mes corregido, no nos daríamos cuenta mientras el archivo local esté entero. Además, dbt
reconstruye todas las tablas en cada corrida. Con dos meses está bien, pero con muchos más
tendríamos que pasar las reglas a modelos incrementales. La lista completa está al final de
`reglas.md`.

## Uso de IA

Usamos Claude Code (Anthropic) como asistente durante todo el proyecto, y los dos le dimos el
mismo uso. Las decisiones las tomamos nosotros: qué herramientas usar, qué severidad y qué
umbral lleva cada regla, cómo responder cada pregunta. Además, auditamos todo lo que hacía.
Claude ejecutaba lo que le pedíamos: escribía código y consultas, corría pruebas y mediciones,
exploraba los datos para verificar cifras y nos ayudaba a redactar la documentación. Cada
cambio pasó por una rama y un pull request que revisó el otro antes de integrarlo, y todo el
código lo podemos explicar.
