# Bitácora de decisiones

Registro de lo hecho y de las decisiones tomadas, con su justificación. Las cifras se dan
como **2025-03 / 2024-03** cuando corresponde.

## Estado al 23/11/2026

| Paso | Estado | Dónde |
| --- | --- | --- |
| 1. Postgres en Compose (credenciales, healthcheck, tuning, tope de memoria) | Hecho | `compose.yaml`, `.env` |
| 2. Entorno Python 3.11 con versiones fijadas | Hecho | `requirements.txt`, `requirements.lock` |
| 3–4. Descarga con hash, log, reintentos y tests | Hecho, 4 tests pasan | `src/pipeline/descarga.py`, `tests/test_descarga.py` |
| 5. Análisis de los dos meses | Hecho | `analisis/exploracion.py`, `reglas.md` |
| 6. Contrato de esquema y comparación | Hecho; el corte del pipeline se conecta en la ingesta | `contracts/yellow_schema.yaml`, `src/pipeline/esquema.py` |
| 7. Prueba de ingesta, midiendo tiempo y RAM | Hecho con PyAirbyte; dlt evaluado | `analisis/prueba_ingesta_resultados.md` y la sección "Herramienta de ingesta" de este archivo |
| 8. Ingesta con dlt de los dos meses y de zonas | Hecho en la rama `dlt` | `src/pipeline/ingesta.py`, `tests/test_ingesta.py` |
| 9. dbt: sources y staging | Hecho | `dbt_project.yml`, `profiles.yml`, `sql/staging/` |
| 10. dbt: reglas, aceptadas, cuarentena y test de una regla | Hecho | `seeds/reglas_calidad.csv`, `sql/calidad/` |
| 11. Reconciliación y reporte de calidad | Hecho | `sql/calidad/reporte_calidad_*.sql`, `tests/dbt/reconciliacion_conteos.sql` |
| 12. Capa curada en Parquet | Hecho | `sql/curada/trips_curados.sql`, `src/pipeline/curada.py`, `tests/test_curada.py` |
| 13. Modelo estrella, tabla agregada y las seis preguntas | Hecho | `sql/modelo/`, `sql/preguntas/`, `RESULTADOS.md` |
| 14. `make all` de punta a punta, dos veces, con los mismos conteos | Hecho | `Makefile`, `.env.example`, `.dlt/config.toml` |
| 16. Orquestación con Dagster | Hecho en la rama `dagster` | `src/orquestacion/definitions.py`, `Makefile`, `tests/test_orquestacion.py` |
| 15. Tiempo y pico de RAM de `make all` en la propia máquina | Hecho en la rama `fix-tarifas` | Sección "Medición de `make all`" de este archivo |
| R19 (tarifa negativa con total positivo) | Hecho en la rama `fix-tarifas` | `seeds/reglas_calidad.csv`, `sql/calidad/`, `sql/modelo/fact_trips.sql`, `sql/preguntas/` |
| 17 en adelante | Pendiente | — |

**Ramas:**
- `master`: diseño original, con PyAirbyte.
- `dlt`: el mismo proyecto, con dlt como herramienta de ingesta. Se abrió a partir de las
  mediciones de la sección "Herramienta de ingesta".
- `dagster`: sale de `dlt` y agrega la orquestación con Dagster (paso 16). Se integra con un
  pull request.

## Términos

- **Descarga:** script propio que baja el archivo de la TLC a `data/raw` sin modificarlo,
  con hash, `ingestion_log` y reintentos (`src/pipeline/descarga.py`).
- **Ingesta:** la herramienta que lleva el Parquet de `data/raw` a Postgres.
- La Parte 1 de la consigna ("Ingesta") la cubren las dos. La tabla de control se llama
  `ingestion_log` porque así la nombra la consigna.

## Infraestructura

### Postgres en contenedor y no instalado en la máquina

- La consigna pide que el repo se pueda clonar y correr de punta a punta con un solo
  comando.
- Con Docker, el único requisito es Docker. El tuning y el tope de memoria viajan en
  `compose.yaml`.
- Con Postgres instalado, quien clone tendría que instalarlo y configurarlo a mano, y eso
  depende del sistema operativo.
- En Linux, Docker no usa una máquina virtual, así que el rendimiento es prácticamente
  igual.
- Igual, el pipeline lee la conexión de `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` y
  `PGPASSWORD`. Para usar un Postgres instalado alcanza con cambiar el `.env`.

### Parámetros de Postgres

| Parámetro | Valor | Por qué |
| --- | --- | --- |
| `mem_limit` | 1,5 GB | Deja margen para Python dentro de 8 GB |
| `shared_buffers` | 384 MB | Una cuarta parte del tope del contenedor |
| `work_mem` | 32 MB | Ordenamientos y joins de las reglas sin desbordar la memoria |
| `maintenance_work_mem` | 128 MB | Creación de índices |

### Memoria compartida del contenedor (`shm_size`)

Docker le da al contenedor 64 MB de `/dev/shm` por defecto. Postgres usa esa memoria para
que varios procesos colaboren en una misma consulta (consultas en paralelo). Un join entre
dos tablas de 7,7 millones de filas la agotó: `could not resize shared memory segment ...
No space left on device`. Se fijó `shm_size: 256m` en `compose.yaml`. Recrear el contenedor
(`docker compose up -d`) no toca los datos, que viven en el volumen `pgdata`.

## Descarga (Parte 1)

- **Idempotente por hash.** Si el archivo existe y su SHA-256 coincide con el último
  registro `ok` de `ingestion_log`, no se vuelve a descargar. La TLC no publica un hash:
  se compara contra el que calculamos y registramos en la descarga anterior.
- **Escritura atómica.** Se descarga a `.part` y se renombra al final, así nunca queda un
  archivo a medias. Si el servidor manda menos bytes que los de `Content-Length`, falla.
- **Reintentos.** Son 3, con esperas de 2, 4 y 8 s. Si se agotan, se registra el error en
  `ingestion_log` y el script termina con código 1.
- **Zonas.** El mismo mecanismo de hash garantiza que la tabla de zonas se descargue una
  sola vez.

## Esquema (Parte 2)

- **El contrato** está en `contracts/yellow_schema.yaml`. Tiene 20 columnas, cada una con
  su nombre de origen, el nombre en snake_case, el tipo en el Parquet (según pyarrow) y el
  tipo en Postgres.
- **Tipos destino:**
  - `smallint` para códigos, conteos e IDs de zona;
  - `numeric(10,2)` para importes y distancia;
  - `timestamp` sin zona horaria;
  - `char(1)` para el flag.
- **`cbd_congestion_fee`** lleva `desde: "2025-01"`, porque el cargo rige desde el
  5/1/2025.
  - Antes de ese mes, que falte es esperado y se carga como nulo. Se usa nulo y no 0
    porque el cargo no existía: 0 diría "se cobró cero".
  - Desde ese mes, que falte es un error.
