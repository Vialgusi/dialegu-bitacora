// Operaciones puras: los identificadores existentes se conservan.
export function recalcularVoces(documento) {
  const turnos = [...documento.turnos].sort((a, b) => a.inicio - b.inicio)
  const ids = [...new Set(turnos.map((turno) => turno.voz))]
  return {
    ...documento,
    turnos,
    voces: ids.map((id) => ({
      ...documento.voces.find((voz) => voz.id === id),
      id,
      segundos: turnos
        .filter((turno) => turno.voz === id)
        .reduce((suma, turno) => suma + Math.max(0, turno.fin - turno.inicio), 0),
    })),
  }
}
function siguienteId(elementos, prefijo) {
  let numero = 1
  while (elementos.some((elemento) => elemento.id === `${prefijo}${numero}`)) numero++
  return `${prefijo}${numero}`
}
export function renombrarVoz(documento, id, nombre) {
  return recalcularVoces({
    ...documento,
    voces: documento.voces.map((voz) => (voz.id === id ? { ...voz, nombre } : voz)),
  })
}
export function unirVoces(documento, origen, destino) {
  if (origen === destino || ![origen, destino].every((id) => documento.voces.some((voz) => voz.id === id)))
    return documento
  return recalcularVoces({
    ...documento,
    meta: documento.meta.entrevistadora === origen
      ? { ...documento.meta, entrevistadora: destino }
      : documento.meta,
    voces: documento.voces.filter((voz) => voz.id !== origen),
    turnos: documento.turnos.map((turno) => turno.voz === origen ? { ...turno, voz: destino } : turno),
  })
}
export function avisoVoces(documento) {
  if (documento.meta.distinguir_voces === false || documento.voces.length !== 1 || !(documento.meta.duracion >= 180))
    return null
  const minutos = Math.round(documento.meta.duracion / 60)
  return `Solo se detectó una voz en ${minutos} minutos. Si en el audio hablan varias personas, vuelva a transcribir indicando cuántas son en «¿Cuántas personas hablan?».`
}
export function asignarVoz(documento, idTurno, idVoz = null) {
  if (!documento.turnos.some((turno) => turno.id === idTurno)) return documento
  let voces = documento.voces
  if (!idVoz) {
    idVoz = siguienteId(voces, 'v')
    let numero = 1
    while (voces.some((voz) => voz.nombre === `Voz ${numero}`)) numero++
    voces = [...voces, { id: idVoz, nombre: `Voz ${numero}`, segundos: 0 }]
  }
  if (!voces.some((voz) => voz.id === idVoz)) return documento
  return recalcularVoces({
    ...documento,
    voces,
    turnos: documento.turnos.map((turno) => (turno.id === idTurno ? { ...turno, voz: idVoz } : turno)),
  })
}
export function editarTexto(documento, id, texto) {
  return recalcularVoces({
    ...documento,
    turnos: documento.turnos.map((turno) => (turno.id === id ? { ...turno, texto, palabras: [] } : turno)),
  })
}
export function unirConAnterior(documento, id) {
  const indice = documento.turnos.findIndex((turno) => turno.id === id)
  if (indice <= 0) return documento
  const anterior = documento.turnos[indice - 1]
  const actual = documento.turnos[indice]
  const unido = {
    ...anterior,
    fin: Math.max(anterior.fin, actual.fin),
    ...((anterior.cita || actual.cita) ? { cita: true } : {}),
    texto: `${anterior.texto.trimEnd()} ${actual.texto.trimStart()}`,
    palabras:
      anterior.palabras?.length && actual.palabras?.length ? [...anterior.palabras, ...actual.palabras] : [],
  }
  return recalcularVoces({
    ...documento,
    turnos: [...documento.turnos.slice(0, indice - 1), unido, ...documento.turnos.slice(indice + 1)],
  })
}
export function dividirTurno(documento, id, cursor) {
  const indice = documento.turnos.findIndex((turno) => turno.id === id)
  if (indice < 0) return documento
  const turno = documento.turnos[indice]
  if (
    !Number.isInteger(cursor) ||
    cursor <= 0 ||
    cursor >= turno.texto.length ||
    !turno.texto.slice(0, cursor).trim() ||
    !turno.texto.slice(cursor).trim()
  )
    return documento
  const palabras = turno.palabras || []
  let posicion = 0
  let cantidad = 0
  for (const palabra of palabras) {
    const comienzo = turno.texto.indexOf(palabra.texto.trim(), posicion)
    if (comienzo < 0) break
    const fin = comienzo + palabra.texto.trim().length
    if (fin > cursor) break
    posicion = fin
    cantidad++
  }
  const corte = palabras.length
    ? cantidad
      ? palabras[cantidad - 1].fin
      : turno.inicio
    : turno.inicio + ((turno.fin - turno.inicio) * cursor) / turno.texto.length
  if (corte <= turno.inicio || corte >= turno.fin) return documento
  const primero = {
    ...turno,
    fin: corte,
    texto: turno.texto.slice(0, cursor).trimEnd(),
    palabras: palabras.slice(0, cantidad),
  }
  const segundo = {
    ...turno,
    id: siguienteId(documento.turnos, 't'),
    inicio: corte,
    texto: turno.texto.slice(cursor).trimStart(),
    palabras: palabras.slice(cantidad),
  }
  return recalcularVoces({
    ...documento,
    turnos: [...documento.turnos.slice(0, indice), primero, segundo, ...documento.turnos.slice(indice + 1)],
  })
}
export function formatoTiempo(segundos) {
  const total = Math.max(0, Math.floor(Number(segundos) || 0))
  const horas = Math.floor(total / 3600)
  const minutos = Math.floor((total % 3600) / 60)
  const resto = String(total % 60).padStart(2, '0')
  return horas
    ? `${horas}:${String(minutos).padStart(2, '0')}:${resto}`
    : `${String(minutos).padStart(2, '0')}:${resto}`
}

