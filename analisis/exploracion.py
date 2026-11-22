"""Paso 5: exploración de los Parquet crudos con DuckDB. No forma parte del pipeline.

Uso (desde la raíz del proyecto):
    python analisis/exploracion.py              # los dos meses
    python analisis/exploracion.py 2025-03      # uno solo
"""

import sys
from datetime import date
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]
MESES = ["2025-03", "2024-03"]


def ruta_parquet(mes):
    anio, m = mes.split("-")
    return RAIZ / f"data/raw/yellow/year={anio}/month={m}/yellow_tripdata_{mes}.parquet"


def limites_del_mes(mes):
    anio, m = map(int, mes.split("-"))
    siguiente = date(anio + (m == 12), m % 12 + 1, 1)
    return f"{anio}-{m:02d}-01", siguiente.isoformat()


def catalogo(columna):
    return (
        f"SELECT {columna}, count(*) AS n, "
        f"round(100.0 * count(*) / sum(count(*)) OVER (), 3) AS pct "
        f"FROM t GROUP BY {columna} ORDER BY n DESC, {columna}"
    )


CONSULTAS = [
    ("Filas del archivo", "SELECT count(*) AS filas FROM t"),
    (
        "2. Columnas con nulos",
        "SELECT column_name, column_type, null_percentage FROM (SUMMARIZE t) "
        "WHERE null_percentage > 0 ORDER BY column_name",
    ),
    ("3a. Catálogo ratecodeid", catalogo("RatecodeID")),
    ("3b. Catálogo payment_type", catalogo("payment_type")),
    ("3c. Catálogo vendorid", catalogo("VendorID")),
    (
        "4. Proveedores: peso y % con bajada igual a la subida",
        """SELECT VendorID, count(*) AS n,
                  round(100.0 * count(*) / sum(count(*)) OVER (), 3) AS pct_de_las_filas,
                  count(*) FILTER (WHERE tpep_dropoff_datetime = tpep_pickup_datetime) AS bajada_igual,
                  round(100.0 * count(*) FILTER (WHERE tpep_dropoff_datetime = tpep_pickup_datetime)
                        / count(*), 2) AS pct_bajada_igual
           FROM t GROUP BY VendorID ORDER BY VendorID""",
    ),
    (
        "5a. Fechas: subida fuera del mes y bajadas problemáticas",
        """SELECT count(*) FILTER (WHERE tpep_pickup_datetime < '{ini}'
                                   OR tpep_pickup_datetime >= '{fin}') AS subida_fuera_del_mes,
                  count(*) FILTER (WHERE tpep_dropoff_datetime < tpep_pickup_datetime) AS bajada_anterior,
                  count(*) FILTER (WHERE tpep_dropoff_datetime = tpep_pickup_datetime) AS bajada_igual,
                  min(tpep_pickup_datetime) AS subida_min, max(tpep_pickup_datetime) AS subida_max
           FROM t""",
    ),
    (
        "5b. Subidas fuera del mes: en qué mes caen",
        """SELECT date_trunc('month', tpep_pickup_datetime) AS mes_de_la_subida, count(*) AS n
           FROM t WHERE tpep_pickup_datetime < '{ini}' OR tpep_pickup_datetime >= '{fin}'
           GROUP BY 1 ORDER BY 1""",
    ),
    (
        "6a. Distancia: signos, percentiles y cola alta",
        """SELECT count(*) FILTER (WHERE trip_distance < 0) AS negativas,
                  count(*) FILTER (WHERE trip_distance = 0) AS ceros,
                  round(quantile_cont(trip_distance, 0.5), 2) AS p50,
                  round(quantile_cont(trip_distance, 0.99), 2) AS p99,
                  round(quantile_cont(trip_distance, 0.999), 2) AS p999,
                  count(*) FILTER (WHERE trip_distance > 50) AS mas_de_50,
                  count(*) FILTER (WHERE trip_distance > 100) AS mas_de_100,
                  count(*) FILTER (WHERE trip_distance > 200) AS mas_de_200,
                  count(*) FILTER (WHERE trip_distance > 500) AS mas_de_500,
                  max(trip_distance) AS maximo
           FROM t""",
    ),
    (
        "6b. Las 8 distancias más largas",
        """SELECT trip_distance, tpep_pickup_datetime, tpep_dropoff_datetime, fare_amount, total_amount
           FROM t ORDER BY trip_distance DESC, tpep_pickup_datetime, tpep_dropoff_datetime LIMIT 8""",
    ),
    (
        "7. Importe y pasajeros",
        """SELECT count(*) FILTER (WHERE total_amount < 0) AS total_negativo,
                  count(*) FILTER (WHERE total_amount = 0) AS total_cero,
                  count(*) FILTER (WHERE fare_amount < 0) AS tarifa_negativa,
                  count(*) FILTER (WHERE passenger_count IS NULL) AS pasajeros_nulo,
                  count(*) FILTER (WHERE passenger_count = 0) AS pasajeros_cero,
                  count(*) FILTER (WHERE passenger_count > 6) AS pasajeros_mas_de_6
           FROM t""",
    ),
    (
        "8. Zonas: nulas, inexistentes y desconocidas (264 y 265)",
        """SELECT count(*) FILTER (WHERE PULocationID IS NULL) AS pu_nulo,
                  count(*) FILTER (WHERE DOLocationID IS NULL) AS do_nulo,
                  count(*) FILTER (WHERE PULocationID NOT IN (SELECT LocationID FROM zonas)) AS pu_inexistente,
                  count(*) FILTER (WHERE DOLocationID NOT IN (SELECT LocationID FROM zonas)) AS do_inexistente,
                  count(*) FILTER (WHERE PULocationID IN (264, 265)) AS pu_264_265,
                  count(*) FILTER (WHERE DOLocationID IN (264, 265)) AS do_264_265
           FROM t""",
    ),
    (
        "9. Duplicados exactos (filas idénticas en todas las columnas)",
        """WITH d AS (SELECT count(*) AS n FROM (SELECT DISTINCT * FROM t))
           SELECT (SELECT count(*) FROM t) AS filas, d.n AS filas_distintas,
                  (SELECT count(*) FROM t) - d.n AS duplicadas FROM d""",
    ),
    (
        "10a. Candidata a regla propia: duración y velocidad (solo bajada > subida)",
        """WITH v AS (
               SELECT date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime) / 60.0 AS minutos,
                      trip_distance AS millas
               FROM t WHERE tpep_dropoff_datetime > tpep_pickup_datetime)
           SELECT count(*) AS viajes,
                  round(quantile_cont(minutos, 0.5), 1) AS p50_min,
                  round(quantile_cont(minutos, 0.99), 1) AS p99_min,
                  round(max(minutos), 1) AS max_min,
                  count(*) FILTER (WHERE minutos > 720) AS mas_de_12h,
                  count(*) FILTER (WHERE minutos > 1440) AS mas_de_24h,
                  count(*) FILTER (WHERE millas / (minutos / 60.0) > 100) AS mas_de_100mph,
                  count(*) FILTER (WHERE millas / (minutos / 60.0) > 200) AS mas_de_200mph
           FROM v""",
    ),
    (
        "10b. Candidata R12: cargo de aeropuerto con subida fuera de JFK y LaGuardia",
        """SELECT count(*) FILTER (WHERE Airport_fee > 0) AS con_cargo_aeropuerto,
                  count(*) FILTER (WHERE Airport_fee > 0 AND PULocationID NOT IN
                      (SELECT LocationID FROM zonas
                       WHERE Zone IN ('JFK Airport', 'LaGuardia Airport'))) AS cargo_fuera_de_jfk_lga
           FROM t""",
    ),
    (
        "11. Histograma de duración (solo bajada > subida)",
        """WITH d AS (SELECT date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime) / 3600.0 AS horas,
                         trip_distance, fare_amount
                  FROM t WHERE tpep_dropoff_datetime > tpep_pickup_datetime)
           SELECT CASE WHEN horas <= 3 THEN 'a) hasta 3 h' WHEN horas <= 6 THEN 'b) 3 a 6 h'
                       WHEN horas <= 12 THEN 'c) 6 a 12 h' WHEN horas <= 23 THEN 'd) 12 a 23 h'
                       WHEN horas <= 24 THEN 'e) 23 a 24 h' ELSE 'f) más de 24 h' END AS tramo,
                  count(*) AS n, round(median(trip_distance), 2) AS med_millas,
                  round(median(fare_amount), 2) AS med_tarifa
           FROM d GROUP BY 1 ORDER BY 1""",
    ),
    (
        "12. R16: velocidad mayor a 80 mph, por tipo de error",
        """WITH v AS (SELECT trip_distance,
                         date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime) AS seg
                  FROM t WHERE tpep_dropoff_datetime > tpep_pickup_datetime AND trip_distance > 0)
           SELECT CASE WHEN trip_distance > 1000 THEN 'a) más de 1000 mi'
                       WHEN seg < 60 THEN 'b) menos de 1 min' ELSE 'c) resto' END AS tipo,
                  count(*) AS n
           FROM v WHERE trip_distance / (seg / 3600.0) > 80 GROUP BY 1 ORDER BY 1""",
    ),
    (
        "13. R05: filas de más de 500 mi que ninguna regla de rechazo agarra",
        """WITH v AS (SELECT trip_distance,
                         date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime) AS seg
                  FROM t WHERE trip_distance > 500)
           SELECT count(*) AS mas_de_500,
                  count(*) FILTER (WHERE seg <= 0) AS r02_r03,
                  count(*) FILTER (WHERE seg > 0 AND trip_distance / (seg / 3600.0) > 80) AS r16,
                  count(*) FILTER (WHERE NOT (seg <= 0 OR trip_distance / (seg / 3600.0) > 80)) AS ninguna
           FROM v""",
    ),
    (
        "14. R17: más de 6 h, tarifa contra taxímetro (US$ 0,70 por minuto)",
        """WITH d AS (SELECT date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime) / 60.0 AS minutos,
                         fare_amount
                  FROM t WHERE tpep_dropoff_datetime > tpep_pickup_datetime)
           SELECT count(*) FILTER (WHERE minutos > 360) AS mas_de_6h,
                  count(*) FILTER (WHERE minutos > 360 AND fare_amount >= 0.70 * minutos) AS cumple_070,
                  count(*) FILTER (WHERE minutos > 360 AND fare_amount >= 0.35 * minutos) AS cumple_035,
                  count(*) FILTER (WHERE minutos > 360 AND fare_amount < 0.35 * minutos) AS rechaza_r17,
                  round(median(fare_amount / minutos) FILTER (WHERE minutos > 360), 3) AS med_usd_por_min
           FROM d""",
    ),
    (
        "15. Importe negativo: cuántas filas tienen gemela positiva (reverso)",
        """SELECT count(*) AS negativas,
                  count(*) FILTER (WHERE EXISTS (
                      SELECT 1 FROM t p
                      WHERE p.tpep_pickup_datetime = n.tpep_pickup_datetime
                        AND p.tpep_dropoff_datetime = n.tpep_dropoff_datetime
                        AND p.PULocationID = n.PULocationID AND p.DOLocationID = n.DOLocationID
                        AND p.total_amount = -n.total_amount)) AS con_gemela,
                  round(sum(total_amount), 0) AS suma_negativa
           FROM t n WHERE total_amount < 0""",
    ),
]


def main():
    meses = sys.argv[1:] or MESES
    con = duckdb.connect()
    con.sql("SET memory_limit = '1500MB'")
    con.sql(
        f"CREATE VIEW zonas AS SELECT * FROM read_csv('{RAIZ}/data/raw/zones/taxi_zone_lookup.csv')"
    )
    for mes in meses:
        ini, fin = limites_del_mes(mes)
        # hive_partitioning=false: sin esto DuckDB inventa las columnas year y month desde la ruta
        con.sql(
            f"CREATE OR REPLACE VIEW t AS "
            f"SELECT * FROM read_parquet('{ruta_parquet(mes)}', hive_partitioning = false)"
        )
        print(f"\n{'=' * 20} {mes} {'=' * 20}")
        for titulo, sql in CONSULTAS:
            print(f"\n--- {titulo}")
            con.sql(sql.format(ini=ini, fin=fin)).show(max_rows=30, max_width=220)


if __name__ == "__main__":
    main()
