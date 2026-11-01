# SPEC · V02-INTERFAZ — Interfaz de grabación, progreso y revisión de la transcripción

- Repo de origen: Dialegu Bitácora · versión 0.2
- Implementa: Codex · revisa: responsable de producto (Claude)
- **Nota posterior (31-10):** la grabación se retiró de la app por decisión de producto; la pantalla Grabando y `grabacion.*` ya no existen. Esta especificación queda como registro de lo encargado.

## 1. Objetivo

Reescribir la interfaz React de `frontend/src/` para que una persona pueda:

1. iniciar una sesión (grabar, cargar audio o video, o abrir un proyecto);
2. ver el avance real del procesamiento y cancelarlo;
3. revisar la transcripción por turnos: nombrar las voces, reasignar turnos, corregir el texto, unir y dividir turnos, y escuchar cada turno;
4. guardar el proyecto y exportar.

Todo contra el contrato de `docs/CONTRATO-MOTOR.md`, que es la fuente de verdad.

## 2. Por qué

La app es para facilitadoras y facilitadores de procesos colectivos (grupos focales, entrevistas, encuentros) que no son técnicos. El motor ahora reconoce voces de verdad, pero nunca será perfecto: la pantalla de revisión es donde la persona convierte la transcripción automática en un registro confiable. La versión actual hace una sola petición que espera toda la transcripción, sin avance, y no permite corregir nada.

## 3. Alcance

**Incluye**

- Pantallas: Inicio, Grabando, Procesando, Revisión y Error, en componentes separados.
- Cliente del motor y del puente de Electron, con modo demostración (`?demo=1`, ver §5 del contrato).
- Funciones puras de edición de la transcripción, con pruebas.
- Hoja de estilos ajustada a una ventana de escritorio de 1100×760 (mínimo 900×640).

**No incluye** (no lo hagas; si te parece necesario, anótalo en el informe final)

- Nada fuera de `frontend/src/`. En particular, no toques `backend/`, `frontend/electron-main.cjs`, `frontend/preload.cjs`, `frontend/package.json`, `docs/` ni `frontend/public/`.
- No agregues dependencias npm.
- No implementes tú el guardado de archivos, la grabación en disco ni la exportación: se piden a `window.bitacora` y al motor.
- Nada de plantillas de informe, resúmenes con IA, «marcar momento» ni transcripción en vivo: son de v0.3 y v0.4.
- Quita los botones de WhatsApp y correo.

## 4. Archivos

| Archivo | Qué |
|---|---|
| `frontend/src/App.jsx` | Solo orquesta: estado de la vista y transiciones |
| `frontend/src/plataforma.js` | Acceso a `window.bitacora` y al motor (`fetch` con `X-Token`). En modo demo devuelve datos simulados con la misma forma |
| `frontend/src/estado/transcripcion.js` | Funciones puras e inmutables: `renombrarVoz`, `asignarVoz` (incluye crear una voz nueva), `editarTexto`, `unirConAnterior`, `dividirTurno`, `recalcularVoces` y `formatoTiempo` |
| `frontend/src/estado/transcripcion.test.js` | Pruebas con `node:test` y `node:assert` (sin dependencias), una por función, más los bordes: primer turno, voz que queda sin turnos, división al inicio o al final del texto |
| `frontend/src/componentes/Inicio.jsx` | Formulario de sesión |
| `frontend/src/componentes/Grabando.jsx` | Grabación |
| `frontend/src/componentes/Procesando.jsx` | Avance |
| `frontend/src/componentes/Revision.jsx` (y subcomponentes si hacen falta) | Revisión |
| `frontend/src/index.css` | Estilos (puedes vaciar `App.css`) |

## 5. Decisiones ya tomadas

**Textos.** En español, tratando de «usted», sin anglicismos («Cargar audio», no «Upload»). Nombres de variables y funciones en español, como en el contrato.

**Sin recursos externos.** Quita el `@import` de Google Fonts y usa la pila de fuentes del sistema (`system-ui, "Segoe UI", sans-serif`). La app debe funcionar sin internet.

**Inicio.**
- Campos: Nombre de la sesión (obligatorio), Tema (opcional) y Tipo (`Encuentro o reunión` / `Grupo focal` / `Entrevista`).
- Idioma: Español por defecto; también Detectar automáticamente, English y Português.
- Calidad: «Rápida», con la ayuda «unos 30 min por hora de audio», o «Alta precisión», con la ayuda «más lenta; para audios difíciles».
- Micrófono: el selector que ya existe.
- Botones: «Grabar», «Cargar audio o video» (`elegirAudio()` y luego crear el trabajo) y «Abrir proyecto» (va directo a Revisión).

