"""Cola de trabajos: un trabajo a la vez, con avance, cancelación y resultado en disco."""

import datetime
import json
import queue
import secrets
import shutil
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from faster_whisper.audio import decode_audio

from . import VERSION, equipo, gpu, modelos
from .descargas import ErrorDescarga
from .alineacion import agrupar_turnos, armar_transcripcion, asignar_voces
from .voces import Cancelado, reconocer_voces

FRECUENCIA = 16000
DIAS_CONSERVACION = 7


def validar_personas(personas):
    """También valida entradas directas a la cola, sin pasar por HTTP."""
    if personas is not None and (type(personas) is not int or not 1 <= personas <= 12):
        raise ValueError("personas debe ser un entero entre 1 y 12 o null")
    return personas

ETAPAS_MENSAJE = {
    "preparando": "Preparando el audio",
    "descargando_modelos": "Descargando modelos (solo la primera vez)",
    "voces": "Reconociendo voces",
    "transcripcion": "Transcribiendo",
    "alineacion": "Ordenando por turnos",
    "listo": "Listo",
}


def _minutos(segundos):
    return f"{int(segundos // 60)}"


class Trabajo:
    def __init__(self, id_, peticion, carpeta):
        validar_personas(peticion.get("personas"))
        self.id = id_
        self.peticion = peticion
        self.carpeta = carpeta
        self.estado = "en_cola"
        self.etapa = "preparando"
        self.progreso = 0
        self.mensaje = "En espera"
        self.error = None
        self.cancelar = threading.Event()
        self.inicio = None
        self.estimado = None
        self.dispositivo = None

    def segundos_restantes(self):
        """Con avance suficiente, proyecta el ritmo real; antes, descuenta del estimado inicial."""
        if self.estado != "procesando" or self.inicio is None:
            return None
        transcurrido = time.monotonic() - self.inicio
        if self.progreso >= 20:
            return round(transcurrido * (100 - self.progreso) / self.progreso)
        if self.estimado:
            return max(30, round(self.estimado - transcurrido))
        return None

    def vista(self):
        return {
            "id": self.id,
            "estado": self.estado,
            "etapa": self.etapa,
            "progreso": self.progreso,
            "mensaje": self.mensaje,
            "error": self.error,
            "modelo": modelos.WHISPER[self.peticion.get("calidad", "rapida")]["nombre"],
            "dispositivo": self.dispositivo,
            "segundos_restantes": self.segundos_restantes(),
        }

    @property
    def ruta_resultado(self):
        return self.carpeta / "resultado.json"

    @property
    def ruta_audio(self):
        return self.carpeta / "audio.wav"


