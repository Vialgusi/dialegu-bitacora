"""Aceleración con tarjeta gráfica NVIDIA (CUDA) para la transcripción.

ctranslate2 ya trae cuDNN; falta cuBLAS, que pesa ~550 MB y solo sirve a quien tiene NVIDIA. Por eso no va en el
instalador: se descarga la primera vez desde el paquete oficial de NVIDIA en PyPI, verificado con SHA-256, y se
guardan solo las dos DLL necesarias en <datos>/modelos/cuda. Si algo falla, el motor sigue en la CPU.
"""

import os
import threading
import zipfile
from pathlib import Path

from .descargas import descargar

# nvidia-cublas-cu12 12.8.4.1 (CUDA 12.8; corre con controladores NVIDIA 525 o posteriores).
CUBLAS_URL = (
    "https://files.pythonhosted.org/packages/70/61/7d7b3c70186fb651d0fbd35b01dbfc8e755f69fd58f817f3d0f642df20c3/"
    "nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl"
)
CUBLAS_TAMANO = 567544208
CUBLAS_SHA256 = "47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af"
CUBLAS_DLL = ("cublas64_12.dll", "cublasLt64_12.dll")

_gpu = None
_activada = False
_candado = threading.Lock()


def hay_gpu():
    """True si hay al menos una tarjeta NVIDIA con controlador CUDA. No necesita cuBLAS."""
    global _gpu
    if _gpu is None:
        try:
            import ctranslate2

            _gpu = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            _gpu = False
    return _gpu


def carpeta_cuda(carpeta_modelos):
    return Path(carpeta_modelos) / "cuda"


def librerias_listas(carpeta_modelos):
    return all((carpeta_cuda(carpeta_modelos) / nombre).exists() for nombre in CUBLAS_DLL)


def preparada(carpeta_modelos):
    """La primera carga en una tarjeta compila sus núcleos CUDA (varios minutos); luego quedan en caché."""
    return (carpeta_cuda(carpeta_modelos) / "preparada").exists()


def marcar_preparada(carpeta_modelos):
    (carpeta_cuda(carpeta_modelos) / "preparada").touch()


def asegurar_librerias(carpeta_modelos, al_avanzar=lambda fraccion: None):
    """Descarga cuBLAS la primera vez y deja sus DLL en <modelos>/cuda."""
    destino = carpeta_cuda(carpeta_modelos)
    if librerias_listas(carpeta_modelos):
        return destino
    destino.mkdir(parents=True, exist_ok=True)
    paquete = destino / "cublas.whl"
    try:
        # descargar() reanuda cortes, reintenta y verifica tamaño y SHA-256 antes de entregar el archivo.
        descargar([CUBLAS_URL], paquete, CUBLAS_TAMANO, CUBLAS_SHA256, lambda hechos, aviso=None: al_avanzar(0.95 * hechos / CUBLAS_TAMANO))
        with zipfile.ZipFile(paquete) as zip_:
            for nombre in CUBLAS_DLL:
                temporal = destino / (nombre + ".parcial")
                with zip_.open(f"nvidia/cublas/bin/{nombre}") as origen, open(temporal, "wb") as salida:
                    while bloque := origen.read(1 << 20):
                        salida.write(bloque)
                os.replace(temporal, destino / nombre)
    finally:
        paquete.unlink(missing_ok=True)
    al_avanzar(1.0)
    return destino


def activar(carpeta_modelos):
    """Hace visibles las DLL de cuBLAS para ctranslate2 (las carga con LoadLibrary al usar la GPU)."""
    global _activada
    with _candado:
        if _activada:
            return
        ruta = str(carpeta_cuda(carpeta_modelos))
        os.add_dll_directory(ruta)
        os.environ["PATH"] = ruta + os.pathsep + os.environ.get("PATH", "")
        _activada = True


def es_error_de_gpu(error):
    """Errores tras los que conviene repetir en la CPU: librerías, memoria de video o el controlador."""
    texto = str(error).lower()
    return isinstance(error, (RuntimeError, OSError)) and any(
        clave in texto for clave in ("cuda", "cublas", "cudnn", "out of memory", "gpu", ".dll")
    )
