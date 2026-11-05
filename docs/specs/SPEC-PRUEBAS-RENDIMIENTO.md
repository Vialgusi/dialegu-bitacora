# SPEC · Diseño de pruebas de rendimiento en PC sin tarjeta gráfica

Rama: `ccr-a7d1c077-i21cic`. Herramienta: `backend/herramientas/banco.py` (no se empaqueta en el instalador).

## 1. Objetivo

Medir con datos, y no con impresiones, qué alternativas hacen que Bitácora tarde menos en un computador **sin tarjeta gráfica NVIDIA** sin empeorar de forma apreciable:

- la transcripción (WER, porcentaje de palabras erradas);
- la atribución de voces (DER, porcentaje del tiempo de habla asignado a la voz equivocada);
- la posibilidad de seguir usando el computador mientras procesa.

Este documento fija las hipótesis, el corpus, los equipos, las métricas, el protocolo, los criterios de decisión y el formato de los resultados. Ninguna optimización pasa al motor sin pasar antes por aquí.

## 2. Línea base

La línea base es el motor de la 0.4.1 tal como está:

| Parámetro | Valor actual | Dónde |
|---|---|---|
| Decodificación | PyAV → 16 kHz, mono, float32 en memoria y WAV int16 para las voces | `trabajos.py:202-207` |
| Motor de texto | faster-whisper / CTranslate2, `compute_type="int8"` en la CPU | `modelos.py:179` |
| Hilos de Whisper | `min(4, max(1, hilos // 3))` → 1 hilo en un equipo de 4 | `modelos.py:181` |
| Búsqueda | `beam_size=5`, `word_timestamps=True`, `vad_filter=True` | `trabajos.py:252-262` |
| Voces | sherpa-onnx, pyannote 3.0 + WeSpeaker ResNet34, `min(2, max(1, hilos // 4))` hilos | `voces.py:81` |
| Concurrencia | voces y texto en paralelo, en dos hilos | `trabajos.py:284` |

En el banco esta configuración se llama `base` y toda variante se compara contra ella **en el mismo equipo, con el mismo audio y en la misma sesión de medición**.

## 3. Hipótesis

Cada hipótesis cambia **una sola cosa** respecto de `base`. Las combinaciones se prueban solo en la fase 3, con las que hayan pasado.

| ID | Hipótesis | Variable | Esperado | Riesgo |
|---|---|---|---|---|
| H0 | Convertir el archivo a otro formato antes de procesar (WAV 16 kHz, FLAC, Opus) no cambia el tiempo de proceso | formato de entrada | Δ tiempo total < 2 %, Δ WER ≈ 0 | — (sirve para cerrar la pregunta) |
| H1 | Dar más hilos a Whisper acelera la transcripción en equipos de 4 a 8 hilos | `hilos_whisper` | 1,5–3× en transcripción | el equipo responde peor |
| H2 | Dar más hilos a las voces acelera esa etapa | `hilos_voces` | 1,3–2× en voces | ídem |
| H3 | `beam_size=1` acelera la transcripción en la CPU | `beam_size` | 1,5–2× | +WER en audio difícil |
| H4 | `BatchedInferencePipeline` acelera la transcripción | `por_lotes`, `tamano_lote` | 1,2–2× en la CPU | más RAM, cambios en marcas de tiempo |
| H5 | Quitar los silencios antes de reconocer voces acelera esa etapa sin empeorar el DER | `voces_sin_silencio` | proporcional al silencio | voces cortadas en los bordes |
| H6 | Con 4 hilos o menos, correr voces y texto en serie (cada uno con todos los hilos) es más rápido que en paralelo | `paralelo` | depende del equipo | — |
| H7 | Un modelo de huellas más liviano acelera las voces | `modelo_huellas` | 1,3–2× en voces | +DER |
| H8 | Acelerar el audio 1,25–1,5× solo para Whisper reduce la transcripción en proporción | `tempo` | −20 a −33 % en transcripción | +WER en habla rápida |
| H9 | Parakeet TDT 0.6B v3 (sherpa-onnx, int8) transcribe español mucho más rápido que Whisper turbo con WER parecido | motor de texto | 3–10× | puntuación, acentos regionales |
| H10 | whisper.cpp con Vulkan aprovecha gráficos integrados Intel o AMD | motor de texto | 2–5× frente a la CPU | empaquetado, controladores |
| H11 | Dos pasadas (borrador rápido y relectura con «Preciso» de los segmentos de baja confianza) acercan la calidad de «Preciso» en menos tiempo | flujo | 40–60 % del tiempo de «Preciso» | elegir mal los segmentos |

Las hipótesis H0 a H6 se pueden medir hoy con `banco.py` sin tocar el motor. Las que requieren integrar otros modelos o motores (H7 a H11) aparecen en §9 como fases siguientes, con lo que hay que agregar al banco.

