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
y la tarifa, `fare_amount`.

## a. Las 10 zonas de origen con más viajes y su variación contra 2024

| Puesto | Zona | Barrio | 2025-03 | 2024-03 | Variación | Variación % |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Midtown Center | Manhattan | 177.720 | 161.173 | 16.547 | 10,27 |
| 2 | Upper East Side South | Manhattan | 167.082 | 153.871 | 13.211 | 8,59 |
| 3 | JFK Airport | Queens | 151.051 | 152.022 | −971 | −0,64 |
| 4 | Upper East Side North | Manhattan | 150.040 | 144.733 | 5.307 | 3,67 |
| 5 | Times Sq/Theatre District | Manhattan | 132.603 | 120.768 | 11.835 | 9,80 |
| 6 | Penn Station/Madison Sq West | Manhattan | 129.494 | 113.152 | 16.342 | 14,44 |
| 7 | Midtown East | Manhattan | 125.902 | 122.325 | 3.577 | 2,92 |
| 8 | Lincoln Square East | Manhattan | 114.779 | 113.545 | 1.234 | 1,09 |
| 9 | Union Sq | Manhattan | 112.147 | 96.319 | 15.828 | 16,43 |
| 10 | East Village | Manhattan | 108.459 | 92.217 | 16.242 | 17,61 |

**Interpretación:** nueve de las diez zonas son de Manhattan y todas crecen, mientras que JFK
es la única que baja. Union Sq y East Village entran al top 10 en lugar de LaGuardia y
Murray Hill, que estaban noveno y décimo en 2024.

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
| 2024-03 | 5 (de 5:00 a 5:59) | 22.672 | 35,18 | 27,78 |
| 2025-03 | 5 (de 5:00 a 5:59) | 32.583 | 33,75 | 27,18 |

El promedio es el ingreso total de la hora dividido por sus viajes. No se promedian los
promedios de cada zona.

**Interpretación:** en los dos meses, la hora de mayor ingreso por viaje es la de las 5 de la
mañana, entre un 24 % y un 27 % por encima del promedio del mes. Es una hora de pocos viajes y más largos
(en 2025, 5,6 millas contra 3,2 del resto del día), y casi uno de cada cinco va o viene de JFK
o de LaGuardia (18 % contra 8 %; en 2024, 21 % contra 9 %).

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
        sum(a.ingreso_total) as ingreso_total
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
        (ingreso_total / viajes)::numeric(10, 2) as ingreso_promedio,
        (sum(ingreso_total) over (partition by periodo)
            / sum(viajes) over (partition by periodo))::numeric(10, 2) as ingreso_promedio_mes,
        row_number() over (partition by periodo order by ingreso_total / viajes desc, hora) as puesto
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

En 2025-03, el **73,90 %** de los viajes pagó el cargo de congestión. En 2024 el cargo no
existía y la columna es nula.

| Puesto | Zona | Barrio | Viajes | Con cargo | % con cargo |
| --- | --- | --- | --- | --- | --- |
| 1 | SoHo | Manhattan | 35.524 | 35.445 | 99,78 |
| 2 | Greenwich Village South | Manhattan | 65.074 | 64.901 | 99,73 |
| 3 | West Village | Manhattan | 97.339 | 97.070 | 99,72 |
| 4 | Greenwich Village North | Manhattan | 59.306 | 59.141 | 99,72 |
| 5 | East Village | Manhattan | 108.459 | 108.143 | 99,71 |

Para entrar al ranking, una zona tiene que tener **al menos 100 viajes en el mes**. Sin ese
mínimo, los primeros puestos serían Rikers Island (2 viajes) y Arden Heights (1 viaje), al
100 %. Con cualquier mínimo entre 3 y 35.000 viajes, el top 5 es el mismo. El 73,90 % del
mes se calcula sobre todas las zonas.

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
| 0 – Flex Fare | 425.750 | 3,08 (3,34) | 916.106 | 2,00 (2,07) |
| 1 – Tarjeta de crédito | 2.594.906 | 26,23 (22,28) | 2.683.910 | 26,23 (22,53) |
| 2 – Efectivo | 465.840 | 0,00 (0,00) | 385.403 | 0,00 (0,00) |
| 3 – Sin cargo | 16.152 | 0,07 (0,04) | 17.836 | 0,09 (0,03) |
| 4 – Disputa | 31.385 | 0,20 (0,11) | 48.615 | 0,08 (0,06) |

El primer valor es el promedio del porcentaje de cada viaje. Entre paréntesis va el total de
propinas sobre el total de tarifas, que no se deja arrastrar por viajes con tarifas de
centavos (hay porcentajes de hasta 700.000 %). Los viajes con tarifa no positiva no entran.

**Interpretación:** con tarjeta, la propina ronda el 26 % de la tarifa en los dos años. El
**0 % del efectivo no es interpretable**: el taxímetro solo registra la propina que se paga
con tarjeta, y la que se deja en efectivo no queda en los datos. No significa que en
efectivo no se deje propina.

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
| JFK Airport | 181.975 | 64,79 | 180.699 | 64,15 |
| LaGuardia Airport | 145.278 | 43,76 | 144.862 | 43,82 |
| JFK o LaGuardia | 323.987 | 55,52 | 322.767 | 55,16 |

Los aeropuertos se identifican por el nombre de la zona en `dim_zone`. Un viaje entre los dos
aeropuertos cuenta en cada uno, pero una sola vez en el total. Por eso el total es menor que
la suma de las dos filas: hubo 3.266 viajes entre aeropuertos en 2024 y 2.794 en 2025.

**Interpretación:** el volumen de los aeropuertos queda casi igual (−0,4 %), mientras que
el total de viajes crece un 14,65 %. JFK tiene una tarifa media 46 % mayor que LaGuardia
porque está más lejos y tiene tarifa fija con Manhattan (`ratecode_id` 2, el 59 % de sus
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

por_aeropuerto as (
    select v.periodo, v.inicio, v.fare_amount, a.aeropuerto
    from viajes_aeropuerto as v
    cross join (values ('JFK Airport'), ('LaGuardia Airport')) as a (aeropuerto)
    where a.aeropuerto in (v.pu_zone, v.do_zone)
),

resultado as (
    select periodo, inicio, aeropuerto, count(*) as viajes, avg(fare_amount) as tarifa_media
    from por_aeropuerto
    group by periodo, inicio, aeropuerto

    union all

    select periodo, inicio, 'JFK o LaGuardia', count(*), avg(fare_amount)
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
| Viajes | 3.534.033 | 4.051.870 | 517.837 | 14,65 |
| Tarifa media (US$) | 19,17 | 18,47 | −0,70 | −3,66 |

**Hipótesis:** casi todo el aumento (490.356 de los 517.837 viajes) viene de los viajes con
`payment_type` 0 (Flex Fare, con precio cerrado al pedirlo por aplicación), que pasaron del
12,0 % al 22,6 % del mes. Tarjeta y efectivo juntos casi no cambian (+8.567). La tarifa media
baja por la mezcla: esos viajes son más baratos (US$ 17,14 de media) y los de tarjeta son algo
más cortos (de 3,36 a 3,29 millas). No parece un cambio de precios: en viajes con tarjeta de
1 a 3 millas, la tarifa por milla casi no varía (de US$ 7,77 a 7,67).

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
        avg(f.fare_amount) as tarifa_media
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
