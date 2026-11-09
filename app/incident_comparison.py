"""Read-only snapshot comparison by exact incident number; no merged dataset."""
from collections import Counter
import json
from openpyxl import Workbook
from sqlalchemy import select
from app.incident_excel import FIELDS, TEXT_FIELDS
from app.incident_export import append, finish
from app.models import IncidentRecord

LABELS = {key: FIELDS[key][0] for key in ('occurred_on', 'registered_on', *TEXT_FIELDS)}
KINDS = {'added': 'Только в новом наборе', 'missing': 'Отсутствуют в новом наборе',
         'changed': 'Изменены', 'unchanged': 'Без изменений'}


class ComparisonProblem(ValueError):
    pass


def compare(db, before, after):
    if before.id == after.id:
        raise ComparisonProblem('Выберите два разных набора.')
    if before.state != 'confirmed' or after.state != 'confirmed':
        raise ComparisonProblem('Для сравнения нужны два подтверждённых набора.')
    maps = [json.loads(batch.mapping_json)['mapping'] for batch in (before, after)]
    def mapped(mapping, key):
        return bool(mapping.get(key) or (key == 'event_name' and mapping.get('event_fallback')))
    fields = [key for key in LABELS if all(mapped(mapping, key) for mapping in maps)]
    excluded = [LABELS[key] for key in LABELS if key not in fields]
    snapshots, periods = [], []
    for batch in (before, after):
        rows = db.scalars(select(IncidentRecord).where(IncidentRecord.batch_id == batch.id)
                          .order_by(IncidentRecord.source_row)).all()
        snapshot = {}
        for row in rows:
            if row.external_id in snapshot:
                raise ComparisonProblem('В одном из наборов номер инцидента встречается несколько раз. '
                                        'Для однозначного сравнения подтвердите импорт по уникальным номерам.')
            snapshot[row.external_id] = row
        snapshots.append(snapshot)
        dates = [row.occurred_on for row in rows]
        periods.append({'count': len(rows), 'minimum': min(dates) if dates else None,
                        'maximum': max(dates) if dates else None})
    old, new = snapshots
    groups = {key: [] for key in KINDS}
    changes = []
    changed_fields = Counter()
    for number in sorted(old.keys() | new.keys()):
        left, right = old.get(number), new.get(number)
        differences = [{'field': key, 'label': LABELS[key], 'before': getattr(left, key), 'after': getattr(right, key)}
                       for key in fields if left is not None and right is not None and getattr(left, key) != getattr(right, key)]
        kind = 'added' if left is None else 'missing' if right is None else 'changed' if differences else 'unchanged'
        item = {'number': number, 'before': left, 'after': right, 'differences': differences}
        groups[kind].append(item)
        for difference in differences:
            changed_fields[difference['label']] += 1
            changes.append({'number': number, **difference})
    distribution = {}
    for key in ('status', 'department', 'group_name'):
        if key not in fields:
            continue
        counts = [Counter(getattr(row, key) for row in snapshot.values()) for snapshot in snapshots]
        distribution[key] = [{'label': value or 'Не указано', 'before': counts[0][value], 'after': counts[1][value],
                              'delta': counts[1][value]-counts[0][value]}
                             for value in sorted(counts[0].keys() | counts[1].keys())]
    warnings = []
    if maps[0] != maps[1]:
        warnings.append('Сопоставления столбцов различаются. Проверьте, что номер, дата и отделение имеют одинаковый смысл в обоих файлах.')
    if periods[0]['minimum'] != periods[1]['minimum'] or periods[0]['maximum'] != periods[1]['maximum']:
        warnings.append('Диапазоны дат различаются. Новые и отсутствующие номера могут быть следствием разных периодов выгрузки.')
    if excluded:
        warnings.append('Не сравниваются поля, не выбранные хотя бы в одном импорте: ' + ', '.join(excluded) + '.')
    return {'groups': groups, 'counts': {key: len(value) for key, value in groups.items()}, 'changes': changes,
            'changed_fields': dict(changed_fields), 'periods': periods, 'warnings': warnings,
            'fields': [LABELS[key] for key in fields], 'distribution': distribution}


def export_comparison(result, before, after):
    book = Workbook(); summary = book.active; summary.title = 'Сравнение наборов'
    append(summary, ['Показатель', 'Значение'])
    append(summary, ['Исходный набор', before.id]); append(summary, ['Новый набор', after.id])
    append(summary, ['Правило', 'Точное совпадение номера инцидента. Полные наборы, без фильтров панели статистики.'])
    append(summary, ['Ограничение', 'Отсутствие номера не означает удаление. Без изменений означает равенство только сравниваемых аналитических полей.'])
    append(summary, ['Сравниваемые поля', '; '.join(result['fields'])])
    for index, period in enumerate(result['periods']):
        append(summary, [('Исходный' if index == 0 else 'Новый') + ' набор: диапазон дат', f"{period['minimum']} — {period['maximum']}"])
        append(summary, [('Исходный' if index == 0 else 'Новый') + ' набор: записей', period['count']])
    for warning in result['warnings']: append(summary, ['Предупреждение', warning])
    for key, count in result['counts'].items(): append(summary, [KINDS[key], count])
    for key, items in result['groups'].items():
        sheet = book.create_sheet(KINDS[key])
        append(sheet, ['Номер инцидента', 'Строка исходного Excel', 'Строка нового Excel', 'Дата до', 'Дата после', 'Отделение до', 'Отделение после', 'Статус до', 'Статус после'])
        for item in items:
            left, right = item['before'], item['after']
            append(sheet, [item['number'], left.source_row if left else None, right.source_row if right else None,
                           left.occurred_on if left else None, right.occurred_on if right else None,
                           left.department if left else '', right.department if right else '',
                           left.status if left else '', right.status if right else ''])
    sheet = book.create_sheet('Изменённые поля')
    append(sheet, ['Номер инцидента', 'Поле', 'Было', 'Стало'])
    for item in result['changes']: append(sheet, [item['number'], item['label'], item['before'], item['after']])
    sheet = book.create_sheet('Сводка изменений полей'); append(sheet, ['Поле', 'Изменённых номеров'])
    for label, count in result['changed_fields'].items(): append(sheet, [label, count])
    for key, rows in result['distribution'].items():
        sheet = book.create_sheet('Динамика — ' + {'status':'статусы','department':'отделения','group_name':'группы'}[key])
        append(sheet, [LABELS[key], 'Исходный набор', 'Новый набор', 'Разница'])
        for row in rows: append(sheet, [row['label'], row['before'], row['after'], row['delta']])
    return finish(book)
