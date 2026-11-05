"""Banco de pruebas de rendimiento: mide variantes del motor sobre un corpus con referencia.

Diseño completo, hipótesis y criterios de decisión: docs/specs/SPEC-PRUEBAS-RENDIMIENTO.md.

Reproduce la tubería de backend/motor/trabajos.py (decodificar, cargar Whisper, voces y texto,
alinear) con los parámetros como variables. Cada corrida va en un proceso nuevo, para que la RAM
pico y la carga del modelo sean las de esa corrida. No se empaqueta en el instalador.

    python -m backend.herramientas.banco --corpus corpus.json --variantes variantes.json \\
        --datos <carpeta de datos> --salida resultados-banco [--repeticiones 3] [--nucleos 4]
    python -m backend.herramientas.banco --resumir resultados-banco/<sesion>
"""

import argparse
import datetime
import hashlib
import json
import multiprocessing as mp
import os
import platform
import queue
import random
import statistics
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

FRECUENCIA = 16000

# La configuración de la app 0.4.1. Toda variante parte de aquí y cambia solo lo que declara.
VARIANTE_BASE = {
    "calidad": "alta",
    "compute_type": "int8",
    "hilos_whisper": "produccion",
    "hilos_voces": "produccion",
    "beam_size": 5,
    "por_lotes": False,
    "tamano_lote": 8,
    "distinguir_voces": True,
    "voces_sin_silencio": False,
    "paralelo": True,
}
HILOS_VALIDOS = ("produccion", "fisicos-1", "todos", "mitad")
CALIDADES = ("rapida", "alta", "maximo")
CAMPOS_AUDIO = {"id", "audio", "referencia", "sha256_referencia", "idioma", "personas", "tema", "tipo", "grupo", "recortar"}

# Criterios de §8 de la especificación.
MEJORA_ACEPTAR = 0.15
MEJORA_MINIMA = 0.10
WER_MEDIO_ACEPTAR = 1.0
WER_MAXIMO_ACEPTAR = 2.0
WER_DESCARTAR = 3.0
DER_MEDIO_ACEPTAR = 2.0
FRACCION_RAM = 0.6
LENTITUD_ACEPTAR = 2.0


# --- Configuración ---------------------------------------------------------------


def _validar_hilos(valor, campo, id_):
    if valor in HILOS_VALIDOS or (type(valor) is int and valor >= 1):
        return
    raise ValueError(f"variante {id_}: {campo} debe ser un entero ≥ 1 o uno de {', '.join(HILOS_VALIDOS)}")


def normalizar_variantes(lista):
    """Completa cada variante con la base, valida tipos y garantiza que exista `base` (primera)."""
    if not isinstance(lista, list):
        raise ValueError("el archivo de variantes debe ser una lista JSON")
    variantes, ids = [], set()
    for entrada in lista:
        if not isinstance(entrada, dict) or not isinstance(entrada.get("id"), str) or not entrada["id"]:
            raise ValueError("cada variante necesita un `id` de texto")
        id_ = entrada["id"]
        if id_ in ids:
            raise ValueError(f"variante repetida: {id_}")
        desconocidas = set(entrada) - set(VARIANTE_BASE) - {"id", "descripcion"}
        if desconocidas:
            raise ValueError(f"variante {id_}: claves desconocidas {sorted(desconocidas)}")
        variante = {"id": id_, "descripcion": entrada.get("descripcion", ""), **VARIANTE_BASE}
        variante.update({k: v for k, v in entrada.items() if k in VARIANTE_BASE})
        if variante["calidad"] not in CALIDADES:
            raise ValueError(f"variante {id_}: calidad debe ser una de {', '.join(CALIDADES)}")
        _validar_hilos(variante["hilos_whisper"], "hilos_whisper", id_)
        _validar_hilos(variante["hilos_voces"], "hilos_voces", id_)
        for campo in ("beam_size", "tamano_lote"):
            if type(variante[campo]) is not int or variante[campo] < 1:
                raise ValueError(f"variante {id_}: {campo} debe ser un entero ≥ 1")
        for campo in ("por_lotes", "distinguir_voces", "voces_sin_silencio", "paralelo"):
            if type(variante[campo]) is not bool:
                raise ValueError(f"variante {id_}: {campo} debe ser true o false")
        ids.add(id_)
        variantes.append(variante)
    if "base" not in ids:
        variantes.insert(0, {"id": "base", "descripcion": "Motor 0.4.1 sin cambios", **VARIANTE_BASE})
    else:
        variantes.sort(key=lambda v: v["id"] != "base")
    return variantes


