-- Falla si el mes asignado (variable mes) o el mismo mes del año anterior no están cargados.
-- Sin este control, las preguntas darían tablas vacías sin avisar.
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
)

select m.periodo, m.inicio
from meses as m
where not exists (
    select 1
    from {{ ref('dim_date') }} as d
    where d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
)
