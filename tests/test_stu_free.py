from copy import deepcopy
from io import BytesIO
import json
import re
from zipfile import ZipFile
from docx import Document
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session
import pytest
from app.config import Settings
from app.main import create_app
from app.database import build_engine
from app.models import StuDraft
from app.stu_schema import StuContent
from app.stu_sections import outline
from tests.test_stu import client,content


def free_content():
 return {'mode':'free','number':'ТЕСТ-1','title':'Свободный тестовый стандарт','edition':1,
  'annotation':'Синтетический пример свободной структуры.',
  'approvals':[{'role':'Разработал','position':'Специалист','person':'Тестов Т. Т.'}],
  'sections':[
   {'id':'first','title':'Первый раздел','blocks':[{'id':'body','kind':'text','text':'Первый абзац.\nВторой абзац.'}],
    'subsections':[{'id':'child','title':'Детали','blocks':[{'id':'child-text','kind':'text','text':'Текст подраздела.'}]}]},
   {'id':'second','title':'Порядок работы','blocks':[{'id':'table','kind':'table','title':'Проверочные данные','headers':['Действие','Исполнитель'],
    'rows':[['Проверить синтетическую заявку','Специалист'],['=1+1','<script>текст</script>']]}],'subsections':[]}]
 }


def initial(c,id):
 text=c.get(f'/stu/{id}').text
 return json.loads(re.search(r'<script id="stu-data" type="application/json">(.*?)</script>',text,re.S)[1])


def create_free(c,base='empty'):
 r=c.post('/stu',data={'mode':'free','base':base},follow_redirects=False)
 assert r.status_code==303
 return int(r.headers['location'].split('/')[-1])


def test_modes_template_and_legacy_default(client):
 c,path=client
 normal=c.post('/stu',follow_redirects=False).headers['location'];assert initial(c,int(normal.split('/')[-1]))['content']['mode']=='standard'
 empty=create_free(c);assert initial(c,empty)['content']['sections']==[]
 seeded=create_free(c,'kkb');data=initial(c,seeded)['content'];assert data['mode']=='free' and len(data['sections'])==10
 assert [s['title'] for s in data['sections']][:2]==['НАЗНАЧЕНИЕ','ОБЛАСТЬ ПРИМЕНЕНИЯ']
 assert c.post('/stu',data={'mode':'unknown'}).status_code==422
 assert c.post('/stu',data={'mode':'free','base':'unknown'}).status_code==422
 # Old payloads keep the standard mode without a migration or manual conversion.
 id=int(normal.split('/')[-1]);engine=build_engine(path/'qms.sqlite3')
 with Session(engine) as db:db.get(StuDraft,id).payload_json=json.dumps(content());db.commit()
 engine.dispose()
 assert initial(c,id)['content']['mode']=='standard'
 assert c.get(f'/stu/{id}/export.docx').status_code==200


def test_save_reload_copy_restart_conflict_and_safe_html(client):
 c,path=client;id=create_free(c);data=free_content();data['sections'][0]['title']='Раздел <script>опасный</script>'
 saved=c.put(f'/stu/{id}',json={'version':1,'content':data});assert saved.status_code==200 and saved.json()['errors']==[]
 assert c.put(f'/stu/{id}',json={'version':1,'content':data}).status_code==409
 assert '<script>опасный</script>' not in c.get(f'/stu/{id}').text
 clone=c.post(f'/stu/{id}/copy',follow_redirects=False).headers['location']
 assert initial(c,int(clone.split('/')[-1]))['content']==StuContent.model_validate(data).model_dump(mode='json')
 with TestClient(create_app(Settings(data_dir=path,_env_file=None))) as restart:
  assert initial(restart,id)['content']==initial(c,id)['content']


