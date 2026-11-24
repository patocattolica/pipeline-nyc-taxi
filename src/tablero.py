"""Arma en Metabase el tablero que compara el mes asignado con el mismo mes del año anterior.

Uso: make viz (levanta Metabase y corre este módulo). No es parte de make all.

Cada tarjeta es un SELECT sobre tablas que ya calculó dbt en el esquema analytics (preguntas,
tabla agregada y reportes de calidad): el tablero muestra, no calcula. Así los números son los
mismos que en RESULTADOS.md. tests/test_tablero.py verifica que no se lean otras tablas.

Es idempotente: busca la colección, las tarjetas y el tablero por nombre, actualiza lo que
existe y crea lo que falta. Si se borra el volumen de Metabase, una nueva corrida lo rearma.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = f"http://127.0.0.1:{os.environ.get('MB_PUERTO', '3001')}"
COLECCION = "Taxis NYC"
TABLERO = "Comparación interanual"
BASE = "Taxis NYC (Postgres)"

# Los dos meses de la comparación, en el mismo orden en todas las tarjetas.
MESES = """
    select mes_comparacion as mes from analytics.p_f_variacion_total
    union all
    select mes_asignado from analytics.p_f_variacion_total
"""

# nombre, tipo de gráfico, SQL, opciones de visualización, ancho y alto (grilla de 24 columnas).
TARJETAS = [
    ("Viajes del mes asignado", "scalar",
     "select viajes_asignado from analytics.p_f_variacion_total", {}, 6, 3),
    ("Variación de viajes (%)", "scalar",
     "select variacion_viajes_pct from analytics.p_f_variacion_total", {}, 6, 3),
    ("Tarifa media (USD)", "scalar",
     "select tarifa_media_asignado from analytics.p_f_variacion_total", {}, 6, 3),
    ("Variación de la tarifa (%)", "scalar",
     "select variacion_tarifa_pct from analytics.p_f_variacion_total", {}, 6, 3),

    ("Viajes aceptados por mes", "bar", """
        select mes_comparacion as mes, viajes_comparacion as viajes
        from analytics.p_f_variacion_total
        union all
        select mes_asignado, viajes_asignado from analytics.p_f_variacion_total
        order by mes
     """, {"graph.dimensions": ["mes"], "graph.metrics": ["viajes"]}, 12, 6),
    ("Calidad: filas aceptadas y en cuarentena por mes", "bar", f"""
        select mes, filas_aceptadas, filas_cuarentena
        from analytics.reporte_calidad_mes
        where mes in ({MESES})
        order by mes
     """, {"graph.dimensions": ["mes"], "graph.metrics": ["filas_aceptadas", "filas_cuarentena"],
           "stackable.stack_type": "stacked"}, 12, 6),

    # Mismo cálculo que la pregunta b: ingreso confiable (sin R19) sobre los viajes con importe,
    # sumados por hora; no se promedian los promedios de agg_zone_hour.
    ("Ingreso promedio por viaje según la hora (USD)", "line", f"""
        select to_char(fecha, 'YYYY-MM') as mes, hora,
               round(sum(ingreso_confiable) / sum(viajes_con_importe), 2) as ingreso_promedio
        from analytics.agg_zone_hour
        where to_char(fecha, 'YYYY-MM') in ({MESES})
        group by 1, 2
        order by hora, mes
     """, {"graph.dimensions": ["hora", "mes"], "graph.metrics": ["ingreso_promedio"]}, 12, 6),
    ("Viajes según la hora", "line", f"""
        select to_char(fecha, 'YYYY-MM') as mes, hora, sum(viajes) as viajes
        from analytics.agg_zone_hour
        where to_char(fecha, 'YYYY-MM') in ({MESES})
        group by 1, 2
        order by hora, mes
     """, {"graph.dimensions": ["hora", "mes"], "graph.metrics": ["viajes"]}, 12, 6),

    ("Top 10 zonas de origen: viajes por mes", "bar", """
        select a.puesto, a.zone as zona, f.mes_comparacion as mes, a.viajes_comparacion as viajes
        from analytics.p_a_top_zonas as a cross join analytics.p_f_variacion_total as f
        union all
        select a.puesto, a.zone, f.mes_asignado, a.viajes_asignado
        from analytics.p_a_top_zonas as a cross join analytics.p_f_variacion_total as f
        order by puesto, mes
     """, {"graph.dimensions": ["zona", "mes"], "graph.metrics": ["viajes"]}, 12, 7),
    ("Top 10 zonas de origen: variación de viajes (%)", "row", """
        select zone as zona, variacion_pct
        from analytics.p_a_top_zonas
        order by puesto
     """, {"graph.dimensions": ["zona"], "graph.metrics": ["variacion_pct"]}, 12, 7),

    ("Propina promedio según el tipo de pago (%)", "bar", """
        select payment_type, tipo_pago, mes, propina_pct_promedio
        from analytics.p_d_propina_por_pago
        order by payment_type, mes
     """, {"graph.dimensions": ["tipo_pago", "mes"], "graph.metrics": ["propina_pct_promedio"]},
     12, 6),
    ("Aeropuertos: tarifa media por mes (USD)", "bar", """
        select aeropuerto, mes, tarifa_media
        from analytics.p_e_aeropuertos
        order by aeropuerto, mes
     """, {"graph.dimensions": ["aeropuerto", "mes"], "graph.metrics": ["tarifa_media"]}, 12, 6),

    ("Viajes con cargo del CBD (%)", "scalar", """
        select distinct pct_cbd_mes from analytics.p_c_cbd_congestion
     """, {}, 6, 5),
    ("Zonas de origen con más viajes con cargo del CBD", "table", """
        select puesto, zone as zona, borough as barrio, viajes, viajes_cbd, pct_cbd_zona
        from analytics.p_c_cbd_congestion
        order by puesto
     """, {}, 18, 5),

    ("Calidad: filas que marca cada regla (% de las leídas)", "bar", f"""
        select regla_id, mes, pct_leidas
        from analytics.reporte_calidad_reglas
        where mes in ({MESES})
          and regla_id in (select regla_id from analytics.reporte_calidad_reglas where filas > 0)
        order by regla_id, mes
     """, {"graph.dimensions": ["regla_id", "mes"], "graph.metrics": ["pct_leidas"]}, 24, 7),
]


def variable(nombre):
    valor = os.environ.get(nombre)
    if not valor:
        sys.exit(f"Falta la variable {nombre} (agregala a .env; ver .env.example)")
    return valor


def pedir(metodo, ruta, cuerpo=None, sesion=None):
    """Llama a la API de Metabase y devuelve la respuesta como JSON."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(URL + ruta, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json")
    if sesion:
        req.add_header("X-Metabase-Session", sesion)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            texto = resp.read().decode()
    except urllib.error.HTTPError as e:
        sys.exit(f"Metabase respondió {e.code} a {metodo} {ruta}: {e.read().decode()[:500]}")
    return json.loads(texto) if texto else None


