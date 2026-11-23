"""Parte 4: capa curada. Escribe un mes de viajes aceptados en Parquet particionado.

Uso (desde la raíz, con las variables PG* cargadas y dbt ya corrido):
    python -m pipeline.curada --mes 2025-03
Lee la vista analytics.trips_curados con DuckDB y escribe
data/curated/yellow/year=AAAA/month=MM/trips.parquet. Reprocesar un mes reemplaza solo ese
archivo.
"""

import argparse
import os
import sys

import duckdb

from pipeline.descarga import RAIZ, mes_valido, ruta_parquet

DIR_CURADA = RAIZ / "data/curated/yellow"
DIR_TEMPORAL = RAIZ / "data/tmp/duckdb"  # donde DuckDB vuelca a disco si no le alcanza la memoria
# Medido con 2025-03: 1,5 GB y todos los hilos llegaron a 2,2 GB de RAM; 512 MB y 2 hilos, a
# 738 MiB en 22 s, con el mismo archivo de salida.
MEMORIA = "512MB"
HILOS = 2
VISTA = "pg.analytics.trips_curados"
REPORTE = "pg.analytics.reporte_calidad_mes"


class CuradaFallida(Exception):
    """El Parquet escrito no tiene las mismas filas que las aceptadas del mes."""


def ruta_particion(mes):
    anio, m = mes.split("-")
    return DIR_CURADA / f"year={anio}" / f"month={m}" / "trips.parquet"


def conectar():
    con = duckdb.connect()  # base en memoria: DuckDB solo hace de motor de lectura y escritura
    DIR_TEMPORAL.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET memory_limit = '{MEMORIA}'")
    con.execute(f"SET threads = {HILOS}")
    con.execute(f"SET temp_directory = '{DIR_TEMPORAL}'")
    con.execute("SET enable_progress_bar = false")
    con.execute("INSTALL postgres")  # solo descarga la extensión la primera vez
    con.execute("LOAD postgres")
    # Cadena vacía: libpq toma PGHOST, PGPORT, PGDATABASE, PGUSER y PGPASSWORD del entorno.
    con.execute("ATTACH '' AS pg (TYPE postgres, READ_ONLY)")
    return con


def escribir_particion(con, consulta, destino):
    """Escribe el resultado de la consulta en destino, a través de un temporal.

    Si algo falla a mitad de camino, el archivo anterior queda intacto. Devuelve las filas
    del archivo escrito.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")
    try:
        con.execute(f"COPY ({consulta}) TO '{temporal}' (FORMAT parquet, COMPRESSION zstd)")
        os.replace(temporal, destino)  # rename atómico: nunca queda un archivo a medias
    finally:
        temporal.unlink(missing_ok=True)
    return con.execute("SELECT count(*) FROM read_parquet(?)", [str(destino)]).fetchone()[0]


def main():
    parser = argparse.ArgumentParser(description="Capa curada en Parquet de un mes")
    parser.add_argument("--mes", required=True, type=mes_valido, help="AAAA-MM")
    args = parser.parse_args()

    archivo = str(ruta_parquet(args.mes).relative_to(RAIZ))
    destino = ruta_particion(args.mes)
    # ORDER BY con desempate por trip_id: la misma entrada da siempre el mismo archivo.
    consulta = (f"SELECT * EXCLUDE (source_file) FROM {VISTA} "
                f"WHERE source_file = '{archivo}' ORDER BY pickup_at, trip_id")

    try:
        con = conectar()
        fila = con.execute(f"SELECT filas_aceptadas FROM {REPORTE} WHERE mes = ?",
                           [args.mes]).fetchone()
        if fila is None:
            raise CuradaFallida(f"{args.mes} no está en el reporte de calidad; corré primero dbt")
        print(f"{args.mes}: escribiendo {destino.relative_to(RAIZ)}...")
        filas = escribir_particion(con, consulta, destino)
        if filas != fila[0]:  # reconciliación: el Parquet contra las aceptadas del mes
            raise CuradaFallida(f"el Parquet tiene {filas} filas y las aceptadas son {fila[0]}")
        print(f"{args.mes}: listo, {filas} filas")
    except (CuradaFallida, duckdb.Error) as e:
        print(f"ERROR: la capa curada falló: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
