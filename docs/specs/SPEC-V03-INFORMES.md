# SPEC · v0.3 — Del audio al informe del espacio

Base: `feature/v02-transcripcion-confiable` (`3b2ad7b`, PR #2 sin fusionar) · rama `feature/v03-informes`.

## 1. Objetivo
Que quien facilita salga de la Bitácora con un **informe de su encuentro, grupo focal o entrevista**, listo para trabajar o compartir, no solo con una transcripción.

## 2. Por qué
La apuesta de la app es facilitar la construcción colectiva: grabar los espacios y convertirlos en productos. Whisper entrega un texto plano; la v0.2 ya ordena por voces. La v0.3 agrega la estructura que pide cada tipo de espacio. Un grupo focal se lee por las preguntas de su guía; una entrevista, como preguntas y respuestas; un encuentro, por sus momentos. Además, el formato que la gente edita es Word.

## 3. Alcance

### 3.1 Contrato (`docs/CONTRATO-MOTOR.md`, sección 3)
Campos **opcionales** que no rompen proyectos v0.2: `version` sigue en 1 y, si un campo falta, se toma su valor por defecto.
- `meta.tipo`: `"encuentro" | "grupo_focal" | "entrevista"` (por defecto `"encuentro"`).
- `meta.momentos`: `[{ "id": "m1", "inicio": 312.4, "titulo": "Segunda pregunta", "tipo": "momento" | "pregunta" }]`, ordenado por `inicio`.
- `meta.guia`: `["¿Qué ha significado…?", …]`, la guía de preguntas de un grupo focal o una entrevista.
- `meta.entrevistadora`: el `id` de la voz que pregunta, en una entrevista.
- `turnos[].cita`: `true` si la persona la marcó como cita destacada.

Actualiza el ejemplo y las reglas del contrato.

### 3.2 Motor: informe (`backend/motor/exportar.py` y un módulo nuevo `backend/motor/informe.py`)
1. `construir_informe(transcripcion) -> dict`: estructura intermedia común a todos los formatos:
   - **portada:** nombre, tema, tipo, fecha y duración;
   - **participantes:** nombre, tiempo de palabra en minutos y porcentaje, y número de intervenciones;
   - **índice de momentos:** con su minuto. Si no hay momentos marcados, uno cada 10 minutos, titulado con las primeras palabras del turno que empieza ahí;
   - **citas destacadas:** voz, minuto y texto;
   - **cuerpo según el tipo:**
     - `grupo_focal`: secciones por pregunta. Las preguntas salen de `meta.momentos` con `tipo:"pregunta"` (si se marcaron) o de `meta.guia` alineada en orden con esos momentos. Si no hay preguntas marcadas, una sola sección;
     - `entrevista`: pares de pregunta y respuesta. Los turnos de `meta.entrevistadora` son las preguntas; si no está definida, se usa la voz con menos tiempo de palabra;
     - `encuentro`: secciones por momento.
   - **transcripción completa:** al final, como anexo, con minuto y voz.
2. Formatos nuevos en `FORMATOS`: `"informe-md"`, `"informe-pdf"` e `"informe-docx"`.
   - El DOCX con `python-docx`: títulos con estilos de Word (Título 1 y 2) para que funcione el panel de navegación, tabla de participantes y citas con estilo «Cita». Agrega `python-docx` a `backend/requirements.txt` y asegúrate de que `Dialegu_Engine.spec` lo incluya (con `collect_data_files('docx')` si hace falta, porque trae plantillas).
   - El PDF con la misma biblioteca que ya usa `a_pdf`.
3. Los exportadores actuales (`md`, `txt`, `srt`, `pdf`) **no cambian**.

### 3.3 Interfaz (`frontend/src`)
1. **Inicio:** elegir el tipo de espacio (encuentro, grupo focal o entrevista). En grupo focal y entrevista, un campo opcional para pegar la guía, una pregunta por línea.
2. **Distinguir voces** (casilla opcional en Inicio, activa por omisión): desactivada, el motor omite sherpa y entrega una sola voz. *(La grabación en vivo se quitó en la v0.2: los momentos se marcan en la revisión, sobre el turno seleccionado.)*
3. **Revisión:**
   - lista de momentos editable: cambiar el título, mover el segundo al turno actual, eliminar o agregar uno en el turno seleccionado;
   - estrella para marcar o desmarcar un turno como cita;
   - en entrevista, selector «¿Quién pregunta?» para `meta.entrevistadora`.
4. **Exportar:** la opción principal pasa a ser «Informe (Word)», seguida de «Informe (PDF)» y «Informe (Markdown)». Los formatos de v0.2 quedan bajo «Otros formatos».
5. Densidad de la interfaz: un título por pantalla, sin etiquetas que repitan el título, acciones con verbo y en primera persona.

## 4. Decisiones ya tomadas
- Nada sale del equipo: ni IA ni resumen automático en este lote. Eso es v0.4, opcional y avisado.
- Se respetan las trampas ya resueltas de la v0.2: voces en otro proceso, fusión por huella con umbral 0,6, runtime de VC en el spec, `HANDLE` en ctypes y vite en el puerto 5175 con `strictPort`.
- No se cambia la versión del archivo `.bitacora`: los campos nuevos son opcionales.

## 5. Criterios de aceptación
- Motor: `venv\Scripts\python -m pytest tests` en verde, con pruebas nuevas en `tests/test_informe.py`:
  - informe de grupo focal con 3 preguntas marcadas → 3 secciones con los turnos correctos;
  - entrevista sin entrevistadora → toma la voz con menos tiempo;
  - un proyecto v0.2 sin campos nuevos produce un informe válido;
  - el DOCX se abre con `python-docx`, tiene Título 1 «Participantes» y las citas;
  - `informe-pdf` produce bytes de PDF válidos.
- Interfaz: `npm test`, `npm run lint` y `npm run build` en verde, con pruebas nuevas:
  - marcar momento guarda el segundo;
  - la estrella marca una cita;
  - un proyecto v0.2 se abre sin errores.
- Modo demostración (`?demo=1`): muestra un grupo focal de ejemplo con 3 momentos y una cita.

## 6. Cómo verificar
```bash
venv/Scripts/python -m pytest tests -q
cd frontend && npm test && npm run lint && npm run build
```
No corras `npm ci`: `frontend/node_modules` es un junction a la copia principal. Si necesitas instalar `python-docx` en el venv compartido, hazlo con `venv/Scripts/python -m pip install python-docx` y anótalo.

## 7. Entrega
Commits atómicos:
1. `docs(contrato): campos de informe`;
2. `feat(motor): informe por tipo`;
3. `feat(motor): exportar Word`;
4. `feat(interfaz): tipo y guía`;
5. `feat(interfaz): marcar momento`;
6. `feat(interfaz): momentos, citas y quién pregunta`;
7. `test: …`.

**Sin push.** Resumen final: qué hiciste, las pruebas y su resultado, las desviaciones y las preguntas.

## 8. Restricciones (qué NO hacer)
- No tocar el empaquetado (salvo agregar `python-docx` al spec) ni el flujo de releases: eso va en otro encargo.
- No procesar audios reales con datos personales. Usa solo el demo sintético.
- No hacer push ni abrir PR.
