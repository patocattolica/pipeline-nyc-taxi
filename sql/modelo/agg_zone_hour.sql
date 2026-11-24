-- Tabla agregada: una fila por zona de origen, fecha y hora con al menos un viaje.
-- Viajes e ingreso_total cuentan todos los viajes; la duración media excluye R03 y R18, y el
-- ingreso confiable excluye R19 (ver fact_trips).
select
    pu_location_id,
    fecha,
    hora,
    count(*) as viajes,
    sum(total_amount) as ingreso_total,
    -- Para el ingreso promedio por viaje: ingreso_confiable / viajes_con_importe.
    sum(total_amount) filter (where importe_confiable) as ingreso_confiable,
    count(*) filter (where importe_confiable) as viajes_con_importe,
    (avg(duracion_min) filter (where duracion_confiable))::numeric(10, 2) as duracion_media_min,
    -- Para promediar varias horas hay que ponderar por este conteo, no promediar promedios.
    count(*) filter (where duracion_confiable) as viajes_con_duracion
from {{ ref('fact_trips') }}
group by pu_location_id, fecha, hora
