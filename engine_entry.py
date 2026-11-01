"""Punto de entrada de Dialegu_Engine.exe (PyInstaller). Recibe los mismos argumentos que backend.servidor."""

import faulthandler
import multiprocessing
import sys

# Si una librería nativa falla (acceso a memoria), deja la pila de Python en motor.log en vez de cerrarse en silencio.
faulthandler.enable()

# El reconocimiento de voces corre en un proceso aparte; en el ejecutable congelado eso exige freeze_support.
multiprocessing.freeze_support()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from backend.servidor import main

if __name__ == "__main__":
    main()
