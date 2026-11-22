import pytest

from pipeline import descarga


class ConFalsa:
    """Hace de conexión a Postgres: guarda el hash de cada INSERT 'ok' en un dict."""

    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=()):
        if "'ok'" in sql:  # INSERT de una descarga exitosa: (archivo, url, filas, bytes, hash)
            self.log[params[0]] = params[4]

    def commit(self):
        pass


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Descarga sin red ni base: la descarga es falsa y cuenta cuántas veces la llaman."""
    log, descargas = {}, []

    def descarga_falsa(url, destino):
        descargas.append(url)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"contenido")

    monkeypatch.setattr(descarga, "RAIZ", tmp_path)
    monkeypatch.setattr(descarga, "descargar_con_reintentos", descarga_falsa)
    monkeypatch.setattr(descarga, "contar_filas", lambda ruta: 1)
    monkeypatch.setattr(descarga, "ultimo_hash_ok", lambda con, archivo: log.get(archivo))
    return ConFalsa(log), descargas, tmp_path / "data/raw/zones/zonas.csv"


def test_segunda_corrida_no_descarga(entorno):
    con, descargas, destino = entorno
    descarga.asegurar_archivo(con, "http://x/zonas.csv", destino)
    descarga.asegurar_archivo(con, "http://x/zonas.csv", destino)
    assert len(descargas) == 1


def test_archivo_alterado_se_vuelve_a_descargar(entorno):
    con, descargas, destino = entorno
    descarga.asegurar_archivo(con, "http://x/zonas.csv", destino)
    destino.write_bytes(b"corrupto")  # el hash ya no coincide con el del log
    descarga.asegurar_archivo(con, "http://x/zonas.csv", destino)
    assert len(descargas) == 2


def test_reintenta_y_se_recupera(monkeypatch):
    intentos, esperas = [], []

    def descarga_inestable(url, destino):
        intentos.append(1)
        if len(intentos) < 3:
            raise OSError("se cayó la red")

    monkeypatch.setattr(descarga, "descargar", descarga_inestable)
    monkeypatch.setattr(descarga.time, "sleep", esperas.append)
    descarga.descargar_con_reintentos("http://x", "destino")
    assert len(intentos) == 3
    assert esperas == [2, 4]  # espera creciente


def test_agota_reintentos_y_falla(monkeypatch):
    intentos, esperas = [], []

    def descarga_rota(url, destino):
        intentos.append(1)
        raise OSError("sin red")

    monkeypatch.setattr(descarga, "descargar", descarga_rota)
    monkeypatch.setattr(descarga.time, "sleep", esperas.append)
    with pytest.raises(OSError):
        descarga.descargar_con_reintentos("http://x", "destino")
    assert len(intentos) == 4  # el primer intento + 3 reintentos
    assert esperas == [2, 4, 8]
