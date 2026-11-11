"""Local period reports. Counts reuse statistics(); comments are never sent to AI."""
from calendar import monthrange
from datetime import date
from io import BytesIO
import re
import struct
from typing import Literal
import zlib

from docx import Document
from docx.shared import Inches, Pt, Cm
from docx.oxml import OxmlElement
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from app.models import IncidentRecord
from app.incident_stats import DIMENSIONS, statistics

MONTHS = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь']


class ReportPeriod(BaseModel):
    report_kind: Literal['month', 'quarter'] = 'month'
    report_year: int = Field(default_factory=lambda: date.today().year, ge=1901, le=9998)
    report_month: int = Field(default_factory=lambda: date.today().month, ge=1, le=12)
    report_quarter: int = Field(default=1, ge=1, le=4)

    def bounds(self):
        first = self.report_month if self.report_kind == 'month' else (self.report_quarter-1)*3+1
        last = first if self.report_kind == 'month' else first+2
        start = date(self.report_year, first, 1)
        end = date(self.report_year, last, monthrange(self.report_year, last)[1])
        previous_end = date.fromordinal(start.toordinal()-1)
        previous_first = previous_end.month if self.report_kind == 'month' else previous_end.month-2
        return start, end, date(previous_end.year, previous_first, 1), previous_end

    @property
    def label(self):
        return f'{MONTHS[self.report_month-1]} {self.report_year}' if self.report_kind == 'month' else f'{self.report_quarter} квартал {self.report_year}'


def prepare_report(db, batch, filters, period):
    start, end, previous_start, previous_end = period.bounds()
    filters = filters.model_copy(update={'batch_id':batch.id, 'date_from':start, 'date_to':end,
                                         'compare_from':previous_start, 'compare_to':previous_end, 'page':1})
    stats = statistics(db, batch.id, filters)
    actual = db.execute(select(func.min(IncidentRecord.occurred_on), func.max(IncidentRecord.occurred_on))
                        .where(IncidentRecord.batch_id == batch.id)).one()
    return {'period':period, 'filters':filters, 'stats':stats, 'source_min':actual[0], 'source_max':actual[1],
            'days':(end-start).days+1, 'previous_days':(previous_end-previous_start).days+1}


def text(value):
    """Remove non-XML characters from user values while preserving ordinary text."""
    return re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]', '', str(value if value is not None else 'Не указано'))


def bar_png(count, maximum):
    """Small fixed-size PNG strip; labels and numbers remain editable in Word."""
    width, height = 400, 16
    filled = round(width*count/maximum) if maximum else 0
    row = b'\x00' + b'\x16\x6a\x64'*filled + b'\xea\xf4\xf1'*(width-filled)
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(row*height))+chunk(b'IEND',b'')


