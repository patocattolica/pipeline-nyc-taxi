-- d. Propina promedio como porcentaje de la tarifa, por tipo de pago, en los dos meses.
-- propina_pct_promedio promedia el porcentaje de cada viaje; propina_pct_global es el total
-- de propinas sobre el total de tarifas, que no se deja arrastrar por tarifas de centavos.
-- La propina en efectivo (2) no se registra: su 0 % no es interpretable.
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
)

select
    to_char(m.inicio, 'YYYY-MM') as mes,
    m.periodo,
    f.payment_type,
    case f.payment_type
        when 0 then 'Flex Fare'
        when 1 then 'Tarjeta de crédito'
        when 2 then 'Efectivo'
        when 3 then 'Sin cargo'
        when 4 then 'Disputa'
        when 5 then 'Desconocido'
        when 6 then 'Viaje anulado'
    end as tipo_pago,
    count(*) as viajes,
    -- propina_pct es nula si la tarifa no es positiva: esos viajes no entran en el promedio.
    count(f.propina_pct) as viajes_con_tarifa,
    avg(f.propina_pct)::numeric(10, 2) as propina_pct_promedio,
    (100 * sum(f.tip_amount) filter (where f.fare_amount > 0)
        / nullif(sum(f.fare_amount) filter (where f.fare_amount > 0), 0))::numeric(10, 2)
        as propina_pct_global
from {{ ref('fact_trips') }} as f
join {{ ref('dim_date') }} as d on d.fecha = f.fecha
join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
group by m.inicio, m.periodo, f.payment_type
order by mes, f.payment_type
