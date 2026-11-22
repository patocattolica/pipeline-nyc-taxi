"""Parte 2: comparación del esquema real de un Parquet contra el contrato."""

from pathlib import Path

import pyarrow.parquet as pq
import yaml

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO = RAIZ / "contracts/yellow_schema.yaml"


def comparar_esquema(ruta_parquet, mes, ruta_contrato=CONTRATO):
    real = {campo.name: str(campo.type) for campo in pq.read_schema(ruta_parquet)}
    with open(ruta_contrato) as f:
        contrato = yaml.safe_load(f)["columnas"]

    faltantes, tipos_distintos = [], []
    for col in contrato:
        nombre = col["origen"]
        if nombre not in real:
            if mes >= col.get("desde", "0000-00"):  # antes de 'desde', que falte es esperado
                faltantes.append(nombre)
        elif real[nombre] != col["tipo_parquet"]:
            tipos_distintos.append((nombre, col["tipo_parquet"], real[nombre]))

    esperadas = {col["origen"] for col in contrato}
    nuevas = [nombre for nombre in real if nombre not in esperadas]

    return {"faltantes": faltantes, "nuevas": nuevas, "tipos_distintos": tipos_distintos}
