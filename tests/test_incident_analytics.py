from datetime import date
from io import BytesIO
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_engine
from app.department_aliases import reference, resolve, suggestions
from app.incident_stats import Filters, statistics
from app.main import create_app
from app.models import IncidentBatch, IncidentRecord, IncidentUpload

OAR = 'Анестезиология-реанимация №2 (кардиореанимация)'
GHO = 'Гнойная хирургия'
TO1 = 'Травматолого-ортопедическое №1 (сочетанная травма)'
NRS = 'Отделение хирургического лечения сложных нарушений ритма сердца и электрокардиостимуляции'


@pytest.fixture
def dataset(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        engine = build_engine(tmp_path / 'qms.sqlite3')
        with Session(engine) as db:
            upload = IncidentUpload(id='a'*32, original_name='analytics.xlsx', stored_name='test.xlsx', sha256='0'*64, inspection_json='{}')
            db.add(upload); db.flush()
            batch = IncidentBatch(upload_id=upload.id, fingerprint='1'*64, sheet_name='Реестр', state='confirmed', policy='unique',
                imported_count=9, mapping_json=json.dumps({'mapping': {'external_id':2,'occurred_on':3,'department':14}}),
                summary_json=json.dumps({'min_date':'2025-01-01','max_date':'2026-04-07'}))
            db.add(batch); db.flush(); batch_id = batch.id
            records = [
                ('2026-01-01', OAR, 'Падение', 'Безопасность', 'R1', 'Открыто'),
                ('2026-01-02', OAR, 'Падение', 'Безопасность', '', 'Отменено'),
                ('2026-04-03', GHO, 'Ошибка лекарства', 'Лекарства', 'R2', 'Открыто'),
                ('2026-04-04', GHO, 'Падение', 'Безопасность', 'R1', 'Удалено'),
                ('2025-01-01', OAR, 'Падение', 'Безопасность', 'R1', 'Открыто'),
                ('2025-01-02', GHO, 'Ошибка лекарства', 'Лекарства', 'R2', 'Открыто'),
                ('2026-04-05', '', '', '', '', 'Открыто'),
                ('2026-04-06', TO1, 'Падение', 'Безопасность', 'R1', 'Открыто'),
                ('2026-04-07', NRS, 'Другое', 'Другое', 'R3', 'Открыто'),
            ]
            for index,(day,department,event,group,cause,status) in enumerate(records,1):
                db.add(IncidentRecord(batch_id=batch_id, source_row=index+1, external_id=str(index), occurred_on=date.fromisoformat(day),
                    registered_on=None, department=department, department_type='', group_name=group, subgroup='', event_name=event,
                    importance='A', status=status, urgent='', source_method='', root_cause=cause))
            db.commit()
        yield client, engine, batch_id
        engine.dispose()


@pytest.mark.parametrize('alias,expected', [('гхо',GHO),('ОАР №2',OAR),('оар-2',OAR),('НХО1','Нейрохирургическое №1'),
                                          ('НРС',NRS),('ХО НРС/ЭКС',NRS),('то1',TO1)])
def test_alias_variants(alias, expected):
    assert resolve(alias) == expected


def test_corrections_future_units_and_unknown_values():
    entries,_ = reference()
    assert any(entry['aliases']==['ОАР 1'] for entry in entries)
    assert any('ТО 2' in entry['aliases'] for entry in entries)
    assert any('ТО 3' in entry['aliases'] for entry in entries)
    assert next(entry for entry in entries if entry['name']=='Эндокринологическое')['aliases']==[]
    assert resolve('Неизвестное отделение')=='Неизвестное отделение'
    future = suggestions([OAR,GHO], 'ОАР1')
    assert len(future)==1 and future[0]['present'] is False
    assert future[0]['label']!='ОАР 1'
    assert [item['value'] for item in suggestions([OAR,GHO], 'гхо')]==[GHO]


def test_suggestions_endpoint_full_names_and_no_phantom_records(dataset):
    client,engine,batch_id=dataset
    data=client.get('/incidents/departments',params={'batch_id':batch_id,'q':'оар2'}).json()
    assert data['items']==[{'value':OAR,'label':OAR,'present':True}]
    future=client.get('/incidents/departments',params={'batch_id':batch_id,'q':'ТО 2'}).json()['items']
    assert len(future)==1 and future[0]['present'] is False
    assert client.get('/incidents/departments',params={'batch_id':9999}).status_code==404
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(IncidentRecord))==9


