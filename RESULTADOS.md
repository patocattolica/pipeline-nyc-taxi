# Resultados

Respuestas a las seis preguntas de la Parte 5 para el mes asignado, **2025-03**, contra el
mismo mes de 2024. Cada consulta es un modelo de dbt en `sql/preguntas/` que lee el modelo
estrella (`fact_trips`, `dim_zone`, `dim_date`, `agg_zone_hour`) y guarda su resultado en
`analytics.p_*`. El mes llega como variable:

```bash
dbt build --select sql/preguntas --vars '{mes: "2025-03"}'
```

El mes de comparación es el mismo mes del año anterior. Si alguno de los dos no está
cargado, el test `tests/dbt/meses_de_preguntas_cargados.sql` falla. Todas las cifras son
de viajes **aceptados**: la cuarentena no entra en el modelo. El ingreso es `total_amount`
y la tarifa, `fare_amount`. Los promedios de tarifa y de ingreso excluyen los viajes con
R19, cuyos importes no son el precio del viaje (`importe_confiable`; ver `reglas.md`). Los
conteos de viajes los incluyen.

## a. Las 10 zonas de origen con más viajes y su variación contra 2024

| Puesto | Zona | Barrio | 2025-03 | 2024-03 | Variación | Variación % |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Midtown Center | Manhattan | 176.179 | 159.484 | 16.695 | 10,47 |
| 2 | Upper East Side South | Manhattan | 166.404 | 152.458 | 13.946 | 9,15 |
| 3 | Upper East Side North | Manhattan | 149.986 | 143.700 | 6.286 | 4,37 |
| 4 | JFK Airport | Queens | 142.481 | 147.419 | −4.938 | −3,35 |
| 5 | Times Sq/Theatre District | Manhattan | 130.209 | 119.037 | 11.172 | 9,39 |
| 6 | Penn Station/Madison Sq West | Manhattan | 127.686 | 111.840 | 15.846 | 14,17 |
| 7 | Midtown East | Manhattan | 124.812 | 121.134 | 3.678 | 3,04 |
| 8 | Lincoln Square East | Manhattan | 114.226 | 112.395 | 1.831 | 1,63 |
| 9 | Union Sq | Manhattan | 111.509 | 95.547 | 15.962 | 16,71 |
| 10 | East Village | Manhattan | 107.535 | 91.378 | 16.157 | 17,68 |

**Interpretación:** nueve de las diez zonas son de Manhattan y todas crecen, mientras que JFK
es la única que baja (−3,35 %). Union Sq y East Village entran al top 10 en lugar de
LaGuardia y Murray Hill, que estaban noveno y décimo en 2024.

<details>
<summary>Consulta: <code>sql/preguntas/p_a_top_zonas.sql</code></summary>

```sql
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
),

viajes_zona as (
    select
        a.pu_location_id,
        sum(a.viajes) filter (where m.periodo = 'asignado') as viajes_asignado,
        sum(a.viajes) filter (where m.periodo = 'comparacion') as viajes_comparacion
    from {{ ref('agg_zone_hour') }} as a
    join {{ ref('dim_date') }} as d on d.fecha = a.fecha
    join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
    group by a.pu_location_id
)

select
    row_number() over (order by v.viajes_asignado desc, v.pu_location_id) as puesto,
    v.pu_location_id,
    z.zone,
    z.borough,
    v.viajes_asignado,
    coalesce(v.viajes_comparacion, 0) as viajes_comparacion,
    v.viajes_asignado - coalesce(v.viajes_comparacion, 0) as variacion,
    (100.0 * (v.viajes_asignado - v.viajes_comparacion)
        / nullif(v.viajes_comparacion, 0))::numeric(10, 2) as variacion_pct
from viajes_zona as v
join {{ ref('dim_zone') }} as z on z.location_id = v.pu_location_id
where v.viajes_asignado is not null
order by puesto
limit 10
```

</details>

## b. La hora del día con mayor ingreso promedio por viaje

| Mes | Hora | Viajes en esa hora | Ingreso promedio por viaje (US$) | Promedio del mes (US$) |
| --- | --- | --- | --- | --- |
| 2024-03 | 5 (de 5:00 a 5:59) | 22.344 | 35,48 | 27,90 |
| 2025-03 | 5 (de 5:00 a 5:59) | 32.054 | 35,32 | 27,97 |

El promedio es el ingreso total de la hora dividido por sus viajes. No se promedian los
promedios de cada zona. Los viajes con R19 cuentan en la columna de viajes, pero no en los
promedios: su total (US$ 4,51 de media) no es el precio del viaje. Con ellos, el promedio de
2025 daba US$ 33,75 a las 5 y 27,18 en el mes, y parecía que bajaba contra 2024.

