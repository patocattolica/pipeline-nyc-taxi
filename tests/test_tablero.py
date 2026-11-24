import re

import tablero

# El tablero muestra resultados que ya calculó dbt: preguntas, tabla agregada y reportes de
# calidad. Si una tarjeta leyera fact_trips o el staging, tendría lógica propia fuera de dbt.
PERMITIDAS = re.compile(
    r"analytics\.(p_[a-f]_\w+|agg_zone_hour|reporte_calidad_mes|reporte_calidad_reglas)")


def test_las_tarjetas_solo_leen_resultados_de_dbt():
    for nombre, _, sql, _, _, _ in tablero.TARJETAS:
        tablas = re.findall(r"\b(?:from|join)\s+([\w.]+)", sql)
        assert tablas, nombre
        for tabla in tablas:
            assert PERMITIDAS.fullmatch(tabla), f"{nombre}: lee {tabla}"


def test_la_grilla_entra_en_24_columnas_sin_superponerse():
    ocupadas = set()
    for fila, columna, ancho, alto in tablero.posiciones():
        assert columna + ancho <= 24
        celdas = {(f, c) for f in range(fila, fila + alto) for c in range(columna, columna + ancho)}
        assert not ocupadas & celdas
        ocupadas |= celdas


def test_nombres_de_tarjetas_unicos():
    # El script busca las tarjetas por nombre para actualizarlas: un nombre repetido pisaría otra.
    nombres = [t[0] for t in tablero.TARJETAS]
    assert len(nombres) == len(set(nombres))
