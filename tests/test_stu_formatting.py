from copy import deepcopy
from io import BytesIO
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
import pytest
from test_stu import content, client, create
from app.stu_schema import StuContent, glossary_key
from app.stu_docx import BASE, generate


def document(data=None):
 return Document(BytesIO(generate(StuContent.model_validate(data or content(4)))))


def test_blank_dates_save_export_and_populated_dates(client):
 c,_=client;id=create(c);data=content()
 assert c.put(f'/stu/{id}',json={'version':1,'content':data}).status_code==200
 assert c.get(f'/stu/{id}/export.docx').status_code==200
 d=document(data)
 assert d.tables[0].rows[2].cells[-1].paragraphs[-1].text=='от '
 assert d.tables[0].rows[7].cells[1].paragraphs[2].text==''
 data['order_date']='2026-11-11';data['effective_date']='2026-12-01'
 d=document(data);assert '11.11.2026' in d.tables[0].rows[2].cells[-1].text
 assert '01.12.2026' in d.tables[0].rows[7].cells[1].text


def test_glossary_sorting_bold_terms_and_legacy_conversion():
 data=content();data['abbreviations']=''
 data['abbreviation_rows']=[{'name':'ЯМ','meaning':'Последнее сокращение'},{'name':'АД','meaning':'Первое сокращение'},{'name':'ЁМ','meaning':'Среднее сокращение'}]
 data['term_rows']=[{'name':'Явление','meaning':'Последний термин'},{'name':'Анализ','meaning':'Первый термин'}]
 d=document(data);paras=d.paragraphs;lines=[p.text for p in paras]
 expected=['АД - Первое сокращение','ЁМ - Среднее сокращение','ЯМ - Последнее сокращение','Анализ - Первый термин','Явление - Последний термин']
 assert [lines.index(text) for text in expected]==sorted(lines.index(text) for text in expected)
 term=next(p for p in paras if p.text==expected[3]);assert next(r for r in term.runs if r.text=='Анализ').bold
 assert next(r for r in term.runs if ' - ' in r.text).bold is False
 old=StuContent.model_validate(content());assert old.abbreviations=='' and old.abbreviation_rows[0].name=='СТУ'
 data=content();data['abbreviations']='Произвольный старый текст без разделителя'
 model=StuContent.model_validate(data);assert model.abbreviations==data['abbreviations'] and not model.abbreviation_rows
 assert sorted(['Ж','Ё','Е'],key=glossary_key)==['Е','Ё','Ж']
 data['abbreviations']='СТУ - '+('я'*6000)
 assert StuContent.model_validate(data).abbreviations==data['abbreviations']


def assert_font(table,size):
 for row in table.rows:
  for cell in row.cells:
   for p in cell.paragraphs:
    for run in p.runs:
     if run.text:assert (run.font.name,run.font.size.pt)==('Arial',size)


def assert_center(table):
 for row in table.rows:
  for cell in row.cells:
   assert cell.vertical_alignment==WD_CELL_VERTICAL_ALIGNMENT.CENTER
   assert all(p.alignment==WD_ALIGN_PARAGRAPH.CENTER for p in cell.paragraphs)


def test_approval_dimensions_no_fill_matrix_and_body_fonts():
 d=document();approval=d.tables[1]
 assert [round(col.width.cm,2) for col in approval.columns]==[3.5,5.44,3.25,2.5,2.5]
 assert_font(approval,10);assert_center(approval)
 assert not approval._tbl.xpath('.//w:shd')
 matrix=next(t for t in d.tables if 'Наименование подразделения' in t.cell(0,1).text)
 assert_font(matrix,10);assert_center(matrix)
 para=next(p for p in d.paragraphs if p.text=='Назначение.')
 assert round(para.paragraph_format.first_line_indent.cm,2)==1
 assert all((r.font.name,r.font.size.pt)==('Arial',12) for r in para.runs)
 for p in d.sections[0].header.tables[0].rows[0].cells[0].paragraphs:
  assert all(r.font.name=='Arial' and r.font.size.pt==12 for r in p.runs)
 for p in d.paragraphs:
  if p.text=='1 НАЗНАЧЕНИЕ':assert all(r.font.size.pt==12 for r in p.runs)
 assert d.styles['toc 1'].font.name=='Arial' and d.styles['toc 1'].font.size.pt==12


def test_process_hidden_borders_gray_fill_and_centered_24():
 d=document();t=next(t for t in d.tables if len(t.columns)==1)
 assert_center(t);assert_font(t,24)
 for edge in t._tbl.xpath('.//w:tcBorders/*'):assert edge.get(qn('w:val'))=='nil'
 assert t.cell(1,0)._tc.get_or_add_tcPr().find(qn('w:shd')).get(qn('w:fill'))=='F2F2F2'
 assert not t.cell(0,0)._tc.xpath('./w:tcPr/w:shd')
 assert all(r.bold is False for row in t.rows for cell in row.cells for p in cell.paragraphs for r in p.runs)


