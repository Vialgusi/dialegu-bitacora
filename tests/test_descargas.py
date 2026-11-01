import hashlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.motor import descargas
from backend.motor.descargas import Cancelado, ErrorDescarga, descargar

CONTENIDO = bytes(range(256)) * 4000  # ~1 MB
SHA = hashlib.sha256(CONTENIDO).hexdigest()
dormir = time.sleep  # las pruebas anulan time.sleep en descargas; el servidor necesita el real


class Servidor:
    """Sirve CONTENIDO con soporte de Range; puede cortar la conexión tras N bytes o ignorar Range."""

    def __init__(self):
        self.cortes = []  # bytes a enviar antes de cortar, uno por petición
        self.ignorar_range = False
        self.goteo = []  # peticiones que envían a cuentagotas: bytes por segundo
        self.pausas = []  # bytes a enviar antes de quedarse callado, uno por petición
        self.rangos = []
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                rango = self.headers.get("Range")
                servidor.rangos.append(rango)
                inicio = 0
                if rango and not servidor.ignorar_range:
                    inicio = int(rango.split("=")[1].rstrip("-"))
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {inicio}-{len(CONTENIDO) - 1}/{len(CONTENIDO)}")
                else:
                    self.send_response(200)
                cuerpo = CONTENIDO[inicio:]
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                if servidor.goteo:
                    ritmo = servidor.goteo.pop(0)
                    try:
                        for i in range(0, len(cuerpo), ritmo // 10):
                            self.wfile.write(cuerpo[i : i + ritmo // 10])
                            self.wfile.flush()
                            dormir(0.1)
                    except OSError:  # el cliente cerró la conexión lenta
                        pass
                    return
                if servidor.pausas:
                    self.wfile.write(cuerpo[: servidor.pausas.pop(0)])
                    self.wfile.flush()
                    dormir(3)  # la red «se congela» sin cerrar la conexión
                    return
                corte = servidor.cortes.pop(0) if servidor.cortes else None
                self.wfile.write(cuerpo[:corte] if corte is not None else cuerpo)
                if corte is not None:
                    self.wfile.flush()
                    self.connection.close()  # el cliente recibe una respuesta truncada

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self.http.server_port}/modelo.bin"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def cerrar(self):
        self.http.shutdown()


@pytest.fixture
def servidor(monkeypatch):
    monkeypatch.setattr(descargas, "ESPERAS", (0,))
    monkeypatch.setattr(descargas.time, "sleep", lambda _s: None)
    s = Servidor()
    yield s
    s.cerrar()


def test_descarga_completa_y_verificada(servidor, tmp_path):
    avances = []
    destino = tmp_path / "modelo.bin"
    descargar([servidor.url], destino, len(CONTENIDO), SHA, lambda hechos, aviso=None: avances.append(hechos))
    assert destino.read_bytes() == CONTENIDO
    assert not (tmp_path / "modelo.bin.parcial").exists()
    assert avances[-1] == len(CONTENIDO)


def test_corte_a_mitad_se_reanuda_con_range(servidor, tmp_path):
    servidor.cortes = [300_000, 200_000]
    destino = tmp_path / "modelo.bin"
    descargar([servidor.url], destino, len(CONTENIDO), SHA)
    assert destino.read_bytes() == CONTENIDO
    assert servidor.rangos == [None, "bytes=300000-", "bytes=500000-"]


def test_conexion_congelada_vence_por_inactividad_y_reanuda(servidor, tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "INACTIVIDAD", 1)
    servidor.pausas = [250_000]
    destino = tmp_path / "modelo.bin"
    inicio = time.monotonic()
    descargar([servidor.url], destino, len(CONTENIDO), SHA)
    assert destino.read_bytes() == CONTENIDO
    # Reanuda desde lo que llegó a disco (el bloque a medio leer al vencer el plazo se descarta).
    assert len(servidor.rangos) == 2 and servidor.rangos[1].startswith("bytes=")
    assert 1 <= time.monotonic() - inicio < 3


def test_conexion_que_se_arrastra_se_reemplaza_por_otra(servidor, tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "VENTANA", 0.5)
    monkeypatch.setattr(descargas, "VELOCIDAD_MINIMA", 200_000)
    servidor.goteo = [50_000]  # 50 KB/s: viva pero inútil
    destino = tmp_path / "modelo.bin"
    inicio = time.monotonic()
    descargar([servidor.url], destino, len(CONTENIDO), SHA)
    assert destino.read_bytes() == CONTENIDO
    assert servidor.rangos[0] is None and servidor.rangos[1].startswith("bytes=")
    assert time.monotonic() - inicio < 5


def test_parcial_de_una_sesion_anterior_continua(servidor, tmp_path):
    destino = tmp_path / "modelo.bin"
    (tmp_path / "modelo.bin.parcial").write_bytes(CONTENIDO[:123_456])
    descargar([servidor.url], destino, len(CONTENIDO), SHA)
    assert destino.read_bytes() == CONTENIDO
    assert servidor.rangos == ["bytes=123456-"]


def test_servidor_que_ignora_range_empieza_de_nuevo(servidor, tmp_path):
    servidor.ignorar_range = True
    destino = tmp_path / "modelo.bin"
    (tmp_path / "modelo.bin.parcial").write_bytes(CONTENIDO[:1000])
    descargar([servidor.url], destino, len(CONTENIDO), SHA)
    assert destino.read_bytes() == CONTENIDO


def test_si_la_primera_url_falla_usa_el_espejo(servidor, tmp_path):
    destino = tmp_path / "modelo.bin"
    descargar(["http://127.0.0.1:9/caido", servidor.url], destino, len(CONTENIDO), SHA)
    assert destino.read_bytes() == CONTENIDO


def test_sin_conexion_se_rinde_con_error_claro_y_avisa_la_espera(tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "ESPERAS", (1,))
    monkeypatch.setattr(descargas.time, "sleep", lambda _s: None)
    avisos = []
    with pytest.raises(ErrorDescarga):
        descargar(["http://127.0.0.1:9/caido"], tmp_path / "m.bin", 10, None, lambda _h, aviso=None: avisos.append(aviso))
    assert any(a and "reintentando" in a for a in avisos)


def test_hash_distinto_descarta_el_archivo(servidor, tmp_path):
    destino = tmp_path / "modelo.bin"
    with pytest.raises(ErrorDescarga, match="hash"):
        descargar([servidor.url], destino, len(CONTENIDO), "0" * 64)
    assert not destino.exists()
    assert not (tmp_path / "modelo.bin.parcial").exists()


def test_cancelar_detiene_la_descarga_y_conserva_lo_bajado(servidor, tmp_path):
    destino = tmp_path / "modelo.bin"
    hechos = []

    def cancelado():
        return bool(hechos) and hechos[-1] > 100_000

    with pytest.raises(Cancelado):
        descargar([servidor.url], destino, len(CONTENIDO), SHA, lambda h, aviso=None: hechos.append(h), cancelado)
    assert not destino.exists()
    assert (tmp_path / "modelo.bin.parcial").stat().st_size > 100_000