- **La comparación** está en `src/pipeline/esquema.py` (`comparar_esquema`). Lee solo el
  pie del Parquet y devuelve las columnas faltantes, las nuevas y las de tipo distinto.
- **Qué hace el pipeline con el resultado:**
  - Faltantes o tipos distintos: corta antes de cargar, con código de salida distinto de 0.
  - Columnas nuevas: solo avisa, y la columna no se carga.
- **Comparación de los dos meses:** coinciden en todo, salvo `cbd_congestion_fee`, que no
  existe en 2024.

## Calidad (Parte 3)

El catálogo completo, con condiciones, severidades, umbrales, filas afectadas y evidencia,
está en `reglas.md`. Las consultas que lo sostienen están en `analisis/exploracion.py`.

**Criterio general:**
- **Rechazo:** la fila no es un viaje válido del mes, o un campo que el modelo necesita es
  imposible.
- **Advertencia:** el viaje existió y su importe es válido, pero un atributo es dudoso.

**Decisiones principales:**
- **R03 (bajada igual a la subida): rechazo.** Manda a la cuarentena al 100 % del
  proveedor 7, que es el 0,52 % de 2025.
- **R04 (distancia ≤ 0): advertencia.** Son 103.722 / 87.168 filas, y la mayoría son viajes
  reales: tarifa negociada, Flex Fare o distancia no informada.
- **R05 (más de 500 millas): advertencia.** Todas las filas que la cumplen ya las rechazan
  R16 o R03.
- **R06 (importe negativo): rechazo.** Son reversos del proveedor 2. Su gemela positiva
  queda aceptada (limitación documentada).
- **R09 (zona inexistente): rechazo.** Una clave sin fila en `dim_zone` rompe el modelo
  estrella.
- **Reglas propias:**
  - R16, velocidad mayor a 80 mph.
  - R17, más de 6 h con una tarifa menor a US$ 0,35 por minuto. Es la mitad de lo mínimo
    que cobra el taxímetro: un viaje de más de 6 horas tiene que tener una tarifa acorde.
- **Reprocesar con otro umbral:** los umbrales viven en el catálogo, no en el código. Un
  viaje real que cae en una regla queda en la cuarentena, aparece en el reporte y se puede
  reprocesar.

## Herramienta de ingesta

### PyAirbyte (diseño original, rama `master`)

Medido con un trozo de 500.000 filas de 2025-03, en una máquina de 12 CPU y 14 GiB
(detalle en `analisis/prueba_ingesta_resultados.md`):

| Medida | Valor |
| --- | --- |
| Tiempo por trozo | unos 105 s: 45 s de lectura del conector y 55 s de escritura en Postgres |
| RAM | 1,3 GiB del proceso y 851 MiB del conector |
| Dos meses completos | unos 28 min, en 17 trozos |

- Hay que cortar el archivo en trozos: con un mes entero, el conector llegó a 5 GB de RAM.
- Deja los nombres en minúscula y pegados, y las fechas y los IDs de 32 bits como texto.
  Agrega columnas `_airbyte_*`.

**Variante probada: caché de PyAirbyte en DuckDB más copia a Postgres.** La escritura bajó
de 55 s a 1,7 s y la copia tardó 6,1 s, así que cada trozo quedó en unos 60 s. Los dos
meses tardarían unos 17 min. No se adoptó, porque la lectura del conector sigue costando
lo mismo.

### dlt (rama `dlt`)

Medido en la misma máquina y la misma base, con dlt 1.32.0 y el formato de carga `csv`:

| Medida | PyAirbyte | dlt |
| --- | --- | --- |
| Trozo de 500.000 filas | unos 105 s | 9 s (35 s con `insert_values`) |
| Mes completo de 2025-03 (4.145.257 filas) | unos 15 min, en 9 trozos | **74 s, de una sola vez** |
| RAM del proceso | 1,3 GiB más 851 MiB del conector, por trozo | 858 MiB con el mes entero |
| RAM de Postgres | 258 MiB | 160 MiB |
| Nombres | `pulocationid` | `pu_location_id` |
| Tipos | texto y `numeric` | los del Parquet: `integer`, `bigint`, `double precision` y `timestamptz` |

**Versiones verificadas:** dlt 1.32.0 (publicada el 29/10/2026) y dagster-dlt 0.29.30
resuelven junto con el resto del stack fijado. La rama usa su propio entorno virtual,
`.venv-dlt`.

**Por qué se elige dlt:**
- Trabaja con Arrow de punta a punta: lee el Parquet de a lotes y no serializa cada fila
  como JSON. Eso explica la diferencia de tiempo y de RAM.
- No hace falta cortar el archivo en trozos.
- Conserva los tipos y normaliza los nombres a snake_case, así que el staging queda más
  simple.
- La cátedra lo mencionó en clase como herramienta de ingesta.

**Cómo escribe cada opción en Postgres:**

| | PyAirbyte | dlt `insert_values` | dlt `csv` |
| --- | --- | --- | --- |
| Cómo viajan los datos | Cada fila como JSON, del conector a PyAirbyte | Tablas Arrow por lotes | Tablas Arrow por lotes |
| Archivo intermedio | JSONL, leído con pandas | Sentencias `INSERT` | CSV |
| Comando en Postgres | `INSERT ... VALUES` a una tabla temporal y `INSERT ... SELECT` a la final | `INSERT ... VALUES` | `COPY ... FROM STDIN` |
| 500.000 filas | unos 105 s | 35 s | 9 s |

El propio código de PyAirbyte para Postgres indica que no usa `COPY` e inserta por
valores. Con `insert_values`, dlt usa el mismo mecanismo que PyAirbyte y es igual 3 veces
más rápido, porque evita el paso por JSON y pandas y la doble escritura.

**Decisiones tomadas:**
- **Formato de carga `csv` por defecto.** Se puede pasar a `insert_values` sin tocar el
  código, con la variable de entorno `INGESTA_FORMATO`. Así, si se objeta el uso interno
  de `COPY`, el cambio es inmediato.
- **Fechas sin zona horaria.** Las columnas de fecha se configuran en dlt con
  `timezone: False`, así la tabla cruda queda con `timestamp`, igual que el Parquet.
- **"N/A" de zonas como texto.** El CSV de zonas se lee sin tomar "N/A" como nulo, así la
  tabla queda idéntica a la publicada por la TLC.

### Ingesta implementada (`src/pipeline/ingesta.py`)

Se corre con `python -m pipeline.ingesta --mes AAAA-MM [--forzar]`. Hace esto, en orden:

1. Compara el esquema contra el contrato. Si hay columnas faltantes o tipos distintos,
   registra el error en `ingestion_log` y sale con código 1. Si hay columnas nuevas, solo
   avisa.
