# Pipeline de taxis amarillos de NYC. Uso: make all MES=2025-03
# Procesa MES y el mismo mes del año anterior (MES_COMP), en este orden de etapas:
# postgres -> descarga -> ingesta -> transformacion (dbt) -> curada.
# Make corta en el primer comando que sale con código distinto de 0.

# Credenciales de Postgres (PGHOST, PGPORT, ...) para todos los comandos. Si no hay .env,
# Make lo crea con la regla de abajo y vuelve a leer este archivo.
-include .env
export

# Entorno virtual: se crea con PYTHON_BASE (Python 3.11) solo si no existe.
PYTHON_BASE ?= python3.11
VENV ?= .venv-dlt
PYTHON := $(VENV)/bin/python
DBT := $(VENV)/bin/dbt
PYTHONPATH := src

MES ?=
# Mismo mes del año anterior: 2025-03 -> 2024-03. Vacío si no se pasó MES.
MES_COMP := $(if $(MES),$(shell expr $(word 1,$(subst -, ,$(MES))) - 1)-$(word 2,$(subst -, ,$(MES))))

.PHONY: all revisar-mes postgres descarga ingesta transformacion curada test conteos

all: curada

revisar-mes:
	@echo "$(MES)" | grep -Eq '^[0-9]{4}-(0[1-9]|1[0-2])$$' \
		|| { echo "Falta MES=AAAA-MM, por ejemplo: make all MES=2025-03"; exit 1; }

.env:
	cp .env.example .env
	@echo "AVISO: no había .env; se copió .env.example (credenciales del Postgres local)"

$(PYTHON):
	$(PYTHON_BASE) -m venv $(VENV)
	$(PYTHON) -m pip install -r requirements.lock

# Levanta Postgres y espera a que el healthcheck dé bien. Si ya está corriendo, no hace nada.
postgres:
	docker compose up -d --wait

# "| $(PYTHON)": hace falta que el entorno exista, pero no se rehace si cambia su fecha.
descarga: revisar-mes postgres | $(PYTHON)
	$(PYTHON) -m pipeline.descarga --mes $(MES)
	$(PYTHON) -m pipeline.descarga --mes $(MES_COMP)

ingesta: descarga
	$(PYTHON) -m pipeline.ingesta --mes $(MES)
	$(PYTHON) -m pipeline.ingesta --mes $(MES_COMP)

# Staging, reglas de calidad, cuarentena, reporte, modelo estrella y preguntas, con sus tests.
# Si la reconciliación de conteos falla, dbt sale con error y no se escribe la capa curada.
transformacion: ingesta
	$(DBT) build --vars '{mes: "$(MES)"}'

curada: transformacion
	$(PYTHON) -m pipeline.curada --mes $(MES)
	$(PYTHON) -m pipeline.curada --mes $(MES_COMP)

test: | $(PYTHON)
	$(PYTHON) -m pytest -q

# Conteos para comparar dos corridas: reporte de calidad, filas del modelo y huella de la curada.
conteos: revisar-mes
	@docker compose exec -T postgres psql -U "$$PGUSER" -d "$$PGDATABASE" \
		-c "select mes, filas_leidas, filas_aceptadas, filas_cuarentena, diferencia from analytics.reporte_calidad_mes order by mes" \
		-c "select d.anio, d.mes, count(*) as filas_fact_trips from analytics.fact_trips f join analytics.dim_date d using (fecha) group by 1, 2 order by 1, 2"
	@sha256sum data/curated/yellow/year=*/month=*/trips.parquet
