{{ config(materialized='table') }}

-- Reporte de calidad por mes y reconciliación de conteos. Las filas leídas salen de la tabla
-- cruda (que la ingesta ya reconcilió contra el Parquet), no del staging: así el control
-- compara contra una fuente independiente de las transformaciones de dbt.
with leidas as (
    select source_file, count(*) as filas_leidas
    from {{ source('raw', 'yellow_trips') }}
    group by source_file
),

aceptadas as (
    select source_file, count(*) as filas_aceptadas
    from {{ ref('trips_aceptados') }}
    group by source_file
),

cuarentena as (
    select source_file, count(*) as filas_cuarentena
    from {{ ref('trips_cuarentena') }}
    group by source_file
)

select
    substring(l.source_file from 'year=(\d{4})') || '-'
        || substring(l.source_file from 'month=(\d{2})') as mes,
    l.source_file,
    l.filas_leidas,
    coalesce(a.filas_aceptadas, 0) as filas_aceptadas,
    coalesce(q.filas_cuarentena, 0) as filas_cuarentena,
    round(100.0 * coalesce(q.filas_cuarentena, 0) / l.filas_leidas, 2) as pct_cuarentena,
    -- Tiene que dar 0: si no, se perdieron o se duplicaron filas en la capa de calidad.
    l.filas_leidas - coalesce(a.filas_aceptadas, 0) - coalesce(q.filas_cuarentena, 0) as diferencia
from leidas as l
left join aceptadas as a using (source_file)
left join cuarentena as q using (source_file)