2. Se saltea si el último registro `ok` de la etapa `ingesta` para ese archivo tiene el
   mismo hash **y** la base tiene todas sus filas. `--forzar` reingiere de todos modos.
3. Lee el Parquet de a lotes de 100.000 filas, toma solo las columnas del contrato y las
   renombra a su nombre destino. Completa `cbd_congestion_fee` con nulos cuando el mes es
   anterior a su `desde` y agrega `source_file`, la ruta relativa del archivo.
4. Carga en `raw.yellow_trips` con `merge` y la estrategia `delete-insert` por
   `source_file`, así reprocesar un mes reemplaza solo sus filas. Las zonas van a
   `raw.taxi_zones` con `replace`.
5. Reconcilia: las filas de ese archivo en la base tienen que ser iguales a las del
   archivo. Si no, registra el error y sale con código 1.
6. Registra la ingesta en `ingestion_log`, con `etapa = 'ingesta'`.

`ingestion_log` tiene una columna `etapa` (`descarga` o `ingesta`), así un único registro
de control cubre toda la Parte 1. La URL queda vacía para la ingesta.

**Verificado:**

| Prueba | Resultado |
| --- | --- |
| Ingesta de 2025-03 (`csv`) | 75 s; 4.145.257 filas |
| Ingesta de 2024-03 (`csv`) | 73 s; 3.582.628 filas; `cbd_congestion_fee` nulo |
| Total en `raw.yellow_trips` | 7.727.885 filas |
| Segunda corrida de 2025-03 | Se saltea en 3 s |
| Reproceso forzado de 2025-03 | La huella (md5 de todas las filas) de 2024 y de 2025 no cambia |
| Reproceso de 2024-03 con `insert_values` | 199 s; huella idéntica a la de `csv` |
| Fechas | `timestamp` sin zona horaria; la mínima de 2024, 2002-12-31 22:17:10, coincide con la del Parquet |
| Zonas | 265 filas; 264 y 265 conservan "N/A" |
| Tests | 4 de descarga y 4 de ingesta: decisión de salteo, renombre y columna faltante, corte por esquema y aviso por columna nueva |

**Pendientes del diseño con dlt:**
- **Medición (resuelto en el paso 15).** Ver la sección "Medición de `make all`".
- **Tabla intermedia de dlt (resuelto en el paso 14).** El merge dejaba
  `raw_staging.yellow_trips` con el último mes cargado (3.582.628 filas, 859 MB). Ahora dlt
  la vacía al terminar cada carga, con `truncate_staging_dataset = true` en
  `.dlt/config.toml`.

## Transformación con dbt

### Proyecto (paso 9)

- **`dbt_project.yml` y `profiles.yml` en la raíz.** dbt busca `profiles.yml` primero en
  la carpeta desde donde se corre, así que alcanza con correrlo desde la raíz del repo. Los
  modelos están en `sql/` y los seeds en `seeds/`, como pide la estructura objetivo.
- **Credenciales.** `profiles.yml` lee cada dato de conexión con `env_var('PG...')`. No
  tiene ningún valor escrito, por eso se puede subir. dbt no lee el `.env`: las variables
  tienen que estar cargadas en el entorno (`set -a; . ./.env; set +a`).
- **Esquemas.** dbt escribe todo en `analytics`. `raw` es de la ingesta: dbt solo lo lee,
  a través de las sources declaradas en `sql/staging/sources.yml`.
- **`threads: 2`.** Pocos modelos en paralelo, por el tope de memoria del contenedor.
- **`.user.yml`.** Es un identificador anónimo que crea dbt. Está en el `.gitignore`.

Se corre así: `set -a; . ./.env; set +a; .venv-dlt/bin/dbt run` (o `dbt test`).

### Staging (paso 9)

El staging solo renombra y convierte tipos: no limpia ni filtra.

- **`stg_taxi_zones`** (vista). `location_id` pasa a `smallint`. Entran las 265 zonas, con
  "N/A" incluido. Tiene tests `unique` y `not_null` sobre `location_id`.
- **`stg_yellow_trips`** (tabla). Se materializa como tabla porque las reglas lo leen
  varias veces y con una vista el md5 de 7,7 millones de filas se recalcularía en cada
  lectura.
  - **Tipos destino.** `smallint` para códigos, pasajeros y zonas; `numeric(10,2)` para
    distancia e importes; `char(1)` para el flag; las fechas quedan `timestamp` y se
    renombran a `pickup_at` y `dropoff_at`. Antes de fijarlos se midieron los máximos: la
    distancia más grande es 320.136,29 y el importe más grande 46.269,44, que entran en
    `numeric(10,2)` (hasta 99.999.999,99).
  - **`row_hash` = `md5(t::text)`.** Es el texto de la fila cruda completa, `source_file`
    incluido. Se calcula sobre los valores crudos, antes de convertir tipos: si se calculara
    después de redondear a dos decimales, dos filas que difieren en el tercer decimal
    quedarían como duplicadas sin serlo. No se usa `concat_ws` porque saltea los nulos y
    `(NULL, 1)` y `(1, NULL)` darían el mismo texto; en el texto de la fila un nulo queda
    como un campo vacío en su lugar.
  - **`dup_n` = `row_number() over (partition by row_hash)`.** Numera las copias de una
    misma fila. No necesita orden: las copias son idénticas, así que cualquier orden da el
    mismo resultado. `dup_n` > 1 es un duplicado exacto (R11).
  - **`trip_id` = `md5(row_hash || '-' || dup_n)`.** El guion evita que la concatenación
    sea ambigua.

**Verificado:**

| Prueba | Resultado |
| --- | --- |
| `dbt debug` | Encuentra los dos archivos y conecta solo con las variables `PG*` |
| `stg_taxi_zones` | 265 filas, 265 `location_id` distintos, `smallint`; pasan `unique` y `not_null` |
| Filas de `stg_yellow_trips` | 7.727.885, las mismas que `raw.yellow_trips` |
| `trip_id` | 7.727.885 distintos; pasan `unique` y `not_null` |
| Duplicados exactos | 0, igual que en el análisis (R11 en `reglas.md`) |
| Por mes | 2024: 3.582.628 filas, `cbd_congestion_fee` nulo en todas; 2025: 4.145.257, con valor en todas |
| Tiempo | 74 s |
| Tamaño | 1,96 GB |
| Segunda corrida | Huella de los `trip_id` idéntica (`e28af7cade13988a7cafecdf7b7e0bc9`) |

**Disco.** Con el staging, Postgres ocupa unos 5,6 GB: 2,8 GB de crudo, 0,86 GB de la
tabla intermedia de dlt y 1,96 GB de staging. Faltan las tablas de calidad y el modelo.

### Calidad (paso 10)

