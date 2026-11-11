from contextlib import closing
from datetime import date, datetime
from io import BytesIO
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_engine, SCHEMA_VERSION
from app.incident_excel import inspect, parse, IncidentValidationError
from app.incident_import import confirm
from app.incident_stats import Filters, statistics
from app.main import create_app
from app.models import IncidentBatch, IncidentRecord, IncidentStagedRow

HEADERS = ['№','Номер инцидента','Дата инцидента','Время инцидента','Дата регистрации','Дата регистрации',
           'Время регистрации','Способ зарегистрирован','Триггер','ФИО зарегистрировавшего',
           'Основное место работы зарегистрировавшего','Важность','№ИБ','Отделение госпитализации пациента',
           'Тип отделения','Группа','Подгруппа','Неблагоприятное событие (наименование инцидента)',
           'Произвольное наименование','Ручной ввод данных отделом СМК в процессе анализа','Причина при регистрации',
           'Корневая причина','Ответственный','Необходимость срочных мер','Статус','Описание неблагоприятного события',
           'Коментарий к закрытию','Лечащий врач','Отделение']


def fixture_body(conflict=False, invalid=False, formula=False):
    workbook = Workbook(); sheet = workbook.active; sheet.title='Реестр'
    sheet.append(HEADERS)
    for ordinal, external, day, dept, group in [(1,100,datetime(2026,1,2),'  Отделение   А ','Падения'),
                 (2,100,datetime(2026,1,2),'Отделение Б' if conflict else 'Отделение А','Падения'),
                 (3,101,datetime(2026,3,3),'Отделение Б','Лекарственная безопасность'),
                 (4,102,datetime(2025,12,31),'NULL','Падения')]:
        row = [None]*29
        for column,value in {0:ordinal,1:external,2:day,4:'2026-01',5:'02.01.2026',7:'Портал',9:'DO_NOT_IMPORT_NAME',
            11:'A',12:'DO_NOT_IMPORT_PATIENT',13:dept,14:'Терапия',15:group,16:'Подгруппа',18:'Событие из резервного поля',
            21:'Проверка',23:'нет',24:'Завершено без улучшений',25:'DO_NOT_IMPORT_DESCRIPTION',28:'Не то отделение'}.items():row[column]=value
        sheet.append(row)
    if invalid or formula:
        row=[None]*29;row[1]=103;row[2]='=TODAY()' if formula else '31.02.2026';sheet.append(row)
    output=BytesIO();workbook.save(output);workbook.close();return output.getvalue()


@pytest.fixture
def local(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path,_env_file=None))) as client:
        yield client,tmp_path


def prepare_via_http(client, body=None):
    response=client.post('/incidents/uploads',files={'file':('test.xlsx',body or fixture_body())})
    assert response.status_code==200
    upload_id=response.url.path.rsplit('/',1)[-1]
    config={key:str(value) if value else '' for key,value in {
        'external_id':2,'occurred_on':3,'registered_on':6,'department':14,'department_type':15,'group_name':16,'subgroup':17,
        'event_name':18,'event_fallback':19,'importance':12,'status':25,'urgent':24,'source_method':8,'root_cause':22}.items()}
    response=client.post(f'/incidents/uploads/{upload_id}/prepare',data={'sheet':'Реестр','header_row':1,**config})
    assert response.status_code==200, response.text
    return int(response.url.path.rsplit('/',1)[-1]), upload_id


def test_inspect_and_parse_exact_columns(tmp_path):
    path=tmp_path/'fixture.xlsx';path.write_bytes(fixture_body())
    info=inspect(path)['sheets'][0]
    assert info['mapping']['external_id']==2
    assert info['mapping']['department']==14
    assert info['mapping']['registered_on']==6
    result=parse(path,{'sheet':'Реестр','header_row':1,'mapping':info['mapping']})
    assert result['summary']['rows']==4 and result['summary']['unique']==3 and result['summary']['duplicates']==1
    assert result['summary']['invalid']==0 and result['summary']['conflicts']==0
    assert result['records'][0]['payload']['department']=='Отделение А'
    assert result['records'][0]['payload']['event_name']=='Событие из резервного поля'
    assert 'DO_NOT_IMPORT' not in json.dumps(result)
    bad=dict(info['mapping']);bad['external_id']=1
    with pytest.raises(IncidentValidationError,match='порядковый'):
        parse(path,{'sheet':'Реестр','header_row':1,'mapping':bad})


