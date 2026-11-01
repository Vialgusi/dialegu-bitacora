import { useEffect, useRef, useState } from 'react'
import {
  MODELOS,
  advertencias,
  aproximado,
  claveVelocidad,
  formatoDuracion,
  formatoMemoria,
  formatoTamano,
  nombreDispositivo,
  recomendar,
} from '../estado/equipo.js'
import { abrirProyecto, consultarEquipo, elegirAudio, estimar } from '../plataforma.js'

function nombreArchivo(ruta) {
  return String(ruta).split(/[\\/]/).pop()
}

export default function Inicio({ alCargar, alAbrir, alError }) {
  const [datos, cambiarDatos] = useState({
    nombre: '',
    tema: '',
    guia: '',
    tipo: 'encuentro',
    idioma: 'es',
    calidad: 'alta',
    distinguir_voces: true,
    usar_gpu: true,
  })
  const [equipo, cambiarEquipo] = useState(null)
  const [archivo, cambiarArchivo] = useState(null)
  const [estimacion, cambiarEstimacion] = useState(null)
  const [ocupado, cambiarOcupado] = useState(false)
  const formulario = useRef(null)
  const modeloElegido = useRef(false)
  useEffect(() => {
    let activo = true
    consultarEquipo()
      .then((resultado) => {
        if (!activo) return
        cambiarEquipo(resultado)
        if (!modeloElegido.current) cambiarDatos((actual) => ({ ...actual, calidad: recomendar(resultado) }))
      })
      .catch(() => {
        /* Sin datos del equipo se puede transcribir igual; solo faltan las estimaciones. */
      })
    return () => {
      activo = false
    }
  }, [])
  const conGpu = Boolean(equipo?.gpu) && datos.usar_gpu
  const recomendada = recomendar(equipo)
  // Al cambiar el archivo o las opciones, se recalcula cuánto tardará con ese audio.
  useEffect(() => {
    if (!archivo) return
    let activo = true
    cambiarEstimacion(null)
    estimar({ ...datos, usar_gpu: conGpu }, archivo)
      .then((resultado) => activo && cambiarEstimacion(resultado))
      .catch(() => activo && cambiarEstimacion({ error: true }))
    return () => {
      activo = false
    }
  }, [archivo, datos.calidad, datos.distinguir_voces, conGpu]) // eslint-disable-line react-hooks/exhaustive-deps
  const campo = (nombre) => ({
    value: datos[nombre],
    onChange: (evento) => cambiarDatos({ ...datos, [nombre]: evento.target.value }),
  })
  const preparar = () => ({
    ...datos,
    nombre: datos.nombre.trim(),
    usar_gpu: conGpu,
    guia: datos.tipo === 'encuentro' ? [] : datos.guia.split('\n').map((p) => p.trim()).filter(Boolean),
  })
  const porHora = (calidad, voces = datos.distinguir_voces) =>
    equipo?.por_hora?.[claveVelocidad(calidad, conGpu, voces)]
  const extraVoces = porHora(datos.calidad, true) - porHora(datos.calidad, false)
  async function elegir() {
    if (!formulario.current.reportValidity()) return
    cambiarOcupado(true)
    try {
      const ruta = await elegirAudio()
      if (ruta) cambiarArchivo(ruta)
    } catch (error) {
      alError(error)
    } finally {
      cambiarOcupado(false)
    }
  }
  async function transcribir() {
    if (!formulario.current.reportValidity()) return
    cambiarOcupado(true)
    try {
      await alCargar(preparar(), archivo)
    } catch (error) {
      alError(error)
    } finally {
      cambiarOcupado(false)
    }
  }
  async function abrir() {
    cambiarOcupado(true)
    try {
      const proyecto = await abrirProyecto()
      if (proyecto) alAbrir(proyecto)
    } catch (error) {
      alError(error)
    } finally {
      cambiarOcupado(false)
    }
  }
  return (
    <section className="inicio">
      <div className="introduccion">
        <p className="ceja">Un espacio para las voces</p>
        <h1>
          De la conversación
          <br />
          al registro colectivo.
        </h1>
        <p>
          Cargue el audio o video de su encuentro. Después podrá escuchar, reconocer las voces y cuidar cada palabra.
        </p>
        <div className="nota">
          01 / Prepare su sesión
          <br />
          <span>El audio se procesa en su equipo.</span>
        </div>
      </div>
      <form
        ref={formulario}
        className="panel formulario"
        onSubmit={(evento) => {
          evento.preventDefault()
          if (archivo) transcribir()
          else elegir()
        }}
      >
        <label htmlFor="nombre">
          Nombre de la sesión <span>obligatorio</span>
        </label>
        <input
          id="nombre"
          required
          pattern=".*\S.*"
          placeholder="Ej. Encuentro de la huerta"
          {...campo('nombre')}
        />
        <label htmlFor="tema">
          Tema y palabras clave <span>opcional</span>
        </label>
        <input
          id="tema"
          aria-describedby="ayuda-tema"
          placeholder="Ej. Huerta comunitaria, barrio La Esperanza, Doña Rosalba, compostaje"
          {...campo('tema')}
        />
        <small id="ayuda-tema">
          Nombres, lugares y términos que se dirán: ayudan a que el modelo los escriba bien.
        </small>
        <div className="dos-columnas">
          <div>
            <label htmlFor="tipo">Tipo</label>
            <select id="tipo" {...campo('tipo')}>
              <option value="encuentro">Encuentro o reunión</option>
              <option value="grupo_focal">Grupo focal</option>
              <option value="entrevista">Entrevista</option>
            </select>
          </div>
          <div>
            <label htmlFor="idioma">Idioma</label>
            <select id="idioma" {...campo('idioma')}>
              <option value="es">Español</option>
              <option value="auto">Detectar automáticamente</option>
              <option value="en">English</option>
              <option value="pt">Português</option>
            </select>
          </div>
        </div>
        {datos.tipo !== 'encuentro' && (
          <>
            <label htmlFor="guia">
              Guía de preguntas <span>opcional · una por línea</span>
            </label>
            <textarea id="guia" rows="4" {...campo('guia')} />
          </>
        )}

        {equipo && (
          <div className="tu-equipo" aria-label="Tu equipo">
            <p className="ceja">Tu equipo</p>
            <p>
              {equipo.procesador} · {equipo.hilos} hilos
              {equipo.memoria ? ` · ${formatoMemoria(equipo.memoria)} de memoria` : ''}
            </p>
            <p>
              {equipo.gpu
                ? `${equipo.gpu.nombre}${equipo.gpu.memoria ? ` · ${formatoMemoria(equipo.gpu.memoria)}` : ''} · compatible: transcribe varias veces más rápido`
                : 'Sin tarjeta gráfica NVIDIA compatible: se usa el procesador.'}
            </p>
          </div>
        )}

        <fieldset className="modelos">
          <legend>Modelo de transcripción</legend>
          {MODELOS.map((modelo) => {
            const info = equipo?.modelos?.[modelo.calidad]
            const hora = porHora(modelo.calidad)
            return (
              <label key={modelo.calidad} className={`modelo ${datos.calidad === modelo.calidad ? 'elegido' : ''}`}>
                <input
                  type="radio"
                  name="calidad"
                  value={modelo.calidad}
                  checked={datos.calidad === modelo.calidad}
                  onChange={() => {
                    modeloElegido.current = true
                    cambiarDatos({ ...datos, calidad: modelo.calidad })
                  }}
                />
                <span>
                  <b>{modelo.titulo}</b>
                  {modelo.calidad === recomendada && equipo && <em className="recomendado">recomendado aquí</em>}
                  <small>
                    Whisper {info?.nombre || ''}
                    {info && ` · ${formatoTamano(info.tamano)}${info.descargado ? ' · descargado' : ' · se descarga la primera vez'}`}
                  </small>
                  <small>{modelo.descripcion}</small>
                </span>
                {hora && <span className="por-hora">~{formatoDuracion(hora)}<small>por hora de audio</small></span>}
              </label>
            )
          })}
        </fieldset>

        <label className="casilla">
          <input
            type="checkbox"
            checked={datos.distinguir_voces}
            aria-describedby="ayuda-voces"
            onChange={(evento) => cambiarDatos({ ...datos, distinguir_voces: evento.target.checked })}
          />
          Distinguir voces
        </label>
        <small id="ayuda-voces">
          {datos.distinguir_voces
            ? `separa a cada persona${extraVoces > 60 ? `; en este equipo agrega unos ${formatoDuracion(extraVoces)} por hora de audio` : ''}`
            : 'todo el texto queda en una sola voz'}
        </small>
        {equipo?.gpu && (
          <label className="casilla">
            <input
              type="checkbox"
              checked={datos.usar_gpu}
              onChange={(evento) => cambiarDatos({ ...datos, usar_gpu: evento.target.checked })}
            />
            Usar la tarjeta gráfica (NVIDIA)
          </label>
        )}
        {advertencias(equipo, datos.calidad, conGpu).map((aviso) => (
          <p key={aviso} className="advertencia">
            {aviso}
          </p>
        ))}

        <details className="expectativas">
          <summary>Qué esperar de la precisión</summary>
          <ul>
            <li>La calidad del audio pesa más que el modelo: micrófono cerca, poco ruido y una persona a la vez.</li>
            <li>
              Los nombres propios, la dicción poco clara, el vocabulario o los términos regionales y los términos
              propios de un campo o tema fallan más. Escríbalos en «Tema y palabras clave» y corrija en bloque con «Buscar y reemplazar».
            </li>
            <li>Los silencios largos y el ruido pueden producir texto inventado o repetido: revise esos tramos.</li>
            <li>Las voces parecidas o que hablan a la vez se confunden: corrija con el cambio de voz de cada turno.</li>
            <li>Es una transcripción automática: siempre conviene revisarla antes de citarla o publicarla.</li>
          </ul>
        </details>

        {archivo ? (
          <div className="estimacion" role="status">
            <p>
              <b>{nombreArchivo(archivo)}</b>
              {estimacion && !estimacion.error && <> · {formatoDuracion(estimacion.duracion)} de audio</>}
            </p>
            {!estimacion && <p>Calculando cuánto tardará…</p>}
            {estimacion?.error && <p>No se pudo estimar el tiempo; puede transcribir igual.</p>}
            {estimacion && !estimacion.error && (
              <>
                <p>
                  Tardará <b>{aproximado(estimacion.segundos)}</b> {nombreDispositivo(estimacion.dispositivo)}
                  {estimacion.medido ? ', según sus transcripciones anteriores' : ' (estimado)'}. Puede seguir usando el
                  computador mientras tanto.
                </p>
                {(estimacion.descarga > 0 || estimacion.preparar_gpu) && (
                  <small>
                    Incluye
                    {estimacion.descarga > 0 && ` descargar ${formatoTamano(estimacion.descarga)}`}
                    {estimacion.descarga > 0 && estimacion.preparar_gpu && ' y'}
                    {estimacion.preparar_gpu && ' preparar la tarjeta gráfica'}, solo la primera vez.
                  </small>
                )}
              </>
            )}
            <div className="acciones">
              <button className="principal" disabled={ocupado || !datos.nombre.trim()}>
                Transcribir
              </button>
              <button type="button" disabled={ocupado} onClick={elegir}>
                Cambiar archivo
              </button>
            </div>
          </div>
        ) : (
          <div className="acciones">
            <button className="principal" disabled={ocupado || !datos.nombre.trim()}>
              Elegir audio o video
            </button>
          </div>
        )}
        <button className="enlace" type="button" disabled={ocupado} onClick={abrir}>
          Abro mi proyecto
        </button>
      </form>
    </section>
  )
}
