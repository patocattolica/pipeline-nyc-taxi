Examen: Pipeline NYC Taxi
Nov 5, 2026 · @pedro
Contexto y objetivo
Cada alumno construye, en forma individual y en su casa, un pipeline batch reproducible que ingiera, valide, limpie y modele los viajes de taxis de Nueva York de dos meses asignados, y responder preguntas de negocio sobre su propio modelo.
Se evalúa el ciclo completo de ingeniería de datos, no el análisis:
    • Ingesta idempotente y trazable.
    • Manejo de un esquema que cambia entre años.
    • Reglas de calidad explícitas, con cuarentena y reconciliación de conteos.
    • Almacenamiento columnar particionado.
    • Modelado dimensional y SQL.
    • Reproducibilidad y documentación de decisiones.
Modalidad: dos chicos, con defensa oral posterior. Plazo: a definir por la cátedra (sugerido: 14 días corridos). Puntaje: 10 puntos, detallados en la rúbrica.
Datos
Cada alumno trabaja con dos archivos mensuales de taxi amarillo de la Comisión de Taxis y Limusinas de Nueva York (TLC): su mes asignado y el mismo mes de 2024, más la tabla de zonas.
Recurso	Enlace
Página oficial de datos	TLC Trip Record Data
Diccionario de datos del taxi amarillo	Yellow Trips Data Dictionary (PDF)
Tabla de zonas	taxi_zone_lookup.csv
Archivo mensual	https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_AAAA-MM.parquet
Para tener en cuenta:
    • Los archivos están en formato Parquet y la TLC los publica cada mes con unos dos meses de demora. Cada uno tiene del orden de 3 a 4 millones de filas (aproximado).
    • Desde 2025 los archivos incluyen la columna cbd_congestion_fee, agregada por los nuevos cargos de congestión; los de 2024 no la tienen.
    • La TLC aclara que no garantiza la exactitud de estos datos. Encontrar y tratar esa suciedad es parte del examen.
Asignación de tarea
Debe realizar el análisis de un mes en comparación con el mismo mes mes del año pasado. O comparar todos los meses con los del año anterior.
Consigna
El pipeline tiene cinco partes que se ejecutan en orden con un solo comando, para el mes que se le pase como parámetro.

arquitectura del pipeline · 5 etapas, cuarentena y log de ingesta
La validación es la compuerta del pipeline: separa las filas aceptadas de las rechazadas, y el log de ingesta registra cada descarga.
Parte 1: Ingesta (15 puntos)
    1. Script parametrizado por mes (por ejemplo, --mes 2025-03) que descarga el archivo a data/raw/yellow/year=AAAA/month=MM/ sin modificarlo. La tabla de zonas se descarga una sola vez.
    2. Idempotencia: correr dos veces el mismo mes no duplica datos ni vuelve a descargar si el archivo ya existe y su hash coincide.
    3. Registro de control ingestion_log con archivo, URL, filas, bytes, hash, fecha y hora, y estado (ok o error).
    4. Ante una falla de red, hasta 3 reintentos con espera creciente. Si sigue fallando, registrar el error y terminar con código de salida distinto de 0.
Parte 2: Esquema (15 puntos)
    1. Definir un contrato de esquema destino (nombre y tipo de cada columna) en un archivo versionado, no implícito en el código.
    2. Antes de cargar, comparar el esquema real de cada archivo contra el contrato y reportar columnas faltantes, columnas nuevas y tipos distintos.
    3. Normalizar los nombres a snake_case (por ejemplo, PULocationID pasa a pu_location_id).
    4. Unificar los dos meses en una misma tabla. Decidir y justificar en el README qué valor toma cbd_congestion_fee en 2024 (nulo o 0) y qué haría el pipeline si mañana aparece una columna que no está en el contrato.
Parte 3: Calidad de datos y cuarentena (25 puntos)
    1. Implementar al menos 8 reglas de calidad, cada una con identificador, descripción, severidad (rechazo o advertencia) y umbral justificado. La severidad de cada regla la decide el alumno y se defiende en el oral. Son obligatorias:
        ◦ Fecha de subida fuera del mes del archivo.
        ◦ Bajada anterior o igual a la subida.
        ◦ Distancia menor o igual a 0, o mayor a un máximo que se debe justificar.
        ◦ Importe total negativo.
        ◦ Cantidad de pasajeros nula o igual a 0.
        ◦ Zona de origen o de destino inexistente en la tabla de zonas.
        ◦ Filas duplicadas exactas.
        ◦ Al menos una regla propia, descubierta explorando los datos.
    2. Las filas que violan una regla de rechazo van a una tabla de cuarentena con la fila original, el archivo de origen y la lista de reglas violadas. Las advertencias no descartan la fila: se marcan en una columna de flags.
    3. Generar un reporte de calidad por mes: filas leídas, aceptadas, en cuarentena y cantidad por regla.
    4. Reconciliación: el pipeline falla si las filas leídas no son iguales a las aceptadas más las de cuarentena.
