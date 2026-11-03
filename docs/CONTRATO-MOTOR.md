# Contrato entre motor, Electron e interfaz (v0.3; compatible con v0.2)

Tres piezas:

- **Motor**: Python (FastAPI) en `backend/`. Transcribe, reconoce voces y exporta.
- **Electron**: `frontend/electron-main.cjs` y `frontend/preload.cjs`. Arranca el motor y maneja los archivos (la app no graba: solo carga audio o video).
- **Interfaz**: React, en `frontend/src/`. Solo habla con el motor por HTTP y con Electron por `window.bitacora`.

## 1. Arranque del motor

```
python -m backend.servidor --puerto <n> --token <t> --datos <carpeta> [--padre <pid>]
Dialegu_Engine.exe        --puerto <n> --token <t> --datos <carpeta> [--padre <pid>]
```

- `--padre`: pid del proceso de Electron. El motor termina solo cuando ese proceso desaparece, aunque se haya cerrado de golpe.
- El motor se ejecuta con prioridad «por debajo de lo normal», y el proceso de voces la hereda.

- Escucha solo en `127.0.0.1:<puerto>`. Electron elige un puerto libre y un token aleatorio de 32 bytes en hexadecimal.
- `--datos` es la carpeta de trabajo (por defecto `%LOCALAPPDATA%\Dialegu Bitacora`). Ahí guarda los modelos (`modelos/`) y los trabajos (`trabajos/<id>/`).
- Todas las rutas `/api/*` exigen la cabecera `X-Token: <t>`. Solo `GET /api/trabajos/{id}/audio` acepta además `?token=<t>`, para poder usarla en `<audio src>`. Sin token correcto responden `401`.
- CORS: solo `null` (archivo local en Electron) y `http://localhost:5175` (desarrollo).

## 2. API HTTP

| Método y ruta | Entrada | Respuesta |
|---|---|---|
| `GET /api/salud` | — | `{ "estado": "listo", "version": "0.2.0", "gpu": true }` (`gpu`: hay una tarjeta NVIDIA con CUDA) |
| `GET /api/equipo` | — | `{ procesador, hilos, memoria, memoria_libre, gpu: { nombre, memoria, librerias, preparada } \| null, modelos: { rapida\|alta\|maximo: { nombre, tamano, descargado } }, por_hora: { "alta\|cuda\|voces": segundos, … } }`. `por_hora` son segundos de proceso por hora de audio en este equipo (medidos si ya hubo trabajos; si no, de referencia), sin contar descargas |
| `POST /api/estimacion` | `{ ruta_audio, calidad, usar_gpu, distinguir_voces }` | `{ duracion, dispositivo: "gpu"\|"cpu", segundos, segundos_proceso, medido, descarga, preparar_gpu }`. `segundos` incluye descargas pendientes y la preparación inicial de la tarjeta |
| `POST /api/trabajos` | JSON `NuevoTrabajo` | `201 { "id": "<id>" }` |
| `GET /api/trabajos/{id}` | — | `EstadoTrabajo` |
| `DELETE /api/trabajos/{id}` | — | `204`; cancela si está en cola o procesando |
| `GET /api/trabajos/{id}/resultado` | — | `Transcripcion` (`409` si aún no está listo) |
| `GET /api/trabajos/{id}/audio` | — | audio WAV 16 kHz mono, con soporte de `Range` |
| `POST /api/exportar` | JSON `{ "transcripcion": Transcripcion, "formato": "informe-docx" \| "informe-pdf" \| "informe-md" \| "md" \| "pdf" \| "srt" \| "txt" }` | archivo (bytes) con `Content-Disposition` |

Los errores responden con el código HTTP correspondiente y `{ "detail": "<texto en español>" }`. La interfaz muestra ese texto. Si `detail` no es un texto (errores de validación `422`), muestra «Los datos enviados no son válidos».

`NuevoTrabajo`:

```json
{
  "ruta_audio": "C:\\Users\\...\\entrevista.mp4",
  "nombre": "Entrevista a Natalia",
  "tema": "Inclusión de estudiantes migrantes",
  "tipo": "entrevista",
  "idioma": "es",
  "calidad": "rapida",
  "usar_gpu": true
}
```

