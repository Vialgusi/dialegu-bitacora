import { useCallback, useState } from 'react'
import LogoDialegu from './assets/LogoDialegu.svg'
import Inicio from './componentes/Inicio.jsx'
import Procesando from './componentes/Procesando.jsx'
import Revision from './componentes/Revision.jsx'
import Error from './componentes/Error.jsx'
import { crearTrabajo, esDemo } from './plataforma.js'

export default function App() {
  const [vista, cambiarVista] = useState('inicio')
  const [trabajo, cambiarTrabajo] = useState(null)
  const [proyecto, cambiarProyecto] = useState(null)
  const [error, cambiarError] = useState('')
  // Última carga enviada al motor: «Reintentar» la repite y la descarga de modelos continúa donde quedó.
  const [ultimaCarga, cambiarUltimaCarga] = useState(null)
  const fallar = useCallback((error) => {
    cambiarError(error.message || 'No se pudo completar la operación.')
    cambiarVista('error')
  }, [])
  const procesar = useCallback(
    async (datos, ruta) => {
      cambiarUltimaCarga({ datos, ruta })
      try {
        const { id } = await crearTrabajo({ ...datos, ruta_audio: ruta })
        cambiarTrabajo(id)
        cambiarVista('procesando')
      } catch (error) {
        fallar(error)
      }
    },
    [fallar],
  )
  const revisar = useCallback((datos) => {
    cambiarUltimaCarga(null)
    cambiarProyecto(datos)
    cambiarVista('revision')
  }, [])
  const inicio = useCallback(() => {
    cambiarUltimaCarga(null)
    cambiarVista('inicio')
  }, [])
  return (
    <div className="aplicacion">
      <header className="marca">
        <img src={LogoDialegu} alt="Dialegu" />
        <span>Bitácora</span>
        <small>Escuchar · comprender · registrar</small>
        {esDemo && <b className="insignia">Demostración</b>}
      </header>
      <main>
        {vista === 'inicio' && (
          <Inicio alCargar={procesar} alAbrir={revisar} alError={fallar} />
        )}
        {vista === 'procesando' && (
          <Procesando id={trabajo} alListo={revisar} alCancelar={inicio} alError={fallar} />
        )}
        {vista === 'revision' && (
          <Revision key={proyecto.id || proyecto.ruta || 'proyecto'} proyecto={proyecto} alInicio={inicio} />
        )}
        {vista === 'error' && (
          <Error
            mensaje={error}
            alInicio={inicio}
            alReintentar={ultimaCarga && (() => procesar(ultimaCarga.datos, ultimaCarga.ruta))}
          />
        )}
      </main>
    </div>
  )
}
