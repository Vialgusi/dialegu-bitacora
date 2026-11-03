import builtins
from copy import deepcopy
import json
import sys
from types import SimpleNamespace

import pytest

from backend.herramientas.medir import _mapear, leer_proyecto, main, medir, normalizar
from backend.motor.modelos import HUELLAS


def documento():
    return {
        "version": 1,
        "voces": [{"id": "a"}, {"id": "b"}],
        "turnos": [
            {"voz": "a", "inicio": 0, "fin": 2, "texto": "¡Hola, qué tal!"},
            {"voz": "b", "inicio": 2, "fin": 4, "texto": "Muy bien."},
        ],
    }


def test_modelo_multilingue_fijado():
    assert HUELLAS["repo"] == "csukuangfj/speaker-embedding-models"
    assert HUELLAS["revision"] == "0743f301363dec56491a490f6d6cbc9d67f9a3bf"
    assert HUELLAS["archivos"] == [("wespeaker_en_voxceleb_resnet34_LM.onnx", 26530550, "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012")]
    assert "renombrar" not in HUELLAS


def test_identicos_y_renombrados():
    ref, hip = documento(), documento()
    assert medir(ref, hip)["wer"] == medir(ref, hip)["der"] == 0
    hip["turnos"][0]["voz"], hip["turnos"][1]["voz"] = "y", "x"
    hip["voces"] = [{"id": "x"}, {"id": "y"}]
    assert medir(ref, hip)["der"] == 0


def test_error_sintetico_conocido():
    ref, hip = documento(), documento()
    hip["turnos"][0]["texto"] = "Hola qué mal"
    hip["turnos"][0]["fin"] = 1
    hip["turnos"].insert(1, {"voz": "b", "inicio": 1, "fin": 2, "texto": ""})
    resultado = medir(ref, hip)
    assert resultado["wer"] == pytest.approx(1 / 5)
    assert resultado["der"] == pytest.approx(1 / 4)
    assert resultado["voces_referencia"] == resultado["voces_hipotesis"] == 2


def test_normalizacion_conserva_tildes():
    assert normalizar("¿SÍ? AÑO—café; CAFE\u0301.") == ["sí", "año", "café", "café"]
    hip = documento()
    hip["turnos"][0]["texto"] = "Hola que tal"
    assert medir(documento(), hip)["wer"] == pytest.approx(1 / 5)


def test_inserciones_omisiones_y_falsas_alarmas():
    ref, hip = documento(), documento()
    hip["turnos"][1]["texto"] = ""
    assert medir(ref, hip)["wer"] == pytest.approx(2 / 5)
    hip = documento()
    hip["turnos"][1]["texto"] += " gracias"
    assert medir(ref, hip)["wer"] == pytest.approx(1 / 5)
    hip = documento()
    hip["turnos"][0]["inicio"] = 1  # un segundo omitido
    hip["turnos"][1]["fin"] = 5  # un segundo de falsa alarma
    assert medir(ref, hip)["der"] == pytest.approx(2 / 4)


def test_solapes_y_documentos_vacios():
    vacio = {"version": 1, "turnos": [], "voces": []}
    assert medir(vacio, vacio)["wer"] == medir(vacio, vacio)["der"] == 0
    assert medir(documento(), vacio)["wer"] == medir(documento(), vacio)["der"] == 1
    ref = documento()
    ref["turnos"][1]["inicio"] = 1
    assert medir(ref, deepcopy(ref))["der"] == 0


def test_fallback_voraz_documentado(monkeypatch):
    importar = builtins.__import__

    def sin_scipy(nombre, *args, **kwargs):
        if nombre.startswith("scipy"):
            raise ImportError("sin scipy")
        return importar(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sin_scipy)
    mapa, metodo = _mapear({("a", "x"): 4, ("b", "y"): 3, ("a", "y"): 2})
    assert mapa == {"x": "a", "y": "b"}
    assert "voraz" in metodo


def test_usa_asignacion_hungara_si_hay_scipy(monkeypatch):
    def asignar(matriz):
        assert matriz == [[-4, -3], [-3, 0.0]]
        return [0, 1], [1, 0]

    monkeypatch.setitem(sys.modules, "scipy.optimize", SimpleNamespace(linear_sum_assignment=asignar))
    mapa, metodo = _mapear({("a", "x"): 4, ("a", "y"): 3, ("b", "x"): 3})
    assert mapa == {"y": "a", "x": "b"}
    assert "húngaro" in metodo


def test_cli_lee_formato_guardado_por_electron(tmp_path, capsys):
    ruta = tmp_path / "ref.bitacora"
    ruta.write_text(json.dumps(documento(), ensure_ascii=False, indent=1), encoding="utf-8")
    assert leer_proyecto(ruta) == documento()
    main(["--referencia", str(ruta), "--hipotesis", str(ruta)])
    salida = capsys.readouterr().out
    assert "WER: 0.00%" in salida
    assert "DER aproximado: 0.00%" in salida
    assert "referencia=2, hipótesis=2" in salida


def test_cli_rechaza_archivo_invalido(tmp_path):
    ruta = tmp_path / "mal.bitacora"
    ruta.write_text('{"version": 7}', encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["--referencia", str(ruta), "--hipotesis", str(ruta)])
    assert error.value.code == 2
