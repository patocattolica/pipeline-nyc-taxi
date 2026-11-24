# Pipeline de taxis amarillos de NYC. Uso: make all MES=2025-03
# Make prepara el entorno (.env, entorno virtual, Postgres y manifiesto de dbt) y Dagster
# corre las etapas para MES y el mismo mes del año anterior, en este orden:
# descarga -> ingesta -> transformacion (dbt build) -> curada.
# Si una etapa falla, la corrida de Dagster falla y make sale con código distinto de 0.

# Credenciales de Postgres (PGHOST, PGPORT, ...) para todos los comandos. Si no hay .env,
# Make lo crea con la regla de abajo y vuelve a leer este archivo.
-include .env
export

# Entorno virtual: se crea con PYTHON_BASE (Python 3.11) solo si no existe.
# En Windows (la variable de entorno OS vale Windows_NT) el venv deja los ejecutables en
# Scripts/ con extensión .exe, y Python 3.11 se invoca con el lanzador "py -3.11". Hay que
# correr make desde Git Bash (o cualquier shell con sh y grep en el PATH). Con la extensión
# .exe en las rutas, Make reconoce que el venv ya existe y no lo recrea en cada corrida.
ifeq ($(OS),Windows_NT)
PYTHON_BASE ?= py -3.11
VENV_BIN ?= Scripts
EXE ?= .exe
# Click expande los comodines en Windows: --select '*' se convertiría en la lista de
# archivos de la carpeta. key:"*" selecciona todos los assets y Click lo deja intacto.
SELECCION ?= key:"*"
else
PYTHON_BASE ?= python3.11
VENV_BIN ?= bin
EXE ?=
SELECCION ?= *
endif
VENV ?= .venv-dlt
PYTHON := $(VENV)/$(VENV_BIN)/python$(EXE)
DBT := $(VENV)/$(VENV_BIN)/dbt$(EXE)
DAGSTER := $(VENV)/$(VENV_BIN)/dagster$(EXE)
PYTHONPATH := src
# Estado de Dagster (corridas, logs): fuera de los datos y fuera de Git.
DAGSTER_HOME := $(CURDIR)/dagster_home
DEFINICIONES := -m orquestacion.definitions

MES ?=

.PHONY: all revisar-mes postgres manifiesto dagster-home ui test conteos

# El mes de comparación lo calcula Dagster (recurso periodo en src/orquestacion/definitions.py).
all: revisar-mes postgres manifiesto dagster-home
	$(DAGSTER) asset materialize $(DEFINICIONES) --select '$(SELECCION)' \
		--config-json '{"resources": {"periodo": {"config": {"mes": "$(MES)"}}}}'

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

# dagster-dbt lee target/manifest.json para armar un asset por modelo. dbt parse no se
# conecta a la base y tarda unos segundos; se corre siempre, así refleja los últimos cambios.
manifiesto: | $(PYTHON)
	$(DBT) parse --quiet

# Un dagster.yaml vacío le confirma a Dagster que guarde todo en DAGSTER_HOME (si falta, avisa).
dagster-home:
	@mkdir -p "$(DAGSTER_HOME)"
	@touch "$(DAGSTER_HOME)/dagster.yaml"

# Interfaz de Dagster en http://localhost:3000, con el historial de corridas de make all.
ui: postgres manifiesto dagster-home
	$(DAGSTER) dev $(DEFINICIONES)

test: manifiesto
	$(PYTHON) -m pytest -q

# Conteos para comparar dos corridas: reporte de calidad, filas del modelo y huella de la curada.
conteos: revisar-mes
	@docker compose exec -T postgres psql -U "$$PGUSER" -d "$$PGDATABASE" \
		-c "select mes, filas_leidas, filas_aceptadas, filas_cuarentena, diferencia from analytics.reporte_calidad_mes order by mes" \
		-c "select d.anio, d.mes, count(*) as filas_fact_trips from analytics.fact_trips f join analytics.dim_date d using (fecha) group by 1, 2 order by 1, 2"
	@sha256sum data/curated/yellow/year=*/month=*/trips.parquet
