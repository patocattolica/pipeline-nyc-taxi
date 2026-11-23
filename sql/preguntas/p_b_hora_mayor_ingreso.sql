-- b. La hora del día con mayor ingreso promedio por viaje, en cada uno de los dos meses.
-- El promedio es ingreso total / viajes de la hora: no se promedian los promedios de agg_zone_hour.
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
),

por_hora as (
    select
        m.periodo,
        m.inicio,
        a.hora,
        sum(a.viajes) as viajes,
        sum(a.ingreso_total) as ingreso_total
    from {{ ref('agg_zone_hour') }} as a
    join {{ ref('dim_date') }} as d on d.fecha = a.fecha
    join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
    group by m.periodo, m.inicio, a.hora
),

ranking as (
    select
        periodo,
        inicio,
        hora,
        viajes,
        (ingreso_total / viajes)::numeric(10, 2) as ingreso_promedio,
        -- Ingreso promedio de todo el mes, como referencia.
        (sum(ingreso_total) over (partition by periodo)
            / sum(viajes) over (partition by periodo))::numeric(10, 2) as ingreso_promedio_mes,
        row_number() over (partition by periodo order by ingreso_total / viajes desc, hora) as puesto
    from por_hora
)

select
    to_char(inicio, 'YYYY-MM') as mes,
    periodo,
    hora,
    viajes,
    ingreso_promedio,
    ingreso_promedio_mes
from ranking
where puesto = 1
order by mes