- **El catálogo es un seed** (`seeds/reglas_calidad.csv`): `id`, `descripcion`,
  `severidad`, `umbral`, `umbral_2` y `unidad`. Los umbrales (R05: 500 mi; R16: 80 mph;
  R17: 360 min y US$ 0,35 por minuto) y las severidades se leen de ahí. Cambiar un umbral o
  pasar una regla de advertencia a rechazo es editar el CSV y correr `dbt seed` y
  `dbt run`, sin tocar el SQL. Tiene tests: `id` único y no nulo, y `severidad` solo
  `rechazo` o `advertencia`.
- **`int_calidad` (tabla)** evalúa las 17 reglas sobre cada viaje del staging. Cada regla
  devuelve su id si se cumple; después se reparten según la severidad del catálogo en
  `reglas_rechazo` y `flags`. Se materializa como tabla porque es el cálculo más pesado y
  así se hace una vez.
  - El mes del archivo, para R01, sale de la ruta en `source_file` (`year=AAAA/month=MM`).
  - R09 cruza origen y destino con `stg_taxi_zones`.
  - R16 calcula la velocidad solo si la duración y la distancia son positivas: Postgres no
    garantiza el orden en que evalúa un `AND`, así que un `CASE` evita dividir por cero.
- **`reglas_rechazo` y `flags` son texto separado por comas** (`R06,R16`), vacío si no
  hay reglas. Se probó primero con listas (`text[]`), pero dbt-postgres lee el tipo de esas
  columnas como `ARRAY` y los unit tests no pueden comparar valores. El texto, además, se
  lee directo en el reporte. Para contar por regla: `unnest(string_to_array(flags, ','))`.
- **`trips_aceptados` (vista)**: `reglas_rechazo = ''`. Es vista para no duplicar 2 GB.
- **`trips_cuarentena` (tabla)**: `reglas_rechazo <> ''`. Guarda la fila del staging (que
  solo convierte tipos, así que es la fila del archivo), su `source_file`, las reglas de
  rechazo violadas y las advertencias que también cumple.
- **Test de reglas con datos sintéticos**: dos *unit tests* de dbt sobre `int_calidad`
  (`sql/calidad/calidad.yml`), con filas inventadas y sin leer los datos reales:
  - `reglas_propias_en_el_borde`: 80 mph exactos no rechaza y 80,08 sí; 361 min con
    US$ 126,35 (0,35 × 361) no rechaza y con un centavo menos sí; 360 min exactos no
    superan la duración máxima; 59 s marca R18 y 60 s no.
  - `severidad_se_lee_del_catalogo`: con R16 como advertencia en el catálogo, el mismo
    viaje pasa de rechazo a flags. Este test encontró un bug: si ninguna regla del catálogo
    era de rechazo, `array_agg` daba nulo y las reglas violadas se perdían. Se corrigió con
    `coalesce(..., '{}')`.

**Verificado:**

| Prueba | Resultado |
| --- | --- |
| Conteo por regla | Igual a la columna "Filas" de `reglas.md` en las 17 reglas (R09, R11, R13 y R14 dan 0) |
| Aceptadas + cuarentena | 7.585.903 + 141.982 = 7.727.885, sin filas en las dos |
| Cuarentena por mes | 2025: 93.387; 2024: 48.595 |
| Combinaciones más frecuentes | R06: 112.942; R03: 23.202; R17: 3.271; R16: 2.258; R02: 198; R01: 55 |
| Tiempo | `int_calidad` 206–238 s; `trips_cuarentena` 13–14 s |
| Tamaño | `int_calidad` 2,0 GB; `trips_cuarentena` 37 MB |
| Dos corridas | Huella de `trip_id`, `reglas_rechazo` y `flags` idéntica (`e0d63d051bc442675574041210bfc142`) |
| `dbt test` | 16 tests pasan, los 2 unit tests incluidos |

**Pendiente:** `int_calidad` tarda unos 4 minutos, el doble que la prueba sintética del
diseño original. Medido en el paso 15: el pipeline completo entra holgado en 8 GB, así que
no se optimizó.

### Reporte de calidad y reconciliación (paso 11)

- **`reporte_calidad_mes` (tabla)**: una fila por mes con filas leídas, aceptadas, en
  cuarentena, el porcentaje en cuarentena y la `diferencia` (leídas − aceptadas −
  cuarentena). Las **leídas salen de `raw.yellow_trips`**, no del staging: la tabla cruda ya
  se reconcilió contra el Parquet en la ingesta, así que el control compara contra una
  fuente independiente de lo que hace dbt. La cadena completa queda: Parquet = crudo (en la
  ingesta) y crudo = aceptadas + cuarentena (en dbt).
- **`reporte_calidad_reglas` (tabla)**: filas por regla y por mes, con la severidad y el
  porcentaje sobre las leídas. Cruza los meses con el catálogo, así aparecen las 17 reglas
  aunque alguna no tenga casos (0).
- **La reconciliación corta el pipeline**: `tests/dbt/reconciliacion_conteos.sql` es un
  test de dbt que devuelve los meses con `diferencia` distinta de 0. Si devuelve alguna
  fila, `dbt test` (o `dbt build`) falla y sale con código distinto de 0, y `make` se
  detiene.
- **Test con datos sintéticos** (`reconciliacion_detecta_filas_perdidas`, unit test): un mes
  con 3 leídas, 2 aceptadas y 1 en cuarentena da diferencia 0; otro con 2 leídas y solo 1
  aceptada da diferencia 1. Es el test obligatorio de reconciliación de conteos.
- **`test-paths: ["tests"]`**: los tests de datos de dbt están en `tests/dbt/`. dbt lee solo
  los `.sql` de `tests/` y pytest solo los `.py`. No pueden ir dentro de `sql/`: al ser la
  carpeta de modelos, dbt los tomaría como modelos (pasó en la primera prueba y creó una
  vista `analytics.reconciliacion_conteos`).

**Verificado:**

| Mes | Leídas | Aceptadas | Cuarentena | % cuarentena | Diferencia |
| --- | --- | --- | --- | --- | --- |
| 2024-03 | 3.582.628 | 3.534.033 | 48.595 | 1,36 | 0 |
| 2025-03 | 4.145.257 | 4.051.870 | 93.387 | 2,25 | 0 |

Los conteos por regla de `reporte_calidad_reglas` son los de `reglas.md`. Los dos reportes
se construyen en 6 s. `dbt test`: 20 tests pasan; pytest: 8.

## Capa curada (Parte 4, paso 12)

