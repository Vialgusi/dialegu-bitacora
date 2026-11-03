"""Compara dos proyectos JSON .bitacora sin cargar audio ni modelos.

WER usa distancia de Levenshtein sobre palabras: minúsculas, Unicode NFC,
tildes conservadas y puntuación sustituida por espacios.

DER aproximado = (omisiones + falsas alarmas + confusiones) / tiempo de habla
de referencia. Integra los intervalos exactamente, sin collar de tolerancia.
En solapes cuenta tiempo por hablante; turnos superpuestos de la misma voz
cuentan una sola vez. No usa nombres: mapea los identificadores uno a uno
maximizando su coincidencia temporal con el algoritmo húngaro de scipy.
Si scipy no está instalado, elige vorazmente el par con mayor coincidencia
restante; esta alternativa es determinista pero no garantiza el óptimo global.
"""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import unicodedata


def leer_proyecto(ruta):
    documento = json.loads(Path(ruta).read_text(encoding="utf-8-sig"))
    if not isinstance(documento, dict) or documento.get("version") != 1 or not isinstance(documento.get("turnos"), list):
        raise ValueError(f"{ruta}: no es un proyecto .bitacora versión 1")
    for turno in documento["turnos"]:
        if not isinstance(turno.get("texto"), str) or not isinstance(turno.get("voz"), str):
            raise ValueError(f"{ruta}: turno sin texto o identificador de voz válido")
        a, b = turno.get("inicio"), turno.get("fin")
        if any(type(t) not in (int, float) or not math.isfinite(t) for t in (a, b)) or not 0 <= a <= b:
            raise ValueError(f"{ruta}: tiempos de turno inválidos")
    return documento


def normalizar(texto):
    texto = unicodedata.normalize("NFC", texto.lower())
    return "".join(" " if unicodedata.category(c).startswith("P") else c for c in texto).split()


def _palabras(documento):
    return normalizar(" ".join(t["texto"] for t in sorted(documento["turnos"], key=lambda t: t["inicio"])))


def wer(referencia, hipotesis):
    ref, hip = _palabras(referencia), _palabras(hipotesis)
    anterior = list(range(len(hip) + 1))
    for i, palabra in enumerate(ref, 1):
        fila = [i]
        for j, otra in enumerate(hip, 1):
            fila.append(min(fila[-1] + 1, anterior[j] + 1, anterior[j - 1] + (palabra != otra)))
        anterior = fila
    return anterior[-1] / len(ref) if ref else (math.inf if hip else 0.0)


def _intervalos(referencia, hipotesis):
    eventos = defaultdict(list)
    for lado, documento in enumerate((referencia, hipotesis)):
        for t in documento["turnos"]:
            eventos[t["inicio"]].append((lado, t["voz"], 1))
            eventos[t["fin"]].append((lado, t["voz"], -1))
    activos = [Counter(), Counter()]
    anterior = None
    for tiempo, cambios in sorted(eventos.items()):
        if anterior is not None and tiempo > anterior:
            yield tiempo - anterior, *(set(v for v, n in lado.items() if n > 0) for lado in activos)
        for lado, voz, cambio in cambios:
            activos[lado][voz] += cambio
        anterior = tiempo


def _mapear(pesos):
    try:
        from scipy.optimize import linear_sum_assignment
    except ImportError:
        # Mayor solape primero; los ids resuelven empates de forma reproducible.
        mapa, usadas = {}, set()
        for (r, h), peso in sorted(pesos.items(), key=lambda par: (-par[1], par[0])):
            if peso > 0 and r not in usadas and h not in mapa:
                mapa[h] = r
                usadas.add(r)
        return mapa, "voraz (sin scipy; puede no ser óptimo)"
    refs = sorted({r for r, _ in pesos})
    hips = sorted({h for _, h in pesos})
    if not refs or not hips:
        return {}, "húngaro (scipy)"
    matriz = [[-pesos.get((r, h), 0.0) for h in hips] for r in refs]
    filas, columnas = linear_sum_assignment(matriz)
    return {hips[h]: refs[r] for r, h in zip(filas, columnas)}, "húngaro (scipy)"


def der_aproximado(referencia, hipotesis):
    pesos = defaultdict(float)
    for duracion, refs, hips in _intervalos(referencia, hipotesis):
        for r in refs:
            for h in hips:
                pesos[r, h] += duracion
    mapa, metodo = _mapear(pesos)
    total = errores = 0.0
    for duracion, refs, hips in _intervalos(referencia, hipotesis):
        aciertos = sum(mapa.get(h) in refs for h in hips)
        total += duracion * len(refs)
        errores += duracion * (max(len(refs), len(hips)) - aciertos)
    return (errores / total if total else (math.inf if errores else 0.0)), metodo


def medir(referencia, hipotesis):
    der, metodo = der_aproximado(referencia, hipotesis)
    return {
        "wer": wer(referencia, hipotesis),
        "der": der,
        "mapeo": metodo,
        "voces_referencia": len(referencia.get("voces", [])),
        "voces_hipotesis": len(hipotesis.get("voces", [])),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--referencia", required=True, type=Path)
    parser.add_argument("--hipotesis", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        resultado = medir(leer_proyecto(args.referencia), leer_proyecto(args.hipotesis))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"WER: {resultado['wer']:.2%}")
    print(f"DER aproximado: {resultado['der']:.2%} · mapeo {resultado['mapeo']}")
    print(f"Voces: referencia={resultado['voces_referencia']}, hipótesis={resultado['voces_hipotesis']}")


if __name__ == "__main__":
    main()
