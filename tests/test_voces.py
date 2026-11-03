import numpy as np
import pytest
from types import SimpleNamespace

from backend.motor import voces

from backend.motor.voces import fusionar_por_similitud


def unitario(*valores):
    v = np.array(valores, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_fragmentos_de_una_persona_se_fusionan_con_ella():
    huellas = {
        "ana": unitario(1, 0, 0),
        "raul": unitario(0, 1, 0),
        "frag_ana": unitario(0.9, 0.2, 0.1),
        "frag_raul": unitario(0.15, 0.95, 0.1),
    }
    segundos = {"ana": 800, "raul": 1900, "frag_ana": 60, "frag_raul": 20}
    assert fusionar_por_similitud(huellas, segundos) == {"frag_ana": "ana", "frag_raul": "raul"}


def test_personas_distintas_no_se_fusionan():
    huellas = {"a": unitario(1, 0.6, 0), "b": unitario(0.6, 1, 0)}  # similitud ≈ 0,88 si se baja el umbral
    assert fusionar_por_similitud({"a": unitario(1, 0, 0), "b": unitario(0.37, 0.93, 0)}, {"a": 1, "b": 1}) == {}
    assert fusionar_por_similitud(huellas, {"a": 1, "b": 1}, umbral=0.95) == {}


def test_la_voz_con_mas_habla_conserva_su_identificador():
    huellas = {"corta": unitario(1, 0.05, 0), "larga": unitario(1, 0, 0.05)}
    assert fusionar_por_similitud(huellas, {"corta": 10, "larga": 500}) == {"corta": "larga"}


def test_cadena_de_fragmentos_termina_en_un_solo_destino():
    huellas = {"p": unitario(1, 0, 0), "f1": unitario(0.95, 0.3, 0), "f2": unitario(0.9, 0.4, 0.1)}
    destino = fusionar_por_similitud(huellas, {"p": 100, "f1": 10, "f2": 5})
    assert destino == {"f1": "p", "f2": "p"}


@pytest.mark.parametrize("personas", [None, 1, 2, 12])
def test_numero_de_personas_configura_agrupacion_y_controla_fusion(monkeypatch, personas):
    configuraciones, fusiones, avances = [], [], []
    segmentos = [SimpleNamespace(start=0, end=2, speaker=0), SimpleNamespace(start=2, end=4, speaker=1)]

    def config(**kwargs):
        return SimpleNamespace(**kwargs)

    def diarizador(configuracion):
        configuraciones.append(configuracion)
        return SimpleNamespace(process=lambda *_a, **_k: SimpleNamespace(sort_by_start_time=lambda: segmentos))

    def extractor(_config):
        assert personas is None, "Con número fijo no se deben extraer huellas para fusionar"
        return object()

    sherpa = SimpleNamespace(
        OfflineSpeakerDiarizationConfig=config,
        OfflineSpeakerSegmentationModelConfig=config,
        OfflineSpeakerSegmentationPyannoteModelConfig=config,
        SpeakerEmbeddingExtractorConfig=config,
        FastClusteringConfig=config,
        OfflineSpeakerDiarization=diarizador,
        SpeakerEmbeddingExtractor=extractor,
    )
    monkeypatch.setitem(__import__("sys").modules, "sherpa_onnx", sherpa)
    monkeypatch.setattr(voces, "_leer_wav", lambda _: np.zeros(64000))
    monkeypatch.setattr(voces, "_huella_media", lambda *_: unitario(1, 0))
    monkeypatch.setattr(voces, "fusionar_por_similitud", lambda *_: fusiones.append(True) or {1: 0})
    resultado = voces._diarizar("x.wav", "seg", "huellas", avances.append, lambda: False, personas)
    assert configuraciones[0].clustering.num_clusters == (personas if personas is not None else -1)
    assert configuraciones[0].clustering.threshold == 0.5
    assert voces.SIMILITUD_MISMA_PERSONA == 0.55
    assert fusiones == ([True] if personas is None else [])
    assert resultado[-1][2] == (0 if personas is None else 1)
    assert avances[-1] == 1.0


def test_personas_cruza_el_proceso_hijo(monkeypatch):
    import queue
    import threading

    class Proceso:
        def __init__(self, target, args, **_):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

        def is_alive(self):
            return False

    contexto = SimpleNamespace(Queue=queue.Queue, Event=threading.Event, Process=Proceso)
    monkeypatch.setattr(voces.mp, "get_context", lambda _: contexto)

    def diarizar(*args):
        assert args[-1] == 3
        return [(0, 2, 0)]

    monkeypatch.setattr(voces, "_diarizar", diarizar)
    assert voces.reconocer_voces("x.wav", "seg", "huellas", lambda _: None, lambda: False, 3) == [(0, 2, 0)]
