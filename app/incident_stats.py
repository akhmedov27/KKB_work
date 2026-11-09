"""Deterministic incident statistics. No model calls or inferred classifications."""
from datetime import date
from typing import Annotated, Literal
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator
from sqlalchemy import distinct, func, select
from app.models import IncidentRecord
from app.department_aliases import selected_departments

DIMENSIONS = {'department': 'Отделение', 'department_type': 'Тип отделения', 'group_name': 'Группа',
              'subgroup': 'Подгруппа', 'event_name': 'Вид события', 'importance': 'Важность', 'status': 'Статус',
              'urgent': 'Срочные меры', 'source_method': 'Способ регистрации', 'root_cause': 'Корневая причина'}


class Filters(BaseModel):
    batch_id: int | None = Field(default=None, ge=1)
    date_from: date | None = None
    date_to: date | None = None
    compare_from: date | None = None
    compare_to: date | None = None
    department: str = Field(default='', max_length=500)
    departments: list[Annotated[str, StringConstraints(max_length=500)]] = Field(default_factory=list, max_length=50)
    exclude_statuses: list[Annotated[str, StringConstraints(max_length=500)]] = Field(default_factory=list, max_length=50)
    pareto_by: Literal['group_name', 'event_name', 'root_cause'] = 'event_name'
    pareto_cutoff: int = Field(default=80, ge=1, le=100)
    min_repeat: int = Field(default=2, ge=2, le=20000)
    group_name: str = Field(default='', max_length=500)
    subgroup: str = Field(default='', max_length=500)
    event_name: str = Field(default='', max_length=5000)
    importance: str = Field(default='', max_length=500)
    status: str = Field(default='', max_length=500)
    number: str = Field(default='', max_length=64)
    page: int = Field(default=1, ge=1, le=1000000)

    @field_validator('departments', 'exclude_statuses')
    @classmethod
    def clean_list(cls, values):
        result, seen = [], set()
        for value in values:
            value = value.strip()
            if value and value.casefold() not in seen:
                result.append(value)
                seen.add(value.casefold())
        return result

    @model_validator(mode='after')
    def dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('Начало периода позже окончания')
        if bool(self.compare_from) != bool(self.compare_to):
            raise ValueError('Для сравнения укажите обе даты второго периода')
        if self.compare_from and self.compare_from > self.compare_to:
            raise ValueError('Начало второго периода позже окончания')
        return self


def percent(part, total):
    if not total:
        return Decimal('0.00')
    return (Decimal(part) * 100 / Decimal(total)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def conditions(batch_id, filters, comparison=False):
    values = [IncidentRecord.batch_id == batch_id]
    start, end = (filters.compare_from, filters.compare_to) if comparison else (filters.date_from, filters.date_to)
    if start:
        values.append(IncidentRecord.occurred_on >= start)
    if end:
        values.append(IncidentRecord.occurred_on <= end)
    departments = selected_departments(filters)
    if departments:
        values.append(func.qms_casefold(IncidentRecord.department).in_(['' if item == '__empty__' else item.casefold() for item in departments]))
    if filters.exclude_statuses:
        values.append(func.qms_casefold(IncidentRecord.status).not_in(['' if item == '__empty__' else item.casefold() for item in filters.exclude_statuses]))
    for key in ('group_name', 'subgroup', 'event_name', 'importance', 'status'):
        selected = getattr(filters, key).strip()
        if selected:
            field = getattr(IncidentRecord, key)
            values.append(func.qms_casefold(field) == ('' if selected == '__empty__' else selected.casefold()))
    if filters.number.strip():
        values.append(IncidentRecord.external_id == filters.number.strip())
    return values


def statistics(db, batch_id, filters):
    where = conditions(batch_id, filters)
    total, unique, minimum, maximum = db.execute(select(func.count(), func.count(distinct(IncidentRecord.external_id)),
        func.min(IncidentRecord.occurred_on), func.max(IncidentRecord.occurred_on)).where(*where)).one()
    distributions = {}
    for key in DIMENSIONS:
        field = getattr(IncidentRecord, key)
        rows = db.execute(select(func.min(field), func.count()).where(*where).group_by(func.qms_casefold(field)).order_by(func.count().desc(), func.min(field))).all()
        distributions[key] = [{'label': label or 'Не указано', 'value': label, 'count': count, 'percent': percent(count, total)} for label, count in rows]
    monthly = dict(db.execute(select(func.strftime('%Y-%m', IncidentRecord.occurred_on), func.count()).where(*where)
                             .group_by(func.strftime('%Y-%m', IncidentRecord.occurred_on))).all())
    start, end = filters.date_from or minimum, filters.date_to or maximum
    if start and end and (end.year-start.year)*12+end.month-start.month <= 120:
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            monthly.setdefault(f'{year:04d}-{month:02d}', 0)
            year, month = (year+1, 1) if month == 12 else (year, month+1)
    months = [{'label': month, 'count': count} for month, count in sorted(monthly.items())]
    comparison = None
    if filters.compare_from:
        previous = db.scalar(select(func.count()).select_from(IncidentRecord).where(*conditions(batch_id, filters, True)))
        comparison = {'count': previous, 'delta': total-previous, 'percent': percent(total-previous, previous) if previous else None,
                      'days': (filters.compare_to-filters.compare_from).days+1,
                      'overlap': bool(start and end and start <= filters.compare_to and end >= filters.compare_from)}
    repeated = db.execute(select(func.min(IncidentRecord.department), func.min(IncidentRecord.event_name), func.count(),
        func.min(IncidentRecord.occurred_on), func.max(IncidentRecord.occurred_on)).where(*where, IncidentRecord.event_name != '')
        .group_by(func.qms_casefold(IncidentRecord.department), func.qms_casefold(IncidentRecord.event_name))
        .having(func.count() >= filters.min_repeat).order_by(func.count().desc(), func.min(IncidentRecord.department), func.min(IncidentRecord.event_name))).all()
    from app.incident_analytics import advanced_statistics
    advanced = advanced_statistics(db, batch_id, filters, distributions, months, total, where)
    return {**advanced, 'repeated': repeated, 'total': total, 'unique': unique, 'minimum': minimum, 'maximum': maximum, 'groups': distributions,
            'months': months, 'comparison': comparison, 'month_max': max([m['count'] for m in months], default=0)}


def register_rows(db, batch_id, filters, all_rows=False):
    statement = select(IncidentRecord).where(*conditions(batch_id, filters)).order_by(IncidentRecord.occurred_on, IncidentRecord.source_row)
    if not all_rows:
        statement = statement.offset((filters.page-1)*50).limit(50)
    return db.scalars(statement).all()
