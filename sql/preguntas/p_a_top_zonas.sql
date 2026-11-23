-- a. Las 10 zonas de origen con más viajes en el mes asignado y su variación contra el
-- mismo mes del año anterior.
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
),

viajes_zona as (
    select
        a.pu_location_id,
        sum(a.viajes) filter (where m.periodo = 'asignado') as viajes_asignado,
        sum(a.viajes) filter (where m.periodo = 'comparacion') as viajes_comparacion
    from {{ ref('agg_zone_hour') }} as a
    join {{ ref('dim_date') }} as d on d.fecha = a.fecha
    join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
    group by a.pu_location_id
)

select
    row_number() over (order by v.viajes_asignado desc, v.pu_location_id) as puesto,
    v.pu_location_id,
    z.zone,
    z.borough,
    v.viajes_asignado,
    coalesce(v.viajes_comparacion, 0) as viajes_comparacion,
    v.viajes_asignado - coalesce(v.viajes_comparacion, 0) as variacion,
    -- Nula si la zona no tuvo viajes en el mes de comparación.
    (100.0 * (v.viajes_asignado - v.viajes_comparacion)
        / nullif(v.viajes_comparacion, 0))::numeric(10, 2) as variacion_pct
from viajes_zona as v
join {{ ref('dim_zone') }} as z on z.location_id = v.pu_location_id
where v.viajes_asignado is not null
order by puesto
limit 10
