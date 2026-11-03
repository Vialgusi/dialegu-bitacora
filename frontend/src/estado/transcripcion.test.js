import prueba from 'node:test'
import afirmar from 'node:assert/strict'
import {
  asignarVoz,
  avisoVoces,
  dividirTurno,
  editarTexto,
  formatoTiempo,
  recalcularVoces,
  renombrarVoz,
  unirConAnterior,
  unirVoces,
} from './transcripcion.js'

function ejemplo() {
  return {
    version: 1,
    meta: { nombre: 'Encuentro' },
    voces: [
      { id: 'v1', nombre: 'Voz 1', segundos: 0 },
      { id: 'v2', nombre: 'Voz 2', segundos: 0 },
    ],
    turnos: [
      { id: 't1', voz: 'v1', inicio: 0, fin: 10, texto: 'Hola mundo', palabras: [] },
      { id: 't2', voz: 'v2', inicio: 12, fin: 20, texto: 'Otra respuesta', palabras: [] },
      { id: 't3', voz: 'v1', inicio: 22, fin: 25, texto: 'Gracias', palabras: [] },
    ],
  }
}
prueba('unir voces reasigna todos los turnos, conserva los datos y actualiza la entrevistadora sin mutar', () => {
  const documento = ejemplo()
  documento.meta.entrevistadora = 'v1'
  const original = structuredClone(documento)
  const resultado = unirVoces(documento, 'v1', 'v2')
  afirmar.deepEqual(resultado.voces, [{ id: 'v2', nombre: 'Voz 2', segundos: 21 }])
  afirmar.deepEqual(resultado.turnos, documento.turnos.map((t) => ({ ...t, voz: 'v2' })))
  afirmar.equal(resultado.meta.entrevistadora, 'v2')
  afirmar.deepEqual(documento, original)
  documento.meta.entrevistadora = 'v2'
  afirmar.equal(unirVoces(documento, 'v1', 'v2').meta.entrevistadora, 'v2')
})
prueba('unir la misma voz o identificadores inexistentes devuelve el documento original', () => {
  const documento = ejemplo()
  for (const [origen, destino] of [['v1', 'v1'], ['v3', 'v1'], ['v1', 'v3']])
    afirmar.equal(unirVoces(documento, origen, destino), documento)
})
prueba('el aviso de una voz solo aparece desde tres minutos y al distinguir voces', () => {
  const documento = ejemplo()
  documento.meta.duracion = 180
  afirmar.equal(avisoVoces(documento), null)
  documento.voces = [documento.voces[0]]
  afirmar.equal(avisoVoces(documento), 'Solo se detectó una voz en 3 minutos. Si en el audio hablan varias personas, vuelva a transcribir indicando cuántas son en «¿Cuántas personas hablan?».')
  documento.meta.distinguir_voces = true
  afirmar.ok(avisoVoces(documento))
  documento.meta.distinguir_voces = false
  afirmar.equal(avisoVoces(documento), null)
  documento.meta.distinguir_voces = true
  documento.meta.duracion = 179
  afirmar.equal(avisoVoces(documento), null)
  delete documento.meta.duracion
  afirmar.equal(avisoVoces(documento), null)
  documento.meta.duracion = 600
  afirmar.match(avisoVoces(documento), /10 minutos/)
  documento.voces = []
  afirmar.equal(avisoVoces(documento), null)
})
prueba('renombrar una voz conserva su identificador y actualiza su duración', () => {
  const resultado = renombrarVoz(ejemplo(), 'v1', 'Karen')
  afirmar.deepEqual(resultado.voces[0], { id: 'v1', nombre: 'Karen', segundos: 13 })
  afirmar.equal(resultado.turnos[2].voz, 'v1')
})
prueba('asignar una voz existente recalcula segundos y orden de primera aparición', () => {
  const resultado = asignarVoz(ejemplo(), 't1', 'v2')
  afirmar.deepEqual(
    resultado.voces.map((voz) => [voz.id, voz.segundos]),
    [
      ['v2', 18],
      ['v1', 3],
    ],
  )
})
prueba('asignar otra voz crea un nombre y un identificador sin colisiones', () => {
  const resultado = asignarVoz(ejemplo(), 't2')
  afirmar.equal(resultado.turnos[1].voz, 'v3')
  afirmar.equal(resultado.voces[1].nombre, 'Voz 3')
})
prueba('se elimina la voz que queda sin turnos', () => {
  const resultado = asignarVoz(ejemplo(), 't2', 'v1')
  afirmar.deepEqual(resultado.voces, [{ id: 'v1', nombre: 'Voz 1', segundos: 21 }])
})
prueba('editar texto descarta palabras cuyos tiempos ya no corresponden', () => {
  const documento = ejemplo()
  documento.turnos[0].palabras = [{ texto: 'Hola', inicio: 0, fin: 3 }]
  const resultado = editarTexto(documento, 't1', 'Buenos días')
  afirmar.equal(resultado.turnos[0].texto, 'Buenos días')
  afirmar.deepEqual(resultado.turnos[0].palabras, [])
  afirmar.equal(documento.turnos[0].texto, 'Hola mundo')
})
prueba('unir conserva la voz y el identificador anteriores, y abarca la pausa', () => {
  const resultado = unirConAnterior(ejemplo(), 't2')
  afirmar.equal(resultado.turnos.length, 2)
  afirmar.deepEqual(resultado.turnos[0], {
    id: 't1',
    voz: 'v1',
    inicio: 0,
    fin: 20,
    texto: 'Hola mundo Otra respuesta',
    palabras: [],
  })
  afirmar.equal(resultado.voces[0].segundos, 23)
})
prueba('el primer turno no se puede unir con el anterior', () => {
  const documento = ejemplo()
  afirmar.equal(unirConAnterior(documento, 't1'), documento)
})
prueba('dividir sin palabras reparte el tiempo en proporción a caracteres', () => {
  const resultado = dividirTurno(ejemplo(), 't1', 5)
  afirmar.equal(resultado.turnos.length, 4)
  afirmar.equal(resultado.turnos[0].texto, 'Hola')
  afirmar.equal(resultado.turnos[1].texto, 'mundo')
  afirmar.equal(resultado.turnos[0].fin, 5)
  afirmar.equal(resultado.turnos[1].inicio, 5)
  afirmar.equal(resultado.turnos[1].id, 't4')
  afirmar.equal(resultado.voces[0].segundos, 13)
})
prueba('dividir usa el fin de la última palabra completa antes del cursor', () => {
  const documento = ejemplo()
  documento.turnos[0].palabras = [
    { texto: 'Hola', inicio: 0, fin: 2 },
    { texto: 'mundo', inicio: 3, fin: 10 },
  ]
  const resultado = dividirTurno(documento, 't1', 5)
  afirmar.equal(resultado.turnos[0].fin, 2)
  afirmar.equal(resultado.turnos[1].inicio, 2)
  afirmar.deepEqual(resultado.turnos[1].palabras, [documento.turnos[0].palabras[1]])
})
prueba('división al inicio del texto no modifica el documento', () => {
  const documento = ejemplo()
  afirmar.equal(dividirTurno(documento, 't1', 0), documento)
})
prueba('división al final del texto no modifica el documento', () => {
  const documento = ejemplo()
  afirmar.equal(dividirTurno(documento, 't1', 10), documento)
})
prueba('división que deja un texto vacío no modifica el documento', () => {
  const documento = ejemplo()
  documento.turnos[0].texto = ' Hola'
  afirmar.equal(dividirTurno(documento, 't1', 1), documento)
})
prueba('recalcular ordena turnos y voces, elimina voces vacías y suma tiempos', () => {
  const documento = ejemplo()
  documento.turnos.reverse()
  documento.voces.push({ id: 'v8', nombre: 'Sin turnos', segundos: 100 })
  const resultado = recalcularVoces(documento)
  afirmar.deepEqual(
    resultado.turnos.map((turno) => turno.id),
    ['t1', 't2', 't3'],
  )
  afirmar.deepEqual(
    resultado.voces.map((voz) => [voz.id, voz.segundos]),
    [
      ['v1', 13],
      ['v2', 8],
    ],
  )
  afirmar.equal(documento.turnos[0].id, 't3')
})
prueba('formato de tiempo incluye horas solo cuando corresponden y trunca decimales', () => {
  afirmar.equal(formatoTiempo(0), '00:00')
  afirmar.equal(formatoTiempo(65.9), '01:05')
  afirmar.equal(formatoTiempo(3665.8), '1:01:05')
  afirmar.equal(formatoTiempo(-2), '00:00')
})
prueba('las operaciones no mutan el documento, incluso con objetos congelados', () => {
  function congelar(objeto) {
    Object.freeze(objeto)
    Object.values(objeto).forEach((valor) => {
      if (valor && typeof valor === 'object') congelar(valor)
    })
    return objeto
  }
  const documento = congelar(ejemplo())
  const antes = JSON.stringify(documento)
  renombrarVoz(documento, 'v1', 'Nombre')
  asignarVoz(documento, 't1')
  editarTexto(documento, 't1', 'Corrección')
  unirConAnterior(documento, 't2')
  dividirTurno(documento, 't1', 5)
  recalcularVoces(documento)
  afirmar.equal(JSON.stringify(documento), antes)
})
prueba('identificadores desconocidos no unen, dividen ni reasignan otros turnos', () => {
  const documento = ejemplo()
  afirmar.equal(unirConAnterior(documento, 'desconocido'), documento)
  afirmar.equal(dividirTurno(documento, 'desconocido', 3), documento)
  afirmar.equal(asignarVoz(documento, 'desconocido'), documento)
  afirmar.equal(asignarVoz(documento, 't1', 'desconocida'), documento)
})