- **Las columnas derivadas se calculan en dbt** (`sql/curada/trips_curados.sql`, vista sobre
  `trips_aceptados`): quedan junto al resto del SQL y tienen tests. DuckDB solo lee y
  escribe. La vista agrega:
  - `duracion_min`, `velocidad_mph` (nula si la duración no es positiva; en las aceptadas no
    pasa, porque R02 y R03 rechazan), `fecha`, `hora` y `dia_semana` de la subida (ISO:
    1 = lunes, 7 = domingo).
  - `propina_pct` = 100 × `tip_amount` / `fare_amount`, nula si la tarifa no es positiva.
  - `pu_borough`, `pu_zone`, `do_borough` y `do_zone`, de `stg_taxi_zones`.
  - Las derivadas son `numeric(10,2)`, como la distancia y los importes. El cast va afuera
    del `CASE`: adentro, Postgres pierde los decimales fijados y el Parquet las recibía como
    `double`.
- **La propina solo es interpretable con tarjeta.** En las aceptadas, la propina promedio es
  US$ 4,28 con tarjeta (`payment_type` 1) y US$ 0,00 en efectivo (2): el taxímetro no
  registra la propina en efectivo. Hay valores extremos (hasta 700.000 %) cuando la tarifa
  es de centavos. Las preguntas sobre propina tienen que filtrar por tarjeta.
- **`src/pipeline/curada.py --mes AAAA-MM`** conecta DuckDB a Postgres con la extensión
  `postgres` (`ATTACH ''`: libpq toma las variables `PG*` del entorno, en solo lectura),
  filtra la vista por el `source_file` del mes y escribe
  `data/curated/yellow/year=AAAA/month=MM/trips.parquet`:
  - **Nombre de archivo fijo** y escritura a un `.tmp` que se renombra al final: reprocesar
    un mes reemplaza solo su archivo y, si algo falla, el anterior queda intacto.
  - **`ORDER BY pickup_at, trip_id`**: el orden fijo hace que la misma entrada dé siempre el
    mismo archivo, byte a byte.
  - **`year` y `month` no van dentro del archivo**: salen de la ruta (estilo Hive). DuckDB
    los agrega al leer con `hive_partitioning`.
  - **Reconciliación**: las filas del Parquet escrito tienen que ser las `filas_aceptadas`
    del mes en `reporte_calidad_mes`. Si no, sale con código 1.
  - La extensión `postgres` de DuckDB se descarga de internet la primera vez (`INSTALL`) y
    queda en `~/.duckdb/extensions`.
- **Memoria de DuckDB.** `memory_limit` acota los datos que maneja DuckDB, no el proceso
  entero. Medido con 2025-03:

  | `memory_limit` | Hilos | RAM pico | Tiempo |
  | --- | --- | --- | --- |
  | 1,5 GB | todos (12) | 2.227 MiB | 16 s |
  | 1 GB | 4 | 1.385 MiB | 18 s |
  | 1 GB | 2 | 1.346 MiB | 18 s |
  | **512 MB** | **2** | **738 MiB** | **22 s** |

  Se eligió 512 MB y 2 hilos. El archivo salió idéntico (mismo sha256) con las cuatro
  configuraciones. Lo que no entra en memoria va a `data/tmp/duckdb`.
- **Test** (`tests/test_curada.py`): con una tabla de DuckDB en memoria escribe dos meses,
  cambia los datos de uno y lo reprocesa. Verifica que el otro archivo tiene el mismo
  sha256 y que no quedan temporales.

**Verificado:**

| Prueba | Resultado |
| --- | --- |
| 2025-03 | 4.051.870 filas (= aceptadas), 22 s, 152 MB |
| 2024-03 | 3.534.033 filas (= aceptadas), 19 s, 131 MB |
| Reproceso de 2025-03 y luego de 2024-03 | Los dos archivos conservan su sha256 (2024 `f61f8171…`, 2025 `66e6e9ff…`); los conteos por partición no cambian |
| Tipos en el Parquet | Importes, distancia y derivadas `DECIMAL(10,2)`; códigos `SMALLINT`; `fecha` `DATE` |
| Tests | `trips_curados`: `trip_id` único y no nulo, `dia_semana` entre 1 y 7. pytest: 9 |

### R18: duración menor a 1 minuto (agregada después del paso 12)

R02 y R03 cubrían la duración negativa y la nula, pero ninguna regla miraba la duración
positiva y muy corta: unos 35.000 viajes aceptados por mes de menos de 1 minuto. Se agregó
**R18, advertencia, umbral 60 s** en el catálogo. Evidencia y justificación en `reglas.md`.

- Cambió el seed, una línea de `int_calidad` y el unit test (`reglas_propias_en_el_borde`:
  59 s marca R18, 60 s no). Se reconstruyó la calidad (259 s) y la capa curada.
- La cuarentena no cambia (141.982), porque es una advertencia. R18 marca 43.216 / 39.531
  filas, de las que 35.135 / 32.514 quedan aceptadas, con US$ 1,45 / 1,31 millones.
- **Regla para el paso 13:** las métricas de duración y velocidad excluyen las filas con
  R18; las de ingreso las incluyen.
- `dbt test`: 21 tests pasan. Huellas nuevas de la capa curada: 2024 `db3c1e4d…`, 2025
  `eb25f5cf…` (cambian porque la columna `flags` cambió).


### R19: tarifa negativa con total positivo (agregada después del paso 16)

El informe de corrección señaló que los viajes con `fare_amount` negativo y `total_amount`
positivo bajaban la tarifa media de la pregunta f. Ninguna regla los miraba: R06 solo ve el
total. Se agregó **R19, advertencia, umbral 0** en el catálogo. Evidencia y justificación en
`reglas.md`.

- Cambiaron el seed y una línea de `int_calidad`, y hay un unit test nuevo
  (`r19_tarifa_negativa_con_total_positivo`): tarifa −1 con total 5 marca R19; tarifa 0 con
  total 5 y tarifa −1 con total 0 no; tarifa −1 con total −5 lo rechaza R06, sin R19.
- La cuarentena no cambia, porque es una advertencia. R19 marca 140.446 / 14.295 filas, de las
  que 140.403 / 14.291 quedan aceptadas. Todas son del proveedor 2 con `payment_type` 0.
- **Regla para las preguntas:** `fact_trips` suma `tarifa_confiable` (falso si el viaje tiene
  R19), igual que `duracion_confiable` para R18. Los promedios de `fare_amount` (preguntas e y
  f) usan solo los verdaderos; los conteos y el ingreso, todos. La d no cambia: ya filtra
  `fare_amount` > 0.
- Efecto: en f, la tarifa media pasa de 19,17 → 18,47 (−3,66 %) a 19,26 → 19,29 (+0,16 %).
  En e, JFK 2025 pasa de 64,15 a 64,18 y el total de 2025, de 55,16 a 55,18 (83 viajes).
- **Calendario (pregunta a):** los dos marzos tienen 5 sábados y 5 domingos, así que no hay un
  fin de semana de más. 2025 tiene 5 lunes y 2024, 5 viernes, lo que juega en contra de 2025.
  Por día, los sábados y domingos crecen +21 % y +22 %, y el resto de la semana entre +10 % y
  +16 %.
