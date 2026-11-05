import json
from pathlib import Path

import pytest

from backend.herramientas import banco
from backend.motor import modelos, voces


def test_variantes_parten_de_la_base_y_base_va_primera():
    variantes = banco.normalizar_variantes([{"id": "beam1", "beam_size": 1}])
    assert [v["id"] for v in variantes] == ["base", "beam1"]
    assert {k: variantes[0][k] for k in banco.VARIANTE_BASE} == banco.VARIANTE_BASE
    assert variantes[1]["beam_size"] == 1
    assert variantes[1]["hilos_whisper"] == "produccion"

    explicita = banco.normalizar_variantes([{"id": "x", "paralelo": False}, {"id": "base"}])
    assert [v["id"] for v in explicita] == ["base", "x"]


@pytest.mark.parametrize(
    "entrada",
    [
        [{"id": "a", "beam": 1}],
        [{"id": "a"}, {"id": "a"}],
        [{"id": "a", "hilos_whisper": 0}],
        [{"id": "a", "hilos_voces": "muchos"}],
        [{"id": "a", "calidad": "enorme"}],
        [{"id": "a", "paralelo": "no"}],
        [{"id": "a", "beam_size": True}],
        [{"beam_size": 1}],
        {"id": "a"},
    ],
)
def test_variantes_invalidas(entrada):
    with pytest.raises(ValueError):
        banco.normalizar_variantes(entrada)


def test_los_ejemplos_del_repositorio_son_validos():
    raiz = Path(__file__).resolve().parents[1] / "docs" / "banco"
    variantes = banco.normalizar_variantes(json.loads((raiz / "variantes-fase1.json").read_text(encoding="utf-8")))
    assert variantes[0]["id"] == "base"
    corpus = banco.normalizar_corpus(json.loads((raiz / "corpus-ejemplo.json").read_text(encoding="utf-8")), raiz)
    assert all(Path(a["audio"]).is_absolute() for a in corpus)
    assert any(a["recortar"] == 600 for a in corpus)


def test_corpus_resuelve_rutas_y_valida(tmp_path):
    corpus = banco.normalizar_corpus([{"id": "e", "audio": "a.mp3", "referencia": "r.bitacora"}], tmp_path)
    assert corpus[0]["audio"] == str((tmp_path / "a.mp3").resolve())
    assert corpus[0]["referencia"] == str((tmp_path / "r.bitacora").resolve())
    assert corpus[0]["idioma"] == "es" and corpus[0]["personas"] is None
    for malo in ([], [{"id": "e"}], [{"id": "e", "audio": "a", "personas": 13}], [{"id": "e", "audio": "a", "recortar": 0}], [{"id": "e", "audio": "a", "otra": 1}]):
        with pytest.raises(ValueError):
            banco.normalizar_corpus(malo, tmp_path)


