{{ config(materialized='table') }}

-- Solo renombra y convierte tipos: no limpia ni filtra (las reglas van en la capa de calidad).
with crudo as (
    select
        t.*,
        -- Texto de la fila cruda completa, source_file incluido: un nulo queda como campo vacío,
        -- así (NULL, 1) y (1, NULL) dan textos distintos. Se calcula antes de convertir tipos.
        md5(t::text) as row_hash
    from {{ source('raw', 'yellow_trips') }} as t
),

numerado as (
    select
        *,
        -- Copias de una misma fila: son idénticas, así que cualquier orden da el mismo resultado.
        row_number() over (partition by row_hash) as dup_n
    from crudo
)

select
    md5(row_hash || '-' || dup_n) as trip_id,
    row_hash,
    dup_n::smallint as dup_n,
    source_file,
    vendor_id::smallint as vendor_id,
    tpep_pickup_datetime as pickup_at,
    tpep_dropoff_datetime as dropoff_at,
    passenger_count::smallint as passenger_count,
    trip_distance::numeric(10, 2) as trip_distance,
    ratecode_id::smallint as ratecode_id,
    store_and_fwd_flag::char(1) as store_and_fwd_flag,
    pu_location_id::smallint as pu_location_id,
    do_location_id::smallint as do_location_id,
    payment_type::smallint as payment_type,
    fare_amount::numeric(10, 2) as fare_amount,
    extra::numeric(10, 2) as extra,
    mta_tax::numeric(10, 2) as mta_tax,
    tip_amount::numeric(10, 2) as tip_amount,
    tolls_amount::numeric(10, 2) as tolls_amount,
    improvement_surcharge::numeric(10, 2) as improvement_surcharge,
    total_amount::numeric(10, 2) as total_amount,
    congestion_surcharge::numeric(10, 2) as congestion_surcharge,
    airport_fee::numeric(10, 2) as airport_fee,
    cbd_congestion_fee::numeric(10, 2) as cbd_congestion_fee
from numerado
