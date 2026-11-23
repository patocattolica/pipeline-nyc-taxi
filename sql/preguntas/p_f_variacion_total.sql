-- f. Variación de viajes totales y de tarifa media entre el mes de comparación y el asignado.
-- Cuenta los viajes aceptados (fact_trips); la tarifa es fare_amount.
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
),

por_mes as (
    select
        m.periodo,
        m.inicio,
        count(*) as viajes,
        avg(f.fare_amount) as tarifa_media
    from {{ ref('fact_trips') }} as f
    join {{ ref('dim_date') }} as d on d.fecha = f.fecha
    join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
    group by m.periodo, m.inicio
)

select
    to_char(c.inicio, 'YYYY-MM') as mes_comparacion,
    to_char(a.inicio, 'YYYY-MM') as mes_asignado,
    c.viajes as viajes_comparacion,
    a.viajes as viajes_asignado,
    a.viajes - c.viajes as variacion_viajes,
    (100.0 * (a.viajes - c.viajes) / c.viajes)::numeric(10, 2) as variacion_viajes_pct,
    c.tarifa_media::numeric(10, 2) as tarifa_media_comparacion,
    a.tarifa_media::numeric(10, 2) as tarifa_media_asignado,
    (a.tarifa_media - c.tarifa_media)::numeric(10, 2) as variacion_tarifa,
    (100 * (a.tarifa_media - c.tarifa_media) / c.tarifa_media)::numeric(10, 2) as variacion_tarifa_pct
from por_mes as a
join por_mes as c on c.periodo = 'comparacion'
where a.periodo = 'asignado'
