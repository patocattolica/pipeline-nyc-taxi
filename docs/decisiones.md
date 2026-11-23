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
| 11 en adelante | Pendiente | — |

**Ramas:**
- `master`: diseño original, con PyAirbyte.
- `dlt`: el mismo proyecto, con dlt como herramienta de ingesta. Se abrió a partir de las
  mediciones de la sección "Herramienta de ingesta".

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
- **Medición.** Repetir la medición en la notebook de 8 GB.
- **Tabla intermedia de dlt.** El merge deja `raw_staging.yellow_trips` con el último mes
  cargado (3.582.628 filas, 859 MB). No afecta los datos, pero ocupa disco: hay que
  vaciarla después de cada carga.

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
  - `reglas_propias_r16_r17_en_el_borde`: 80 mph exactos no rechaza y 80,08 sí; 361 min
    con US$ 126,35 (0,35 × 361) no rechaza y con un centavo menos sí; 360 min exactos no
    superan la duración máxima.
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
diseño original. Medirlo en la notebook de 8 GB y, si hace falta, optimizarlo.
