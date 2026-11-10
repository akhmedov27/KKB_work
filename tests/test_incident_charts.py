import html
import json
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_incident_analytics import dataset, GHO
from app.incident_charts import chart_data, snapshot_chart
from app.incident_stats import Filters, statistics
from app.models import IncidentRecord


def payload(client, params=None):
    page=client.get('/modules/incidents',params=params)
    assert page.status_code==200
    return json.loads(re.search(r'<script id="incident-chart-data" type="application/json">(.*?)</script>',page.text,re.S)[1])


def test_chart_counts_and_drilldowns_share_filter_denominators(dataset):
    client,engine,batch=dataset
    params=[('batch_id',batch),('date_from','2026-01-02'),('date_to','2026-04-04'),
            ('departments','ГХО'),('departments','ОАР2'),('exclude_statuses','Удалено')]
    data=payload(client,params)
    charts={chart['id']:chart for chart in data['charts']}
    assert len(charts)==8
    assert sum(row['values'][0] for row in charts['departments']['rows'])==2
    assert sum(sum(row['values']) for row in charts['heat-month']['rows'])==2
    assert sum(sum(row['values']) for row in charts['heat-group']['rows'])==2
    for chart in data['charts']:
        for row in chart['rows']:
            for i,href in enumerate(row.get('hrefs',[])):
                if not href: continue
                query=parse_qs(urlsplit(href).query)
                assert query['exclude_statuses']==['Удалено']
                assert query['page']==['1']
                response=client.get(href)
                assert response.status_code==200
                expected=row['values'][i] if chart['id']!='pareto' else row['values'][0]
                assert int(re.search(r'id="incident-total">(\d+)<',response.text)[1])==expected
    first=charts['heat-month']['rows'][0]['hrefs'][0]
    assert parse_qs(urlsplit(first).query)['date_from']==['2026-01-02']
    assert charts['periods']['rows']==[]


def test_second_period_links_and_missing_cause_filter_export(dataset):
    client,_,batch=dataset
    data=payload(client,{'batch_id':batch,'date_from':'2026-01-01','date_to':'2026-12-31',
                         'compare_from':'2025-01-01','compare_to':'2025-12-31'})
    chart=next(chart for chart in data['charts'] if chart['id']=='periods')
    assert sum(row['values'][0] for row in chart['rows'])==7
    assert sum(row['values'][1] for row in chart['rows'])==2
    for row in chart['rows']:
        for i,href in enumerate(row['hrefs']):
            text=client.get(href).text
            assert int(re.search(r'id="incident-total">(\d+)<',text)[1])==row['values'][i]
    page=client.get('/modules/incidents',params={'batch_id':batch,'root_cause':'__empty__'})
    assert 'id="incident-total">2<' in page.text
    export=html.unescape(re.search(r'href="([^"]+)" id="incident-export"',page.text)[1])
    assert 'root_cause=__empty__' in export
    assert client.get(export).status_code==200


def test_literal_missing_label_does_not_merge_with_empty_and_json_is_safe(dataset):
    client,engine,batch=dataset
    with Session(engine) as db:
        row=db.scalar(select(IncidentRecord).where(IncidentRecord.batch_id==batch,IncidentRecord.department==GHO))
        row.department='Не указано';row.group_name='</script><script>alert(1)</script>'
        db.commit()
    data=payload(client,{'batch_id':batch})
    heat=next(chart for chart in data['charts'] if chart['id']=='heat-group')
    assert sum(sum(row['values']) for row in heat['rows'])==9
    blanks=[row for row in heat['rows'] if row['label']=='Не указано']
    assert len(blanks)==2
    assert sorted(sum(row['values']) for row in blanks)==[1,1]
    text=client.get('/modules/incidents',params={'batch_id':batch}).text
    assert '</script><script>alert(1)</script>' not in text
    assert '\\u003c/script\\u003e' in text


def test_bounded_axes_status_remainder_and_empty_charts(dataset):
    client,engine,batch=dataset
    with Session(engine) as db:
        base=db.scalar(select(IncidentRecord).where(IncidentRecord.batch_id==batch))
        for i in range(30):
            fields={key:getattr(base,key) for key in ['registered_on','department_type','subgroup','event_name','importance','urgent','source_method','root_cause']}
            db.add(IncidentRecord(batch_id=batch,external_id=f'x{i}',source_row=100+i,
                occurred_on=date(2020+i//12,i%12+1,1),department=f'Отделение {i}',status=f'Статус {i}',group_name=f'Группа {i}',**fields))
        db.commit()
    data=payload(client,{'batch_id':batch})
    charts={row['id']:row for row in data['charts']}
    assert len(charts['departments']['rows'])==15
    assert len(charts['heat-month']['columns'])<=24
    assert len(charts['heat-group']['columns'])==12
    assert len(charts['statuses']['series'])==9
    totals={row['label']:row['values'][0] for row in charts['departments']['rows']}
    assert all(sum(row['values'])==totals[row['label']] for row in charts['statuses']['rows'])
    empty=payload(client,{'batch_id':batch,'date_from':'2000-01-01','date_to':'2000-12-31'})
    assert all(not any(any(row['values']) for row in chart['rows']) for chart in empty['charts'])


def test_snapshot_chart_categories_and_navigation():
    result={'counts':{'added':3,'missing':2,'changed':4,'unchanged':10}}
    data=snapshot_chart(result,11,12)
    chart=data['charts'][0]
    assert [row['values'] for row in chart['rows']]==[[3],[2],[4],[10]]
    for row,key in zip(chart['rows'],result['counts']):
        assert parse_qs(urlsplit(row['hrefs'][0]).query)=={'before_id':['11'],'after_id':['12'],'kind':[key]}