**Interpretación:** en los dos meses, la hora de mayor ingreso por viaje es la de las 5 de la
mañana, un 26 % / 27 % por encima del promedio del mes, y el valor casi no cambia entre los dos
años. Es una hora de pocos viajes y más largos (en 2025, 5,6 millas contra 3,2 del resto del
día), y casi uno de cada cinco va o viene de JFK o de LaGuardia (18 % contra 8 %; en 2024,
21 % contra 9 %).

<details>
<summary>Consulta: <code>sql/preguntas/p_b_hora_mayor_ingreso.sql</code></summary>

```sql
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
),

por_hora as (
    select
        m.periodo,
        m.inicio,
        a.hora,
        sum(a.viajes) as viajes,
        sum(a.viajes_con_importe) as viajes_con_importe,
        sum(a.ingreso_confiable) as ingreso_total
    from {{ ref('agg_zone_hour') }} as a
    join {{ ref('dim_date') }} as d on d.fecha = a.fecha
    join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
    group by m.periodo, m.inicio, a.hora
),

ranking as (
    select
        periodo,
        inicio,
        hora,
        viajes,
        (ingreso_total / viajes_con_importe)::numeric(10, 2) as ingreso_promedio,
        -- Ingreso promedio de todo el mes, como referencia.
        (sum(ingreso_total) over (partition by periodo)
            / sum(viajes_con_importe) over (partition by periodo))::numeric(10, 2) as ingreso_promedio_mes,
        row_number() over (partition by periodo order by ingreso_total / viajes_con_importe desc, hora) as puesto
    from por_hora
)

select
    to_char(inicio, 'YYYY-MM') as mes,
    periodo,
    hora,
    viajes,
    ingreso_promedio,
    ingreso_promedio_mes
from ranking
where puesto = 1
order by mes
```

</details>

## c. Viajes con `cbd_congestion_fee` mayor a 0 en 2025-03 y las 5 zonas con mayor proporción

En 2025-03, el **73,98 %** de los viajes pagó el cargo de congestión. En 2024 el cargo no
existía y la columna es nula.

| Puesto | Zona | Barrio | Viajes | Con cargo | % con cargo |
| --- | --- | --- | --- | --- | --- |
| 1 | SoHo | Manhattan | 35.315 | 35.238 | 99,78 |
| 2 | Greenwich Village South | Manhattan | 64.567 | 64.397 | 99,74 |
| 3 | Greenwich Village North | Manhattan | 58.912 | 58.752 | 99,73 |
| 4 | West Village | Manhattan | 96.816 | 96.549 | 99,72 |
| 5 | East Village | Manhattan | 107.535 | 107.222 | 99,71 |

Para entrar al ranking, una zona tiene que tener **al menos 100 viajes en el mes**. Sin ese
mínimo, los primeros puestos serían Rikers Island (2 viajes) y Arden Heights (1 viaje), al
100 %. Con cualquier mínimo entre 3 y 35.000 viajes, el top 5 es el mismo; por encima de
35.315 sale SoHo, por su tamaño y no por su proporción. El mínimo deja afuera 33 de las 260
zonas con viajes, que suman unos 1.000 viajes del mes. El 73,98 % del mes se calcula sobre
todas las zonas.

**Interpretación:** las cinco zonas están en el sur de Manhattan, dentro de la zona de
congestión, donde casi todos los viajes que salen pagan el cargo. Las cinco están separadas
por 0,07 puntos, así que el orden dentro del top 5 no es significativo.

<details>
<summary>Consulta: <code>sql/preguntas/p_c_cbd_congestion.sql</code></summary>

```sql
with parametros as (
    select
        to_date('{{ var("mes") }}', 'YYYY-MM') as inicio,
        100 as viajes_minimos
),

por_zona as (
    select
        f.pu_location_id,
        count(*) as viajes,
        count(*) filter (where f.cbd_congestion_fee > 0) as viajes_cbd
    from {{ ref('fact_trips') }} as f
    join {{ ref('dim_date') }} as d on d.fecha = f.fecha
    join parametros as p on d.anio = extract(year from p.inicio) and d.mes = extract(month from p.inicio)
    group by f.pu_location_id
),

ranking as (
    select
        pu_location_id,
        viajes,
        viajes_cbd,
        100.0 * sum(viajes_cbd) over () / sum(viajes) over () as pct_cbd_mes,
        100.0 * viajes_cbd / viajes as pct_cbd_zona
    from por_zona
)

select
    row_number() over (order by r.pct_cbd_zona desc, r.pu_location_id) as puesto,
    to_char(p.inicio, 'YYYY-MM') as mes,
    r.pct_cbd_mes::numeric(10, 2) as pct_cbd_mes,
    r.pu_location_id,
    z.zone,
    z.borough,
    r.viajes,
    r.viajes_cbd,
    r.pct_cbd_zona::numeric(10, 2) as pct_cbd_zona
from ranking as r
cross join parametros as p
join {{ ref('dim_zone') }} as z on z.location_id = r.pu_location_id
where r.viajes >= p.viajes_minimos
order by puesto
limit 5
```