## 4. Corpus de prueba

### 4.1 Reglas

- **Solo audio público o grabado para la prueba con consentimiento.** Nunca grabaciones reales de usuarios (ver `CONTRIBUTING.md`). Los audios **no se suben al repositorio**: se documenta de dónde salen y cómo se recortan.
- Cada audio tiene una **referencia revisada por una persona**: un `.bitacora` generado con «Máximo» y corregido por completo escuchando el audio (texto y voz de cada turno). Si es posible, una segunda persona revisa una muestra de 5 minutos.
- La referencia se congela: su SHA-256 queda anotado en `corpus.json` y el banco avisa si cambia.

### 4.2 Composición mínima

Cubre los tres tipos de sesión de la app y los casos difíciles que señala el README:

| ID | Tipo | Duración | Voces | Rasgo | Fuente sugerida |
|---|---|---|---|---|---|
| `entrevista-limpia` | entrevista | 8 min | 2 | radio, poco ruido | Entrevista Wikimedia (CC BY-SA 4.0), ya usada en `docs/PRUEBA-AUDIO-PUBLICO.md` |
| `debate-sala` | grupo focal | 18 min | 3 | sala, ruido, solapes | Debate presidencial Perú 2006 (dominio público) |
| `encuentro-largo` | encuentro | 45–60 min | 5 o más | silencios largos, micrófono lejano | grabación propia con consentimiento o Commons |
| `telefono` | entrevista | 10 min | 2 | 8 kHz remuestreado, celular | grabación propia |
| `acento-regional` | entrevista | 10 min | 2 | español rural o andino, nombres propios | Commons o grabación propia |
| `zoom-pistas` | grupo focal | 15 min | 3–4 | una pista por persona (para la fase 3) | grabación propia de una reunión de prueba |

Para H0 se generan, desde `entrevista-limpia` y `debate-sala`, copias en MP3 128 kbps, M4A/AAC, Opus 32 kbps, WAV 44,1 kHz estéreo y WAV 16 kHz mono, con `ffmpeg`. Las órdenes exactas quedan en §10.

Para las corridas rápidas del día a día basta con `entrevista-limpia` y los primeros 10 minutos de `debate-sala`. El corpus completo se corre antes de decidir.

## 5. Equipos

Lo que importa es el usuario sin tarjeta gráfica, así que el banco se corre en **equipos reales** de al menos tres perfiles y, mientras no los haya, en el equipo de desarrollo **simulando** los perfiles.

| Perfil | Ejemplo | Hilos | RAM | Uso |
|---|---|---|---|---|
| P1 · modesto | Celeron, Pentium Silver, Ryzen 3 de portátil | 2–4 | 4–8 GB | el caso que más importa |
| P2 · típico | Core i5 o Ryzen 5 de portátil de 4 a 6 años | 8 | 8–16 GB | la mayoría |
| P3 · de escritorio | i7-8700 (equipo de referencia) | 12 | 16–32 GB | techo; también se mide la GPU para comparar |

**Simulación de perfiles** en un equipo más potente: `--nucleos N` fija la afinidad del proceso a N núcleos lógicos (en Windows requiere `psutil`; en Linux usa `os.sched_setaffinity`). No simula la memoria, la caché ni la falta de AVX2, por eso los resultados simulados se marcan como tales y **nunca** reemplazan la medición en un P1 real antes de cambiar valores por defecto.

Condiciones de cada sesión de medición:

- portátil enchufado y plan de energía «Alto rendimiento» o «Equilibrado», siempre el mismo, anotado;
- sin otras aplicaciones pesadas abiertas; navegador cerrado;
- antivirus sin escaneo programado durante la sesión;
- el banco anota procesador, hilos, núcleos físicos, RAM, sistema, instrucciones (AVX2, AVX-512) y versiones de CTranslate2, faster-whisper, sherpa-onnx y onnxruntime.

## 6. Métricas

| Métrica | Definición | Cómo se mide |
|---|---|---|
| **RTF** total | segundos de proceso ÷ segundos de audio, sin descargas | reloj monotónico alrededor de todo el trabajo, en un proceso nuevo |
| RTF por etapa | decodificar, cargar modelo, voces, transcripción, alineación | relojes por etapa. Con `paralelo`, la etapa más larga manda |
| **WER** | Levenshtein por palabras, normalización de `medir.py` | `medir.wer(referencia, hipótesis)` |
| **DER aproximado** | omisiones + falsas alarmas + confusiones ÷ habla de referencia, mapeo húngaro | `medir.der_aproximado` |
| Voces detectadas | número de voces de la hipótesis frente a la referencia | `medir.medir` |
| **RAM pico** | máximo RSS del proceso de la corrida y sus hijos | `psutil` (opcional), muestreo cada 0,2 s del proceso y sus hijos; sin `psutil` queda vacía |
| CPU media | uso medio del proceso, en núcleos | `psutil`: tiempo de CPU del árbol de procesos ÷ tiempo de reloj |
| **Lentitud del equipo** | p95 de la duración de una tarea fija de 20 ms en un proceso aparte durante la corrida ÷ la misma tarea en reposo | sonda de `banco.py` |

