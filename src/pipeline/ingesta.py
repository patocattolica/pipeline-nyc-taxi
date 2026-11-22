"""Parte 1: ingesta con dlt de un mes de viajes y de la tabla de zonas a Postgres.

Uso (desde la raíz, con las variables PG* cargadas):
    python -m pipeline.ingesta --mes 2025-03
El formato de carga se elige con INGESTA_FORMATO: csv (por defecto) o insert_values.
"""

import argparse
import os
import sys
from urllib.parse import quote

import dlt
import psycopg
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import yaml

from pipeline.descarga import (
    RAIZ, RUTA_ZONAS, contar_filas, crear_tabla_log, mes_valido, ruta_parquet, sha256_de,
    ultimo_hash_ok,
)
from pipeline.esquema import CONTRATO, comparar_esquema

ESQUEMA_PG = "raw"
TABLA_VIAJES = "yellow_trips"
TABLA_ZONAS = "taxi_zones"
LOTE = 100_000  # filas por lote leído del Parquet: acota la RAM sin importar el tamaño del mes
FORMATO = os.environ.get("INGESTA_FORMATO", "csv")
NOMBRES_ZONAS = {"LocationID": "location_id", "Borough": "borough", "Zone": "zone",
                 "service_zone": "service_zone"}


class IngestaFallida(Exception):
    """El esquema no cumple el contrato o los conteos no cierran."""


def leer_contrato():
    with open(CONTRATO) as f:
        return yaml.safe_load(f)["columnas"]


def lotes_viajes(ruta, contrato, archivo):
    """Lotes Arrow con las columnas del contrato, renombradas, y el archivo de origen."""
    presentes = set(pq.read_schema(ruta).names)
    a_leer = [c["origen"] for c in contrato if c["origen"] in presentes]
    for lote in pq.ParquetFile(ruta).iter_batches(batch_size=LOTE, columns=a_leer):
        tabla = pa.Table.from_batches([lote])
        for col in contrato:
            if col["origen"] not in presentes:  # solo llega acá si su 'desde' es posterior al mes
                tipo = pa.type_for_alias(col["tipo_parquet"])
                tabla = tabla.append_column(col["origen"], pa.nulls(len(tabla), tipo))
        tabla = tabla.select([c["origen"] for c in contrato])
        tabla = tabla.rename_columns([c["destino"] for c in contrato])
        yield tabla.append_column("source_file", pa.array([archivo] * len(tabla), pa.string()))


def tabla_zonas(ruta):
    # strings_can_be_null=False: "N/A" queda como texto, igual que en el CSV de la TLC.
    opciones = pacsv.ConvertOptions(strings_can_be_null=False)
    tabla = pacsv.read_csv(ruta, convert_options=opciones)
    return tabla.rename_columns([NOMBRES_ZONAS[n] for n in tabla.column_names])


def recurso_viajes(ruta, contrato, archivo):
    return dlt.resource(
        lotes_viajes(ruta, contrato, archivo),
        name=TABLA_VIAJES,
        # Borra las filas de este source_file y carga las nuevas: reprocesar un mes no toca el otro.
        write_disposition={"disposition": "merge", "strategy": "delete-insert"},
        merge_key="source_file",
        columns={c: {"timezone": False} for c in ("tpep_pickup_datetime", "tpep_dropoff_datetime")},
    )


def recurso_zonas(ruta):
    return dlt.resource([tabla_zonas(ruta)], name=TABLA_ZONAS, write_disposition="replace")


def crear_pipeline():
    e = os.environ
    url = (f"postgresql://{quote(e['PGUSER'])}:{quote(e['PGPASSWORD'])}@"
           f"{e['PGHOST']}:{e['PGPORT']}/{e['PGDATABASE']}")
    return dlt.pipeline(
        pipeline_name="taxis",
        destination=dlt.destinations.postgres(url),
        dataset_name=ESQUEMA_PG,
        pipelines_dir=str(RAIZ / "data/dlt"),  # estado local de dlt, fuera de Git
    )


def filas_en_db(con, tabla, archivo=None):
    if con.execute("SELECT to_regclass(%s)", (f"{ESQUEMA_PG}.{tabla}",)).fetchone()[0] is None:
        return 0
    sql = f"SELECT count(*) FROM {ESQUEMA_PG}.{tabla}"
    if archivo is None:
        return con.execute(sql).fetchone()[0]
    return con.execute(sql + " WHERE source_file = %s", (archivo,)).fetchone()[0]