def normalizar_corpus(lista, carpeta):
    """Valida el corpus; las rutas relativas se resuelven contra la carpeta del archivo de corpus."""
    if not isinstance(lista, list) or not lista:
        raise ValueError("el corpus debe ser una lista JSON no vacía")
    audios, ids = [], set()
    for entrada in lista:
        if not isinstance(entrada, dict) or not isinstance(entrada.get("id"), str) or not isinstance(entrada.get("audio"), str):
            raise ValueError("cada audio del corpus necesita `id` y `audio`")
        if entrada["id"] in ids:
            raise ValueError(f"audio repetido en el corpus: {entrada['id']}")
        desconocidas = set(entrada) - CAMPOS_AUDIO
        if desconocidas:
            raise ValueError(f"audio {entrada['id']}: claves desconocidas {sorted(desconocidas)}")
        personas = entrada.get("personas")
        if personas is not None and (type(personas) is not int or not 1 <= personas <= 12):
            raise ValueError(f"audio {entrada['id']}: personas debe ser un entero entre 1 y 12 o null")
        recortar = entrada.get("recortar")
        if recortar is not None and (not isinstance(recortar, (int, float)) or isinstance(recortar, bool) or recortar <= 0):
            raise ValueError(f"audio {entrada['id']}: recortar debe ser un número de segundos > 0")
        audio = {
            "id": entrada["id"],
            "audio": str((carpeta / entrada["audio"]).resolve()),
            "referencia": str((carpeta / entrada["referencia"]).resolve()) if entrada.get("referencia") else None,
            "sha256_referencia": entrada.get("sha256_referencia"),
            "idioma": entrada.get("idioma", "es"),
            "personas": personas,
            "tema": entrada.get("tema", ""),
            "tipo": entrada.get("tipo", "entrevista"),
            "grupo": entrada.get("grupo"),
            "recortar": recortar,
        }
        ids.add(audio["id"])
        audios.append(audio)
    return audios


