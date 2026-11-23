-- Viajes sin ninguna regla de rechazo. Las advertencias quedan marcadas en flags.
select *
from {{ ref('int_calidad') }}
where reglas_rechazo = ''