**Grabando.**
- `MediaRecorder.start(5000)`. En cada `ondataavailable`, `grabacion.agregar(await e.data.arrayBuffer())`, en orden y sin perder trozos: encadena las promesas.
- Al detener: `grabacion.terminar()` y crear el trabajo con la ruta devuelta.
- Muestra el cronómetro y el nombre de la sesión.

**Procesando.**
- Consulta `GET /api/trabajos/{id}` cada 1000 ms.
- Muestra una barra de progreso, la etapa en español y el `mensaje`. Etapas: preparando → «Preparando el audio», descargando_modelos → «Descargando modelos (solo la primera vez)», voces → «Reconociendo voces», transcripcion → «Transcribiendo», alineacion → «Ordenando por turnos».
- Botón «Cancelar» (`DELETE`): vuelve a Inicio.
- Si el estado es `error`, va a la pantalla de Error con el texto del motor. Si es `listo`, pide `/resultado` y pasa a Revisión.

**Revisión.**

*Diseño*
- Cabecera: nombre, tipo, duración y número de voces.
- Columna lateral de 260 px con las voces; en ventanas de menos de 900 px pasa arriba.
- Lista de turnos a la derecha.

*Voces*
- Cada una con su muestra de color (paleta fija de 8 colores con buen contraste sobre blanco, asignada por orden).
- Nombre editable en un campo de texto.
- Minutos de habla y porcentaje.

*Turnos*
- Cada turno muestra:
  - un botón con la hora de inicio en `mm:ss` (o `h:mm:ss`), que reproduce desde ahí;
  - un selector de voz, con la opción «Otra voz…» al final, que crea `Voz N`;
  - el texto en un `textarea` que crece con su contenido;
  - las acciones «Unir con el anterior» y «Dividir aquí».
- «Dividir aquí» corta en la posición del cursor. El tiempo de corte sale de `palabras` si las hay (la última palabra cuyo texto acumulado cabe antes del cursor); si no, se reparte en proporción a los caracteres.
- El borde izquierdo de cada turno usa el color de su voz.
- El turno que se está escuchando queda resaltado y la lista lo desplaza a la vista, sin moverlo mientras la persona escribe en él.

*Audio*
- Un solo `<audio>` para toda la pantalla. Su fuente es `GET /api/trabajos/{id}/audio?token=…`, o `urlAudio` si el proyecto se reabrió. Si no hay audio, los botones de hora se desactivan con un aviso.

*Acciones*
- «Deshacer» (y `Ctrl+Z` fuera de los campos de texto) con una pila de 50 estados.
- «Guardar proyecto» (`Ctrl+S`): guarda en la misma ruta si ya tiene una.
- «Exportar», con un menú: Markdown, PDF, Subtítulos (SRT) y Texto. Llama a `POST /api/exportar` y luego a `guardarArchivo`.
- «Nueva sesión»: si hay cambios sin guardar, pide confirmación.

**Accesibilidad.** Todos los campos con `<label>` y todo se puede usar con teclado, con foco visible. Los colores de voz nunca son la única pista: el nombre de la voz siempre se ve.

## 6. Criterios de aceptación

1. `npm run lint` y `npm run build` (en `frontend/`) terminan sin errores ni advertencias nuevas.
2. `node --test frontend/src/estado/` pasa, con al menos 12 pruebas.
3. Con `npm run dev` y `http://localhost:5175/?demo=1`, se recorre todo el flujo sin consola con errores: Inicio → Procesando (avanza solo) → Revisión con los 8 turnos y las 2 voces del ejemplo. Renombrar «Voz 1» actualiza todos sus turnos; unir, dividir y deshacer funcionan; un clic en la hora reproduce `demo/huerta.mp3` desde ese punto.
4. Ningún componente llama a `fetch` ni a `window.bitacora` directamente: todo pasa por `plataforma.js`.
5. No hay URLs externas en `frontend/src/`.
6. `git diff --stat` solo muestra archivos dentro de `frontend/src/`.

## 7. Cómo verificar

```bash
cd frontend
npm run lint
npm run build
node --test src/estado/
git diff --stat
```

## 8. Entrega

- No hagas commit ni push. Deja los cambios en el árbol de trabajo.
- Termina con un informe breve en español: qué hiciste, la salida de los comandos de verificación, qué no pudiste verificar y las preguntas abiertas.

## 9. Restricciones

- `frontend/node_modules` es un enlace a otra copia del repositorio: no ejecutes `npm install` ni `npm ci`.
- Si el contrato y esta especificación se contradicen, gana el contrato. Anota la contradicción en el informe.
