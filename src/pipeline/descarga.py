"""Parte 1: descarga de un mes de taxis amarillos y de la tabla de zonas."""

import argparse
import hashlib
import http.client
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import psycopg
import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parents[2]
URL_MES = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{mes}.parquet"
URL_ZONAS = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
RUTA_ZONAS = RAIZ / "data/raw/zones/taxi_zone_lookup.csv"

REINTENTOS = 3  # después del primer intento: 4 intentos en total
ESPERA_INICIAL = 2  # segundos; se duplica en cada reintento (2, 4, 8)
ERRORES_DE_RED = (OSError, http.client.HTTPException)  # OSError incluye URLError y timeouts


class DescargaIncompleta(OSError):
    """El servidor cortó antes de mandar todos los bytes que anunció."""


def ruta_parquet(mes):
    anio, m = mes.split("-")
    return RAIZ / "data/raw/yellow" / f"year={anio}" / f"month={m}" / f"yellow_tripdata_{mes}.parquet"


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
            etapa      text        NOT NULL DEFAULT 'descarga'
                                   CHECK (etapa IN ('descarga', 'ingesta')),
            archivo    text        NOT NULL,
            url        text,
            filas      bigint,
            bytes      bigint,
            hash       text,
            fecha_hora timestamptz NOT NULL DEFAULT now(),
            estado     text        NOT NULL CHECK (estado IN ('ok', 'error')),
            mensaje    text
        )
        """
    )
    # Si la tabla ya existía sin la columna, se la agrega (no hace nada si ya está).
    con.execute("ALTER TABLE ingestion_log ADD COLUMN IF NOT EXISTS mensaje text")
    con.execute(
        "ALTER TABLE ingestion_log ADD COLUMN IF NOT EXISTS etapa text NOT NULL DEFAULT 'descarga' "
        "CHECK (etapa IN ('descarga', 'ingesta'))"
    )
    con.execute("ALTER TABLE ingestion_log ALTER COLUMN url DROP NOT NULL")  # la ingesta no tiene URL


def ultimo_hash_ok(con, archivo, etapa="descarga"):
    fila = con.execute(
        "SELECT hash FROM ingestion_log WHERE archivo = %s AND etapa = %s AND estado = 'ok' "
        "ORDER BY id DESC LIMIT 1",
        (archivo, etapa),
    ).fetchone()
    return fila[0] if fila else None


def descargar(url, destino):
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(temporal, "wb") as f:
            esperado = resp.headers.get("Content-Length")
            shutil.copyfileobj(resp, f)
        recibido = temporal.stat().st_size
        if esperado is not None and recibido != int(esperado):
            raise DescargaIncompleta(f"llegaron {recibido} de {esperado} bytes")
        temporal.replace(destino)  # el rename es atómico: nunca queda un archivo a medias
    finally:
        temporal.unlink(missing_ok=True)


def descargar_con_reintentos(url, destino):
    for intento in range(REINTENTOS + 1):
        try:
            descargar(url, destino)
            return
        except ERRORES_DE_RED as e:
            if intento == REINTENTOS:
                raise  # se acabaron los intentos: el error sube
            espera = ESPERA_INICIAL * 2**intento
            print(f"  falló ({type(e).__name__}: {e}); reintento {intento + 1}/{REINTENTOS} en {espera} s")
            time.sleep(espera)


def asegurar_archivo(con, url, destino):
    archivo = str(destino.relative_to(RAIZ))
    if destino.exists() and sha256_de(destino) == ultimo_hash_ok(con, archivo):
        print(f"{archivo}: ya existe y el hash coincide con el log, no se descarga")
        return
    print(f"{archivo}: descargando...")
    try:
        descargar_con_reintentos(url, destino)
    except ERRORES_DE_RED as e:
        con.execute(
            "INSERT INTO ingestion_log (archivo, url, estado, mensaje) "
            "VALUES (%s, %s, 'error', %s)",
            (archivo, url, f"{type(e).__name__}: {e}"),
        )
        con.commit()  # sin esto, el error que sube haría rollback y se perdería la fila
        raise
    con.execute(
        "INSERT INTO ingestion_log (archivo, url, filas, bytes, hash, estado) "
        "VALUES (%s, %s, %s, %s, %s, 'ok')",
        (archivo, url, contar_filas(destino), destino.stat().st_size, sha256_de(destino)),
    )
    print(f"{archivo}: listo")


def main():
    parser = argparse.ArgumentParser(description="Descarga de taxis amarillos de NYC")
    parser.add_argument("--mes", required=True, type=mes_valido, help="AAAA-MM")
    args = parser.parse_args()

    destino_mes = ruta_parquet(args.mes)
    destino_zonas = RUTA_ZONAS

    try:
        with psycopg.connect() as con:  # lee PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
            crear_tabla_log(con)
            asegurar_archivo(con, URL_ZONAS, destino_zonas)
            asegurar_archivo(con, URL_MES.format(mes=args.mes), destino_mes)
    except ERRORES_DE_RED as e:
        print(f"ERROR: la descarga falló: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
