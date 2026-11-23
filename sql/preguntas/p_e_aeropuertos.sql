-- e. Viajes y tarifa media de los que empiezan o terminan en JFK o LaGuardia, identificados
-- por nombre de zona, en los dos meses. Un viaje entre los dos aeropuertos cuenta en cada
-- uno, pero una sola vez en el total.
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
),

viajes_aeropuerto as (
    select
        m.periodo,
        m.inicio,
        f.trip_id,
        f.fare_amount,
        zpu.zone as pu_zone,
        zdo.zone as do_zone
    from {{ ref('fact_trips') }} as f
    join {{ ref('dim_date') }} as d on d.fecha = f.fecha
    join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
    join {{ ref('dim_zone') }} as zpu on zpu.location_id = f.pu_location_id
    join {{ ref('dim_zone') }} as zdo on zdo.location_id = f.do_location_id
    where zpu.zone in ('JFK Airport', 'LaGuardia Airport')
       or zdo.zone in ('JFK Airport', 'LaGuardia Airport')
),

-- Una fila por viaje y aeropuerto: si empieza y termina en el mismo, cuenta una vez.
por_aeropuerto as (
    select v.periodo, v.inicio, v.fare_amount, a.aeropuerto
    from viajes_aeropuerto as v
    cross join (values ('JFK Airport'), ('LaGuardia Airport')) as a (aeropuerto)
    where a.aeropuerto in (v.pu_zone, v.do_zone)
),

resultado as (
    select periodo, inicio, aeropuerto, count(*) as viajes, avg(fare_amount) as tarifa_media
    from por_aeropuerto
    group by periodo, inicio, aeropuerto

    union all

    select periodo, inicio, 'JFK o LaGuardia', count(*), avg(fare_amount)
    from viajes_aeropuerto
    group by periodo, inicio
)

select
    to_char(inicio, 'YYYY-MM') as mes,
    periodo,
    aeropuerto,
    viajes,
    tarifa_media::numeric(10, 2) as tarifa_media
from resultado
order by mes, aeropuerto