- Huellas nuevas de la capa curada (cambian porque cambió la columna `flags`): 2024
  `ea6554d1…`, 2025 `361e1449…`.

## Modelo y preguntas (Parte 5, paso 13)

### Modelo estrella (`sql/modelo/`, tablas)

| Tabla | Granularidad | Clave | Origen |
| --- | --- | --- | --- |
| `dim_zone` | una fila por zona de la TLC (265, con 264 y 265) | `location_id` | `stg_taxi_zones` |
| `dim_date` | una fila por día de cada mes cargado, haya viajes o no | `fecha` | meses de `source_file` |
| `fact_trips` | una fila por viaje aceptado | `trip_id` | `trips_curados` |
| `agg_zone_hour` | una fila por zona de origen, fecha y hora con al menos un viaje | las tres columnas | `fact_trips` |

- **`dim_zone` no filtra 264 ni 265:** R10 es advertencia y hay viajes aceptados que las usan;
  sin ellas fallaría el test de relación de `fact_trips`.
- **`dim_date` saca los meses de la ruta del archivo** y no de `pickup_at`, porque las filas de
  R01 traen fechas de otros meses (como 2002-12). `nombre_dia` sale de un arreglo y no de
  `to_char`, que depende del idioma del servidor.
- **`fact_trips` es angosta:** claves, atributos del viaje, medidas y `flags`. Los nombres de
  zona viven en `dim_zone` y los atributos de la fecha en `dim_date`. Agrega
  `duracion_confiable` (falso si el viaje tiene R18), así la regla del paso 12 se aplica con
  una columna y no buscando texto en `flags`.
- **`agg_zone_hour`:** `viajes` e `ingreso_total` (suma de `total_amount`) cuentan todos los
  viajes; `duracion_media_min` promedia solo los de `duracion_confiable` (nula si todos son
  R18). `viajes_con_duracion` permite ponderar al agregar varias horas, en lugar de promediar
  promedios.
- **Tablas completas, no incrementales:** con dos meses se reconstruyen en segundos y son
  idempotentes sin lógica extra.
- **Tests:** claves únicas y no nulas; `relationships` de `fact_trips` y `agg_zone_hour` hacia
  las dos dimensiones; `tests/dbt/agg_zone_hour_cuadra_con_fact.sql` falla si la suma de
  viajes o de ingreso de la agregada difiere de `fact_trips`.

### Preguntas (`sql/preguntas/`, una tabla por pregunta)

- **El mes asignado llega como variable de dbt:** `--vars '{mes: "2025-03"}'`. La comparación
  es el mismo mes del año anterior. No tiene valor por defecto: sin la variable, las preguntas
  no compilan (`Required var 'mes' not found`) y el resto del proyecto sigue funcionando.
- **`tests/dbt/meses_de_preguntas_cargados.sql`** falla si alguno de los dos meses no está en
  `dim_date`; sin ese control, las preguntas darían tablas vacías sin avisar.
- Cada pregunta repite la CTE `meses`, así cada archivo se lee solo y se copia tal cual a
  `RESULTADOS.md`. Leen las dimensiones para separar los meses (`dim_date`) y para los nombres
  de zona (`dim_zone`).
- **c:** solo entran zonas con al menos 100 viajes en el mes. Sin mínimo, encabezan Rikers
  Island (2 viajes) y Arden Heights (1) al 100 %; con cualquier mínimo entre 3 y 35.000 el
  top 5 es el mismo.
- **d:** se muestran el promedio del porcentaje por viaje y el total de propinas sobre el total
  de tarifas, porque hay porcentajes de hasta 700.000 % con tarifas de centavos.
- **e:** los aeropuertos se identifican por `zone` (`JFK Airport`, `LaGuardia Airport`). Un
  viaje entre los dos cuenta en cada uno y una sola vez en el total.

**Verificado:**

| Prueba | Resultado |
| --- | --- |
| `fact_trips` | 7.585.903 filas (= aceptadas), 3.534.033 / 4.051.870 por año; 67.649 con R18; 11 s; 1.212 MB |
| `agg_zone_hour` | 211.390 filas; `sum(viajes)` y `sum(ingreso_total)` iguales a `fact_trips`; 3,7 s; 16 MB |
| `dim_date` | 62 días; el 1/3/2024 viernes y el 1/3/2025 sábado |
| Preguntas b, c y e | Iguales a consultas independientes sobre `fact_trips` con los ID de zona |
| Sin `mes` / con `mes` 2025-04 | No compila / el test de meses falla con código 1 |
| `dbt build --vars '{mes: "2025-03"}'` | 60 de 60, 393 s |
| Dos corridas del modelo y las preguntas | Las 10 tablas con la misma huella md5 |

**Disco.** `fact_trips` suma 1,2 GB; la base queda en unos 8,9 GB.

## Comando único (paso 14)

`make all MES=2025-03` corre todo para el mes asignado y el mismo mes del año anterior
(`MES_COMP`, calculado en el `Makefile`):

```text
revisar-mes, postgres, entorno -> descarga -> ingesta -> transformacion (dbt build) -> curada
```

- **Make corta en el primer comando con código distinto de 0.** Como los scripts y dbt ya
  salen con error ante fallas (reintentos agotados, contrato, reconciliación), el pipeline
  se detiene donde falla: si la reconciliación de dbt no cierra, no se escribe la curada.
- **`MES` es obligatorio y se valida** (`AAAA-MM`, mes de 01 a 12) antes de ejecutar nada.
- **`postgres`**: `docker compose up -d --wait` levanta el contenedor y espera el
  healthcheck; si ya está corriendo, no hace nada.
- **Clon nuevo con un solo comando:**
  - Si no hay `.env`, Make copia `.env.example` y avisa. Las credenciales del ejemplo son
    solo para el Postgres del contenedor, que escucha en 127.0.0.1. `.env.example` también
    documenta `INGESTA_FORMATO`.
  - Si no existe el entorno virtual, Make lo crea con `python3.11 -m venv` e instala
    `requirements.lock`. El intérprete se cambia con `PYTHON_BASE=...`. Requisitos para
    quien clone: Docker, Make y Python 3.11.
- **`transformacion` es un solo `dbt build --vars '{mes: "..."}'`**: corre el seed, los
  modelos y los tests en orden de dependencias, así que no hace falta un `dbt seed` aparte.
- **`make conteos MES=...`** muestra el reporte de calidad por mes, las filas de `fact_trips`
  por mes y el sha256 de cada archivo curado: es lo que se compara entre dos corridas.
- **`make test`** corre pytest. Los tests de dbt ya corren dentro de `make all`.
- **Tabla intermedia de dlt:** `.dlt/config.toml` activa `truncate_staging_dataset`. Al
  reingerir 2024-03, `raw_staging.yellow_trips` pasó de 859 MB a 8 kB y `raw` conservó sus
  filas.

**Verificado:**

