"""XLSX import worker; no network or spreadsheet execution."""
import json
import sys
from pathlib import Path
from app.incident_excel import inspect, parse, IncidentValidationError


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    except ImportError:
        pass
    mode, source, output, *extra = sys.argv[1:]
    try:
        result = inspect(Path(source)) if mode == 'inspect' else parse(Path(source), json.loads(Path(extra[0]).read_text(encoding='utf-8')))
        value = {'ok': True, 'result': result}
    except (IncidentValidationError, KeyError) as exc:
        # Only our validation errors are useful; parser exceptions may contain data.
        value = {'ok': False, 'error': str(exc)[:300] if isinstance(exc, IncidentValidationError) else 'Лист не найден'}
    except Exception:
        value = {'ok': False, 'error': 'Не удалось прочитать XLSX. Проверьте формат, целостность и отсутствие пароля.'}
    Path(output).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
