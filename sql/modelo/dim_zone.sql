-- Dimensión de zonas: una fila por zona de la TLC. Entran las 265, también 264 y 265
-- (desconocidas): R10 es advertencia y hay viajes aceptados que las usan.
select
    location_id,
    borough,
    zone,
    service_zone
from {{ ref('stg_taxi_zones') }}
