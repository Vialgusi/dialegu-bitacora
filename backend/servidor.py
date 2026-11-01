"""Servidor HTTP del motor. Contrato en docs/CONTRATO-MOTOR.md.

Uso: python -m backend.servidor --puerto 50123 --token <hex> --datos <carpeta>
"""

import argparse
import hmac
import os
import re
import sys
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from backend.motor import VERSION, equipo, gpu
from backend.motor.exportar import FORMATOS
from backend.motor.trabajos import Cola


class Momento(BaseModel):
    id: str = Field(min_length=1)
    inicio: float = Field(ge=0, allow_inf_nan=False)
    titulo: str
    tipo: Literal["momento", "pregunta"] = "momento"


class NuevoTrabajo(BaseModel):
    ruta_audio: str
    nombre: str = Field(min_length=1, max_length=200)
    tema: str = Field(default="", max_length=500)
    tipo: Literal["encuentro", "grupo_focal", "entrevista"] = "encuentro"
    guia: list[str] = Field(default_factory=list)
    momentos: list[Momento] = Field(default_factory=list)
    idioma: str = Field(default="es", pattern=r"^(auto|[a-z]{2})$")
    calidad: Literal["rapida", "alta", "maximo"] = "rapida"
    distinguir_voces: bool = True
    usar_gpu: bool = True


class PeticionEstimacion(BaseModel):
    ruta_audio: str
    calidad: Literal["rapida", "alta", "maximo"] = "rapida"
    distinguir_voces: bool = True
    usar_gpu: bool = True


class PeticionExportar(BaseModel):
    transcripcion: dict
    formato: Literal["md", "pdf", "srt", "txt", "informe-md", "informe-pdf", "informe-docx"]


def crear_app(token, carpeta_datos):
    app = FastAPI(title="Dialegu Bitácora · motor", version=VERSION, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null", "http://localhost:5175"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-Token", "Content-Type", "Range"],
        expose_headers=["Content-Disposition"],
    )
    cola = Cola(carpeta_datos)

    def autorizar(request: Request):
        recibido = request.headers.get("X-Token") or ""
        if not hmac.compare_digest(recibido, token):
            raise HTTPException(status_code=401, detail="Token inválido")

    def autorizar_audio(request: Request):
        recibido = request.headers.get("X-Token") or request.query_params.get("token") or ""
        if not hmac.compare_digest(recibido, token):
            raise HTTPException(status_code=401, detail="Token inválido")

    def trabajo_o_404(id_):
        trabajo = cola.obtener(id_)
        if trabajo is None:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado")
        return trabajo

    @app.get("/api/salud", dependencies=[Depends(autorizar)])
    def salud():
        return {"estado": "listo", "version": VERSION, "gpu": gpu.hay_gpu()}

    @app.get("/api/equipo", dependencies=[Depends(autorizar)])
    def describir_equipo():
        # Minutos de proceso por hora de audio para cada combinación, sin contar descargas (se informan aparte).
        por_hora = {
            equipo.clave(calidad, "cuda" if usar else "cpu", voces): equipo.estimar(
                cola.datos, cola.carpeta_modelos, 3600, calidad, usar, voces
            )["segundos_proceso"]
            for calidad in ("rapida", "alta", "maximo")
            for usar in ((False, True) if gpu.hay_gpu() else (False,))
            for voces in (True, False)
        }
        return {**equipo.describir(cola.carpeta_modelos), "por_hora": por_hora}

    @app.post("/api/estimacion", dependencies=[Depends(autorizar)])
    def estimar(peticion: PeticionEstimacion):
        ruta = Path(peticion.ruta_audio)
        if not ruta.is_absolute() or not ruta.is_file():
            raise HTTPException(status_code=400, detail="No se encontró el archivo de audio.")
        duracion = equipo.duracion_audio(ruta)
        if duracion is None:
            raise HTTPException(status_code=422, detail="No se pudo leer la duración del audio.")
        return equipo.estimar(
            cola.datos, cola.carpeta_modelos, duracion, peticion.calidad, peticion.usar_gpu, peticion.distinguir_voces
        )

    @app.post("/api/trabajos", status_code=201, dependencies=[Depends(autorizar)])
    def crear_trabajo(peticion: NuevoTrabajo):
        ruta = Path(peticion.ruta_audio)
        if not ruta.is_absolute() or not ruta.is_file():
            raise HTTPException(status_code=400, detail="No se encontró el archivo de audio.")
        trabajo = cola.crear(peticion.model_dump())
        return {"id": trabajo.id}

    @app.get("/api/trabajos/{id_}", dependencies=[Depends(autorizar)])
    def estado_trabajo(id_: str):
        return trabajo_o_404(id_).vista()

    @app.delete("/api/trabajos/{id_}", status_code=204, dependencies=[Depends(autorizar)])
    def cancelar_trabajo(id_: str):
        cola.cancelar(trabajo_o_404(id_))
        return Response(status_code=204)

    @app.get("/api/trabajos/{id_}/resultado", dependencies=[Depends(autorizar)])
    def resultado(id_: str):
        trabajo = trabajo_o_404(id_)
        if trabajo.estado != "listo":
            raise HTTPException(status_code=409, detail="El trabajo aún no termina.")
        return Response(trabajo.ruta_resultado.read_bytes(), media_type="application/json")

    @app.get("/api/trabajos/{id_}/audio", dependencies=[Depends(autorizar_audio)])
    def audio(id_: str):
        trabajo = trabajo_o_404(id_)
        if not trabajo.ruta_audio.exists():
            raise HTTPException(status_code=409, detail="El audio aún no está listo.")
        return FileResponse(trabajo.ruta_audio, media_type="audio/wav")

    @app.post("/api/exportar", dependencies=[Depends(autorizar)])
    def exportar(peticion: PeticionExportar):
        generar, tipo = FORMATOS[peticion.formato]
        try:
            datos = generar(peticion.transcripcion)
        except (KeyError, TypeError) as error:
            raise HTTPException(status_code=422, detail=f"Transcripción incompleta: falta {error}") from error
        base = re.sub(r"[^\w\- ]+", "", peticion.transcripcion.get("meta", {}).get("nombre", "")).strip() or "bitacora"
        extension = peticion.formato.removeprefix("informe-")
        nombre = f"{base}.{extension}"
        return Response(
            datos,
            media_type=tipo,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}"},
        )

    return app