def resolver_hilos(valor, etapa, logicos, fisicos):
    """Número de hilos para `etapa` ("whisper" o "voces") en un equipo con esos hilos lógicos y núcleos físicos."""
    if type(valor) is int:
        return valor
    if valor == "produccion":
        # Las mismas fórmulas que la app, pero con los hilos del equipo (real o simulado).
        if etapa == "whisper":
            return min(4, max(1, logicos // 3))
        return min(2, max(1, logicos // 4))
    if valor == "fisicos-1":
        return max(1, fisicos - 1)
    if valor == "todos":
        return max(1, logicos)
    if valor == "mitad":
        return max(1, logicos // 2)
    raise ValueError(f"hilos desconocidos: {valor}")


def plan(variantes, audios, repeticiones, semilla):
    """Lista de corridas (variante, audio, repetición) en un orden barajado y reproducible."""
    corridas = [(v["id"], a["id"], r) for r in range(1, repeticiones + 1) for v in variantes for a in audios]
    random.Random(semilla).shuffle(corridas)
    return corridas


# --- Audio sin silencios (H5) ---------------------------------------------------------


def compactar(segmentos):
    """Mapa de piezas (inicio_original, inicio_compacto, duracion) en segundos a partir de tramos de habla.

    `segmentos` son pares (inicio, fin) en segundos, ordenados y sin solaparse (como los devuelve el VAD).
    """
    mapa, cursor = [], 0.0
    for inicio, fin in segmentos:
        if fin <= inicio:
            continue
        mapa.append((inicio, cursor, fin - inicio))
        cursor += fin - inicio
    return mapa


def devolver_tramos(tramos, mapa):
    """Lleva tramos (inicio, fin, voz) del audio compacto al original, partiéndolos en cada corte de silencio."""
    salida = []
    for a, b, voz in tramos:
        for original, compacto, duracion in mapa:
            desde, hasta = max(a, compacto), min(b, compacto + duracion)
            if hasta > desde:
                salida.append((original + desde - compacto, original + hasta - compacto, voz))
    return sorted(salida)


# --- Referencias -----------------------------------------------------------------


def recortar_documento(documento, segundos):
    """Deja en el documento solo lo dicho antes de `segundos`; usa las palabras si las hay."""
    turnos = []
    for turno in documento["turnos"]:
        if turno["inicio"] >= segundos:
            continue
        palabras = turno.get("palabras")
        if palabras:
            dentro = [p for p in palabras if p["fin"] <= segundos]
            if not dentro:
                continue
            turnos.append({**turno, "fin": dentro[-1]["fin"], "palabras": dentro, "texto": " ".join(p["texto"] for p in dentro)})
        elif turno["fin"] <= segundos:
            turnos.append(turno)
    usadas = {t["voz"] for t in turnos}
    return {**documento, "turnos": turnos, "voces": [v for v in documento.get("voces", []) if v.get("id") in usadas]}


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


# --- Equipo --------------------------------------------------------------------


def _psutil():
    try:
        import psutil

        return psutil
    except ImportError:
        return None


def _nucleos_fisicos():
    psutil = _psutil()
    fisicos = psutil.cpu_count(logical=False) if psutil else None
    return fisicos or max(1, (os.cpu_count() or 2) // 2)


def describir_equipo(nucleos=None):
    from importlib import metadata

    from backend.motor import equipo

    logicos_reales = os.cpu_count() or 1
    fisicos_reales = _nucleos_fisicos()
    try:
        from numpy._core._multiarray_umath import __cpu_features__ as rasgos
    except ImportError:  # numpy < 2
        from numpy.core._multiarray_umath import __cpu_features__ as rasgos
    versiones = {}
    for paquete in ("ctranslate2", "faster-whisper", "sherpa-onnx", "onnxruntime", "av", "numpy"):
        try:
            versiones[paquete] = metadata.version(paquete)
        except metadata.PackageNotFoundError:
            versiones[paquete] = None
    psutil = _psutil()
    logicos = min(nucleos, logicos_reales) if nucleos else logicos_reales
    return {
        "procesador": equipo._procesador(),
        "sistema": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "hilos_logicos": logicos_reales,
        "nucleos_fisicos": fisicos_reales,
        "memoria": psutil.virtual_memory().total if psutil else equipo._memoria()[0],
        "instrucciones": sorted(k for k in ("AVX", "AVX2", "FMA3", "AVX512F", "AVX512_SKX", "NEON") if rasgos.get(k)),
        "versiones": versiones,
        "simulado": bool(nucleos and nucleos < logicos_reales),
        "hilos_efectivos": logicos,
        "fisicos_efectivos": max(1, round(logicos * fisicos_reales / logicos_reales)),
    }


def _limitar_nucleos(nucleos):
    if not nucleos:
        return
    cpus = list(range(min(nucleos, os.cpu_count() or nucleos)))
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, cpus)
        return
    psutil = _psutil()
    if psutil is None:
        raise RuntimeError("--nucleos necesita psutil en este sistema: pip install psutil")
    psutil.Process().cpu_affinity(cpus)


# --- Sonda de lentitud del equipo ------------------------------------------------------


def _trabajo_fijo(vueltas):
    total = 0
    for i in range(vueltas):
        total += i * i
    return total


def calibrar_sonda(objetivo=0.02):
    """Vueltas que tardan ~20 ms con el equipo en reposo."""
    vueltas = 10000
    while True:
        inicio = time.perf_counter()
        _trabajo_fijo(vueltas)
        transcurrido = time.perf_counter() - inicio
        if transcurrido >= objetivo / 4:
            return max(1000, int(vueltas * objetivo / transcurrido))
        vueltas *= 4


def _sonda(vueltas, parar, duraciones):
    while not parar.is_set():
        inicio = time.perf_counter()
        _trabajo_fijo(vueltas)
        duraciones.put(time.perf_counter() - inicio)
        time.sleep(0.1)


def percentil(valores, p):
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(round(p * (len(ordenados) - 1))))]


def _vaciar(cola):
    valores = []
    while True:
        try:
            valores.append(cola.get_nowait())
        except queue.Empty:
            return valores


def medir_reposo(contexto, vueltas, segundos=3.0):
    parar, duraciones = contexto.Event(), contexto.Queue()
    sonda = contexto.Process(target=_sonda, args=(vueltas, parar, duraciones), daemon=True)
    sonda.start()
    time.sleep(segundos)
    parar.set()
    sonda.join(timeout=5)
    return percentil(_vaciar(duraciones), 0.95)


# --- Una corrida (en su propio proceso) ---------------------------------------------------


def _guardar_wav(ruta, muestras):
    enteros = (np.clip(muestras, -1, 1) * 32767).astype("<i2")
    with wave.open(str(ruta), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(FRECUENCIA)
        wav.writeframes(enteros.tobytes())


def ejecutar_corrida(tarea):
    """Corre la tubería completa con una variante. Devuelve tiempos por etapa y el documento .bitacora."""
    from concurrent.futures import ThreadPoolExecutor

    _limitar_nucleos(tarea["nucleos"])
    from faster_whisper import BatchedInferencePipeline, WhisperModel
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    from backend.motor import alineacion, modelos, voces

    v, a = tarea["variante"], tarea["audio"]
    carpeta_modelos = Path(tarea["datos"]) / "modelos"
    rutas = modelos.asegurar_modelos(carpeta_modelos, v["calidad"], v["distinguir_voces"])
    tiempos = {}
    reloj = time.perf_counter
    inicio = reloj()

    muestras = decode_audio(a["audio"], sampling_rate=FRECUENCIA)
    if a.get("recortar"):
        muestras = muestras[: int(a["recortar"] * FRECUENCIA)]
    duracion = len(muestras) / FRECUENCIA
    temporal = tempfile.TemporaryDirectory(prefix="banco-")
    ruta_wav = Path(temporal.name) / "audio.wav"
    mapa = None
    if v["distinguir_voces"]:
        if v["voces_sin_silencio"]:
            # Los mismos parámetros de VAD que usa la transcripción, para cortar donde Whisper también corta.
            opciones = VadOptions(min_silence_duration_ms=700, speech_pad_ms=400)
            habla = [(s["start"] / FRECUENCIA, s["end"] / FRECUENCIA) for s in get_speech_timestamps(muestras, opciones)]
            mapa = compactar(habla)
            partes = [muestras[int(o * FRECUENCIA) : int((o + d) * FRECUENCIA)] for o, _c, d in mapa]
            _guardar_wav(ruta_wav, np.concatenate(partes) if partes else muestras[:0])
            tiempos["habla_fraccion"] = sum(d for _o, _c, d in mapa) / duracion if duracion else 0
        else:
            _guardar_wav(ruta_wav, muestras)
    tiempos["decodificar"] = reloj() - inicio

    t0 = reloj()
    modelo = WhisperModel(str(rutas["whisper"]), device="cpu", compute_type=v["compute_type"], cpu_threads=tarea["hilos_whisper"])
    tiempos["cargar"] = reloj() - t0

    def texto():
        t = reloj()
        parametros = dict(
            language=None if a["idioma"] == "auto" else a["idioma"],
            beam_size=v["beam_size"],
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
            vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 400},
            hotwords=a.get("tema", "").strip() or None,
        )
        if v["por_lotes"]:
            segmentos, _ = BatchedInferencePipeline(modelo).transcribe(muestras, batch_size=v["tamano_lote"], **parametros)
        else:
            segmentos, _ = modelo.transcribe(muestras, **parametros)
        palabras = [(w.start, w.end, w.word) for s in segmentos for w in (s.words or [])]
        tiempos["transcripcion"] = reloj() - t
        return palabras

    def voces_():
        t = reloj()
        tramos = voces.reconocer_voces(
            ruta_wav, rutas["segmentacion"], rutas["huellas"], lambda _f: None, lambda: False, a.get("personas"), hilos=tarea["hilos_voces"]
        )
        if mapa is not None:
            tramos = devolver_tramos(tramos, mapa)
        tiempos["voces"] = reloj() - t
        return tramos

    if not v["distinguir_voces"]:
        palabras, tramos = texto(), []
    elif v["paralelo"]:
        with ThreadPoolExecutor(max_workers=2) as hilos:
            futuro_voces, futuro_texto = hilos.submit(voces_), hilos.submit(texto)
            palabras, tramos = futuro_texto.result(), futuro_voces.result()
    else:
        tramos = voces_()
        palabras = texto()

    t0 = reloj()
    turnos = alineacion.agrupar_turnos(alineacion.asignar_voces(palabras, tramos))
    meta = {"nombre": a["id"], "tipo": a["tipo"], "duracion": round(duracion, 2), "idioma": a["idioma"], "banco": v["id"]}
    documento = alineacion.armar_transcripcion(turnos, meta)
    tiempos["alineacion"] = reloj() - t0
    tiempos["total"] = reloj() - inicio
    temporal.cleanup()
    return {"duracion": duracion, "tiempos": tiempos, "documento": documento}


def _hijo(tarea, resultado):
    try:
        resultado.put(("ok", ejecutar_corrida(tarea)))
    except BaseException as error:  # se reporta en la línea de resultados
        resultado.put(("error", repr(error)))


def correr_aislado(contexto, tarea, vueltas_sonda, intervalo=0.2):
    """Lanza la corrida en un proceso nuevo, mide RAM pico y CPU del árbol de procesos y la lentitud con la sonda.

    La RAM y la CPU necesitan psutil (opcional, solo para el banco); sin él quedan vacías.
    """
    psutil = _psutil()
    resultado = contexto.Queue()
    parar, duraciones = contexto.Event(), contexto.Queue()
    sonda = contexto.Process(target=_sonda, args=(vueltas_sonda, parar, duraciones), daemon=True) if vueltas_sonda else None
    hijo = contexto.Process(target=_hijo, args=(tarea, resultado), daemon=False)
    inicio = time.perf_counter()
    hijo.start()
    if sonda:
        sonda.start()
    ram_pico, cpu_por_pid, respuesta = 0, {}, None
    try:
        while respuesta is None:
            if psutil:
                try:
                    raiz = psutil.Process(hijo.pid)
                    arbol = [raiz, *raiz.children(recursive=True)]
                    ram = 0
                    for proceso in arbol:
                        try:
                            ram += proceso.memory_info().rss
                            veces = proceso.cpu_times()
                            cpu_por_pid[proceso.pid] = veces.user + veces.system
                        except psutil.Error:
                            pass
                    ram_pico = max(ram_pico, ram)
                except psutil.Error:
                    pass
            try:
                respuesta = resultado.get(timeout=intervalo)
            except queue.Empty:
                if not hijo.is_alive():
                    respuesta = ("error", f"el proceso terminó sin resultado (código {hijo.exitcode})")
    finally:
        reloj = time.perf_counter() - inicio
        if sonda:
            parar.set()
            sonda.join(timeout=5)
        hijo.join(timeout=30)
        if hijo.is_alive():
            hijo.terminate()
    return {
        "estado": respuesta[0],
        "valor": respuesta[1],
        "ram_pico": ram_pico or None,
        "cpu_media": (sum(cpu_por_pid.values()) / reloj) if cpu_por_pid and reloj else None,
        "sonda_p95": percentil(_vaciar(duraciones), 0.95) if sonda else None,
    }


# --- Sesión ------------------------------------------------------------------------


def correr_sesion(args):
    from backend.herramientas import medir

    variantes = normalizar_variantes(json.loads(Path(args.variantes).read_text(encoding="utf-8")))
    audios = normalizar_corpus(json.loads(Path(args.corpus).read_text(encoding="utf-8")), Path(args.corpus).resolve().parent)
    equipo = describir_equipo(args.nucleos)
    corridas = plan(variantes, audios, args.repeticiones, args.semilla)
    por_variante = {v["id"]: v for v in variantes}
    por_audio = {a["id"]: a for a in audios}
    hilos = {
        v["id"]: {
            "whisper": resolver_hilos(v["hilos_whisper"], "whisper", equipo["hilos_efectivos"], equipo["fisicos_efectivos"]),
            "voces": resolver_hilos(v["hilos_voces"], "voces", equipo["hilos_efectivos"], equipo["fisicos_efectivos"]),
        }
        for v in variantes
    }
    print(f"Equipo: {equipo['procesador']} · {equipo['hilos_efectivos']} hilos" + (" (simulado)" if equipo["simulado"] else ""))
    for v in variantes:
        print(f"  {v['id']:<22} Whisper {hilos[v['id']]['whisper']} hilos · voces {hilos[v['id']]['voces']} hilos · {v['descripcion']}")
    print(f"{len(corridas)} corridas ({len(variantes)} variantes × {len(audios)} audios × {args.repeticiones} repeticiones)")
    if args.en_seco:
        for corrida in corridas:
            print("  ", *corrida)
        return None

    referencias = {}
    for a in audios:
        if not a["referencia"]:
            continue
        if a["sha256_referencia"] and sha256(a["referencia"]) != a["sha256_referencia"]:
            raise SystemExit(f"La referencia de {a['id']} cambió (SHA-256 distinto). Corrija el corpus o la referencia.")
        documento = medir.leer_proyecto(a["referencia"])
        referencias[a["id"]] = recortar_documento(documento, a["recortar"]) if a["recortar"] else documento

    sesion = Path(args.salida) / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    (sesion / "hipotesis").mkdir(parents=True)
    (sesion / "equipo.json").write_text(json.dumps(equipo, ensure_ascii=False, indent=1), encoding="utf-8")
    (sesion / "plan.json").write_text(
        json.dumps({"variantes": variantes, "audios": audios, "corridas": corridas, "semilla": args.semilla, "hilos": hilos}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    contexto = mp.get_context("spawn")
    vueltas = calibrar_sonda() if not args.sin_sonda else None
    reposo = medir_reposo(contexto, vueltas) if vueltas else None

    def tarea(variante_id, audio_id):
        return {
            "variante": por_variante[variante_id],
            "audio": por_audio[audio_id],
            "datos": args.datos,
            "nucleos": args.nucleos,
            "hilos_whisper": hilos[variante_id]["whisper"],
            "hilos_voces": hilos[variante_id]["voces"],
        }

    from backend.motor import modelos

    print("Preparando modelos y calentando (no cuenta)…", flush=True)
    for v in variantes:
        modelos.asegurar_modelos(Path(args.datos) / "modelos", v["calidad"], v["distinguir_voces"])
    calentar = {**tarea("base", audios[0]["id"])}
    calentar["audio"] = {**calentar["audio"], "recortar": 60}
    correr_aislado(contexto, calentar, None)

    with open(sesion / "resultados.jsonl", "a", encoding="utf-8") as salida:
        for n, (variante_id, audio_id, repeticion) in enumerate(corridas, start=1):
            print(f"[{n}/{len(corridas)}] {variante_id} · {audio_id} · repetición {repeticion}", flush=True)
            medido = correr_aislado(contexto, tarea(variante_id, audio_id), vueltas)
            linea = {
                "variante": variante_id,
                "audio": audio_id,
                "grupo": por_audio[audio_id]["grupo"],
                "repeticion": repeticion,
                "hilos": hilos[variante_id],
                "simulado": equipo["simulado"],
                "ram_pico": medido["ram_pico"],
                "cpu_media": medido["cpu_media"],
                "lentitud": (medido["sonda_p95"] / reposo) if medido["sonda_p95"] and reposo else None,
                "error": medido["valor"] if medido["estado"] == "error" else None,
            }
            if medido["estado"] == "ok":
                valor = medido["valor"]
                duracion = valor["duracion"]
                linea["duracion"] = duracion
                linea["tiempos"] = {k: round(s, 3) for k, s in valor["tiempos"].items()}
                linea["rtf"] = valor["tiempos"]["total"] / duracion
                if audio_id in referencias:
                    m = medir.medir(referencias[audio_id], valor["documento"])
                    linea.update(wer=m["wer"], der=m["der"], voces_referencia=m["voces_referencia"], voces_hipotesis=m["voces_hipotesis"])
                if repeticion == 1:
                    destino = sesion / "hipotesis" / f"{variante_id}__{audio_id}.bitacora"
                    destino.write_text(json.dumps(valor["documento"], ensure_ascii=False), encoding="utf-8")
                print(f"    RTF {linea['rtf']:.3f}" + (f" · WER {linea['wer']:.1%} · DER {linea['der']:.1%}" if "wer" in linea else ""), flush=True)
            else:
                print(f"    error: {linea['error']}", flush=True)
            salida.write(json.dumps(linea, ensure_ascii=False) + "\n")
            salida.flush()
    return sesion


# --- Resumen -------------------------------------------------------------------------


def _mediana(valores):
    valores = [x for x in valores if x is not None]
    return statistics.median(valores) if valores else None


def resumir(lineas, ram_perfil=8 * 2**30):
    """Medianas por variante y audio, deltas frente a `base` y veredicto según §8 de la especificación."""
    grupos = {}
    for linea in lineas:
        if linea.get("error"):
            continue
        grupos.setdefault((linea["variante"], linea["audio"]), []).append(linea)
    celdas = {
        clave: {
            "n": len(filas),
            "rtf": _mediana(f.get("rtf") for f in filas),
            "rtf_min": min(f["rtf"] for f in filas),
            "rtf_max": max(f["rtf"] for f in filas),
            "wer": _mediana(f.get("wer") for f in filas),
            "der": _mediana(f.get("der") for f in filas),
            "ram": _mediana(f.get("ram_pico") for f in filas),
            "lentitud": _mediana(f.get("lentitud") for f in filas),
            "grupo": filas[0].get("grupo"),
        }
        for clave, filas in grupos.items()
    }
    variantes = sorted({v for v, _a in celdas}, key=lambda v: (v != "base", v))
    audios = sorted({a for _v, a in celdas})
    veredictos = {}
    for variante in variantes:
        if variante == "base":
            continue
        mejoras, dwer, dder, rams, lentitudes = [], [], [], [], []
        for audio in audios:
            celda, base = celdas.get((variante, audio)), celdas.get(("base", audio))
            if not celda or not base:
                continue
            mejoras.append(1 - celda["rtf"] / base["rtf"])
            if celda["wer"] is not None and base["wer"] is not None:
                dwer.append(100 * (celda["wer"] - base["wer"]))
            if celda["der"] is not None and base["der"] is not None:
                dder.append(100 * (celda["der"] - base["der"]))
            if celda["ram"] is not None:
                rams.append(celda["ram"])
            if celda["lentitud"] is not None:
                lentitudes.append(celda["lentitud"])
        if not mejoras:
            continue
        resumen = {
            "mejora": statistics.mean(mejoras),
            "dwer_medio": statistics.mean(dwer) if dwer else None,
            "dwer_max": max(dwer) if dwer else None,
            "dder_medio": statistics.mean(dder) if dder else None,
            "ram_max": max(rams) if rams else None,
            "lentitud": max(lentitudes) if lentitudes else None,
        }
        resumen["veredicto"] = veredicto(resumen, ram_perfil)
        veredictos[variante] = resumen
    return {"celdas": celdas, "variantes": variantes, "audios": audios, "veredictos": veredictos}


def veredicto(r, ram_perfil=8 * 2**30):
    if r["mejora"] < MEJORA_MINIMA or (r["dwer_medio"] is not None and r["dwer_medio"] > WER_DESCARTAR):
        return "descartar"
    if r["mejora"] < MEJORA_ACEPTAR:
        return "no concluyente"
    if r["dwer_medio"] is None:
        return "falta referencia"
    calidad_ok = (
        r["dwer_medio"] <= WER_MEDIO_ACEPTAR
        and r["dwer_max"] <= WER_MAXIMO_ACEPTAR
        and (r["dder_medio"] is None or r["dder_medio"] <= DER_MEDIO_ACEPTAR)
    )
    if r["ram_max"] is not None and r["ram_max"] > FRACCION_RAM * ram_perfil:
        return "descartar (RAM)"
    if calidad_ok and (r["lentitud"] is None or r["lentitud"] <= LENTITUD_ACEPTAR):
        return "aceptar"
    return "opción"


def _f(valor, formato):
    return "—" if valor is None else format(valor, formato)


def resumen_markdown(resumen, equipo):
    lineas = [
        "# Resumen del banco de rendimiento",
        "",
        f"Equipo: {equipo.get('procesador')} · {equipo.get('hilos_efectivos')} hilos"
        + (" **(simulado con afinidad)**" if equipo.get("simulado") else "")
        + f" · {_f((equipo.get('memoria') or 0) / 2**30, '.0f')} GB · {', '.join(equipo.get('instrucciones', []))}",
        f"Versiones: {', '.join(f'{k} {v}' for k, v in equipo.get('versiones', {}).items() if v)}",
        "",
        "## Medianas por variante y audio",
        "",
        "| Variante | Audio | n | RTF (mín–máx) | WER | DER | RAM pico | Lentitud |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for variante in resumen["variantes"]:
        for audio in resumen["audios"]:
            c = resumen["celdas"].get((variante, audio))
            if not c:
                continue
            lineas.append(
                f"| {variante} | {audio} | {c['n']} | {c['rtf']:.3f} ({c['rtf_min']:.3f}–{c['rtf_max']:.3f}) | "
                f"{_f(c['wer'], '.1%')} | {_f(c['der'], '.1%')} | {_f(c['ram'] and c['ram'] / 2**30, '.2f')} GB | {_f(c['lentitud'], '.2f')} |"
            )
    lineas += [
        "",
        "## Veredicto frente a `base`",
        "",
        "| Variante | Menos tiempo | Δ WER medio (máx) | Δ DER medio | Lentitud máx | Veredicto |",
        "|---|---|---|---|---|---|",
    ]
    for variante, r in resumen["veredictos"].items():
        lineas.append(
            f"| {variante} | {r['mejora']:.0%} | {_f(r['dwer_medio'], '+.1f')} ({_f(r['dwer_max'], '+.1f')}) pts | "
            f"{_f(r['dder_medio'], '+.1f')} pts | {_f(r['lentitud'], '.2f')} | **{r['veredicto']}** |"
        )
    formatos = {}
    for (variante, audio), c in resumen["celdas"].items():
        if variante == "base" and c["grupo"]:
            formatos.setdefault(c["grupo"], []).append((audio, c))
    formatos = {g: filas for g, filas in formatos.items() if len(filas) > 1}
    if formatos:
        lineas += ["", "## Formatos de entrada (H0, variante `base`)", "", "| Grupo | Audio | RTF | Δ frente al más rápido | WER |", "|---|---|---|---|---|"]
        for grupo, filas in sorted(formatos.items()):
            minimo = min(c["rtf"] for _a, c in filas)
            for audio, c in sorted(filas, key=lambda f: f[1]["rtf"]):
                lineas.append(f"| {grupo} | {audio} | {c['rtf']:.3f} | {c['rtf'] / minimo - 1:+.1%} | {_f(c['wer'], '.1%')} |")
    lineas += [
        "",
        "RTF: segundos de proceso por segundo de audio (menos es mejor). Lentitud: p95 de una tarea fija durante la corrida ÷ en reposo.",
        "Criterios: docs/specs/SPEC-PRUEBAS-RENDIMIENTO.md §8. Este resumen solo tiene números: se puede compartir.",
    ]
    return "\n".join(lineas) + "\n"


def escribir_resumen(sesion, ram_perfil):
    sesion = Path(sesion)
    lineas = [json.loads(l) for l in (sesion / "resultados.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    equipo = json.loads((sesion / "equipo.json").read_text(encoding="utf-8"))
    texto = resumen_markdown(resumir(lineas, ram_perfil), equipo)
    (sesion / "resumen.md").write_text(texto, encoding="utf-8")
    return texto


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, help="JSON con los audios y sus referencias")
    parser.add_argument("--variantes", type=Path, help="JSON con las variantes a medir")
    parser.add_argument("--datos", help="carpeta de datos (los modelos van en <datos>/modelos)")
    parser.add_argument("--salida", default="resultados-banco", help="carpeta donde se crea la sesión")
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--semilla", type=int, default=2026)
    parser.add_argument("--nucleos", type=int, help="limita la corrida a N núcleos lógicos (simulación)")
    parser.add_argument("--ram-perfil", type=float, default=8, help="GB de RAM del equipo modesto para el criterio de RAM")
    parser.add_argument("--sin-sonda", action="store_true", help="no mide la lentitud del equipo")
    parser.add_argument("--en-seco", action="store_true", help="muestra el plan sin cargar modelos")
    parser.add_argument("--resumir", type=Path, help="rehace resumen.md de una sesión guardada")
    args = parser.parse_args(argv)
    ram_perfil = args.ram_perfil * 2**30
    if args.resumir:
        print(escribir_resumen(args.resumir, ram_perfil))
        return
    if not args.corpus or not args.variantes or (not args.datos and not args.en_seco):
        parser.error("se necesitan --corpus, --variantes y --datos (o --resumir)")
    if args.repeticiones < 1 or (args.nucleos is not None and args.nucleos < 1):
        parser.error("--repeticiones y --nucleos deben ser ≥ 1")
    try:
        sesion = correr_sesion(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if sesion:
        print(escribir_resumen(sesion, ram_perfil))
        print(f"Resultados en {sesion}")


if __name__ == "__main__":
    sys.exit(main())
