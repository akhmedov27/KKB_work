"""Descriptive statistics with explicit denominators, no causal inference."""
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import func, select
from app.models import IncidentRecord


def comparison_table(db, batch_id, filters, current_groups, field_name):
    from app.incident_stats import conditions, percent
    field = getattr(IncidentRecord, field_name)
    previous = db.execute(select(func.min(field), func.count()).where(*conditions(batch_id, filters, True))
                          .group_by(func.qms_casefold(field))).all()
    current = {group['value'].casefold(): (group['label'], group['count']) for group in current_groups}
    before = {name.casefold(): (name or 'Не указано', count) for name, count in previous}
    rows = []
    for key in current.keys() | before.keys():
        label = current.get(key, before.get(key))[0]
        first, second = current.get(key, ('', 0))[1], before.get(key, ('', 0))[1]
        rows.append({'value': key, 'label': label, 'current': first, 'previous': second, 'delta': first-second,
                     'percent': percent(first-second, second) if second else None})
    return sorted(rows, key=lambda row: (-abs(row['delta']), row['label'].casefold()))


def advanced_statistics(db, batch_id, filters, distributions, months, total, where):
    from app.incident_stats import percent
    quarters = defaultdict(int)
    for month in months:
        year, number = month['label'].split('-')
        quarters[f'{year} · {(int(number)-1)//3+1} квартал'] += month['count']
    pareto, running, threshold_count, reached = [], 0, 0, False
    for index, group in enumerate(distributions[filters.pareto_by]):
        running += group['count']
        in_core = not reached
        if in_core:
            threshold_count = index+1
        pareto.append({**group, 'cumulative': percent(running, total), 'in_core': in_core})
        if Decimal(running)*100 >= Decimal(total)*filters.pareto_cutoff:
            reached = True
    cross = db.execute(select(func.min(IncidentRecord.department), func.min(IncidentRecord.group_name), func.count())
                       .where(*where).group_by(func.qms_casefold(IncidentRecord.department), func.qms_casefold(IncidentRecord.group_name))
                       .order_by(func.count().desc(), func.min(IncidentRecord.department), func.min(IncidentRecord.group_name))).all()
    department_counts = {group['value'].casefold(): group['count'] for group in distributions['department']}
    cross_rows = [{'department': department or 'Не указано', 'group': group or 'Не указано', 'count': count,
                   'department_percent': percent(count, department_counts[department.casefold()]),
                   'total_percent': percent(count, total)} for department, group, count in cross]
    shown = pareto[:15]
    maximum = max((item['count'] for item in shown), default=0)
    bars, points = [], []
    for index, item in enumerate(shown):
        width = 650 / len(shown)
        x = 55 + index*width
        height = item['count'] / maximum * 190 if maximum else 0
        bars.append({**item, 'x': x, 'y': 210-height, 'width': width*0.65, 'height': height, 'index': index+1})
        points.append(f'{x+width*0.325:.2f},{210-float(item["cumulative"])*1.9:.2f}')
    return {'pareto_chart': bars, 'pareto_points': ' '.join(points), 'pareto_max': maximum,
            'quarter_max': max(quarters.values(), default=0), 'quarters': [{'label': label, 'count': count} for label, count in sorted(quarters.items())],
            'pareto': pareto, 'pareto_core_count': threshold_count,
            'pareto_core_percent': pareto[threshold_count-1]['cumulative'] if threshold_count else Decimal('0.00'),
            'department_comparison': comparison_table(db, batch_id, filters, distributions['department'], 'department') if filters.compare_from else [],
            'group_comparison': comparison_table(db, batch_id, filters, distributions['group_name'], 'group_name') if filters.compare_from else [],
            'cross_rows': cross_rows,
            'missing_departments': sum(group['count'] for group in distributions['department'] if not group['value']),
            'missing_causes': sum(group['count'] for group in distributions['root_cause'] if not group['value'])}