La **lentitud del equipo** es la forma de medir que la app «no acapare el computador», que es una decisión de diseño explícita (`voces.py:79`, `modelos.py:180`). Un valor de 1,0 significa que la sonda no notó la carga; 3,0, que una tarea interactiva tarda tres veces más.

## 7. Protocolo

1. **Preparar.** Descargar los modelos una vez (`--datos` apunta a la carpeta de datos de la app o a una propia). Las descargas nunca cuentan en los tiempos.
2. **Calentar.** Una corrida de 60 s de audio con `base` que se descarta: carga la caché del disco y estabiliza la frecuencia del procesador.
3. **Aislar.** Cada corrida (variante × audio × repetición) corre en **un proceso nuevo**, así la RAM pico es la de esa corrida, el modelo se carga cada vez (como en la primera transcripción tras abrir la app) y la afinidad no se arrastra.
4. **Repetir.** 3 repeticiones por combinación (5 si la diferencia con `base` queda entre 5 y 15 %). Se reporta la **mediana** y el rango.
5. **Intercalar.** El orden de las corridas se baraja con semilla fija (`--semilla`): así el calentamiento térmico o una tarea de fondo no favorece siempre a la misma variante.
6. **Registrar.** Cada corrida agrega una línea a `resultados.jsonl` con el equipo, la variante completa, los tiempos, la RAM, la lentitud, el WER y el DER. Se guarda el `.bitacora` de la primera repetición para revisar los errores a mano.
7. **Resumir.** `banco.py --resumir` produce `resumen.md` con la tabla de medianas y el veredicto de cada variante según §8.

## 8. Criterios de decisión

Una variante se **acepta** para llevarla al motor si, en el corpus completo y en al menos un equipo P1 o P2 real:

- reduce el RTF total en **≥ 15 %** frente a `base` (mediana), y
- el WER sube **≤ 1,0 punto** absoluto en promedio y **≤ 2,0 puntos** en cualquier audio, y
- el DER sube **≤ 2,0 puntos** absolutos en promedio (si toca las voces), y
- la RAM pico no supera el **60 %** de la RAM del perfil P1 (≈ 4,8 GB en un equipo de 8 GB).

Se marca como **opción** (por ejemplo un modo «Lo más rápido posible» que la persona elige) si cumple el tiempo pero empeora el WER entre 1 y 3 puntos, o si la lentitud del equipo pasa de 2,0. En ese caso la interfaz tiene que explicar el costo.

Se **descarta** si no llega al 10 % de mejora o empeora el WER más de 3 puntos.

Para H0 la regla es la inversa: se confirma si el RTF total cambia menos de 2 % entre formatos y el WER cambia menos de 0,5 puntos (el Opus a 32 kbps puede empeorar algo por la compresión, no por el formato).

## 9. Fases

### Fase 1 · parámetros del motor actual (H0–H6)

Sin cambiar el motor: el banco reproduce la tubería de `trabajos.py` con los parámetros como variables. Archivo de variantes de ejemplo: `docs/banco/variantes-fase1.json`.

Matriz mínima por perfil:

| Variante | Cambia |
|---|---|
| `base` | — |
| `hilos-fisicos` | `hilos_whisper` = núcleos físicos − 1, `hilos_voces` = 2 |
| `hilos-todos` | `hilos_whisper` = hilos lógicos, `hilos_voces` = hilos lógicos ÷ 2 |
| `beam1` | `beam_size` = 1 |
| `lotes8` | `por_lotes` = true, `tamano_lote` = 8 |
| `voces-sin-silencio` | `voces_sin_silencio` = true |
| `serie` | `paralelo` = false con todos los hilos para cada etapa |
| `sin-voces` | `distinguir_voces` = false (techo de la transcripción sola) |

Y para H0, la variante `base` sobre cada copia del mismo audio en otro formato.

Se corre con los tres modelos solo en P3; en P1 y P2 basta con «Ligero» y «Preciso».

### Fase 2 · modelos y motores alternativos (H7–H10)

Lo que hay que agregar al banco, sin tocar el motor:

