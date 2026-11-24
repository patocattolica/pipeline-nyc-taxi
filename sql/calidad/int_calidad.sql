{{ config(materialized='table') }}

-- Evalúa las 23 reglas sobre cada viaje. No descarta filas: separa las reglas violadas en
-- rechazos y advertencias según la severidad del catálogo (seeds/reglas_calidad.csv).
-- También calcula la duración real del viaje (duracion_seg), que usa la capa curada.
with parametros as (
    -- El catálogo en una sola fila: umbrales y lista de reglas que rechazan.
    select
        max(umbral) filter (where id = 'R05') as distancia_max,
        max(umbral) filter (where id = 'R16') as velocidad_max,
        max(umbral) filter (where id = 'R17') as duracion_max_min,
        max(umbral_2) filter (where id = 'R17') as tarifa_min_por_min,
        max(umbral) filter (where id = 'R18') as duracion_min_seg,
        max(umbral) filter (where id = 'R19') as tarifa_min,
        max(umbral) filter (where id = 'R23') as cargo_cbd,
        -- coalesce: sin reglas de rechazo, array_agg da nulo y las reglas se perderían.
        coalesce(array_agg(id order by id) filter (where severidad = 'rechazo'), '{}') as ids_rechazo
    from {{ ref('reglas_calidad') }}
),

reversos as (
    -- Claves de los registros de reverso (total negativo), con el total en positivo: la gemela
    -- es la fila con las mismas claves y ese total (R20). distinct deja cada clave una sola
    -- vez, así el join de abajo no puede duplicar viajes.
    select distinct
        source_file, vendor_id, pickup_at, dropoff_at, pu_location_id, do_location_id,
        -total_amount as total_amount
    from {{ ref('stg_yellow_trips') }}
    where total_amount < 0
)

select
    v.*,
    d.segundos as duracion_seg,
    -- Texto separado por comas (por ejemplo 'R03,R16'); vacío si no viola ninguna.
    array_to_string(array(
        select r from unnest(c.violadas) with ordinality as u (r, n)
        where r = any (p.ids_rechazo) order by n
    ), ',') as reglas_rechazo,
    array_to_string(array(
        select r from unnest(c.violadas) with ordinality as u (r, n)
        where not (r = any (p.ids_rechazo)) order by n
    ), ',') as flags
from {{ ref('stg_yellow_trips') }} as v
left join {{ ref('stg_taxi_zones') }} as zpu on zpu.location_id = v.pu_location_id
left join {{ ref('stg_taxi_zones') }} as zdo on zdo.location_id = v.do_location_id
left join reversos as rev
    on rev.source_file = v.source_file
   and rev.vendor_id = v.vendor_id
   and rev.pickup_at = v.pickup_at
   and rev.dropoff_at = v.dropoff_at
   and rev.pu_location_id = v.pu_location_id
   and rev.do_location_id = v.do_location_id
   and rev.total_amount = v.total_amount
cross join parametros as p
cross join lateral (
    select
        -- Primer instante del mes del archivo, sacado de la ruta (.../year=2025/month=03/...).
        make_date(
            substring(v.source_file from 'year=(\d{4})')::int,
            substring(v.source_file from 'month=(\d{2})')::int,
            1
        )::timestamp as inicio_mes,
        -- Las fechas son hora local de Nueva York sin zona horaria. Restarlas tal cual ignora el
        -- cambio de horario (en marzo, un viaje que cruza las 2:00 suma una hora que no pasó).
        -- Con at time zone la resta da el tiempo real transcurrido.
        extract(epoch from (v.dropoff_at at time zone 'America/New_York')
                         - (v.pickup_at at time zone 'America/New_York')) as segundos
) as d
cross join lateral (
    -- Cada regla devuelve su id si se cumple y nulo si no; array_remove saca los nulos.
    select array_remove(array[
        case when v.pickup_at < d.inicio_mes
               or v.pickup_at >= d.inicio_mes + interval '1 month' then 'R01' end,
        case when d.segundos < 0 then 'R02' end,
        case when d.segundos = 0 then 'R03' end,
        case when v.trip_distance <= 0 then 'R04' end,
        case when v.trip_distance > p.distancia_max then 'R05' end,
        case when v.total_amount < 0 then 'R06' end,
        case when v.passenger_count is null then 'R07' end,
        case when v.passenger_count = 0 then 'R08' end,
        case when zpu.location_id is null or zdo.location_id is null then 'R09' end,
        -- 264 es "Unknown". La 265 ("Outside of NYC") es un destino conocido: ver R21.
        case when v.pu_location_id = 264 or v.do_location_id = 264 then 'R10' end,
        case when v.dup_n > 1 then 'R11' end,
        case when v.airport_fee > 0 and v.pu_location_id not in (132, 138) then 'R12' end,
        case when v.ratecode_id not in (1, 2, 3, 4, 5, 6, 99) then 'R13' end,
        case when v.payment_type not in (0, 1, 2, 3, 4, 5, 6) then 'R14' end,
        case when v.payment_type in (3, 4, 6) then 'R15' end,
        -- La velocidad se calcula solo con duración y distancia positivas: evita dividir por 0.
        case when (case when d.segundos > 0 and v.trip_distance > 0
                        then v.trip_distance / (d.segundos / 3600.0) end) > p.velocidad_max
             then 'R16' end,
        case when d.segundos / 60.0 > p.duracion_max_min
              and v.fare_amount < p.tarifa_min_por_min * d.segundos / 60.0 then 'R17' end,
        -- Duración positiva pero menor al mínimo (la nula o negativa la cubren R02 y R03).
        case when d.segundos > 0 and d.segundos < p.duracion_min_seg then 'R18' end,
        -- Tarifa negativa con un total que se cobró (el total negativo lo cubre R06).
        case when v.fare_amount < p.tarifa_min and v.total_amount > p.tarifa_min then 'R19' end,
        -- La fila positiva de un par cobro + reverso (el reverso lo rechaza R06).
        case when rev.source_file is not null then 'R20' end,
        -- Subida fuera de la ciudad; bajar en la 265 es un destino válido y no lleva regla.
        case when v.pu_location_id = 265 then 'R21' end,
        -- Tarifa fija entre JFK y Manhattan en un viaje que no sube ni baja en JFK (132).
        case when v.ratecode_id = 2 and v.pu_location_id <> 132 and v.do_location_id <> 132 then 'R22' end,
        -- El cargo del CBD es de 0 o del valor del catálogo; abs: el reverso lleva el valor negativo.
        case when abs(v.cbd_congestion_fee) not in (0, p.cargo_cbd) then 'R23' end
    ], null) as violadas
) as c
