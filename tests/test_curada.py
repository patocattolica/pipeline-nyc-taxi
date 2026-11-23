import hashlib

import duckdb

from pipeline import curada


def sha256(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_reprocesar_un_mes_reemplaza_solo_su_particion(tmp_path):
    con = duckdb.connect()
    con.execute("CREATE TABLE viajes AS SELECT * FROM (VALUES ('2025-03', 1), ('2025-03', 2), "
                "('2024-03', 3)) AS t(mes, x)")
    marzo_25 = tmp_path / "year=2025/month=03/trips.parquet"
    marzo_24 = tmp_path / "year=2024/month=03/trips.parquet"

    assert curada.escribir_particion(
        con, "SELECT x FROM viajes WHERE mes = '2025-03' ORDER BY x", marzo_25) == 2
    assert curada.escribir_particion(
        con, "SELECT x FROM viajes WHERE mes = '2024-03' ORDER BY x", marzo_24) == 1
    huella_24 = sha256(marzo_24)

    # Cambian los datos de 2025 y se reprocesa solo ese mes.
    con.execute("DELETE FROM viajes WHERE x = 2")
    assert curada.escribir_particion(
        con, "SELECT x FROM viajes WHERE mes = '2025-03' ORDER BY x", marzo_25) == 1

    assert sha256(marzo_24) == huella_24  # la otra partición no se tocó
    assert not list(tmp_path.rglob("*.tmp"))  # no quedan temporales
