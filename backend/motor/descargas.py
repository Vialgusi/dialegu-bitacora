"""Descarga resistente a cortes: reanuda con Range, reintenta con espera, alterna espejos y verifica el archivo.

Cada archivo se baja a «<destino>.parcial» y solo se renombra cuando su tamaño y su SHA-256 coinciden,
así que un corte (o cerrar la app) nunca deja un modelo a medias en su lugar y el siguiente intento
continúa donde quedó.
"""

import hashlib
import http.client
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .voces import Cancelado

BLOQUE = 1 << 16
# Segundos sin recibir datos antes de dar la conexión por caída (urllib lo aplica a cada lectura).
INACTIVIDAD = 30
# Intentos seguidos sin avanzar ni un byte antes de rendirse; cada uno espera más que el anterior.
INTENTOS = 6
ESPERAS = (2, 5, 10, 20, 30)
# Algunas conexiones al CDN quedan vivas pero casi detenidas (decenas de KB/s) mientras otras van a
# decenas de MB/s. Cada VENTANA segundos se mide la velocidad y, si cae por debajo del umbral, se
# reconecta (reanudando con Range): umbral = máx(VELOCIDAD_MINIMA, mejor velocidad vista / 4).
VENTANA = 15
VELOCIDAD_MINIMA = 64_000
AGENTE = "Dialegu-Bitacora/0.3 (+https://dialegu.com)"


class ErrorDescarga(Exception):
    """La descarga no se pudo completar; el archivo parcial se conserva para reanudar."""


class ConexionLenta(OSError):
    """La conexión sigue viva pero se arrastra: conviene abrir otra."""


def descargar(urls, destino, tamano, sha256=None, al_avanzar=lambda hechos, aviso=None: None, cancelado=lambda: False):
    """Baja «destino» probando las URL en orden y reanudando lo que ya haya en disco.

    al_avanzar(hechos, aviso) recibe los bytes ya en disco y, mientras espera para reintentar, un aviso para la persona.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")
    fallos, ultimo_error = 0, None
    medida = {"mejor": 0.0}
    while True:
        if cancelado():
            raise Cancelado()
        hechos = parcial.stat().st_size if parcial.exists() else 0
        if hechos > tamano:  # restos de otra versión del archivo
            parcial.unlink()
            hechos = 0
        if hechos == tamano:
            break
        url = urls[fallos % len(urls)]
        antes, lenta = hechos, False
        try:
            _bajar(url, parcial, hechos, al_avanzar, cancelado, medida)
        except Cancelado:
            raise
        except ConexionLenta as error:
            lenta = True
            print(f"[descarga] {destino.name}: {error}; se reconecta", flush=True)
        except (OSError, http.client.HTTPException) as error:  # timeouts, cortes y respuestas truncadas
            ultimo_error = error
            print(f"[descarga] {destino.name}: {error!r} desde {url.split('?')[0]}", flush=True)
        avanzo = parcial.exists() and parcial.stat().st_size > antes
        fallos = 0 if avanzo else fallos + 1
        if fallos >= INTENTOS:
            raise ErrorDescarga(f"{destino.name}: {ultimo_error!r}")
        if not lenta and (not avanzo or parcial.stat().st_size < tamano):
            _esperar(ESPERAS[min(fallos, len(ESPERAS) - 1)], hechos, al_avanzar, cancelado)

    if sha256 and _sha256(parcial, cancelado) != sha256:
        parcial.unlink()
        raise ErrorDescarga(f"{destino.name}: el archivo descargado no coincide con el original (hash distinto)")
    os.replace(parcial, destino)
    al_avanzar(tamano)


def _bajar(url, parcial, desde, al_avanzar, cancelado, medida):
    cabeceras = {"User-Agent": AGENTE}
    if desde:
        cabeceras["Range"] = f"bytes={desde}-"
    peticion = urllib.request.Request(url, headers=cabeceras)
    try:
        respuesta = urllib.request.urlopen(peticion, timeout=INACTIVIDAD)
    except urllib.error.HTTPError as error:
        if error.code == 416:  # pide más allá del final: lo parcial no sirve
            parcial.unlink(missing_ok=True)
        raise
    with respuesta:
        if desde and respuesta.status != 206:  # el servidor ignoró Range: empezar de nuevo
            desde = 0
        with open(parcial, "ab" if desde else "wb") as salida:
            hechos = desde
            inicio_ventana, hechos_ventana = time.monotonic(), hechos
            while bloque := respuesta.read(BLOQUE):
                if cancelado():
                    raise Cancelado()
                salida.write(bloque)
                hechos += len(bloque)
                al_avanzar(hechos)
                transcurrido = time.monotonic() - inicio_ventana
                if transcurrido >= VENTANA:
                    velocidad = (hechos - hechos_ventana) / transcurrido
                    medida["mejor"] = max(medida["mejor"], velocidad)
                    if velocidad < max(VELOCIDAD_MINIMA, medida["mejor"] / 4):
                        raise ConexionLenta(f"conexión lenta ({velocidad / 1e3:.0f} KB/s)")
                    inicio_ventana, hechos_ventana = time.monotonic(), hechos


def _esperar(segundos, hechos, al_avanzar, cancelado):
    for restantes in range(segundos, 0, -1):
        if cancelado():
            raise Cancelado()
        al_avanzar(hechos, f"Se interrumpió la conexión; reintentando en {restantes} s")
        time.sleep(1)


def _sha256(ruta, cancelado):
    resumen = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        while bloque := archivo.read(1 << 20):
            if cancelado():
                raise Cancelado()
            resumen.update(bloque)
    return resumen.hexdigest()
