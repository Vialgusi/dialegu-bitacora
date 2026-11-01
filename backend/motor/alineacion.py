"""Une las palabras de Whisper con los tramos de voces y arma la Transcripcion del contrato."""

# Una voz con menos habla que esto es casi siempre un error de agrupación (tos, risa, cambio de micrófono).
SEGUNDOS_MINIMOS_POR_VOZ = 10.0
# Silencio a partir del cual una misma voz empieza turno nuevo.
PAUSA_NUEVO_TURNO = 4.0
# Turnos largos se cortan en el siguiente fin de oración, para que sean editables.
SEGUNDOS_TURNO_LARGO = 45.0
# Turnos de este tamaño o menores se consideran ruido de borde y se funden con sus vecinos.
PALABRAS_TURNO_MINIMO = 2
SEGUNDOS_TURNO_MINIMO = 1.0


def _voz_de_palabra(inicio, fin, tramos):
    mejor, solape_max = None, 0.0
    for a, b, voz in tramos:
        if a > fin:
            break
        solape = min(fin, b) - max(inicio, a)
        if solape > solape_max:
            mejor, solape_max = voz, solape
    if mejor is None:
        medio = (inicio + fin) / 2
        mejor = min(tramos, key=lambda t: min(abs(medio - t[0]), abs(medio - t[1])))[2]
    return mejor


def _voces_menores(tramos):
    duracion = {}
    for a, b, voz in tramos:
        duracion[voz] = duracion.get(voz, 0.0) + (b - a)
    menores = {v for v, s in duracion.items() if s < SEGUNDOS_MINIMOS_POR_VOZ}
    return set() if menores == set(duracion) else menores


def asignar_voces(palabras, tramos):
    """palabras: [(inicio, fin, texto)] → [(inicio, fin, texto, voz)]."""
    if not palabras:
        return []
    if not tramos:
        return [(*p, 0) for p in palabras]

    voces = [_voz_de_palabra(p[0], p[1], tramos) for p in palabras]
    menores = _voces_menores(tramos)
    if menores:
        # Cada palabra de una voz menor pasa a la voz válida anterior (o a la siguiente, al comienzo).
        ultima_valida = next((v for v in voces if v not in menores), None)
        for i, voz in enumerate(voces):
            if voz in menores:
                voces[i] = ultima_valida
            else:
                ultima_valida = voz
    return [(*p, v) for p, v in zip(palabras, voces)]


def _cierra_oracion(texto):
    return texto.rstrip().endswith((".", "?", "!", "…"))


def agrupar_turnos(palabras_con_voz):
    turnos = []
    for inicio, fin, texto, voz in palabras_con_voz:
        actual = turnos[-1] if turnos else None
        continua = (
            actual is not None
            and actual["voz"] == voz
            and inicio - actual["fin"] < PAUSA_NUEVO_TURNO
            and not (actual["fin"] - actual["inicio"] > SEGUNDOS_TURNO_LARGO and _cierra_oracion(actual["palabras"][-1][2]))
        )
        if continua:
            actual["palabras"].append((inicio, fin, texto))
            actual["fin"] = fin
        else:
            turnos.append({"voz": voz, "inicio": inicio, "fin": fin, "palabras": [(inicio, fin, texto)]})
    return _suavizar(turnos)


def _es_ruido(turno):
    return len(turno["palabras"]) <= PALABRAS_TURNO_MINIMO and turno["fin"] - turno["inicio"] < SEGUNDOS_TURNO_MINIMO


def _fundir(destino, origen):
    destino["palabras"] = sorted(destino["palabras"] + origen["palabras"])
    destino["inicio"] = min(destino["inicio"], origen["inicio"])
    destino["fin"] = max(destino["fin"], origen["fin"])


def _suavizar(turnos):
    """Funde turnos-ruido (una o dos palabras en menos de un segundo) con el vecino que corresponda."""
    cambiado = True
    while cambiado and len(turnos) > 1:
        cambiado = False
        for i, turno in enumerate(turnos):
            if not _es_ruido(turno):
                continue
            anterior = turnos[i - 1] if i > 0 else None
            siguiente = turnos[i + 1] if i + 1 < len(turnos) else None
            if anterior and siguiente and anterior["voz"] == siguiente["voz"]:
                _fundir(anterior, turno)
                _fundir(anterior, siguiente)
                del turnos[i : i + 2]
            elif anterior:
                _fundir(anterior, turno)
                del turnos[i]
            else:
                _fundir(siguiente, turno)
                del turnos[i]
            cambiado = True
            break
    # Dos turnos vecinos de la misma voz que quedaron juntos tras fundir se unen si la pausa es corta.
    unidos = []
    for turno in turnos:
        if unidos and unidos[-1]["voz"] == turno["voz"] and turno["inicio"] - unidos[-1]["fin"] < PAUSA_NUEVO_TURNO and unidos[-1]["fin"] - unidos[-1]["inicio"] <= SEGUNDOS_TURNO_LARGO:
            _fundir(unidos[-1], turno)
        else:
            unidos.append(turno)
    return unidos


def armar_transcripcion(turnos, meta):
    """Convierte los turnos internos al documento `Transcripcion` del contrato."""
    ids = {}
    for turno in turnos:
        ids.setdefault(turno["voz"], f"v{len(ids) + 1}")

    salida_turnos, segundos = [], {i: 0.0 for i in ids.values()}
    for n, turno in enumerate(turnos, start=1):
        voz = ids[turno["voz"]]
        segundos[voz] += turno["fin"] - turno["inicio"]
        salida_turnos.append(
            {
                "id": f"t{n}",
                "voz": voz,
                "inicio": round(turno["inicio"], 2),
                "fin": round(turno["fin"], 2),
                "texto": "".join(p[2] for p in turno["palabras"]).strip(),
                "palabras": [{"inicio": round(a, 2), "fin": round(b, 2), "texto": t.strip()} for a, b, t in turno["palabras"]],
            }
        )
    voces = [{"id": i, "nombre": f"Voz {n}", "segundos": round(segundos[i], 1)} for n, i in enumerate(ids.values(), start=1)]
    return {"version": 1, "meta": meta, "voces": voces, "turnos": salida_turnos}
