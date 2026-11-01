import { useEffect, useRef, useState } from 'react'
import { aproximado, nombreDispositivo } from '../estado/equipo.js'
import { cancelarTrabajo, consultarTrabajo, obtenerAudio, obtenerResultado } from '../plataforma.js'
const etapas = {
  preparando: 'Preparando el audio',
  descargando_modelos: 'Descargando modelos (solo la primera vez)',
  voces: 'Reconociendo voces',
  transcripcion: 'Transcribiendo',
  alineacion: 'Ordenando por turnos',
  listo: 'Transcripción lista',
}
export default function Procesando({ id, alListo, alCancelar, alError }) {
  const [avance, cambiarAvance] = useState({ progreso: 0, etapa: 'preparando', mensaje: '' })
  const [cancelando, cambiarCancelando] = useState(false)
  const cancelado = useRef(false)
  useEffect(() => {
    let activo = true
    let reloj
    async function consultar() {
      try {
        const estado = await consultarTrabajo(id)
        if (!activo || cancelado.current) return
        cambiarAvance(estado)
        if (estado.estado === 'error') throw new Error(estado.error || estado.mensaje)
        if (estado.estado === 'cancelado') {
          alCancelar()
          return
        }
        if (estado.estado === 'listo') {
          const transcripcion = await obtenerResultado(id)
          const urlAudio = await obtenerAudio(id)
          if (activo && !cancelado.current) alListo({ id, transcripcion, urlAudio, ruta: null })
          return
        }
        reloj = setTimeout(consultar, 1000)
      } catch (error) {
        if (activo && !cancelado.current) alError(error)
      }
    }
    consultar()
    return () => {
      activo = false
      clearTimeout(reloj)
    }
  }, [id, alListo, alCancelar, alError])
  async function cancelar() {
    cancelado.current = true
    cambiarCancelando(true)
    try {
      await cancelarTrabajo(id)
      alCancelar()
    } catch (error) {
      alError(error)
    }
  }
  return (
    <section className="panel centrado">
      <p className="ceja">Del audio a las palabras</p>
      <h1>{etapas[avance.etapa] || 'Esperando el turno'}</h1>
      <div className="avance">
        <label htmlFor="progreso">
          Avance del procesamiento <strong>{avance.progreso}%</strong>
        </label>
        <progress id="progreso" value={avance.progreso} max="100" />
      </div>
      <p role="status">{avance.mensaje}</p>
      {avance.modelo && (
        <p className="detalle-proceso">
          Whisper {avance.modelo}
          {avance.dispositivo && ` · ${nombreDispositivo(avance.dispositivo)}`}
          {avance.segundos_restantes != null && ` · quedan ${aproximado(avance.segundos_restantes)}`}
          <br />
          Puede seguir usando el computador: el proceso corre con prioridad baja.
        </p>
      )}
      <button disabled={cancelando} onClick={cancelar}>
        {cancelando ? 'Cancelando…' : 'Cancelar'}
      </button>
    </section>
  )
}
