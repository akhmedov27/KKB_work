from datetime import date
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile

from docx import Document
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_incident_analytics import dataset, OAR, GHO
from app.incident_report import ReportPeriod, prepare_report
from app.incident_stats import Filters
from app.models import IncidentBatch, IncidentRecord


def document_text(doc):
    return '\n'.join([p.text for p in doc.paragraphs]+[cell.text for t in doc.tables for row in t.rows for cell in row.cells])


@pytest.mark.parametrize('kind,year,month,quarter,expected',[
    ('month',2026,1,1,('2026-01-01','2026-01-31','2025-12-01','2025-12-31')),
    ('month',2024,2,1,('2024-02-01','2024-02-29','2024-01-01','2024-01-31')),
    ('quarter',2026,1,1,('2026-01-01','2026-03-31','2025-10-01','2025-12-31')),
    ('quarter',2026,1,2,('2026-04-01','2026-06-30','2026-01-01','2026-03-31')),
])
def test_calendar_bounds(kind,year,month,quarter,expected):
    period=ReportPeriod(report_kind=kind,report_year=year,report_month=month,report_quarter=quarter)
    assert tuple(map(str,period.bounds()))==expected


def test_report_counts_period_override_filters_and_excel(dataset):
    client,engine,batch=dataset
    params=[('batch_id',batch),('report_kind','quarter'),('report_year',2026),('report_quarter',2),
            ('departments','ГХО'),('departments','ОАР2'),('exclude_statuses','Удалено'),
            ('date_from','2000-01-01'),('date_to','2000-02-01')]
    page=client.get('/incidents/report',params=params)
    assert page.status_code==200
    assert 'id="report-total">1<' in page.text
    assert 'id="report-previous">2<' in page.text
    assert GHO in page.text and OAR in page.text
    import html
    export=html.unescape(re.search(r'id="period-report-excel" href="([^"]+)"',page.text)[1])
    assert 'date_from=2026-04-01' in export and 'compare_from=2026-01-01' in export
    assert client.get(export).status_code==200
    with Session(engine) as db:
        filters=Filters(departments=['ГХО','ОАР2'],exclude_statuses=['Удалено'])
        report=prepare_report(db,db.get(IncidentBatch,batch),filters,ReportPeriod(report_kind='quarter',report_year=2026,report_quarter=2))
        assert report['stats']['total']==1 and report['stats']['comparison']['count']==2
        assert report['days']==91 and report['previous_days']==90
        assert filters.date_from is None  # do not mutate source filters


def test_docx_comments_no_ai_no_saved_data_and_graphics(dataset,monkeypatch):
    client,engine,batch=dataset
    from app.ai_service import AIService
    def forbidden(*args,**kwargs): raise AssertionError('Report must not call AI')
    monkeypatch.setattr(AIService,'reply',forbidden)
    comment='Комментарий пользователя: <script> пример & проверка\nВторая строка.'
    response=client.post('/incidents/report.docx',data={'batch_id':batch,'report_kind':'quarter',
        'report_year':2026,'report_quarter':2,'departments':['ГХО','ОАР2'],'exclude_statuses':['Удалено'], 'comment':comment})
    assert response.status_code==200 and 'wordprocessingml.document' in response.headers['content-type']
    doc=Document(BytesIO(response.content));body=document_text(doc)
    assert comment in body
    assert '2026-04-01 — 2026-06-30 (91 дней)' in body
    assert '2026-01-01 — 2026-03-31 (90 дней)' in body
    assert GHO in body and OAR in body and 'Удалено' in body
    assert '9. Комментарий пользователя' in body and '5. Парето' in body
    assert doc.inline_shapes
    with ZipFile(BytesIO(response.content)) as package:
        assert any(name.startswith('word/media/') and name.endswith('.png') for name in package.namelist())
        rels=package.read('word/_rels/document.xml.rels').decode()
        assert 'TargetMode="External"' not in rels
        assert all(package.read(name).startswith(b'\x89PNG\r\n\x1a\n') for name in package.namelist() if name.startswith('word/media/'))
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(IncidentRecord))==9
    marker='Комментарий пользователя: <script>'.encode()
    assert marker not in Path(engine.url.database).read_bytes()
    assert marker not in (Path(engine.url.database).parent/'logs'/'app.log').read_bytes()


def test_empty_period_base_zero_and_comment_limit(dataset):
    client,_,batch=dataset
    data={'batch_id':batch,'report_kind':'month','report_year':2000,'report_month':2}
    response=client.post('/incidents/report.docx',data=data)
    assert response.status_code==200
    body=document_text(Document(BytesIO(response.content)))
    assert 'Нет записей: Парето не рассчитывается.' in body
    assert 'Не определяется: база 0' in body and 'Комментарий не добавлен.' in body
    assert client.post('/incidents/report.docx',data={**data,'comment':'x'*12001}).status_code==400


@pytest.mark.parametrize('values',[{'report_kind':'bad'},{'report_year':1900},{'report_month':13},{'report_quarter':0}])
def test_report_validation(dataset,values):
    client,_,batch=dataset
    assert client.get('/incidents/report',params={'batch_id':batch,**values}).status_code==400
    assert client.post('/incidents/report.docx',data={'batch_id':batch,**values}).status_code==400


def test_no_confirmed_or_unknown_report_source(dataset):
    client,engine,batch=dataset
    assert client.get('/incidents/report',params={'batch_id':999}).status_code==404
    with Session(engine) as db:
        db.get(IncidentBatch,batch).state='draft';db.commit()
    assert client.get('/incidents/report').status_code==400
    assert client.post('/incidents/report.docx',data={'batch_id':batch}).status_code==400
