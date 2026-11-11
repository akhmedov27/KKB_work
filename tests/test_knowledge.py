from contextlib import closing
from datetime import date
from io import BytesIO
import json
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import pymupdf
from openpyxl import Workbook
from docx import Document as WordDocument

from app.config import Settings
from app.database import SCHEMA_VERSION, build_engine
from legacy_app import create_app
from app.models import Base, Document, DocumentExtraction, DocumentMetadata
from app.search import excerpt, literal_position, text_parts


@pytest.fixture
def local(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        yield client, tmp_path


def seed(path, name='fixture.pdf', text='Текст для внутреннего аудита', metadata=None, extraction_status='ready', sources=None):
    engine = build_engine(path / 'qms.sqlite3')
    with Session(engine) as db:
        document = Document(original_name=name, stored_name=name, size=1)
        db.add(document)
        db.flush()
        document_id = document.id
        if extraction_status:
            db.add(DocumentExtraction(document_id=document_id, status=extraction_status, text=text,
                                      source_map_json=json.dumps(sources or [])))
        if metadata:
            db.add(DocumentMetadata(document_id=document_id, **metadata))
        db.commit()
    engine.dispose()
    return document_id


def result_ids(html):
    return [int(i) for i in re.findall(r'class="knowledge-result" data-document-id="(\d+)"', html)]


def test_russian_search_title_number_content_and_literal_symbols(local):
    client, path = local
    by_name = seed(path, name='ПРОГРАММА_100%.pdf', text='Другой текст')
    by_body = seed(path, name='body.pdf', text='ВНУТРЕННИЙ АУДИТ; ставка 25% и знак _')
    by_meta = seed(path, name='meta.pdf', metadata={'title': 'Программа проверки', 'registration_number': 'СТУ-005'})
    assert result_ids(client.get('/modules/knowledge', params={'q': 'программа'}).text) == [by_meta, by_name]
    assert result_ids(client.get('/modules/knowledge', params={'q': 'внутренний аудит'}).text) == [by_body]
    assert result_ids(client.get('/modules/knowledge', params={'q': 'сту-005'}).text) == [by_meta]
    assert result_ids(client.get('/modules/knowledge', params={'q': '100%'}).text) == [by_name]
    assert result_ids(client.get('/modules/knowledge', params={'q': '25%'}).text) == [by_body]
    assert result_ids(client.get('/modules/knowledge', params={'q': "' OR 1=1 --"}).text) == []
    assert 'Ничего не найдено' in client.get('/modules/knowledge', params={'q': 'несуществующая фраза'}).text
    assert len(result_ids(client.get('/modules/knowledge', params={'q': '   '}).text)) == 3


def test_filters_and_status_not_inferred(local):
    client, path = local
    unknown = seed(path, name='unknown.pdf')
    active = seed(path, name='active.pdf', metadata={'lifecycle_status': 'active', 'category': 'instruction', 'department': 'Отдел качества', 'review_on': date(2000, 1, 1)})
    archived = seed(path, name='archive.pdf', metadata={'lifecycle_status': 'archived', 'category': 'instruction', 'department': 'Архив', 'review_on': date(2000, 1, 1)})
    cancelled = seed(path, name='cancelled.pdf', metadata={'lifecycle_status': 'cancelled', 'category': 'report'})
    assert result_ids(client.get('/modules/knowledge', params={'status': 'unspecified'}).text) == [unknown]
    assert result_ids(client.get('/modules/knowledge', params={'status': 'active', 'category': 'instruction', 'department': 'КАЧЕСТВА'}).text) == [active]
    assert result_ids(client.get('/modules/knowledge', params={'status': 'archived'}).text) == [archived]
    assert result_ids(client.get('/modules/knowledge', params={'status': 'cancelled'}).text) == [cancelled]
    assert 'Срок пересмотра истёк' in client.get('/modules/knowledge', params={'status': 'active'}).text
    assert 'Срок пересмотра истёк' not in client.get('/modules/knowledge', params={'status': 'archived'}).text
    assert result_ids(client.get('/modules/knowledge', params={'category': 'report'}).text) == [cancelled]


def test_metadata_save_dates_escape_and_persistence(local):
    client, path = local
    document_id = seed(path)
    fields = {'title': '  <script>Название</script> ', 'registration_number': 'ККБ-5', 'version': '2.1',
              'department': 'Отдел СМК', 'category': 'stu', 'lifecycle_status': 'active',
              'approved_on': '2026-01-20', 'review_on': '2099-02-01'}
    assert client.post(f'/documents/{document_id}/metadata', data=fields).status_code == 200
    html = client.get(f'/documents/{document_id}').text
    assert '&lt;script&gt;Название&lt;/script&gt;' in html and '<script>Название</script>' not in html
    assert 'ККБ-5' in html and '2099-02-01' in html
    with TestClient(create_app(Settings(data_dir=path, _env_file=None))) as restarted:
        assert 'ККБ-5' in restarted.get(f'/documents/{document_id}').text
    engine = build_engine(path / 'qms.sqlite3')
    with Session(engine) as db:
        metadata = db.get(DocumentMetadata, document_id)
        assert metadata.title == '<script>Название</script>'
        assert metadata.approved_on == date(2026, 1, 20)
    engine.dispose()
    fields.update(approved_on='', review_on='')
    assert client.post(f'/documents/{document_id}/metadata', data=fields).status_code == 200
    log = (path / 'logs' / 'app.log').read_text(encoding='utf-8')
    assert 'ККБ-5' not in log and 'Название' not in log


@pytest.mark.parametrize('fields', [{'title': 'x' * 256}, {'approved_on': 'not-a-date'}, {'review_on': '2026-02-30'}, {'lifecycle_status': 'invented'}, {'category': 'invented'}, {'department': 'x' * 151}])
def test_metadata_invalid_values_do_not_overwrite(local, fields):
    client, path = local
    document_id = seed(path, metadata={'title': 'Сохранённое название'})
    assert client.post(f'/documents/{document_id}/metadata', data=fields).status_code == 422
    assert 'Сохранённое название' in client.get(f'/documents/{document_id}').text
    assert client.post('/documents/9999/metadata', data={'title': 'Нет'}).status_code == 404


@pytest.mark.parametrize('params', [{'q': 'a' * 201}, {'page': 0}, {'status': 'bad'}, {'category': 'bad'}])
def test_search_validation(local, params):
    assert local[0].get('/modules/knowledge', params=params).status_code == 422


def test_pagination_preserves_filters_and_all_results(local):
    client, path = local
    ids = [seed(path, name=f'{i}-ПЛАН%.pdf', metadata={'lifecycle_status': 'active'}) for i in range(23)]
    params = {'q': 'план%', 'status': 'active', 'category': 'all', 'page': 1}
    first = client.get('/modules/knowledge', params=params).text
    next_url = re.search(r'href="([^"]+)">Следующая страница', first)[1].replace('&amp;', '&')
    assert 'status=active' in next_url and '%25' in next_url
    second = client.get(next_url).text
    assert len(result_ids(first)) == 20 and len(result_ids(second)) == 3
    assert set(result_ids(first) + result_ids(second)) == set(ids)
    assert not set(result_ids(first)) & set(result_ids(second))


def test_failed_extraction_not_searched_and_snippets_escape(local):
    client, path = local
    seed(path, name='failed.pdf', text='ONLY_FAILED_CONTENT', extraction_status='error')
    good = seed(path, name='safe.pdf', text='Начало <img src=x onerror=alert(1)> КАЧЕСТВО конец')
    assert result_ids(client.get('/modules/knowledge', params={'q': 'ONLY_FAILED_CONTENT'}).text) == []
    html = client.get('/modules/knowledge', params={'q': 'качество'}).text
    assert result_ids(html) == [good]
    assert '&lt;img' in html and '<img src=x' not in html
    assert 'расположение не сохранено' in html
    assert f'/documents/{good}#document-text' in html


@pytest.mark.parametrize('extension,needle,location', [('pdf', 'second source', 'Страница 2'), ('xlsx', 'значение СМК', 'Лист: Тестовый лист'), ('docx', 'текст СМК', 'Основной текст DOCX')])
def test_source_citations_from_real_extraction(local, extension, needle, location):
    client, _ = local
    buffer = BytesIO()
    if extension == 'pdf':
        with pymupdf.open() as document:
            document.new_page().insert_text((72, 72), 'First source')
            document.new_page().insert_text((72, 72), 'second source [Page 999 fake]')
            buffer.write(document.tobytes())
    elif extension == 'xlsx':
        workbook = Workbook()
        workbook.active.title = 'Тестовый лист'
        workbook.active['A1'] = 'Значение СМК'
        workbook.save(buffer)
        workbook.close()
    else:
        document = WordDocument()
        document.add_paragraph('Текст СМК')
        document.save(buffer)
    data = client.post('/uploads', files={'file': ('source.' + extension, buffer.getvalue())}).json()
    assert data['status'] == 'ready'
    html = client.get('/modules/knowledge', params={'q': needle}).text
    assert f'Источник: {location}' in html
    anchor = re.search(r'class="source-link" href="[^"]+#([^"]+)"', html)[1]
    assert f'id="{anchor}"' in client.get(data['url']).text


def test_excerpt_positions_and_no_guessed_sources():
    text = 'Straße\nВТОРАЯ СТРАНИЦА [Страница 999]'
    assert literal_position(text, 'вторая') == text.index('ВТОРАЯ')
    result = json.loads(excerpt(text, 'вторая', '[]'))
    assert result['location'] is None
    assert 'ВТОРАЯ' in result['text']
    parts = text_parts(text, json.dumps([{'start': 7, 'end': len(text), 'label': 'Страница 2'}]))
    assert ''.join(part['text'] for part in parts) == text
    assert json.loads(excerpt(text, 'вторая', '[invalid json'))['location'] is None


def previous_v2(path):
    with TestClient(create_app(Settings(data_dir=path, _env_file=None))) as client:
        client.post('/chat', data={'message': 'Переписка до QMS-005'})
    document_id = seed(path, text='Старый извлечённый текст', metadata={'title': 'Will be removed for v2 fixture'})
    with closing(sqlite3.connect(path / 'qms.sqlite3')) as db:
        db.execute('DROP TABLE document_metadata')
        db.execute('ALTER TABLE document_extractions DROP COLUMN source_map_json')
        db.execute('PRAGMA user_version=2')
        db.commit()
    (path / 'uploads' / 'fixture.pdf').write_bytes(b'preserved original')
    return document_id


def test_v2_upgrade_preserves_text_history_and_originals(local):
    # A separate path avoids migrating a database with a live client.
    _, parent = local
    path = parent / 'old-v2'
    path.mkdir()
    document_id = previous_v2(path)
    with TestClient(create_app(Settings(data_dir=path, _env_file=None))) as client:
        assert 'Переписка до QMS-005' in client.get('/').text
        html = client.get('/modules/knowledge', params={'q': 'старый извлечённый'}).text
        assert result_ids(html) == [document_id]
        assert 'расположение не сохранено' in html
        assert 'Не указан' in html
        assert client.post(f'/documents/{document_id}/metadata', data={'title': 'Реквизиты после обновления'}).status_code == 200
    assert (path / 'uploads' / 'fixture.pdf').read_bytes() == b'preserved original'
    backups = list((path / 'backups').glob(f'qms-before-v{SCHEMA_VERSION}-*.sqlite3'))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 2
        assert backup.execute('SELECT text FROM document_extractions').fetchone()[0] == 'Старый извлечённый текст'
    with TestClient(create_app(Settings(data_dir=path, _env_file=None))):
        pass
    assert len(list((path / 'backups').glob('*.sqlite3'))) == 1


def test_v2_upgrade_failure_rolls_back(local, monkeypatch):
    _, parent = local
    path = parent / 'failed-v2'
    path.mkdir()
    previous_v2(path)
    original = Base.metadata.create_all
    def fail_after_ddl(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Synthetic v3 migration failure')
    monkeypatch.setattr(Base.metadata, 'create_all', fail_after_ddl)
    with pytest.raises(RuntimeError, match='Synthetic v3 migration failure'):
        with TestClient(create_app(Settings(data_dir=path, _env_file=None))):
            pass
    with closing(sqlite3.connect(path / 'qms.sqlite3')) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert 'source_map_json' not in {row[1] for row in db.execute('PRAGMA table_info(document_extractions)')}
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='document_metadata'").fetchall()
        assert db.execute('SELECT text FROM document_extractions').fetchone()[0] == 'Старый извлечённый текст'


def test_reprocessing_refreshes_search_and_keeps_metadata(local):
    client, path = local
    buffer = BytesIO()
    document = WordDocument()
    document.add_paragraph('Старая уникальная фраза')
    document.save(buffer)
    data = client.post('/uploads', files={'file': ('refresh.docx', buffer.getvalue())}).json()
    assert client.post(data['url'] + '/metadata', data={'title': 'Постоянные реквизиты', 'lifecycle_status': 'active'}).status_code == 200
    assert result_ids(client.get('/modules/knowledge', params={'q': 'старая уникальная'}).text) == [data['id']]
    engine = build_engine(path / 'qms.sqlite3')
    with Session(engine) as db:
        stored = db.get(Document, data['id']).stored_name
    engine.dispose()
    new_document = WordDocument()
    new_document.add_paragraph('Новая уникальная фраза')
    new_document.save(path / 'uploads' / stored)
    assert client.post(data['url'] + '/extract').json()['status'] == 'ready'
    assert result_ids(client.get('/modules/knowledge', params={'q': 'старая уникальная'}).text) == []
    assert result_ids(client.get('/modules/knowledge', params={'q': 'новая уникальная', 'status': 'active'}).text) == [data['id']]
    assert 'Постоянные реквизиты' in client.get(data['url']).text