| Prueba | Resultado |
| --- | --- |
| `make all` sin `MES` o con `MES=2025-13` | Corta con el mensaje, antes de ejecutar nada |
| Sin `.env` (carpeta aparte) | Copia `.env.example`, avisa y sigue; la segunda vez no hace nada |
| Entorno nuevo desde `requirements.lock` (carpeta aparte, Python 3.11) | 43 s; importa dlt 1.32.0, dbt 1.12.7, duckdb 1.4.3; la segunda vez no se rehace |
| `make all MES=2025-03`, corrida 1 | Código 0, 507 s (dbt 457 s, 60 de 60) |
| `make all MES=2025-03`, corrida 2 | Código 0, 493 s (dbt 441 s, 60 de 60) |
| Descarga e ingesta en las dos corridas | Se saltean por hash, en segundos |
| Conteos antes, después de la corrida 1 y después de la 2 | Idénticos: leídas 3.582.628 / 4.145.257; aceptadas 3.534.033 / 4.051.870; cuarentena 48.595 / 93.387; diferencia 0 |
| Archivos curados | Mismo sha256 en las tres tomas: 2024 `db3c1e4d…`, 2025 `eb25f5cf…` |
| `make test` | 9 pasan |

Casi todo el tiempo de una corrida es `dbt build`, y dentro de él `int_calidad` (unos 4
minutos). El tiempo y el pico de RAM están en la sección "Medición de `make all`" (paso 15).

## Orquestación con Dagster (paso 16)

`make all MES=2025-03` prepara el entorno y le pasa la corrida a Dagster:

```text
make: revisar-mes, postgres, entorno, dbt parse -> dagster asset materialize --select '*'
Dagster: descarga -> raw/yellow_trips y raw/taxi_zones -> modelos de dbt -> curada
```

Las definiciones están en `src/orquestacion/definitions.py`.

### Qué hace Make y qué hace Dagster

- **Make prepara; Dagster ejecuta.** Make sigue creando `.env` y el entorno virtual, levanta
  Postgres (`docker compose up -d --wait`) y genera el manifiesto de dbt. Levantar el contenedor
  es infraestructura y no un dato, por eso no es un asset. Las cuatro etapas de datos las corre
  Dagster, en una sola corrida.
- **Make ya no encadena las etapas.** Se sacaron los objetivos `descarga`, `ingesta`,
  `transformacion` y `curada` y el cálculo de `MES_COMP`. Para correr una sola etapa se usa
  Dagster: `dagster asset materialize -m orquestacion.definitions --select descarga
  --config-json ...`.
- **`dagster asset materialize` y no `dagster job execute`.** En Dagster 1.13, `job execute` solo
  recibe la configuración en un archivo (`-c`) y no como texto. `asset materialize` acepta
  `--config-json` y, si la corrida falla, sale con código 1, igual que `job execute`. Avisa que
  está reemplazado por `dg launch`, pero `dg` es otro paquete (`dagster-dg-cli`) que no está en
  el stack fijado.
- **`dbt parse` en cada `make all`.** dagster-dbt arma un asset por modelo leyendo
  `target/manifest.json`, que no está en Git. `dbt parse` no se conecta a la base y tarda unos
  segundos. Se corre siempre, así el manifiesto no queda viejo si cambia un modelo. Se verificó
  que compila sin la variable `mes`: al parsear, dbt toma como nula una variable que falta y la
  exige recién al compilar.
- **`DAGSTER_HOME=dagster_home/`.** Dagster guarda ahí las corridas y sus logs, que están en el
  `.gitignore`. Make crea un `dagster.yaml` vacío: sin él, Dagster avisa en cada corrida que usa
  la configuración por defecto. El run id y las fechas de corrida quedan solo ahí, nunca en los datos.
- **`make ui`** levanta la interfaz de Dagster (`dagster dev`) en http://localhost:3000, con el
  grafo de assets y el historial de las corridas de `make all`.

### Cómo se pasa el mes

Se evaluaron tres opciones:

| Opción | A favor | En contra |
| --- | --- | --- |
| **Configuración de la corrida (elegida)** | Una corrida y un comando; el mes se valida y el de comparación se calcula en un solo lugar | La interfaz agrupa por corrida, no por mes |
| Particiones mensuales (`2024-03` y `2025-03` por separado) | Cada mes materializado por separado en la interfaz | dbt reconstruye tablas completas y las preguntas necesitan los dos meses a la vez, así que no puede ser una partición. Como Dagster no mezcla particiones distintas en una corrida, serían unas 5 corridas encadenadas por Make. Además, la dependencia con el año anterior pide una `PartitionMapping` propia |
| Partición con el mes asignado como clave | Historial por mes asignado | La partición `2025-03` también escribiría 2024-03: una partición dejaría de ser una porción de datos separada de las demás |

- **El recurso `periodo`** (`Periodo`, un `ConfigurableResource`) tiene un solo campo, `mes`. Se
  pasa al lanzar la corrida:
  `--config-json '{"resources": {"periodo": {"config": {"mes": "2025-03"}}}}'`.
  Se usa un recurso y no la configuración de cada asset para no repetir el mes cuatro veces.
- **Valida el mes al iniciar la corrida** (`setup_for_execution`), con la misma expresión que
  `revisar-mes`. Un mes inválido corta antes de ejecutar cualquier asset.
- **`mes_comp`** es el mismo mes del año anterior (2025-03 → 2024-03). Cada asset procesa los
  dos meses en el mismo orden que el Makefile del paso 14: primero el asignado, después el de
  comparación.
- **El mes no entra en los datos por Dagster.** Llega a los scripts como `--mes` y a dbt como
  `--vars`, igual que antes. Por eso cada salida sigue dependiendo solo del mes, del archivo
  crudo, del contrato y de las reglas.

### Assets

| Asset | Qué ejecuta | Depende de |
| --- | --- | --- |
| `descarga` | `python -m pipeline.descarga --mes X`, para los dos meses | — |
| `raw/yellow_trips`, `raw/taxi_zones` | `python -m pipeline.ingesta --mes X`, para los dos meses | `descarga` |
| modelos de dbt (19: seed, staging, calidad, curada, modelo y preguntas) | `dbt build --vars '{"mes": "..."}'` | `raw/yellow_trips` y `raw/taxi_zones` |
| `curada` | `python -m pipeline.curada --mes X`, para los dos meses | `trips_curados` y `reporte_calidad_mes` |

- **Las etapas propias corren como subproceso**, con el Python del mismo entorno. No se cambió
  ninguna línea de `descarga.py`, `ingesta.py` ni `curada.py`: siguen haciendo su validación de
  contrato, el salteo por hash, la reconciliación y el registro en `ingestion_log`. Si el script
  sale con código distinto de 0, el asset lanza `dagster.Failure` con ese código.
  - Además, como cada etapa es su propio proceso, la memoria de dlt y de DuckDB se libera al
    terminar.
