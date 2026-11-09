from typing import Protocol


class AIProvider(Protocol):
    def reply(self, message: str) -> str: ...


class MockProvider:
    def reply(self, message: str) -> str:
        return f"Тестовый ответ MockProvider. Получен запрос: «{message}». Анализ документов и медицинские рекомендации не выполняются."


class ProviderUnavailable(Exception):
    pass


class LocalProvider:
    def reply(self, message: str) -> str:
        raise ProviderUnavailable("Локальный ИИ пока не подключён. Выберите mock в конфигурации.")


class CloudProvider:
    def reply(self, message: str) -> str:
        raise ProviderUnavailable("Облачный ИИ отключён на этапе QMS-001. Внешние запросы не выполняются.")


def get_provider(name: str) -> AIProvider:
    return {"mock": MockProvider, "local": LocalProvider, "cloud": CloudProvider}[name]()
