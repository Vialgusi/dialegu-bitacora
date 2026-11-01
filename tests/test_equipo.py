import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.motor import equipo, gpu
from backend.motor.exportar import FORMATOS, nota_metodologica
from backend.servidor import crear_app

TOKEN = "e" * 64
DEMO = Path("frontend/public/demo/huerta.mp3").resolve()


@pytest.fixture
def cliente(tmp_path):
    return TestClient(crear_app(TOKEN, tmp_path))


def test_equipo_describe_hardware_modelos_y_tiempos_por_hora(cliente):
    datos = cliente.get("/api/equipo", headers={"X-Token": TOKEN}).json()
    assert datos["hilos"] >= 1 and datos["procesador"]
    assert set(datos["modelos"]) == {"rapida", "alta", "maximo"}
    assert datos["modelos"]["maximo"]["nombre"] == "large-v3"
    assert not datos["modelos"]["maximo"]["descargado"]
    assert datos["por_hora"]["alta|cpu|voces"] > datos["por_hora"]["alta|cpu|sin_voces"] or datos["por_hora"]["alta|cpu|voces"] > 0


def test_estimacion_lee_la_duracion_y_suma_descargas(cliente):
    respuesta = cliente.post(
        "/api/estimacion", headers={"X-Token": TOKEN}, json={"ruta_audio": str(DEMO), "calidad": "maximo", "usar_gpu": False}
    ).json()
    assert 50 < respuesta["duracion"] < 60
    assert respuesta["descarga"] > 3e9
    assert respuesta["segundos"] > respuesta["segundos_proceso"]
    assert respuesta["medido"] is False


def test_estimacion_rechaza_archivo_inexistente(cliente, tmp_path):
    r = cliente.post("/api/estimacion", headers={"X-Token": TOKEN}, json={"ruta_audio": str(tmp_path / "no.mp3")})
    assert r.status_code == 400


def test_la_velocidad_medida_reemplaza_la_referencia(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu, "hay_gpu", lambda: False)
    referencia = equipo.estimar(tmp_path, tmp_path, 3600, "alta", False, True)
    equipo.registrar_velocidad(tmp_path, "alta", "cpu", True, 900, 3600)
    medida = equipo.estimar(tmp_path, tmp_path, 3600, "alta", False, True)
    assert medida["medido"] and medida["segundos_proceso"] == 900 != referencia["segundos_proceso"]
    equipo.registrar_velocidad(tmp_path, "alta", "cpu", True, 1800, 3600)
    assert json.loads((tmp_path / "velocidades.json").read_text())["alta|cpu|voces"] == 0.375
    equipo.registrar_velocidad(tmp_path, "alta", "cpu", True, 30, 120)  # audio corto: no cuenta
    assert json.loads((tmp_path / "velocidades.json").read_text())["alta|cpu|voces"] == 0.375


def test_nota_metodologica_y_en_el_informe():
    meta = {"nombre": "x", "tipo": "entrevista", "fecha": "2026-10-31", "duracion": 60, "modelo": "large-v3-turbo", "dispositivo": "gpu",
            "idioma": "es", "distinguir_voces": True, "modelo_voces": "pyannote", "segundos_proceso": 125, "version_app": "0.3.0"}
    nota = nota_metodologica(meta)
    assert "Whisper large-v3-turbo en tarjeta gráfica NVIDIA" in nota and "02:05" in nota and "revisado" in nota
    assert "una sola voz" in nota_metodologica({**meta, "distinguir_voces": False})
    t = {"meta": meta, "voces": [{"id": "v1", "nombre": "Ana", "segundos": 1}], "turnos": [{"id": "t1", "voz": "v1", "inicio": 0, "fin": 1, "texto": "hola", "palabras": []}]}
    assert "Nota metodológica" in FORMATOS["informe-md"][0](t).decode("utf-8")