</details>

## d. Propina promedio como porcentaje de la tarifa, por tipo de pago

| Tipo de pago | Viajes 2024-03 | Propina % 2024-03 | Viajes 2025-03 | Propina % 2025-03 |
| --- | --- | --- | --- | --- |
| 0 – Flex Fare | 425.917 | 3,08 (3,34) | 916.212 | 2,00 (2,07) |
| 1 – Tarjeta de crédito | 2.594.989 | 26,23 (22,28) | 2.702.631 | 26,25 (22,54) |
| 2 – Efectivo | 457.506 | 0,00 (0,00) | 373.421 | 0,00 (0,00) |
| 3 – Sin cargo | 9.929 | 0,00 (0,01) | 10.340 | 0,02 (0,01) |
| 4 – Disputa | 8.329 | 0,02 (0,01) | 11.016 | 0,02 (0,02) |

El primer valor es el promedio del porcentaje de cada viaje. Entre paréntesis va el total de
propinas sobre el total de tarifas, que no se deja arrastrar por viajes con tarifas de
centavos (hay porcentajes de hasta 700.000 %). Los viajes con tarifa no positiva no entran:
entre ellos, las 140.407 filas de 2025 con R19, todas de Flex Fare.

**Interpretación:** con tarjeta, la propina ronda el 26 % de la tarifa en los dos años. El
**0 % del efectivo no es interpretable**: el taxímetro solo registra la propina que se paga
con tarjeta, y la que se deja en efectivo no queda en los datos. No significa que en
efectivo no se deje propina. Tampoco se interpretan Flex Fare, cuya propina probablemente se
paga en la aplicación y no llega a los datos, ni "sin cargo" y "disputa", que no tienen una tarifa
cobrada. Disputa tiene pocos viajes porque la mayoría eran cobros revertidos y R20 los rechaza.

<details>
<summary>Consulta: <code>sql/preguntas/p_d_propina_por_pago.sql</code></summary>

```sql
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
)

select
    to_char(m.inicio, 'YYYY-MM') as mes,
    m.periodo,
    f.payment_type,
    case f.payment_type
        when 0 then 'Flex Fare'
        when 1 then 'Tarjeta de crédito'
        when 2 then 'Efectivo'
        when 3 then 'Sin cargo'
        when 4 then 'Disputa'
        when 5 then 'Desconocido'
        when 6 then 'Viaje anulado'
    end as tipo_pago,
    count(*) as viajes,
    count(f.propina_pct) as viajes_con_tarifa,
    avg(f.propina_pct)::numeric(10, 2) as propina_pct_promedio,
    (100 * sum(f.tip_amount) filter (where f.fare_amount > 0)
        / nullif(sum(f.fare_amount) filter (where f.fare_amount > 0), 0))::numeric(10, 2)
        as propina_pct_global
from {{ ref('fact_trips') }} as f
join {{ ref('dim_date') }} as d on d.fecha = f.fecha
join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
group by m.inicio, m.periodo, f.payment_type
order by mes, f.payment_type
```

</details>

## e. Viajes y tarifa media de los que empiezan o terminan en JFK o LaGuardia

| Aeropuerto | Viajes 2024-03 | Tarifa media 2024-03 (US$) | Viajes 2025-03 | Tarifa media 2025-03 (US$) |
| --- | --- | --- | --- | --- |
| JFK Airport | 176.980 | 65,17 | 171.683 | 64,91 |
| LaGuardia Airport | 143.920 | 43,80 | 142.869 | 43,83 |
| JFK o LaGuardia | 317.701 | 55,66 | 311.913 | 55,39 |

Los aeropuertos se identifican por el nombre de la zona en `dim_zone`. Un viaje entre los dos
aeropuertos cuenta en cada uno, pero una sola vez en el total. Por eso el total es menor que
la suma de las dos filas: hubo 3.199 viajes entre aeropuertos en 2024 y 2.639 en 2025.

**Interpretación:** los viajes de aeropuerto bajan un 1,8 %, mientras que el total crece un
14,78 %; la caída está en JFK (−3,0 %). JFK tiene una tarifa media 48 % mayor que LaGuardia
porque está más lejos y tiene tarifa fija con Manhattan (`ratecode_id` 2, el 60 % de sus
viajes en 2024).

