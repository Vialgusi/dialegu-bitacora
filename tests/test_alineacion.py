from backend.motor.alineacion import agrupar_turnos, armar_transcripcion, asignar_voces


def palabras(*items):
    """items: (inicio, fin, texto)."""
    return list(items)


def test_asigna_por_solapamiento_y_corta_turno_dentro_de_un_segmento():
    tramos = [(0.0, 5.0, 7), (5.2, 9.0, 3)]
    ps = palabras((0.5, 1.0, " Hola"), (1.1, 1.6, " todos."), (5.3, 5.8, " Bueno,"), (5.9, 6.4, " gracias"))
    turnos = agrupar_turnos(asignar_voces(ps, tramos))
    assert [t["voz"] for t in turnos] == [7, 3]
    assert "".join(p[2] for p in turnos[1]["palabras"]).strip() == "Bueno, gracias"


def test_palabra_fuera_de_todo_tramo_va_al_mas_cercano():
    tramos = [(0.0, 2.0, 1), (10.0, 12.0, 2)]
    asignadas = asignar_voces(palabras((9.0, 9.4, " ya")), tramos)
    assert asignadas[0][3] == 2


def test_voz_con_poca_habla_se_absorbe_en_la_anterior():
    tramos = [(0.0, 30.0, 1), (30.0, 31.0, 9), (31.0, 60.0, 2)]
    ps = palabras((10.0, 10.5, " uno"), (30.2, 30.6, " eh"), (40.0, 40.5, " dos"))
    voces = [p[3] for p in asignar_voces(ps, tramos)]
    assert voces == [1, 1, 2]


def test_si_todas_las_voces_son_menores_no_se_absorbe_ninguna():
    tramos = [(0.0, 3.0, 1), (3.0, 6.0, 2)]
    voces = [p[3] for p in asignar_voces(palabras((1.0, 1.5, " a"), (4.0, 4.5, " b")), tramos)]
    assert voces == [1, 2]


def test_turno_ruido_entre_dos_de_la_misma_voz_se_funde():
    ps = [
        (0.0, 0.5, " Para", 1),
        (0.6, 1.0, " empezar", 1),
        (1.1, 1.3, " tres", 2),
        (1.4, 1.9, " meses", 1),
        (2.0, 2.5, " largos.", 1),
    ]
    turnos = agrupar_turnos(ps)
    assert len(turnos) == 1
    assert turnos[0]["voz"] == 1
    assert [p[2] for p in turnos[0]["palabras"]] == [" Para", " empezar", " tres", " meses", " largos."]


def test_turno_largo_se_corta_en_fin_de_oracion():
    ps = [(float(i), i + 0.5, " palabra." if i == 50 else " palabra", 1) for i in range(60)]
    turnos = agrupar_turnos(ps)
    assert len(turnos) == 2
    assert turnos[0]["palabras"][-1][2] == " palabra."


def test_pausa_larga_de_la_misma_voz_abre_turno_nuevo():
    ps = [(0.0, 0.5, " Uno", 1), (0.6, 1.0, " dos", 1), (1.1, 1.5, " tres.", 1), (8.0, 8.5, " Otra", 1), (8.6, 9.0, " idea", 1), (9.1, 9.5, " más.", 1)]
    assert len(agrupar_turnos(ps)) == 2


def test_sin_tramos_todo_queda_en_una_voz():
    asignadas = asignar_voces(palabras((0.0, 0.5, " hola"), (0.6, 1.0, " mundo")), [])
    assert {p[3] for p in asignadas} == {0}


def test_armar_transcripcion_numera_voces_por_orden_de_aparicion():
    turnos = agrupar_turnos([(0.0, 2.0, " Hola", 5), (2.1, 3.0, " qué tal", 5), (4.0, 6.0, " Bien", 2), (6.1, 7.0, " gracias", 2)])
    t = armar_transcripcion(turnos, {"nombre": "x"})
    assert [v["id"] for v in t["voces"]] == ["v1", "v2"]
    assert [v["nombre"] for v in t["voces"]] == ["Voz 1", "Voz 2"]
    assert t["turnos"][0] == {
        "id": "t1",
        "voz": "v1",
        "inicio": 0.0,
        "fin": 3.0,
        "texto": "Hola qué tal",
        "palabras": [{"inicio": 0.0, "fin": 2.0, "texto": "Hola"}, {"inicio": 2.1, "fin": 3.0, "texto": "qué tal"}],
    }
    assert t["voces"][1]["segundos"] == 3.0
