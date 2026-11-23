-- Falla si la tabla agregada perdió o duplicó viajes: la suma de viajes y de ingreso de
-- agg_zone_hour tiene que ser igual al total de fact_trips.
with agregada as (
    select sum(viajes) as viajes, sum(ingreso_total) as ingreso
    from {{ ref('agg_zone_hour') }}
),

hechos as (
    select count(*) as viajes, sum(total_amount) as ingreso
    from {{ ref('fact_trips') }}
)

select a.viajes as viajes_agg, h.viajes as viajes_fact, a.ingreso as ingreso_agg, h.ingreso as ingreso_fact
from agregada as a
cross join hechos as h
where a.viajes <> h.viajes or a.ingreso <> h.ingreso
