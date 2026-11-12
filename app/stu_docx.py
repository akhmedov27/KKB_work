"""DOCX constructor based on the supplied hospital template, without Word runtime."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import re
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
from docx.enum.style import WD_STYLE_TYPE
from docx.text.paragraph import Paragraph
from docx.table import Table
from app.stu_schema import glossary_key
from docx.enum.section import WD_SECTION_START, WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

BASE=Path(__file__).parent/'assets'/'stu_base.docx'
INDICATOR_WIDTHS_CM=[0.490361,1.728611,0.779639,1.594556,1.852083,2.159,1.386417,2.007306,1.342319,1.852083,2.056694]
TITLE_BANNER='С И С Т Е М А  М Е Н Е Д Ж М Е Н Т А  К А Ч Е С Т В А'

INDICATORS=[('name','Показатель'),('unit','Ед. изм.'),('criterion','Критерий для сбора данных'),('target','Нормативное значение'),
 ('source','Источник сбора данных / источник просмотра данных'),('who','Кто вносит'),('what','Что вносит'),('where','Куда вносит'),
 ('frequency','Периодичность анализа'),('responsible','Ответственный')]


def clean(value):
 return re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]','',str(value))


def field(p,code,size=12,color=None):
 r=p.add_run();f=OxmlElement('w:fldSimple');f.set(qn('w:instr'),code);r._r.addnext(f)
 result=OxmlElement('w:r');pr=OxmlElement('w:rPr');fonts=OxmlElement('w:rFonts')
 for key in ['ascii','hAnsi','cs']:fonts.set(qn('w:'+key),'Arial')
 pr.append(fonts);sz=OxmlElement('w:sz');sz.set(qn('w:val'),str(size*2));pr.append(sz)
 if color:
  c=OxmlElement('w:color');c.set(qn('w:val'),color);pr.append(c)
 result.append(pr);cached=OxmlElement('w:t');cached.set(qn('xml:space'),'preserve');cached.text=' ';result.append(cached);f.append(result)


def appendix_name(value):
 value=value.strip()
 for i,char in enumerate(value):
  if char.isalpha():return value[:i]+char.upper()+value[i+1:]
 return value


def current_year():
 return datetime.now(timezone(timedelta(hours=7))).year


def set_russian_proofing(document):
 """Set inherited and explicit proofing language across every Word story."""
 language='ru-RU'
 defaults=document.styles.element.find(qn('w:docDefaults'))
 if defaults is None:
  defaults=OxmlElement('w:docDefaults');document.styles.element.insert(0,defaults)
 default=defaults.find(qn('w:rPrDefault'))
 if default is None:default=OxmlElement('w:rPrDefault');defaults.append(default)
 if default.find(qn('w:rPr')) is None:default.append(OxmlElement('w:rPr'))
 for part in document.part.package.parts:
  root=getattr(part,'element',None)
  if root is None:continue
  for run in root.iter(qn('w:r')):
   if run.find(qn('w:rPr')) is None:run.insert(0,OxmlElement('w:rPr'))
  for pr in root.iter(qn('w:rPr')):
   if pr.find(qn('w:lang')) is None:pr.append(OxmlElement('w:lang'))
  for lang in root.iter(qn('w:lang')):
   for slot in ['val','eastAsia','bidi']:lang.set(qn('w:'+slot),language)
  for tag in ['noProof','hideSpellingErrors','hideGrammaticalErrors']:
   for node in list(root.iter(qn('w:'+tag))):node.getparent().remove(node)
 settings=document.settings.element
 theme=settings.find(qn('w:themeFontLang'))
 if theme is None:theme=OxmlElement('w:themeFontLang');settings.append(theme)
 for slot in ['val','eastAsia','bidi']:theme.set(qn('w:'+slot),language)
 state=settings.find(qn('w:proofState'))
 if state is None:state=OxmlElement('w:proofState');settings.append(state)
 state.set(qn('w:spelling'),'dirty');state.set(qn('w:grammar'),'dirty')
 document.core_properties.language=language


def generate(content):
 d=Document(BASE);s=d.sections[0]
 training=[]
 for node in list(d.element.body)[1:]:
  if node.tag!=qn('w:sectPr'):training.append(deepcopy(node));d.element.body.remove(node)
 values=content.model_dump(mode='json')
 for key in ['order_date','effective_date']:
  value=getattr(content,key);values[key]=value.strftime('%d.%m.%Y') if value else ''
 values['order_number']=content.order_number or '_____'
 for row in d.tables[0].rows:
  seen=set()
  for cell in row.cells:
   if cell._tc in seen:continue
   seen.add(cell._tc)
   for p in cell.paragraphs:
    if ' '.join(p.text.split())==' '.join(TITLE_BANNER.split()):
     runs=[r for r in p.runs if r.text]
     if runs:
      runs[0].text=TITLE_BANNER
      for r in runs[1:]:r.text=''
    for r in p.runs:
     for key,value in values.items():
      if isinstance(value,(str,int)) and '{{'+key+'}}' in r.text:r.text=r.text.replace('{{'+key+'}}',clean(value))
 last=d.tables[0].rows[-1]
 cell=last.cells[0]
 if cell._tc is not last.cells[-1]._tc:cell=cell.merge(last.cells[-1])
 cell.text=f'Красноярск, {current_year()}'
 cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
 for p in cell.paragraphs:
  p.alignment=WD_ALIGN_PARAGRAPH.CENTER
  p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.left_indent=Cm(0);p.paragraph_format.right_indent=Cm(0)
  p.paragraph_format.space_before=Pt(0);p.paragraph_format.space_after=Pt(0)
  for r in p.runs:r.font.name='Arial';r.font.size=Pt(12)
 s.different_first_page_header_footer=True
 header=s.header
 t=header.tables[0] if header.tables else header.add_table(rows=1,cols=2,width=Cm(17.2))
 t.autofit=False
 tw=t._tbl.tblPr.find(qn('w:tblW'));tw.set(qn('w:type'),'dxa');tw.set(qn('w:w'),str(round(17.44*1440/2.54)))
 for col,cell,cm in zip(t.columns,t.rows[0].cells,[12.94,4.5]):
  col.width=Cm(cm);cell.width=Cm(cm)
 t.cell(0,0).text=f'СТУ {clean(content.number)} «{clean(content.title)}»'
 right_style=d.styles.add_style('StuHeaderRight',WD_STYLE_TYPE.PARAGRAPH)
 right_style.font.name='Arial';right_style.font.size=Pt(9);right_style.font.color.rgb=RGBColor.from_string('808080')
 right_style.paragraph_format.space_before=Pt(0);right_style.paragraph_format.space_after=Pt(0);right_style.paragraph_format.line_spacing=1
 c=t.cell(0,1);c.text='';p=c.paragraphs[0];p.add_run('Страница ');field(p,'PAGE',9,'808080');p.add_run(' из ');field(p,'NUMPAGES',9,'808080')
 p=c.add_paragraph('Редакция № '+str(content.edition))
 for index,cell in enumerate(t.rows[0].cells):
  for p in cell.paragraphs:
   if index==1:p.style=right_style
   p.paragraph_format.space_after=Pt(0)
   for r in p.runs:
    r.font.name='Arial';r.font.size=Pt(12 if index==0 else 9);r.font.color.rgb=RGBColor.from_string('000000' if index==0 else '808080')
 for cell in t.rows[0].cells:
  pr=cell._tc.get_or_add_tcPr()
  for old in list(pr.findall(qn('w:tcBorders'))):pr.remove(old)
  borders=OxmlElement('w:tcBorders')
  for side in ['top','left','bottom','right']:
   item=OxmlElement('w:'+side);item.set(qn('w:val'),'single');item.set(qn('w:sz'),'4');item.set(qn('w:color'),'000000');borders.append(item)
  cell._tc.get_or_add_tcPr().append(borders)
 # Word resolves TOC styles by styleId; a second case-variant name creates
 # duplicate TOC1 IDs and can restore Cambria when the contents field updates.
 for level in [1,2]:
  style_id=f'TOC{level}'
  matches=[style for style in d.styles if style.style_id==style_id]
  style=matches[0] if matches else d.styles.add_style(f'toc {level}',WD_STYLE_TYPE.PARAGRAPH,builtin=True)
  style.element.set(qn('w:styleId'),style_id)
  for duplicate in matches[1:]:duplicate.element.getparent().remove(duplicate.element)
  style.font.name='Arial';style.font.size=Pt(12)
  fonts=style.element.get_or_add_rPr().get_or_add_rFonts()
  for attr in list(fonts.attrib):del fonts.attrib[attr]
  for slot in ['ascii','hAnsi','cs','eastAsia']:fonts.set(qn('w:'+slot),'Arial')
  szcs=OxmlElement('w:szCs');szcs.set(qn('w:val'),'24');style.element.get_or_add_rPr().append(szcs)
  style.paragraph_format.first_line_indent=Cm(0)
 update=OxmlElement('w:updateFields');update.set(qn('w:val'),'true');d.settings.element.append(update)
 def para(text='',align=None):
  p=d.add_paragraph()
  p.paragraph_format.space_after=Pt(6);p.paragraph_format.first_line_indent=Cm(1)
  p.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY if align is None else align
  r=p.add_run(clean(text));r.font.name='Arial';r.font.size=Pt(12)
  return p
 def paragraphs(text):
  for line in text.splitlines():para(line)
 def heading(text,level=1):
  p=d.add_paragraph(style='Heading 1' if re.match(r'^\d+ ',text) or text.startswith('ПРИЛОЖЕНИЕ ') or text=='ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ' else None)
  p.paragraph_format.keep_with_next=True
  p.paragraph_format.first_line_indent=Cm(1);p.paragraph_format.left_indent=Cm(0)
  r=p.add_run(clean(text));r.bold=True;r.font.name='Arial';r.font.size=Pt(12)
  return p
 def newpage():d.add_page_break()
 tables=[]
 def table(headers,rows,shade='FDE9D9',size=12,kind='generic',widths=None):
  t=d.add_table(rows=1,cols=len(headers));t.autofit=False
  width=d.sections[-1].page_width-d.sections[-1].left_margin-d.sections[-1].right_margin
  weights=[1]*len(headers)
  if len(headers)==4:weights=[8.2,3.8,3,2.2]
  if len(headers)==5:weights=[1,1,1.3,2,4]
  if headers[0]=='№\nп/п':weights=[.8,3.2,*[(width/360000-4.0)/(len(headers)-2)]*(len(headers)-2)]
  if len(headers)==11:weights=[.6,2.3,1,1.5,1.7,2,1.2,1.3,1.2,1.5,1.5]
  for i,(col,w) in enumerate(zip(t.columns,weights)):col.width=Cm(widths[i]) if widths else int(width*w/sum(weights))
  for rowdata in [headers,*rows]:
   row=t.rows[0] if rowdata is headers else t.add_row()
   row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
   for cell,value,col in zip(row.cells,rowdata,t.columns):
    cell.width=col.width;cell.text=clean(value)
    pr=cell._tc.get_or_add_tcPr();b=OxmlElement('w:tcBorders')
    for side in ['top','left','bottom','right']:
     e=OxmlElement('w:'+side);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'000000');b.append(e)
    pr.append(b)
    for p in cell.paragraphs:
     p.paragraph_format.space_after=Pt(1);p.paragraph_format.space_before=Pt(1);p.paragraph_format.line_spacing=1
     for r in p.runs:r.font.name='Arial';r.font.size=Pt(size)
  for cell in t.rows[0].cells:
   if shade:
    sh=OxmlElement('w:shd');sh.set(qn('w:fill'),shade);cell._tc.get_or_add_tcPr().append(sh)
   for r in cell.paragraphs[0].runs:r.bold=True
  t.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
  tables.append({'table':t,'size':size,'shade':shade,'headers':1,'kind':kind})
  return t
 def second_header(t,labels):
  next(item for item in tables if item['table'] is t)['headers']=2
  row=t.add_row()
  for c,label in zip(row.cells,labels):
   c.text=label
   for p in c.paragraphs:
    for r in p.runs:r.font.name='Arial';r.font.size=Pt(8);r.bold=True
  t._tbl.remove(row._tr);t._tbl.insert(3,row._tr)
  row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
  return row
 newpage();heading('ЛИСТ СОГЛАСОВАНИЯ')
 table(['Ответственность','Должность','Фамилия,\nинициалы','Подпись','Дата'],[[r.role,r.position,r.person,'',''] for r in content.approvals],shade=None,size=10,kind='approval',widths=[3.5,5.44,3.25,2.5,2.5])
 newpage();heading('АННОТАЦИЯ');paragraphs(content.annotation)
 newpage();toc_heading=heading('СОДЕРЖАНИЕ');toc_heading.alignment=WD_ALIGN_PARAGRAPH.CENTER;toc_heading.paragraph_format.first_line_indent=Cm(0);p=para()
 begin=OxmlElement('w:fldChar');begin.set(qn('w:fldCharType'),'begin');p.add_run()._r.append(begin)
 instr=OxmlElement('w:instrText');instr.text=' TOC \\o "1-2" \\h \\z \\u ';p.add_run()._r.append(instr)
 separate=OxmlElement('w:fldChar');separate.set(qn('w:fldCharType'),'separate');p.add_run()._r.append(separate)
 headings=['1 НАЗНАЧЕНИЕ','2 ОБЛАСТЬ ПРИМЕНЕНИЯ','3 НОРМАТИВНЫЕ ССЫЛКИ','4 СОКРАЩЕНИЯ И ОБОЗНАЧЕНИЯ','5 ОТВЕТСТВЕННОСТЬ','6 ОПИСАНИЕ ПРОЦЕССА']
 headings += [f'6.{i} {appendix_name(name)}' for i,name in enumerate(content.processes,1)]
 headings += ['7 ОЦЕНКА РИСКОВ','8 ПОКАЗАТЕЛИ ПРОЦЕССА','9 ВНЕСЕНИЕ ИЗМЕНЕНИЙ','10 ХРАНЕНИЕ']
 headings += [f'ПРИЛОЖЕНИЕ {i}. {appendix_name(name)}' for i,name in enumerate(content.appendices,1)]
 if content.edition>1:headings.append('ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ')
 headings.append('ВЕДОМОСТЬ ОБУЧЕНИЯ И ОЗНАКОМЛЕНИЯ СО СТАНДАРТОМ')
 for name in headings:
  p=para(name,WD_ALIGN_PARAGRAPH.LEFT);p.style=next(style for style in d.styles if style.style_id=='TOC1');p.paragraph_format.first_line_indent=Cm(0)
 end=OxmlElement('w:fldChar');end.set(qn('w:fldCharType'),'end');p.add_run()._r.append(end)
 para('Обновите содержание в Word: щёлкните по содержанию и выберите «Обновить поле».')
 newpage()
 for title,key in [('1 НАЗНАЧЕНИЕ','purpose'),('2 ОБЛАСТЬ ПРИМЕНЕНИЯ','scope'),('3 НОРМАТИВНЫЕ ССЫЛКИ','references')]:
  heading(title);paragraphs(getattr(content,key))
 heading('4 СОКРАЩЕНИЯ И ОБОЗНАЧЕНИЯ')
 for row in sorted(content.abbreviation_rows,key=lambda row:glossary_key(row.name)):
  para(f'{row.name.strip()} - {row.meaning.strip()}')
 if content.abbreviations.strip():paragraphs(content.abbreviations)
 for row in sorted(content.term_rows,key=lambda row:glossary_key(row.name)):
  p=para();r=p.add_run(clean(row.name.strip()));r.bold=True;r.font.name='Arial';r.font.size=Pt(12)
  r=p.add_run(clean(' - '+row.meaning.strip()));r.bold=False;r.font.name='Arial';r.font.size=Pt(12)
 heading('5 ОТВЕТСТВЕННОСТЬ')
 para(f'Ответственность за правильность разработки, внедрение и исполнение настоящего стандарта учреждения несет {content.owner}.')
 para('Ответственность за выполнение требований настоящего стандарта учреждения также возлагается на сотрудников подразделений в соответствии с таблицей 1 «Матрица ответственности».')
 if content.matrix_landscape:
  sec=d.add_section(WD_SECTION_START.NEW_PAGE);sec.orientation=WD_ORIENT.LANDSCAPE;sec.page_width,sec.page_height=Cm(29.7),Cm(21);sec.different_first_page_header_footer=False
 para('Таблица 1 — Матрица ответственности')
 t=table(['№\nп/п','Наименование подразделения',*['Должность']*len(content.positions)],
  [[i,r.name,*['V' if x else '' for x in r.marks]] for i,r in enumerate(content.departments,1)],shade='D9D9D9',size=10,kind='matrix')
 row=second_header(t,['','',*content.positions])
 t.cell(0,0).merge(t.cell(1,0));t.cell(0,1).merge(t.cell(1,1))
 if len(content.positions)>1:t.cell(0,2).merge(t.cell(0,len(content.positions)+1)).text='Должность'
 row=t.add_row();row.cells[0].merge(row.cells[-1]).text='Сотрудники КГБУЗ ККБ должны знать и выполнять требования настоящего стандарта учреждения'
 if content.matrix_landscape:
  sec=d.add_section(WD_SECTION_START.NEW_PAGE);sec.orientation=WD_ORIENT.PORTRAIT;sec.page_width,sec.page_height=Cm(21),Cm(29.7);sec.different_first_page_header_footer=False
 heading('6 ОПИСАНИЕ ПРОЦЕССА')
 paragraphs(content.process_custom or f'Порядок {content.process_name} представлен в виде квалиграммы и текстового описания к ней.')
 for i,name in enumerate(content.processes,1):
  newpage();t=table([''],[[''],[f'6.{i} {appendix_name(name)}'],['']],shade=None,size=24,kind='process')
  t._tbl.remove(t.rows[0]._tr)
  for row,height in zip(t.rows,[9.846,2.845,11.465]):row.height=Cm(height)
  p=t.rows[1].cells[0].paragraphs[0];p.alignment=WD_ALIGN_PARAGRAPH.CENTER
  # A real heading in the middle cell is included in Word TOC.
  ppr=p._p.get_or_add_pPr();o=OxmlElement('w:outlineLvl');o.set(qn('w:val'),'1');ppr.append(o)
  graph=content.qualigrams.get(content.process_ids[i-1])
  landscape=graph is not None and graph.orientation=='landscape'
  if landscape:
   sec=d.add_section(WD_SECTION_START.NEW_PAGE);sec.orientation=WD_ORIENT.LANDSCAPE;sec.page_width,sec.page_height=Cm(29.7),Cm(21);sec.different_first_page_header_footer=False
  else:newpage()
  para('Квалиграмма',WD_ALIGN_PARAGRAPH.LEFT)
  if graph:
   from app.qualigram_render import png
   sec=d.sections[-1];available_w=sec.page_width-sec.left_margin-sec.right_margin
   available_h=sec.page_height-sec.top_margin-sec.bottom_margin-Cm(1.8)
   scale=min(available_w/graph.width,available_h/graph.height)
   pic=d.add_paragraph();pic.paragraph_format.space_after=Pt(0)
   pic.add_run().add_picture(BytesIO(png(graph,name)),width=int(graph.width*scale),height=int(graph.height*scale))
  if landscape:
   sec=d.add_section(WD_SECTION_START.NEW_PAGE);sec.orientation=WD_ORIENT.PORTRAIT;sec.page_width,sec.page_height=Cm(21),Cm(29.7);sec.different_first_page_header_footer=False
  else:newpage()
  para('Текстовое описание к квалиграмме',WD_ALIGN_PARAGRAPH.LEFT)
  if graph:paragraphs(graph.description)
 newpage();heading('7 ОЦЕНКА РИСКОВ')
 t=table(['Возможный прецедент','Риски','Риски','Ранг'],[[r.event,r.probability,r.impact,r.rank] for r in content.risks],kind='risk')
 second_header(t,['','Вероятность','Влияние','']);t.cell(0,0).merge(t.cell(1,0));t.cell(0,3).merge(t.cell(1,3));t.cell(0,1).merge(t.cell(0,2)).text='Риски'
 heading('8 ПОКАЗАТЕЛИ ПРОЦЕССА')
 t=table(['№',*[label for _,label in INDICATORS]],[[i,*[getattr(r,k) for k,_ in INDICATORS]] for i,r in enumerate(content.indicators,1)],size=10,kind='indicator',widths=INDICATOR_WIDTHS_CM)
 second_header(t,['','','','','','','Кто вносит','Что вносит','Куда вносит','Периодичность анализа','Ответственный'])
 for i in range(6):t.cell(0,i).merge(t.cell(1,i))
 t.cell(0,6).merge(t.cell(0,8)).text='Внесение данных';t.cell(0,9).merge(t.cell(0,10)).text='Проведение анализа данных для управления процессом'
 heading('9 ВНЕСЕНИЕ ИЗМЕНЕНИЙ')
 para(f'Предложения по внесению изменений в содержание настоящего стандарта может внести любой сотрудник. Предложения передаются {content.proposals_to}.')
 para(f'Внесение изменений в подлинник настоящего стандарта производит {content.changes_owner} совместно с менеджером ответственным за систему менеджмента качества.')
 heading('10 ХРАНЕНИЕ')
 for line in ['Подлинник настоящего стандарта хранится в отделе системе менеджмента качества.','Срок хранения подлинника – до минования надобности.',
 'Электронная версия утвержденного стандарта располагается на сетевых ресурсах КГБУЗ ККБ:',
 '– www.medics.medgorod.ru//Портал/Обучение/База знаний (https://medics.medgorod.ru/components/edu/wiki);',
 '– Обмен// 4_ДОКУМЕНТЫ ККБ/1 СТАНДАРТЫ УЧРЕЖДЕНИЯ.']:para(line)
 for i,name in enumerate(content.appendices,1):
  newpage();p=heading(f'ПРИЛОЖЕНИЕ {i}');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
  p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.left_indent=Cm(0);p.paragraph_format.right_indent=Cm(0)
  r=p.add_run();r.add_break();r.font.name='Arial';r.font.size=Pt(12);r.bold=True
  r=p.add_run(clean(appendix_name(name)));r.font.name='Arial';r.font.size=Pt(12);r.bold=True
 if content.edition>1:
  newpage();heading('ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ')
  t=table(['Редакция','№ изменения','Страница изменения','Вид изменения','Краткое описание изменений'],[[f'Ред. {content.edition}',i,r.pages,r.kind,r.description] for i,r in enumerate(content.changes,1)])
  if len(content.changes)>1:t.cell(1,0).merge(t.cell(len(content.changes),0)).text=f'Ред. {content.edition}'
 newpage()
 for node in training:
  # Preserve the source layout (including row heights/blank paragraphs), but make
  # inherited text fonts explicit so Word does not substitute Cambria/Times.
  node=deepcopy(node)
  for element in node.iter(qn('w:p')):
   p=Paragraph(element,d)
   if 'ОБУЧЕНИЯ  И' in p.text:
    for run in p.runs:run.text=run.text.replace('ОБУЧЕНИЯ  И','ОБУЧЕНИЯ И')
   if p.text.strip() and p.style.name=='Heading 1':p.paragraph_format.first_line_indent=Cm(1);p.paragraph_format.left_indent=Cm(0)
   if not p.runs:p.add_run()
   for r in p.runs:
    r.font.name='Arial';r.font.size=Pt(12)
    if 'Обучение прошел, со стандартом ознакомлен:' in p.text:r.bold=True
  d.element.body.insert(len(d.element.body)-1,node)
 for item in tables:
  t=item['table']
  process=item['kind']=='process'
  for ri,row in enumerate(t.rows):
   if item['kind']=='approval' and ri>0:
    row.height=Cm(1);row.height_rule=WD_ROW_HEIGHT_RULE.AT_LEAST
   seen=set()
   for cell in row.cells:
    if cell._tc in seen:continue
    seen.add(cell._tc)
    if item['kind'] in ['risk','indicator','matrix']:
     for paragraph in list(cell.paragraphs):
      if len(cell.paragraphs)>1 and not paragraph.text.strip() and not paragraph._p.xpath('.//w:drawing | .//w:fldChar | .//w:fldSimple'):
       cell._tc.remove(paragraph._p)
    pr=cell._tc.get_or_add_tcPr()
    for old in list(pr):
     if old.tag in (qn('w:tcBorders'),qn('w:shd')):pr.remove(old)
    borders=OxmlElement('w:tcBorders')
    for side in ['top','left','bottom','right']:
     edge=OxmlElement('w:'+side);edge.set(qn('w:val'),'nil' if process else 'single');edge.set(qn('w:sz'),'4');edge.set(qn('w:color'),'000000');borders.append(edge)
    pr.append(borders)
    color='F2F2F2' if process and ri==1 else item['shade'] if not process and ri<item['headers'] else None
    if color:
     shade=OxmlElement('w:shd');shade.set(qn('w:fill'),color);pr.append(shade)
    if item['kind'] in ['approval','matrix','process','risk','indicator']:cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for p in cell.paragraphs:
     p.paragraph_format.space_after=Pt(1);p.paragraph_format.space_before=Pt(1);p.paragraph_format.line_spacing=1;p.paragraph_format.first_line_indent=Cm(0)
     if item['kind'] in ['approval','matrix','process','risk','indicator']:
      p.alignment=WD_ALIGN_PARAGRAPH.LEFT if item['kind']=='risk' and ri>=item['headers'] and cell._tc is row.cells[0]._tc else WD_ALIGN_PARAGRAPH.CENTER
     for r in p.runs:r.font.name='Arial';r.font.size=Pt(item['size']);r.bold=not process and ri<item['headers']
 # Write borders on physical continuation cells too; python-docx row.cells
 # aliases vertical merges to their origin and otherwise leaves gaps in the frame.
 for item in tables:
  if item['kind']=='process':continue
  rows=[]
  for tr in item['table']._tbl.tr_lst:
   cells={};col=0
   for tc in tr.tc_lst:
    cells[col]=tc;span=tc.tcPr.find(qn('w:gridSpan')) if tc.tcPr is not None else None
    col+=int(span.get(qn('w:val'))) if span is not None else 1
   rows.append(cells)
  for ri,cells in enumerate(rows):
   for col,tc in cells.items():
    pr=tc.get_or_add_tcPr();merge=pr.find(qn('w:vMerge'))
    continuation=merge is not None and merge.get(qn('w:val'),'continue')=='continue'
    next_tc=rows[ri+1].get(col) if ri+1<len(rows) else None
    next_merge=next_tc.tcPr.find(qn('w:vMerge')) if next_tc is not None and next_tc.tcPr is not None else None
    continues=next_merge is not None and next_merge.get(qn('w:val'),'continue')=='continue'
    for old in list(pr.findall(qn('w:tcBorders'))):pr.remove(old)
    borders=OxmlElement('w:tcBorders')
    for side in ['top','left','bottom','right']:
     edge=OxmlElement('w:'+side);edge.set(qn('w:val'),'nil' if (side=='top' and continuation) or (side=='bottom' and continues) else 'single');edge.set(qn('w:sz'),'4');edge.set(qn('w:color'),'000000');borders.append(edge)
    pr.append(borders)
 d.core_properties.title=clean('СТУ '+content.number+' '+content.title);d.core_properties.author='ККБ'
 set_russian_proofing(d)
 output=BytesIO();d.save(output);return output.getvalue()
