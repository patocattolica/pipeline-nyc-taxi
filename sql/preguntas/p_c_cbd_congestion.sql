-- c. Porcentaje de viajes con cbd_congestion_fee > 0 en el mes asignado, y las 5 zonas de
-- origen con mayor proporción de esos viajes. Solo entran zonas con al menos 100 viajes en
-- el mes: sin mínimo, el ranking lo encabezan zonas con 1 o 2 viajes al 100 %.
with parametros as (
    select
        to_date('{{ var("mes") }}', 'YYYY-MM') as inicio,
        100 as viajes_minimos
),

por_zona as (
    select
        f.pu_location_id,
        count(*) as viajes,
        count(*) filter (where f.cbd_congestion_fee > 0) as viajes_cbd
    from {{ ref('fact_trips') }} as f
    join {{ ref('dim_date') }} as d on d.fecha = f.fecha
    join parametros as p on d.anio = extract(year from p.inicio) and d.mes = extract(month from p.inicio)
    group by f.pu_location_id
),

ranking as (
    select
        pu_location_id,
        viajes,
        viajes_cbd,
        -- Porcentaje de todo el mes, sobre todas las zonas (sin el mínimo de viajes).
        100.0 * sum(viajes_cbd) over () / sum(viajes) over () as pct_cbd_mes,
        100.0 * viajes_cbd / viajes as pct_cbd_zona
    from por_zona
)

select
    row_number() over (order by r.pct_cbd_zona desc, r.pu_location_id) as puesto,
    to_char(p.inicio, 'YYYY-MM') as mes,
    r.pct_cbd_mes::numeric(10, 2) as pct_cbd_mes,
    r.pu_location_id,
    z.zone,
    z.borough,
    r.viajes,
    r.viajes_cbd,
    r.pct_cbd_zona::numeric(10, 2) as pct_cbd_zona
from ranking as r
cross join parametros as p
join {{ ref('dim_zone') }} as z on z.location_id = r.pu_location_id
where r.viajes >= p.viajes_minimos
order by puesto
limit 5
