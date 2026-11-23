-- Tabla agregada: una fila por zona de origen, fecha y hora con al menos un viaje.
-- Viajes e ingreso cuentan todos los viajes; la duración media excluye los de R18.
select
    pu_location_id,
    fecha,
    hora,
    count(*) as viajes,
    sum(total_amount) as ingreso_total,
    (avg(duracion_min) filter (where duracion_confiable))::numeric(10, 2) as duracion_media_min,
    -- Para promediar varias horas hay que ponderar por este conteo, no promediar promedios.
    count(*) filter (where duracion_confiable) as viajes_con_duracion
from {{ ref('fact_trips') }}
group by pu_location_id, fecha, hora
