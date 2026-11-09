from contextlib import closing
from io import BytesIO
import sqlite3
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from docx import Document as WordDocument
from openpyxl import Workbook
import pymupdf

from app.config import Settings
from app.database import build_engine
from app.extraction import ExtractionResult, extract_local
from app.extract_worker import extract
from app.main import create_app
from app.models import Document, DocumentExtraction


def fixture_bytes(extension):
    buffer = BytesIO()
    if extension == 'docx':
        document = WordDocument()
        document.add_paragraph('Тестовый документ СМК <script>test</script>')
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = 'Проверка'
        table.cell(0, 1).text = 'Качество'
        document.save(buffer)
    elif extension == 'xlsx':
        workbook = Workbook()
        workbook.active.title = 'План СМК'
        workbook.active.append(['Процесс', 'Оценка'])
        workbook.active.append(['Аудит', 5])
        workbook.active['C2'] = '=1+1'
        workbook.save(buffer)
        workbook.close()
    else:
        with pymupdf.open() as document:
            document.new_page().insert_text((72, 72), 'Synthetic PDF quality text')
            document.new_page().insert_text((72, 72), 'Second page')
            buffer.write(document.tobytes())
    return buffer.getvalue()


@pytest.fixture
def local(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        yield client, tmp_path


@pytest.mark.parametrize('extension,expected', [('docx', 'Качество'), ('xlsx', 'Лист: План СМК'), ('pdf', '[Страница 2]')])
def test_real_upload_extract_persist(local, extension, expected):
    client, path = local
    body = fixture_bytes(extension)
    response = client.post('/uploads', files={'file': (f'test.{extension}', body)})
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ready'
    html = client.get(data['url']).text
    assert expected in html
    assert 'Текст извлечён' in html
    if extension == 'docx':
        assert '<script>test</script>' not in html
        assert '&lt;script&gt;test&lt;/script&gt;' in html
        assert 'Проверка | Качество' in html
    if extension == 'xlsx':
        assert '=1+1' not in html
    engine = build_engine(path / 'qms.sqlite3')
    with Session(engine) as db:
        extraction = db.get(DocumentExtraction, data['id'])
        document = db.get(Document, data['id'])
        assert expected in extraction.text and extraction.status == 'ready'
        assert (path / 'uploads' / document.stored_name).read_bytes() == body
    engine.dispose()
    assert client.post(data['url'] + '/extract').json()['status'] == 'ready'
    with TestClient(create_app(Settings(data_dir=path, _env_file=None))) as restarted:
        assert expected in restarted.get(data['url']).text


def test_corrupt_original_retained_with_error(local):
    client, path = local
    data = client.post('/uploads', files={'file': ('bad.pdf', b'not a PDF')}).json()
    assert data['status'] == 'error'
    assert len(list((path / 'uploads').iterdir())) == 1
    assert 'Ошибка обработки' in client.get(data['url']).text
    assert 'Ошибка обработки' in client.get('/modules/knowledge').text
    assert client.get('/health').status_code == 200
    assert client.get('/documents/9999').status_code == 404
    assert client.post('/documents/9999/extract').status_code == 404


def test_empty_scan_and_password_pdf(local):
    client, _ = local
    with pymupdf.open() as document:
        page = document.new_page()
        page.draw_rect(pymupdf.Rect(10, 10, 40, 40))
        scan = document.tobytes()
        protected = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='test')
    data = client.post('/uploads', files={'file': ('scan.pdf', scan)}).json()
    assert data['status'] == 'empty'
    assert 'OCR' in client.get(data['url']).text
    data = client.post('/uploads', files={'file': ('protected.pdf', protected)}).json()
    assert data['status'] == 'error'
    assert 'паролем' in client.get(data['url']).text


def test_empty_docx_and_formula_not_evaluated(tmp_path):
    path = tmp_path / 'empty.docx'
    WordDocument().save(path)
    assert extract(path).status == 'empty'
    workbook = Workbook()
    workbook.active['A1'] = '=1+1'
    path = tmp_path / 'formula.xlsx'
    workbook.save(path)
    workbook.close()
    result = extract(path)
    assert result.status == 'empty' and result.text == ''


def test_ooxml_entities_rejected(tmp_path):
    path = tmp_path / 'entity.docx'
    with ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<!DOCTYPE a [<!ENTITY b SYSTEM "file:///no-access">]><a>&b;</a>')
    result = extract(path)
    assert result.status == 'error' and not result.text


def test_macro_package_rejected(tmp_path):
    path = tmp_path / 'macro.docx'
    with ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<document/>')
        archive.writestr('word/vbaProject.bin', b'do not execute')
    result = extract(path)
    assert result.status == 'error' and 'макросами' in result.notice


def test_zip_expansion_limit(tmp_path):
    path = tmp_path / 'oversized.xlsx'
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('xl/workbook.xml', '<x>' + 'a' * (33 * 1024 * 1024) + '</x>')
    result = extract(path)
    assert result.status == 'error' and '32 МиБ' in result.notice


