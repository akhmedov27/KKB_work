"""Editable one-page qualigrams, bounded for local low-memory use."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ID=Annotated[str,StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,64}$')]
Label=Annotated[str,StringConstraints(max_length=500)]
KINDS={'action':'Действие','start':'Начало процесса','end':'Окончание процесса',
       'dept_in':'Отдел — вход','dept_out':'Отдел — выход','department':'Отдел — внешний',
       'and':'И','or':'ИЛИ','note':'Пояснение','document':'Документ','date':'Дата','number':'Номер'}
EDGE_KINDS={'information':'Информация','defect':'Брак','risk':'Высокий риск'}

class Model(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

class Lane(Model):
 id:ID
 name:Annotated[str,StringConstraints(max_length=200)]=''

class Node(Model):
 id:ID
 kind:Literal['action','start','end','dept_in','dept_out','department','and','or','note','document','date','number']='action'
 text:Annotated[str,StringConstraints(max_length=2000)]=''
 x:float=Field(default=40,ge=20,le=1657)
 y:float=Field(default=160,ge=140,le=1657)
 width:float=Field(default=180,ge=40,le=1657)
 height:float=Field(default=90,ge=24,le=1517)
 lanes:list[ID]=Field(default_factory=list,max_length=5)
 responsible:ID|None=None
 number:int|None=Field(default=None,ge=1,le=9999)
 font_size:int=Field(default=16,ge=10,le=30)

class Edge(Model):
 id:ID
 source:ID
 target:ID
 source_port:Literal['auto','top','right','bottom','left']='auto'
 target_port:Literal['auto','top','right','bottom','left']='auto'
 kind:Literal['information','defect','risk']='information'
 label:Label=''

class Qualigram(Model):
 orientation:Literal['portrait','landscape']='portrait'
 lanes:list[Lane]=Field(default_factory=list,max_length=5)
 nodes:list[Node]=Field(default_factory=list,max_length=100)
 edges:list[Edge]=Field(default_factory=list,max_length=200)
 description:Annotated[str,StringConstraints(max_length=20000)]=''

 @property
 def width(self):return 1200 if self.orientation=='portrait' else 1697
 @property
 def height(self):return 1697 if self.orientation=='portrait' else 1200

 @model_validator(mode='after')
 def references(self):
  lane_ids={row.id for row in self.lanes};node_ids={row.id for row in self.nodes}
  if len(lane_ids)!=len(self.lanes) or len(node_ids)!=len(self.nodes) or len({r.id for r in self.edges})!=len(self.edges):
   raise ValueError('Идентификаторы должны быть уникальны.')
  for node in self.nodes:
   if len(set(node.lanes))!=len(node.lanes) or not set(node.lanes)<=lane_ids:
    raise ValueError('Участник действия не найден среди дорожек.')
   if node.responsible is not None and node.responsible not in node.lanes:
    raise ValueError('Ответственный должен входить в число исполнителей действия.')
   if node.x+node.width>self.width-20+.001 or node.y+node.height>self.height-20+.001:
    raise ValueError('Блок выходит за границы листа.')
  for edge in self.edges:
   if edge.source not in node_ids or edge.target not in node_ids:
    raise ValueError('Связь ссылается на удалённый блок.')
  return self

 def errors(self):
  errors=[]
  if not self.lanes or any(not row.name.strip() for row in self.lanes):errors.append('Задайте от 1 до 5 дорожек с названиями.')
  if not self.nodes:errors.append('Добавьте блоки схемы.')
  for i,node in enumerate(self.nodes,1):
   if not node.text.strip():errors.append(f'Блок {i}: заполните подпись.')
   if node.kind=='action' and (not node.lanes or node.responsible is None):errors.append(f'Действие {i}: выберите исполнителей и одного ответственного.')
  return errors

 def warnings(self):
  warnings=[]
  if not any(n.kind in ('start','dept_in') for n in self.nodes):warnings.append('Не отмечен вход в процесс.')
  if not any(n.kind in ('end','dept_out') for n in self.nodes):warnings.append('Не отмечен выход из процесса.')
  connected={id for edge in self.edges for id in (edge.source,edge.target)}
  if any(n.id not in connected and n.kind not in ('note','date','number','document') for n in self.nodes):warnings.append('Есть блоки без связей.')
  numbers=[n.number for n in self.nodes if n.kind=='action' and n.number is not None]
  if len(set(numbers))!=len(numbers):warnings.append('Номера действий повторяются.')
  return warnings

 def action_description(self):
  names={lane.id:lane.name for lane in self.lanes};nodes={node.id:node for node in self.nodes};lines=[]
  actions=[n for n in self.nodes if n.kind=='action']
  for index,node in enumerate(sorted(actions,key=lambda n:(n.y,n.x)),1):
   lines.append(f'{node.number or index}. {node.text.strip()}')
   lines.append('Ответственный: '+names.get(node.responsible,'не выбран')+'.')
   participants=[names[id] for id in node.lanes if id!=node.responsible]
   if participants:lines.append('Участники: '+', '.join(participants)+'.')
   for edge in self.edges:
    if edge.source==node.id:lines.append('Переход'+(' «'+edge.label+'»' if edge.label else '')+': '+nodes[edge.target].text.strip()+'.')
   lines.append('')
  return '\n'.join(lines).strip()