export function normalizarDocumento(documento) {
  return recalcularVoces({
    ...documento,
    meta: { tipo: 'encuentro', momentos: [], guia: [], entrevistadora: null, ...documento.meta },
  })
}
export function marcarMomento(documento, inicio) {
  const momentos = documento.meta.momentos || []
  const guia = documento.meta.guia || []
  const pregunta = ['grupo_focal', 'entrevista'].includes(documento.meta.tipo)
  const indice = momentos.filter((m) => m.tipo === 'pregunta').length
  const momento = {
    id: siguienteId(momentos, 'm'),
    inicio,
    titulo: pregunta ? (guia[indice] || `Pregunta ${indice + 1}`) : `Momento ${momentos.length + 1}`,
    tipo: pregunta ? 'pregunta' : 'momento',
  }
  return {
    ...documento,
    meta: { ...documento.meta, momentos: [...momentos, momento].sort((a, b) => a.inicio - b.inicio) },
  }
}
export function editarMomento(documento, id, cambios) {
  const momentos = (documento.meta.momentos || [])
    .flatMap((m) => m.id === id ? (cambios === null ? [] : [{ ...m, ...cambios }]) : [m])
    .sort((a, b) => a.inicio - b.inicio)
  return { ...documento, meta: { ...documento.meta, momentos } }
}
export function alternarCita(documento, id) {
  return {
    ...documento,
    turnos: documento.turnos.map((t) => t.id === id ? { ...t, cita: !t.cita } : t),
  }
}

