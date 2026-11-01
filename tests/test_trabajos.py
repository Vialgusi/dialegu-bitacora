import json
from types import SimpleNamespace

import numpy as np

from backend.motor import trabajos
from backend.motor.trabajos import FRECUENCIA, Cola, Trabajo


class WhisperFalso:
    def transcribe(self, muestras, **_):
        palabras = [SimpleNamespace(start=0.2, end=0.6, word=" Hola"), SimpleNamespace(start=0.7, end=1.4, word=" grupo.")]
        return iter([SimpleNamespace(end=1.5, words=palabras)]), None


def preparar(monkeypatch, tmp_path):
    usados = []
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
