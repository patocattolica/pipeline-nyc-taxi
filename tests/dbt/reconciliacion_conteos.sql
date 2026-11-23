-- Falla si en algún mes las filas leídas no son iguales a las aceptadas más las de cuarentena.
-- dbt marca el test como fallido si esta consulta devuelve alguna fila.
select mes, filas_leidas, filas_aceptadas, filas_cuarentena, diferencia
from {{ ref('reporte_calidad_mes') }}
where diferencia <> 0
