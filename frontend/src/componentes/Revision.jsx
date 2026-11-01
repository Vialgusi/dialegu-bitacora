import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  alternarCita,
  citarFragmento,
  contarCoincidencias,
  editarMomento,
  listarCitas,
  quitarCita,
  reemplazarTodo,
  tiempoEnPosicion,
  marcarMomento,
  normalizarDocumento,
  asignarVoz,
  dividirTurno,
  editarTexto,
  formatoTiempo,
  renombrarVoz,
  unirConAnterior,
} from '../estado/transcripcion.js'
import { formatoDuracion, nombreDispositivo } from '../estado/equipo.js'
import { esDemo, exportar, guardarProyecto } from '../plataforma.js'

const colores = ['#236454', '#94552c', '#365d9d', '#8d3767', '#606b23', '#8a432f', '#536279', '#6e4994']
const tipos = { encuentro: 'Encuentro o reunión', grupo_focal: 'Grupo focal', entrevista: 'Entrevista' }

function Turno({
  turno,
  voces,
  indice,
  color,
  escuchando,
  seguir,
  sinAudio,
  alEscuchar,
  alEscribir,
  alEditar,
  alAsignar,
  alUnir,
  alDividir,
  alCita,
  alSeleccionar,
  seleccionado,
}) {
  const texto = useRef(null)
  const tarjeta = useRef(null)
  const cursor = useRef(0)
  useLayoutEffect(() => {
    texto.current.style.height = 'auto'
    texto.current.style.height = `${texto.current.scrollHeight}px`
  }, [turno.texto])
  useEffect(() => {
    if (escuchando && seguir && !tarjeta.current.contains(document.activeElement))
      tarjeta.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [escuchando, seguir])
  return (
    <article onFocusCapture={alSeleccionar} onClick={alSeleccionar} ref={tarjeta} className={`turno ${seleccionado ? 'seleccionado' : ''} ${escuchando ? 'escuchando' : ''}`} style={{ '--voz': color }}>
      <div className="turno-cabecera">
        <button
          className="hora"
          disabled={sinAudio}
          aria-label={`Escuchar turno ${indice + 1} desde ${formatoTiempo(turno.inicio)}`}
          onClick={() => alEscuchar(turno.inicio)}
        >
          {formatoTiempo(turno.inicio)}
        </button>
        <label className="solo-lectores" htmlFor={`voz-${turno.id}`}>
          Voz del turno {indice + 1}
        </label>
        <select
          id={`voz-${turno.id}`}
          value={turno.voz}
          onChange={(evento) => alAsignar(evento.target.value === 'otra' ? null : evento.target.value)}
        >
          {voces.map((voz) => (
            <option key={voz.id} value={voz.id}>
              {voz.nombre || 'Voz sin nombre'}
            </option>
          ))}
          <option value="otra">Otra voz…</option>
        </select>
        <span className="numero-turno">{String(indice + 1).padStart(2, '0')}</span>
      </div>
      <label className="solo-lectores" htmlFor={`texto-${turno.id}`}>
        Texto del turno {indice + 1}
      </label>
      <textarea
        id={`texto-${turno.id}`}
        ref={texto}
        rows="1"
        value={turno.texto}
        data-turno={turno.id}
        onSelect={(evento) => {
          cursor.current = evento.target.selectionStart
        }}
        onClick={(evento) => {
          // Alt+clic en una palabra: el audio salta a ese punto.
          if (evento.altKey && !sinAudio) alEscuchar(tiempoEnPosicion(turno, evento.target.selectionStart))
        }}
        onChange={(evento) => {
          cursor.current = evento.target.selectionStart
          alEscribir()
          alEditar(evento.target.value)
        }}
      />
      <div className="turno-acciones">
        <button
          aria-pressed={Boolean(turno.cita)}
          aria-label={`Destaco como cita el turno ${indice + 1}`}
          title="Ctrl+Q cita el turno, o solo el texto seleccionado"
          onClick={alCita}
        >
          {turno.cita ? '★' : '☆'} Cita
        </button>
        <button disabled={indice === 0} onClick={alUnir}>
          Uno con el anterior
        </button>
        <button onClick={() => alDividir(cursor.current)} title="Ctrl+Enter">
          Divido aquí
        </button>
      </div>
    </article>
  )
}

export default function Revision({ proyecto, alInicio }) {
  // `version` cuenta las ediciones; comparar números evita serializar el documento en cada tecla,
  // lo que con una hora de audio (miles de palabras con tiempos) vuelve lenta la escritura.
  const [historial, cambiarHistorial] = useState(() => ({
    actual: normalizarDocumento(proyecto.transcripcion),
    anteriores: [],
    version: 0,
  }))
  const documento = historial.actual
  const [seleccion, cambiarSeleccion] = useState(proyecto.transcripcion.turnos[0]?.id || null)
  const seleccionado = documento.turnos.find((t) => t.id === seleccion)
  const [versionGuardada, cambiarVersionGuardada] = useState(proyecto.ruta ? 0 : null)
  const [ruta, cambiarRuta] = useState(proyecto.ruta || null)
  const [mensaje, cambiarMensaje] = useState('')
  const [error, cambiarError] = useState('')
  const [ocupado, cambiarOcupado] = useState(false)
  const bloqueo = useRef(false)
  const [menu, cambiarMenu] = useState(false)
  const [tiempo, cambiarTiempo] = useState(null)
  const [reproduciendo, cambiarReproduciendo] = useState(false)
  const [sinAudio, cambiarSinAudio] = useState(!proyecto.urlAudio)
  const [duracion, cambiarDuracion] = useState(proyecto.transcripcion.meta?.duracion || 0)
  const [velocidad, cambiarVelocidad] = useState(1)
  const [seguir, cambiarSeguir] = useState(true)
  const [pausarAlEscribir, cambiarPausarAlEscribir] = useState(true)
  const [buscar, cambiarBuscar] = useState('')
  const [reemplazo, cambiarReemplazo] = useState('')
  const audio = useRef(null)
  const retroceder = useRef(false)
  const campoBuscar = useRef(null)
  const coincidencias = contarCoincidencias(documento, buscar)
  const citas = listarCitas(documento)
  const cambios = historial.version !== versionGuardada
  const total = documento.voces.reduce((suma, voz) => suma + voz.segundos, 0)
  const turnoActivo =
    !reproduciendo || tiempo === null
      ? null
      : documento.turnos.find((turno) => tiempo >= turno.inicio && tiempo < turno.fin)?.id
  function editar(operacion) {
    cambiarHistorial((anterior) => {
      const actual = operacion(anterior.actual)
      if (actual === anterior.actual) return anterior
      return {
        actual,
        anteriores: [...anterior.anteriores, anterior.actual].slice(-50),
        version: anterior.version + 1,
      }
    })
  }
  function deshacer() {
    cambiarHistorial((anterior) =>
      anterior.anteriores.length
        ? {
            actual: anterior.anteriores.at(-1),
            anteriores: anterior.anteriores.slice(0, -1),
            version: anterior.version + 1,
          }
        : anterior,
    )
  }
  async function guardar() {
    if (bloqueo.current) return
    bloqueo.current = true
    cambiarOcupado(true)
    cambiarError('')
    cambiarMensaje('')
    try {
      const destino = await guardarProyecto({ transcripcion: documento, rutaProyecto: ruta })
      if (destino) {
        cambiarRuta(destino)
        cambiarVersionGuardada(historial.version)
        cambiarMensaje(
          esDemo ? 'Demostración: guardado simulado; no se creó un archivo.' : 'Proyecto guardado.',
        )
      }
    } catch (error) {
      cambiarError(error.message)
    } finally {
      bloqueo.current = false
      cambiarOcupado(false)
    }
  }
  async function descargar(formato) {
    if (bloqueo.current) return
    bloqueo.current = true
    cambiarMenu(false)
    cambiarOcupado(true)
    cambiarError('')
    cambiarMensaje('')
    try {
      const resultado = await exportar(documento, formato)
      if (resultado)
        cambiarMensaje(
          esDemo ? 'Demostración: exportación simulada; no se creó un archivo.' : 'Archivo exportado.',
        )
    } catch (error) {
      cambiarError(error.message)
    } finally {
      bloqueo.current = false
      cambiarOcupado(false)
    }
  }
  async function escuchar(inicio) {
    try {
      retroceder.current = false
      audio.current.currentTime = inicio
      await audio.current.play()
    } catch {
      cambiarError('No se pudo reproducir el audio. Compruebe que el archivo esté disponible.')
    }
  }
  function alternarAudio() {
    if (sinAudio) return
    const reproductor = audio.current
    if (!reproductor.paused) return reproductor.pause()
    // Tras pausar por escribir, se retoma 2 s antes para no perder el hilo de la frase.
    if (retroceder.current) reproductor.currentTime = Math.max(0, reproductor.currentTime - 2)
    retroceder.current = false
    reproductor
      .play()
      .catch(() => cambiarError('No se pudo reproducir el audio. Compruebe que el archivo esté disponible.'))
  }
  function mover(segundos) {
    if (sinAudio) return
    const reproductor = audio.current
    const final = Number.isFinite(reproductor.duration) ? reproductor.duration : duracion
    reproductor.currentTime = Math.min(Math.max(0, reproductor.currentTime + segundos), final)
    cambiarTiempo(reproductor.currentTime)
  }
  function alEscribir() {
    if (pausarAlEscribir && audio.current && !audio.current.paused) {
      audio.current.pause()
      retroceder.current = true
    }
  }
  // Selecciona la siguiente coincidencia de la búsqueda, empezando después del cursor en el turno actual.
  function irASiguiente() {
    if (!coincidencias) return
    const patron = buscar.toLowerCase()
    const desde = Math.max(0, documento.turnos.findIndex((t) => t.id === seleccion))
    const activo = document.activeElement
    const desdeCursor = activo?.dataset?.turno === documento.turnos[desde]?.id ? activo.selectionEnd : 0
    for (let paso = 0; paso <= documento.turnos.length; paso++) {
      const turno = documento.turnos[(desde + paso) % documento.turnos.length]
      const posicion = turno.texto.toLowerCase().indexOf(patron, paso === 0 ? desdeCursor : 0)
      if (posicion >= 0) {
        cambiarSeleccion(turno.id)
        const campo = document.getElementById(`texto-${turno.id}`)
        campo.focus()
        campo.setSelectionRange(posicion, posicion + buscar.length)
        return
      }
    }
  }
  function citarDesdeTeclado() {
    const campo = document.activeElement
    const idTurno = campo?.dataset?.turno
    if (idTurno && campo.selectionEnd > campo.selectionStart) {
      const citado = citarFragmento(documento, idTurno, campo.selectionStart, campo.selectionEnd)
      if (citado !== documento) {
        editar(() => citado)
        cambiarMensaje('Fragmento agregado a las citas.')
      }
      return
    }
    const destino = idTurno || seleccion
    if (destino) editar((actual) => alternarCita(actual, destino))
  }
  function dividirDesdeTeclado() {
    const campo = document.activeElement
    const idTurno = campo?.dataset?.turno
    if (!idTurno) return
    const dividido = dividirTurno(documento, idTurno, campo.selectionStart)
    if (dividido === documento) cambiarMensaje('Coloque el cursor entre dos palabras dentro del turno.')
    else editar(() => dividido)
  }
  useEffect(() => {
    function teclado(evento) {
      // Alt+← / Alt+→: 5 s atrás o adelante (Ctrl+flechas se reservan para moverse entre palabras).
      if (evento.altKey && !evento.ctrlKey && (evento.key === 'ArrowLeft' || evento.key === 'ArrowRight')) {
        evento.preventDefault()
        mover(evento.key === 'ArrowLeft' ? -5 : 5)
        return
      }
      if (!(evento.ctrlKey || evento.metaKey) || evento.altKey) return
      const tecla = evento.key.toLowerCase()
      const atajos = {
        ' ': alternarAudio,
        q: citarDesdeTeclado,
        enter: dividirDesdeTeclado,
        f: () => {
          campoBuscar.current?.focus()
          campoBuscar.current?.select()
        },
      }
      if (atajos[tecla]) {
        evento.preventDefault()
        atajos[tecla]()
        return
      }
      if (tecla === 's') {
        evento.preventDefault()
        void guardar()
      }
      if (
        tecla === 'z' &&
        !evento.shiftKey &&
        !evento.target.closest('input, textarea, select, [contenteditable="true"]')
      ) {
        evento.preventDefault()
        deshacer()
      }
    }
    function salir(evento) {
      if (cambios) {
        evento.preventDefault()
        evento.returnValue = ''
      }
    }
    window.addEventListener('keydown', teclado)
    window.addEventListener('beforeunload', salir)
    return () => {
      window.removeEventListener('keydown', teclado)
      window.removeEventListener('beforeunload', salir)
    }
  })
  return (
    <section className="revision">
      <header className="revision-cabecera">
        <div>

          <h1>{documento.meta.nombre}</h1>
          <p>
            {tipos[documento.meta.tipo] || documento.meta.tipo} · {formatoTiempo(documento.meta.duracion)} ·{' '}
            {documento.voces.length} voces
          </p>
          {documento.meta.modelo && (
            <p className="ficha-tecnica" title="Se incluye como nota metodológica en el informe">
              Transcrito con Whisper {documento.meta.modelo}
              {documento.meta.dispositivo && ` ${nombreDispositivo(documento.meta.dispositivo)}`}
              {documento.meta.segundos_proceso ? ` · ${formatoDuracion(documento.meta.segundos_proceso)} de proceso` : ''}
              {documento.meta.distinguir_voces === false ? ' · sin distinguir voces' : ''}
            </p>
          )}
        </div>
        <button
          disabled={ocupado}
          onClick={() => {
            if (
              !cambios ||
              window.confirm('Hay cambios sin guardar. ¿Desea iniciar una nueva sesión y descartarlos?')
            )
              alInicio()
          }}
        >
          Inicio otra sesión
        </button>
      </header>
      <div className="herramientas">
        <button
          disabled={!historial.anteriores.length}
          onClick={deshacer}
          title="Ctrl+Z fuera de los campos de texto"
        >
          Deshago el cambio
        </button>
        <span className="estado-guardado">{cambios ? 'Cambios sin guardar' : 'Proyecto guardado'}</span>
        <button className="principal" disabled={ocupado} onClick={guardar} title="Ctrl+S">
          Guardo mi proyecto
        </button>
        <div className="exportacion">
          <button
            disabled={ocupado}
            aria-expanded={menu}
            aria-controls="formatos"
            onClick={() => cambiarMenu(!menu)}
          >
            Exporto mi informe ▾
          </button>
          {menu && (
            <div
              id="formatos"
              className="menu"
              onKeyDown={(evento) => {
                if (evento.key === 'Escape') cambiarMenu(false)
              }}
            >
              {[
                ['informe-docx', 'Informe (Word)'],
                ['informe-pdf', 'Informe (PDF)'],
                ['informe-md', 'Informe (Markdown)'],
              ].map(([formato, nombre]) => <button key={formato} onClick={() => descargar(formato)}>{nombre}</button>)}
              <details><summary>Otros formatos</summary>
              {[
                ['md', 'Markdown'],
                ['pdf', 'PDF'],
                ['srt', 'Subtítulos (SRT)'],
                ['txt', 'Texto'],
              ].map(([formato, nombre]) => (
                <button key={formato} onClick={() => descargar(formato)}>
                  {nombre}
                </button>
              ))}
              </details>
            </div>
          )}
        </div>
      </div>
      <div className="buscar" role="search">
        <label className="solo-lectores" htmlFor="buscar">
          Buscar en la transcripción
        </label>
        <input
          id="buscar"
          ref={campoBuscar}
          placeholder="Buscar (Ctrl+F)"
          value={buscar}
          onChange={(evento) => cambiarBuscar(evento.target.value)}
          onKeyDown={(evento) => {
            if (evento.key === 'Enter') {
              evento.preventDefault()
              irASiguiente()
            }
          }}
        />
        <label className="solo-lectores" htmlFor="reemplazo">
          Reemplazar por
        </label>
        <input
          id="reemplazo"
          placeholder="Reemplazar por"
          value={reemplazo}
          onChange={(evento) => cambiarReemplazo(evento.target.value)}
        />
        <span className="coincidencias" aria-live="polite">
          {buscar ? `${coincidencias} ${coincidencias === 1 ? 'coincidencia' : 'coincidencias'}` : ''}
        </span>
        <button disabled={!coincidencias} onClick={irASiguiente}>
          Siguiente
        </button>
        <button
          disabled={!coincidencias}
          onClick={() => {
            editar((actual) => reemplazarTodo(actual, buscar, reemplazo))
            cambiarMensaje(`${coincidencias} ${coincidencias === 1 ? 'reemplazo hecho' : 'reemplazos hechos'}.`)
          }}
        >
          Reemplazo todo
        </button>
      </div>
      {mensaje && (
        <p className="aviso" role="status">
          {mensaje}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <section className="momentos panel" aria-labelledby="titulo-momentos">
        <h2 id="titulo-momentos">Momentos</h2>
        <label htmlFor="turno-seleccionado">Turno actual</label>
        <select id="turno-seleccionado" value={seleccionado?.id || ''} onChange={(e) => cambiarSeleccion(e.target.value)}>
          {!seleccionado && <option value="">Selecciono un turno</option>}
          {documento.turnos.map((t, i) => <option key={t.id} value={t.id}>{i + 1} · {formatoTiempo(t.inicio)} · {t.texto.slice(0, 55)}</option>)}
        </select>
        <button disabled={!seleccionado} onClick={() => editar((d) => marcarMomento(d, seleccionado.inicio))}>Agrego un momento aquí</button>
        <ol>
          {documento.meta.momentos.map((m) => <li key={m.id}>
            <time>{formatoTiempo(m.inicio)}</time>
            <input aria-label={`Título de ${m.id}`} value={m.titulo} onChange={(e) => editar((d) => editarMomento(d, m.id, { titulo: e.target.value }))} />
            <button disabled={!seleccionado} onClick={() => editar((d) => editarMomento(d, m.id, { inicio: seleccionado.inicio }))}>Muevo al turno actual</button>
            <button onClick={() => editar((d) => editarMomento(d, m.id, null))}>Elimino</button>
          </li>)}
        </ol>
        {documento.meta.tipo === 'entrevista' && <>
          <label htmlFor="entrevistadora">¿Quién pregunta?</label>
          <select id="entrevistadora" value={documento.meta.entrevistadora || ''} onChange={(e) => editar((d) => ({ ...d, meta: { ...d.meta, entrevistadora: e.target.value || null } }))}>
            <option value="">Automático: la voz con menos tiempo</option>
            {documento.voces.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
          </select>
        </>}
      </section>
      <div className="revision-cuerpo">
        <aside className="voces">

          <h2>
            Voces <span>{documento.voces.length}</span>
          </h2>
          <p className="ayuda">Escriba un nombre para identificar cada voz.</p>
          {documento.voces.map((voz, indice) => (
            <div className="voz" key={voz.id}>
              <label htmlFor={`nombre-${voz.id}`}>
                <span className="muestra" style={{ background: colores[indice % colores.length] }} />
                Nombre de la voz {indice + 1}
              </label>
              <input
                id={`nombre-${voz.id}`}
                value={voz.nombre}
                onChange={(evento) => editar((actual) => renombrarVoz(actual, voz.id, evento.target.value))}
              />
              <small>
                {(voz.segundos / 60).toLocaleString('es', { maximumFractionDigits: 1 })} min ·{' '}
                {total ? Math.round((voz.segundos / total) * 100) : 0}% del habla
              </small>
            </div>
          ))}
          <section className="citas" aria-labelledby="titulo-citas">
            <h2 id="titulo-citas">
              Citas <span>{citas.length}</span>
            </h2>
            <p className="ayuda">
              Seleccione texto y pulse Ctrl+Q para citar un fragmento, o use la estrella para citar el turno.
            </p>
            <ol>
              {citas.map((cita) => (
                <li key={`${cita.tipo}-${cita.id}`}>
                  <button
                    className="hora"
                    disabled={sinAudio}
                    aria-label={`Escuchar la cita de ${cita.nombre} en ${formatoTiempo(cita.inicio)}`}
                    onClick={() => escuchar(cita.inicio)}
                  >
                    {formatoTiempo(cita.inicio)}
                  </button>
                  <b>{cita.nombre}</b>
                  <q>{cita.texto.length > 160 ? `${cita.texto.slice(0, 160)}…` : cita.texto}</q>
                  <button
                    className="quitar"
                    aria-label={`Quitar la cita de ${cita.nombre} en ${formatoTiempo(cita.inicio)}`}
                    onClick={() =>
                      editar((actual) =>
                        cita.tipo === 'turno' ? alternarCita(actual, cita.turno) : quitarCita(actual, cita.id),
                      )
                    }
                  >
                    Quitar
                  </button>
                </li>
              ))}
            </ol>
          </section>
        </aside>
        <div className="turnos">
          <div className="lista-cabecera">
            <h2>Transcripción</h2>
            <span>{documento.turnos.length} turnos</span>
          </div>
          <p className="ayuda">
            Escuche desde la hora indicada o con Alt+clic sobre una palabra. Para dividir, coloque el cursor en el
            texto (Ctrl+Enter).
          </p>
          {documento.turnos.length === 0 && <p>No se detectaron turnos de habla.</p>}
          {documento.turnos.map((turno, indice) => (
            <Turno
              key={turno.id}
              turno={turno}
              indice={indice}
              voces={documento.voces}
              color={colores[documento.voces.findIndex((voz) => voz.id === turno.voz) % colores.length]}
              escuchando={turnoActivo === turno.id}
              seguir={seguir}
              sinAudio={sinAudio}
              alEscribir={alEscribir}
              seleccionado={seleccionado?.id === turno.id}
              alSeleccionar={() => cambiarSeleccion(turno.id)}
              alCita={() => editar((actual) => alternarCita(actual, turno.id))}
              alEscuchar={escuchar}
              alEditar={(texto) => editar((actual) => editarTexto(actual, turno.id, texto))}
              alAsignar={(voz) => editar((actual) => asignarVoz(actual, turno.id, voz))}
              alUnir={() => editar((actual) => unirConAnterior(actual, turno.id))}
              alDividir={(cursor) => {
                const dividido = dividirTurno(documento, turno.id, cursor)
                if (dividido === documento)
                  cambiarMensaje('Coloque el cursor entre dos palabras dentro del turno.')
                else editar(() => dividido)
              }}
            />
          ))}
        </div>
      </div>
      <div className="barra-audio" role="region" aria-label="Control del audio">
        <audio
          ref={audio}
          src={proyecto.urlAudio || undefined}
          preload="metadata"
          onPlay={() => cambiarReproduciendo(true)}
          onPause={() => cambiarReproduciendo(false)}
          onTimeUpdate={(evento) => cambiarTiempo(evento.currentTarget.currentTime)}
          onLoadedMetadata={(evento) => {
            if (Number.isFinite(evento.currentTarget.duration)) cambiarDuracion(evento.currentTarget.duration)
            evento.currentTarget.playbackRate = velocidad
          }}
          onEnded={() => cambiarTiempo(null)}
          onError={() => cambiarSinAudio(true)}
        />
        {sinAudio ? (
          <p role="status">El audio no está disponible. Puede seguir revisando el texto.</p>
        ) : (
          <>
            <button onClick={() => mover(-5)} aria-label="Retroceder 5 segundos" title="Alt+←">
              −5 s
            </button>
            <button
              className="principal reproducir"
              onClick={alternarAudio}
              aria-label={reproduciendo ? 'Pausar' : 'Reproducir'}
              title="Ctrl+Espacio"
            >
              {reproduciendo ? '❚❚' : '▶'}
            </button>
            <button onClick={() => mover(5)} aria-label="Avanzar 5 segundos" title="Alt+→">
              +5 s
            </button>
            <input
              type="range"
              aria-label="Posición del audio"
              min="0"
              max={Math.max(duracion, 1)}
              step="0.5"
              value={tiempo ?? 0}
              onChange={(evento) => {
                audio.current.currentTime = Number(evento.target.value)
                cambiarTiempo(Number(evento.target.value))
              }}
            />
            <span className="reloj-audio">
              {formatoTiempo(tiempo ?? 0)} / {formatoTiempo(duracion)}
            </span>
            <label className="solo-lectores" htmlFor="velocidad">
              Velocidad
            </label>
            <select
              id="velocidad"
              value={velocidad}
              onChange={(evento) => {
                const valor = Number(evento.target.value)
                cambiarVelocidad(valor)
                audio.current.playbackRate = valor
              }}
            >
              {[0.75, 1, 1.25, 1.5].map((valor) => (
                <option key={valor} value={valor}>
                  {valor.toLocaleString('es')}×
                </option>
              ))}
            </select>
            <label className="casilla">
              <input type="checkbox" checked={seguir} onChange={(evento) => cambiarSeguir(evento.target.checked)} />
              Seguir el audio
            </label>
            <label className="casilla">
              <input
                type="checkbox"
                checked={pausarAlEscribir}
                onChange={(evento) => cambiarPausarAlEscribir(evento.target.checked)}
              />
              Pausar al escribir
            </label>
          </>
        )}
      </div>
    </section>
  )
}
