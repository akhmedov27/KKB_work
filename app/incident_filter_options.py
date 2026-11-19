"""Batch-scoped category choices, independent of date and department filters."""
from sqlalchemy import func, select
from app.models import IncidentRecord


def subgroup_query(batch_id, group_name=''):
    statement=select(func.min(IncidentRecord.subgroup)).where(IncidentRecord.batch_id==batch_id)
    group=group_name.strip()
    if group:
        statement=statement.where(func.qms_casefold(IncidentRecord.group_name)==('' if group=='__empty__' else group.casefold()))
    return statement.group_by(func.qms_casefold(IncidentRecord.subgroup))


def subgroup_options(db,batch_id,group_name='',selected=''):
    query=subgroup_query(batch_id,group_name)
    rows=db.scalars(query.order_by(func.qms_casefold(IncidentRecord.subgroup)).limit(501)).all()
    result=rows[:500]
    # A valid active value beyond the first 500 must remain selectable.
    if selected and not any((value or '__empty__').casefold()==selected.strip().casefold() for value in result):
        value=selected.strip()
        extra=db.scalar(query.where(func.qms_casefold(IncidentRecord.subgroup)==('' if value=='__empty__' else value.casefold())).limit(1))
        if extra is not None:result.append(extra)
    return {'items':[{'value':value or '__empty__','label':value or 'Не указано'} for value in result], 'truncated':len(rows)>500}


def reset_unrelated_subgroup(db,batch_id,filters):
    if not filters.group_name.strip() or not filters.subgroup.strip():return
    value=filters.subgroup.strip()
    found=db.scalar(subgroup_query(batch_id,filters.group_name).where(
        func.qms_casefold(IncidentRecord.subgroup)==('' if value=='__empty__' else value.casefold())).limit(1))
    if found is None:
        filters.subgroup=''
        filters.page=1
