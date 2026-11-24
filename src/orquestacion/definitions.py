"""Paso 16: orquestación del pipeline con Dagster.

Una corrida procesa el mes asignado y el mismo mes del año anterior, en este orden de assets:
descarga -> raw/yellow_trips y raw/taxi_zones (ingesta) -> modelos de dbt -> curada.

Uso (desde la raíz, con las variables PG* cargadas y target/manifest.json generado por
`dbt parse`; `make all MES=2025-03` hace todo eso):
    dagster asset materialize -m orquestacion.definitions --select '*' \
        --config-json '{"resources": {"periodo": {"config": {"mes": "2025-03"}}}}'

Las etapas de descarga, ingesta y curada se ejecutan con su propio comando
(`python -m pipeline.<etapa> --mes AAAA-MM`): conservan toda su lógica (contrato, salteo por
hash, reconciliación, ingestion_log) y su código de salida decide si el asset falla.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import dagster as dg
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets, get_asset_key_for_model

from pipeline.curada import ruta_particion
from pipeline.descarga import RAIZ, contar_filas, ruta_parquet, sha256_de

PROYECTO_DBT = DbtProject(project_dir=RAIZ)
# El dbt del mismo entorno virtual que corre Dagster, sin depender del PATH.
# En Windows el ejecutable se llama dbt.exe.
DBT_EJECUTABLE = str(Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt"))


class Periodo(dg.ConfigurableResource):
    """Mes asignado (AAAA-MM). El de comparación es el mismo mes del año anterior."""

    mes: str

    def setup_for_execution(self, context):
        # Se valida al iniciar la corrida, antes de ejecutar cualquier asset.
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", self.mes):
            raise dg.Failure(f"'{self.mes}' no tiene el formato AAAA-MM, por ejemplo 2025-03")

    @property
    def mes_comp(self):
        anio, m = self.mes.split("-")
        return f"{int(anio) - 1}-{m}"

    @property
    def meses(self):
        # Mismo orden que el Makefile del paso 14: primero el asignado, después el de comparación.
        return [self.mes, self.mes_comp]


def correr_etapa(context, modulo, mes):
    """Ejecuta `python -m pipeline.<modulo> --mes <mes>` y falla si sale con código distinto de 0."""
    comando = [sys.executable, "-m", f"pipeline.{modulo}", "--mes", mes]
    # PYTHONUNBUFFERED y PYTHONIOENCODING hacen que la salida llegue línea a línea y en UTF-8
    # aunque no vaya a una terminal.
    entorno = {
        **os.environ,
        "PYTHONPATH": str(RAIZ / "src"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    context.log.info("Ejecuta: " + " ".join(comando[1:]))
    # La salida de la etapa (incluidos los logs de dlt) se reenvía al log de Dagster, así
    # queda en la corrida de la interfaz y no solo en la terminal.
    with subprocess.Popen(
        comando,
        cwd=RAIZ,
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as proceso:
        for linea in proceso.stdout:
            if linea.strip():
                context.log.info(linea.rstrip())
    if proceso.returncode != 0:
        raise dg.Failure(
            f"pipeline.{modulo} --mes {mes} salió con código {proceso.returncode}"
        )


def huella(ruta):
    """Filas y sha256 de un archivo, para mostrarlos como metadata en Dagster."""
    return {"filas": contar_filas(ruta), "sha256": sha256_de(ruta)}


@dg.asset(group_name="ingesta", description="Parquet del mes en data/raw y tabla de zonas.")
def descarga(context: dg.AssetExecutionContext, periodo: Periodo) -> dg.MaterializeResult:
    for mes in periodo.meses:
        correr_etapa(context, "descarga", mes)
    return dg.MaterializeResult(
        metadata={mes: dg.MetadataValue.json(huella(ruta_parquet(mes))) for mes in periodo.meses}
    )


# Las claves coinciden con las sources de dbt (sql/staging/sources.yml): así dagster-dbt
# conecta los modelos de staging con este asset sin configuración extra.
@dg.multi_asset(
    group_name="ingesta",
    specs=[
        dg.AssetSpec(["raw", "yellow_trips"], deps=[descarga], description="Viajes en Postgres."),
        dg.AssetSpec(["raw", "taxi_zones"], deps=[descarga], description="Zonas en Postgres."),
    ],
)
def ingesta(context: dg.AssetExecutionContext, periodo: Periodo):
    for mes in periodo.meses:
        correr_etapa(context, "ingesta", mes)
    yield dg.MaterializeResult(asset_key=["raw", "yellow_trips"], metadata={"meses": periodo.meses})
    yield dg.MaterializeResult(asset_key=["raw", "taxi_zones"])


class AlLogDeDagster:
    """Archivo de texto que manda cada línea escrita al log de eventos de Dagster.

    dagster-dbt escribe el texto de dbt ("1 of 65 START ...", los errores de la base) en
    sys.stdout. Ahí solo se ve si Dagster captura stdout, y en Windows no lo hace. Con esto
    llega como INFO a la corrida, en vivo y en cualquier sistema.
    """

    _COLOR = re.compile(r"\x1b\[[0-9;]*m")

    def __init__(self, log):
        self._log = log
        self._pendiente = ""

    def write(self, texto):
        *lineas, self._pendiente = (self._pendiente + texto).split("\n")
        for linea in lineas:
            linea = self._COLOR.sub("", linea).rstrip()
            if linea:
                self._log.info(linea)
        return len(texto)

    def flush(self):
        pass


@dbt_assets(manifest=PROYECTO_DBT.manifest_path, project=PROYECTO_DBT)
def modelos_dbt(context: dg.AssetExecutionContext, dbt: DbtCliResource, periodo: Periodo):
    # Un solo `dbt build`, como en el paso 14. Si falla un test (la reconciliación incluida),
    # dbt sale con código 1, dagster-dbt lanza un error y la curada no se ejecuta.
    with contextlib.redirect_stdout(AlLogDeDagster(context.log)):
        yield from dbt.cli(
            ["build", "--vars", json.dumps({"mes": periodo.mes})], context=context
        ).stream()


@dg.asset(
    group_name="curada",
    deps=[
        get_asset_key_for_model([modelos_dbt], "trips_curados"),
        get_asset_key_for_model([modelos_dbt], "reporte_calidad_mes"),
    ],
    description="data/curated/yellow/year=AAAA/month=MM/trips.parquet de cada mes.",
)
def curada(context: dg.AssetExecutionContext, periodo: Periodo) -> dg.MaterializeResult:
    for mes in periodo.meses:
        correr_etapa(context, "curada", mes)
    return dg.MaterializeResult(
        metadata={mes: dg.MetadataValue.json(huella(ruta_particion(mes))) for mes in periodo.meses}
    )


# El mismo grafo como job, para lanzarlo desde la interfaz (make ui).
pipeline_mes = dg.define_asset_job(
    "pipeline_mes",
    selection=dg.AssetSelection.all(),
    description="Mes asignado y su mes de comparación, de la descarga a la capa curada.",
)

defs = dg.Definitions(
    assets=[descarga, ingesta, modelos_dbt, curada],
    jobs=[pipeline_mes],
    # Un paso por vez, en el mismo proceso: con 8 GB de RAM no se corren etapas pesadas en
    # paralelo. Vale para toda corrida (make all, el job y la interfaz).
    executor=dg.in_process_executor,
    resources={
        "dbt": DbtCliResource(project_dir=PROYECTO_DBT, dbt_executable=DBT_EJECUTABLE),
        "periodo": Periodo.configure_at_launch(),
    },
)
