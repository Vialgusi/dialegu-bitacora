# Prueba de punta a punta con audio público (revisión de 0.4.0)

Prueba hecha el 3 de noviembre de 2026 sobre el motor de la 0.4.0 y sobre esta rama, con audios de Wikimedia Commons. No se usó ninguna grabación privada y los audios no están en el repositorio. Para repetirla, descargue los archivos y recórtelos con `ffmpeg`.

## Audios

| Audio | Licencia | Voces reales | Uso |
|---|---|---|---|
| [Debate presidencial Perú 2006, parte 1](https://commons.wikimedia.org/wiki/File:Debate-presidencial-peru2006-parte1.ogg) (18 min 21 s) | Dominio público | 3 (moderador y dos candidatos), grabación de sala con ruido | Caso difícil |
| [Entrevista Wikimedia (radio, Venezuela)](https://commons.wikimedia.org/wiki/File:ENTREVISTA_WIKIMEDIA.ogg), primeros 8 min | CC BY-SA 4.0 (Fhaidel) | 2 (entrevistadora e invitado) | Caso limpio |

Equipo: i7-8700, 32 GB, GTX 1660 Ti. Modelo «Preciso» (`large-v3-turbo`), español, salvo que se indique.

## Resultados

| Caso | Voces detectadas en 0.4.0 | Voces detectadas con esta rama |
|---|---|---|
| Entrevista 8 min, automático | **1** (invitada e invitado en el mismo turno) | **2**, turnos alternados correctamente |
| Entrevista 8 min, «2 personas» | 2, correcto | 2, correcto |
| Debate 18 min, automático | **1** | 2 (el moderador queda con uno de los candidatos) |
| Debate 18 min, «3 personas» | 2 (la tercera quedó por debajo de 10 s y se absorbió) | sin cambio |

Tiempos de proceso (incluye voces): entrevista de 8 min, 117 s con la tarjeta gráfica y 159 s solo con el procesador y el modelo «Ligero»; debate de 18 min, 249 a 279 s con la tarjeta. La primera transcripción tras abrir la app suma unos 50 s de carga del modelo en la tarjeta.

Exportación: informe Word, PDF y Markdown, más Markdown, PDF, SRT y TXT de la transcripción, en los tres tipos de sesión. Los siete formatos se abren sin errores; tildes, comillas, `<`, `&`, `*` y `#` en citas salen bien.

## Qué falló y por qué

En 0.4.0 el modo automático juntaba a todas las personas en una voz. La agrupación sí separa a las personas, pero después `fusionar_por_similitud` (umbral 0,55) volvía a unirlas: con la huella WeSpeaker, el promedio de las huellas de personas distintas da una similitud de 0,86 a 0,96, así que ningún umbral útil sirve para decidir «misma persona». Con la huella anterior, personas distintas daban 0,1 a 0,6 y una misma persona 0,88, y por eso 0,6 funcionaba en la 0.3.

Medición de la agrupación sola (umbral de sherpa) con la huella WeSpeaker:

| Umbral | Entrevista (2 voces reales) | Debate (3 voces reales) |
|---|---|---|
| 0,3 | 2 grupos grandes y 3 fragmentos | 7 grupos |
| 0,4 | 2 grupos grandes y 2 fragmentos | 4 grupos |
| 0,5 | 2 grupos limpios | 2 grupos |
| 0,6 | 1 grupo | no medido |

## Qué cambia

- Umbral de agrupación 0,4 y sin fusión entre voces grandes: solo se absorben fragmentos (menos de 20 s o del 5 % del habla) en la voz grande más parecida.
- «Unir con…» en el panel de voces de la revisión y aviso cuando solo se detecta una voz en un audio largo.
- Validación del número de personas en el formulario y mensaje correcto mientras se carga el modelo.

## Pendiente

- La calibración sale de dos audios. Conviene medir con más grabaciones propias (con su consentimiento) usando `python -m backend.herramientas.medir`.
- Grabaciones con ruido de sala y voces parecidas siguen mezclando personas; indicar cuántas hablan es lo más fiable.
- En entrevistas, el informe usa el turno completo de la entrevistadora como encabezado de pregunta; con turnos largos queda pesado.
