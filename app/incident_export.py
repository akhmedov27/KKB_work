"""Excel exports: all user strings are explicitly stored as text, not formulas."""
from io import BytesIO
import json
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from sqlalchemy import select
from app.models import IncidentStagedRow
from app.incident_stats import DIMENSIONS


def append(sheet, row):
    sheet.append(row)
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.value = ILLEGAL_CHARACTERS_RE.sub('', cell.value)
            cell.data_type = 's'  # =, +, -, @ remain literal text in Excel.


def finish(workbook):
    for sheet in workbook:
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='166A64')
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(55, max(14, max(len(str(c.value or '')) for c in column[:100]) + 2))
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical='top', wrap_text=True)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def add_validation(workbook, db, batch_id):
    errors = workbook.create_sheet('Ошибки импорта')
    duplicates = workbook.create_sheet('Повторы')
    append(errors, ['Строка Excel', 'Номер инцидента', 'Ошибка', 'Предупреждения'])
    append(duplicates, ['Строка Excel', 'Номер инцидента', 'Первое вхождение', 'Различаются данные'])
    for row in db.scalars(select(IncidentStagedRow).where(IncidentStagedRow.batch_id == batch_id).order_by(IncidentStagedRow.source_row)):
        payload, issues, warnings = json.loads(row.payload_json), json.loads(row.errors_json), json.loads(row.warnings_json)
        if issues or warnings:
            append(errors, [row.source_row, payload['external_id'], '; '.join(issues), '; '.join(warnings)])
        if row.duplicate_of is not None or row.conflict:
            append(duplicates, [row.source_row, payload['external_id'], row.duplicate_of, 'Да' if row.conflict else 'Нет'])


def validation_export(db, batch):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Проверка'
    append(sheet, ['Параметр', 'Значение'])
    append(sheet, ['Лист', batch.sheet_name])
    for key, value in json.loads(batch.summary_json).items():
        append(sheet, [{'rows':'Строки', 'valid':'Корректные строки', 'invalid':'Строки с ошибками', 'duplicates':'Повторные вхождения номера', 'unique':'Уникальные номера', 'conflicts':'Конфликтующие номера', 'blank_rows':'Пустые строки', 'fallback':'Применено резервное наименование', 'min_date':'Минимальная дата инцидента', 'max_date':'Максимальная дата инцидента'}[key], value])
    add_validation(workbook, db, batch.id)
    return finish(workbook)


def statistics_export(db, batch, upload, filters, stats, rows):
    workbook = Workbook()
    summary = workbook.active
    summary.title = 'Сводка'
    append(summary, ['Показатель', 'Значение'])
    append(summary, ['Файл', upload.original_name])
    append(summary, ['Лист', batch.sheet_name])
    mapping = json.loads(batch.mapping_json)
    append(summary, ['Столбец номера инцидента', get_column_letter(mapping['mapping']['external_id'])])
    append(summary, ['Столбец даты инцидента', get_column_letter(mapping['mapping']['occurred_on'])])
    append(summary, ['Столбец отделения', get_column_letter(mapping['mapping']['department']) if mapping['mapping']['department'] else 'Не импортируется'])
    append(summary, ['Основа подсчёта', 'Уникальные номера из выбранного столбца' if batch.policy == 'unique' else 'Все импортированные строки'])
    append(summary, ['Количество в выборке', stats['total']])
    append(summary, ['Уникальных номеров', stats['unique']])
    append(summary, ['Доля в таблицах', 'Число записей категории / количество в текущей выборке × 100%. Пустые категории включены.'])
    for key, value in filters.model_dump().items():
        if key != 'page' and value is not None and value != '':
            append(summary, [{**DIMENSIONS, 'batch_id':'Номер набора', 'date_from':'Дата инцидента с', 'date_to':'Дата инцидента по', 'compare_from':'Второй период с', 'compare_to':'Второй период по', 'number':'Номер инцидента'}.get(key, key), value])
    if stats['comparison']:
        for key, value in stats['comparison'].items():
            append(summary, ['Сравнение: ' + {'count':'Количество во втором периоде','delta':'Изменение количества','percent':'Изменение, %','days':'Длительность второго периода, дней','overlap':'Периоды пересекаются'}[key], str(value) if value is not None else 'Не рассчитывается при базе 0'])
    for key, label in DIMENSIONS.items():
        sheet = workbook.create_sheet(label[:31])
        append(sheet, [label, 'Количество', 'Доля, %'])
        for group in stats['groups'][key]:
            append(sheet, [group['label'], group['count'], float(group['percent'])])
        if key == 'department' and sheet.max_row > 1:
            chart = BarChart()
            chart.type = 'bar'; chart.title = 'Отделения: первые 10 по количеству'
            chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=min(11, sheet.max_row)), titles_from_data=True)
            chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=min(11, sheet.max_row)))
            sheet.add_chart(chart, 'E2')
    monthly = workbook.create_sheet('Динамика')
    append(monthly, ['Месяц', 'Количество'])
    for month in stats['months']:
        append(monthly, [month['label'], month['count']])
    if monthly.max_row > 1:
        chart = LineChart(); chart.title = 'Динамика по дате инцидента'
        chart.add_data(Reference(monthly, min_col=2, min_row=1, max_row=monthly.max_row), titles_from_data=True)
        chart.set_categories(Reference(monthly, min_col=1, min_row=2, max_row=monthly.max_row))
        monthly.add_chart(chart, 'D2')
    repeated = workbook.create_sheet('Повторяемость')
    append(repeated, ['Отделение', 'Вид события', 'Количество записей', 'Первая дата', 'Последняя дата'])
    for row in stats['repeated']:
        append(repeated, list(row))
    register = workbook.create_sheet('Реестр')
    append(register, ['Номер инцидента', 'Дата инцидента', 'Дата регистрации', *DIMENSIONS.values(), 'Строка исходного листа'])
    for row in rows:
        append(register, [row.external_id, row.occurred_on, row.registered_on, *[getattr(row, key) for key in DIMENSIONS], row.source_row])
    add_validation(workbook, db, batch.id)
    return finish(workbook)
