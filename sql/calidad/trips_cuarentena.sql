{{ config(materialized='table') }}

-- Viajes con al menos una regla de rechazo: la fila, su archivo de origen (source_file) y las
-- reglas violadas (reglas_rechazo; flags tiene las advertencias que también cumple).
select *
from {{ ref('int_calidad') }}
where reglas_rechazo <> ''