@pytest.mark.parametrize("logicos", [1, 2, 4, 8, 12, 16, 32])
def test_hilos_produccion_coinciden_con_la_app(logicos):
    assert banco.resolver_hilos("produccion", "whisper", logicos, logicos // 2) == modelos.hilos_whisper(logicos)
    assert banco.resolver_hilos("produccion", "voces", logicos, logicos // 2) == voces.hilos_voces(logicos)


def test_hilos_otras_reglas():
    assert banco.resolver_hilos("fisicos-1", "whisper", 8, 4) == 3
    assert banco.resolver_hilos("fisicos-1", "whisper", 2, 1) == 1
    assert banco.resolver_hilos("todos", "voces", 8, 4) == 8
    assert banco.resolver_hilos("mitad", "voces", 4, 2) == 2
    assert banco.resolver_hilos(3, "whisper", 4, 2) == 3
    assert banco.resolver_hilos("produccion", "whisper", 4, 2) == 1  # el caso del portátil de 4 hilos


def test_plan_completo_barajado_y_reproducible():
    variantes = banco.normalizar_variantes([{"id": "a"}, {"id": "b"}])
    audios = [{"id": "x"}, {"id": "y"}]
    uno = banco.plan(variantes, audios, 3, semilla=7)
    assert len(uno) == 3 * 3 * 2 and len(set(uno)) == len(uno)
    assert uno == banco.plan(variantes, audios, 3, semilla=7)
    assert uno != sorted(uno)


def test_compactar_y_devolver_tramos_al_audio_original():
    mapa = banco.compactar([(1.0, 3.0), (5.0, 6.0), (10.0, 12.0)])
    assert mapa == [(1.0, 0.0, 2.0), (5.0, 2.0, 1.0), (10.0, 3.0, 2.0)]
    tramos = [(0.5, 2.5, 0), (2.5, 4.0, 1)]
    assert banco.devolver_tramos(tramos, mapa) == [
        (1.5, 3.0, 0),
        (5.0, 5.5, 0),
        (5.5, 6.0, 1),
        (10.0, 11.0, 1),
    ]
    assert banco.devolver_tramos([(0.0, 5.0, 2)], mapa) == [(1.0, 3.0, 2), (5.0, 6.0, 2), (10.0, 12.0, 2)]
    assert banco.compactar([(2.0, 2.0)]) == []


def test_recortar_documento_por_palabras_y_por_turnos():
    documento = {
        "version": 1,
        "voces": [{"id": "v1"}, {"id": "v2"}, {"id": "v3"}],
        "turnos": [
            {"voz": "v1", "inicio": 0, "fin": 4, "texto": "uno dos", "palabras": [{"inicio": 0, "fin": 1, "texto": "uno"}, {"inicio": 3, "fin": 4, "texto": "dos"}]},
            {"voz": "v2", "inicio": 5, "fin": 6, "texto": "tres"},
            {"voz": "v3", "inicio": 9, "fin": 10, "texto": "cuatro"},
        ],
    }
    recortado = banco.recortar_documento(documento, 3.5)
    assert [t["texto"] for t in recortado["turnos"]] == ["uno"]
    assert recortado["turnos"][0]["fin"] == 1
    assert [v["id"] for v in recortado["voces"]] == ["v1"]
    assert [t["voz"] for t in banco.recortar_documento(documento, 7)["turnos"]] == ["v1", "v2"]


def test_percentil():
    assert banco.percentil([], 0.95) is None
    assert banco.percentil([3, 1, 2], 0.5) == 2
    assert banco.percentil(list(range(101)), 0.95) == 95


def _linea(variante, audio, rtf, wer=0.10, der=0.10, ram=2 * 2**30, lentitud=1.2, grupo=None, error=None):
    return {"variante": variante, "audio": audio, "rtf": rtf, "wer": wer, "der": der, "ram_pico": ram, "lentitud": lentitud, "grupo": grupo, "error": error}


def test_resumen_medianas_y_veredictos():
    lineas = []
    for audio in ("a", "b"):
        lineas += [_linea("base", audio, r) for r in (1.0, 1.1, 0.9)]
        lineas += [_linea("rapida", audio, r, wer=0.105) for r in (0.5, 0.6, 0.4)]
        lineas += [_linea("peor", audio, 0.7, wer=0.16)]
        lineas += [_linea("igual", audio, 0.95)]
        lineas += [_linea("intermedia", audio, 0.6, wer=0.125)]
        lineas += [_linea("pesada", audio, 0.5, ram=6 * 2**30)]
    lineas.append(_linea("rapida", "a", 0.01, error="falló"))
    r = banco.resumir(lineas)
    assert r["variantes"][0] == "base"
    assert r["celdas"][("base", "a")]["rtf"] == 1.0
    assert r["celdas"][("rapida", "a")]["rtf"] == 0.5  # la corrida con error no cuenta
    v = r["veredictos"]
    assert v["rapida"]["mejora"] == pytest.approx(0.5)
    assert v["rapida"]["dwer_medio"] == pytest.approx(0.5)
    assert v["rapida"]["veredicto"] == "aceptar"
    assert v["peor"]["veredicto"] == "descartar"
    assert v["igual"]["veredicto"] == "descartar"
    assert v["intermedia"]["veredicto"] == "opción"
    assert v["pesada"]["veredicto"] == "descartar (RAM)"


def test_veredicto_sin_referencia_y_no_concluyente():
    base = {"dwer_medio": None, "dwer_max": None, "dder_medio": None, "ram_max": None, "lentitud": None}
    assert banco.veredicto({**base, "mejora": 0.30}) == "falta referencia"
    assert banco.veredicto({**base, "mejora": 0.12}) == "no concluyente"
    assert banco.veredicto({**base, "mejora": 0.30, "dwer_medio": 0.0, "dwer_max": 0.0, "lentitud": 3.0}) == "opción"


def test_resumen_markdown_incluye_formatos(tmp_path):
    lineas = [
        _linea("base", "e-wav", 0.50, grupo="entrevista"),
        _linea("base", "e-mp3", 0.51, grupo="entrevista"),
        _linea("beam1", "e-wav", 0.30, grupo="entrevista"),
        _linea("beam1", "e-mp3", 0.31, grupo="entrevista"),
    ]
    sesion = tmp_path / "sesion"
    sesion.mkdir()
    (sesion / "resultados.jsonl").write_text("\n".join(json.dumps(l) for l in lineas), encoding="utf-8")
    (sesion / "equipo.json").write_text(json.dumps({"procesador": "CPU de prueba", "hilos_efectivos": 4, "simulado": True, "memoria": 8 * 2**30, "instrucciones": ["AVX2"], "versiones": {"ctranslate2": "4"}}), encoding="utf-8")
    texto = banco.escribir_resumen(sesion, 8 * 2**30)
    assert (sesion / "resumen.md").read_text(encoding="utf-8") == texto
    assert "simulado" in texto
    assert "| beam1 | 40% |" in texto
    assert "Formatos de entrada (H0" in texto
    assert "| entrevista | e-mp3 | 0.510 | +2.0% |" in texto


def test_en_seco_no_carga_modelos(tmp_path, capsys, monkeypatch):
    (tmp_path / "corpus.json").write_text(json.dumps([{"id": "x", "audio": "x.mp3"}]), encoding="utf-8")
    (tmp_path / "variantes.json").write_text(json.dumps([{"id": "beam1", "beam_size": 1}]), encoding="utf-8")
    monkeypatch.setattr(banco, "ejecutar_corrida", lambda *_a: pytest.fail("no debe correr"))
    banco.main(["--corpus", str(tmp_path / "corpus.json"), "--variantes", str(tmp_path / "variantes.json"), "--en-seco", "--nucleos", "4", "--repeticiones", "2"])
    salida = capsys.readouterr().out
    assert "4 corridas (2 variantes × 1 audios × 2 repeticiones)" in salida
    assert "beam1" in salida


def test_main_pide_argumentos():
    with pytest.raises(SystemExit):
        banco.main(["--corpus", "c.json"])
