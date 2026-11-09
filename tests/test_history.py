import re
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.database import build_engine
from app.main import create_app
from app.models import ChatMessage, Conversation


def make_app(path):
    return create_app(Settings(data_dir=path, _env_file=None))


def create_dialog(client, title):
    response = client.post('/conversations', data={'title': title}, follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers['location'].split('=')[1])


def test_separate_conversations_and_restart(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        first = create_dialog(client, '<script>Первый</script>')
        second = create_dialog(client, 'Второй')
        assert client.post('/chat', data={'conversation_id': first, 'message': 'ONLY_FIRST'}).status_code == 200
        assert client.post('/chat', data={'conversation_id': second, 'message': 'ONLY_SECOND'}).status_code == 200
        a, b = client.get(f'/?conversation_id={first}').text, client.get(f'/?conversation_id={second}').text
        assert 'ONLY_FIRST' in a and 'ONLY_SECOND' not in a
        assert 'ONLY_SECOND' in b and 'ONLY_FIRST' not in b
        assert '<script>Первый</script>' not in a
        assert '&lt;script&gt;Первый&lt;/script&gt;' in a
    with TestClient(make_app(tmp_path)) as restarted:
        assert 'ONLY_FIRST' in restarted.get(f'/?conversation_id={first}').text
        assert 'ONLY_SECOND' in restarted.get(f'/?conversation_id={second}').text


@pytest.mark.parametrize('data,status', [({'title': '   '}, 400), ({'title': 'x' * 121}, 422)])
def test_title_validation(tmp_path, data, status):
    with TestClient(make_app(tmp_path)) as client:
        assert client.post('/conversations', data=data).status_code == status


def test_missing_and_invalid_conversation(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        assert client.get('/?conversation_id=9999').status_code == 404
        assert client.post('/chat', data={'conversation_id': 9999, 'message': 'not saved'}).status_code == 404
        assert client.post('/chat', data={'conversation_id': -1, 'message': 'not saved'}).status_code == 422
        assert client.get('/?before_id=-1').status_code == 422
        assert client.get('/?conversation_page=0').status_code == 422


def test_message_pagination_no_duplicates_or_leaks(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        selected = create_dialog(client, 'Длинная история')
        other = create_dialog(client, 'Другой')
        engine = build_engine(tmp_path / 'qms.sqlite3')
        with Session(engine) as db:
            db.add_all([ChatMessage(conversation_id=selected, role='user', content=f'TEST-{i}') for i in range(123)])
            db.add(ChatMessage(conversation_id=other, role='user', content='OTHER_SECRET'))
            db.commit()
        engine.dispose()
        ids = []
        url = f'/?conversation_id={selected}'
        sizes = []
        while True:
            html = client.get(url).text
            assert 'OTHER_SECRET' not in html
            batch = [int(i) for i in re.findall(r'data-message-id="(\d+)"', html)]
            sizes.append(len(batch))
            assert batch == sorted(batch)
            ids.extend(batch)
            link = re.search(r'id="older-messages" href="([^"]+)"', html)
            if not link:
                break
            url = link[1].replace('&amp;', '&')
            assert 'before_id=' in url
        assert sizes == [50, 50, 23]
        assert len(ids) == len(set(ids)) == 123


def test_conversation_pagination(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        for i in range(22):
            create_dialog(client, f'Диалог {i}')
        first = client.get('/').text
        second = client.get('/?conversation_page=2').text
        assert 'Ещё диалоги' in first
        assert 'Ещё диалоги' not in second
        assert len(re.findall(r'<a href="/\?conversation_id=\d+"', first)) >= 20
        assert 'Диалог 0' in second


def legacy_database(path, role='user'):
    with closing(sqlite3.connect(path / 'qms.sqlite3')) as db:
        db.execute('CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, role VARCHAR(20) NOT NULL, content TEXT NOT NULL, created_at DATETIME NOT NULL)')
        db.execute('INSERT INTO chat_messages VALUES (7, ?, ?, ?)', (role, 'Старая переписка', '2026-11-01 10:00:00.000000'))
        db.execute('CREATE TABLE documents (id INTEGER PRIMARY KEY, original_name VARCHAR(255) NOT NULL, stored_name VARCHAR(50) UNIQUE NOT NULL, size INTEGER NOT NULL, created_at DATETIME NOT NULL)')
        db.execute("INSERT INTO documents VALUES (1, 'old.pdf', 'abc.pdf', 3, '2026-11-01 10:00:00')")
        db.commit()
    (path / 'uploads').mkdir()
    (path / 'uploads' / 'abc.pdf').write_bytes(b'old')


def test_upgrade_preserves_history_documents_and_backup(tmp_path):
    legacy_database(tmp_path)
    with TestClient(make_app(tmp_path)) as client:
        html = client.get('/').text
        assert 'История до QMS-003' in html and 'Старая переписка' in html
        assert 'data-message-id="7"' in html
        assert '01.11.2026 10:00' in html
        assert 'old.pdf' in client.get('/modules/knowledge').text
        assert client.post('/chat', data={'message': 'Новый запрос'}).status_code == 200
    backups = list((tmp_path / 'backups').glob('*.sqlite3'))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert backup.execute('SELECT content FROM chat_messages').fetchone()[0] == 'Старая переписка'
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 0
    assert (tmp_path / 'uploads' / 'abc.pdf').read_bytes() == b'old'
    with TestClient(make_app(tmp_path)) as client:
        assert 'Новый запрос' in client.get('/').text
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0] == 3


def test_failed_upgrade_rolls_back(tmp_path):
    legacy_database(tmp_path, role='invalid')
    with pytest.raises(IntegrityError):
        with TestClient(make_app(tmp_path)):
            pass
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
        assert db.execute('SELECT id, role FROM chat_messages').fetchall() == [(7, 'invalid')]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='conversations'").fetchall() == []
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1


def test_newer_schema_refused(tmp_path):
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        db.execute('PRAGMA user_version=999')
    with pytest.raises(RuntimeError, match='более новой'):
        with TestClient(make_app(tmp_path)):
            pass
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 999


def test_failed_exchange_is_atomic(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        engine = build_engine(tmp_path / 'qms.sqlite3')
        with Session(engine) as db:
            original = db.scalar(select(Conversation.updated_at))
        def fail_on_answer(mapper, connection, target):
            if target.role == 'assistant':
                raise RuntimeError('Synthetic database failure')
        event.listen(ChatMessage, 'before_insert', fail_on_answer)
        try:
            assert client.post('/chat', data={'message': 'ATOMIC'}).status_code == 500
        finally:
            event.remove(ChatMessage, 'before_insert', fail_on_answer)
        with Session(engine) as db:
            assert db.scalars(select(ChatMessage)).all() == []
            assert db.scalar(select(Conversation.updated_at)) == original
        engine.dispose()


def test_foreign_key_prevents_orphans_and_deletion(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        client.post('/chat', data={'message': 'Сохранить'})
        engine = build_engine(tmp_path / 'qms.sqlite3')
        with engine.connect() as connection:
            assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql('DELETE FROM conversations')
            connection.rollback()
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql("INSERT INTO chat_messages(conversation_id, role, content, created_at) VALUES (9999, 'user', 'x', '2026-01-01')")
            connection.rollback()
        engine.dispose()
