"""Local parser subprocess boundary and bounded result contract."""
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

MAX_TEXT_CHARS = 500_000
TIMEOUT_SECONDS = 20
_GATE = threading.BoundedSemaphore(1)
STATUS_LABELS = {'ready': 'Текст извлечён', 'empty': 'Нет доступного текста', 'error': 'Ошибка обработки'}


class ExtractionResult(BaseModel):
    status: Literal['ready', 'empty', 'error']
    text: str = Field(default='', max_length=MAX_TEXT_CHARS)
    notice: str = Field(default='', max_length=500)


class ProcessingBusy(Exception):
    pass


def extract_local(path: Path) -> ExtractionResult:
    if not _GATE.acquire(blocking=False):
        raise ProcessingBusy('Сейчас обрабатывается другой файл. Повторите попытку после завершения.')
    try:
        if not path.is_file():
            return ExtractionResult(status='error', notice='Исходный файл не найден в локальном хранилище.')
        try:
            completed = subprocess.run(
                [sys.executable, '-m', 'app.extract_worker', str(path.resolve())],
                cwd=Path(__file__).resolve().parent.parent,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'},
                capture_output=True, timeout=TIMEOUT_SECONDS, check=False,
            )
            if completed.returncode != 0 or len(completed.stdout) > MAX_TEXT_CHARS * 6 + 4096:
                return ExtractionResult(status='error', notice='Процесс обработки завершился с ошибкой или превысил лимит ресурсов.')
            return ExtractionResult.model_validate_json(completed.stdout)
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for the child on timeout.
            return ExtractionResult(status='error', notice='Превышено время обработки (20 секунд). Попробуйте файл меньшего размера.')
        except (OSError, ValueError):
            return ExtractionResult(status='error', notice='Не удалось запустить обработку. Проверьте установку зависимостей.')
    finally:
        _GATE.release()
