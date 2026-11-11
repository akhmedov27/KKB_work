"""Incident pages, explicit import review and local Excel export."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, Query
from fastapi.responses import RedirectResponse, Response
from openpyxl.utils import get_column_letter
from pydantic import ValidationError
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.incident_excel import FIELDS
from app.incident_import import ImportProblem, confirm, prepare, run_worker
from app.incident_stats import DIMENSIONS, Filters, register_rows, statistics
from app.incident_export import statistics_export, validation_export
from app.models import IncidentBatch, IncidentRecord, IncidentStagedRow, IncidentUpload
from app.storage import save_upload
from app.department_aliases import selected_departments, suggestions
from app.incident_report import ReportPeriod, MONTHS, prepare_report, document_report
from app.incident_charts import chart_data, snapshot_chart
from app.incident_comparison import compare, export_comparison, ComparisonProblem, KINDS


def make_router(sessions, settings, render, logger):
    router = APIRouter()
    folder = settings.data_dir.resolve() / 'incident_imports'
    folder.mkdir(parents=True, exist_ok=True)

    def page(request, template, **context):
        return render(request, template, active='incidents', title='Инциденты', dimensions=DIMENSIONS, **context)

    def filters_for(request, params=None):
        params = request.query_params if params is None else params
        values = {key: value for key, value in params.items() if value != ''}
        for key in ('departments', 'exclude_statuses'):
            values[key] = params.getlist(key)
        try:
            filters = Filters.model_validate(values)
            filters.departments = selected_departments(filters)
            filters.department = ''
            return filters
        except (ValidationError, ValueError):
            raise HTTPException(400, 'Проверьте даты, номер набора и длину фильтров. Для сравнения нужны обе даты второго периода; начало не позже окончания.') from None

    def selected_batch(db, filters):
        batch = db.get(IncidentBatch, filters.batch_id) if filters.batch_id else db.scalar(select(IncidentBatch).where(IncidentBatch.state == 'confirmed').order_by(IncidentBatch.confirmed_at.desc(), IncidentBatch.id.desc()).limit(1))
        if batch is not None and batch.state != 'confirmed':
            raise HTTPException(400, 'Этот импорт ещё не подтверждён. Откройте его проверку.')
        if filters.batch_id and batch is None:
            raise HTTPException(404)
        return batch

    @router.get('/modules/incidents')
    def dashboard(request: Request):
        filters = filters_for(request)
        with sessions() as db:
            batches = db.scalars(select(IncidentBatch).order_by(IncidentBatch.id.desc()).limit(20)).all()
            batch = selected_batch(db, filters)
            if batch is None:
                return page(request, 'incidents.html', batch=None, batches=batches)
            filters.batch_id = batch.id
            upload = db.get(IncidentUpload, batch.upload_id)
            stats = statistics(db, batch.id, filters)
            rows = register_rows(db, batch.id, filters)
            charts = chart_data(db, batch.id, filters, stats)
            options = {}
            for key in ('department', 'group_name', 'subgroup', 'event_name', 'importance', 'status', 'root_cause'):
                field = getattr(IncidentRecord, key)
                options[key] = db.scalars(select(field).where(IncidentRecord.batch_id == batch.id).distinct().order_by(field).limit(500)).all()
        args = {key: value for key, value in filters.model_dump(mode='json').items() if value is not None and value != '' and value != []}
        def url(page_number):
            return '/modules/incidents?' + urlencode({**args, 'page': page_number}, doseq=True)
        return page(request, 'incidents.html', batch=batch, batches=batches, upload=upload, summary=json.loads(batch.summary_json),
                    stats=stats, rows=rows, filters=filters, options=options, charts=charts,
                    report_url='/incidents/report?' + urlencode(args, doseq=True),
                    export_url='/incidents/export.xlsx?' + urlencode(args, doseq=True),
                    previous_url=url(filters.page-1) if filters.page > 1 else None,
                    next_url=url(filters.page+1) if filters.page*50 < stats['total'] else None)

    def report_for(db, request, params):
        filters = filters_for(request, params)
        try:
            period = ReportPeriod.model_validate({key: value for key, value in params.items() if key.startswith('report_') and value != ''})
        except ValidationError:
            raise HTTPException(400, 'Выберите месяц или квартал, год 1901–9998, месяц 1–12 и квартал 1–4.') from None
        batch = selected_batch(db, filters)
        if batch is None:
            raise HTTPException(400, 'Сначала подтвердите импорт инцидентов.')
        upload = db.get(IncidentUpload, batch.upload_id)
        report = prepare_report(db, batch, filters, period)
        return batch, upload, report

    @router.get('/incidents/report')
    def report_page(request: Request):
        with sessions() as db:
            batch, upload, report = report_for(db, request, request.query_params)
        filters = report['filters']
        args = {key: value for key, value in filters.model_dump(mode='json').items() if value is not None and value != '' and value != []}
        hidden = [(key, item) for key, value in args.items() if key not in ('date_from','date_to','compare_from','compare_to','page')
                  for item in (value if isinstance(value, list) else [value])]
        return page(request, 'incident_report.html', batch=batch, upload=upload, report=report, months=MONTHS,
                    report_hidden=hidden, period_hidden=report['period'].model_dump(),
                    report_excel_url='/incidents/export.xlsx?' + urlencode(args, doseq=True))

    @router.post('/incidents/report.docx')
    async def report_docx(request: Request):
        form = await request.form()
        comment = form.get('comment', '')
        if not isinstance(comment, str) or len(comment) > 12000:
            raise HTTPException(400, 'Комментарий должен содержать не более 12 000 символов.')
        def generate():
            with sessions() as db:
                batch, upload, report = report_for(db, request, form)
                return document_report(report, batch, upload, comment)
        content = await run_in_threadpool(generate)
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        headers={'Content-Disposition': 'attachment; filename="incident_period_report.docx"'})

    def comparison_result(db, before_id, after_id):
        before, after = db.get(IncidentBatch, before_id), db.get(IncidentBatch, after_id)
        if before is None or after is None:
            raise HTTPException(404, 'Набор не найден.')
        try:
            return before, after, compare(db, before, after)
        except ComparisonProblem as exc:
            raise HTTPException(400, str(exc)) from None

    @router.get('/incidents/compare')
    def compare_page(request: Request, before_id: int | None = Query(None, ge=1),
                     after_id: int | None = Query(None, ge=1), kind: str = Query('changed', pattern='^(added|missing|changed|unchanged)$'),
                     page_number: int = Query(1, ge=1, le=1000000)):
        with sessions() as db:
            batches = db.scalars(select(IncidentBatch).where(IncidentBatch.state == 'confirmed')
                                 .order_by(IncidentBatch.confirmed_at.desc(), IncidentBatch.id.desc())).all()
            uploads = {item.id: db.get(IncidentUpload, item.upload_id).original_name for item in batches}
            result, before, after = None, None, None
            if before_id is not None and after_id is not None:
                before, after, result = comparison_result(db, before_id, after_id)
            elif before_id is not None or after_id is not None:
                raise HTTPException(400, 'Выберите исходный и новый наборы.')
        def link(target_kind, number):
            return '/incidents/compare?' + urlencode({'before_id': before_id, 'after_id': after_id, 'kind': target_kind, 'page_number': number})
        count = result['counts'][kind] if result else 0
        return page(request, 'incident_comparison.html', batches=batches, uploads=uploads, result=result,
                    before=before, after=after, kinds=KINDS, kind=kind, page_number=page_number,
                    charts=snapshot_chart(result, before.id, after.id) if result else None,
                    items=result['groups'][kind][(page_number-1)*50:page_number*50] if result else [],
                    links={key: link(key, 1) for key in KINDS},
                    previous_url=link(kind, page_number-1) if page_number > 1 else None,
                    next_url=link(kind, page_number+1) if page_number*50 < count else None)

    @router.get('/incidents/compare.xlsx')
    def compare_export(before_id: int = Query(..., ge=1), after_id: int = Query(..., ge=1)):
        with sessions() as db:
            before, after, result = comparison_result(db, before_id, after_id)
            content = export_comparison(result, before, after)
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="incident_comparison.xlsx"'})

    @router.get('/incidents/departments')
    def department_search(batch_id: int, q: str = Query('', max_length=500)):
        with sessions() as db:
            batch = db.get(IncidentBatch, batch_id)
            if batch is None or batch.state != 'confirmed':
                raise HTTPException(404)
            actual = db.scalars(select(IncidentRecord.department).where(IncidentRecord.batch_id == batch_id).distinct()).all()
        return {'items': suggestions(actual, q)}

    @router.post('/incidents/uploads')
    async def upload(request: Request, file: UploadFile = File(...)):
        if Path(file.filename or '').suffix.lower() != '.xlsx':
            await file.close()
            raise HTTPException(400, 'Для реестра инцидентов нужен XLSX.')
        name, stored, _ = await save_upload(file, folder, settings.max_upload_mb*1024*1024)
        try:
            info = await run_in_threadpool(run_worker, folder, folder / stored)
            def register():
                with (folder / stored).open('rb') as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                upload_id = uuid.uuid4().hex
                with sessions.begin() as db:
                    db.add(IncidentUpload(id=upload_id, original_name=name, stored_name=stored, sha256=digest,
                                          inspection_json=json.dumps(info, ensure_ascii=False)))
                return upload_id
            upload_id = await run_in_threadpool(register)
        except ImportProblem as exc:
            (folder / stored).unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from None
        except Exception:
            (folder / stored).unlink(missing_ok=True)
            raise
        logger.info('Загружен реестр для проверки; id=%s', upload_id)
        return RedirectResponse('/incidents/uploads/' + upload_id, status_code=303)

    @router.get('/incidents/uploads/{upload_id}')
    def mapping_page(request: Request, upload_id: str, sheet: str | None = None):
        with sessions() as db:
            upload = db.get(IncidentUpload, upload_id)
        if upload is None:
            raise HTTPException(404)
        info = json.loads(upload.inspection_json)
        selected = next((item for item in info['sheets'] if item['name'] == sheet), None) if sheet else info['sheets'][0]
        if selected is None:
            raise HTTPException(400, 'Лист не найден.')
        columns = [(index+1, f'{get_column_letter(index+1)} · {header or "Без заголовка"}') for index, header in enumerate(selected['headers'])]
        return page(request, 'incident_mapping.html', upload=upload, sheets=info['sheets'], selected=selected, columns=columns, fields=FIELDS)

    @router.post('/incidents/uploads/{upload_id}/prepare')
    async def prepare_import(request: Request, upload_id: str):
        form = await request.form()
        try:
            mapping = {key: int(form[key]) if form.get(key) else None for key in FIELDS}
            config = {'sheet': str(form['sheet']), 'header_row': int(form['header_row']), 'mapping': mapping}
        except (ValueError, KeyError):
            raise HTTPException(400, 'Проверьте выбор листа и столбцов.') from None
        with sessions() as db:
            upload = db.get(IncidentUpload, upload_id)
        if upload is None:
            raise HTTPException(404)
        try:
            batch_id = await run_in_threadpool(prepare, sessions, upload, folder, config)
        except ImportProblem as exc:
            raise HTTPException(400, str(exc)) from None
        return RedirectResponse(f'/incidents/imports/{batch_id}', status_code=303)

    @router.get('/incidents/imports/{batch_id}')
    def preview(request: Request, batch_id: int):
        with sessions() as db:
            batch = db.get(IncidentBatch, batch_id)
            if batch is None:
                raise HTTPException(404)
            upload = db.get(IncidentUpload, batch.upload_id)
            rows = db.scalars(select(IncidentStagedRow).where(IncidentStagedRow.batch_id == batch_id).order_by(IncidentStagedRow.source_row).limit(20)).all()
            issues = db.scalars(select(IncidentStagedRow).where(IncidentStagedRow.batch_id == batch_id,
                 (IncidentStagedRow.errors_json != '[]') | (IncidentStagedRow.duplicate_of.is_not(None)) | IncidentStagedRow.conflict)
                 .order_by(IncidentStagedRow.source_row).limit(50)).all()
        def unpack(row):
            return {'row': row, 'payload': json.loads(row.payload_json), 'errors': json.loads(row.errors_json), 'warnings': json.loads(row.warnings_json)}
        return page(request, 'incident_preview.html', batch=batch, upload=upload, summary=json.loads(batch.summary_json),
                    rows=[unpack(row) for row in rows], issues=[unpack(row) for row in issues])

    @router.post('/incidents/imports/{batch_id}/confirm')
    def confirm_import(batch_id: int, policy: str = Form('unique'), skip_invalid: bool = Form(False)):
        try:
            count = confirm(sessions, batch_id, policy, skip_invalid)
        except ImportProblem as exc:
            raise HTTPException(400, str(exc)) from None
        logger.info('Подтверждён импорт; набор=%d; записей=%d', batch_id, count)
        return RedirectResponse(f'/modules/incidents?batch_id={batch_id}', status_code=303)

    @router.get('/incidents/imports/{batch_id}/report.xlsx')
    def check_report(batch_id: int):
        with sessions() as db:
            batch = db.get(IncidentBatch, batch_id)
            if batch is None:
                raise HTTPException(404)
            result = validation_export(db, batch)
        return Response(result, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="incident_validation.xlsx"'})

    @router.get('/incidents/export.xlsx')
    def export(request: Request):
        filters = filters_for(request)
        with sessions() as db:
            batch = selected_batch(db, filters)
            if batch is None:
                raise HTTPException(400, 'Сначала подтвердите импорт.')
            upload = db.get(IncidentUpload, batch.upload_id)
            result = statistics_export(db, batch, upload, filters, statistics(db, batch.id, filters), register_rows(db, batch.id, filters, True))
        logger.info('Экспорт статистики; набор=%d', batch.id)
        return Response(result, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="incident_statistics.xlsx"'})

    return router