def test_custom_docx_outline_fonts_tables_and_shared_sheets(client):
 c,_=client;id=create_free(c)
 assert c.put(f'/stu/{id}',json={'version':1,'content':free_content()}).json()['errors']==[]
 result=c.get(f'/stu/{id}/export.docx');assert result.status_code==200
 doc=Document(BytesIO(result.content))
 headings=[(p.text,p.style.name) for p in doc.paragraphs if p.style is not None and p.style.name in ('Heading 1','Heading 2')]
 assert ('1 Первый раздел','Heading 1') in headings and ('1.1 Детали','Heading 2') in headings and ('2 Порядок работы','Heading 1') in headings
 assert not any('НАЗНАЧЕНИЕ' in p.text or 'ОЦЕНКА РИСКОВ' in p.text for p in doc.paragraphs)
 assert any(p.text=='Первый абзац.' for p in doc.paragraphs)
 assert any(p.text=='Второй абзац.' for p in doc.paragraphs)
 assert any(p.text=='Таблица 1 — Проверочные данные' for p in doc.paragraphs)
 table=next(t for t in doc.tables if t.cell(0,0).text=='Действие')
 assert table.cell(2,0).text=='=1+1' and table.cell(2,1).text=='<script>текст</script>'
 for row in table.rows:
  for cell in row.cells:
   for p in cell.paragraphs:
    for r in p.runs:assert r.font.name=='Arial' and r.font.size.pt==12
 assert len(doc.tables[-1].rows)==48 and len(doc.inline_shapes)>=1
 assert abs(doc.sections[0].header.tables[0].cell(0,0).width.cm-12.94)<.003
 for p in doc.paragraphs:
  if p.style is not None and p.style.name in ('Heading 1','Heading 2') and p.text[:1].isdigit():assert abs(p.paragraph_format.first_line_indent.cm-1)<.003
 with ZipFile(BytesIO(result.content)) as z:
  xml=z.read('word/document.xml').decode();assert 'TOC ' in xml and 'ru-RU' in xml and 'TOC2' in xml
  assert not any('TargetMode="External"' in z.read(n).decode() for n in z.namelist() if n.endswith('.rels'))


def test_renumber_reorder_delete_and_edition_changes(client):
 c,_=client;id=create_free(c);data=free_content();data['sections'].reverse()
 c.put(f'/stu/{id}',json={'version':1,'content':data})
 doc=Document(BytesIO(c.get(f'/stu/{id}/export.docx').content))
 assert any(p.text=='1 Порядок работы' for p in doc.paragraphs)
 assert any(p.text=='2.1 Детали' for p in doc.paragraphs)
 data['sections'].pop();data['edition']=2
 r=c.put(f'/stu/{id}',json={'version':2,'content':data});assert r.json()['errors']
 assert c.get(f'/stu/{id}/export.docx').status_code==400
 data.update(changes_reviewed=True,changes=[{'pages':'5','kind':'Исключено','description':'Удалён раздел'}])
 assert c.put(f'/stu/{id}',json={'version':3,'content':data}).json()['errors']==[]
 doc=Document(BytesIO(c.get(f'/stu/{id}/export.docx').content))
 assert any(p.text=='ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ' for p in doc.paragraphs)
 assert not any('Детали' in p.text for p in doc.paragraphs)


@pytest.mark.parametrize('mutation',[
 lambda d:d['sections'][1]['blocks'][0].update(headers=[]),
 lambda d:d['sections'][1]['blocks'][0].update(rows=[['Одна ячейка']]),
 lambda d:d['sections'][1]['blocks'][0].update(rows=[['','']]*51),
 lambda d:d['sections'][0]['blocks'][0].update(kind='script'),
 lambda d:d['sections'][0].update(id='second'),
 lambda d:d['sections'][0]['blocks'][0].update(id='child'),
 lambda d:d['sections'][0].update(title='x'*501),
])
def test_invalid_structure_does_not_replace_saved_draft(client,mutation):
 c,_=client;id=create_free(c);data=free_content();c.put(f'/stu/{id}',json={'version':1,'content':data});before=initial(c,id)
 bad=deepcopy(data);mutation(bad)
 assert c.put(f'/stu/{id}',json={'version':2,'content':bad}).status_code==400
 assert initial(c,id)==before


def test_incomplete_free_draft_and_limits():
 data=StuContent(mode='free');assert any('один раздел' in e for e in data.export_errors())
 # No legacy mandatory matrix/process/risk requirements in free mode.
 data=free_content();data['sections'][1]['blocks'][0]['rows']=[['','']]
 errors=StuContent.model_validate(data).export_errors()
 assert any('данные таблицы' in e for e in errors)
 assert not any('Матрица' in e or 'Возможные прецеденты' in e for e in errors)
 data=free_content();data['sections']=[{'id':f's{i}','title':'Раздел','blocks':[],'subsections':[{'id':f'sub{i}','title':'Подраздел'}]} for i in range(26)]
 with pytest.raises(ValidationError):StuContent.model_validate(data)
 data=free_content();data['sections']=[{'id':f's{i}','title':'Раздел','blocks':[{'id':f'b{i}','kind':'table','headers':['']*10,'rows':[['']*10 for _ in range(50)]}]} for i in range(10)]
 with pytest.raises(ValidationError):StuContent.model_validate(data)