def test_import_confirm_stats_and_repeat(local):
    client,path=local
    body=fixture_body()
    batch_id,upload_id=prepare_via_http(client,body)
    assert 'Корректных' in client.get(f'/incidents/imports/{batch_id}').text
    assert 'Статистика появится' in client.get('/modules/incidents').text
    response=client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique'})
    assert response.status_code==200 and 'id="incident-total">3<' in response.text
    engine=build_engine(path/'qms.sqlite3')
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(IncidentRecord))==3
        assert db.scalar(select(func.count()).select_from(IncidentStagedRow))==4
        stats=statistics(db,batch_id,Filters(date_from=date(2026,1,1),date_to=date(2026,3,31),compare_from=date(2025,12,1),compare_to=date(2025,12,31)))
        assert stats['total']==2 and stats['unique']==2
        assert [(m['label'],m['count']) for m in stats['months']]==[('2026-01',1),('2026-02',0),('2026-03',1)]
        assert stats['comparison']['delta']==1 and stats['comparison']['percent']==100
        assert sum(r['count'] for r in stats['groups']['department'])==stats['total']
        assert sum(r['percent'] for r in stats['groups']['department'])==100
    engine.dispose()
    assert client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique'}).status_code==200
    same_batch,_=prepare_via_http(client,body)
    assert same_batch==batch_id
    assert 'id="incident-total">3<' in client.get('/modules/incidents').text


def test_invalid_rows_require_explicit_skip(local):
    client,_=local;batch_id,_=prepare_via_http(client,fixture_body(invalid=True))
    assert client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique'}).status_code==400
    assert client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique','skip_invalid':'true'}).status_code==200


def test_conflicts_block_unique_but_rows_explicit(local):
    client,_=local;batch_id,_=prepare_via_http(client,fixture_body(conflict=True))
    assert client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique'}).status_code==400
    html=client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'rows'}).text
    assert 'id="incident-total">4<' in html and 'Все импортированные' not in html
    assert 'все импортированные строки отдельно' in html


def test_formula_is_error_not_executed(tmp_path):
    path=tmp_path/'formula.xlsx';path.write_bytes(fixture_body(formula=True));info=inspect(path)['sheets'][0]
    parsed=parse(path,{'sheet':info['name'],'header_row':1,'mapping':info['mapping']})
    assert parsed['summary']['invalid']==1
    assert any('формула' in error for row in parsed['records'] for error in row['errors'])


def test_excel_export_filtered_and_safe_strings(local):
    client,path=local;batch_id,_=prepare_via_http(client)
    client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique'})
    engine=build_engine(path/'qms.sqlite3')
    with Session(engine) as db:
        record=db.scalar(select(IncidentRecord).where(IncidentRecord.external_id=='100'))
        record.event_name='=HYPERLINK("https://example.invalid","test")'
        db.commit()
    engine.dispose()
    response=client.get('/incidents/export.xlsx',params={'batch_id':batch_id,'date_from':'2026-01-01','date_to':'2026-01-31'})
    assert response.status_code==200
    workbook=load_workbook(BytesIO(response.content),data_only=False)
    assert workbook['Реестр'].max_row==2
    assert workbook['Реестр']['A2'].value=='100'
    cells=[cell for sheet in workbook for row in sheet for cell in row]
    assert all(cell.data_type!='f' for cell in cells)
    assert any(str(cell.value).startswith('=HYPERLINK') for cell in cells)
    assert not any('DO_NOT_IMPORT' in str(cell.value) for cell in cells)
    assert workbook['Динамика']._charts
    workbook.close()
    report=client.get(f'/incidents/imports/{batch_id}/report.xlsx')
    workbook=load_workbook(BytesIO(report.content));assert workbook['Повторы'].max_row==2;workbook.close()


def test_filters_boundaries_missing_and_zero_comparison(local):
    client,path=local;batch_id,_=prepare_via_http(client);client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique'})
    response=client.get('/modules/incidents',params={'batch_id':batch_id,'date_from':'2026-01-02','date_to':'2026-01-02','department':'отделение а'})
    assert 'id="incident-total">1<' in response.text
    assert 'id="incident-total">1<' in client.get('/modules/incidents',params={'batch_id':batch_id,'department':'__empty__'}).text
    assert client.get('/modules/incidents',params={'date_from':'2026-03-01','date_to':'2026-01-01'}).status_code==400
    assert client.get('/modules/incidents',params={'compare_from':'2026-01-01'}).status_code==400
    engine=build_engine(path/'qms.sqlite3')
    with Session(engine) as db:
        stats=statistics(db,batch_id,Filters(compare_from=date(2020,1,1),compare_to=date(2020,1,31)))
        assert stats['comparison']['count']==0 and stats['comparison']['percent'] is None
    engine.dispose()


