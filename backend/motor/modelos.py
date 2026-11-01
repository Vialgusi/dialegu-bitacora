"""Descarga y carga de modelos. Todo queda en <datos>/modelos y se descarga una sola vez.

Los archivos se piden a Hugging Face en una revisión fija (su contenido no cambia) y, si falla,
a su espejo hf-mirror.com. Cada uno lleva su tamaño y, los grandes, su SHA-256 para verificarlo.
"""

import os
import shutil
import threading
from pathlib import Path

from faster_whisper import WhisperModel

from .descargas import descargar

ESPEJOS = ("https://huggingface.co", "https://hf-mirror.com")

# Segmentación pyannote 3.0 (MIT) y huellas de voz 3D-Speaker ERes2Net (Apache-2.0), exportadas por sherpa-onnx.
SEGMENTACION = {
    "repo": "csukuangfj/sherpa-onnx-pyannote-segmentation-3-0",
    "revision": "9403a6902bb58e3d5ae8c7e77c3422de279db2e0",
    "carpeta": "sherpa-onnx-pyannote-segmentation-3-0",
    "archivos": [("model.onnx", 5992913, "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079")],
}
HUELLAS = {
    "repo": "csukuangfj/speaker-embedding-models",
    "revision": "0743f301363dec56491a490f6d6cbc9d67f9a3bf",
    "carpeta": "",
    "archivos": [
        (
            "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
            39593761,
            "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
        )
    ],
    # Nombre local que ya usaban las versiones anteriores.
    "renombrar": {"3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx": "3dspeaker_eres2net_base_16k.onnx"},
}
WHISPER = {
    "rapida": {
        "nombre": "small",
        "repo": "Systran/faster-whisper-small",
        "revision": "536b0662742c02347bc0e980a01041f333bce120",
        "carpeta": "faster-whisper-small",
        "archivos": [
            ("config.json", 2370, None),
            ("tokenizer.json", 2203239, None),
            ("vocabulary.txt", 459861, None),
            ("model.bin", 483546902, "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
        ],
    },
    "alta": {
        "nombre": "large-v3-turbo",
        "repo": "dropbox-dash/faster-whisper-large-v3-turbo",
        "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        "carpeta": "faster-whisper-large-v3-turbo",
        "archivos": [
            ("config.json", 2263, None),
            ("preprocessor_config.json", 340, None),
            ("tokenizer.json", 2710337, None),
            ("vocabulary.json", 1068114, None),
            ("model.bin", 1617884929, "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"),
        ],
    },
    "maximo": {
        "nombre": "large-v3",
        "repo": "Systran/faster-whisper-large-v3",
        "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        "carpeta": "faster-whisper-large-v3",
        "archivos": [
            ("config.json", 2394, None),
            ("preprocessor_config.json", 340, None),
            ("tokenizer.json", 2480617, None),
            ("vocabulary.json", 1068114, None),
            ("model.bin", 3087284237, "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1"),
        ],
    },
}

_whisper = {}
_candado_whisper = threading.Lock()


def _destino(carpeta, modelo, archivo):
    nombre = modelo.get("renombrar", {}).get(archivo, archivo)
    return Path(carpeta) / modelo["carpeta"] / nombre


def _faltantes(carpeta, modelo):
    return [(a, t, h) for a, t, h in modelo["archivos"] if not _destino(carpeta, modelo, a).exists()]


def _cache_anterior(carpeta, calidad):
    """Modelo de Whisper que bajaron versiones anteriores con huggingface_hub, si está completo."""
    nombre = WHISPER[calidad]["nombre"]
    for modelo_bin in Path(carpeta).glob(f"models--*--faster-whisper-{nombre}/snapshots/*/model.bin"):
        return modelo_bin.parent
    return None


def _adoptar_incompleto(carpeta, modelo):
    """Aprovecha lo que huggingface_hub dejó a medias (versiones anteriores) como punto de partida."""
    for archivo, _tamano, sha in modelo["archivos"]:
        parcial = _destino(carpeta, modelo, archivo).with_name(archivo + ".parcial")
        if not sha or parcial.exists():
            continue
        for viejo in Path(carpeta).glob(f"models--*/blobs/{sha}*.incomplete"):
            parcial.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(viejo, parcial)
            except OSError:  # otra instancia lo tiene abierto: se descarga desde cero
                pass
            break


def ruta_whisper(carpeta, calidad):
    """Carpeta local del modelo de Whisper de esa calidad, o None si falta descargarlo."""
    modelo = WHISPER[calidad]
    if not _faltantes(carpeta, modelo):
        return Path(carpeta) / modelo["carpeta"]
    return _cache_anterior(carpeta, calidad)


def whisper_descargado(carpeta, calidad):
    """True si el modelo de Whisper de esa calidad ya está en la carpeta local."""
    return ruta_whisper(carpeta, calidad) is not None


def bytes_pendientes(carpeta, calidad, distinguir_voces):
    """Bytes que faltaría descargar para un trabajo con esa calidad (0 si ya está todo)."""
    modelos = [SEGMENTACION, HUELLAS] if distinguir_voces else []
    if ruta_whisper(carpeta, calidad) is None:
        modelos.append(WHISPER[calidad])
    return sum(tamano for modelo in modelos for _a, tamano, _h in _faltantes(carpeta, modelo))


def asegurar_modelos(carpeta, calidad, distinguir_voces, al_avanzar=lambda hechos, total, aviso=None: None, cancelado=lambda: False):
    """Descarga lo que falte y devuelve {"whisper", "segmentacion", "huellas"} con rutas locales.

    al_avanzar(hechos, total, aviso) cuenta bytes sobre el total pendiente de esta llamada.
    """
    carpeta = Path(carpeta)
    modelos = [SEGMENTACION, HUELLAS] if distinguir_voces else []
    if ruta_whisper(carpeta, calidad) is None:
        modelos.append(WHISPER[calidad])
    pendientes = []
    for modelo in modelos:
        _adoptar_incompleto(carpeta, modelo)
        pendientes += [(modelo, archivo, tamano, sha) for archivo, tamano, sha in _faltantes(carpeta, modelo)]
    total = sum(t for _m, _a, t, _h in pendientes)
    if pendientes:
        print(f"[modelos] por descargar: {', '.join(a for _m, a, _t, _h in pendientes)} ({total / 1e6:.0f} MB)", flush=True)
    previos = 0
    for modelo, archivo, tamano, sha in pendientes:
        urls = [f"{base}/{modelo['repo']}/resolve/{modelo['revision']}/{archivo}" for base in ESPEJOS]
        descargar(
            urls,
            _destino(carpeta, modelo, archivo),
            tamano,
            sha,
            lambda hechos, aviso=None, previos=previos: al_avanzar(previos + hechos, total, aviso),
            cancelado,
        )
        previos += tamano
    return {
        "whisper": ruta_whisper(carpeta, calidad),
        "segmentacion": _destino(carpeta, SEGMENTACION, "model.onnx") if distinguir_voces else None,
        "huellas": _destino(carpeta, HUELLAS, HUELLAS["archivos"][0][0]) if distinguir_voces else None,
    }


def cargar_whisper(ruta, dispositivo="cpu"):
    """Carga el modelo de Whisper desde su carpeta local; queda en memoria para los siguientes trabajos."""
    clave = (str(ruta), dispositivo)
    with _candado_whisper:
        if clave not in _whisper:
            _whisper[clave] = WhisperModel(
                str(ruta),
                device=dispositivo,
                # En la GPU, int8_float16: en una GTX 1660 Ti float16 puro fue 3 veces más lento y float32 ocupa el doble.
                compute_type="int8_float16" if dispositivo == "cuda" else "int8",
                # Deja libre buena parte del equipo; las voces corren en paralelo con otros 2 hilos.
                cpu_threads=min(4, max(1, (os.cpu_count() or 4) // 3)),
            )
        return _whisper[clave]
