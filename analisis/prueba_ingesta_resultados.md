# Prueba de ingesta con PyAirbyte (paso 7)

Script: `analisis/prueba_ingesta.py`. Carga las primeras 500.000 filas de
`yellow_tripdata_2025-03.parquet` con el conector File de PyAirbyte a `prueba.trozo` en
Postgres, con `AIRBYTE_OFFLINE_MODE=1` y `force_full_refresh=True`.

**Máquina de la medición:** 12 CPU, 14 GiB de RAM. Postgres 17 en Docker, con un tope de
1,5 GiB. No es la notebook de 8 GB que pide la consigna, así que hay que repetir la
medición en ese equipo.

## Resultados

| Medida | Corrida 1 | Corrida 2 |
| --- | --- | --- |
| Filas procesadas | 500.000 | 500.000 |
| Lectura del conector | 45 s | 46 s |
| Escritura en Postgres | 49 s | 57 s |
| Tiempo total del sync | 99,5 s | 107,1 s |
| RAM máxima del script (PyAirbyte) | 1.308 MiB | 1.249 MiB |
| RAM máxima del conector (subproceso) | 851 MiB | 851 MiB |
| RAM máxima del contenedor de Postgres | 157 MiB | 258 MiB |
| Filas en `prueba.trozo` después de la corrida | — | 500.000 |
| Tamaño de `prueba.trozo` | — | 102 MB |

- La RAM del script y la del conector salen de `resource.getrusage` (`ru_maxrss`): la del
  propio proceso y la del mayor subproceso.
- La RAM de Postgres sale de `docker stats`, con una muestra cada 1 o 2 segundos.

## Observaciones

- **La segunda corrida reemplazó la tabla en lugar de agregar filas:** siguen siendo
  500.000. Ese comportamiento se debe a `force_full_refresh=True`.
- **Tipos que deja PyAirbyte:**
  - `vendorid`, `pulocationid`, `dolocationid` (int32 en el Parquet) y las dos fechas
    quedan como `character varying`;
  - el resto de los números queda como `numeric`.
  - Los nombres quedan en minúscula y pegados.
  - Agrega `_airbyte_raw_id`, `_airbyte_extracted_at` y `_airbyte_meta`.
  - El staging tiene que convertir todos los tipos.
- **Las dos fases del sync no se superponen del todo:** primero el conector lee a archivos
  locales y después el script los escribe en Postgres. El peor caso, sumando los dos
  procesos, ronda los 2,2 GiB.

## Estimación para el mes completo

| | 2025-03 | 2024-03 | Los dos |
| --- | --- | --- | --- |
| Filas | 4.145.257 | 3.582.628 | 7.727.885 |
| Trozos de 500.000 | 9 | 8 | 17 |
| Tiempo (unos 105 s por trozo) | unos 15 min | unos 13 min | unos 28 min |
| Espacio en Postgres (unos 102 MB por trozo) | unos 850 MB | unos 730 MB | unos 1,6 GB |

La RAM no crece con la cantidad de trozos, porque cada trozo es un sync aparte.