def esperar_metabase(segundos=180):
    """Metabase tarda unos 40 s en arrancar; espera a que /api/health responda ok."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(URL + "/api/health", timeout=5) as resp:
                if json.loads(resp.read()).get("status") == "ok":
                    return
        except (urllib.error.URLError, ConnectionError, ValueError):
            pass
        time.sleep(3)
    sys.exit(f"Metabase no respondió en {URL} después de {segundos} s")


def iniciar_sesion(email, clave):
    """La primera vez crea el usuario administrador; después solo inicia sesión."""
    propiedades = pedir("GET", "/api/session/properties")
    if not propiedades.get("has-user-setup"):
        return pedir("POST", "/api/setup", {
            "token": propiedades["setup-token"],
            "user": {"email": email, "password": clave, "first_name": "Admin",
                     "last_name": "Taxis", "site_name": COLECCION},
            "prefs": {"site_name": COLECCION, "site_locale": "es", "allow_tracking": False},
        })["id"]
    return pedir("POST", "/api/session", {"username": email, "password": clave})["id"]


def conectar_base(sesion):
    """Crea o actualiza la conexión a Postgres, limitada al esquema analytics."""
    conexion = {
        "engine": "postgres",
        "name": BASE,
        "details": {
            # Metabase corre en la red de Compose: llega a Postgres por el nombre del servicio.
            "host": "postgres", "port": 5432,
            "dbname": variable("PGDATABASE"), "user": variable("PGUSER"),
            "password": variable("PGPASSWORD"), "ssl": False,
            "schema-filters-type": "inclusion", "schema-filters-patterns": "analytics",
        },
    }
    bases = pedir("GET", "/api/database", sesion=sesion)
    bases = bases["data"] if isinstance(bases, dict) else bases
    existente = next((b for b in bases if b["name"] == BASE), None)
    if existente:
        return pedir("PUT", f"/api/database/{existente['id']}", conexion, sesion)["id"]
    return pedir("POST", "/api/database", conexion, sesion)["id"]


def buscar_coleccion(sesion):
    for c in pedir("GET", "/api/collection", sesion=sesion):
        if c.get("name") == COLECCION and not c.get("archived"):
            return c["id"]
    return pedir("POST", "/api/collection", {"name": COLECCION}, sesion)["id"]


def items(sesion, coleccion, modelo):
    """Nombre -> id de las tarjetas o tableros de la colección."""
    datos = pedir("GET", f"/api/collection/{coleccion}/items?models={modelo}", sesion=sesion)
    return {i["name"]: i["id"] for i in datos["data"]}


def guardar_tarjetas(sesion, base, coleccion):
    existentes = items(sesion, coleccion, "card")
    ids = []
    for nombre, tipo, sql, opciones, _, _ in TARJETAS:
        tarjeta = {
            "name": nombre,
            "display": tipo,
            "collection_id": coleccion,
            "visualization_settings": opciones,
            "dataset_query": {"type": "native", "database": base,
                              "native": {"query": " ".join(sql.split())}},
        }
        if nombre in existentes:
            ids.append(pedir("PUT", f"/api/card/{existentes[nombre]}", tarjeta, sesion)["id"])
        else:
            ids.append(pedir("POST", "/api/card", tarjeta, sesion)["id"])
    return ids


def posiciones():
    """Ubica las tarjetas de izquierda a derecha en filas de 24 columnas, en el orden de TARJETAS."""
    fila = columna = alto_fila = 0
    for _, _, _, _, ancho, alto in TARJETAS:
        if columna + ancho > 24:
            fila, columna, alto_fila = fila + alto_fila, 0, 0
        yield fila, columna, ancho, alto
        columna += ancho
        alto_fila = max(alto_fila, alto)


def guardar_tablero(sesion, coleccion, tarjetas):
    existentes = items(sesion, coleccion, "dashboard")
    if TABLERO in existentes:
        tablero = existentes[TABLERO]
    else:
        tablero = pedir("POST", "/api/dashboard", {"name": TABLERO, "collection_id": coleccion},
                        sesion)["id"]
    # Se manda la grilla completa: reemplaza las tarjetas que tuviera el tablero.
    grilla = [
        {"id": -(i + 1), "card_id": tarjeta, "row": fila, "col": columna,
         "size_x": ancho, "size_y": alto, "parameter_mappings": [], "visualization_settings": {}}
        for i, (tarjeta, (fila, columna, ancho, alto)) in enumerate(zip(tarjetas, posiciones()))
    ]
    pedir("PUT", f"/api/dashboard/{tablero}", {"dashcards": grilla}, sesion)
    return tablero


def main():
    email, clave = variable("MB_ADMIN_EMAIL"), variable("MB_ADMIN_PASSWORD")
    esperar_metabase()
    sesion = iniciar_sesion(email, clave)
    base = conectar_base(sesion)
    coleccion = buscar_coleccion(sesion)
    tarjetas = guardar_tarjetas(sesion, base, coleccion)
    tablero = guardar_tablero(sesion, coleccion, tarjetas)
    print(f"Tablero listo: {URL}/dashboard/{tablero} (usuario {email})")


if __name__ == "__main__":
    main()
