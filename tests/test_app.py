from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.config import Settings
from legacy_app import create_app
from app.models import ChatMessage, Document


@pytest.fixture
def setup(tmp_path):
    settings = Settings(data_dir=tmp_path, max_upload_mb=1, _env_file=None)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, tmp_path


def test_pages(setup):
    client, _ = setup
    for url in ['/', *['/modules/' + m for m in ['knowledge', 'documents', 'incidents', 'risks', 'audits', 'reports', 'settings']]]:
        response = client.get(url)
        assert response.status_code == 200
        assert 'lang="ru"' in response.text
        assert 'QMS Assistant' in response.text
    assert client.get('/modules/unknown').status_code == 404
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/static/htmx.min.js').status_code == 200


def test_chat_persists_and_escapes(setup):
    client, path = setup
    response = client.post('/chat', data={'message': '<script>alert(1)</script>'})
    assert response.status_code == 200
    assert 'MockProvider' in response.text
    assert '<script>' not in response.text
    engine = create_engine('sqlite:///' + str(path / 'qms.sqlite3'))
    with Session(engine) as db:
        rows = db.scalars(select(ChatMessage).order_by(ChatMessage.id)).all()
        assert [m.role for m in rows] == ['user', 'assistant']
        assert rows[0].content == '<script>alert(1)</script>'
    engine.dispose()
    with TestClient(create_app(Settings(data_dir=path, _env_file=None))) as restarted:
        assert 'MockProvider' in restarted.get('/').text


@pytest.mark.parametrize('message,status', [('', 422), ('   ', 400), ('a' * 4001, 422)])
def test_chat_validation(setup, message, status):
    assert setup[0].post('/chat', data={'message': message}).status_code == status


@pytest.mark.parametrize('extension', ['docx', 'xlsx', 'pdf', 'PDF'])
def test_upload(setup, extension):
    client, path = setup
    # Synthetic bytes: this phase checks extension/size, not file authenticity.
    response = client.post('/uploads', files={'file': (f'../../test.{extension}', b'synthetic fixture')})
    assert response.status_code == 200
    files = list((path / 'uploads').iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b'synthetic fixture'
    assert files[0].name != f'test.{extension}'
    engine = create_engine('sqlite:///' + str(path / 'qms.sqlite3'))
    with Session(engine) as db:
        doc = db.scalar(select(Document))
        assert doc.original_name == f'test.{extension}'
        assert doc.size == 17
    engine.dispose()
    assert f'test.{extension}' in client.get('/modules/knowledge').text
    assert client.get('/uploads/' + files[0].name).status_code == 404


@pytest.mark.parametrize('name,body,status', [('bad.exe', b'x', 400), ('bad.pdf.exe', b'x', 400), ('empty.pdf', b'', 400), ('large.pdf', b'x' * (1024 * 1024 + 1), 413)])
def test_invalid_upload_cleanup(setup, name, body, status):
    client, path = setup
    assert client.post('/uploads', files={'file': (name, body)}).status_code == status
    assert list((path / 'uploads').iterdir()) == []


@pytest.mark.parametrize('provider', ['local', 'cloud'])
def test_real_providers_never_called(tmp_path, provider, monkeypatch):
    import socket
    def forbidden(*a, **kw):
        raise AssertionError('Внешний запрос запрещён')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    with TestClient(create_app(Settings(data_dir=tmp_path, ai_provider=provider, _env_file=None))) as client:
        assert client.post('/chat', data={'message': 'Тест'}).status_code == 503
        assert 'Тест</p>' not in client.get('/').text


def test_error_logging(setup, monkeypatch):
    client, path = setup
    def fail(*args):
        raise OSError('synthetic failure')
    from app.providers import MockProvider
    monkeypatch.setattr(MockProvider, 'reply', fail)
    with TestClient(client.app, raise_server_exceptions=False) as errors:
        response = errors.post('/chat', data={'message': 'sensitive-test-text'})
    assert response.status_code == 500
    log = (path / 'logs' / 'app.log').read_text(encoding='utf-8')
    assert 'OSError' in log
    assert 'sensitive-test-text' not in log


def test_navigation_and_html_not_found(setup):
    client, _ = setup
    for module in ['knowledge', 'documents', 'incidents', 'risks', 'audits', 'reports', 'settings']:
        html = client.get('/modules/' + module).text
        assert html.count('aria-current="page"') == 1
        assert f'href="/modules/{module}" class="active" aria-current="page"' in html
        assert 'aria-controls="sidebar-nav"' in html
    response = client.get('/missing', headers={'accept': 'text/html'})
    assert response.status_code == 404
    assert 'Вернуться на главную' in response.text
    assert client.get('/missing').headers['content-type'].startswith('application/json')


def test_settings_show_configured_limit_and_provider(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, max_upload_mb=3, ai_provider='local', _env_file=None))) as client:
        settings = client.get('/modules/settings').text
        assert '<dd>local</dd>' in settings
        assert '<dd>3 МиБ</dd>' in settings
        knowledge = client.get('/modules/knowledge').text
        assert 'data-max-bytes="3145728"' in knowledge
        assert 'Документов пока нет' in knowledge
