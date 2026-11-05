"""Informe local y determinista, común a los exportadores; no resume ni inventa texto."""

import re


def titulo_de_pregunta(texto, maximo=120):
    """Título corto de una sección de entrevista: la última pregunta del turno o, si no hay, su primera oración."""
    texto = texto.strip()
    if not texto:
        return "Pregunta"
    oraciones = re.split(r"(?<=[.!?…])\s+", texto)
    preguntas = [oracion for oracion in oraciones if oracion.endswith("?")]
    titulo = preguntas[-1] if preguntas else oraciones[0]
    if preguntas and "¿" in titulo:
        # El primer «¿» de la oración: uno posterior puede ser una pregunta citada («¿por qué no?»).
        titulo = titulo[titulo.find("¿"):]
    # Whisper suele empezar en minúscula un turno cortado: el título va con mayúscula inicial.
    inicial = re.search(r"\w", titulo)
    if inicial:
        titulo = titulo[:inicial.start()] + titulo[inicial.start()].upper() + titulo[inicial.start() + 1:]
    if len(titulo) > maximo:
        corte = titulo.rfind(" ", 0, maximo - 1)
        titulo = titulo[:corte if corte > 0 else maximo - 1].rstrip() + "…"
    return titulo


def construir_informe(transcripcion):
    meta = transcripcion["meta"]
    turnos = sorted(transcripcion["turnos"], key=lambda t: t["inicio"])
    voces = transcripcion["voces"]
    nombres = {v["id"]: v["nombre"] for v in voces}
    tiempos = {v["id"]: sum(max(0, t["fin"] - t["inicio"]) for t in turnos if t["voz"] == v["id"]) for v in voces}
    total = sum(tiempos.values()) or 1
    tipo = meta.get("tipo", "encuentro")
    anexo = [{**t, "nombre": nombres.get(t["voz"], t["voz"])} for t in turnos]
    momentos = sorted((dict(m) for m in meta.get("momentos", [])), key=lambda m: m["inicio"])
    if not momentos:
        # Primer turno de cada bloque de diez minutos que contenga habla.
        bloques = set()
        for t in turnos:
            bloque = int(t["inicio"] // 600)
            if bloque not in bloques:
                bloques.add(bloque)
                palabras = t["texto"].split()
                titulo = " ".join(palabras[:8]) + ("…" if len(palabras) > 8 else "")
                momentos.append({"id": f"auto{bloque}", "inicio": t["inicio"], "titulo": titulo or "Momento", "tipo": "momento"})

    def secciones(marcas):
        if not marcas:
            return [{"titulo": "Conversación", "inicio": 0, "turnos": anexo}]
        resultado = []
        for i, m in enumerate(marcas):
            limite = marcas[i + 1]["inicio"] if i + 1 < len(marcas) else float("inf")
            # La apertura anterior a la primera marca se conserva en la primera sección.
            inicio = m["inicio"] if i else 0
            resultado.append({"titulo": m["titulo"], "inicio": m["inicio"], "turnos": [t for t in anexo if inicio <= t["inicio"] < limite]})
        return resultado

    entrevistadora = meta.get("entrevistadora")
    if tipo == "entrevista":
        activas = [v for v in voces if any(t["voz"] == v["id"] for t in turnos)]
        if entrevistadora not in {v["id"] for v in activas}:
            entrevistadora = min(activas, key=lambda v: tiempos[v["id"]])["id"] if activas else None
        cuerpo = []
        for t in anexo:
            # Un comentario de la entrevistadora sin pregunta («interesante») no abre sección: sigue en la actual.
            if t["voz"] == entrevistadora and (not cuerpo or "?" in t["texto"]):
                if cuerpo and not cuerpo[-1]["respuestas"] and cuerpo[-1]["preguntas"]:
                    cuerpo[-1]["preguntas"].append(t)
                else:
                    cuerpo.append({"titulo": titulo_de_pregunta(t["texto"]), "inicio": t["inicio"], "preguntas": [t], "respuestas": []})
            else:
                if not cuerpo:
                    cuerpo.append({"titulo": "Apertura", "inicio": t["inicio"], "preguntas": [], "respuestas": []})
                cuerpo[-1]["respuestas"].append(t)
    elif tipo == "grupo_focal":
        preguntas = [dict(m) for m in momentos if m.get("tipo") == "pregunta"]
        guia = meta.get("guia", [])
        for i, m in enumerate(preguntas):
            m["titulo"] = m.get("titulo") or (guia[i] if i < len(guia) else f"Pregunta {i + 1}")
        cuerpo = secciones(preguntas)
    else:
        cuerpo = secciones(momentos)
    return {
        "portada": {k: meta.get(k, "" if k != "duracion" else 0) for k in ("nombre", "tema", "fecha", "duracion")} | {"tipo": tipo},
        "participantes": [{"id": v["id"], "nombre": v["nombre"], "minutos": tiempos[v["id"]] / 60, "porcentaje": 100 * tiempos[v["id"]] / total, "intervenciones": sum(t["voz"] == v["id"] for t in turnos)} for v in voces],
        "momentos": momentos,
        "citas": _citas(transcripcion, anexo, nombres),
        "cuerpo": cuerpo,
        "entrevistadora": entrevistadora,
        "transcripcion": anexo,
    }


def _citas(transcripcion, anexo, nombres):
    """Turnos con estrella y fragmentos citados (`citas` del documento), en orden de aparición."""
    voz_actual = {t["id"]: t["voz"] for t in anexo}
    fragmentos = [
        {**c, "voz": voz_actual.get(c.get("turno"), c.get("voz")), "nombre": nombres.get(voz_actual.get(c.get("turno"), c.get("voz")), "")}
        for c in transcripcion.get("citas", [])
    ]
    return sorted([t for t in anexo if t.get("cita", False)] + fragmentos, key=lambda c: c["inicio"])
