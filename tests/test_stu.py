from contextlib import closing
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
import pytest
from app.config import Settings
from app.main import create_app
from app.database import build_engine, SCHEMA_VERSION
from app.models import ChatMessage, Document as StoredDocument, StuDraft
from app.stu_schema import StuContent


def content(edition=1):
 return {'number':'24.2-2026','title':'Тестовый стандарт учреждения','edition':edition,'order_number':'','order_date':None,'effective_date':None,
  'approvals':[{'role':'Согласовал','position':'Руководитель','person':'Тестов Т. Т.'},{'role':'Разработал','position':'Специалист','person':'Примеров П. П.'}],
  'annotation':'Тестовая аннотация.','purpose':'Назначение.','scope':'Область.','references':'Нормативные ссылки.','abbreviations':'СТУ — стандарт учреждения.',
  'owner':'руководитель подразделения','positions':['Руководитель','Врач','Медсестра'],
  'departments':[{'name':'Подразделение А','marks':[True,False,True]},{'name':'Подразделение Б','marks':[False,True,False]}],
  'matrix_landscape':False,'process_name':'тестового процесса','process_custom':'','processes':['Тестовый процесс'],
  'risks':[{'event':'Тестовый прецедент','probability':4,'impact':5}],
  'indicators':[dict(name='Тестовый показатель',unit='шт.',criterion='Каждый случай',target='Задано пользователем',source='Реестр',who='Сотрудник',what='Значение',where='Реестр',frequency='Ежемесячно',responsible='Руководитель')],
  'proposals_to':'ответственному','changes_owner':'специалист','appendices':['Тестовое приложение'],
  'changes_reviewed':edition>1,'changes':[{'pages':'8, 9','kind':'Измененная редакция','description':'Обновлено описание'},{'pages':'10','kind':'Введено впервые','description':'Добавлен раздел'}] if edition>1 else []}

@pytest.fixture
def client(tmp_path):
 with TestClient(create_app(Settings(data_dir=tmp_path,_env_file=None))) as c:yield c,tmp_path

def create(c):
 r=c.post('/stu',follow_redirects=False);assert r.status_code==303;return int(r.headers['location'].split('/')[-1])

def full_text(d):return '\n'.join([p.text for p in d.paragraphs]+[cell.text for t in d.tables for row in t.rows for cell in row.cells])

def test_draft_restart_conflict_copy_and_escape(client):
 c,path=client;id=create(c);payload=content();payload['title']='<script>Тест</script>'
 assert c.put(f'/stu/{id}',json={'version':1,'content':payload}).json()['version']==2
 assert c.put(f'/stu/{id}',json={'version':1,'content':content()}).status_code==409
 html=c.get(f'/stu/{id}').text;assert '<script>Тест</script>' not in html and '\\u003cscript\\u003e' in html
 copy=c.post(f'/stu/{id}/copy',follow_redirects=False);assert copy.status_code==303
 with TestClient(create_app(Settings(data_dir=path,_env_file=None))) as restart:
  assert '\\u003cscript\\u003e' in restart.get(f'/stu/{id}').text
  assert c.get(copy.headers['location']).status_code==200

@pytest.mark.parametrize('edition',[1,4])
def test_docx_structure_fields_ranks_training_and_no_external_links(client,edition):
 c,_=client;id=create(c);data=content(edition)
 saved=c.put(f'/stu/{id}',json={'version':1,'content':data});assert saved.status_code==200 and saved.json()['errors']==[]
 result=c.get(f'/stu/{id}/export.docx');assert result.status_code==200
 d=Document(BytesIO(result.content));body=full_text(d)
 for heading in ['1 НАЗНАЧЕНИЕ','4 СОКРАЩЕНИЯ И ОБОЗНАЧЕНИЯ','5 ОТВЕТСТВЕННОСТЬ','8 ПОКАЗАТЕЛИ ПРОЦЕССА','10 ХРАНЕНИЕ','Квалиграмма','Текстовое описание к квалиграмме','ПРИЛОЖЕНИЕ 1','ВЕДОМОСТЬ ОБУЧЕНИЯ']:
  assert heading in body
 assert ('ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ' in body)==(edition>1)
 assert '12.5-2020' not in body and 'препаратов калия' not in body
 risk=next(t for t in d.tables if 'Возможный прецедент' in t.cell(0,0).text)
 assert risk.rows[2].cells[3].text=='20'
 approvals=d.tables[1]
 assert all(row.cells[3].text=='' and row.cells[4].text=='' for row in approvals.rows[1:])
 assert len(d.tables[-1].rows)==48
 assert len(d.element.xpath('.//w:drawing'))>=1  # preserve the supplied logo
 matrix=next(t for t in d.tables if 'Наименование подразделения' in t.cell(0,1).text)
 assert [c.text for c in matrix.rows[2].cells[2:]]==['V','','V']
 with ZipFile(BytesIO(result.content)) as z:
  assert 'TOC ' in z.read('word/document.xml').decode()
  header=''.join(z.read(n).decode() for n in z.namelist() if n.startswith('word/header') and n.endswith('.xml'))
  assert 'PAGE' in header and 'NUMPAGES' in header and '24.2-2026' in header
  assert 'Редакция № '+str(edition) in header
  assert 'w:highlight' not in z.read('word/document.xml').decode()
  assert not any('TargetMode="External"' in z.read(n).decode() for n in z.namelist() if n.endswith('.rels'))

