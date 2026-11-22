"""Paso 7: prueba de ingesta de un trozo del Parquet con PyAirbyte, midiendo tiempo y RAM.

No forma parte del pipeline. Uso (desde la raíz, con las variables PG* cargadas):
    AIRBYTE_OFFLINE_MODE=1 python analisis/prueba_ingesta.py [filas]
"""

import os
import resource
import sys
import time
from pathlib import Path

import airbyte as ab
import pyarrow as pa
import pyarrow.parquet as pq
from airbyte.caches import PostgresCache

RAIZ = Path(__file__).resolve().parents[1]
ORIGEN = RAIZ / "data/raw/yellow/year=2025/month=03/yellow_tripdata_2025-03.parquet"
TROZO = RAIZ / "data/tmp/trozo_prueba.parquet"


def cortar_trozo(filas):
    lote = next(pq.ParquetFile(ORIGEN).iter_batches(batch_size=filas))
    TROZO.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_batches([lote]), TROZO)
    return lote.num_rows


def main():
    filas = int(sys.argv[1]) if len(sys.argv) > 1 else 500_000
    print(f"trozo: {cortar_trozo(filas)} filas en {TROZO.relative_to(RAIZ)}")

    cache = PostgresCache(
        host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
        username=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        database=os.environ["PGDATABASE"], schema_name="prueba",
    )
    fuente = ab.get_source(
        "source-file", pip_url="airbyte-source-file",
        config={"dataset_name": "trozo", "format": "parquet", "url": str(TROZO),
                "provider": {"storage": "local"}},
    )
    fuente.select_all_streams()

    inicio = time.perf_counter()
    resultado = fuente.read(cache=cache, force_full_refresh=True)
    segundos = time.perf_counter() - inicio

    # ru_maxrss está en KiB en Linux. CHILDREN = el mayor subproceso (el conector).
    ram_propia = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    ram_conector = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    print(f"filas procesadas: {resultado.processed_records}")
    print(f"segundos del sync: {segundos:.1f}")
    print(f"RAM máxima del script: {ram_propia:.0f} MiB")
    print(f"RAM máxima del conector: {ram_conector:.0f} MiB")


if __name__ == "__main__":
    main()
