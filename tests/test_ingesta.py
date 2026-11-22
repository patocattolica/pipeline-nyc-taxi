import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline import ingesta

CONTRATO = [
    {"origen": "VendorID", "destino": "vendor_id", "tipo_parquet": "int32"},
    {"origen": "cbd_congestion_fee", "destino": "cbd_congestion_fee", "tipo_parquet": "double",
     "desde": "2025-01"},
]


class ConFalsa:
    """Hace de conexión a Postgres: guarda cada INSERT en una lista."""

    def __init__(self):
        self.inserts = []

    def execute(self, sql, params=()):
        self.inserts.append(params)


def test_saltea_solo_si_hash_y_filas_coinciden():
    assert ingesta.ya_ingerido("abc", "abc", 10, 10)
    assert not ingesta.ya_ingerido("abc", "xyz", 10, 10)  # el archivo cambió
    assert not ingesta.ya_ingerido("abc", "abc", 10, 7)  # faltan filas en la base
    assert not ingesta.ya_ingerido("abc", None, 10, 0)  # nunca se ingirió


def test_lotes_renombra_agrega_faltante_y_archivo(tmp_path):
    ruta = tmp_path / "viajes.parquet"
    pq.write_table(pa.table({"VendorID": pa.array([1, 2], pa.int32())}), ruta)  # sin cbd, como 2024

    tabla = pa.concat_tables(ingesta.lotes_viajes(ruta, CONTRATO, "data/raw/x.parquet"))

    assert tabla.column_names == ["vendor_id", "cbd_congestion_fee", "source_file"]
    assert tabla["cbd_congestion_fee"].null_count == 2
    assert tabla["cbd_congestion_fee"].type == pa.float64()
    assert tabla["source_file"].to_pylist() == ["data/raw/x.parquet"] * 2


def test_esquema_con_faltantes_corta_y_registra(tmp_path, monkeypatch):
    monkeypatch.setattr(ingesta, "RAIZ", tmp_path)
    monkeypatch.setattr(ingesta, "comparar_esquema", lambda ruta, mes: {
        "faltantes": ["Airport_fee"], "nuevas": ["airport_fee"], "tipos_distintos": []})
    con = ConFalsa()

    with pytest.raises(ingesta.IngestaFallida):
        ingesta.validar_esquema(con, tmp_path / "viajes.parquet", "2025-03")
    assert con.inserts[0][4] == "error"  # (archivo, filas, bytes, hash, estado, mensaje)


def test_esquema_con_solo_columnas_nuevas_avisa_y_sigue(tmp_path, monkeypatch):
    monkeypatch.setattr(ingesta, "RAIZ", tmp_path)
    monkeypatch.setattr(ingesta, "comparar_esquema", lambda ruta, mes: {
        "faltantes": [], "nuevas": ["columna_nueva"], "tipos_distintos": []})
    con = ConFalsa()

    ingesta.validar_esquema(con, tmp_path / "viajes.parquet", "2025-03")  # no lanza
    assert con.inserts == []
