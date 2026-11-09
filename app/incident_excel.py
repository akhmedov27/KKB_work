"""Bounded XLSX inspection and validation. Contents are data, never code."""
from datetime import date, datetime
import hashlib
import json
import re

from openpyxl import load_workbook
from app.extract_worker import check_office_package

MAX_ROWS = 20_000
MAX_COLUMNS = 100
MAX_CELLS = 1_000_000
MAX_TEXT = 10_000_000
FIELDS = {
    'external_id': ('Номер инцидента', 'Номер инцидента'),
    'occurred_on': ('Дата инцидента', 'Дата инцидента'),
    'registered_on': ('Дата регистрации', 'Дата регистрации'),
    'department': ('Отделение для статистики', 'Отделение госпитализации пациента'),
    'department_type': ('Тип отделения', 'Тип отделения'),
    'group_name': ('Группа', 'Группа'),
    'subgroup': ('Подгруппа', 'Подгруппа'),
    'event_name': ('Вид события', 'Неблагоприятное событие (наименование инцидента)'),
    'event_fallback': ('Резервное наименование, если основное пусто', 'Произвольное наименование'),
    'importance': ('Важность (исходный код)', 'Важность'),
    'status': ('Статус', 'Статус'),
    'urgent': ('Необходимость срочных мер', 'Необходимость срочных мер'),
    'source_method': ('Способ регистрации', 'Способ зарегистрирован'),
    'root_cause': ('Корневая причина', 'Корневая причина'),
}
class IncidentValidationError(ValueError):
    pass


REQUIRED = {'external_id', 'occurred_on'}
TEXT_FIELDS = ('department', 'department_type', 'group_name', 'subgroup', 'event_name', 'importance', 'status', 'urgent', 'source_method', 'root_cause')


def clean(value):
    text = re.sub(r'\s+', ' ', str(value if value is not None else '')).strip()
    return '' if text.casefold() in {'null', 'none', 'nan'} else text


def number(value):
    if isinstance(value, bool):
        raise IncidentValidationError('Некорректный номер инцидента')
    if isinstance(value, (int, float)):
        if value < 0 or int(value) != value:
            raise IncidentValidationError('Номер инцидента должен быть целым или текстовым идентификатором')
        value = str(int(value))
    text = clean(value)
    if not text or len(text) > 64:
        raise IncidentValidationError('Не указан или слишком длинный номер инцидента')
    return text


def parse_date(value, required=False):
    if value is None or clean(value) == '':
        if required:
            raise IncidentValidationError('Не указана дата')
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d.%m.%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError:
            pass
    raise IncidentValidationError('Некорректная дата: нужна дата Excel, ДД.ММ.ГГГГ или ГГГГ-ММ-ДД')


def open_book(path):
    check_office_package(path, '.xlsx', allow_print_settings=True)
    return load_workbook(path, read_only=True, data_only=False, keep_links=False)


def inspect(path):
    workbook = open_book(path)
    try:
        if len(workbook.worksheets) > 20:
            raise IncidentValidationError('Допускается не более 20 листов')
        sheets = []
        for sheet in workbook:
            if (sheet.max_column or 0) > MAX_COLUMNS:
                raise IncidentValidationError('Допускается не более 100 столбцов')
            candidates = []
            for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=10, max_col=min(sheet.max_column or 1, MAX_COLUMNS)), 1):
                headers = [clean(cell.value)[:255] for cell in row]
                if any(headers):
                    score = sum(clean(expected).casefold() in [v.casefold() for v in headers] for _, expected in FIELDS.values())
                    candidates.append({'row': row_number, 'headers': headers, 'score': score})
            best = max(candidates, key=lambda c: c['score']) if candidates else {'row': 1, 'headers': [], 'score': 0}
            mapping = {}
            for key, (_, expected) in FIELDS.items():
                matches = [index + 1 for index, title in enumerate(best['headers']) if title.casefold() == expected.casefold()]
                mapping[key] = matches[-1] if matches else None
            sheets.append({'name': sheet.title, 'rows': sheet.max_row or 0, 'header_row': best['row'],
                           'headers': best['headers'], 'mapping': mapping})
        return {'sheets': sheets}
    finally:
        workbook.close()


