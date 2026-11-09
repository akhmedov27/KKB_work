from datetime import date
from io import BytesIO
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_engine
from app.incident_comparison import compare
from app.main import create_app
from app.models import IncidentBatch, IncidentRecord, IncidentUpload

MAPPING = {'external_id': 2, 'occurred_on': 3, 'registered_on': 6, 'department': 14,
           'group_name': 16, 'event_name': 18, 'event_fallback': 19, 'status': 25, 'root_cause': 22}


def add_batch(db, token, records, state='confirmed', mapping=None):
    upload = IncidentUpload(id=token*32, original_name=f'{token}.xlsx', stored_name=f'{token}.xlsx',
                            sha256=token*64, inspection_json='{}')
    db.add(upload); db.flush()
    batch = IncidentBatch(upload_id=upload.id, fingerprint=token*64, sheet_name='Реестр', state=state,
                          policy='unique', imported_count=len(records), summary_json='{}',
                          mapping_json=json.dumps({'mapping': MAPPING if mapping is None else mapping}))
    db.add(batch); db.flush()
    for index, record in enumerate(records, 2):
        values = dict(external_id=str(index), occurred_on=date(2026, 1, 1), registered_on=None,
                      department='Полное отделение А', department_type='', group_name='Группа А', subgroup='',
                      event_name='Событие', importance='', status='Открыто', urgent='', source_method='', root_cause='')
        values.update(record)
        db.add(IncidentRecord(batch_id=batch.id, source_row=index, **values))
    db.flush()
    return batch.id


@pytest.fixture
def snapshots(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        engine=build_engine(tmp_path/'qms.sqlite3')
        with Session(engine) as db:
            old=add_batch(db,'a',[{'external_id':'001'}, {'external_id':'B'}, {'external_id':'C'}])
            new=add_batch(db,'b',[{'external_id':'001'}, {'external_id':'B','status':'Закрыто',
                'department':'Полное отделение Б','occurred_on':date(2026,2,1),'root_cause':'=HYPERLINK("x")'},
                {'external_id':'D','status':'<script>alert(1)</script>'}])
            db.commit()
        yield client,engine,old,new
        engine.dispose()


def test_exact_matching_details_distributions_and_no_mutation(snapshots):
    client,engine,old,new=snapshots
    with Session(engine) as db:
        result=compare(db,db.get(IncidentBatch,old),db.get(IncidentBatch,new))
        assert result['counts']=={'added':1,'missing':1,'changed':1,'unchanged':1}
        assert result['groups']['unchanged'][0]['number']=='001'
        assert {item['field'] for item in result['changes']}=={'occurred_on','department','status','root_cause'}
        assert any('Диапазоны дат' in warning for warning in result['warnings'])
        for rows in result['distribution'].values():
            assert sum(item['before'] for item in rows)==3
            assert sum(item['after'] for item in rows)==3
        reverse=compare(db,db.get(IncidentBatch,new),db.get(IncidentBatch,old))
        assert reverse['groups']['added'][0]['number']=='C'
        assert reverse['groups']['missing'][0]['number']=='D'
    params={'before_id':old,'after_id':new}
    page=client.get('/incidents/compare',params=params)
    assert page.status_code==200 and 'id="count-changed">1<' in page.text
    assert 'Дата инцидента' in page.text and 'Полное отделение Б' in page.text
    added=client.get('/incidents/compare',params={**params,'kind':'added'})
    assert '&lt;script&gt;' in added.text and '<script>alert(1)</script>' not in added.text
    assert client.get('/incidents/compare',params=params).text==page.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(IncidentRecord))==6
        assert db.get(IncidentRecord,1).external_id=='001'


def test_export_all_categories_exact_values_and_no_formulas(snapshots):
    client,_,old,new=snapshots
    response=client.get('/incidents/compare.xlsx',params={'before_id':old,'after_id':new})
    assert response.status_code==200
    book=load_workbook(BytesIO(response.content))
    assert {'Только в новом наборе','Отсутствуют в новом наборе','Изменены','Без изменений','Изменённые поля'}.issubset(book.sheetnames)
    assert book['Изменённые поля'].max_row==5
    assert book['Без изменений']['A2'].value=='001'
    assert '=HYPERLINK("x")' in [row[3] for row in book['Изменённые поля'].iter_rows(min_row=2,values_only=True)]
    assert not any(cell.data_type=='f' for sheet in book for row in sheet for cell in row)
    book.close()


@pytest.mark.parametrize('path',['/incidents/compare','/incidents/compare.xlsx'])
def test_reject_same_missing_draft_and_ambiguous_number(snapshots,path):
    client,engine,old,new=snapshots
    assert client.get(path,params={'before_id':old,'after_id':old}).status_code==400
    assert client.get(path,params={'before_id':old,'after_id':999}).status_code==404
    with Session(engine) as db:
        draft=add_batch(db,'c',[],state='draft')
        duplicate=add_batch(db,'d',[{'external_id':'X'},{'external_id':'X'}])
        db.commit()
    assert client.get(path,params={'before_id':old,'after_id':draft}).status_code==400
    response=client.get(path,params={'before_id':old,'after_id':duplicate})
    assert response.status_code==400 and 'несколько раз' in response.text


def test_only_common_mapped_fields_fallback_and_exact_case(snapshots):
    _,engine,old,new=snapshots
    with Session(engine) as db:
        left,right=db.get(IncidentBatch,old),db.get(IncidentBatch,new)
        mapping={**MAPPING,'status':None,'root_cause':None,'event_name':None}
        right.mapping_json=json.dumps({'mapping':mapping})
        row=db.scalar(select(IncidentRecord).where(IncidentRecord.batch_id==new,IncidentRecord.external_id=='001'))
        row.status='Другой'; row.event_name='Другой вид'; row.department='полное отделение А'
        db.flush()
        result=compare(db,left,right)
        fields={item['field'] for item in result['changes']}
        assert 'status' not in fields and 'root_cause' not in fields
        assert 'event_name' in fields  # fallback alone still maps the effective event name
        assert 'department' in fields  # changes of case are explicit, never hidden
        assert any('Сопоставления' in warning for warning in result['warnings'])
        assert any('Статус' in warning for warning in result['warnings'])


def test_pagination_validation_empty_and_same_date_not_false_completeness(snapshots):
    client,engine,old,new=snapshots
    with Session(engine) as db:
        empty=add_batch(db,'e',[])
        many=add_batch(db,'f',[{'external_id':f'{i:03d}'} for i in range(56)])
        db.commit()
    response=client.get('/incidents/compare',params={'before_id':empty,'after_id':many,'kind':'added'})
    assert response.status_code==200 and 'id="count-added">56<' in response.text
    assert 'page_number=2' in response.text
    second=client.get('/incidents/compare',params={'before_id':empty,'after_id':many,'kind':'added','page_number':2})
    assert '>055<' in second.text and '>000<' not in second.text
    for params in [{'before_id':old},{'after_id':new},{'kind':'bad'},{'page_number':0},{'before_id':-1}]:
        assert client.get('/incidents/compare',params=params).status_code in {400,422}
    assert client.get('/incidents/compare').status_code==200
    response=client.get('/incidents/compare.xlsx',params={'before_id':empty,'after_id':many})
    book=load_workbook(BytesIO(response.content))
    assert book['Только в новом наборе'].max_row==57
    book.close()
