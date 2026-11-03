import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.motor import trabajos
from backend.motor.trabajos import FRECUENCIA, Cola, Trabajo


class WhisperFalso:
    def transcribe(self, muestras, **_):
        palabras = [SimpleNamespace(start=0.2, end=0.6, word=" Hola"), SimpleNamespace(start=0.7, end=1.4, word=" grupo.")]
        return iter([SimpleNamespace(end=1.5, words=palabras)]), None


def preparar(monkeypatch, tmp_path):
    usados = []
    # Pruebas independientes del hardware: tampoco deben descargar las librerías de CUDA.
    monkeypatch.setattr(trabajos.gpu, "hay_gpu", lambda: False)
    monkeypatch.setattr(trabajos, "decode_audio", lambda *_a, **_k: np.zeros(FRECUENCIA * 2, dtype=np.float32))

    def asegurar(_carpeta, _calidad, distinguir, *_a):
        if distinguir:
            usados.append("modelos")
        return {"whisper": "w", "segmentacion": "seg" if distinguir else None, "huellas": "huellas" if distinguir else None}

    monkeypatch.setattr(trabajos.modelos, "asegurar_modelos", asegurar)
    monkeypatch.setattr(trabajos.modelos, "cargar_whisper", lambda *_a: WhisperFalso())
    monkeypatch.setattr(trabajos, "reconocer_voces", lambda *_a: usados.append("voces") or [(0.0, 1.0, 0), (1.0, 2.0, 1)])
    monkeypatch.setattr(Cola, "_bucle", lambda self: None)
    return Cola(tmp_path), usados


def procesar(cola, tmp_path, **extra):
    peticion = {"ruta_audio": "x.wav", "nombre": "Prueba", "tipo": "encuentro", "idioma": "es", "calidad": "rapida", **extra}
    carpeta = tmp_path / "t"
    carpeta.mkdir()
    trabajo = Trabajo("t", peticion, carpeta)
    cola._procesar(trabajo)
    return json.loads(trabajo.ruta_resultado.read_text(encoding="utf-8"))


def test_sin_distinguir_voces_no_usa_sherpa_y_entrega_una_voz(monkeypatch, tmp_path):
    cola, usados = preparar(monkeypatch, tmp_path)
    resultado = procesar(cola, tmp_path, distinguir_voces=False)
    assert usados == []
    assert len(resultado["voces"]) == 1
    assert resultado["meta"]["distinguir_voces"] is False
    assert "Hola" in resultado["turnos"][0]["texto"]


def test_por_omision_distingue_voces(monkeypatch, tmp_path):
    cola, usados = preparar(monkeypatch, tmp_path)
    resultado = procesar(cola, tmp_path)
    assert usados == ["modelos", "voces"]
    assert resultado["meta"]["distinguir_voces"] is True


@pytest.mark.parametrize("con_descarga", [False, True])
def test_informa_carga_en_memoria_antes_de_cargar_whisper(monkeypatch, tmp_path, con_descarga):
    cola, _ = preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(trabajos.modelos, "bytes_pendientes", lambda *_: 100 if con_descarga else 0)
    asegurar = trabajos.modelos.asegurar_modelos

    def asegurar_con_avance(carpeta, calidad, distinguir, al_descargar, cancelado):
        if con_descarga:
            al_descargar(100, 100)
        return asegurar(carpeta, calidad, distinguir, al_descargar, cancelado)

    monkeypatch.setattr(trabajos.modelos, "asegurar_modelos", asegurar_con_avance)
    carpeta = tmp_path / "t"
    carpeta.mkdir()
    trabajo = Trabajo("t", {"ruta_audio": "x.wav", "calidad": "rapida", "nombre": "Prueba", "tipo": "encuentro", "idioma": "es"}, carpeta)
    avances = []
    avanzar = cola._avanzar

    def registrar(*args):
        avanzar(*args)
        avances.append(trabajo.progreso)

    def cargar(*_):
        assert trabajo.etapa == "descargando_modelos"
        assert trabajo.mensaje == "Cargando el modelo de transcripción en la memoria"
        assert trabajo.progreso >= (10 if con_descarga else 9)
        return WhisperFalso()

    monkeypatch.setattr(cola, "_avanzar", registrar)
    monkeypatch.setattr(trabajos.modelos, "cargar_whisper", cargar)
    cola._procesar(trabajo)
    assert avances == sorted(avances)


@pytest.mark.parametrize("personas", [None, 1, 12])
def test_parametros_de_calidad_y_personas_llegan_a_los_motores(monkeypatch, tmp_path, personas):
    cola, _ = preparar(monkeypatch, tmp_path)
    opciones, numeros = [], []

    class WhisperEspia(WhisperFalso):
        def transcribe(self, muestras, **kwargs):
            opciones.append(kwargs)
            return super().transcribe(muestras, **kwargs)

    monkeypatch.setattr(trabajos.modelos, "cargar_whisper", lambda *_: WhisperEspia())
    monkeypatch.setattr(trabajos, "reconocer_voces", lambda *args: numeros.append(args[-1]) or [(0, 2, 0)])
    resultado = procesar(cola, tmp_path, personas=personas, tema=" Huerta ")
    assert numeros == [personas]
    assert opciones[0]["condition_on_previous_text"] is False
    assert opciones[0]["vad_parameters"] == {"min_silence_duration_ms": 700, "speech_pad_ms": 400}
    assert opciones[0]["vad_filter"] is True
    assert opciones[0]["hotwords"] == "Huerta"
    assert resultado["meta"]["personas"] == personas
    assert "WeSpeaker ResNet34" in resultado["meta"]["modelo_voces"]


@pytest.mark.parametrize("personas", [0, 13, -1, True, 2.0, 1.5, "2", ""])
def test_cola_rechaza_personas_invalidas(monkeypatch, tmp_path, personas):
    cola, _ = preparar(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="personas"):
        cola.crear({"personas": personas})
    assert list(cola.carpeta_trabajos.iterdir()) == []
    with pytest.raises(ValueError, match="personas"):
        Trabajo("t", {"personas": personas}, tmp_path)
