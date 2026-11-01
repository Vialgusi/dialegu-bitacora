import io
import zipfile

import pytest

from backend.motor import gpu, trabajos
from backend.motor.descargas import ErrorDescarga


def _paquete_falso():
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as zip_:
        for nombre in gpu.CUBLAS_DLL:
            zip_.writestr(f"nvidia/cublas/bin/{nombre}", b"dll " + nombre.encode())
        zip_.writestr("nvidia/cublas/bin/nvblas64_12.dll", b"no se usa")
    return memoria.getvalue()


@pytest.fixture
def descarga_falsa(monkeypatch):
    llamadas = []

    def descargar(urls, destino, tamano, sha256, al_avanzar, *_):
        llamadas.append((urls, tamano, sha256))
        destino.write_bytes(_paquete_falso())
        al_avanzar(tamano)

    monkeypatch.setattr(gpu, "descargar", descargar)
    return llamadas


def test_extrae_solo_las_dll_de_cublas_y_borra_el_paquete(tmp_path, descarga_falsa):
    destino = gpu.asegurar_librerias(tmp_path)
    assert sorted(p.name for p in destino.iterdir()) == sorted(gpu.CUBLAS_DLL)
    assert gpu.librerias_listas(tmp_path)
    # Se pide el paquete fijado, con su tamaño y SHA-256 para que descargar() lo verifique.
    assert descarga_falsa == [([gpu.CUBLAS_URL], gpu.CUBLAS_TAMANO, gpu.CUBLAS_SHA256)]


def test_si_la_descarga_falla_no_quedan_librerias_a_medias(tmp_path, monkeypatch):
    def falla(*_args, **_kwargs):
        raise ErrorDescarga("la suma de verificación no coincide")

    monkeypatch.setattr(gpu, "descargar", falla)
    with pytest.raises(ErrorDescarga):
        gpu.asegurar_librerias(tmp_path)
    assert not gpu.librerias_listas(tmp_path)


@pytest.mark.parametrize(
    "error, esperado",
    [
        (RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"), True),
        (RuntimeError("CUDA failed with error out of memory"), True),
        (RuntimeError("otra cosa"), False),
        (ValueError("cuda"), False),
    ],
)
def test_reconoce_errores_de_gpu(error, esperado):
    assert gpu.es_error_de_gpu(error) is esperado


def test_sin_tarjeta_nvidia_usa_la_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu, "hay_gpu", lambda: False)
    cola = trabajos.Cola(tmp_path)
    assert cola._preparar_gpu(trabajos.Trabajo("t", {}, tmp_path)) == "cpu"


def test_si_falla_la_descarga_de_cuda_sigue_en_la_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu, "hay_gpu", lambda: True)

    def sin_red(*_):
        raise OSError("sin conexión")

    monkeypatch.setattr(gpu, "asegurar_librerias", sin_red)
    cola = trabajos.Cola(tmp_path)
    assert cola._preparar_gpu(trabajos.Trabajo("t", {}, tmp_path)) == "cpu"
