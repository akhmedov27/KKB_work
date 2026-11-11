"""Bounded local drafts. Document edition and optimistic save version are distinct."""
from typing import Annotated, Literal
from datetime import date
import re
import unicodedata
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Short = Annotated[str, StringConstraints(max_length=500)]
Long = Annotated[str, StringConstraints(max_length=20000)]

class Row(BaseModel):
    model_config = ConfigDict(extra='forbid')

class GlossaryEntry(Row):
    name: Short = ''
    meaning: Annotated[str, StringConstraints(max_length=5000)] = ''


def glossary_key(name):
    alphabet='0123456789абвгдеёжзийклмнопрстуфхцчшщъыьэюяabcdefghijklmnopqrstuvwxyz'
    ranks={char:i for i,char in enumerate(alphabet)}
    name=unicodedata.normalize('NFC',name).casefold()
    return tuple(ranks.get(char,1000+ord(char)) for char in name if char.isalnum())


class Approval(Row):
    role: Literal['Согласовал','Разработал'] = 'Разработал'
    position: Short = ''
    person: Short = ''

class Department(Row):
    name: Short = ''
    marks: list[bool] = Field(default_factory=list,max_length=20)

class Risk(Row):
    event: Short = ''
    probability: int = Field(default=1,ge=1,le=5,strict=True)
    impact: int = Field(default=1,ge=1,le=5,strict=True)
    @property
    def rank(self): return self.probability*self.impact

class Indicator(Row):
    name: Short = ''
    unit: Short = ''
    criterion: Short = ''
    target: Short = ''
    source: Short = ''
    who: Short = ''
    what: Short = ''
    where: Short = ''
    frequency: Short = ''
    responsible: Short = ''

class Change(Row):
    pages: Short = ''
    kind: Literal['Введено впервые','Измененная редакция','Исключено'] = 'Измененная редакция'
    description: Short = ''

class StuContent(Row):
    number: Short = ''
    title: Short = ''
    edition: int = Field(default=1,ge=1,le=999,strict=True)
    order_number: Short = ''
    order_date: date | None = None
    effective_date: date | None = None
    approvals: list[Approval] = Field(default_factory=list,max_length=50)
    annotation: Long = ''
    purpose: Long = ''
    scope: Long = ''
    references: Long = ''
    abbreviations: Long = ''  # Preserve unstructured text from earlier drafts.
    abbreviation_rows: list[GlossaryEntry] = Field(default_factory=list,max_length=100)
    term_rows: list[GlossaryEntry] = Field(default_factory=list,max_length=100)
    owner: Short = ''
    positions: list[Short] = Field(default_factory=lambda:['Зав. отделением','Старшая медсестра','Врач','Медсестра','Младший медперсонал','Санитар'],max_length=20)
    departments: list[Department] = Field(default_factory=list,max_length=100)
    matrix_landscape: bool = False
    process_name: Short = ''
    process_custom: Long = ''
    processes: list[Short] = Field(default_factory=list,max_length=20)
    risks: list[Risk] = Field(default_factory=list,max_length=100)
    indicators: list[Indicator] = Field(default_factory=list,max_length=50)
    proposals_to: Short = ''
    changes_owner: Short = ''
    appendices: list[Short] = Field(default_factory=list,max_length=30)
    changes_reviewed: bool = False
    changes: list[Change] = Field(default_factory=list,max_length=100)

    @model_validator(mode='before')
    @classmethod
    def upgrade_glossary(cls, data):
        if not isinstance(data,dict) or data.get('abbreviation_rows') or not isinstance(data.get('abbreviations'),str):
            return data
        lines=[line.strip() for line in data['abbreviations'].splitlines() if line.strip()]
        pairs=[re.fullmatch(r'(.+?)\s+(?:-|–|—)\s+(.+)',line) for line in lines]
        if lines and len(lines)<=100 and all(pairs) and all(len(m[1].strip())<=500 and len(m[2].strip())<=5000 for m in pairs):
            data={**data,'abbreviations':'','abbreviation_rows':[{'name':m[1].strip(),'meaning':m[2].strip()} for m in pairs]}
        return data

    @model_validator(mode='after')
    def matrix_shape(self):
        if any(len(row.marks)!=len(self.positions) for row in self.departments):
            raise ValueError('Число отметок в строке матрицы должно совпадать с числом должностей.')
        return self

    def export_errors(self):
        errors=[]
        for key,label in {'number':'Номер СТУ','title':'Наименование СТУ','annotation':'Аннотация','purpose':'1 Назначение',
            'scope':'2 Область применения','references':'3 Нормативные ссылки',
            'owner':'Ответственный за стандарт','proposals_to':'Получатель предложений','changes_owner':'Ответственный за изменения'}.items():
            if not getattr(self,key).strip():errors.append(label)
        if not self.abbreviations.strip() and not self.abbreviation_rows and not self.term_rows:errors.append('4 Сокращения и обозначения')
        for rows,label in [(self.abbreviation_rows,'сокращения'),(self.term_rows,'термины')]:
            if any(not row.name.strip() or not row.meaning.strip() for row in rows):errors.append('4 Заполните название и значение: '+label)
        if not self.approvals or any(not r.position.strip() or not r.person.strip() for r in self.approvals):errors.append('Лист согласования: должность и фамилия для каждой строки')
        if not self.positions or any(not p.strip() for p in self.positions):errors.append('Матрица: названия должностей')
        if not self.departments or any(not d.name.strip() for d in self.departments):errors.append('Матрица: названия подразделений')
        if not self.process_custom.strip() and not self.process_name.strip():errors.append('6 Вступление к описанию процесса')
        if not self.processes or any(not p.strip() for p in self.processes):errors.append('Названия блоков процесса')
        if not self.risks or any(not r.event.strip() for r in self.risks):errors.append('7 Возможные прецеденты')
        if not self.indicators or any(any(not str(v).strip() for v in r.model_dump().values()) for r in self.indicators):errors.append('8 Все поля показателей процесса')
        if any(not p.strip() for p in self.appendices):errors.append('Названия приложений')
        if self.edition>1 and (not self.changes_reviewed or not self.changes or any(not r.pages.strip() or not r.description.strip() for r in self.changes)):
            errors.append('Лист регистрации изменений: подтвердите проверку и заполните страницы и описания')
        return errors