def document_report(report, batch, upload, comment=''):
    doc=Document()
    section=doc.sections[0]
    section.top_margin=section.bottom_margin=Cm(1.8)
    section.left_margin=section.right_margin=Cm(1.7)
    style=doc.styles['Normal']; style.font.name='Arial'; style.font.size=Pt(10)
    for name in ['Title','Heading 1','Heading 2']: doc.styles[name].font.name='Arial'
    doc.core_properties.title='Аналитический отчёт по инцидентам'
    doc.core_properties.author='QMS Assistant KKB'
    stats, filters=report['stats'],report['filters']
    def p(value): doc.add_paragraph(text(value))
    def table(headers, rows, proportions=None):
        result=doc.add_table(rows=1, cols=len(headers));result.style='Light Shading Accent 1'
        result.autofit=False
        n=len(headers)
        proportions=proportions or ([.35,.65] if n==2 else [.45,.1375,.1375,.1375,.1375] if n==5 else [.55]+[.45/(n-1)]*(n-1))
        usable=section.page_width-section.left_margin-section.right_margin
        for column, fraction in zip(result.columns, proportions): column.width=int(usable*fraction)
        header=OxmlElement('w:tblHeader');result.rows[0]._tr.get_or_add_trPr().append(header)
        def fill(row, values):
            row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
            for cell,value,fraction in zip(row.cells,values,proportions):
                cell.width=int(usable*fraction);cell.text=text(value)
        fill(result.rows[0],headers)
        for row in rows: fill(result.add_row(),row)
        return result
    def chart(title, rows):
        doc.add_heading(title,level=2)
        if not rows or not any(count for _,count in rows): p('Нет записей для диаграммы.');return
        maximum=max(count for _,count in rows)
        result=table(['Категория','Количество (общая шкала)','Записей'],[],[.47,.40,.13])
        for label,count in rows:
            row=result.add_row();row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
            cells=row.cells
            for cell,column in zip(cells,result.columns):cell.width=column.width
            cells[0].text=text(label);cells[2].text=str(count)
            cells[1].paragraphs[0].add_run().add_picture(BytesIO(bar_png(count,maximum)),width=Inches(2.0),height=Inches(.10))
        p(f'Шкала одинакова для всех строк диаграммы: 0–{maximum}. Подписи и значения редактируются как текст Word.')
    doc.add_heading('Аналитический отчёт по инцидентам',0)
    p(report['period'].label)
    p('Рабочий отчёт QMS Assistant KKB. Не является утверждённой формой ККБ. Используйте синтетические данные.')
    doc.add_heading('1. Источник и правила подсчёта',1)
    table(['Параметр','Значение'],[
        ['Подтверждённый набор',batch.id],['Исходный файл',upload.original_name],['Лист',batch.sheet_name],
        ['Период отчёта',f'{filters.date_from} — {filters.date_to} ({report["days"]} дней)'],
        ['Предыдущий период',f'{filters.compare_from} — {filters.compare_to} ({report["previous_days"]} дней)'],
        ['Диапазон дат всего набора',f'{report["source_min"] or "Нет данных"} — {report["source_max"] or "Нет данных"}'],
        ['Основа подсчёта','Один инцидент на уникальный номер' if batch.policy=='unique' else 'Все подтверждённые строки отдельно'],
        ['Идентификатор','Номер инцидента из выбранного столбца (B в согласованном образце); порядковый A не используется']])
    p('Сравниваются два периода одного набора с одинаковыми фильтрами. Полнота периода не подтверждается; отсутствие записей не доказывает отсутствие инцидентов. Количества не нормируются по длительности, госпитализациям или койко-дням.')
    labels={**DIMENSIONS,'departments':'Выбранные отделения','exclude_statuses':'Исключённые статусы','number':'Номер инцидента',
            'pareto_by':'Поле Парето','pareto_cutoff':'Порог Парето, %','min_repeat':'Минимум повторяемости'}
    rows=[]
    for key in ['departments','group_name','subgroup','event_name','importance','status','root_cause','exclude_statuses','number','pareto_by','pareto_cutoff','min_repeat']:
        value=getattr(filters,key)
        if isinstance(value,list): value='; '.join('Не указано' if v=='__empty__' else v for v in value) or 'Все / нет ограничений'
        elif key=='pareto_by': value=DIMENSIONS[value]
        elif value=='__empty__': value='Не указано'
        elif value=='': value='Все / нет ограничений'
        rows.append([labels[key],value])
    table(['Фильтр / настройка','Значение'],rows)
    doc.add_heading('2. Основные показатели и сравнение',1)
    comp=stats['comparison']
    table(['Показатель','Значение'],[['Записей в текущем периоде',stats['total']],['Уникальных номеров',stats['unique']],
        ['Записей в предыдущем периоде',comp['count']],['Изменение количества',comp['delta']],
        ['Относительное изменение','Не определяется: база 0' if comp['percent'] is None else f'{comp["percent"]}%']])
    p('Изменение = текущий период − предыдущий. Процент = изменение / количество предыдущего периода × 100%. Плюс и минус не означают автоматически ухудшение или улучшение.')
    doc.add_heading('3. Динамика',1)
    chart('Динамика по месяцам даты инцидента',[(row['label'],row['count']) for row in stats['months']])
    doc.add_heading('4. Отделения и категории',1)
    for key in ['department','group_name','event_name','status']:
        doc.add_heading(DIMENSIONS[key]+' — первые 10 по количеству',2)
        rows=stats['groups'][key][:10]
        table(['Категория','Количество','Доля, %'],[[r['label'],r['count'],r['percent']] for r in rows] or [['Нет данных',0,'—']])
        if key=='department': chart('Диаграмма отделений — первые 10',[(r['label'],r['count']) for r in rows])
    p('Доли считаются от всех записей текущей выборки, включая пустые категории «Не указано». Первые 10 категорий не обязательно составляют 100%; полные распределения доступны в Excel.')
    doc.add_heading('5. Парето',1)
    p(f'Поле: {DIMENSIONS[filters.pareto_by]}. Порог: {filters.pareto_cutoff}%.')
    if stats['total']:
        p(f'Порог достигается на {stats["pareto_core_count"]} категориях; накопленная доля {stats["pareto_core_percent"]}%. Включена категория, пересекающая порог. Пустые значения участвуют в расчёте.')
    else: p('Нет записей: Парето не рассчитывается.')
    table(['Категория (первые 10)','Количество','Доля, %','Накоплено, %'],[[r['label'],r['count'],r['percent'],r['cumulative']] for r in stats['pareto'][:10]] or [['Нет данных',0,'—','—']])
    p('Частота указанной причины не доказывает причинную связь или тяжесть события.')
    doc.add_heading('6. Повторяющиеся сочетания',1)
    p(f'Одинаковое отделение и вид события, минимум {filters.min_repeat} записей. Первые 10 сочетаний; это не вывод о повторном событии у одного пациента.')
    table(['Отделение','Событие','Записей','Первая / последняя дата'],[[row[0] or 'Не указано',row[1],row[2],f'{row[3]} / {row[4]}'] for row in stats['repeated'][:10]] or [['Нет сочетаний','—',0,'—']],[.28,.40,.10,.22])
    doc.add_heading('7. Сравнение отделений и групп',1)
    for key,title in [('department_comparison','Отделения'),('group_comparison','Группы')]:
        doc.add_heading(title+' — первые 10 по абсолютному изменению',2)
        table(['Категория','Текущий','Предыдущий','Разница','Изменение, %'],[[r['label'],r['current'],r['previous'],r['delta'],r['percent'] if r['percent'] is not None else 'База 0'] for r in stats[key][:10]] or [['Нет данных',0,0,0,'База 0']])
    doc.add_heading('8. Заполненность данных',1)
    missing_event=sum(r['count'] for r in stats['groups']['event_name'] if not r['value'])
    table(['Пустое поле','Записей'],[['Отделение',stats['missing_departments']],['Вид события',missing_event],['Корневая причина',stats['missing_causes']]])
    p('Оценивается наличие значения, а не его правильность. Без знаменателей нельзя сравнивать частоту риска между отделениями.')
    doc.add_heading('9. Комментарий пользователя',1)
    p(comment.strip() or 'Комментарий не добавлен.')
    p('Комментарий введён пользователем и не проверен приложением. Автоматические медицинские выводы и выводы ИИ не формировались.')
    output=BytesIO();doc.save(output);return output.getvalue()
