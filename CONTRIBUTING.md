# Cómo contribuir a Dialegu Bitácora

Gracias por querer mejorar Bitácora. Toda ayuda cuenta: reportar un error, contar cómo le fue con sus audios, proponer una idea, mejorar textos o escribir código.

## Antes que nada: privacidad

Bitácora se usa con conversaciones reales, a menudo sensibles.

- **No suba audios, transcripciones, proyectos `.bitacora` ni exportaciones reales** a issues, PR o discusiones, ni siquiera fragmentos.
- Si un error depende del audio, descríbalo con datos técnicos: duración, formato, modelo, si se usó la tarjeta gráfica y el mensaje de error. Si hace falta un ejemplo, grabe uno propio sin datos personales o use el modo demostración.
- Las capturas de pantalla deben mostrar la demostración o datos inventados.

## Reportar un error o proponer una mejora

Abra un [issue](../../issues/new/choose) con la plantilla que corresponda. Incluya la versión de la app, Windows, procesador, memoria y tarjeta gráfica (la pantalla de inicio los muestra en «Tu equipo»).

Para hablar de **calidad de la transcripción**, lo más útil son números: qué modelo, cuánto tardó y qué tipo de errores vio (nombres propios, voces confundidas, texto repetido), sin copiar el texto.

## Contribuir código

1. Haga un fork y cree una rama desde `main`: `feature/descripcion-corta` o `fix/descripcion-corta`.
2. Prepare el entorno como indica el [README](README.md#desarrollo).
3. Haga cambios pequeños y enfocados, con pruebas cuando cambie el comportamiento:
   - motor: `tests/` con pytest;
   - interfaz: `frontend/src/estado/*.test.js` con `node --test`.
4. Antes de abrir el PR:

   ```bash
   venv\Scripts\python -m pytest tests
   cd frontend && npm test && npm run lint && npm run build
   ```

5. Abra el PR y explique qué cambia, por qué y cómo lo probó. El CI corre las mismas pruebas en Windows.

### Convenciones

- **Idioma:** la interfaz, los mensajes, los nombres en el código y los commits van en español. Para quien usa la app: usted, frases cortas y verbos en primera persona en los botones («Guardo mi proyecto»).
- **Commits:** estilo convencional en español, por ejemplo `feat(exportar): …`, `fix(voces): …`, `docs: …`.
- **Sin servicios externos:** el audio y el texto no deben salir del equipo. Toda descarga nueva (modelos, librerías) se fija por versión y se verifica con SHA-256.
- **Contrato:** si cambia la API entre la interfaz y el motor, actualice [docs/CONTRATO-MOTOR.md](docs/CONTRATO-MOTOR.md).

## Licencia

Al contribuir, acepta que su aporte se publique bajo la licencia del proyecto, [GPL-3.0-or-later](LICENSE).