// Palabra (con tiempos) que ocupa la posición `posicion` del texto; null si el turno fue editado y ya no las tiene.
function palabraEnPosicion(turno, posicion) {
  let desde = 0
  let ultima = null
  for (const palabra of turno.palabras || []) {
    const limpia = palabra.texto.trim()
    const comienzo = turno.texto.indexOf(limpia, desde)
    if (comienzo < 0) return ultima
    if (posicion < comienzo + limpia.length) return palabra
    desde = comienzo + limpia.length
    ultima = palabra
  }
  return ultima
}
function tiempoProporcional(turno, posicion) {
  const largo = turno.texto.length || 1
  return turno.inicio + ((turno.fin - turno.inicio) * Math.min(Math.max(posicion, 0), largo)) / largo
}
// Momento del audio donde se dice el texto en `posicion`: por palabra si hay tiempos; si no, estimado.
export function tiempoEnPosicion(turno, posicion) {
  return palabraEnPosicion(turno, posicion)?.inicio ?? tiempoProporcional(turno, posicion)
}
export function citarFragmento(documento, idTurno, desde, hasta) {
  const turno = documento.turnos.find((t) => t.id === idTurno)
  if (!turno || hasta <= desde) return documento
  const crudo = turno.texto.slice(desde, hasta)
  const texto = crudo.trim()
  if (!texto) return documento
  const inicioReal = desde + crudo.indexOf(texto)
  const finReal = inicioReal + texto.length
  const citas = documento.citas || []
  if (citas.some((c) => c.turno === idTurno && c.texto === texto)) return documento
  const cita = {
    id: siguienteId(citas, 'c'),
    turno: idTurno,
    voz: turno.voz,
    inicio: tiempoEnPosicion(turno, inicioReal),
    fin: palabraEnPosicion(turno, finReal - 1)?.fin ?? tiempoProporcional(turno, finReal),
    texto,
  }
  return { ...documento, citas: [...citas, cita].sort((a, b) => a.inicio - b.inicio) }
}
export function quitarCita(documento, id) {
  return { ...documento, citas: (documento.citas || []).filter((c) => c.id !== id) }
}
// Citas para el panel: turnos con estrella y fragmentos, en orden de aparición.
export function listarCitas(documento) {
  const nombres = Object.fromEntries(documento.voces.map((v) => [v.id, v.nombre]))
  const turnos = Object.fromEntries(documento.turnos.map((t) => [t.id, t]))
  return [
    ...documento.turnos.filter((t) => t.cita).map((t) => ({ id: t.id, tipo: 'turno', turno: t.id, voz: t.voz, inicio: t.inicio, texto: t.texto })),
    ...(documento.citas || []).map((c) => ({ ...c, tipo: 'fragmento', voz: turnos[c.turno]?.voz ?? c.voz })),
  ]
    .map((c) => ({ ...c, nombre: nombres[c.voz] || 'Voz sin nombre' }))
    .sort((a, b) => a.inicio - b.inicio)
}

function patronBusqueda(buscar) {
  return new RegExp(buscar.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'giu')
}
export function contarCoincidencias(documento, buscar) {
  if (!buscar) return 0
  const patron = patronBusqueda(buscar)
  return documento.turnos.reduce((suma, t) => suma + (t.texto.match(patron)?.length || 0), 0)
}
// Reemplaza en todos los turnos, sin distinguir mayúsculas. Si se busca una sola palabra, los tiempos por
// palabra se conservan (se corrige también en ellas); si se buscan varias, ese turno pierde los tiempos.
export function reemplazarTodo(documento, buscar, reemplazo) {
  if (!buscar) return documento
  const patron = patronBusqueda(buscar)
  const unaPalabra = !/\s/.test(buscar.trim())
  let cambio = false
  const turnos = documento.turnos.map((t) => {
    if (!t.texto.match(patron)) return t
    cambio = true
    return {
      ...t,
      texto: t.texto.replace(patron, () => reemplazo),
      palabras: unaPalabra
        ? (t.palabras || []).map((p) => ({ ...p, texto: p.texto.replace(patron, () => reemplazo) }))
        : [],
    }
  })
  return cambio ? recalcularVoces({ ...documento, turnos }) : documento
}
