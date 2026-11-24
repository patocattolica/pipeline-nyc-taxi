"""Orquestación con Dagster: mes de comparación, orden de los assets y corte ante fallas.

No necesitan Postgres. Sí necesitan target/manifest.json (`dbt parse`), que `make test`
genera antes de correr pytest.
"""

import json

import pytest

from pipeline.descarga import RAIZ

if not (RAIZ / "target/manifest.json").exists():
    pytest.skip("falta target/manifest.json: correr dbt parse o make test", allow_module_level=True)

import dagster as dg  # noqa: E402

from orquestacion import definitions  # noqa: E402
from orquestacion.definitions import Periodo, correr_etapa, defs  # noqa: E402


@pytest.mark.parametrize("mes, comp", [("2025-03", "2024-03"), ("2025-01", "2024-01"),
                                       ("2000-12", "1999-12")])
def test_mes_de_comparacion_es_el_mismo_mes_del_anio_anterior(mes, comp):
    assert Periodo(mes=mes).meses == [mes, comp]


@pytest.mark.parametrize("mes", ["2025-13", "2025-3", "marzo", ""])
def test_mes_invalido_corta_antes_de_ejecutar(mes):
    with pytest.raises(dg.Failure):
        Periodo(mes=mes).setup_for_execution(None)


def test_orden_de_los_assets():
    grafo = defs.resolve_asset_graph()

    def padres(clave):
        return {p.to_user_string() for p in grafo.get(dg.AssetKey(clave)).parent_keys}

    assert padres(["raw", "yellow_trips"]) == {"descarga"}
    assert padres("stg_yellow_trips") == {"raw/yellow_trips"}
    assert padres("stg_taxi_zones") == {"raw/taxi_zones"}
    assert padres("curada") == {"trips_curados", "reporte_calidad_mes"}


def test_un_paso_por_vez():
    assert defs.resolve_job_def("pipeline_mes").executor_def is dg.in_process_executor


def test_etapa_que_sale_con_error_hace_fallar_el_asset(tmp_path, monkeypatch):
    # El log de las etapas va a un archivo temporal: no ensucia logs/pipeline.log, que lee Loki.
    monkeypatch.setattr(definitions, "LOG_PIPELINE", tmp_path / "pipeline.log")
    contexto = dg.build_asset_context()
    # Un módulo inexistente: python -m sale con código 1, igual que una etapa que falla.
    with pytest.raises(dg.Failure, match="código 1"):
        correr_etapa(contexto, "no_existe", "2025-03")


def test_las_lineas_de_las_etapas_quedan_en_el_log_json(tmp_path, monkeypatch):
    archivo = tmp_path / "logs" / "pipeline.log"
    monkeypatch.setattr(definitions, "LOG_PIPELINE", archivo)
    definitions.escribir_log(dg.build_asset_context(), "ingesta", "ya está en raw, no se ingiere")
    registro = json.loads(archivo.read_text(encoding="utf-8").splitlines()[0])
    assert registro["paso"] == "ingesta"
    assert registro["linea"] == "ya está en raw, no se ingiere"
    assert {"ts", "run_id"} <= registro.keys()

