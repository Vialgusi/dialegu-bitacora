# Banco de rendimiento

Archivos de ejemplo para `backend/herramientas/banco.py`. El diseño completo está en [`docs/specs/SPEC-PRUEBAS-RENDIMIENTO.md`](../specs/SPEC-PRUEBAS-RENDIMIENTO.md).

- `variantes-fase1.json`: las variantes de la fase 1 (hipótesis H1 a H6, más dos de referencia con el modelo Ligero).
- `corpus-ejemplo.json`: la forma de un corpus. Las rutas son relativas a la carpeta donde guarde **su** copia del archivo; los audios y las referencias no van en el repositorio. Las entradas con el mismo `grupo` son el mismo audio en distintos formatos y alimentan la tabla de H0.

Campos de cada audio: `id`, `audio`, `referencia` (un `.bitacora` revisado por una persona), `sha256_referencia` (para detectar cambios), `idioma`, `personas`, `tema`, `tipo`, `grupo` y `recortar` (segundos; recorta el audio y la referencia).

Campos de cada variante (lo que no se declara queda como en la app 0.4.1): `calidad` (`rapida`, `alta`, `maximo`), `compute_type`, `hilos_whisper` y `hilos_voces` (un número, `produccion`, `fisicos-1`, `todos` o `mitad`), `beam_size`, `por_lotes`, `tamano_lote`, `distinguir_voces`, `voces_sin_silencio` y `paralelo`.

```bash
pip install psutil   # opcional: RAM pico, CPU y --nucleos en Windows
python -m backend.herramientas.banco --corpus mi-corpus.json --variantes docs/banco/variantes-fase1.json --datos <carpeta> --en-seco
```
