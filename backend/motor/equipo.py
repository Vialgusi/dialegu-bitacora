"""Qué equipo tiene la persona y cuánto tardará un trabajo en él.

Las estimaciones parten de una tabla de referencia y, tras cada trabajo, usan la velocidad medida en ese
mismo equipo (<datos>/velocidades.json), por modelo, dispositivo y si se distinguieron voces.
"""

import json
import os
import subprocess
import sys
import threading

from . import gpu, modelos

# Fracción de la duración del audio que tarda cada parte, medida en un i7-8700 (12 hilos) con GTX 1660 Ti.
# Ej.: 0,45 = una hora de audio tarda ~27 min. Voces y transcripción corren en paralelo.
REFERENCIA_TRANSCRIPCION = {
    "cpu": {"rapida": 0.2, "alta": 0.45, "maximo": 0.9},
    "cuda": {"rapida": 0.04, "alta": 0.08, "maximo": 0.15},
}
REFERENCIA_VOCES = 0.27  # entrevista de 64 min: 17,6 min en total con GPU, casi todo en voces
HILOS_REFERENCIA = 12
MINIMO_PARA_MEDIR = 300
SEGUNDOS_FIJOS = 20  # cargar el modelo y ordenar los turnos
SEGUNDOS_PREPARAR_GPU = 240  # primera vez: compilar los núcleos CUDA de la tarjeta
VELOCIDAD_DESCARGA = 5e6  # bytes por segundo, conservador

_candado = threading.Lock()
_gpu_detalle = None


def _procesador():
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as clave:
                return " ".join(winreg.QueryValueEx(clave, "ProcessorNameString")[0].split())
        except OSError:
            pass
    import platform

    return platform.processor() or "Procesador"


def _memoria():
    """(total, libre) en bytes; (None, None) si no se puede saber."""
    if sys.platform == "win32":
        import ctypes

        class Estado(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        estado = Estado(dwLength=ctypes.sizeof(Estado))
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
            return estado.ullTotalPhys, estado.ullAvailPhys
    return None, None


def _tarjeta():
    """{"nombre", "memoria"} de la NVIDIA según nvidia-smi (viene con el controlador); None si no hay."""
    global _gpu_detalle
    if _gpu_detalle is None:
        _gpu_detalle = {}
        if gpu.hay_gpu():
            try:
                salida = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ).stdout.splitlines()[0]
                nombre, memoria = (parte.strip() for parte in salida.split(","))
                _gpu_detalle = {"nombre": nombre, "memoria": int(float(memoria)) * 2**20}
            except (OSError, IndexError, ValueError, subprocess.SubprocessError):
                _gpu_detalle = {"nombre": "Tarjeta NVIDIA", "memoria": None}
    return _gpu_detalle or None


def describir(carpeta_modelos):
    total, libre = _memoria()
    tarjeta = _tarjeta()
    return {
        "procesador": _procesador(),
        "hilos": os.cpu_count() or 1,
        "memoria": total,
        "memoria_libre": libre,
        "gpu": tarjeta and {**tarjeta, "librerias": gpu.librerias_listas(carpeta_modelos), "preparada": gpu.preparada(carpeta_modelos)},
        "modelos": {
            calidad: {
                "nombre": modelo["nombre"],
                "tamano": sum(t for _a, t, _h in modelo["archivos"]),
                "descargado": modelos.whisper_descargado(carpeta_modelos, calidad),
            }
            for calidad, modelo in modelos.WHISPER.items()
        },
    }


def clave(calidad, dispositivo, distinguir_voces):
    return f"{calidad}|{dispositivo}|{'voces' if distinguir_voces else 'sin_voces'}"


def leer_velocidades(carpeta_datos):
    try:
        return json.loads((carpeta_datos / "velocidades.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def registrar_velocidad(carpeta_datos, calidad, dispositivo, distinguir_voces, segundos, duracion):
    """Guarda cuánto tardó por segundo de audio; promedia con lo anterior para suavizar."""
    if duracion < MINIMO_PARA_MEDIR:
        return  # en audios cortos domina la carga del modelo y la medida se infla
    with _candado:
        velocidades = leer_velocidades(carpeta_datos)
        nueva = segundos / duracion
        anterior = velocidades.get(clave(calidad, dispositivo, distinguir_voces))
        velocidades[clave(calidad, dispositivo, distinguir_voces)] = round(nueva if anterior is None else (anterior + nueva) / 2, 4)
        (carpeta_datos / "velocidades.json").write_text(json.dumps(velocidades, indent=1), encoding="utf-8")


def duracion_audio(ruta):
    """Duración en segundos leyendo solo la cabecera del archivo; None si no se puede."""
    try:
        import av

        with av.open(str(ruta)) as contenedor:
            if contenedor.duration:
                return contenedor.duration / 1e6
            flujo = next(iter(contenedor.streams.audio), None)
            if flujo and flujo.duration and flujo.time_base:
                return float(flujo.duration * flujo.time_base)
    except Exception:
        pass
    return None


def estimar(carpeta_datos, carpeta_modelos, duracion, calidad, usar_gpu, distinguir_voces):
    """Segundos estimados del trabajo, desglosados, y si sale de una medición en este equipo."""
    dispositivo = "cuda" if usar_gpu and gpu.hay_gpu() else "cpu"
    medida = leer_velocidades(carpeta_datos).get(clave(calidad, dispositivo, distinguir_voces))
    if medida is not None:
        proceso = medida * duracion
    else:
        escala = min(3.0, max(0.5, HILOS_REFERENCIA / (os.cpu_count() or HILOS_REFERENCIA)))
        transcribir = REFERENCIA_TRANSCRIPCION[dispositivo][calidad] * (escala if dispositivo == "cpu" else 1)
        voces = REFERENCIA_VOCES * escala if distinguir_voces else 0
        proceso = max(transcribir, voces) * duracion + SEGUNDOS_FIJOS
    pendientes = modelos.bytes_pendientes(carpeta_modelos, calidad, distinguir_voces)
    preparar = dispositivo == "cuda" and not gpu.preparada(carpeta_modelos)
    if dispositivo == "cuda" and not gpu.librerias_listas(carpeta_modelos):
        pendientes += gpu.CUBLAS_TAMANO
    return {
        "duracion": duracion,
        "dispositivo": "gpu" if dispositivo == "cuda" else "cpu",
        "segundos": round(proceso + pendientes / VELOCIDAD_DESCARGA + (SEGUNDOS_PREPARAR_GPU if preparar else 0)),
        "segundos_proceso": round(proceso),
        "medido": medida is not None,
        "descarga": pendientes,
        "preparar_gpu": preparar,
    }