def test_text_and_page_limits(tmp_path, monkeypatch):
    import app.extract_worker as worker
    path = tmp_path / 'text.docx'
    path.write_bytes(fixture_bytes('docx'))
    monkeypatch.setattr(worker, 'MAX_TEXT_CHARS', 10)
    assert extract(path).status == 'error'
    monkeypatch.setattr(worker, 'MAX_PDF_PAGES', 1)
    path = tmp_path / 'pages.pdf'
    path.write_bytes(fixture_bytes('pdf'))
    assert '200 страниц' in extract(path).notice


def test_worker_timeout_and_crash_release_gate(tmp_path, monkeypatch):
    import app.extraction as module
    path = tmp_path / 'test.pdf'
    path.write_bytes(b'test')
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 20)
    monkeypatch.setattr(module.subprocess, 'run', timeout)
    assert '20 секунд' in extract_local(path).notice
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, b'', b'private parser error'))
    result = extract_local(path)
    assert result.status == 'error' and 'private' not in result.notice
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, b'not json', b''))
    assert extract_local(path).status == 'error'
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, ExtractionResult(status='empty').model_dump_json().encode(), b''))
    assert extract_local(path).status == 'empty'


def test_processing_busy_keeps_upload(local):
    import app.extraction as module
    client, path = local
    assert module._GATE.acquire(blocking=False)
    try:
        data = client.post('/uploads', files={'file': ('later.pdf', fixture_bytes('pdf'))}).json()
        assert data['status'] == 'unprocessed'
        assert client.post(data['url'] + '/extract').status_code == 409
        assert 'Не обработан' in client.get(data['url']).text
    finally:
        module._GATE.release()
    assert client.post(data['url'] + '/extract').json()['status'] == 'ready'


def test_missing_file_and_safe_path(local):
    client, path = local
    data = client.post('/uploads', files={'file': ('gone.pdf', b'corrupt')}).json()
    next((path / 'uploads').iterdir()).unlink()
    result = client.post(data['url'] + '/extract').json()
    assert result['status'] == 'error' and 'не найден' in result['message']
    engine = build_engine(path / 'qms.sqlite3')
    with Session(engine) as db:
        db.get(Document, data['id']).stored_name = '../qms.sqlite3'
        db.commit()
    engine.dispose()
    result = client.post(data['url'] + '/extract').json()
    assert result['status'] == 'error' and 'путь' in result['message']


def test_upgrade_v1_preserves_documents_and_history(tmp_path):
    # Restore the exact previous schema from an existing initialized database.
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        client.post('/chat', data={'message': 'История v1'})
        doc = client.post('/uploads', files={'file': ('old.docx', fixture_bytes('docx'))}).json()
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        db.execute('DROP TABLE document_extractions')
        db.execute('PRAGMA user_version=1')
        db.commit()
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        assert 'История v1' in client.get('/').text
        assert 'Не обработан' in client.get(doc['url']).text
        assert client.post(doc['url'] + '/extract').json()['status'] == 'ready'
    backups = list((tmp_path / 'backups').glob('qms-before-v2-*.sqlite3'))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 1
        assert backup.execute('SELECT original_name FROM documents').fetchone()[0] == 'old.docx'
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))):
        pass
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1


def test_blank_table_is_not_reported_as_text(tmp_path):
    path = tmp_path / 'empty-table.docx'
    document = WordDocument()
    document.add_table(rows=2, cols=2)
    document.save(path)
    assert extract(path).status == 'empty'


def test_spreadsheet_limits_and_external_links(tmp_path, monkeypatch):
    import socket
    import app.extract_worker as worker
    path = tmp_path / 'links.xlsx'
    workbook = Workbook()
    workbook.active['A1'] = 'Внешняя ссылка'
    workbook.active['A1'].hyperlink = 'https://example.invalid/do-not-fetch'
    workbook.save(path)
    workbook.close()
    def forbidden(*a, **k):
        raise AssertionError('Network access forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    assert extract(path).status == 'ready'
    path.write_bytes(fixture_bytes('xlsx'))
    monkeypatch.setattr(worker, 'MAX_ROWS', 1)
    assert extract(path).status == 'error'


def test_failed_v1_upgrade_rolls_back(tmp_path, monkeypatch):
    from app.models import Base
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        client.post('/chat', data={'message': 'Сохранить при ошибке миграции'})
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        db.execute('DROP TABLE document_extractions')
        db.execute('PRAGMA user_version=1')
        db.commit()
    original = Base.metadata.create_all
    def fail_after_ddl(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Synthetic migration failure')
    monkeypatch.setattr(Base.metadata, 'create_all', fail_after_ddl)
    with pytest.raises(RuntimeError, match='Synthetic migration failure'):
        with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))):
            pass
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='document_extractions'").fetchall()
        assert db.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0] == 2
    assert len(list((tmp_path / 'backups').glob('qms-before-v2-*.sqlite3'))) == 1
