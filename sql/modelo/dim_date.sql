-- Dimensión de fechas: una fila por día de cada mes cargado. Los meses salen de la ruta
-- del archivo (source_file) y no de pickup_at, que en las filas de R01 cae fuera del mes.
with meses as (
    select distinct
        make_date(
            substring(source_file from 'year=(\d{4})')::int,
            substring(source_file from 'month=(\d{2})')::int,
            1
        ) as inicio_mes
    from {{ ref('stg_yellow_trips') }}
),

dias as (
    select d::date as fecha
    from meses
    cross join lateral generate_series(
        inicio_mes,
        inicio_mes + interval '1 month' - interval '1 day',
        interval '1 day'
    ) as d
)

select
    fecha,
    extract(year from fecha)::smallint as anio,
    extract(month from fecha)::smallint as mes,
    extract(day from fecha)::smallint as dia,
    extract(isodow from fecha)::smallint as dia_semana,  -- 1 = lunes ... 7 = domingo
    (array['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'])
        [extract(isodow from fecha)::int] as nombre_dia,
    extract(isodow from fecha) in (6, 7) as es_fin_de_semana
from dias
