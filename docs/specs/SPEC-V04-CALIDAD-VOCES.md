# SPEC · v0.4 — Calidad de la transcripción y de las voces

Base: `feature/v03-informes` (`e4ea1b4`, PR #3) · rama `feature/v04-calidad-voces`. El PR va encadenado detrás del #3.

## 1. Objetivo
Reducir las dos imprecisiones que la persona vio al probar la v0.3 con sesiones reales:
- personas partidas en varias voces, o dos personas unidas en una;
- palabras mal transcritas, repeticiones y texto inventado en silencios.

## 2. Por qué
Diagnóstico completo en `E:\Desarrollo\Analisis\responsable-producto\grabadora\MEJORA-CALIDAD-2026-10-31.md`. La causa principal de los fallos de voces es que las huellas de voz usan `3dspeaker eres2net zh-cn`, un modelo **entrenado con voces en chino**. Este cambio aplica sus recomendaciones A2, A3, A4 y B1.

## 3. Alcance

### 3.1 Huellas de voz multilingües (B1)
En `backend/motor/modelos.py`, `HUELLAS` pasa a `wespeaker_en_voxceleb_resnet34_LM.onnx`, la huella que usa pyannote 3.1, entrenada con VoxCeleb (miles de hablantes de muchos idiomas):
- repositorio `csukuangfj/speaker-embedding-models`, revisión `0743f301363dec56491a490f6d6cbc9d67f9a3bf` (la misma de hoy);
- tamaño `26530550`;
- SHA-256 `e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012`;
- quita `renombrar`, que ya no aplica.

El descargador propio que ya existe se encarga de la primera descarga. El modelo anterior puede quedar en disco: no lo borres.

Los umbrales cambian con la huella. Vuélvelos configurables con constantes documentadas en `backend/motor/voces.py`:
- `UMBRAL_AGRUPACION` (hoy `0.6` en `FastClusteringConfig`, línea 91);
- `SIMILITUD_MISMA_PERSONA` (hoy `0.6`, línea 28).

Valores iniciales para resnet34: **0.5** para la agrupación y **0.55** para la fusión. Anota en un comentario que son provisionales hasta medir con la referencia de §3.5.

### 3.2 Número de personas (A4)
Agrega un campo opcional **«¿Cuántas personas hablan?»** (número de 1 a 12, vacío = «No sé») en `frontend/src/componentes/Inicio.jsx`, junto a «Tema».
- Viaja en los parámetros del trabajo como `personas` (entero o `null`), validado en `backend/servidor.py` y en `backend/motor/trabajos.py`.
- Si viene, `FastClusteringConfig(num_clusters=personas)`. Si no, el comportamiento automático actual.
- Con número fijo, **no** se aplica la fusión por similitud: ya se conoce cuántas voces hay.

### 3.3 Transcripción sin arrastre (A2)
En `whisper.transcribe` (`backend/motor/trabajos.py`, ~L240) agrega `condition_on_previous_text=False`. Esto evita que una alucinación se repita en las ventanas siguientes de un audio largo.

### 3.4 Cortes de palabras (A3)
En la misma llamada, `vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 400}`. Hoy usa el valor por defecto de faster-whisper. Documenta por qué en un comentario.

### 3.5 Script de medición
Crea `backend/herramientas/medir.py`, una herramienta de línea de comandos que **no se empaqueta** en el instalador:

```
python -m backend.herramientas.medir --referencia ref.bitacora --hipotesis hip.bitacora
```

Imprime, entre dos documentos `.bitacora`:
- **WER**: palabras erradas, normalizando minúsculas, tildes conservadas y signos de puntuación fuera;
- **DER aproximado**: proporción del tiempo con voz asignada a una persona distinta, con un mapeo óptimo de voces (algoritmo húngaro con `scipy`, si ya está en el venv; si no, una búsqueda voraz documentada);
- el número de voces de cada documento.

Lee el formato `.bitacora` que ya usa la app; mira cómo lo escribe el frontend.

## 4. Qué NO hacer
- No cambiar el modelo de Whisper ni agregar Parakeet ni PyTorch.
- No descargar modelos en las pruebas: simula el extractor o el diarizador como hacen las pruebas actuales de `tests/test_voces.py`.
- No tocar el instalador ni `Dialegu_Engine.spec`, salvo para excluir `backend/herramientas` si hiciera falta.
- **No hacer commit ni push.** Deja los cambios en el árbol de trabajo.

## 5. Criterios de aceptación
- Pruebas nuevas en `tests/`:
  - el campo `personas` llega a `num_clusters` y desactiva la fusión;
  - sin `personas` se mantiene `-1` y la fusión;
  - `condition_on_previous_text=False` y `vad_parameters` llegan a `transcribe`;
  - `HUELLAS` apunta al archivo y al SHA nuevos;
  - `medir.py` da WER 0 y DER 0 con documentos idénticos, y valores conocidos con un caso sintético pequeño.
- `E:/Desarrollo/Aplicaciones/Grabadora/venv/Scripts/python.exe -m pytest -q` en verde.
- En `frontend/`: `npm run lint` y `npm test` en verde.

## 6. Entrega
Por punto: qué cambiaste (archivo y línea), las pruebas y su resultado, y las preguntas abiertas.
