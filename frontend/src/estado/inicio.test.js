import prueba from 'node:test'
import afirmar from 'node:assert/strict'
import { normalizarPersonas } from './equipo.js'

prueba('normaliza enteros entre 1 y 12 escritos en el formulario', () => {
  for (const valor of [1, 2, 12, '1', '2', '12', ' 3 '])
    afirmar.equal(normalizarPersonas(valor, true), Number(valor))
})

prueba('vacíos, decimales, texto y valores fuera de rango dejan el modo automático', () => {
  for (const valor of ['', ' ', null, undefined, '2,5', '2.5', 2.5, 'texto', 0, '0', 13, '13', -1, NaN, Infinity, true, false, [], {}])
    afirmar.equal(normalizarPersonas(valor, true), null)
})

prueba('sin distinguir voces se descarta el número de personas', () => {
  for (const valor of ['2', 1, 12, ''])
    afirmar.equal(normalizarPersonas(valor, false), null)
})
