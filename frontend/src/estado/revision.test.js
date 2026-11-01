import { test as prueba } from 'node:test'
import afirmar from 'node:assert/strict'
import {
  citarFragmento,
  contarCoincidencias,
  listarCitas,
  quitarCita,
  reemplazarTodo,
  tiempoEnPosicion,
} from './transcripcion.js'

const documento = () => ({
  meta: { nombre: 'Prueba' },
  voces: [
    { id: 'v1', nombre: 'Ana', segundos: 4 },
    { id: 'v2', nombre: 'Raúl', segundos: 4 },
  ],
  turnos: [
    {
      id: 't1',
      voz: 'v1',
      inicio: 10,
      fin: 14,
      texto: 'Llegaron de Venesuela ayer.',
      palabras: [
        { inicio: 10, fin: 11, texto: ' Llegaron' },
        { inicio: 11, fin: 11.5, texto: ' de' },
        { inicio: 11.5, fin: 13, texto: ' Venesuela' },
        { inicio: 13, fin: 14, texto: ' ayer.' },
      ],
    },
    { id: 't2', voz: 'v2', inicio: 20, fin: 24, texto: 'En venesuela también.', palabras: [], cita: true },
  ],
})

prueba('el tiempo de una posición sale de la palabra; sin palabras, se estima', () => {
  const d = documento()
  afirmar.equal(tiempoEnPosicion(d.turnos[0], 14), 11.5)
  afirmar.equal(tiempoEnPosicion(d.turnos[0], 0), 10)
  afirmar.equal(tiempoEnPosicion(d.turnos[1], 0), 20)
  afirmar.ok(tiempoEnPosicion(d.turnos[1], 10) > 21)
})

prueba('citar un fragmento guarda texto y tiempos exactos, sin duplicar', () => {
  const d = documento()
  const desde = d.turnos[0].texto.indexOf('de')
  const hasta = d.turnos[0].texto.indexOf(' ayer')
  const citado = citarFragmento(d, 't1', desde - 1, hasta + 1)
  afirmar.deepEqual(citado.citas, [{ id: 'c1', turno: 't1', voz: 'v1', inicio: 11, fin: 13, texto: 'de Venesuela' }])
  afirmar.equal(citarFragmento(citado, 't1', desde, hasta), citado)
  afirmar.equal(citarFragmento(d, 't1', 3, 3), d)
  afirmar.equal(d.citas, undefined)
})

prueba('el panel junta turnos con estrella y fragmentos en orden y con la voz actual', () => {
  const d = citarFragmento(documento(), 't1', 0, 8)
  const citas = listarCitas(d)
  afirmar.deepEqual(citas.map((c) => [c.tipo, c.nombre, c.inicio]), [['fragmento', 'Ana', 10], ['turno', 'Raúl', 20]])
  afirmar.equal(listarCitas(quitarCita(d, 'c1')).length, 1)
})

prueba('reemplazar todo sin distinguir mayúsculas y conservando tiempos de una palabra', () => {
  const d = documento()
  afirmar.equal(contarCoincidencias(d, 'venesuela'), 2)
  const r = reemplazarTodo(d, 'Venesuela', 'Venezuela')
  afirmar.equal(r.turnos[0].texto, 'Llegaron de Venezuela ayer.')
  afirmar.equal(r.turnos[1].texto, 'En Venezuela también.')
  afirmar.equal(r.turnos[0].palabras[2].texto, ' Venezuela')
  afirmar.equal(r.turnos[0].palabras[2].inicio, 11.5)
  afirmar.equal(contarCoincidencias(r, 'venesuela'), 0)
  afirmar.equal(reemplazarTodo(d, 'no existe', 'x'), d)
  afirmar.equal(reemplazarTodo(d, 'de Venesuela', 'desde Venezuela').turnos[0].palabras.length, 0)
  afirmar.equal(reemplazarTodo(d, 'a.b', 'x'), d)
})