Parte 4: Transformación y almacenamiento (15 puntos)
    1. Escribir la capa curada en Parquet particionado por year y month (estilo Hive).
    2. Agregar columnas derivadas: duración en minutos, velocidad promedio en mph, fecha, hora y día de la semana de la subida, y propina como porcentaje de la tarifa.
    3. Enriquecer con la tabla de zonas: barrio (borough) y nombre de zona de origen y de destino.
    4. Reprocesar un mes reemplaza solo su partición y deja intactas las demás. Demostrarlo en el README con los conteos antes y después.
Parte 5: Modelo y preguntas de negocio (20 puntos)
    1. Construir un modelo estrella mínimo con fact_trips, dim_zone y dim_date, y escribir en el README la granularidad de cada tabla.
    2. Construir la tabla agregada agg_zone_hour: viajes, ingreso total y duración media por zona de origen, fecha y hora.
    3. Responder con SQL sobre el propio modelo, para los dos meses asignados, y volcar los resultados en RESULTADOS.md:
        a. Las 10 zonas de origen con más viajes y su variación contra el mes de 2024.
        b. La hora del día con mayor ingreso promedio por viaje.
        c. El porcentaje de viajes con cbd_congestion_fee mayor a 0 en el mes asignado, y las 5 zonas de origen con mayor proporción de esos viajes.
        d. La propina promedio, como porcentaje de la tarifa, por tipo de pago, explicando por qué el valor de uno de los tipos de pago no es interpretable.
        e. Cantidad de viajes y tarifa media de los que empiezan o terminan en los aeropuertos JFK o LaGuardia, identificados por nombre de zona.
        f. La variación de viajes totales y de tarifa media entre los dos meses, con una hipótesis de causa en no más de 5 líneas.
Entregables (10 puntos)
Se entrega un repositorio Git (enlace o .zip) que cualquiera pueda clonar y ejecutar de punta a punta con un solo comando, sin los datos incluidos.
Estructura mínima:
README.md
RESULTADOS.md
requirements.txt        (o pyproject.toml)
Makefile                (o script equivalente)
contracts/yellow_schema.yaml
src/                    ingesta, esquema, calidad, transformación, modelo
sql/                    modelo y preguntas, una consulta por archivo
tests/
.gitignore              (excluye data/)
    • Comando único: make all MES=2025-03 (o equivalente) ejecuta ingesta, validación, transformación, modelo y preguntas para el mes asignado y su mes de comparación.
    • README: cómo instalar y ejecutar, arquitectura, decisiones (umbrales, severidades, tratamiento de nulos), limitaciones conocidas, tiempo de ejecución y pico de RAM en la propia máquina, y declaración de uso de IA.
    • Tests automatizados: al menos 3, que cubran una regla de calidad sobre datos sintéticos, la idempotencia de la ingesta y la reconciliación de conteos.
    • RESULTADOS.md: las 6 respuestas con su número, la consulta que la produce y una línea de interpretación.
Reglas
El examen es individual: se puede consultar documentación y material de la materia, pero no compartir código ni resultados con otros alumnos.
    • Herramientas: Python 3.10 o superior, SQL, y DuckDB, Polars o pandas. dbt, Airflow, Prefect, dagster o PySpark están permitidos, suman puntos por sí mismos (sobre todo herramientas que no se vieron en la materia).
    • Recursos: el pipeline debe correr en una notebook con 8 GB de RAM. Elegir la herramienta y cuidar la memoria es parte de lo que se evalúa.
    • Uso de IA: permitido como asistente, declarando en el README qué herramienta se usó y para qué. Todo el código entregado debe poder explicarse en la defensa; lo que no se pueda explicar no se cuenta.
    • Consultas: por el canal que defina la cátedra, hasta 48 horas antes de la entrega, y solo sobre la consigna, no sobre la solución.
    • Entrega tardía: a definir por la cátedra.
    • Plagio: dos entregas con código sustancialmente igual quedan desaprobadas.
Defensa oral
Fecha a definir.
Demostración:
    1. Correr el pipeline completo para el mes elegido.
    2. Volver a correrlo y mostrar que los conteos no cambian.
    3. Mostrar el reporte de calidad y una fila en cuarentena con su regla violada.