from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.ai_service import AIService
from app.config import Settings
from app.database import SCHEMA_VERSION, build_engine
from legacy_app import create_app
from app.models import ChatMessage, Conversation, Document, DocumentExtraction
from app.providers import CloudProvider, ProviderUnavailable


def cloud_settings(tmp_path, **overrides):
    return Settings(**{'data_dir': tmp_path, 'ai_provider': 'cloud', 'cloud_enabled': True,
                       'cloud_api_key': 'SYNTHETIC_KEY_NOT_REAL', '_env_file': None, **overrides})


def install_transport(monkeypatch, handler):
    import app.providers as providers
    original = httpx.Client
    monkeypatch.setattr(providers.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def reply_response(text='Синтетический ответ ИИ', finish_reason='stop'):
    return httpx.Response(200, json={'choices': [{'message': {'content': text}, 'finish_reason': finish_reason}]})


@pytest.mark.parametrize('changes', [{'cloud_enabled': False}, {'cloud_api_key': ''}, {'cloud_model': ''}, {'cloud_endpoint': 'https://evil.invalid/chat/completions'}, {'cloud_endpoint': 'http://api.deepseek.com/chat/completions'}])
def test_disabled_or_unconfigured_never_connects(tmp_path, monkeypatch, changes):
    def forbidden(request):
        raise AssertionError('Unexpected external call')
    install_transport(monkeypatch, forbidden)
    with pytest.raises(ProviderUnavailable):
        AIService(cloud_settings(tmp_path, **changes)).reply('Тест', cloud_consent=True)


def test_each_request_requires_consent_and_sends_only_explicit_text(tmp_path, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url == 'https://api.deepseek.com/chat/completions'
        assert request.headers['authorization'] == 'Bearer SYNTHETIC_KEY_NOT_REAL'
        payload = json.loads(request.content)
        assert payload['model'] == 'deepseek-chat'
        assert payload['stream'] is False
        assert payload['max_tokens'] == 512
        assert [message['role'] for message in payload['messages']] == ['system', 'user']
        assert 'MANUAL_FRAGMENT' in payload['messages'][1]['content']
        assert 'OLD_PRIVATE_HISTORY' not in request.content.decode()
        assert 'PRIVATE_FILE_CONTENT' not in request.content.decode()
        return reply_response('<script>synthetic response</script>')
    install_transport(monkeypatch, handle)
    app = create_app(cloud_settings(tmp_path))
    with TestClient(app) as client:
        engine = build_engine(tmp_path / 'qms.sqlite3')
        with Session(engine) as db:
            conversation_id = db.scalar(select(Conversation.id))
            db.add(ChatMessage(conversation_id=conversation_id, role='user', content='OLD_PRIVATE_HISTORY'))
            document = Document(original_name='private-test.pdf', stored_name='private-test.pdf', size=1)
            db.add(document)
            db.flush()
            db.add(DocumentExtraction(document_id=document.id, status='ready', text='PRIVATE_FILE_CONTENT'))
            db.commit()
        engine.dispose()
        # Browsing/health/settings must never probe the remote endpoint.
        assert client.get('/').status_code == 200
        settings_html = client.get('/modules/settings').text
        assert 'SYNTHETIC_KEY_NOT_REAL' not in settings_html
        assert client.get('/health').status_code == 200
        assert calls == []
        assert client.post('/chat', data={'message': 'Denied'}).status_code == 403
        response = client.post('/chat', data={'message': 'CURRENT_QUESTION', 'fragment': 'MANUAL_FRAGMENT', 'cloud_consent': 'true'})
        assert response.status_code == 200 and 'DeepSeek' in response.text
        assert '<script>synthetic response</script>' not in response.text
        assert '&lt;script&gt;synthetic response&lt;/script&gt;' in response.text
        assert len(calls) == 1
        assert client.post('/chat', data={'message': 'Must re-consent'}).status_code == 403
    engine = build_engine(tmp_path / 'qms.sqlite3')
    with Session(engine) as db:
        messages = db.scalars(select(ChatMessage).order_by(ChatMessage.id)).all()
        assert len(messages) == 3
        assert messages[2].provider == 'cloud' and messages[2].model == 'deepseek-chat'
        assert messages[0].content == 'OLD_PRIVATE_HISTORY'
        assert 'MANUAL_FRAGMENT' in messages[1].content
    engine.dispose()
    log = (tmp_path / 'logs' / 'app.log').read_text(encoding='utf-8')
    assert 'SYNTHETIC_KEY_NOT_REAL' not in log and 'CURRENT_QUESTION' not in log


@pytest.mark.parametrize('upstream,status', [(401, 502), (402, 502), (403, 502), (429, 429), (500, 502), (302, 502)])
def test_http_errors_no_retry_no_history_no_raw_error(tmp_path, monkeypatch, upstream, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(upstream, headers={'location': 'https://evil.invalid'}, text='PRIVATE_RAW_RESPONSE')
    install_transport(monkeypatch, handle)
    with TestClient(create_app(cloud_settings(tmp_path))) as client:
        response = client.post('/chat', data={'message': 'Тест', 'cloud_consent': 'true'})
        assert response.status_code == status
        assert 'PRIVATE_RAW_RESPONSE' not in response.text
        assert len(calls) == 1
        assert 'data-message-id' not in client.get('/').text


@pytest.mark.parametrize('body', [{'choices': []}, {'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}, {'choices': [{'message': {'content': 'a' * 20001}, 'finish_reason': 'stop'}]}, {'choices': [{'message': {'content': 'text', 'tool_calls': [{'x': 'y'}]}, 'finish_reason': 'tool_calls'}]}])
def test_invalid_provider_payload(tmp_path, monkeypatch, body):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ProviderUnavailable) as error:
        AIService(cloud_settings(tmp_path)).reply('Тест', cloud_consent=True)
    assert error.value.status_code == 502


def test_timeout_and_response_size_limits(tmp_path, monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout('PRIVATE_TIMEOUT', request=request)
    install_transport(monkeypatch, timeout)
    with pytest.raises(ProviderUnavailable) as error:
        AIService(cloud_settings(tmp_path)).reply('Тест', cloud_consent=True)
    assert error.value.status_code == 504 and 'PRIVATE_TIMEOUT' not in str(error.value)
    # Restore Client before installing a second test transport.
    monkeypatch.undo()
    install_transport(monkeypatch, lambda request: httpx.Response(200, content=b'x' * (256 * 1024 + 1)))
    with pytest.raises(ProviderUnavailable, match='размер'):
        AIService(cloud_settings(tmp_path)).reply('Тест', cloud_consent=True)


def test_truncated_output_is_marked(tmp_path, monkeypatch):
    install_transport(monkeypatch, lambda request: reply_response('Текст', 'length'))
    reply = AIService(cloud_settings(tmp_path)).reply('Тест', cloud_consent=True)
    assert 'Ответ сокращён' in reply.text


def test_foreign_origin_rejected(tmp_path, monkeypatch):
    install_transport(monkeypatch, lambda request: pytest.fail('Must not send'))
    with TestClient(create_app(cloud_settings(tmp_path))) as client:
        response = client.post('/chat', data={'message': 'Тест', 'cloud_consent': 'true'}, headers={'origin': 'https://evil.invalid'})
        assert response.status_code == 403


def test_direct_adapter_cannot_bypass_consent(tmp_path, monkeypatch):
    install_transport(monkeypatch, lambda request: pytest.fail('Must not send'))
    with pytest.raises(ProviderUnavailable):
        CloudProvider(cloud_settings(tmp_path)).reply('Тест')
    with pytest.raises(ProviderUnavailable):
        CloudProvider(Settings(data_dir=tmp_path, _env_file=None)).reply('Тест', allow_cloud=True)


@pytest.mark.parametrize('endpoint', ['http://192.168.1.2:1234/v1/chat/completions', 'https://public.example/v1/chat/completions', 'http://user:secret@127.0.0.1/v1/chat/completions', 'http://[broken', 'http://127.0.0.1:bad/v1/chat/completions'])
def test_local_endpoints_restricted_to_loopback(tmp_path, endpoint):
    settings = Settings(data_dir=tmp_path, ai_provider='local', local_endpoint=endpoint, local_model='already-installed', _env_file=None)
    with pytest.raises(ProviderUnavailable):
        AIService(settings).reply('Тест')


def test_local_client_over_real_http_protocol_server(tmp_path):
    """Protocol emulator, NOT a real language model or claim of model quality."""
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            body = json.dumps({'choices': [{'message': {'content': 'Ответ тестового HTTP-сервера'}, 'finish_reason': 'stop'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(data_dir=tmp_path, ai_provider='local', local_model='protocol-test',
                            local_endpoint=f'http://127.0.0.1:{server.server_port}/v1/chat/completions', _env_file=None)
        reply = AIService(settings).reply('Синтетический запрос')
        assert reply.text == 'Ответ тестового HTTP-сервера'
        assert reply.provider == 'local' and received[0]['messages'][1]['content'] == 'Синтетический запрос'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_ai_busy_gate(tmp_path):
    import app.ai_service as service
    settings = Settings(data_dir=tmp_path, _env_file=None)
    assert service._GATE.acquire(blocking=False)
    try:
        with pytest.raises(ProviderUnavailable) as error:
            AIService(settings).reply('Тест')
        assert error.value.status_code == 409
    finally:
        service._GATE.release()


def test_upgrade_v3_preserves_mock_identity(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        assert client.post('/chat', data={'message': 'Прежний тестовый чат'}).status_code == 200
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        db.execute('ALTER TABLE chat_messages DROP COLUMN provider')
        db.execute('ALTER TABLE chat_messages DROP COLUMN model')
        db.execute('PRAGMA user_version=3')
        db.commit()
    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as client:
        html = client.get('/').text
        assert 'Прежний тестовый чат' in html and 'Тестовый помощник' in html
    backups = list((tmp_path / 'backups').glob(f'qms-before-v{SCHEMA_VERSION}-*.sqlite3'))
    assert len(backups) == 1
    with closing(sqlite3.connect(tmp_path / 'qms.sqlite3')) as db:
        assert db.execute('SELECT DISTINCT provider, model FROM chat_messages').fetchall() == [('mock', '')]
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION


def groq_settings(tmp_path, **overrides):
    return cloud_settings(tmp_path, **{'cloud_service': 'groq',
                                     'cloud_endpoint': 'https://api.groq.com/openai/v1/chat/completions',
                                     'cloud_model': 'llama-3.1-8b-instant', **overrides})


def test_groq_request_consent_and_persistent_identity(tmp_path, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url == 'https://api.groq.com/openai/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer SYNTHETIC_KEY_NOT_REAL'
        body = json.loads(request.content)
        assert body['model'] == 'llama-3.1-8b-instant'
        assert body['max_completion_tokens'] == 512 and 'max_tokens' not in body
        assert len(body['messages']) == 2
        assert 'Фрагмент для Groq' in body['messages'][1]['content']
        return reply_response('Синтетический ответ Groq')
    install_transport(monkeypatch, handle)
    with TestClient(create_app(groq_settings(tmp_path))) as client:
        home = client.get('/').text
        assert 'фрагмент в Groq (api.groq.com)' in home
        assert 'фрагмент в DeepSeek' not in home
        assert 'Ключ Groq' in client.get('/modules/settings').text
        assert calls == []
        response = client.post('/chat', data={'message': 'Без разрешения'})
        assert response.status_code == 403 and 'Groq' in response.text and calls == []
        response = client.post('/chat', data={'message': 'Тест', 'fragment': 'Фрагмент для Groq', 'cloud_consent': 'true'})
        assert response.status_code == 200 and 'Groq · llama-3.1-8b-instant' in response.text
        assert len(calls) == 1
    # Changing current configuration must not relabel historical responses.
    with TestClient(create_app(cloud_settings(tmp_path))) as client:
        html = client.get('/').text
        assert 'Groq · llama-3.1-8b-instant' in html
        assert 'DeepSeek · llama-3.1-8b-instant' not in html
    engine = build_engine(tmp_path / 'qms.sqlite3')
    with Session(engine) as db:
        rows = db.scalars(select(ChatMessage).order_by(ChatMessage.id)).all()
        assert rows[1].provider == 'groq'
    engine.dispose()


@pytest.mark.parametrize('endpoint', ['https://api.deepseek.com/chat/completions', 'https://api.groq.com.evil.invalid/openai/v1/chat/completions', 'http://api.groq.com/openai/v1/chat/completions', 'https://api.groq.com/openai/v1/chat/completions?key=private'])
def test_groq_service_endpoint_pair_prevents_key_misdirection(tmp_path, monkeypatch, endpoint):
    install_transport(monkeypatch, lambda request: pytest.fail('Key must not leave application'))
    with pytest.raises(ProviderUnavailable):
        AIService(groq_settings(tmp_path, cloud_endpoint=endpoint)).reply('Тест', cloud_consent=True)


@pytest.mark.parametrize('changes', [{'cloud_enabled': False}, {'cloud_api_key': ''}, {'cloud_model': ''}])
def test_groq_disabled_missing_key_or_model_no_request(tmp_path, monkeypatch, changes):
    install_transport(monkeypatch, lambda request: pytest.fail('Must not send'))
    with pytest.raises(ProviderUnavailable):
        AIService(groq_settings(tmp_path, **changes)).reply('Тест', cloud_consent=True)


def test_existing_deepseek_configuration_remains_valid(tmp_path):
    from app.providers import check_configuration
    settings = cloud_settings(tmp_path)
    assert settings.cloud_service == 'deepseek'
    check_configuration(settings)


def test_groq_rate_limit_has_no_fallback_or_retries(tmp_path, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(429, text='PRIVATE_RESPONSE')
    install_transport(monkeypatch, handle)
    with TestClient(create_app(groq_settings(tmp_path))) as client:
        response = client.post('/chat', data={'message': 'Тест', 'cloud_consent': 'true'})
        assert response.status_code == 429 and len(calls) == 1
        assert 'PRIVATE_RESPONSE' not in response.text
        assert 'data-message-id=' not in client.get('/').text
