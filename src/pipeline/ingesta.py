"""Parte 1: descarga de un mes de taxis amarillos y de la tabla de zonas."""

import argparse
import hashlib
import re
import shutil
import urllib.request
from pathlib import Path

import psycopg
import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parents[2]
URL_MES = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{mes}.parquet"
URL_ZONAS = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"


def mes_valido(texto):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", texto):
        raise argparse.ArgumentTypeError(f"'{texto}' no tiene el formato AAAA-MM")
    return texto


def sha256_de(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def contar_filas(ruta):
    if ruta.suffix == ".parquet":
        return pq.ParquetFile(ruta).metadata.num_rows  # solo lee el pie del archivo
    with open(ruta, "rb") as f:
        return sum(1 for _ in f) - 1  # CSV: líneas menos el encabezado


def crear_tabla_log(con):
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_log (
            id         bigserial PRIMARY KEY,
            archivo    text        NOT NULL,
            url        text        NOT NULL,
            filas      bigint,
            bytes      bigint,
            hash       text,
            fecha_hora timestamptz NOT NULL DEFAULT now(),
            estado     text        NOT NULL CHECK (estado IN ('ok', 'error'))
        )
        """
    )


def ultimo_hash_ok(con, archivo):
    fila = con.execute(
        "SELECT hash FROM ingestion_log WHERE archivo = %s AND estado = 'ok' "
        "ORDER BY id DESC LIMIT 1",
        (archivo,),
    ).fetchone()
    return fila[0] if fila else None


def descargar(url, destino):
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(temporal, "wb") as f:
            shutil.copyfileobj(resp, f)
        temporal.replace(destino)  # el rename es atómico: nunca queda un archivo a medias
    finally:
        temporal.unlink(missing_ok=True)


def asegurar_archivo(con, url, destino):
    archivo = str(destino.relative_to(RAIZ))
    if destino.exists() and sha256_de(destino) == ultimo_hash_ok(con, archivo):
        print(f"{archivo}: ya existe y el hash coincide con el log, no se descarga")
        return
    print(f"{archivo}: descargando...")
    descargar(url, destino)
    con.execute(
        "INSERT INTO ingestion_log (archivo, url, filas, bytes, hash, estado) "
        "VALUES (%s, %s, %s, %s, %s, 'ok')",
        (archivo, url, contar_filas(destino), destino.stat().st_size, sha256_de(destino)),
    )
    print(f"{archivo}: listo")


def main():
    parser = argparse.ArgumentParser(description="Ingesta de taxis amarillos de NYC")
    parser.add_argument("--mes", required=True, type=mes_valido, help="AAAA-MM")
    args = parser.parse_args()
    anio, mes = args.mes.split("-")

    destino_mes = (
        RAIZ / "data/raw/yellow" / f"year={anio}" / f"month={mes}"
        / f"yellow_tripdata_{args.mes}.parquet"
    )
    destino_zonas = RAIZ / "data/raw/zones/taxi_zone_lookup.csv"

    with psycopg.connect() as con:  # lee PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
        crear_tabla_log(con)
        asegurar_archivo(con, URL_ZONAS, destino_zonas)
        asegurar_archivo(con, URL_MES.format(mes=args.mes), destino_mes)


if __name__ == "__main__":
    main()
