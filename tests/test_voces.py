import numpy as np

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
