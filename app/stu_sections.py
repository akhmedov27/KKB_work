"""Editable STU outline: two heading levels, text and ordinary tables."""
from typing import Annotated, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from app.qualigram_model import ID

Short=Annotated[str,StringConstraints(max_length=500)]
Long=Annotated[str,StringConstraints(max_length=20000)]
Cell=Annotated[str,StringConstraints(max_length=5000)]

class Item(BaseModel):
 model_config=ConfigDict(extra='forbid')
 id:ID=Field(default_factory=lambda:uuid4().hex)

class TextBlock(Item):
 kind:Literal['text']='text'
 text:Long=''

class TableBlock(Item):
 kind:Literal['table']='table'
 title:Short=''
 headers:list[Short]=Field(default_factory=lambda:['',''],min_length=1,max_length=10)
 rows:list[list[Cell]]=Field(default_factory=lambda:[['','']],max_length=50)

 @model_validator(mode='after')
 def rectangular(self):
  if any(len(row)!=len(self.headers) for row in self.rows):raise ValueError('Число ячеек не совпадает с числом столбцов.')
  return self

Block=Annotated[TextBlock|TableBlock,Field(discriminator='kind')]

class Subsection(Item):
 title:Short=''
 blocks:list[Block]=Field(default_factory=list,max_length=50)

class Section(Subsection):
 subsections:list[Subsection]=Field(default_factory=list,max_length=20)


def outline(sections):
 for i,section in enumerate(sections,1):
  yield str(i),1,section
  for j,subsection in enumerate(section.subsections,1):yield f'{i}.{j}',2,subsection


def section_errors(sections):
 errors=[]
 if not sections:errors.append('Добавьте хотя бы один раздел.')
 for number,level,section in outline(sections):
  label='Раздел '+number
  if not section.title.strip():errors.append(label+': заполните название.')
  if not section.blocks and (level==2 or not section.subsections):errors.append(label+': добавьте текст или таблицу.')
  for i,block in enumerate(section.blocks,1):
   prefix=f'{label}, блок {i}: '
   if block.kind=='text' and not block.text.strip():errors.append(prefix+'заполните текст или удалите пустой блок.')
   if block.kind=='table':
    if any(not h.strip() for h in block.headers):errors.append(prefix+'заполните заголовки столбцов.')
    if not block.rows or not any(c.strip() for row in block.rows for c in row):errors.append(prefix+'добавьте данные таблицы.')
 return errors


def template_sections():
 # Structure only: no automatic clinical content or special-table imitation.
 titles=['НАЗНАЧЕНИЕ','ОБЛАСТЬ ПРИМЕНЕНИЯ','НОРМАТИВНЫЕ ССЫЛКИ','СОКРАЩЕНИЯ И ОБОЗНАЧЕНИЯ','ОТВЕТСТВЕННОСТЬ',
         'ОПИСАНИЕ ПРОЦЕССА','ОЦЕНКА РИСКОВ','ПОКАЗАТЕЛИ ПРОЦЕССА','ВНЕСЕНИЕ ИЗМЕНЕНИЙ','ХРАНЕНИЕ']
 return [Section(title=title,blocks=[TextBlock()]) for title in titles]