- **No se usa dagster-dlt.** Su `@dlt_assets` ejecuta el pipeline de dlt directamente y
  saltearía la lógica propia de `ingesta.py` (contrato, salteo por hash, reconciliación,
  `ingestion_log`). Usarlo obligaba a partir el script en piezas, y no se agregó la dependencia
  para no tener un paquete sin uso.
- **Las claves `raw/yellow_trips` y `raw/taxi_zones` coinciden con las sources de dbt.**
  dagster-dbt les pone a las sources la clave `[source, tabla]`, así que el staging queda
  conectado a la ingesta sin traductor y el grafo muestra la cadena completa.
- **dbt con dagster-dbt** (`@dbt_assets`): es un solo `dbt build`, como en el paso 14. Los 38
  tests de datos y los 3 unit tests corren dentro. Los tests sobre un modelo aparecen en Dagster
  como asset checks; los singulares que cruzan varios modelos (la reconciliación, por ejemplo)
  aparecen como observaciones.
- **Si falla un test de dbt, la corrida falla.** dbt sale con código 1, dagster-dbt lanza un
  error, `curada` no se ejecuta, la corrida queda fallida y `make` sale con código distinto de 0.
- **Metadata.** `descarga` y `curada` registran, para cada mes, las filas y el sha256 del
  archivo, así la interfaz muestra la huella de cada corrida.
- **Un paso por vez.** `in_process_executor` en `Definitions`: los pasos corren de a uno y en el
  mismo proceso, para toda corrida (`make all`, el job `pipeline_mes` y la interfaz).

### Dependencias

- **`dagster-dbt==0.29.30`** se agregó a `requirements.txt`. El lock se regeneró sobre el entorno
  ya instalado desde el lock anterior, así pip no movió ninguna versión. Solo se agregaron
  `dagster-dbt` y sus dependencias nuevas: `annotated-doc`, `shellingham`, `sqlglotc`,
  `sqlglotrs` y `typer`.
- **`psycopg[binary]==3.3.9`** (agrega `psycopg-binary==3.3.9`, la misma versión). Sin la
  variante binaria, psycopg necesita la librería `libpq` instalada en el sistema. En una máquina
  sin ella, `pipeline.descarga` fallaba al importarse, con o sin Dagster. Así se mantiene que
  quien clone solo necesita Docker, Make y Python 3.11. dbt ya usaba `psycopg2-binary` por el
  mismo motivo.

### Tests (`tests/test_orquestacion.py`)

No necesitan Postgres. Sí necesitan el manifiesto de dbt: `make test` corre `dbt parse` antes
de pytest y, si se corre pytest suelto sin el manifiesto, el archivo se saltea con un aviso.

- El mes de comparación es el mismo mes del año anterior, enero incluido.
- Un mes inválido (`2025-13`, `2025-3`, vacío) corta antes de ejecutar.
- Orden de los assets: `descarga` → `raw/*` → staging, y `curada` después de `trips_curados` y
  `reporte_calidad_mes`.
- El job usa `in_process_executor`.
- Una etapa que sale con código 1 hace fallar el asset.

**Verificado:**

| Prueba | Resultado |
| --- | --- |
| `make all MES=2025-03`, corrida 1 (sin datos, sin contenedor y con un entorno nuevo) | Código 0, 14 min 2 s: descarga 1 min 48 s, ingesta 2 min 1 s, dbt 8 min 55 s (60 de 60), curada 1 min 3 s |
| `make all MES=2025-03`, corrida 2 | Código 0, 11 min 26 s: descarga e ingesta se saltean por hash (1 s y 6 s), dbt 9 min 59 s (60 de 60), curada 1 min 7 s |
| Conteos después de cada corrida | Idénticos y los mismos del paso 14: leídas 3.582.628 / 4.145.257; aceptadas 3.534.033 / 4.051.870; cuarentena 48.595 / 93.387; diferencia 0 |
| Archivos curados | Mismo sha256 en las dos corridas y el mismo del paso 14: 2024 `db3c1e4d…`, 2025 `eb25f5cf…` |
| Reconciliación forzada a fallar (`diferencia <> 1`, cambio temporal revertido) | Falla `reconciliacion_conteos` (2 filas); dbt da `ERROR=1`; Dagster marca `modelos_dbt` como fallido y no ejecuta `curada`; `make` sale con código 2; los archivos curados no se tocan |
| Mes inválido pasado directo a Dagster (`2025-13`) | Falla al iniciar el recurso `periodo`, antes de ejecutar cualquier asset; código 1 |
| `dagster definitions validate` | Pasa |
| `make test` | 19 pasan: 9 de antes y 10 de orquestación |
| RAM pico (`/usr/bin/time`, el proceso más grande, sin contar Postgres) | 704 MiB en la corrida 1 y 1.090 MiB en la corrida 2, en una máquina de 12 CPU y 14 GiB |

Las corridas por Dagster tardan lo mismo que con Make: casi todo el tiempo sigue siendo
`dbt build`, y dentro de él `int_calidad`. El tiempo y el pico de RAM están en la sección
"Medición de `make all`" (paso 15).

## Medición de `make all` (paso 15, después de R19)

Medido con `/usr/bin/time -v make all MES=2025-03`, con los datos ya descargados e ingeridos
(descarga e ingesta se saltean por hash) y el contenedor de Postgres ya levantado. La memoria
de Postgres se muestreó cada 5 s con `docker stats`, porque `/usr/bin/time` no ve los procesos
del contenedor.

| Medida | Resultado |
| --- | --- |
| Tiempo total (`Elapsed (wall clock) time`) | 5 min 49 s (349 s), código 0 |
| Pico de RAM (`Maximum resident set size`) | 1.070.088 kB (1.045 MiB) |
| Pico de memoria del contenedor de Postgres (`docker stats`) | 1,48 GiB, contra el tope de 1,5 GiB de `mem_limit` |
| `dbt build` | 62 de 62 (dos más que antes: el unit test de R19 y el `not_null` de `tarifa_confiable`) |
| `make conteos` | Leídas 3.582.628 / 4.145.257; aceptadas 3.534.033 / 4.051.870; cuarentena 48.595 / 93.387; diferencia 0 |
| Máquina | La propia: 8 CPU (`nproc`) y 14 GiB de RAM |

- `Maximum resident set size` es el pico del proceso más grande que lanzó `make`, no la suma
  de todos los procesos. Sumado al pico de Postgres, el pipeline queda en unos 2,5 GiB.
- La consigna pide medir en la propia máquina y que el pipeline corra en una notebook de
  8 GB, que es donde lo prueba el docente. El pico medido (unos 2,5 GiB) entra holgado, y
  Postgres no puede pasar de 1,5 GiB porque lo limita `mem_limit` en `compose.yaml`.
