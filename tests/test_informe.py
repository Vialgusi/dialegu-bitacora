import json
from pathlib import Path
from io import BytesIO

import pytest

from backend.motor.informe import construir_informe
from backend.motor.exportar import FORMATOS


@pytest.fixture
def demo():
    return json.loads(Path('frontend/src/demo/transcripcion-demo.json').read_text(encoding='utf-8'))


def test_grupo_focal_tres_preguntas(demo):
    informe = construir_informe(demo)
    assert [[t['id'] for t in s['turnos']] for s in informe['cuerpo']] == [['t1', 't2', 't3'], ['t4', 't5', 't6'], ['t7', 't8']]
    assert informe['citas'][0]['id'] == 't3'
    assert sum(v['intervenciones'] for v in informe['participantes']) == 8
    assert sum(v['porcentaje'] for v in informe['participantes']) == pytest.approx(100)


def test_entrevista_menor_tiempo_y_respuestas(demo):
    demo['meta']['tipo'] = 'entrevista'
    # Las cifras guardadas pueden estar desactualizadas: se calcula desde turnos.
    demo['voces'][0]['segundos'] = 0
    informe = construir_informe(demo)
    assert informe['entrevistadora'] == 'v2'
    assert informe['cuerpo'][0]['titulo'] == 'Apertura'
    assert [t['id'] for t in informe['cuerpo'][2]['preguntas']] == ['t5', 't6']
    demo['meta']['entrevistadora'] = 'v1'
    informe = construir_informe(demo)
    assert informe['entrevistadora'] == 'v1'
    assert [t['id'] for t in informe['cuerpo'][1]['respuestas']] == ['t5', 't6']


def test_v02_sin_campos_nuevos(demo):
    for campo in ('tipo', 'momentos', 'guia', 'entrevistadora'):
        demo['meta'].pop(campo, None)
    for t in demo['turnos']:
        t.pop('cita', None)
    informe = construir_informe(demo)
    assert informe['portada']['tipo'] == 'encuentro'
    assert len(informe['cuerpo']) == 1
    assert informe['citas'] == []
    assert len(informe['transcripcion']) == len(demo['turnos'])


def test_docx_titulos_tabla_y_cita(demo):
    from docx import Document
    datos, mime = FORMATOS['informe-docx']
    doc = Document(BytesIO(datos(demo)))
    assert any(p.text == 'Participantes' and p.style.name == 'Heading 1' for p in doc.paragraphs)
    assert any(p.style.name == 'Heading 2' for p in doc.paragraphs)
    assert any(p.style.name == 'Quote' and demo['turnos'][2]['texto'] in p.text for p in doc.paragraphs)
    assert len(doc.tables[0].rows) == 3
    assert mime.endswith('wordprocessingml.document')


def test_pdf_y_markdown(demo):
    pdf = FORMATOS['informe-pdf'][0](demo)
    assert pdf.startswith(b'%PDF-')
    assert pdf.rstrip().endswith(b'%%EOF')
    md = FORMATOS['informe-md'][0](demo).decode('utf-8')
    assert '## Participantes' in md
    assert '## Anexo' in md
    assert '> — Voz 2 · 00:14' in md


def test_sin_marcas_guia_no_inventa_tiempos(demo):
    demo['meta']['momentos'] = []
    assert len(construir_informe(demo)['cuerpo']) == 1


def test_guia_sustituye_titulo_vacio(demo):
    demo['meta']['momentos'][1]['titulo'] = ''
    assert construir_informe(demo)['cuerpo'][1]['titulo'] == demo['meta']['guia'][1]


def test_indice_automatico_y_documento_vacio(demo):
    demo['meta']['momentos'] = []
    demo['turnos'][3]['inicio'] = 610
    demo['turnos'][3]['fin'] = 615
    informe = construir_informe(demo)
    assert [m['inicio'] for m in informe['momentos']] == [0, 610]
    demo['turnos'] = []
    demo['voces'] = []
    demo['meta']['tipo'] = 'entrevista'
    informe = construir_informe(demo)
    assert informe['cuerpo'] == []
    assert informe['participantes'] == []


def test_citas_por_fragmento_con_la_voz_actual_y_en_orden(demo):
    turno = demo['turnos'][0]
    demo['citas'] = [{'id': 'c1', 'turno': turno['id'], 'voz': 'otra', 'inicio': turno['inicio'] + 0.5, 'fin': turno['fin'], 'texto': 'fragmento citado'}]
    informe = construir_informe(demo)
    fragmento = next(c for c in informe['citas'] if c['id'] == 'c1')
    assert fragmento['voz'] == turno['voz']
    assert fragmento['nombre'] == next(v['nombre'] for v in demo['voces'] if v['id'] == turno['voz'])
    assert [c['inicio'] for c in informe['citas']] == sorted(c['inicio'] for c in informe['citas'])
    assert 'fragmento citado' in FORMATOS['informe-md'][0](demo).decode('utf-8')


def test_docx_carta_pie_numerado_y_fecha_legible(demo):
    from docx import Document
    doc = Document(BytesIO(FORMATOS['informe-docx'][0](demo)))
    seccion = doc.sections[0]
    assert round(seccion.page_width.cm, 1) == 21.6 and round(seccion.page_height.cm, 1) == 27.9
    assert 'NUMPAGES' in seccion.footer._element.xml and 'PAGE' in seccion.first_page_footer._element.xml
    assert any('31 de octubre de 2026' in p.text for p in doc.paragraphs)
    assert doc.core_properties.title == demo['meta']['nombre']
    assert next(p for p in doc.paragraphs if p.text.startswith('Anexo')).paragraph_format.page_break_before


def test_pdf_con_marcadores_y_sin_fuente_unicode(demo, monkeypatch):
    from backend.motor import exportar
    pdf = FORMATOS['informe-pdf'][0](demo)
    assert b'/Outlines' in pdf
    monkeypatch.setattr(exportar, '_fuente_unicode', lambda: None)
    assert FORMATOS['informe-pdf'][0](demo).startswith(b'%PDF-')
    assert FORMATOS['pdf'][0](demo).startswith(b'%PDF-')


def test_entrevista_no_repite_la_pregunta_del_titulo(demo):
    demo['meta']['tipo'] = 'entrevista'
    md = FORMATOS['informe-md'][0](demo).decode('utf-8')
    conversacion = md.split('## Conversación')[1].split('## Nota metodológica')[0]
    pregunta = demo['turnos'][2]['texto']  # Voz 2 habla menos: es la entrevistadora
    assert conversacion.count(pregunta) == 1
