import ejemplo from './demo/transcripcion-demo.json'

export const esDemo = new URLSearchParams(window.location.search).get('demo') === '1'
const trabajosDemo = new Map()
let conexion
// Electron antepone «Error invoking remote method '…': Error:» a los errores del proceso principal.
const PREFIJO_IPC = /^Error invoking remote method '[^']+': (?:\w*Error: )?/

function sinPrefijoIpc(promesa) {
  return Promise.resolve(promesa).catch((error) => {
    throw new Error(String(error?.message || error).replace(PREFIJO_IPC, ''))
  })
}

// contextBridge congela window.bitacora (propiedades de solo lectura): un Proxy que devuelva otra
// función viola los invariantes de JavaScript, así que se arma una copia envuelta una sola vez.
let envuelto
function envolver(objeto) {
  return Object.fromEntries(
    Object.entries(objeto).map(([clave, valor]) => [
      clave,
      typeof valor === 'function'
        ? (...args) => sinPrefijoIpc(valor(...args))
        : valor && typeof valor === 'object'
          ? envolver(valor)
          : valor,
    ]),
  )
}
function puente() {
  if (!window.bitacora)
    throw new Error(
      'Abra la aplicación de escritorio para usar archivos y el motor, o use el modo demostración (?demo=1).',
    )
  envuelto ??= envolver(window.bitacora)
  return envuelto
}
async function motor() {
  if (!conexion)
    conexion = puente()
      .motor()
      .catch((error) => {
        conexion = null
        throw error
      })
  return conexion
}
async function peticion(ruta, opciones = {}) {
  const { url, token } = await motor()
  let respuesta
  try {
    respuesta = await fetch(`${url}${ruta}`, {
      ...opciones,
      headers: { 'X-Token': token, ...(opciones.body ? { 'Content-Type': 'application/json' } : {}) },
    })
  } catch {
    throw new Error('No se pudo conectar con el motor. Compruebe que esté disponible e inténtelo de nuevo.')
  }
  if (!respuesta.ok) {
    let mensaje = 'No se pudo completar la petición al motor.'
    try {
      const { detail } = await respuesta.json()
      mensaje = typeof detail === 'string' ? detail : 'Los datos enviados no son válidos'
    } catch {
      /* Respuesta sin JSON. */
    }
    throw new Error(mensaje)
  }
  return respuesta
}
// Equipo de la demostración: un portátil sin tarjeta gráfica, con los modelos ligero y preciso descargados.
const equipoDemo = {
  procesador: 'Procesador de demostración',
  hilos: 8,
  memoria: 16 * 2 ** 30,
  memoria_libre: 9 * 2 ** 30,
  gpu: null,
  modelos: {
    rapida: { nombre: 'small', tamano: 486212372, descargado: true },
    alta: { nombre: 'large-v3-turbo', tamano: 1621665983, descargado: true },
    maximo: { nombre: 'large-v3', tamano: 3090835702, descargado: false },
  },
  por_hora: {
    'rapida|cpu|voces': 1430, 'rapida|cpu|sin_voces': 920,
    'alta|cpu|voces': 2045, 'alta|cpu|sin_voces': 2045,
    'maximo|cpu|voces': 4070, 'maximo|cpu|sin_voces': 4070,
  },
}
export async function consultarEquipo() {
  return esDemo ? equipoDemo : (await peticion('/api/equipo')).json()
}
export async function estimar(datos, ruta) {
  if (!esDemo)
    return (
      await peticion('/api/estimacion', {
        method: 'POST',
        body: JSON.stringify({
          ruta_audio: ruta,
          calidad: datos.calidad,
          usar_gpu: datos.usar_gpu,
          distinguir_voces: datos.distinguir_voces,
        }),
      })
    ).json()
  const clave = `${datos.calidad}|cpu|${datos.distinguir_voces ? 'voces' : 'sin_voces'}`
  const proceso = Math.round((equipoDemo.por_hora[clave] * ejemplo.meta.duracion) / 3600)
  const descarga = equipoDemo.modelos[datos.calidad].descargado ? 0 : equipoDemo.modelos[datos.calidad].tamano
  return {
    duracion: ejemplo.meta.duracion,
    dispositivo: 'cpu',
    segundos: proceso + Math.round(descarga / 5e6),
    segundos_proceso: proceso,
    medido: false,
    descarga,
    preparar_gpu: false,
  }
}
export async function elegirAudio() {
  return esDemo ? ejemplo.meta.audio_original : puente().elegirAudio()
}
export async function crearTrabajo(datos) {
  if (!esDemo)
    return (await peticion('/api/trabajos', { method: 'POST', body: JSON.stringify(datos) })).json()
  const id = `demo-${Date.now()}`
  trabajosDemo.set(id, Date.now())
  return { id }
}
export async function consultarTrabajo(id) {
  if (!esDemo) return (await peticion(`/api/trabajos/${encodeURIComponent(id)}`)).json()
  const progreso = Math.min(100, Math.floor((Date.now() - trabajosDemo.get(id)) / 80))
  const etapas = ['preparando', 'descargando_modelos', 'voces', 'transcripcion', 'alineacion']
  return {
    id,
    estado: progreso === 100 ? 'listo' : 'procesando',
    etapa: etapas[Math.min(4, Math.floor(progreso / 20))],
    progreso,
    mensaje: 'Preparando la transcripción de ejemplo en este equipo.',
    error: null,
    modelo: 'large-v3-turbo',
    dispositivo: 'cpu',
    segundos_restantes: Math.round(((100 - progreso) * 8) / 100),
  }
}
export async function cancelarTrabajo(id) {
  if (esDemo) {
    trabajosDemo.delete(id)
    return
  }
  await peticion(`/api/trabajos/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
export async function obtenerResultado(id) {
  return esDemo
    ? structuredClone(ejemplo)
    : (await peticion(`/api/trabajos/${encodeURIComponent(id)}/resultado`)).json()
}
export async function obtenerAudio(id) {
  if (esDemo) return 'demo/huerta.mp3'
  const { url, token } = await motor()
  return `${url}/api/trabajos/${encodeURIComponent(id)}/audio?token=${encodeURIComponent(token)}`
}
export async function abrirProyecto() {
  return esDemo
    ? { ruta: 'demostracion.bitacora', transcripcion: structuredClone(ejemplo), urlAudio: 'demo/huerta.mp3' }
    : puente().abrirProyecto()
}
export async function guardarProyecto(opciones) {
  return esDemo ? 'demostracion.bitacora' : puente().guardarProyecto(opciones)
}
export async function exportar(transcripcion, formato) {
  if (esDemo) return `demostracion.${formato}`
  const respuesta = await peticion('/api/exportar', {
    method: 'POST',
    body: JSON.stringify({ transcripcion, formato }),
  })
  const datos = await respuesta.arrayBuffer()
  return puente().guardarArchivo({
    nombreSugerido: transcripcion.meta.nombre,
    datos,
    extension: formato.replace('informe-', ''),
  })
}