class Cola:
    def __init__(self, carpeta_datos):
        self.datos = Path(carpeta_datos)
        self.carpeta_trabajos = self.datos / "trabajos"
        self.carpeta_modelos = self.datos / "modelos"
        self.carpeta_trabajos.mkdir(parents=True, exist_ok=True)
        self.trabajos = {}
        self._candado = threading.Lock()
        self._pendientes = queue.Queue()
        self._limpiar_antiguos()
        threading.Thread(target=self._bucle, daemon=True, name="cola-trabajos").start()

    # --- API pública -------------------------------------------------------------

    def crear(self, peticion):
        validar_personas(peticion.get("personas"))
        id_ = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
        carpeta = self.carpeta_trabajos / id_
        carpeta.mkdir(parents=True)
        trabajo = Trabajo(id_, peticion, carpeta)
        with self._candado:
            self.trabajos[id_] = trabajo
        self._pendientes.put(trabajo)
        return trabajo

    def obtener(self, id_):
        with self._candado:
            return self.trabajos.get(id_)

    def cancelar(self, trabajo):
        trabajo.cancelar.set()
        if trabajo.estado == "en_cola":
            trabajo.estado = "cancelado"
            trabajo.mensaje = "Cancelado"

    # --- Interno -----------------------------------------------------------------

    def _limpiar_antiguos(self):
        limite = time.time() - DIAS_CONSERVACION * 86400
        for carpeta in self.carpeta_trabajos.iterdir():
            if carpeta.is_dir() and carpeta.stat().st_mtime < limite:
                shutil.rmtree(carpeta, ignore_errors=True)

    def _bucle(self):
        while True:
            trabajo = self._pendientes.get()
            if trabajo.cancelar.is_set():
                continue
            trabajo.estado = "procesando"
            try:
                self._procesar(trabajo)
                trabajo.estado, trabajo.etapa, trabajo.progreso = "listo", "listo", 100
                trabajo.mensaje = ETAPAS_MENSAJE["listo"]
            except Cancelado:
                trabajo.estado, trabajo.mensaje = "cancelado", "Cancelado"
            except Exception as error:  # el detalle va al registro; a la persona, un mensaje claro
                print(f"[trabajo {trabajo.id}] error: {error!r}", flush=True)
                trabajo.estado = "error"
                trabajo.error = _mensaje_de_error(error)

    def _preparar_gpu(self, trabajo):
        """Devuelve "cuda" si hay NVIDIA y sus librerías quedaron listas; si no, "cpu". Nunca detiene el trabajo."""
        if not gpu.hay_gpu():
            return "cpu"
        try:
            if not gpu.librerias_listas(self.carpeta_modelos):
                gpu.asegurar_librerias(
                    self.carpeta_modelos,
                    lambda f: self._avanzar(
                        trabajo,
                        "descargando_modelos",
                        8,
                        f"Descargando la aceleración para la tarjeta gráfica ({int(f * 100)} % de 570 MB, solo la primera vez)",
                    ),
                )
            gpu.activar(self.carpeta_modelos)
            if not gpu.preparada(self.carpeta_modelos):
                self._avanzar(
                    trabajo,
                    "descargando_modelos",
                    9,
                    "Preparando la tarjeta gráfica (solo la primera vez; puede tardar unos minutos)",
                )
            return "cuda"
        except Exception as error:
            print(f"[trabajo {trabajo.id}] sin aceleración por GPU: {error!r}", flush=True)
            return "cpu"

    def _avanzar(self, trabajo, etapa, progreso, mensaje=None):
        trabajo.etapa = etapa
        trabajo.progreso = max(trabajo.progreso, min(99, int(progreso)))
        trabajo.mensaje = mensaje or ETAPAS_MENSAJE[etapa]

    def _procesar(self, trabajo):
        p = trabajo.peticion
        personas = validar_personas(p.get("personas"))
        cancelado = trabajo.cancelar.is_set
        trabajo.inicio = time.monotonic()
        distinguir = p.get("distinguir_voces", True)
        usar_gpu = p.get("usar_gpu", True)
        # La primera vez (descargas o preparar la tarjeta) no sirve para medir la velocidad del equipo.
        primera_vez = modelos.bytes_pendientes(self.carpeta_modelos, p["calidad"], distinguir) > 0 or (
            usar_gpu and gpu.hay_gpu() and not (gpu.librerias_listas(self.carpeta_modelos) and gpu.preparada(self.carpeta_modelos))
        )

        # 1. Audio a 16 kHz mono (0–5 %). decode_audio lee audio y video con PyAV, sin ffmpeg externo.
        self._avanzar(trabajo, "preparando", 1)
        muestras = decode_audio(p["ruta_audio"], sampling_rate=FRECUENCIA)
        duracion = len(muestras) / FRECUENCIA
        if duracion < 1:
            raise ValueError("audio_vacio")
        trabajo.estimado = equipo.estimar(self.datos, self.carpeta_modelos, duracion, p["calidad"], usar_gpu, distinguir)["segundos"]
        _guardar_wav(trabajo.ruta_audio, muestras)
        if cancelado():
            raise Cancelado()
        self._avanzar(trabajo, "preparando", 5)

        # 2. Modelos (5–10 %). Sin «Distinguir voces» no se descargan ni se usan los modelos de voces.
        self._avanzar(trabajo, "descargando_modelos", 5)
        uso = {"dispositivo": self._preparar_gpu(trabajo) if usar_gpu else "cpu"}
        calidad_modelo = p["calidad"]
        trabajo.dispositivo = "gpu" if uso["dispositivo"] == "cuda" else "cpu"

        def al_descargar(hechos, total, aviso=None):
            mensaje = f"{ETAPAS_MENSAJE['descargando_modelos']}: {_megas(hechos)} de {_megas(total)} MB ({100 * hechos // total} %)"
            self._avanzar(trabajo, "descargando_modelos", 5 + 5 * hechos / total, f"{mensaje}. {aviso}" if aviso else mensaje)

        rutas = modelos.asegurar_modelos(self.carpeta_modelos, calidad_modelo, distinguir, al_descargar, cancelado)
        segmentacion, huellas = rutas["segmentacion"], rutas["huellas"]
        try:
            whisper = modelos.cargar_whisper(rutas["whisper"], uso["dispositivo"])
            if uso["dispositivo"] == "cuda":
                gpu.marcar_preparada(self.carpeta_modelos)
        except Exception as error:
            if uso["dispositivo"] != "cuda" or not gpu.es_error_de_gpu(error):
                raise
            print(f"[trabajo {trabajo.id}] la GPU no cargó el modelo, sigue en la CPU: {error!r}", flush=True)
            uso["dispositivo"] = "cpu"
            trabajo.dispositivo = "cpu"
            whisper = modelos.cargar_whisper(rutas["whisper"])
        if cancelado():
            raise Cancelado()

        # 3. Voces y transcripción en paralelo (10–95 %): son independientes y ambas liberan el GIL.
        fraccion = {"voces": 0.0 if distinguir else 1.0, "transcripcion": 0.0}

        def informar(parte, valor):
            fraccion[parte] = valor
            atrasada = min(fraccion, key=fraccion.get)
            hecho = (fraccion["voces"] + fraccion["transcripcion"]) / 2
            minuto = fraccion["transcripcion"] * duracion
            mensaje = f"{ETAPAS_MENSAJE[atrasada]}: {_minutos(minuto)} de {_minutos(duracion)} minutos transcritos"
            self._avanzar(trabajo, atrasada, 10 + 85 * hecho, mensaje)

        def transcribir_con(whisper):
            segmentos, _ = whisper.transcribe(
                muestras,
                language=None if p["idioma"] == "auto" else p["idioma"],
                beam_size=5,
                word_timestamps=True,
                vad_filter=True,
                # Evita arrastrar repeticiones o texto inventado a las ventanas siguientes.
                condition_on_previous_text=False,
                # Conserva pausas breves y margen alrededor del habla para no cortar palabras.
                vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 400},
                # El tema y las palabras clave orientan a Whisper en cada ventana: nombres, lugares y jerga.
                hotwords=p.get("tema", "").strip() or None,
            )
            palabras = []
            for segmento in segmentos:
                if cancelado():
                    raise Cancelado()
                palabras.extend((w.start, w.end, w.word) for w in segmento.words or [])
                informar("transcripcion", segmento.end / duracion)
            informar("transcripcion", 1.0)
            return palabras

        def transcribir():
            try:
                return transcribir_con(whisper)
            except Exception as error:
                if uso["dispositivo"] != "cuda" or not gpu.es_error_de_gpu(error):
                    raise
                # Memoria de video agotada o controlador inestable: se repite completa en la CPU.
                print(f"[trabajo {trabajo.id}] falló la GPU, se repite en la CPU: {error!r}", flush=True)
                uso["dispositivo"] = "cpu"
                return transcribir_con(modelos.cargar_whisper(rutas["whisper"]))

        with ThreadPoolExecutor(max_workers=2) as hilos:
            futuro_voces = distinguir and hilos.submit(
                reconocer_voces, trabajo.ruta_audio, segmentacion, huellas, lambda f: informar("voces", f), cancelado, personas
            )
            futuro_texto = hilos.submit(transcribir)
            try:
                palabras = futuro_texto.result()
                tramos = futuro_voces.result() if futuro_voces else []
            except Cancelado:
                trabajo.cancelar.set()
                raise

        # 4. Alineación (95–100 %).
        self._avanzar(trabajo, "alineacion", 96)
        turnos = agrupar_turnos(asignar_voces(palabras, tramos))
        meta = {
            "nombre": p["nombre"],
            "tema": p.get("tema", ""),
            "tipo": p["tipo"],
            "guia": p.get("guia", []),
            "momentos": sorted(p.get("momentos", []), key=lambda m: m["inicio"]),
            "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
            "duracion": round(duracion, 2),
            "idioma": p["idioma"],
            "calidad": p["calidad"],
            "distinguir_voces": distinguir,
            "personas": personas,
            "dispositivo": "gpu" if uso["dispositivo"] == "cuda" else "cpu",
            "modelo": modelos.WHISPER[p["calidad"]]["nombre"],
            "modelo_voces": "pyannote segmentación 3.0 + WeSpeaker ResNet34 VoxCeleb" if distinguir else None,
            "segundos_proceso": round(time.monotonic() - trabajo.inicio),
            "version_app": VERSION,
            "audio_original": p["ruta_audio"],
        }
        transcripcion = armar_transcripcion(turnos, meta)
        trabajo.ruta_resultado.write_text(json.dumps(transcripcion, ensure_ascii=False), encoding="utf-8")
        if not primera_vez:
            equipo.registrar_velocidad(
                self.datos, p["calidad"], uso["dispositivo"], distinguir, time.monotonic() - trabajo.inicio, duracion
            )


def _megas(octetos):
    return f"{octetos / 1e6:,.0f}".replace(",", " ")


def _guardar_wav(ruta, muestras):
    enteros = (np.clip(muestras, -1, 1) * 32767).astype("<i2")
    with wave.open(str(ruta), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(FRECUENCIA)
        wav.writeframes(enteros.tobytes())


def _mensaje_de_error(error):
    texto = str(error)
    if texto == "audio_vacio":
        return "El archivo no tiene audio o dura menos de un segundo."
    if isinstance(error, (FileNotFoundError, PermissionError)):
        return "No se pudo leer el archivo de audio. Verifique que exista y no esté abierto en otro programa."
    if isinstance(error, ErrorDescarga):
        return (
            "No se pudo descargar el modelo: la conexión se cortó varias veces. "
            "Revise la conexión a internet y pulse «Reintentar»; la descarga continúa donde quedó."
        )
    if "urlopen" in texto or "HTTP" in texto or "connection" in texto.lower():
        return "No se pudieron descargar los modelos. La primera vez se necesita conexión a internet."
    return f"No se pudo procesar el audio ({type(error).__name__}). Pruebe con otro archivo o con calidad «Rápida»."