def parse(path, config):
    workbook = open_book(path)
    try:
        sheet = workbook[config['sheet']]
        header_row = int(config['header_row'])
        if not 1 <= header_row <= 10:
            raise IncidentValidationError('Строка заголовков должна быть от 1 до 10')
        mapping = config['mapping']
        if set(mapping) != set(FIELDS) or any(not mapping.get(key) for key in REQUIRED):
            raise IncidentValidationError('Выберите столбцы номера и даты инцидента')
        columns = [int(v) for v in mapping.values() if v is not None]
        if any(v < 1 or v > MAX_COLUMNS for v in columns):
            raise IncidentValidationError('Некорректный номер столбца')
        if len(columns) != len(set(columns)):
            raise IncidentValidationError('Один столбец нельзя назначить разным полям')
        if (sheet.max_column or 0) > MAX_COLUMNS or (sheet.max_row or 0) > MAX_ROWS + header_row:
            raise IncidentValidationError('Лимит импорта: 20 000 строк, 100 столбцов')
        headers = next(sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True), ())
        if any(v > len(headers) for v in columns):
            raise IncidentValidationError('Выбранный столбец отсутствует')
        if clean(headers[mapping['external_id']-1]) == '№':
            raise IncidentValidationError('Выбран порядковый №. Укажите столбец «Номер инцидента», в вашем образце это B.')
        forbidden = ('фио', '№иб', 'лечащий врач', 'ответственный', 'описание неблагоприятного', 'коментарий к закрытию')
        for column in columns:
            if any(token in clean(headers[column-1]).casefold() for token in forbidden):
                raise IncidentValidationError('Именные поля, номера историй болезни и описания не предназначены для этой статистики')
        records, first_by_id, conflicts, text_size, cells, blanks = [], {}, set(), 0, 0, 0
        for row_index, row in enumerate(sheet.iter_rows(min_row=header_row + 1), header_row + 1):
            cells += len(row)
            if cells > MAX_CELLS or row_index - header_row > MAX_ROWS:
                raise IncidentValidationError('Превышен лимит: 20 000 строк или 1 000 000 ячеек')
            if not any(cell.value is not None for cell in row):
                blanks += 1
                continue
            errors, warnings, payload = [], [], {}
            values = {}
            for key, col in mapping.items():
                cell = row[col-1] if col else None
                if cell is not None and cell.data_type == 'f':
                    errors.append(f'{FIELDS[key][0]}: формула не импортируется и не вычисляется')
                if cell is not None and cell.data_type == 'e':
                    errors.append(f'{FIELDS[key][0]}: ошибка Excel в ячейке')
                values[key] = cell.value if cell is not None and cell.data_type not in {'f', 'e'} else None
            try:
                payload['external_id'] = number(values['external_id'])
            except (ValueError, OverflowError) as exc:
                payload['external_id'] = ''
                errors.append(str(exc))
            for key in ('occurred_on', 'registered_on'):
                try:
                    payload[key] = parse_date(values[key], key == 'occurred_on')
                except ValueError as exc:
                    payload[key] = None
                    errors.append(f'{FIELDS[key][0]}: {exc}')
            fallback = False
            for key in TEXT_FIELDS:
                value = clean(values[key])
                if key == 'event_name' and not value:
                    value = clean(values['event_fallback'])
                    fallback = bool(value)
                limit = 5000 if key in {'event_name', 'root_cause'} else 500
                if len(value) > limit:
                    errors.append(f'{FIELDS[key][0]}: более {limit} символов')
                    value = ''
                payload[key] = value
            for key in ('department', 'group_name', 'event_name', 'importance', 'status'):
                if not payload[key]:
                    warnings.append(f'{FIELDS[key][0]}: не указано')
            signature = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            duplicate_of = None
            conflict = False
            if not errors:
                external_id = payload['external_id']
                if external_id in first_by_id:
                    first, fingerprint = first_by_id[external_id]
                    duplicate_of = first
                    if signature != fingerprint:
                        conflicts.add(external_id)
                else:
                    first_by_id[external_id] = (row_index, signature)
            text_size += sum(len(str(v or '')) for v in payload.values())
            if text_size > MAX_TEXT:
                raise IncidentValidationError('Объём выбранных текстовых полей превышает 10 млн символов')
            records.append({'source_row': row_index, 'payload': payload, 'errors': errors,
                            'warnings': warnings, 'duplicate_of': duplicate_of, 'conflict': conflict, 'fallback': fallback})
        for record in records:
            record['conflict'] = record['payload']['external_id'] in conflicts
        valid = [r for r in records if not r['errors']]
        dates = [r['payload']['occurred_on'] for r in valid]
        return {'records': records, 'summary': {'rows': len(records), 'valid': len(valid), 'invalid': len(records)-len(valid),
                'duplicates': sum(r['duplicate_of'] is not None for r in valid), 'unique': len(first_by_id),
                'conflicts': len(conflicts), 'blank_rows': blanks, 'fallback': sum(r['fallback'] for r in valid),
                'min_date': min(dates) if dates else None, 'max_date': max(dates) if dates else None}}
    finally:
        workbook.close()
