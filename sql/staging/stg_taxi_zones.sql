select
    location_id::smallint as location_id,
    borough,
    zone,
    service_zone
from {{ source('raw', 'taxi_zones') }}