def carpeta_por_defecto():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "Dialegu Bitacora")


def _bajar_prioridad():
    """El procesamiento dura minutos: que no compita con lo que la persona está haciendo en su equipo.
    Los procesos hijos (reconocimiento de voces) heredan la prioridad."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Sin estos tipos, ctypes trunca el handle a 32 bits y la llamada falla (error 6) en Windows de 64 bits.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        if not kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS):
            print(f"No se pudo bajar la prioridad (error {ctypes.get_last_error()})", flush=True)
    else:
        os.nice(5)


def _vigilar_padre(pid):
    """Cierra el motor si la app de escritorio muere sin avisar (cierre forzado, caída), para no dejarlo huérfano."""
    import threading

    def esperar():
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            SYNCHRONIZE, INFINITE = 0x00100000, 0xFFFFFFFF
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                kernel32.WaitForSingleObject(handle, INFINITE)
        else:
            import time

            while os.getppid() == pid:
                time.sleep(2)
        print("La app de escritorio se cerró; el motor termina.", flush=True)
        os._exit(0)

    threading.Thread(target=esperar, daemon=True, name="vigilar-padre").start()


def main(argv=None):
    import uvicorn

    parser = argparse.ArgumentParser(description="Motor de Dialegu Bitácora")
    parser.add_argument("--puerto", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--datos", default=carpeta_por_defecto())
    parser.add_argument("--padre", type=int, help="pid de la app de escritorio; el motor termina cuando ella termina")
    args = parser.parse_args(argv)
    if len(args.token) < 32:
        parser.error("el token debe tener al menos 32 caracteres")

    _bajar_prioridad()
    if args.padre:
        _vigilar_padre(args.padre)
    app = crear_app(args.token, args.datos)
    print(f"Dialegu Bitácora · motor {VERSION} en 127.0.0.1:{args.puerto}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.puerto, log_level="warning")


if __name__ == "__main__":
    main()