def test_commit_failure_rolls_back_batch_and_records(local,monkeypatch):
    client,path=local;batch_id,_=prepare_via_http(client)
    import app.incident_import as module
    original=module.insert
    def fail_on_records(model):
        if model is IncidentRecord:raise RuntimeError('Synthetic insertion failure')
        return original(model)
    monkeypatch.setattr(module,'insert',fail_on_records)
    with TestClient(client.app,raise_server_exceptions=False) as errors:
        assert errors.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique'}).status_code==500
    engine=build_engine(path/'qms.sqlite3')
    with Session(engine) as db:
        assert db.get(IncidentBatch,batch_id).state=='draft'
        assert db.scalar(select(func.count()).select_from(IncidentRecord))==0
    engine.dispose()


def test_invalid_file_not_registered(local):
    client,path=local
    assert client.post('/incidents/uploads',files={'file':('bad.pdf',b'no')}).status_code==400
    assert client.post('/incidents/uploads',files={'file':('bad.xlsx',b'no')}).status_code==400
    assert not list((path/'incident_imports').iterdir())
    assert client.get('/incidents/imports/9999').status_code==404


def test_v4_upgrade_preserves_existing_data(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,_env_file=None))
    with TestClient(app):pass
    with closing(sqlite3.connect(tmp_path/'qms.sqlite3')) as db:
        db.execute("INSERT INTO chat_messages(conversation_id,role,content,created_at,provider,model) VALUES (1,'user','До статистики','2026-01-01','mock','')");db.commit()
    with closing(sqlite3.connect(tmp_path/'qms.sqlite3')) as db:
        for table in ['incident_records','incident_staged_rows','incident_batches','incident_uploads']:db.execute('DROP TABLE '+table)
        db.execute('PRAGMA user_version=4');db.commit()
    with TestClient(create_app(Settings(data_dir=tmp_path,_env_file=None))) as client:
        with closing(sqlite3.connect(tmp_path/'qms.sqlite3')) as db:
            assert db.execute("SELECT content FROM chat_messages WHERE content='До статистики'").fetchone()==('До статистики',)
        assert client.get('/modules/incidents').status_code==200
    assert len(list((tmp_path/'backups').glob(f'qms-before-v{SCHEMA_VERSION}-*.sqlite3')))==1


def test_parallel_confirmation_does_not_duplicate(local):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import sessionmaker
    client,path=local;batch_id,_=prepare_via_http(client)
    engine=build_engine(path/'qms.sqlite3');sessions=sessionmaker(engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts=list(pool.map(lambda _:confirm(sessions,batch_id,'unique'),range(2)))
    assert counts==[3,3]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(IncidentRecord))==3
    engine.dispose()


def test_incident_workflow_never_invokes_ai(local,monkeypatch):
    from app.ai_service import AIService
    def forbidden(*a,**k):raise AssertionError('AI must not be called')
    monkeypatch.setattr(AIService,'reply',forbidden)
    client,_=local;batch_id,_=prepare_via_http(client)
    assert client.post(f'/incidents/imports/{batch_id}/confirm',data={'policy':'unique'}).status_code==200
    assert client.get('/incidents/export.xlsx',params={'batch_id':batch_id}).status_code==200


def test_inert_print_settings_allowed_but_macros_rejected(tmp_path):
    from zipfile import ZipFile,ZIP_DEFLATED
    for name,allowed in [('xl/printerSettings/printerSettings1.bin',True),('xl/vbaProject.bin',False)]:
        path=tmp_path/('print.xlsx' if allowed else 'macro.xlsx')
        original=BytesIO(fixture_body())
        with ZipFile(original) as source,ZipFile(path,'w',ZIP_DEFLATED) as target:
            for item in source.infolist():target.writestr(item,source.read(item))
            target.writestr(name,b'inert fixture')
        if allowed:assert inspect(path)['sheets'][0]['mapping']['external_id']==2
        else:
            from app.extract_worker import InvalidDocument
            with pytest.raises(InvalidDocument):inspect(path)



def test_excel_error_cell_flagged_not_counted(tmp_path):
    workbook=load_workbook(BytesIO(fixture_body()))
    workbook.active['P2']='#N/A'
    path=tmp_path/'error-cell.xlsx';workbook.save(path);workbook.close()
    info=inspect(path)['sheets'][0]
    result=parse(path,{'sheet':info['name'],'header_row':1,'mapping':info['mapping']})
    assert result['summary']['invalid']==1
    assert any('ошибка Excel' in error for row in result['records'] for error in row['errors'])



def test_default_dataset_is_most_recent_confirmation(local):
    client,_=local
    first,_=prepare_via_http(client,fixture_body())
    second,_=prepare_via_http(client,fixture_body(conflict=True))
    client.post(f'/incidents/imports/{second}/confirm',data={'policy':'rows'})
    client.post(f'/incidents/imports/{first}/confirm',data={'policy':'unique'})
    html=client.get('/modules/incidents').text
    assert f'Набор № {first}' in html
    assert 'id="incident-total">3<' in html