<details>
<summary>Consulta: <code>sql/preguntas/p_e_aeropuertos.sql</code></summary>

```sql
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
),

viajes_aeropuerto as (
    select
        m.periodo,
        m.inicio,
        f.trip_id,
        f.fare_amount,
        f.importe_confiable,
        zpu.zone as pu_zone,
        zdo.zone as do_zone
    from {{ ref('fact_trips') }} as f
    join {{ ref('dim_date') }} as d on d.fecha = f.fecha
    join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
    join {{ ref('dim_zone') }} as zpu on zpu.location_id = f.pu_location_id
    join {{ ref('dim_zone') }} as zdo on zdo.location_id = f.do_location_id
    where zpu.zone in ('JFK Airport', 'LaGuardia Airport')
       or zdo.zone in ('JFK Airport', 'LaGuardia Airport')
),

-- Una fila por viaje y aeropuerto: si empieza y termina en el mismo, cuenta una vez.
por_aeropuerto as (
    select v.periodo, v.inicio, v.fare_amount, v.importe_confiable, a.aeropuerto
    from viajes_aeropuerto as v
    cross join (values ('JFK Airport'), ('LaGuardia Airport')) as a (aeropuerto)
    where a.aeropuerto in (v.pu_zone, v.do_zone)
),

resultado as (
    select periodo, inicio, aeropuerto, count(*) as viajes,
        avg(fare_amount) filter (where importe_confiable) as tarifa_media
    from por_aeropuerto
    group by periodo, inicio, aeropuerto

    union all

    select periodo, inicio, 'JFK o LaGuardia', count(*), avg(fare_amount) filter (where importe_confiable)
    from viajes_aeropuerto
    group by periodo, inicio
)

select
    to_char(inicio, 'YYYY-MM') as mes,
    periodo,
    aeropuerto,
    viajes,
    tarifa_media::numeric(10, 2) as tarifa_media
from resultado
order by mes, aeropuerto
```

</details>

## f. Variación de viajes totales y de tarifa media entre los dos meses

| Medida | 2024-03 | 2025-03 | Variación | Variación % |
| --- | --- | --- | --- | --- |
| Viajes | 3.496.670 | 4.013.620 | 516.950 | 14,78 |
| Tarifa media (US$), sin R19 | 19,24 | 19,22 | −0,01 | −0,07 |

**Hipótesis:** el 89 % del aumento (461.700 de 516.950 viajes) es Flex Fare (`payment_type` 0) del
proveedor 2: viajes pedidos por aplicación. Desde el 5/1/2025 el cargo de congestión es de US$ 0,75
por viaje en taxi amarillo y de US$ 1,50 en Uber y Lyft, lo que favorece la sustitución. El calendario
no lo explica: los dos marzos tienen 5 sábados y 5 domingos, aunque estos crecen más (+21,5 y +22,5 %
por día). Sin R19 la tarifa media no cambia (−0,07 %): la baja que se veía venía de esas filas.

<details>
<summary>Consulta: <code>sql/preguntas/p_f_variacion_total.sql</code></summary>

```sql
with meses as (
    select 'asignado' as periodo, to_date('{{ var("mes") }}', 'YYYY-MM') as inicio
    union all
    select 'comparacion', (to_date('{{ var("mes") }}', 'YYYY-MM') - interval '1 year')::date
),

por_mes as (
    select
        m.periodo,
        m.inicio,
        count(*) as viajes,
        avg(f.fare_amount) filter (where f.importe_confiable) as tarifa_media
    from {{ ref('fact_trips') }} as f
    join {{ ref('dim_date') }} as d on d.fecha = f.fecha
    join meses as m on d.anio = extract(year from m.inicio) and d.mes = extract(month from m.inicio)
    group by m.periodo, m.inicio
)

select
    to_char(c.inicio, 'YYYY-MM') as mes_comparacion,
    to_char(a.inicio, 'YYYY-MM') as mes_asignado,
    c.viajes as viajes_comparacion,
    a.viajes as viajes_asignado,
    a.viajes - c.viajes as variacion_viajes,
    (100.0 * (a.viajes - c.viajes) / c.viajes)::numeric(10, 2) as variacion_viajes_pct,
    c.tarifa_media::numeric(10, 2) as tarifa_media_comparacion,
    a.tarifa_media::numeric(10, 2) as tarifa_media_asignado,
    (a.tarifa_media - c.tarifa_media)::numeric(10, 2) as variacion_tarifa,
    (100 * (a.tarifa_media - c.tarifa_media) / c.tarifa_media)::numeric(10, 2) as variacion_tarifa_pct
from por_mes as a
join por_mes as c on c.periodo = 'comparacion'
where a.periodo = 'asignado'
```

</details>
