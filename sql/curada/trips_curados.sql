-- Viajes aceptados con las columnas derivadas y los nombres de zona. Es una vista: la lee
-- src/pipeline/curada.py de a un mes y la escribe en Parquet (data/curated/).
select
    t.trip_id,
    t.source_file,
    t.vendor_id,
    t.pickup_at,
    t.dropoff_at,
    t.passenger_count,
    t.trip_distance,
    t.ratecode_id,
    t.store_and_fwd_flag,
    t.pu_location_id,
    zpu.borough as pu_borough,
    zpu.zone as pu_zone,
    t.do_location_id,
    zdo.borough as do_borough,
    zdo.zone as do_zone,
    t.payment_type,
    t.fare_amount,
    t.extra,
    t.mta_tax,
    t.tip_amount,
    t.tolls_amount,
    t.improvement_surcharge,
    t.total_amount,
    t.congestion_surcharge,
    t.airport_fee,
    t.cbd_congestion_fee,
    t.flags,
    -- Derivadas. Las aceptadas tienen bajada posterior a la subida (R02 y R03 rechazan).
    (extract(epoch from t.dropoff_at - t.pickup_at) / 60.0)::numeric(10, 2) as duracion_min,
    -- El cast va afuera del CASE: adentro, Postgres pierde los decimales fijados.
    (case when t.dropoff_at > t.pickup_at
          then t.trip_distance / (extract(epoch from t.dropoff_at - t.pickup_at) / 3600.0)
     end)::numeric(10, 2) as velocidad_mph,
    t.pickup_at::date as fecha,
    extract(hour from t.pickup_at)::smallint as hora,
    extract(isodow from t.pickup_at)::smallint as dia_semana,  -- 1 = lunes ... 7 = domingo
    -- Nulo si la tarifa no es positiva. Solo es interpretable con tarjeta (payment_type 1):
    -- la propina en efectivo no se registra y queda en 0.
    (case when t.fare_amount > 0 then 100 * t.tip_amount / t.fare_amount end)::numeric(10, 2) as propina_pct
from {{ ref('trips_aceptados') }} as t
left join {{ ref('stg_taxi_zones') }} as zpu on zpu.location_id = t.pu_location_id
left join {{ ref('stg_taxi_zones') }} as zdo on zdo.location_id = t.do_location_id
