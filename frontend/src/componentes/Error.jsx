export default function Error({ mensaje, alInicio, alReintentar }) {
  return (
    <section className="panel centrado">
      <p className="ceja">No se pudo continuar</p>
      <h1>Revise lo ocurrido</h1>
      <p role="alert">{mensaje}</p>
      <div className="acciones">
        {alReintentar && (
          <button className="principal" onClick={alReintentar}>
            Reintentar
          </button>
        )}
        <button className={alReintentar ? '' : 'principal'} onClick={alInicio}>
          Volver al inicio
        </button>
      </div>
    </section>
  )
}