- `ruta_audio`: ruta absoluta en el equipo (audio o video). La interfaz nunca sube bytes: Electron le da la ruta.
- `tipo`: `encuentro` | `grupo_focal` | `entrevista`.
- `idioma`: código ISO (`es`, `en`, `pt`…) o `auto`.
- `calidad`: `rapida` = «Ligero» (Whisper `small`) | `alta` = «Preciso» (`large-v3-turbo`) | `maximo` = «Máximo» (`large-v3`, 3,1 GB). Se respeta la elección también con GPU.
- `tema`: además de ir al informe, se pasa a Whisper como `hotwords` (nombres, lugares y términos que orientan la transcripción).
- `personas` (opcional, `null` por omisión): entero entre 1 y 12. Fija el número de voces y omite la fusión por similitud; con `null` la detección es automática. Solo se usa si `distinguir_voces` está activo. Se conserva en `meta.personas`.
- `usar_gpu` (por defecto `true`): si hay NVIDIA, transcribe en la tarjeta. La primera vez descarga cuBLAS (~570 MB, paquete oficial de NVIDIA en PyPI verificado con SHA-256) a `<datos>/modelos/cuda` y compila los núcleos CUDA (unos minutos). Ante cualquier fallo de la GPU el trabajo sigue o se repite en la CPU.
- `distinguir_voces` (opcional, `true` por omisión): con `false` el motor no descarga ni usa los modelos de voces y entrega todo en una sola voz. Se copia en `meta.distinguir_voces`.
- Solo se procesa un trabajo a la vez; los demás esperan en cola.

`EstadoTrabajo`:

```json
{
  "id": "20261031-101500-a1b2",
  "estado": "procesando",
  "etapa": "transcripcion",
  "progreso": 42,
  "mensaje": "Transcribiendo: 27 de 64 minutos",
  "error": null
}
```

- `estado`: `en_cola` | `procesando` | `listo` | `error` | `cancelado`.
- `etapa`: `preparando` | `descargando_modelos` | `voces` | `transcripcion` | `alineacion` | `listo`.
- `progreso`: entero de 0 a 100, total del trabajo. Nunca retrocede.
- `mensaje`: texto en español listo para mostrar.
- `error`: texto en español, solo si `estado` es `error`.

## 3. `Transcripcion` (el documento central)

Es también lo que se guarda en el proyecto `.bitacora`.

```json
{
  "version": 1,
  "meta": {
    "nombre": "Entrevista a Natalia",
    "tema": "Inclusión de estudiantes migrantes",
    "tipo": "entrevista",
    "guia": ["¿Qué ha significado la huerta?"],
    "momentos": [{ "id": "m1", "inicio": 1.7, "titulo": "¿Qué ha significado la huerta?", "tipo": "pregunta" }],
    "entrevistadora": "v1",
    "fecha": "2026-10-31T10:15:00",
    "duracion": 3865.8,
    "idioma": "es",
    "calidad": "rapida",
    "dispositivo": "cpu",
    "modelo": "large-v3-turbo",
    "modelo_voces": "pyannote segmentación 3.0 + WeSpeaker ResNet34 VoxCeleb",
    "segundos_proceso": 1056,
    "version_app": "0.4.0",
    "audio_original": "C:\\...\\entrevista.mp4"
  },
  "voces": [
    { "id": "v1", "nombre": "Voz 1", "segundos": 1580.2 },
    { "id": "v2", "nombre": "Voz 2", "segundos": 2101.7 }
  ],
  "turnos": [
    {
      "id": "t1",
      "voz": "v1",
      "inicio": 1.7,
      "fin": 130.5,
      "texto": "Mi nombre es Karen Leal…",
      "cita": true,
      "palabras": [ { "inicio": 1.7, "fin": 2.0, "texto": "Mi" } ]
    }
  ]
}
```

Reglas:

