from copy import deepcopy
from io import BytesIO
import xml.etree.ElementTree as ET
from docx import Document
from pydantic import ValidationError
import pytest
from app.qualigram_model import Qualigram
from app.qualigram_render import svg, png, layout_errors
from app.qualigram_vdx import vdx, NS
from app.stu_schema import StuContent
from tests.test_stu import client, create, content


def diagram():
 return {'lanes':[{'id':'a','name':'Руководитель'},{'id':'b','name':'Специалист'}],
 'nodes':[{'id':'s','kind':'dept_in','text':'Вход','x':50,'y':160,'width':150,'height':70},
 {'id':'n','kind':'action','text':'Проверить заявку','x':40,'y':320,'width':1100,'height':150,'lanes':['a','b'],'responsible':'a','number':1},
 {'id':'e','kind':'dept_out','text':'Завершено','x':50,'y':600,'width':150,'height':70}],
 'edges':[{'id':'e1','source':'s','target':'n','label':'Заявка'},{'id':'e2','source':'n','target':'e','label':'Результат','kind':'defect'}], 'description':'Описание пользователя.'}

@pytest.mark.parametrize('mutation',[lambda q:q['lanes'].extend([{'id':str(i),'name':'X'} for i in range(4)]),lambda q:q['nodes'][1].update(responsible='missing'),lambda q:q['nodes'][1].update(x=1000),lambda q:q['edges'][0].update(target='missing'),lambda q:q['nodes'][1].update(x=float('nan')),lambda q:q['nodes'].append(q['nodes'][0])])
def test_invalid_structure(mutation):
 q=diagram();mutation(q)
 with pytest.raises(ValidationError):Qualigram.model_validate(q)


def test_render_editable_native_shapes_and_safe_text():
 q=Qualigram.model_validate(diagram());assert not q.errors() and not layout_errors(q)
 assert 'Руководитель' in q.action_description() and 'Специалист' in q.action_description()
 assert 'Отв.' in svg(q) and 'Уч.' in svg(q) and '<polygon points=' in svg(q)
 q.nodes[1].text='<script>alert(1)</script>'
 assert '<script>' not in svg(q) and '&lt;script&gt;' in svg(q)
 assert png(q).startswith(b'\x89PNG')
 root=ET.fromstring(vdx(q));ns={'v':NS};shapes=root.findall('.//v:Shape',ns);ids=[s.get('ID') for s in shapes]
 assert len(ids)==len(set(ids));assert root.find('.//v:ForeignData',ns) is None
 assert '<script>alert(1)</script>' in ''.join(root.itertext())
 links=root.findall('.//v:Connect',ns);assert len(links)==4
 assert all(c.get('FromSheet') in ids and c.get('ToSheet') in ids for c in links)
 assert len(root.findall('.//v:Connection',ns))==12


def test_ids_survive_reorder_and_reject_orphans():
 c=StuContent.model_validate(content());pid=c.process_ids[0];c.qualigrams[pid]=Qualigram.model_validate(diagram())
 data=c.model_dump(mode='json');data['processes'].append('Второй');data['process_ids'].append('other')
 data['processes'].reverse();data['process_ids'].reverse();restored=StuContent.model_validate(data)
 assert restored.qualigrams[restored.process_ids[1]].nodes[1].text=='Проверить заявку'
 data['process_ids']=['bad','other']
 with pytest.raises(ValidationError):StuContent.model_validate(data)


def test_routes_conflicts_export_and_remove(client):
 c,_=client;id=create(c);data=StuContent.model_validate(content()).model_dump(mode='json');pid=data['process_ids'][0]
 assert c.put(f'/stu/{id}',json={'version':1,'content':data}).status_code==200
 base=f'/stu/{id}/qualigrams/{pid}'
 assert c.get(base).status_code==200
 assert c.get(base+'/export.vdx').status_code==400
 preview=c.post(base+'/preview',json=diagram());assert preview.status_code==200 and preview.json()['errors']==[]
 assert c.put(base,json={'version':2,'diagram':diagram()}).json()['version']==3
 assert c.put(base,json={'version':2,'diagram':diagram()}).status_code==409
 assert c.put(f'/stu/{id}',json={'version':2,'content':data}).status_code==409
 assert c.get(base+'/export.png').content.startswith(b'\x89PNG')
 assert ET.fromstring(c.get(base+'/export.vdx').content).tag=='{'+NS+'}VisioDocument'
 doc=Document(BytesIO(c.get(f'/stu/{id}/export.docx').content));assert len(doc.inline_shapes)>=2
 assert 'Описание пользователя.' in '\n'.join(p.text for p in doc.paragraphs)
 assert c.get(base+'/export.exe').status_code==404
 assert c.put(base,json={'version':3,'diagram':None}).status_code==200
 assert c.get(base+'/export.png').status_code==400


def test_overflow_draft_allowed_export_blocked(client):
 c,_=client;id=create(c);data=StuContent.model_validate(content()).model_dump(mode='json');pid=data['process_ids'][0]
 c.put(f'/stu/{id}',json={'version':1,'content':data});base=f'/stu/{id}/qualigrams/{pid}'
 q=diagram();q['nodes'][1].update(text='Длинный текст '*100,height=24)
 assert c.put(base,json={'version':2,'diagram':q}).status_code==200
 assert c.post(base+'/preview',json=q).json()['errors']
 assert c.get(base+'/export.png').status_code==400 and c.get(f'/stu/{id}/export.docx').status_code==400
 assert c.post(base+'/preview',json={'lanes':[],'nodes':[{'id':'bad','x':-10}]}).status_code==400
 assert c.get(f'/stu/{id}/qualigrams/missing').status_code==404


def test_ports_for_shared_block_and_dashed_raster_geometry():
 from app.qualigram_render import endpoints
 q=Qualigram.model_validate(diagram())
 assert endpoints(q,q.edges[0])[2:]==('bottom','top')
 assert endpoints(q,q.edges[1])[2:]==('bottom','top')
 # Explicit segments retain defect dashes in PyMuPDF, which omits SVG dash styles.
 root=ET.fromstring(svg(q));ns={'s':'http://www.w3.org/2000/svg'}
 group=next(x for x in root.findall('s:g',ns) if x.get('data-edge-id')=='e2')
 assert len(group.findall('s:line',ns))>3
 q.orientation='landscape';assert q.width==1697 and q.height==1200
 assert png(q).startswith(b'\x89PNG')
