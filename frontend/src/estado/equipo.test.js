import { test as prueba } from 'node:test'
import afirmar from 'node:assert/strict'
import { advertencias, aproximado, claveVelocidad, formatoDuracion, formatoMemoria, formatoTamano, recomendar } from './equipo.js'

const GB = 2 ** 30

prueba('formatos legibles de tiempo y tamaño', () => {
  afirmar.equal(formatoDuracion(20), 'menos de 1 min')
  afirmar.equal(formatoDuracion(1018), '17 min')
  afirmar.equal(formatoDuracion(3900), '1 h 05 min')
  afirmar.equal(formatoTamano(1621665983), '1,6 GB')
  afirmar.equal(formatoTamano(486212372), '486 MB')
})

prueba('la clave coincide con la del motor', () => {
  afirmar.equal(claveVelocidad('alta', true, false), 'alta|cuda|sin_voces')
  afirmar.equal(claveVelocidad('rapida', false, true), 'rapida|cpu|voces')
})

prueba('recomienda Preciso con tarjeta o equipo holgado, Ligero si es modesto', () => {
  afirmar.equal(recomendar({ gpu: { nombre: 'x' }, hilos: 4, memoria: 4 * GB }), 'alta')
  afirmar.equal(recomendar({ gpu: null, hilos: 12, memoria: 16 * GB }), 'alta')
  afirmar.equal(recomendar({ gpu: null, hilos: 4, memoria: 8 * GB }), 'rapida')
  afirmar.equal(recomendar({ gpu: null, hilos: 8, memoria: 4 * GB }), 'rapida')
})

prueba('advierte solo lo que aplica', () => {
  const holgado = { gpu: { librerias: true, preparada: true }, memoria_libre: 20 * GB }
  afirmar.deepEqual(advertencias(holgado, 'alta', true), [])
  afirmar.match(advertencias({ ...holgado, memoria_libre: 2 * GB }, 'alta', true)[0], /memoria libre/)
  afirmar.match(advertencias({ gpu: null, memoria_libre: 20 * GB }, 'maximo', false)[0], /muy lento/)
  afirmar.match(advertencias({ ...holgado, gpu: { librerias: false } }, 'alta', true)[0], /570 MB/)
  afirmar.match(advertencias({ ...holgado, gpu: { librerias: true, preparada: false } }, 'alta', true)[0], /prepara/)
})

prueba('memoria en binario y frase aproximada sin «unos 1 min»', () => {
  afirmar.equal(formatoMemoria(16 * GB), '16 GB')
  afirmar.equal(aproximado(20), 'menos de 1 min')
  afirmar.equal(aproximado(70), 'alrededor de 1 min')
  afirmar.equal(aproximado(1018), 'unos 17 min')
})
