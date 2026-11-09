"""Controlled entry point: no file, metadata or history retrieval is performed."""
from dataclasses import dataclass
import threading

from app.providers import check_configuration, get_provider, ProviderUnavailable, cloud_label

_GATE = threading.BoundedSemaphore(1)


@dataclass(frozen=True)
class AIReply:
    text: str
    user_text: str
    provider: str
    model: str


class AIService:
    def __init__(self, settings):
        self.settings = settings

    def reply(self, message, fragment='', cloud_consent=False):
        if not message.strip() or len(message) > 4000 or len(fragment) > 6000:
            raise ProviderUnavailable('Проверьте длину запроса и явно добавленного фрагмента.', 422)
        check_configuration(self.settings)
        if self.settings.ai_provider == 'cloud' and not cloud_consent:
            raise ProviderUnavailable(f'Подтвердите отправку текущего запроса и введённого фрагмента в {cloud_label(self.settings)}.', 403)
        message, fragment = message.strip(), fragment.strip()
        user_text = message + ('\n\nЯвно добавленный пользователем фрагмент:\n' + fragment if fragment else '')
        if not _GATE.acquire(blocking=False):
            raise ProviderUnavailable('Другой запрос к ИИ ещё выполняется. Дождитесь завершения.', 409)
        try:
            provider = get_provider(self.settings.ai_provider, self.settings)
            text = provider.reply(user_text, allow_cloud=True) if self.settings.ai_provider == 'cloud' else provider.reply(user_text)
            model = self.settings.cloud_model if self.settings.ai_provider == 'cloud' else self.settings.local_model if self.settings.ai_provider == 'local' else ''
            provider_id = 'groq' if self.settings.ai_provider == 'cloud' and self.settings.cloud_service == 'groq' else self.settings.ai_provider
            return AIReply(text=text, user_text=user_text, provider=provider_id, model=model)
        finally:
            _GATE.release()

    def status(self):
        try:
            check_configuration(self.settings)
            return 'Тестовый провайдер готов' if self.settings.ai_provider == 'mock' else 'Параметры заданы. Доступность сервиса проверяется при отправке запроса.'
        except ProviderUnavailable as exc:
            return str(exc)
