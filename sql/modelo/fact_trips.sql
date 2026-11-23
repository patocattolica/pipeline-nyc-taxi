-- Tabla de hechos: una fila por viaje aceptado. Lleva las claves hacia dim_date y dim_zone
-- y las medidas; los nombres de zona y los atributos de la fecha viven en las dimensiones.
select
    trip_id,
    fecha,
    hora,
    pu_location_id,
    do_location_id,
    vendor_id,
    ratecode_id,
    payment_type,
    passenger_count,
    trip_distance,
    fare_amount,
    extra,
    mta_tax,
    tip_amount,
    tolls_amount,
    improvement_surcharge,
    total_amount,
    congestion_surcharge,
    airport_fee,
    cbd_congestion_fee,
    duracion_min,
    velocidad_mph,
    propina_pct,
    flags,
    -- Las métricas de duración y velocidad excluyen los viajes de menos de 1 minuto (R18).
    not ('R18' = any(string_to_array(flags, ','))) as duracion_confiable,
    -- Los promedios de fare_amount excluyen las tarifas negativas con total positivo (R19).
    not ('R19' = any(string_to_array(flags, ','))) as tarifa_confiable
from {{ ref('trips_curados') }}
