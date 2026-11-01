import prueba from 'node:test'
import afirmar from 'node:assert/strict'
import { alternarCita, editarMomento, marcarMomento, normalizarDocumento, unirConAnterior, dividirTurno } from './transcripcion.js'

const antiguo = () => ({ version: 1, meta: { nombre: 'v0.2' }, voces: [{id: 'v1', nombre: 'Ana'}], turnos: [{id: 't1', voz: 'v1', inicio: 1.25, fin: 10, texto: 'Hola mundo', palabras: []}] })
prueba('abro un proyecto v0.2 con los valores opcionales', () => {
  const d = normalizarDocumento(antiguo())
  afirmar.equal(d.version, 1)
  afirmar.equal(d.meta.tipo, 'encuentro')
  afirmar.deepEqual(d.meta.momentos, [])
  afirmar.deepEqual(d.meta.guia, [])
  afirmar.equal(d.meta.entrevistadora, null)
})
prueba('marcar momento guarda el segundo exacto y conserva el original', () => {
  const d = antiguo()
  const resultado = marcarMomento(d, 312.456)
  afirmar.equal(resultado.meta.momentos[0].inicio, 312.456)
  afirmar.equal(d.meta.momentos, undefined)
})
prueba('la guía titula las preguntas en orden', () => {
  const d = antiguo()
  d.meta.tipo = 'grupo_focal'
  d.meta.guia = ['Primera', 'Segunda']
  const resultado = marcarMomento(marcarMomento(d, 1.25), 8)
  afirmar.deepEqual(resultado.meta.momentos.map((m) => [m.titulo, m.tipo]), [['Primera', 'pregunta'], ['Segunda', 'pregunta']])
})
prueba('edito, muevo, ordeno y elimino momentos sin cambiar sus ids', () => {
  let d = marcarMomento(marcarMomento(antiguo(), 10), 20)
  d = editarMomento(d, 'm2', {inicio: 0, titulo: 'Apertura'})
  afirmar.equal(d.meta.momentos[0].id, 'm2')
  afirmar.equal(d.meta.momentos[0].titulo, 'Apertura')
  d = editarMomento(d, 'm2', null)
  afirmar.deepEqual(d.meta.momentos.map((m) => m.id), ['m1'])
})
prueba('la estrella marca y desmarca una cita sin mutar el turno', () => {
  const d = antiguo()
  const marcado = alternarCita(d, 't1')
  afirmar.equal(marcado.turnos[0].cita, true)
  afirmar.equal(alternarCita(marcado, 't1').turnos[0].cita, false)
  afirmar.equal(d.turnos[0].cita, undefined)
})
prueba('dividir y unir conserva las citas', () => {
  const d = alternarCita(antiguo(), 't1')
  const dividido = dividirTurno(d, 't1', 5)
  afirmar.ok(dividido.turnos.every((t) => t.cita))
  const soloSegundo = alternarCita(dividido, 't1')
  afirmar.equal(unirConAnterior(soloSegundo, 't2').turnos[0].cita, true)
})
prueba('un grupo focal sin guía permite marcar preguntas', () => {
  const d = antiguo()
  d.meta.tipo = 'grupo_focal'
  const marcado = marcarMomento(d, 1.25)
  afirmar.equal(marcado.meta.momentos[0].tipo, 'pregunta')
  afirmar.equal(marcado.meta.momentos[0].titulo, 'Pregunta 1')
})
