"""Staged incident imports with a bounded worker and atomic confirmation."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from app.models import IncidentBatch, IncidentStagedRow, IncidentRecord, now

_GATE = threading.BoundedSemaphore(1)


class ImportProblem(Exception):
    pass


def run_worker(folder: Path, source: Path, config=None):
    if not _GATE.acquire(blocking=False):
        raise ImportProblem('Другой файл ещё проверяется. Повторите попытку после завершения.')
    token = uuid.uuid4().hex
    output, config_file = folder / (token + '.json'), folder / (token + '.config.json')
    try:
        args = [sys.executable, '-m', 'app.incident_worker', 'parse' if config else 'inspect', str(source.resolve()), str(output.resolve())]
        if config:
            config_file.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
            args.append(str(config_file.resolve()))
        result = subprocess.run(args, cwd=Path(__file__).resolve().parent.parent,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'},
                                timeout=30, capture_output=True, check=False)
        if result.returncode or not output.is_file() or output.stat().st_size > 64 * 1024 * 1024:
            raise ImportProblem('Не удалось проверить файл: превышен лимит ресурсов или процесс завершился с ошибкой.')
        value = json.loads(output.read_text(encoding='utf-8'))
        if not value['ok']:
            raise ImportProblem(value['error'])
        return value['result']
    except subprocess.TimeoutExpired:
        raise ImportProblem('Проверка превысила 30 секунд. Разделите файл на части.') from None
    except (OSError, ValueError, KeyError):
        raise ImportProblem('Не удалось запустить проверку XLSX. Проверьте локальное хранилище и зависимости.') from None
    finally:
        output.unlink(missing_ok=True)
        config_file.unlink(missing_ok=True)
        _GATE.release()


def prepare(sessions, upload, folder, config):
    fingerprint = hashlib.sha256((upload.sha256 + json.dumps(config, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
    with sessions() as db:
        existing = db.scalar(select(IncidentBatch.id).where(IncidentBatch.fingerprint == fingerprint))
        if existing:
            return existing
    result = run_worker(folder, folder / upload.stored_name, config)
    try:
        with sessions.begin() as db:
            batch = IncidentBatch(upload_id=upload.id, fingerprint=fingerprint, sheet_name=config['sheet'],
                                  mapping_json=json.dumps(config, ensure_ascii=False), summary_json=json.dumps(result['summary']))
            db.add(batch)
            db.flush()
            batch_id = batch.id
            if result['records']:
                db.execute(insert(IncidentStagedRow), [{'batch_id': batch_id, 'source_row': row['source_row'],
                    'payload_json': json.dumps(row['payload'], ensure_ascii=False), 'errors_json': json.dumps(row['errors'], ensure_ascii=False),
                    'warnings_json': json.dumps(row['warnings'], ensure_ascii=False), 'duplicate_of': row['duplicate_of'],
                    'conflict': row['conflict']} for row in result['records']])
        return batch_id
    except IntegrityError:
        with sessions() as db:
            existing = db.scalar(select(IncidentBatch.id).where(IncidentBatch.fingerprint == fingerprint))
            if existing:
                return existing
        raise


def confirm(sessions, batch_id, policy, skip_invalid=False):
    if policy not in {'unique', 'rows'}:
        raise ImportProblem('Выберите способ подсчёта: уникальные номера или все строки.')
    with sessions.begin() as db:
        batch = db.get(IncidentBatch, batch_id)
        if batch is None:
            raise ImportProblem('Проверка импорта не найдена.')
        if batch.state == 'confirmed':
            return batch.imported_count
        summary = json.loads(batch.summary_json)
        if not summary['valid']:
            raise ImportProblem('Нет корректных строк для импорта.')
        if summary['invalid'] and not skip_invalid:
            raise ImportProblem('В файле есть ошибки. Исправьте файл или явно разрешите импорт только корректных строк.')
        if summary['conflicts'] and policy == 'unique':
            raise ImportProblem('Одинаковые номера содержат разные данные. Исправьте источник или выберите подсчёт всех строк.')
        claimed = db.execute(update(IncidentBatch).where(IncidentBatch.id == batch_id, IncidentBatch.state == 'draft')
                             .values(state='confirmed', confirmed_at=now(), policy=policy)).rowcount
        if not claimed:
            db.expire(batch)
            return db.get(IncidentBatch, batch_id).imported_count
        staged = db.scalars(select(IncidentStagedRow).where(IncidentStagedRow.batch_id == batch_id).order_by(IncidentStagedRow.source_row)).all()
        records = []
        for row in staged:
            if json.loads(row.errors_json) or (policy == 'unique' and row.duplicate_of is not None):
                continue
            payload = json.loads(row.payload_json)
            payload['occurred_on'] = date.fromisoformat(payload['occurred_on'])
            payload['registered_on'] = date.fromisoformat(payload['registered_on']) if payload['registered_on'] else None
            records.append({'batch_id': batch_id, 'source_row': row.source_row, **payload})
        db.execute(insert(IncidentRecord), records)
        batch.imported_count = len(records)
        return len(records)
