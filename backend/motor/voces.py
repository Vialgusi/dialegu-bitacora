"""Reconocimiento de voces (diarización) con sherpa-onnx.

sherpa-onnx retiene el GIL durante tramos largos (17 s seguidos con 10 minutos de audio), lo que
congelaría el servidor HTTP. Por eso corre en un proceso aparte que lee el WAV del trabajo.
"""

import multiprocessing as mp
import os
import queue
import wave

import numpy as np


class Cancelado(Exception):
    pass


def _leer_wav(ruta):
    with wave.open(str(ruta), "rb") as wav:
        datos = wav.readframes(wav.getnframes())
    return np.frombuffer(datos, dtype="<i2").astype(np.float32) / 32768.0


# Medición: en una entrevista de 2 voces, 0,3–0,5 dan 2 grupos grandes y 0,6 da 1;
# en un debate de 3 voces, 0,4 da 4 grupos y 0,5 da 2. Preferimos voces de más:
# unirlas en la revisión es fácil; separarlas turno por turno no lo es.
UMBRAL_AGRUPACION = 0.4
SEGUNDOS_FRAGMENTO = 20.0
FRACCION_FRAGMENTO = 0.05
TRAMOS_POR_HUELLA = 8
SEGUNDOS_MINIMOS_TRAMO = 1.5
SEGUNDOS_MAXIMOS_TRAMO = 10.0


def _huella_media(audio, tramos, extractor):
    """Huella normalizada de una voz, promediando hasta 8 trozos de sus tramos más largos; None si no alcanza."""
    trozos = []
    for inicio, fin in sorted(tramos, key=lambda t: t[1] - t[0], reverse=True):
        a = inicio
        while a + SEGUNDOS_MINIMOS_TRAMO <= fin and len(trozos) < TRAMOS_POR_HUELLA:
            trozos.append((a, min(a + SEGUNDOS_MAXIMOS_TRAMO, fin)))
            a += SEGUNDOS_MAXIMOS_TRAMO
    if not trozos:
        return None
    huellas = []
    for a, b in trozos:
        flujo = extractor.create_stream()
        flujo.accept_waveform(16000, audio[int(a * 16000) : int(b * 16000)])
        flujo.input_finished()
        h = np.asarray(extractor.compute(flujo), dtype=np.float32)
        huellas.append(h / (np.linalg.norm(h) or 1.0))
    media = np.mean(huellas, axis=0)
    return media / (np.linalg.norm(media) or 1.0)


def absorber_fragmentos(huellas, segundos):
    """Asigna solo voces breves a la voz grande con huella más parecida."""
    if len(segundos) <= 1:
        return {}
    limite = max(SEGUNDOS_FRAGMENTO, FRACCION_FRAGMENTO * sum(segundos.values()))
    grandes = [v for v, s in segundos.items() if s >= limite and huellas.get(v) is not None]
    if not grandes:
        return {}

    def similitud(a, b):
        ha, hb = huellas[a], huellas[b]
        return float(ha @ hb) / ((np.linalg.norm(ha) * np.linalg.norm(hb)) or 1.0)

    return {
        v: max(grandes, key=lambda destino: similitud(v, destino))
        for v, s in segundos.items()
        if s < limite and huellas.get(v) is not None
    }


def hilos_voces(logicos=None):
    """Pocos hilos a propósito: la app no debe acaparar el equipo de quien la usa mientras procesa."""
    return min(2, max(1, (logicos or os.cpu_count() or 4) // 4))


def _diarizar(ruta_wav, ruta_segmentacion, ruta_huellas, al_avanzar, cancelado, personas=None, hilos=None):
    import sherpa_onnx

    # `hilos` solo lo fija el banco de pruebas (backend/herramientas/banco.py); la app usa el valor por defecto.
    hilos = hilos or hilos_voces()
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(ruta_segmentacion)),
            num_threads=hilos,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(ruta_huellas), num_threads=hilos),
        # Sin un número conocido, sherpa estima cuántas voces hay usando el umbral.
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=personas if personas is not None else -1, threshold=UMBRAL_AGRUPACION),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    diarizador = sherpa_onnx.OfflineSpeakerDiarization(config)

    def avance(procesados, total):
        if cancelado():
            return 1
        al_avanzar(0.95 * procesados / max(total, 1))
        return 0

    audio = _leer_wav(ruta_wav)
    resultado = diarizador.process(audio, callback=avance)
    tramos = [(s.start, s.end, s.speaker) for s in resultado.sort_by_start_time()]
    if cancelado() or not tramos:
        return tramos

    if personas is not None:
        # La fusión alteraría el número de personas que se indicó explícitamente.
        al_avanzar(1.0)
        return tramos

    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(ruta_huellas), num_threads=hilos)
    )
    por_voz, segundos = {}, {}
    for a, b, v in tramos:
        por_voz.setdefault(v, []).append((a, b))
        segundos[v] = segundos.get(v, 0.0) + (b - a)
    huellas = {}
    for v, lista in por_voz.items():
        h = _huella_media(audio, lista, extractor)
        if h is not None:
            huellas[v] = h
    destino = absorber_fragmentos(huellas, segundos)
    al_avanzar(1.0)
    return [(a, b, destino.get(v, v)) for a, b, v in tramos]


def _proceso_hijo(ruta_wav, ruta_segmentacion, ruta_huellas, mensajes, cancelar, personas=None, hilos=None):
    try:
        tramos = _diarizar(
            ruta_wav, ruta_segmentacion, ruta_huellas, lambda f: mensajes.put(("avance", f)), cancelar.is_set, personas, hilos=hilos
        )
        mensajes.put(("cancelado", None) if cancelar.is_set() else ("listo", tramos))
    except Exception as error:  # se reenvía al proceso principal
        mensajes.put(("error", repr(error)))


def reconocer_voces(ruta_wav, ruta_segmentacion, ruta_huellas, al_avanzar, cancelado, personas=None, hilos=None):
    """Devuelve una lista de tramos (inicio, fin, voz) ordenada por inicio.

    `voz` es un entero arbitrario; el orden de aparición se decide después, en la alineación.
    """
    contexto = mp.get_context("spawn")
    mensajes, cancelar = contexto.Queue(), contexto.Event()
    hijo = contexto.Process(
        target=_proceso_hijo,
        args=(str(ruta_wav), str(ruta_segmentacion), str(ruta_huellas), mensajes, cancelar, personas, hilos),
        daemon=True,
        name="voces",
    )
    hijo.start()
    try:
        while True:
            if cancelado():
                cancelar.set()
            try:
                tipo, valor = mensajes.get(timeout=0.5)
            except queue.Empty:
                if not hijo.is_alive():
                    raise RuntimeError(f"el proceso de voces terminó sin resultado (código {hijo.exitcode})")
                continue
            if tipo == "avance":
                al_avanzar(valor)
            elif tipo == "listo":
                return valor
            elif tipo == "cancelado":
                raise Cancelado()
            else:
                raise RuntimeError(f"reconocimiento de voces: {valor}")
    finally:
        if hijo.is_alive():
            hijo.join(timeout=5)
        if hijo.is_alive():
            hijo.terminate()