def test_alias_filters_or_selection_and_exclusion(dataset):
    client,engine,batch_id=dataset
    with Session(engine) as db:
        all_stats=statistics(db,batch_id,Filters())
        assert all_stats['total']==9
        assert statistics(db,batch_id,Filters(department='ГХО'))['total']==3
        filters=Filters(date_from=date(2026,1,1),departments=['оар2','ГХО'],exclude_statuses=['отменено','удалено'])
        assert statistics(db,batch_id,filters)['total']==2
        assert statistics(db,batch_id,Filters(departments=['ГХО',GHO]))['total']==3
        assert statistics(db,batch_id,Filters(departments=['ТО 2']))['total']==0
        assert statistics(db,batch_id,Filters(departments=['__empty__']))['total']==1
        assert statistics(db,batch_id,Filters(department='Неизвестное отделение'))['total']==0
    response=client.get('/modules/incidents',params=[('batch_id',batch_id),('departments','ГХО'),('departments','оар2'),
        ('exclude_statuses','Отменено'),('exclude_statuses','Удалено'),('date_from','2026-01-01')])
    assert response.status_code==200 and 'id="incident-total">2<' in response.text
    assert GHO in response.text and OAR in response.text
    # Every repeated parameter survives the export URL.
    import re, html
    export=html.unescape(re.search(r'href="([^"]+)" id="incident-export"',response.text)[1])
    query=parse_qs(urlsplit(export).query)
    assert set(query['departments'])=={GHO,OAR}
    assert set(query['exclude_statuses'])=={'Отменено','Удалено'}
    assert client.get(export).status_code==200


def test_quarters_pareto_cross_table_and_quality_denominators(dataset):
    _,engine,batch_id=dataset
    with Session(engine) as db:
        filters=Filters(date_from=date(2026,1,1),date_to=date(2026,12,31))
        stats=statistics(db,batch_id,filters)
        assert stats['total']==7
        assert [item['count'] for item in stats['quarters']]==[2,5,0,0]
        assert sum(item['count'] for item in stats['quarters'])==stats['total']
        assert sum(item['count'] for item in stats['pareto'])==stats['total']
        assert stats['pareto'][-1]['cumulative']==100
        assert stats['pareto_core_count']==3 and stats['pareto_core_percent']>=80
        assert stats['pareto'][1]['cumulative']<80
        assert sum(item['count'] for item in stats['cross_rows'])==stats['total']
        gho=[item for item in stats['cross_rows'] if item['department']==GHO]
        assert len(gho)==2 and all(item['department_percent']==50 for item in gho)
        assert stats['missing_departments']==1 and stats['missing_causes']==2
        assert len(stats['repeated'])==1 and stats['repeated'][0][2]==2
        filters.min_repeat=3
        assert statistics(db,batch_id,filters)['repeated']==[]
        filters.pareto_by='root_cause';filters.pareto_cutoff=100
        stats=statistics(db,batch_id,filters)
        assert stats['pareto_core_count']==len(stats['pareto']) and stats['pareto_core_percent']==100
        assert any(item['label']=='Не указано' for item in stats['pareto'])


def test_period_comparison_totals_and_zero_base(dataset):
    _,engine,batch_id=dataset
    with Session(engine) as db:
        stats=statistics(db,batch_id,Filters(date_from=date(2026,1,1),date_to=date(2026,12,31),
            compare_from=date(2025,1,1),compare_to=date(2025,12,31)))
        rows=stats['department_comparison']
        assert sum(row['current'] for row in rows)==7 and sum(row['previous'] for row in rows)==2
        assert next(row for row in rows if row['label']==OAR)['percent']==100
        assert next(row for row in rows if row['label']==TO1)['percent'] is None
        assert sum(row['current'] for row in stats['group_comparison'])==7
        assert sum(row['previous'] for row in stats['group_comparison'])==2
        empty=statistics(db,batch_id,Filters(date_from=date(2020,1,1),date_to=date(2020,12,31)))
        assert empty['total']==0 and empty['pareto_core_count']==0 and empty['pareto_chart']==[]


@pytest.mark.parametrize('params',[{'pareto_cutoff':0},{'pareto_cutoff':101},{'min_repeat':1},{'pareto_by':'invented'},
                                   [('departments','x')]*51])
def test_new_controls_validation(dataset,params):
    client,_,_=dataset
    assert client.get('/modules/incidents',params=params).status_code==400


def test_export_new_sheets_and_full_names(dataset):
    client,_,batch_id=dataset
    response=client.get('/incidents/export.xlsx',params=[('batch_id',batch_id),('departments','ГХО'),('departments','ОАР2'),
        ('exclude_statuses','Отменено'),('date_from','2026-01-01'),('date_to','2026-12-31'),
        ('compare_from','2025-01-01'),('compare_to','2025-12-31')])
    assert response.status_code==200
    workbook=load_workbook(BytesIO(response.content),data_only=False)
    assert {'Кварталы','Парето','Сравнение отделений','Сравнение групп','Отделения и группы'}.issubset(workbook.sheetnames)
    assert workbook['Реестр'].max_row==4
    names=[row[0] for row in workbook['Отделение'].iter_rows(min_row=2,values_only=True)]
    assert set(names)=={OAR,GHO}
    assert workbook['Парето']._charts
    assert not any(cell.data_type=='f' for sheet in workbook for row in sheet for cell in row)
    summary=dict(workbook['Сводка'].iter_rows(min_row=2,values_only=True))
    assert OAR in summary['Выбранные отделения'] and 'Отменено' in summary['Исключённые статусы']
    workbook.close()
