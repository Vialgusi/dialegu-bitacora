import pytest
from fastapi.testclient import TestClient

from backend.motor.exportar import a_markdown, a_srt
from backend.servidor import crear_app

TOKEN = "a" * 64

TRANSCRIPCION = {
    "version": 1,
    "meta": {"nombre": "Grupo focal «Huerta» — prueba", "tema": "Agua", "tipo": "grupo_focal", "fecha": "2026-10-31T10:00:00", "duracion": 75.0},
    "voces": [{"id": "v1", "nombre": "Ana", "segundos": 30.0}, {"id": "v2", "nombre": "Raúl", "segundos": 10.0}],
    "turnos": [
        {"id": "t1", "voz": "v1", "inicio": 0.0, "fin": 30.0, "texto": "¿Qué ha significado la huerta?", "palabras": []},
        {
            "id": "t2",
            "voz": "v2",
            "inicio": 65.0,
            "fin": 75.0,
            "texto": "Un espacio de encuentro.",
            "palabras": [{"inicio": 65.0, "fin": 66.0, "texto": "Un"}, {"inicio": 72.0, "fin": 75.0, "texto": "encuentro."}],
        },
    ],
}


@pytest.fixture
def cliente(tmp_path):
    return TestClient(crear_app(TOKEN, tmp_path))


def con_token():
    return {"X-Token": TOKEN}


def test_sin_token_responde_401(cliente):
    assert cliente.get("/api/salud").status_code == 401
    assert cliente.get("/api/salud", headers={"X-Token": "b" * 64}).status_code == 401


def test_salud(cliente):
    respuesta = cliente.get("/api/salud", headers=con_token())
    assert respuesta.json()["estado"] == "listo"
    assert isinstance(respuesta.json()["gpu"], bool)


def test_origen_web_ajeno_no_recibe_permiso_cors(cliente):
    respuesta = cliente.options(
        "/api/salud",
        headers={"Origin": "https://sitio-cualquiera.com", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in respuesta.headers


def test_trabajo_con_archivo_inexistente_responde_400(cliente, tmp_path):
    respuesta = cliente.post("/api/trabajos", headers=con_token(), json={"ruta_audio": str(tmp_path / "no.wav"), "nombre": "x"})
    assert respuesta.status_code == 400
    assert "No se encontró" in respuesta.json()["detail"]


def test_trabajo_desconocido_responde_404(cliente):
    assert cliente.get("/api/trabajos/nada", headers=con_token()).status_code == 404


def test_audio_acepta_token_por_parametro_pero_exige_token(cliente):
    assert cliente.get("/api/trabajos/nada/audio").status_code == 401
    assert cliente.get(f"/api/trabajos/nada/audio?token={TOKEN}").status_code == 404


@pytest.mark.parametrize("formato", ["md", "txt", "srt", "pdf", "informe-md", "informe-pdf", "informe-docx"])
def test_exportar_todos_los_formatos(cliente, formato):
    respuesta = cliente.post("/api/exportar", headers=con_token(), json={"transcripcion": TRANSCRIPCION, "formato": formato})
    assert respuesta.status_code == 200
    assert len(respuesta.content) > 50
    assert "filename*=UTF-8''" in respuesta.headers["content-disposition"]
    assert respuesta.headers["content-disposition"].endswith("." + formato.removeprefix("informe-"))


def test_markdown_incluye_participacion_y_turnos():
    md = a_markdown(TRANSCRIPCION)
    assert "| Ana | 00:30 | 75 % |" in md
    assert "**Raúl** · `01:05`" in md


def test_srt_corta_por_palabras_y_nombra_la_voz():
    srt = a_srt(TRANSCRIPCION)
    assert "00:01:05,000 --> 00:01:12,000\nRaúl: Un" not in srt  # el corte llega hasta el fin de la palabra
    assert "00:01:05,000 --> 00:01:15,000\nRaúl: Un encuentro." in srt
    assert srt.startswith("1\n00:00:00,000 --> 00:00:30,000\nAna: ¿Qué ha significado la huerta?")


def test_metadatos_nuevos_admitidos_sin_procesar_audio():
    from backend.servidor import NuevoTrabajo
    datos = NuevoTrabajo(ruta_audio="sintetico.wav", nombre="Demo", guia=["Pregunta"], momentos=[{"id": "m1", "inicio": 3.125, "titulo": "Pregunta", "tipo": "pregunta"}]).model_dump()
    assert datos["guia"] == ["Pregunta"]
    assert datos["momentos"][0]["inicio"] == 3.125


@pytest.mark.parametrize("inicio", [-1, float("inf"), float("nan")])
def test_rechaza_momentos_con_tiempos_invalidos(inicio):
    from pydantic import ValidationError
    from backend.servidor import Momento
    with pytest.raises(ValidationError):
        Momento(id="m1", inicio=inicio, titulo="Pregunta")


@pytest.mark.parametrize("personas", [0, 13, -1, True, 2.0, 1.5, "2", ""])
def test_api_rechaza_personas_invalidas(cliente, personas):
    respuesta = cliente.post("/api/trabajos", headers=con_token(), json={"ruta_audio": "x.wav", "nombre": "x", "personas": personas})
    assert respuesta.status_code == 422


@pytest.mark.parametrize("personas", [None, 1, 12])
def test_api_pasa_personas_a_la_cola(cliente, tmp_path, monkeypatch, personas):
    from types import SimpleNamespace
    from backend.motor.trabajos import Cola

    recibidas = []
    monkeypatch.setattr(Cola, "crear", lambda self, peticion: recibidas.append(peticion) or SimpleNamespace(id="t"))
    ruta = tmp_path / "x.wav"
    ruta.touch()
    respuesta = cliente.post("/api/trabajos", headers=con_token(), json={"ruta_audio": str(ruta), "nombre": "x", "personas": personas})
    assert respuesta.status_code == 201
    assert recibidas[0]["personas"] == personas
