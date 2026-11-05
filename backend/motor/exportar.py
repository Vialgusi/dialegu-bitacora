"""Exportación de una Transcripcion a Markdown, texto, subtítulos SRT, PDF y Word."""

import os
import re
from io import BytesIO
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace
from .informe import construir_informe

TIPOS = {"encuentro": "Encuentro o reunión", "grupo_focal": "Grupo focal", "entrevista": "Entrevista"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
SEGUNDOS_POR_SUBTITULO = 6.0
# Colores de la app (index.css): verde de marca, texto, gris suave y bordes.
VERDE, TINTA, SUAVE, LINEA = (33, 88, 70), (31, 36, 33), (98, 113, 105), (216, 222, 212)


def hora(segundos, decimales=False):
    segundos = max(0.0, segundos)
    h, resto = divmod(int(segundos), 3600)
    m, s = divmod(resto, 60)
    if decimales:
        ms = int(round((segundos - int(segundos)) * 1000)) % 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fecha_legible(fecha):
    """«2026-10-31T10:00:00» o «31-10-2026» → «31 de octubre de 2026»; si no se entiende, se deja como vino."""
    texto = str(fecha or "")
    try:
        partes = texto[:10].replace("/", "-").split("-")
        if len(partes) != 3:
            raise ValueError
        if len(partes[0]) == 4:
            anio, mes, dia = (int(x) for x in partes)
        elif len(partes[2]) == 4:
            dia, mes, anio = (int(x) for x in partes)
        else:
            raise ValueError
        if not (1 <= mes <= 12 and 1 <= dia <= 31):
            raise ValueError
        return f"{dia} de {MESES[mes - 1]} de {anio}"
    except ValueError:
        return texto


def porcentaje(valor):
    return f"{valor:.1f}".replace(".", ",") + " %"


def _nombres(t):
    return {v["id"]: v["nombre"] for v in t["voces"]}


def _participacion(t):
    total = sum(v["segundos"] for v in t["voces"]) or 1
    return [(v["nombre"], v["segundos"], 100 * v["segundos"] / total) for v in t["voces"]]


def _cabecera(t):
    m = t["meta"]
    filas = [("Tipo", TIPOS.get(m.get("tipo"), m.get("tipo", ""))), ("Fecha", fecha_legible(m.get("fecha", ""))), ("Duración", hora(m.get("duracion", 0)))]
    if m.get("tema"):
        filas.insert(0, ("Tema", m["tema"]))
    return filas


def a_markdown(t):
    nombres = _nombres(t)
    lineas = [f"# {t['meta']['nombre']}", ""]
    lineas += [f"- **{k}:** {v}" for k, v in _cabecera(t)]
    lineas += ["", "## Participación", "", "| Voz | Tiempo | % |", "|---|---|---|"]
    lineas += [f"| {n} | {hora(s)} | {p:.0f} % |" for n, s, p in _participacion(t)]
    lineas += ["", "## Transcripción", ""]
    for turno in t["turnos"]:
        lineas += [f"**{nombres.get(turno['voz'], turno['voz'])}** · `{hora(turno['inicio'])}`", "", turno["texto"], ""]
    return "\n".join(lineas)


def a_texto(t):
    nombres = _nombres(t)
    lineas = [t["meta"]["nombre"], ""]
    lineas += [f"{k}: {v}" for k, v in _cabecera(t)]
    lineas.append("")
    for turno in t["turnos"]:
        lineas += [f"[{hora(turno['inicio'])}] {nombres.get(turno['voz'], turno['voz'])}:", turno["texto"], ""]
    return "\n".join(lineas)


def _subtitulos_de_turno(turno):
    palabras = turno.get("palabras") or []
    if not palabras:
        yield turno["inicio"], turno["fin"], turno["texto"]
        return
    bloque = []
    for palabra in palabras:
        bloque.append(palabra)
        if bloque[-1]["fin"] - bloque[0]["inicio"] >= SEGUNDOS_POR_SUBTITULO:
            yield bloque[0]["inicio"], bloque[-1]["fin"], " ".join(p["texto"] for p in bloque)
            bloque = []
    if bloque:
        yield bloque[0]["inicio"], bloque[-1]["fin"], " ".join(p["texto"] for p in bloque)


def a_srt(t):
    nombres = _nombres(t)
    bloques, n = [], 0
    for turno in t["turnos"]:
        quien = nombres.get(turno["voz"], turno["voz"])
        for inicio, fin, texto in _subtitulos_de_turno(turno):
            n += 1
            bloques.append(f"{n}\n{hora(inicio, True)} --> {hora(fin, True)}\n{quien}: {texto}\n")
    return "\n".join(bloques)


def _fuente_unicode():
    """Arial de Windows si existe: cubre tildes, ñ, comillas y rayas que la fuente base del PDF no admite."""
    carpeta = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    rutas = {"": carpeta / "arial.ttf", "B": carpeta / "arialbd.ttf", "I": carpeta / "ariali.ttf"}
    if not (rutas[""].exists() and rutas["B"].exists()):
        return None
    if not rutas["I"].exists():
        rutas["I"] = rutas[""]  # sin la cursiva, las citas van en redonda; no se pierde la fuente completa
    return rutas


# Signos fuera de latin-1 que usa el informe, para la fuente base del PDF (sin Arial).
_LATIN1 = str.maketrans({"—": "-", "–": "-", "…": "...", "“": '"', "”": '"', "‘": "'", "’": "'"})


class _Pdf(FPDF):
    """Hoja carta con cabecera, pie con «Página X de Y», marcadores y los bloques del informe."""

    def __init__(self, titulo):
        super().__init__(format="Letter")
        self.titulo = titulo
        self.set_margins(22, 20, 22)
        self.set_auto_page_break(auto=True, margin=20)
        fuente = _fuente_unicode()
        if fuente:
            for estilo, ruta in fuente.items():
                self.add_font("texto", estilo, str(ruta))
        self.familia = "texto" if fuente else "helvetica"
        self.unicode = bool(fuente)
        self.set_title(self.t(titulo))
        self.set_creator("Dialegu Bitácora")
        self.set_lang("es")
        self.add_page()

    def t(self, texto):
        if self.unicode:
            return texto
        return str(texto).translate(_LATIN1).encode("latin-1", "replace").decode("latin-1")

    def recortar(self, texto, ancho):
        """Corta con «…» lo que no cabe en `ancho` mm con la letra actual (para celdas de una línea)."""
        texto = self.t(texto)
        if self.get_string_width(texto) <= ancho:
            return texto
        puntos = self.t("…")
        while texto and self.get_string_width(texto + puntos) > ancho:
            texto = texto[:-1]
        return texto.rstrip() + puntos

    def letra(self, estilo="", tamano=10, color=TINTA):
        self.set_font(self.familia, estilo, tamano)
        self.set_text_color(*color)

    def header(self):
        if self.page_no() == 1:
            return
        self.letra("", 8, SUAVE)
        self.cell(0, 5, self.recortar(self.titulo, self.epw), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LINEA)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.set_y(self.get_y() + 6)

    def footer(self):
        self.set_y(-13)
        self.letra("", 8, SUAVE)
        self.cell(0, 5, self.t("Dialegu Bitácora"))
        self.set_x(self.l_margin)
        self.cell(0, 5, self.t(f"Página {self.page_no()} de {{nb}}"), align="R")

    def espacio(self, alto):
        """Salta de página si no caben `alto` mm: evita títulos y nombres huérfanos al pie."""
        if self.get_y() + alto > self.page_break_trigger:
            self.add_page()

    def bloque(self, tipo, valor):
        getattr(self, f"_{tipo}")(valor)

    def _titulo(self, texto):
        self.letra("B", 20, VERDE)
        self.multi_cell(0, 9, self.t(texto), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*VERDE)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y() + 2, self.l_margin + 30, self.get_y() + 2)
        self.ln(6)

    def _ficha(self, filas):
        for etiqueta, valor in filas:
            self.letra("B", 9.5, SUAVE)
            self.cell(24, 5.5, self.t(etiqueta))
            self.letra("", 9.5)
            self.multi_cell(0, 5.5, self.t(valor), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def _h1(self, texto):
        self.espacio(30)
        self.ln(5)
        self.start_section(self.t(texto), level=0)
        self.letra("B", 14, VERDE)
        self.multi_cell(0, 7, self.t(texto), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LINEA)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)

    def _anexo(self, texto):
        self.add_page()
        self._h1(texto)

    def _h2(self, texto):
        self.espacio(25)
        self.ln(2)
        self.start_section(self.t(texto), level=1)
        self.letra("B", 11, TINTA)
        self.multi_cell(0, 5.5, self.t(texto), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def _tabla(self, filas):
        self.letra("", 9.5)
        self.set_draw_color(*LINEA)
        self.set_line_width(0.2)
        with self.table(
            col_widths=(40,) + (20,) * (len(filas[0]) - 1),
            text_align=("LEFT",) + ("RIGHT",) * (len(filas[0]) - 1),
            headings_style=FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=VERDE),
            line_height=6.5,
            padding=(1, 2),
            borders_layout="HORIZONTAL_LINES",
        ) as tabla:
            for fila in filas:
                fila_pdf = tabla.row()
                for celda in fila:
                    fila_pdf.cell(self.t(celda))
        self.ln(2)

    def _momento(self, valor):
        inicio, titulo = valor
        self.letra("B", 9.5, VERDE)
        self.cell(16, 5.5, inicio)
        self.letra("", 10)
        self.multi_cell(0, 5.5, self.t(titulo), new_x="LMARGIN", new_y="NEXT")
        self.ln(0.5)

    def _cita(self, valor):
        texto, atribucion = valor
        self.letra("I", 10.5)
        opciones = dict(align="L", padding=(0.5, 0, 0.5, 4))
        alto = self.multi_cell(0, 5.6, self.t(f"«{texto}»"), dry_run=True, output="HEIGHT", **opciones)
        # La cita y su atribución van juntas si caben en una página; si no, al menos arrancan con dos líneas.
        self.espacio(alto + 5 if alto + 5 < self.eph else 16)
        self.set_draw_color(*VERDE)
        self.set_line_width(0.8)
        self.multi_cell(0, 5.6, self.t(f"«{texto}»"), border="L", new_x="LMARGIN", new_y="NEXT", **opciones)
        self.letra("", 8.5, SUAVE)
        self.cell(0, 5, self.recortar(f"— {atribucion}", self.epw), align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(2.5)

    def _turno(self, valor):
        nombre, inicio, texto = valor
        self.espacio(12)
        self.letra("B", 9.5, VERDE)
        nombre = self.recortar(nombre, self.epw - 20)  # deja sitio a la hora
        self.cell(self.get_string_width(nombre) + 2, 5, nombre)
        self.letra("", 8.5, SUAVE)
        self.cell(0, 5, inicio, new_x="LMARGIN", new_y="NEXT")
        self.letra("", 10)
        self.multi_cell(0, 5.3, self.t(texto), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(2.5)

    def _parrafo(self, texto):
        self.letra("", 9.5, SUAVE)
        self.multi_cell(0, 5, self.t(texto), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

    def salida(self):
        return bytes(self.output())


def a_pdf(t):
    nombres = _nombres(t)
    pdf = _Pdf(t["meta"]["nombre"])
    pdf.bloque("titulo", t["meta"]["nombre"])
    pdf.bloque("ficha", _cabecera(t))
    pdf.bloque("h1", "Participación")
    pdf.bloque("tabla", [["Voz", "Tiempo", "% del habla"]] + [[n, hora(s), porcentaje(p)] for n, s, p in _participacion(t)])
    pdf.bloque("h1", "Transcripción")
    for turno in t["turnos"]:
        pdf.bloque("turno", (nombres.get(turno["voz"], turno["voz"]), hora(turno["inicio"]), turno["texto"]))
    return pdf.salida()


def _bloques_informe(t):
    """Secuencia semántica compartida por Markdown, PDF y Word."""
    informe = construir_informe(t)
    p = informe["portada"]
    yield "titulo", p["nombre"]
    ficha = [("Tipo", TIPOS.get(p["tipo"], p["tipo"])), ("Fecha", fecha_legible(p["fecha"])), ("Duración", hora(p["duracion"]))]
    if p["tema"]:
        ficha.insert(0, ("Tema", p["tema"]))
    yield "ficha", ficha
    yield "h1", "Participantes"
    yield "tabla", [["Voz", "Tiempo de habla", "% del habla", "Intervenciones"]] + [
        [v["nombre"], hora(v["minutos"] * 60), porcentaje(v["porcentaje"]), str(v["intervenciones"])] for v in informe["participantes"]
    ]
    yield "h1", "Índice de momentos"
    for m in informe["momentos"]:
        yield "momento", (hora(m["inicio"]), m["titulo"])
    yield "h1", "Citas destacadas"
    for c in informe["citas"]:
        yield "cita", (c["texto"], f"{c['nombre']} · {hora(c['inicio'])}")
    if not informe["citas"]:
        yield "parrafo", "No se marcaron citas durante la revisión."
    yield "h1", "Conversación"
    for seccion in informe["cuerpo"]:
        yield "h2", f"{hora(seccion['inicio'])} · {seccion['titulo']}"
        if "turnos" in seccion:
            turnos = seccion["turnos"]
        else:
            # La primera pregunta ya es el título de la sección: no se repite.
            preguntas = seccion["preguntas"]
            if preguntas and preguntas[0]["texto"].strip() == seccion["titulo"]:
                preguntas = preguntas[1:]
            turnos = preguntas + seccion["respuestas"]
        for turno in turnos:
            yield "turno", (turno["nombre"], hora(turno["inicio"]), turno["texto"])
    yield "h1", "Nota metodológica"
    yield "parrafo", nota_metodologica(t.get("meta", {}))
    yield "anexo", "Anexo · Transcripción completa"
    for turno in informe["transcripcion"]:
        yield "turno", (turno["nombre"], hora(turno["inicio"]), turno["texto"])


IDIOMAS = {"es": "español", "en": "inglés", "pt": "portugués", "auto": "detectado automáticamente"}


def nota_metodologica(meta):
    """Cómo se produjo el registro, para que sea citable y quede claro que hubo revisión humana."""
    partes = [
        "Transcripción automática hecha en el equipo local, sin enviar el audio a servidores externos",
        f"con Whisper {meta['modelo']}" if meta.get("modelo") else None,
        {"gpu": "en tarjeta gráfica NVIDIA", "cpu": "en el procesador"}.get(meta.get("dispositivo")),
    ]
    frases = [" ".join(p for p in partes if p) + "."]
    if meta.get("idioma"):
        frases.append(f"Idioma: {IDIOMAS.get(meta['idioma'], meta['idioma'])}.")
    if meta.get("distinguir_voces") is False:
        frases.append("No se distinguieron voces: todo el texto se atribuye a una sola voz.")
    elif meta.get("modelo_voces"):
        frases.append(f"Voces reconocidas automáticamente con {meta['modelo_voces']}.")
    if meta.get("segundos_proceso"):
        frases.append(f"Tiempo de proceso: {hora(meta['segundos_proceso'])}.")
    if meta.get("version_app"):
        frases.append(f"Dialegu Bitácora {meta['version_app']}.")
    frases.append(
        "El texto fue revisado y corregido por una persona; aun así puede contener errores de transcripción "
        "o de atribución de voces, sobre todo en nombres propios, términos regionales o especializados y habla superpuesta."
    )
    return " ".join(frases)


_MARCA_MD = re.compile(r"^(\s*)([-+*#>|]|\d+[.)](?=\s|$))")


def _md_texto(texto):
    """Lo que se dijo no debe volverse lista, título, cita ni tabla: se escapa la marca al inicio de cada línea."""
    def escapar(m):
        marca = m.group(2)
        # «1.» se escapa como «1\.»: una barra delante del número quedaría visible.
        return m.group(1) + (marca[:-1] + "\\" + marca[-1] if marca[0].isdigit() else "\\" + marca)
    return "\n".join(_MARCA_MD.sub(escapar, linea) for linea in str(texto).split("\n"))


def a_informe_markdown(t):
    def escapar(texto):
        return texto.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
    lineas = []
    for tipo, valor in _bloques_informe(t):
        if lineas and lineas[-1].startswith("- `") and tipo != "momento":
            lineas.append("")
        if tipo == "tabla":
            for i, fila in enumerate(valor):
                lineas.append("| " + " | ".join(escapar(c) for c in fila) + " |")
                if i == 0:
                    lineas.append("|---" + "|--:" * (len(fila) - 1) + "|")
            lineas.append("")
        elif tipo == "ficha":
            lineas += [f"- **{k}:** {v}" for k, v in valor] + [""]
        elif tipo == "momento":
            lineas.append(f"- `{valor[0]}` {valor[1]}")
        elif tipo == "cita":
            lineas += [f"> {_md_texto(valor[0])}", ">", f"> — {valor[1]}", ""]
        elif tipo == "turno":
            lineas += [f"**{valor[0]}** · `{valor[1]}`  ", _md_texto(valor[2]), ""]
        else:
            prefijo = {"titulo": "# ", "h1": "## ", "anexo": "## ", "h2": "### "}.get(tipo, "")
            lineas += [prefijo + valor, ""]
    return "\n".join(lineas)


def _xml(etiqueta, **atributos):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    elemento = OxmlElement(etiqueta)
    for nombre, valor in atributos.items():
        elemento.set(qn(nombre.replace("_", ":", 1)), valor)
    return elemento


# Word valida el orden de los hijos según el esquema OOXML: cada elemento nuevo va antes de estos.
_DESPUES_DE_LANG = ("w:eastAsianLayout", "w:specVanish", "w:oMath")
_DESPUES_DE_PBDR = (
    "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct",
    "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
    "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
)
_DESPUES_DE_TBLBORDERS = ("w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange")


def _docx_estilos(documento):
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    seccion = documento.sections[0]
    seccion.page_width, seccion.page_height = Cm(21.59), Cm(27.94)
    seccion.left_margin = seccion.right_margin = Cm(2.5)
    seccion.top_margin = seccion.bottom_margin = Cm(2.2)
    estilos = documento.styles

    def fuente(estilo, tamano, color=TINTA, negrita=None, cursiva=None):
        # Se fija Arial en todas las variantes y se quita la fuente del tema, que Word aplicaría encima.
        fuentes = estilo.element.get_or_add_rPr().get_or_add_rFonts()
        for atributo in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            fuentes.set(qn(atributo), "Arial")
        for atributo in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            fuentes.attrib.pop(qn(atributo), None)
        estilo.font.size = Pt(tamano)
        estilo.font.color.rgb = RGBColor(*color)
        estilo.font.bold, estilo.font.italic = negrita, cursiva

    normal = estilos["Normal"]
    fuente(normal, 10.5)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    normal.element.get_or_add_rPr().insert_element_before(_xml("w:lang", w_val="es-CO"), *_DESPUES_DE_LANG)

    for nombre, tamano, color, antes, despues in (("Title", 22, VERDE, 0, 4), ("Heading 1", 15, VERDE, 18, 6), ("Heading 2", 11.5, TINTA, 12, 4)):
        estilo = estilos[nombre]
        fuente(estilo, tamano, color, negrita=True)
        formato = estilo.paragraph_format
        formato.space_before, formato.space_after, formato.keep_with_next = Pt(antes), Pt(despues), True
    # El título de la plantilla trae borde inferior azul y letras espaciadas: se quitan.
    for padre, etiqueta in ((estilos["Title"].element.get_or_add_pPr(), "w:pBdr"), (estilos["Title"].element.get_or_add_rPr(), "w:spacing")):
        for sobrante in padre.findall(qn(etiqueta)):
            padre.remove(sobrante)
    estilos["Title"].paragraph_format.space_after = Pt(12)

    cita = estilos["Quote"]
    fuente(cita, 11, TINTA, cursiva=True)
    cita.paragraph_format.left_indent = Cm(0.6)
    cita.paragraph_format.right_indent = Cm(0)
    cita.paragraph_format.space_after = Pt(2)
    # La atribución no queda sola al comienzo de la página siguiente.
    cita.paragraph_format.keep_with_next = True
    cita.paragraph_format.keep_together = True
    borde = _xml("w:pBdr")
    borde.append(_xml("w:left", w_val="single", w_sz="18", w_space="10", w_color="215846"))
    cita.element.get_or_add_pPr().insert_element_before(borde, *_DESPUES_DE_PBDR)

    for nombre, tamano, color in (("Atribución", 8.5, SUAVE), ("Ficha", 10, TINTA), ("Nota", 9.5, SUAVE), ("Pie", 8, SUAVE)):
        estilo = estilos.add_style(nombre, WD_STYLE_TYPE.PARAGRAPH)
        estilo.base_style = normal
        fuente(estilo, tamano, color)
    estilos["Ficha"].paragraph_format.space_after = Pt(1)
    estilos["Atribución"].paragraph_format.space_after = Pt(10)
    estilos["Pie"].paragraph_format.space_after = Pt(0)


def _docx_campo(parrafo, codigo):
    """Campo de Word (PAGE, NUMPAGES) que se calcula al abrir o imprimir."""
    parrafo.add_run()._r.append(_xml("w:fldChar", w_fldCharType="begin"))
    instruccion = _xml("w:instrText", xml_space="preserve")
    instruccion.text = f" {codigo} "
    parrafo.add_run()._r.append(instruccion)
    parrafo.add_run()._r.append(_xml("w:fldChar", w_fldCharType="separate"))
    parrafo.add_run("1")
    parrafo.add_run()._r.append(_xml("w:fldChar", w_fldCharType="end"))


def _docx_tabla(documento, filas):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    tabla = documento.add_table(rows=0, cols=len(filas[0]))
    bordes = _xml("w:tblBorders")
    for lado in ("top", "bottom", "insideH"):
        bordes.append(_xml(f"w:{lado}", w_val="single", w_sz="4", w_color="D8DED4"))
    tabla._tbl.tblPr.insert_element_before(bordes, *_DESPUES_DE_TBLBORDERS)
    anchos = [Cm(6.5)] + [Cm(3.2)] * (len(filas[0]) - 1)
    for i, fila in enumerate(filas):
        fila_docx = tabla.add_row()
        if i == 0:
            fila_docx._tr.get_or_add_trPr().append(_xml("w:tblHeader"))
        for j, (celda, texto) in enumerate(zip(fila_docx.cells, fila)):
            celda.width = anchos[j]
            parrafo = celda.paragraphs[0]
            parrafo.paragraph_format.space_before = parrafo.paragraph_format.space_after = Pt(3)
            parrafo.alignment = WD_ALIGN_PARAGRAPH.RIGHT if j else WD_ALIGN_PARAGRAPH.LEFT
            run = parrafo.add_run(texto)
            run.font.size = Pt(10)
            if i == 0:
                run.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)
                celda._tc.get_or_add_tcPr().append(_xml("w:shd", w_val="clear", w_color="auto", w_fill="215846"))
    documento.add_paragraph()


def a_informe_docx(t):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.shared import Cm, Pt, RGBColor

    documento = Document()
    _docx_estilos(documento)
    nombre = t["meta"]["nombre"]
    documento.core_properties.title = nombre
    documento.core_properties.author = "Dialegu Bitácora"
    documento.core_properties.language = "es-CO"

    seccion = documento.sections[0]
    seccion.different_first_page_header_footer = True
    seccion.header.paragraphs[0].text = nombre
    seccion.header.paragraphs[0].style = "Pie"
    for pie in (seccion.footer, seccion.first_page_footer):
        parrafo = pie.paragraphs[0]
        parrafo.style = "Pie"
        parrafo.paragraph_format.tab_stops.add_tab_stop(Cm(16.59), WD_TAB_ALIGNMENT.RIGHT)
        parrafo.add_run("Dialegu Bitácora\tPágina ")
        _docx_campo(parrafo, "PAGE")
        parrafo.add_run(" de ")
        _docx_campo(parrafo, "NUMPAGES")

    def color(run, rgb, tamano=None, negrita=None):
        run.font.color.rgb = RGBColor(*rgb)
        if tamano:
            run.font.size = Pt(tamano)
        run.bold = negrita

    for tipo, valor in _bloques_informe(t):
        if tipo == "titulo":
            documento.add_paragraph(valor, style="Title")
        elif tipo == "ficha":
            for etiqueta, dato in valor:
                parrafo = documento.add_paragraph(style="Ficha")
                parrafo.paragraph_format.tab_stops.add_tab_stop(Cm(2.6))
                color(parrafo.add_run(f"{etiqueta}\t"), SUAVE, negrita=True)
                parrafo.add_run(dato)
        elif tipo in ("h1", "h2", "anexo"):
            encabezado = documento.add_heading(valor, 2 if tipo == "h2" else 1)
            encabezado.paragraph_format.page_break_before = tipo == "anexo"
        elif tipo == "tabla":
            _docx_tabla(documento, valor)
        elif tipo == "momento":
            parrafo = documento.add_paragraph()
            parrafo.paragraph_format.tab_stops.add_tab_stop(Cm(1.6))
            parrafo.paragraph_format.space_after = Pt(2)
            color(parrafo.add_run(f"{valor[0]}\t"), VERDE, negrita=True)
            parrafo.add_run(valor[1])
        elif tipo == "cita":
            documento.add_paragraph(f"«{valor[0]}»", style="Quote")
            documento.add_paragraph(f"— {valor[1]}", style="Atribución").alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif tipo == "turno":
            quien, inicio, texto = valor
            parrafo = documento.add_paragraph()
            parrafo.paragraph_format.space_after = Pt(8)
            color(parrafo.add_run(quien), VERDE, 10, negrita=True)
            marca = parrafo.add_run(f"  {inicio}")
            color(marca, SUAVE, 9)
            marca.add_break()
            parrafo.add_run(texto)
        else:
            documento.add_paragraph(valor, style="Nota")
    salida = BytesIO()
    documento.save(salida)
    return salida.getvalue()


def a_informe_pdf(t):
    pdf = _Pdf(t["meta"]["nombre"])
    for tipo, valor in _bloques_informe(t):
        pdf.bloque(tipo, valor)
    return pdf.salida()


FORMATOS = {
    "informe-md": (lambda t: a_informe_markdown(t).encode("utf-8"), "text/markdown; charset=utf-8"),
    "informe-pdf": (a_informe_pdf, "application/pdf"),
    "informe-docx": (a_informe_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "md": (lambda t: a_markdown(t).encode("utf-8"), "text/markdown; charset=utf-8"),
    "txt": (lambda t: a_texto(t).encode("utf-8"), "text/plain; charset=utf-8"),
    "srt": (lambda t: a_srt(t).encode("utf-8"), "application/x-subrip; charset=utf-8"),
    "pdf": (a_pdf, "application/pdf"),
}
