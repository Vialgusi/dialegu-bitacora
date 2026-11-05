// Cómo contar a la persona qué modelo usa, qué implica y cuánto tardará en su equipo.
export function normalizarPersonas(valor, distinguirVoces) {
  if (distinguirVoces === false || !['string', 'number'].includes(typeof valor) || String(valor).trim() === '')
    return null
  const personas = Number(valor)
  return Number.isInteger(personas) && personas >= 1 && personas <= 12 ? personas : null
}

export const MODELOS = [
  {
    calidad: 'rapida',
    titulo: 'Ligero',
    descripcion: 'Bien con audio claro y una persona a la vez. Para pruebas o equipos modestos.',
    memoria: 2 * 2 ** 30,
  },
  {
    calidad: 'alta',
    titulo: 'Preciso',
    descripcion: 'Muy buena precisión en conversaciones reales. La opción para casi todo.',
    memoria: 4 * 2 ** 30,
  },
  {
    calidad: 'maximo',
    titulo: 'Máximo',
    descripcion: 'Lo más fiel con ruido, acentos y términos poco comunes. Pensado para equipos con tarjeta gráfica.',
    memoria: 6 * 2 ** 30,
  },
]

export function formatoTamano(bytes) {
  if (!bytes) return '0 MB'
  return bytes >= 1e9
    ? `${(bytes / 1e9).toLocaleString('es', { maximumFractionDigits: 1 })} GB`
    : `${Math.max(1, Math.round(bytes / 1e6))} MB`
}

// La memoria se cuenta en binario (16 GB de RAM son 16 × 2³⁰ bytes); las descargas, en decimal.
export function formatoMemoria(bytes) {
  return `${Math.round((bytes || 0) / 2 ** 30)} GB`
}

// Frase para «Tardará …»: «menos de 1 min», «alrededor de 1 min», «unos 18 min».
export function aproximado(segundos) {
  const texto = formatoDuracion(segundos)
  if (texto === 'menos de 1 min') return texto
  return texto === '1 min' ? 'alrededor de 1 min' : `unos ${texto}`
}

// «18 min», «1 h 05 min», «menos de 1 min».
export function formatoDuracion(segundos) {
  const minutos = Math.round((segundos || 0) / 60)
  if (minutos < 1) return 'menos de 1 min'
  if (minutos < 60) return `${minutos} min`
  return `${Math.floor(minutos / 60)} h ${String(minutos % 60).padStart(2, '0')} min`
}

export function claveVelocidad(calidad, conGpu, voces) {
  return `${calidad}|${conGpu ? 'cuda' : 'cpu'}|${voces ? 'voces' : 'sin_voces'}`
}

// Con tarjeta o un procesador holgado, «Preciso»; con poca memoria o pocos hilos, «Ligero».
export function recomendar(equipo) {
  if (!equipo) return 'alta'
  if (equipo.gpu) return 'alta'
  const memoria = equipo.memoria ?? Infinity
  return equipo.hilos >= 8 && memoria >= 8 * 2 ** 30 ? 'alta' : 'rapida'
}

export function advertencias(equipo, calidad, conGpu) {
  if (!equipo) return []
  const modelo = MODELOS.find((m) => m.calidad === calidad)
  const lista = []
  if (equipo.memoria_libre != null && modelo && equipo.memoria_libre < modelo.memoria)
    lista.push(
      `Este modelo necesita unos ${formatoMemoria(modelo.memoria)} de memoria libre y ahora hay ${formatoMemoria(equipo.memoria_libre)}. Cierre otros programas o elija un modelo más liviano.`,
    )
  if (calidad === 'maximo' && !conGpu)
    lista.push('Sin tarjeta gráfica, el modelo Máximo es muy lento: puede tardar más que el propio audio.')
  if (conGpu && equipo.gpu && !equipo.gpu.librerias)
    lista.push('La primera vez se descargan unos 570 MB de librerías de NVIDIA para usar la tarjeta.')
  else if (conGpu && equipo.gpu && !equipo.gpu.preparada)
    lista.push('La primera vez la tarjeta gráfica se prepara durante unos minutos; después ya no.')
  return lista
}

export function nombreDispositivo(dispositivo) {
  return dispositivo === 'gpu' ? 'en la tarjeta gráfica' : 'en el procesador'
}