- `version` sigue en **1**. Todos los campos de informe son opcionales: `meta.tipo` vale `encuentro` si falta; `meta.momentos` y `meta.guia` valen `[]`; `meta.entrevistadora` vale `null`; `turnos[].cita` vale `false`.
- `meta.tipo`: `encuentro` | `grupo_focal` | `entrevista`.
- `meta.momentos`: marcas con `id` único y estable, `inicio` en segundos no negativos, `titulo` y `tipo` (`momento` | `pregunta`), ordenadas por `inicio`. Al mover una marca se reordena la lista.
- `meta.guia`: preguntas en orden, una cadena por pregunta. `NuevoTrabajo` admite también `guia` y `momentos` opcionales y el motor los conserva en `meta` del resultado.
- `meta.entrevistadora`: identificador de voz o `null`. Si falta o la voz ya no tiene turnos, el informe usa la voz activa con menos tiempo de palabra (en empates, primera aparición).
- `turnos[].cita`: booleano editable. Al unir turnos, la cita se conserva si alguno estaba destacado; al dividir, ambas partes heredan la marca.
- `citas` (opcional, en la raíz del documento): fragmentos citados `[{ id, turno, voz, inicio, fin, texto }]`, creados al seleccionar texto y pulsar Ctrl+Q. `texto` es copia fija del fragmento; la voz del informe se toma del turno `turno` si aún existe (si no, de `voz`). El informe junta estos fragmentos con los turnos con `cita: true`, en orden de `inicio`.
- El informe calcula tiempos e intervenciones desde los turnos actuales. Los porcentajes usan el total de habla, no la duración del audio.
- Las secciones asignan turnos por su inicio: desde cada marca hasta antes de la siguiente. La apertura previa a la primera marca queda en la primera sección. Sin marcas, el índice usa el primer turno de cada bloque de diez minutos que tenga habla.
- Grupo focal: secciones por marcas `pregunta`; un título vacío usa la guía en ese orden. Sin preguntas marcadas, una sección (la guía sola no inventa tiempos).
- Entrevista: las preguntas consecutivas sin respuesta se agrupan; las respuestas consecutivas pertenecen a la última pregunta. El habla anterior a la primera pregunta queda como apertura. El anexo conserva todos los turnos.
- Los informes se exportan como `informe-docx`, `informe-pdf` e `informe-md`, con extensiones `.docx`, `.pdf` y `.md`. Los formatos anteriores conservan su comportamiento.

- `voces` va ordenado por orden de primera aparición. Los nombres los cambia la persona; el `id` no cambia nunca.
- `turnos` va ordenado por `inicio`. `palabras` puede venir vacío en turnos que la persona editó a mano.
- Tiempos en segundos (número real).
- La interfaz puede cambiar libremente `voces[].nombre`, `turnos[].voz`, `turnos[].texto`, unir turnos y dividirlos. Al hacerlo, recalcula `voces[].segundos` como la suma de `fin - inicio` de sus turnos, y puede eliminar voces sin turnos.

- `EstadoTrabajo` agrega `modelo`, `dispositivo` y `segundos_restantes` (con 20 % o más de avance, proyecta el ritmo real; antes, el estimado inicial).
- Tras cada trabajo sin descargas ni preparación de la tarjeta, el motor guarda su velocidad en `<datos>/velocidades.json` para afinar las estimaciones.
- El informe termina con una «Nota metodológica» armada con `meta` (modelo, dispositivo, idioma, voces, tiempo de proceso, versión y aviso de revisión humana).

## 4. Puente de Electron: `window.bitacora`

Lo expone `frontend/preload.cjs` con `contextBridge`. Todas las funciones devuelven promesas.

| Función | Devuelve | Para qué |
|---|---|---|
| `motor()` | `{ url: "http://127.0.0.1:<n>", token: "<t>" }` | conectar con el motor |
| `elegirAudio()` | ruta (`string`) o `null` | cuadro de diálogo para abrir audio o video |
| `guardarArchivo({ nombreSugerido, datos, extension })` | ruta o `null` | cuadro «Guardar como» para exportaciones; `datos` es `ArrayBuffer` |
| `guardarProyecto({ transcripcion, rutaProyecto })` | ruta o `null` | guarda el `.bitacora`; si `rutaProyecto` es `null`, pregunta dónde |
| `abrirProyecto()` | `{ ruta, transcripcion, urlAudio }` o `null` | abre un `.bitacora`; `urlAudio` es un `file:///` de `meta.audio_original`, o `null` si ese archivo ya no existe |
| `mostrarEnCarpeta(ruta)` | `true` | abre el explorador en el archivo |

Para escuchar fragmentos, la interfaz usa `GET /api/trabajos/{id}/audio?token=…` cuando viene de un trabajo, o `urlAudio` cuando viene de un proyecto reabierto.

## 5. Modo demostración (para desarrollar la interfaz sin motor)

Si la URL lleva `?demo=1`, la interfaz no llama al motor ni a `window.bitacora`. Usa un grupo focal sintético con tres preguntas marcadas y una cita en `frontend/src/demo/transcripcion-demo.json` y simula un trabajo que avanza de 0 a 100 en unos 8 segundos.
