# -*- mode: python ; coding: utf-8 -*-
# Motor de Dialegu Bitácora como carpeta ejecutable (onedir).
# Compilar desde la raíz del repo: pyinstaller Dialegu_Engine.spec --distpath backend-dist
# Los modelos NO se empaquetan: se descargan en el primer uso a %LOCALAPPDATA%\Dialegu Bitacora\modelos.
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

datas, binaries, hiddenimports = [], [], []
datas += collect_data_files('docx')
for paquete in ('faster_whisper', 'ctranslate2', 'sherpa_onnx', 'av', 'fpdf'):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules('uvicorn') + collect_submodules(
    'backend', filter=lambda nombre: not nombre.startswith('backend.herramientas')
)

a = Analysis(
    ['engine_entry.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'matplotlib', 'tkinter', 'backend.herramientas'],
    noarchive=False,
    optimize=0,
)

# Runtime de Visual C++: PyInstaller tomaba un msvcp140.dll de 2017 (14.16) y ctranslate2, compilado con
# VS 2022, se caía con un acceso inválido a memoria (0xc0000005) al crear el modelo de Whisper.
# Se empaqueta el runtime del sistema de compilación, que debe ser 14.40 o superior (redistribuible).
import os
RUNTIME_VC = ('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll')
sistema = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32')
a.binaries = [b for b in a.binaries if os.path.basename(b[0]).lower() not in RUNTIME_VC]
a.binaries += [(nombre, os.path.join(sistema, nombre), 'BINARY') for nombre in RUNTIME_VC if os.path.exists(os.path.join(sistema, nombre))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Dialegu_Engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Dialegu_Engine',
)
