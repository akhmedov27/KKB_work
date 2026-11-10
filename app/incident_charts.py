"""Bounded chart payloads; all counts share the dashboard's SQL conditions."""
from calendar import monthrange
from datetime import date
from urllib.parse import urlencode
from sqlalchemy import func, select
from app.models import IncidentRecord
from app.incident_stats import conditions, DIMENSIONS


def chart_data(db, batch_id, filters, stats):
    args = {key: value for key, value in filters.model_dump(mode='json').items()
            if value is not None and value != '' and value != []}
    args['batch_id'] = batch_id

    def link(**changes):
        values = {**args, **changes, 'page': 1}
        return '/modules/incidents?' + urlencode(values, doseq=True) + '#incident-register'

    def value(raw):
        return raw or '__empty__'

    def month_link(month, **changes):
        year, number = map(int, month.split('-'))
        start, end = date(year, number, 1), date(year, number, monthrange(year, number)[1])
        start = max(start, filters.date_from) if filters.date_from else start
        end = min(end, filters.date_to) if filters.date_to else end
        return link(date_from=start.isoformat(), date_to=end.isoformat(), **changes)

    departments = stats['groups']['department'][:15]
    charts = []
    charts.append({'id': 'months', 'title': 'Динамика по месяцам', 'type': 'bars',
                   'note': 'Последние 24 месяца выбранного диапазона; ноль не подтверждает полноту данных.',
                   'rows': [{'label': row['label'], 'values': [row['count']], 'hrefs': [month_link(row['label'])]}
                            for row in stats['months'][-24:]], 'series': ['Количество']})
    charts.append({'id': 'departments', 'title': 'Инциденты по отделениям', 'type': 'bars',
                   'note': 'Первые 15 отделений по количеству. Полные названия; количество зарегистрированных записей, не уровень риска.',
                   'rows': [{'label': row['label'], 'values': [row['count']], 'hrefs': [link(departments=[value(row['value'])], department='')]}
                            for row in departments], 'series': ['Количество']})
    months = [row['label'] for row in stats['months'][-24:]]
    where = conditions(batch_id, filters)
    monthly = db.execute(select(func.qms_casefold(IncidentRecord.department), func.strftime('%Y-%m', IncidentRecord.occurred_on), func.count())
                         .where(*where).group_by(func.qms_casefold(IncidentRecord.department), func.strftime('%Y-%m', IncidentRecord.occurred_on))).all()
    month_counts = {(dept, month): count for dept, month, count in monthly}
    charts.append({'id': 'heat-month', 'title': 'Отделение × месяц', 'type': 'heat', 'columns': months,
                   'note': 'Первые 15 отделений по количеству × последние 24 месяца. Цвет показывает количество; ноль — отсутствие записей в наборе.',
                   'rows': [{'label': row['label'], 'values': [month_counts.get((row['value'].casefold(), month), 0) for month in months],
                             'hrefs': [month_link(month, departments=[value(row['value'])], department='') for month in months]} for row in departments]})
    groups = stats['groups']['group_name'][:12]
    # SQL groups raw empty values separately from literal "Не указано" labels.
    cross_raw = db.execute(select(func.qms_casefold(IncidentRecord.department), func.qms_casefold(IncidentRecord.group_name), func.count())
                           .where(*where).group_by(func.qms_casefold(IncidentRecord.department), func.qms_casefold(IncidentRecord.group_name))).all()
    cross = {(dept, group): count for dept, group, count in cross_raw}
    charts.append({'id': 'heat-group', 'title': 'Отделение × группа событий', 'type': 'heat', 'columns': [row['label'] for row in groups],
                   'note': 'Первые 15 отделений × первые 12 групп по количеству. Остальные категории не включены в рисунок; полные данные — в Excel.',
                   'rows': [{'label': row['label'], 'values': [cross.get((row['value'].casefold(), group['value'].casefold()), 0) for group in groups],
                             'hrefs': [link(departments=[value(row['value'])], department='', group_name=value(group['value'])) for group in groups]} for row in departments]})
    statuses = stats['groups']['status']
    # Keep a bounded legend without silently discarding the remaining statuses.
    shown_statuses = statuses[:8]
    status_counts = db.execute(select(func.qms_casefold(IncidentRecord.department), func.qms_casefold(IncidentRecord.status), func.count())
                              .where(*where).group_by(func.qms_casefold(IncidentRecord.department), func.qms_casefold(IncidentRecord.status))).all()
    status_counts = {(dept, status): count for dept, status, count in status_counts}
    status_rows = []
    for row in departments:
        counts = [status_counts.get((row['value'].casefold(), status['value'].casefold()), 0) for status in shown_statuses]
        hrefs = [link(departments=[value(row['value'])], department='', status=value(status['value'])) for status in shown_statuses]
        if len(statuses) > 8:
            counts.append(row['count']-sum(counts)); hrefs.append(None)
        status_rows.append({'label': row['label'], 'values': counts, 'hrefs': hrefs})
    charts.append({'id': 'statuses', 'title': 'Статусы по отделениям', 'type': 'stack',
                   'note': 'Первые 15 отделений. Проценты считаются внутри каждого отделения в текущей выборке. Остальные статусы объединены в «Другие статусы».',
                   'series': [row['label'] for row in shown_statuses] + (['Другие статусы'] if len(statuses) > 8 else []), 'rows': status_rows})
    comparison = stats['department_comparison'][:15]
    charts.append({'id': 'periods', 'title': 'Сравнение отделений за два периода', 'type': 'bars',
                   'note': (f"Второй период: {filters.compare_from} — {filters.compare_to}. Первые 15 по абсолютному изменению; количества без нормирования на длительность."
                            + (' Периоды пересекаются.' if stats['comparison'] and stats['comparison']['overlap'] else ''))
                           if filters.compare_from else 'Задайте обе даты второго периода в фильтрах. Количества сравниваются без нормирования на длительность.',
                   'series': ['Текущий период', 'Второй период'],
                   'rows': [{'label': row['label'], 'values': [row['current'], row['previous']],
                             'hrefs': [link(departments=[value(row['value'])], department=''),
                                       link(departments=[value(row['value'])], department='', date_from=filters.compare_from.isoformat(), date_to=filters.compare_to.isoformat())]}
                            for row in comparison]})
    charts.append({'id': 'quality', 'title': 'Заполненность данных', 'type': 'stack',
                   'note': 'Проверяется только наличие значения. Доля считается от всех записей текущей выборки.',
                   'series': ['Заполнено', 'Не указано'],
                   'rows': [{'label': label, 'values': [stats['total']-missing, missing],
                             'hrefs': [None, link(**({'departments': ['__empty__'], 'department': ''} if field == 'department' else {field: '__empty__'}))]}
                            for label, field, missing in [('Отделение', 'department', stats['missing_departments']),
                                ('Вид события', 'event_name', sum(row['count'] for row in stats['groups']['event_name'] if not row['value'])),
                                ('Корневая причина', 'root_cause', stats['missing_causes'])]]})
    charts.append({'id': 'pareto', 'title': 'Парето: ' + DIMENSIONS[filters.pareto_by], 'type': 'pareto',
                   'note': f"Первые 15 категорий. Линия — накопленная доля всей выборки, порог {filters.pareto_cutoff}%. Полные названия — ниже и в таблице Парето.",
                   'threshold': filters.pareto_cutoff, 'series': ['Количество', 'Накопленная доля, %'],
                   'rows': [{'label': row['label'], 'values': [row['count'], float(row['cumulative'])],
                             'hrefs': [link(**{filters.pareto_by: value(row['value'])})] if filters.pareto_by in ('group_name', 'event_name', 'root_cause') else []}
                            for row in stats['pareto'][:15]]})
    return {'context': f"Набор № {batch_id}. Даты: {filters.date_from or stats['minimum'] or 'нет'} — {filters.date_to or stats['maximum'] or 'нет'}. Записей: {stats['total']}. Действуют фильтры выборки.",
            'charts': charts}


def snapshot_chart(result, before_id, after_id):
    labels = {'added': 'Только в новом наборе', 'missing': 'Отсутствуют в новом наборе',
              'changed': 'Изменены', 'unchanged': 'Без изменений'}
    return {'context': f'Сравнение наборов № {before_id} → № {after_id}. Отсутствие номера не означает удаление.',
            'charts': [{'id': 'snapshots', 'title': 'Изменения между выгрузками', 'type': 'bars', 'series': ['Номеров'],
                        'note': 'Каждый номер входит ровно в одну категорию. Нажмите столбец для просмотра номеров.',
                        'rows': [{'label': label, 'values': [result['counts'][key]],
                                  'hrefs': ['/incidents/compare?' + urlencode({'before_id': before_id, 'after_id': after_id, 'kind': key})]}
                                 for key, label in labels.items()]}]}