def ya_ingerido(hash_actual, hash_log, filas_archivo, filas_db):
    """Se saltea solo si el archivo no cambió y sus filas siguen todas en la base."""
    return hash_actual is not None and hash_actual == hash_log and filas_archivo == filas_db


def registrar(con, archivo, estado, filas=None, bytes_=None, hash_=None, mensaje=None):
    con.execute(
        "INSERT INTO ingestion_log (etapa, archivo, filas, bytes, hash, estado, mensaje) "
        "VALUES ('ingesta', %s, %s, %s, %s, %s, %s)",
        (archivo, filas, bytes_, hash_, estado, mensaje),
    )


def ingerir(con, pipeline, recurso, ruta, tabla, por_archivo, forzar=False):
    archivo = str(ruta.relative_to(RAIZ))
    hash_actual, filas_archivo = sha256_de(ruta), contar_filas(ruta)
    filtro = archivo if por_archivo else None
    if not forzar and ya_ingerido(hash_actual, ultimo_hash_ok(con, archivo, "ingesta"),
                                  filas_archivo, filas_en_db(con, tabla, filtro)):
        print(f"{archivo}: ya está en {ESQUEMA_PG}.{tabla} con el mismo hash, no se ingiere")
        return
    print(f"{archivo}: ingiriendo a {ESQUEMA_PG}.{tabla} (formato {FORMATO})...")
    pipeline.run(recurso, loader_file_format=FORMATO)
    filas_db = filas_en_db(con, tabla, filtro)
    if filas_db != filas_archivo:  # reconciliación: lo que hay en la base contra el archivo
        mensaje = f"el archivo tiene {filas_archivo} filas y la base {filas_db}"
        registrar(con, archivo, "error", filas_db, ruta.stat().st_size, hash_actual, mensaje)
        raise IngestaFallida(f"{archivo}: {mensaje}")
    registrar(con, archivo, "ok", filas_db, ruta.stat().st_size, hash_actual)
    print(f"{archivo}: listo, {filas_db} filas")


def validar_esquema(con, ruta, mes):
    archivo = str(ruta.relative_to(RAIZ))
    dif = comparar_esquema(ruta, mes)
    if dif["nuevas"]:
        print(f"AVISO: {archivo} trae columnas fuera del contrato, no se cargan: {dif['nuevas']}")
    if dif["faltantes"] or dif["tipos_distintos"]:
        mensaje = f"faltantes={dif['faltantes']} tipos_distintos={dif['tipos_distintos']}"
        registrar(con, archivo, "error", mensaje=mensaje)
        raise IngestaFallida(f"{archivo} no cumple el contrato: {mensaje}")


def main():
    parser = argparse.ArgumentParser(description="Ingesta de taxis amarillos de NYC con dlt")
    parser.add_argument("--mes", required=True, type=mes_valido, help="AAAA-MM")
    parser.add_argument("--forzar", action="store_true",
                        help="reingiere el mes aunque el archivo ya esté cargado con el mismo hash")
    args = parser.parse_args()
    ruta_mes = ruta_parquet(args.mes)

    for ruta in (RUTA_ZONAS, ruta_mes):
        if not ruta.exists():
            print(f"ERROR: falta {ruta.relative_to(RAIZ)}; corré primero la descarga", file=sys.stderr)
            sys.exit(1)

    try:
        # autocommit: cada consulta ve lo que dlt ya confirmó y no deja bloqueos abiertos.
        with psycopg.connect(autocommit=True) as con:  # lee PGHOST, PGPORT, PGDATABASE, ...
            crear_tabla_log(con)
            validar_esquema(con, ruta_mes, args.mes)
            pipeline = crear_pipeline()
            archivo_mes = str(ruta_mes.relative_to(RAIZ))
            ingerir(con, pipeline, recurso_zonas(RUTA_ZONAS), RUTA_ZONAS, TABLA_ZONAS, False)
            ingerir(con, pipeline, recurso_viajes(ruta_mes, leer_contrato(), archivo_mes),
                    ruta_mes, TABLA_VIAJES, True, args.forzar)
    except IngestaFallida as e:
        print(f"ERROR: la ingesta falló: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