def test_risk_alignment_indicators_and_appendix_soft_break():
 data=content();data['appendices']=['образец с Сохранением РЕГИСТРА']
 d=document(data);risk=next(t for t in d.tables if 'Возможный прецедент' in t.cell(0,0).text)
 assert_font(risk,12)
 for i,row in enumerate(risk.rows):
  for j,c in enumerate(row.cells):
   assert c.vertical_alignment==WD_CELL_VERTICAL_ALIGNMENT.CENTER
   assert all(p.alignment==(WD_ALIGN_PARAGRAPH.LEFT if i>=2 and j==0 else WD_ALIGN_PARAGRAPH.CENTER) for p in c.paragraphs)
 indicators=next(t for t in d.tables if len(t.columns)==11);assert_font(indicators,10);assert_center(indicators)
 p=next(p for p in d.paragraphs if p.text.startswith('ПРИЛОЖЕНИЕ 1\n'))
 assert p.text=='ПРИЛОЖЕНИЕ 1\nОбразец с Сохранением РЕГИСТРА'
 assert p.style.name=='Heading 1' and p.alignment==WD_ALIGN_PARAGRAPH.CENTER
 assert all(r.bold for r in p.runs)
 assert len(p._p.xpath('.//w:br'))==1


def test_training_layout_retained_font_explicit_and_partial_glossary_validation():
 d=document();source=Document(BASE)
 assert d.tables[-1]._tbl.tblGrid.xml==source.tables[-1]._tbl.tblGrid.xml
 assert [r.height for r in d.tables[-1].rows]==[r.height for r in source.tables[-1].rows]
 assert_font(d.tables[-1],12)
 p=next(p for p in d.paragraphs if p.text.startswith('Обучение прошел'))
 assert all(r.font.name=='Arial' and r.font.size.pt==12 for r in p.runs)
 data=content();data['abbreviations']='';data['abbreviation_rows']=[{'name':'АД','meaning':''}]
 assert any('сокращения' in s for s in StuContent.model_validate(data).export_errors())


def test_refined_banner_approval_rows_and_actual_word_toc_style():
 from docx.enum.table import WD_ROW_HEIGHT_RULE
 from app.stu_docx import TITLE_BANNER
 d=document()
 assert any(p.text==TITLE_BANNER for cell in d.tables[0].rows[0].cells for p in cell.paragraphs)
 approval=d.tables[1]
 assert approval.cell(0,2).text=='Фамилия,\nинициалы'
 for row in approval.rows[1:]:
  assert round(row.height.cm,2)==1 and row.height_rule==WD_ROW_HEIGHT_RULE.AT_LEAST
 for level in [1,2]:
  styles=[s for s in d.styles if s.style_id==f'TOC{level}']
  assert len(styles)==1
  assert styles[0].font.name=='Arial' and styles[0].font.size.pt==12
  fonts=styles[0].element.rPr.rFonts
  assert fonts.get(qn('w:ascii'))==fonts.get(qn('w:hAnsi'))==fonts.get(qn('w:cs'))=='Arial'
  assert not any('Theme' in attr for attr in fonts.attrib)
 contents=next(p for p in d.paragraphs if p.text=='СОДЕРЖАНИЕ')
 assert contents.alignment==WD_ALIGN_PARAGRAPH.CENTER and contents.paragraph_format.first_line_indent==0
 for title in ['АННОТАЦИЯ','1 НАЗНАЧЕНИЕ','7 ОЦЕНКА РИСКОВ']:
  p=next(p for p in d.paragraphs if p.text==title and (title=='АННОТАЦИЯ' or p.style is not None and p.style.name=='Heading 1'))
  assert round(p.paragraph_format.first_line_indent.cm,2)==1


def test_refined_header_color_and_compact_merged_table_headers():
 from app.stu_docx import INDICATOR_WIDTHS_CM
 d=document();header=d.sections[0].header.tables[0]
 right=header.cell(0,1)
 for p in right.paragraphs:
  for run in p.runs:
   if run.text:assert run.font.name=='Arial' and run.font.size.pt==9 and str(run.font.color.rgb)=='808080'
 fields=right._tc.xpath('.//w:fldSimple/w:r/w:rPr')
 assert len(fields)==2
 for pr in fields:
  assert pr.find(qn('w:sz')).get(qn('w:val'))=='18'
  assert pr.find(qn('w:color')).get(qn('w:val'))=='808080'
 for edge in header._tbl.xpath('.//w:tcBorders/*'):assert edge.get(qn('w:color'))=='000000'
 indicator=next(t for t in d.tables if len(t.columns)==11)
 assert all(abs(c.width.cm-expected)<.002 for c,expected in zip(indicator.columns,INDICATOR_WIDTHS_CM))
 assert_font(indicator,10)
 risk=next(t for t in d.tables if 'Возможный прецедент' in t.cell(0,0).text)
 for t in [risk,indicator]:
  for row in t.rows[:2]:
   for cell in row.cells:
    assert len(cell.paragraphs)==1
    assert cell.paragraphs[0].text.strip()
