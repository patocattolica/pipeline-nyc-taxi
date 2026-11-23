{{ config(materialized='table') }}

-- Cantidad de filas por regla y por mes. Incluye las reglas sin casos (con 0), para que el
-- reporte muestre todas aunque un mes no viole alguna.
with violaciones as (
    select
        source_file,
        unnest(string_to_array(reglas_rechazo, ',') || string_to_array(flags, ',')) as regla_id
    from {{ ref('int_calidad') }}
    where reglas_rechazo <> '' or flags <> ''
),

conteos as (
    select source_file, regla_id, count(*) as filas
    from violaciones
    group by source_file, regla_id
)

select
    m.mes,
    r.id as regla_id,
    r.descripcion,
    r.severidad,
    coalesce(c.filas, 0) as filas,
    round(100.0 * coalesce(c.filas, 0) / m.filas_leidas, 3) as pct_leidas
from {{ ref('reporte_calidad_mes') }} as m
cross join {{ ref('reglas_calidad') }} as r
left join conteos as c on c.source_file = m.source_file and c.regla_id = r.id