- **H7:** un parámetro `modelo_huellas` con los modelos de sherpa-onnx (3D-Speaker CAM++, ERes2Net-base, NeMo TitaNet-small), fijados por revisión y SHA-256 como los demás.
- **H8:** `tempo` aplica el filtro `atempo` de PyAV al audio de Whisper (no al de las voces) y divide las marcas de tiempo por el factor.
- **H9:** un motor de texto `parakeet` con `sherpa_onnx.OfflineRecognizer.from_transducer` y el modelo int8 de Parakeet TDT 0.6B v3. Hay que convertir sus marcas por token a palabras para reutilizar `asignar_voces`.
- **H10:** un motor `whisper.cpp` (por `pywhispercpp` o el ejecutable) con modelos GGML q5_0 o q8_0, medido con y sin Vulkan, en un equipo con gráficos integrados Intel y otro AMD.

Cada motor nuevo se compara contra `base` **y** contra el mejor resultado de la fase 1, que es la verdadera línea a superar.

### Fase 3 · combinaciones y flujos (H11 y pistas separadas)

- Combinar las variantes aceptadas (por ejemplo `hilos-fisicos` + `voces-sin-silencio` + `beam1`) y verificar que las ganancias se suman.
- **Pistas separadas:** con `zoom-pistas`, transcribir cada pista sin reconocer voces y ordenar por tiempo; comparar tiempo y DER contra la mezcla con voces.
- **H11 · dos pasadas:** medir con varios umbrales de confianza (`avg_logprob`, `compression_ratio`) qué fracción del audio se relee y cuánto se acerca el WER al de «Preciso».

### Fase 4 · validación en la app

Lo aceptado se implementa en el motor detrás de una opción, se repite el banco con la app empaquetada (`Dialegu_Engine`) en un P1 real y se actualizan la tabla de referencia de `equipo.py` (`REFERENCIA_TRANSCRIPCION`, `REFERENCIA_VOCES`) y los tiempos del README.

## 10. Uso del banco

```bash
# 1. Corpus: describa los audios y sus referencias (rutas locales, fuera del repositorio).
#    Ejemplo en docs/banco/corpus-ejemplo.json.

# 2. Correr la fase 1, 3 repeticiones, en un proceso nuevo cada vez.
python -m backend.herramientas.banco \
    --corpus mi-corpus.json \
    --variantes docs/banco/variantes-fase1.json \
    --datos "%APPDATA%\Dialegu Bitacora" \
    --salida resultados-banco \
    --repeticiones 3

# 3. Simular un equipo de 4 hilos en uno más grande (los resultados quedan marcados como simulados).
python -m backend.herramientas.banco ... --nucleos 4

# 4. Ver qué se correría, sin cargar modelos.
python -m backend.herramientas.banco ... --en-seco

# 5. Rehacer el resumen desde los resultados guardados.
python -m backend.herramientas.banco --resumir resultados-banco/<sesion>
```

Copias para H0 (`ffmpeg`, fuera del repositorio):

```bash
ffmpeg -i entrevista.ogg -ar 16000 -ac 1 -c:a pcm_s16le entrevista-16k.wav
ffmpeg -i entrevista.ogg -ar 44100 -ac 2 -c:a pcm_s16le entrevista-44k.wav
ffmpeg -i entrevista.ogg -c:a libmp3lame -b:a 128k entrevista.mp3
ffmpeg -i entrevista.ogg -c:a aac -b:a 96k entrevista.m4a
ffmpeg -i entrevista.ogg -c:a libopus -b:a 32k entrevista.opus
```

**Versión de PyAV.** `requirements.txt` no fija `av`. Con `faster-whisper==1.2.1`, PyAV 16 o posterior rompe `decode_audio` (`open() got an unexpected keyword argument 'metadata_errors'`, visto con PyAV 19.0.2 al preparar este banco). Instale `av<16` en el entorno del banco y anote la versión: el banco la registra en `equipo.json`.

Los resultados (`resultados-banco/`) **no se suben al repositorio** si incluyen texto transcrito de audios no públicos. El `resumen.md` solo tiene números y sí se puede compartir en un issue o PR.

## 11. Pruebas del banco

El banco tiene sus propias pruebas en `tests/test_banco.py`, que no descargan modelos ni usan audio real:

- lectura y validación del corpus y de las variantes (valores por defecto iguales a `base`, claves desconocidas rechazadas);
- expansión de la matriz y orden barajado reproducible con la semilla;
- cálculo de hilos (`"produccion"`, `"fisicos-1"`, `"todos"`, número);
- compactación del audio sin silencios y devolución exacta de los tiempos al audio original;
- resumen: medianas, deltas frente a `base` y veredicto según §8.

Corren en el CI junto a las demás (`pytest tests`).

## 12. Qué NO hacer

- No cambiar los valores por defecto del motor a partir de mediciones simuladas o de un solo audio.
- No usar audios ni transcripciones de personas usuarias como corpus.
- No agregar dependencias al instalador para el banco: `psutil` es opcional y solo lo usa la herramienta.
- No comparar corridas de equipos distintos entre sí sin normalizar contra la `base` de cada equipo.
