import re
from io import BytesIO
from urllib.parse import parse_qs,urlsplit
import html
from lxml import html as dom
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session
import pytest
from tests.test_incident_analytics import dataset
from app.models import IncidentRecord

@pytest.fixture
def categories(dataset):
 client,engine,batch=dataset
 with Session(engine) as db:
  records=db.scalars(select(IncidentRecord).where(IncidentRecord.batch_id==batch).order_by(IncidentRecord.id)).all()
  for row,subgroup in zip(records,['Падения','Травмы','Назначение','Падения','падения','Травмы','','','Другое']):row.subgroup=subgroup
  db.commit()
 return client,engine,batch


def choices(text):
 doc=dom.fromstring(text)
 return {option.get('value'):bool(option.get('selected') is not None) for option in doc.xpath('//select[@id="filter-subgroup"]/option')}


def test_removed_fields_and_group_scoped_server_options(categories):
 c,_,batch=categories
 page=c.get('/modules/incidents',params={'batch_id':batch,'group_name':'бЕзОпАсНоСтЬ','subgroup':'падения'})
 assert page.status_code==200
 doc=dom.fromstring(page.text)
 assert not doc.xpath('//*[@id="filter-event_name" or @id="filter-root_cause"]')
 assert set(choices(page.text))=={'','__empty__','Падения','Травмы'}
 assert choices(page.text)['Падения']
 assert 'Назначение' not in choices(page.text)
 # No group: all batch subgroups. Empty group is an explicit separate selection.
 assert 'Назначение' in choices(c.get('/modules/incidents',params={'batch_id':batch}).text)
 assert set(choices(c.get('/modules/incidents',params={'batch_id':batch,'group_name':'__empty__'}).text))=={'','__empty__'}


def test_unrelated_subgroup_resets_for_dashboard_and_export(categories):
 c,_,batch=categories
 params={'batch_id':batch,'group_name':'Лекарства','subgroup':'Падения','page':7}
 page=c.get('/modules/incidents',params=params)
 assert page.status_code==200 and 'id="incident-total">2<' in page.text
 assert choices(page.text)[''] and 'Подгруппа сброшена' in page.text
 assert 'Страница 1' in page.text
 export=html.unescape(re.search(r'href="([^"]+)" id="incident-export"',page.text)[1])
 assert 'subgroup' not in parse_qs(urlsplit(export).query)
 book=load_workbook(BytesIO(c.get('/incidents/export.xlsx',params=params).content))
 summary=dict(book['Сводка'].values)
 assert summary['Количество в выборке']==2
 valid=c.get('/modules/incidents',params={**params,'subgroup':'Травмы','page':1})
 assert 'id="incident-total">1<' in valid.text and choices(valid.text)['Травмы']


def test_lookup_empty_casefold_unknown_and_validation(categories):
 c,_,batch=categories
 def get(group):return c.get('/incidents/subgroups',params={'batch_id':batch,'group_name':group})
 assert {i['value'] for i in get('лЕкАрСтВа').json()['items']}=={'Назначение','Травмы'}
 assert {i['value'] for i in get('__empty__').json()['items']}=={'__empty__'}
 assert get('Несуществующая').json()['items']==[]
 assert c.get('/incidents/subgroups',params={'batch_id':99999}).status_code==404
 assert c.get('/incidents/subgroups',params={'batch_id':0}).status_code==422
 assert get('x'*501).status_code==422


def test_diagram_drilldown_stays_visible_without_filter_controls(categories):
 c,_,batch=categories
 text=c.get('/modules/incidents',params={'batch_id':batch,'event_name':'Падение','root_cause':'R1'}).text
 doc=dom.fromstring(text)
 assert len(doc.xpath('//*[@data-chart-slice]'))==2
 assert len(doc.xpath('//input[@type="hidden" and @name="event_name"]'))==1
 assert len(doc.xpath('//input[@type="hidden" and @name="root_cause"]'))==1
 assert not doc.xpath('//*[@id="filter-event_name" or @id="filter-root_cause"]')


def test_long_lists_preserve_valid_active_value(categories):
 c,engine,batch=categories
 with Session(engine) as db:
  base=db.scalar(select(IncidentRecord).where(IncidentRecord.batch_id==batch))
  for i in range(505):
   values={col.name:getattr(base,col.name) for col in IncidentRecord.__table__.columns if col.name not in ('id','external_id','source_row','group_name','subgroup')}
   db.add(IncidentRecord(**values,external_id='limit'+str(i),source_row=100+i,group_name='Много',subgroup=f'Подгруппа {i:03d}'))
  db.commit()
 data=c.get('/incidents/subgroups',params={'batch_id':batch,'group_name':'Много','selected':'Подгруппа 504'}).json()
 assert data['truncated'] and len(data['items'])==501
 assert data['items'][-1]['value']=='Подгруппа 504'