@pytest.mark.parametrize('change',[{'edition':0},{'risks':[{'event':'x','probability':6,'impact':1}]},{'departments':[{'name':'x','marks':[True]}]},{'number':'x'*501}])
def test_invalid_payload_never_overwrites(client,change):
 c,path=client;id=create(c);base=content();c.put(f'/stu/{id}',json={'version':1,'content':base})
 assert c.put(f'/stu/{id}',json={'version':2,'content':{**base,**change}}).status_code==400
 engine=build_engine(path/'qms.sqlite3')
 with Session(engine) as db:assert json.loads(db.get(StuDraft,id).payload_json)==StuContent.model_validate(base).model_dump(mode='json')
 engine.dispose()

def test_incomplete_draft_and_second_edition_require_explicit_changes(client):
 c,_=client;id=create(c)
 assert c.get(f'/stu/{id}/export.docx').status_code==400
 data=content(2);data['changes_reviewed']=False
 response=c.put(f'/stu/{id}',json={'version':1,'content':data});assert response.status_code==200 and response.json()['errors']
 assert c.get(f'/stu/{id}/export.docx').status_code==400
 data['changes_reviewed']=True
 assert c.put(f'/stu/{id}',json={'version':2,'content':data}).json()['errors']==[]
 assert c.get(f'/stu/{id}/export.docx').status_code==200
 assert c.get('/stu/999').status_code==404

def test_landscape_matrix_and_portrait_restored(client):
 c,_=client;id=create(c);data=content();data['matrix_landscape']=True
 c.put(f'/stu/{id}',json={'version':1,'content':data})
 response=c.get(f'/stu/{id}/export.docx');assert response.status_code==200
 d=Document(BytesIO(response.content))
 assert len(d.sections)==3
 assert d.sections[1].page_width>d.sections[1].page_height
 assert d.sections[2].page_width<d.sections[2].page_height

def test_current_app_has_no_removed_features_or_ai(client,monkeypatch):
 c,path=client
 import app.ai_service
 monkeypatch.setattr(app.ai_service.AIService,'__init__',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No AI in current app')))
 assert c.get('/').status_code==200
 html=c.get('/').text
 assert 'Конструктор СТУ' in html and 'chat-form' not in html
 for label in ['База знаний','История диалогов','ИИ-провайдер','/modules/risks']:assert label not in html
 for url in ['/modules/knowledge','/modules/documents','/modules/risks','/documents/1']:assert c.get(url).status_code==404
 assert c.post('/chat',data={'message':'тест'}).status_code==404
 assert c.post('/uploads',files={'file':('x.pdf',b'x')}).status_code==404
 assert c.get('/health').json()['provider']=='disabled'
 with TestClient(create_app(Settings(data_dir=path,_env_file=None))) as restarted:
  assert restarted.get('/health').status_code==200

def test_v5_upgrade_backup_preserves_existing_data(tmp_path):
 path=tmp_path/'qms.sqlite3'
 with TestClient(create_app(Settings(data_dir=tmp_path,_env_file=None))):pass
 with closing(sqlite3.connect(path)) as db:
  db.execute('DROP TABLE stu_drafts');db.execute('PRAGMA user_version=5')
  db.execute("INSERT INTO documents(original_name,stored_name,size,created_at) VALUES ('old.pdf','old.pdf',3,'2026-01-01')");db.commit()
 with TestClient(create_app(Settings(data_dir=tmp_path,_env_file=None))) as c:
  assert c.get('/health').json()['schema_version']==6
  assert c.get('/modules/stu').status_code==200
 with closing(sqlite3.connect(path)) as db:assert db.execute('SELECT original_name FROM documents').fetchone()==('old.pdf',)
 assert list((tmp_path/'backups').glob('qms-before-v6-*.sqlite3'))
