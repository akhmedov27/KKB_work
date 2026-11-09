"""One-shot text extraction. Never launches document applications or macros."""
import sys
from pathlib import Path
from zipfile import ZipFile

from app.extraction import ExtractionResult, MAX_TEXT_CHARS

MAX_UNPACKED = 32 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_PDF_PAGES = 200
MAX_SHEETS = 20
MAX_ROWS = 50_000
MAX_CELLS = 100_000


class InvalidDocument(Exception):
    pass


class TextBuffer:
    def __init__(self):
        self.parts = []
        self.size = 0
        self.has_content = False

    def add(self, value, *, content=True):
        text = str(value).strip() if value is not None else ''
        if not text:
            return
        self.size += len(text) + (1 if self.parts else 0)
        if self.size > MAX_TEXT_CHARS:
            raise InvalidDocument('Превышен лимит текста: 500 000 символов. Разделите документ на части.')
        self.parts.append(text)
        self.has_content |= content

    def finish(self, empty_notice):
        if not self.has_content:
            return ExtractionResult(status='empty', notice=empty_notice)
        return ExtractionResult(status='ready', text='\n'.join(self.parts), notice='Текст извлечён локально. Проверьте полноту и порядок по оригиналу.')


def check_office_package(path, suffix):
    """Inspect in memory; never extract ZIP entries onto the filesystem."""
    from defusedxml import ElementTree
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            names = {item.filename for item in entries}
            required = 'word/document.xml' if suffix == '.docx' else 'xl/workbook.xml'
            if len(entries) > MAX_ENTRIES or sum(i.file_size for i in entries) > MAX_UNPACKED:
                raise InvalidDocument('Превышен лимит Office-архива: 2000 элементов или 32 МиБ распакованных данных.')
            if len(names) != len(entries) or required not in names or '[Content_Types].xml' not in names:
                raise InvalidDocument('Формат содержимого не соответствует расширению документа.')
            for item in entries:
                if item.flag_bits & 1:
                    raise InvalidDocument('Документы Office с паролем не поддерживаются.')
                if 'vbaproject' in item.filename.lower() or item.filename.lower().endswith('.bin'):
                    raise InvalidDocument('Документы со встроенными двоичными объектами или макросами не поддерживаются.')
                if item.file_size > 1024 * 1024 and item.file_size > max(item.compress_size, 1) * 200:
                    raise InvalidDocument('Слишком высокая степень сжатия Office-архива. Обработка остановлена.')
                # Defused XML rejects DTD/entities, including external entities.
                if item.filename.lower().endswith(('.xml', '.rels')):
                    with archive.open(item) as stream:
                        ElementTree.parse(stream, forbid_dtd=True)
    except InvalidDocument:
        raise
    except Exception as exc:
        raise InvalidDocument('Не удалось прочитать Office-документ: файл повреждён, зашифрован или имеет неподдерживаемую структуру.') from exc


def extract_docx(path):
    from docx import Document
    from docx.table import Table
    check_office_package(path, '.docx')
    buffer = TextBuffer()
    for block in Document(path).iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                values = [cell.text for cell in row.cells]
                if any(value.strip() for value in values):
                    buffer.add(' | '.join(values))
        else:
            buffer.add(block.text)
    return buffer.finish('В основном содержимом DOCX не найден текст. Колонтитулы, текстовые поля и изображения не извлекаются.')


def extract_xlsx(path):
    from openpyxl import load_workbook
    check_office_package(path, '.xlsx')
    buffer = TextBuffer()
    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        if len(workbook.worksheets) > MAX_SHEETS:
            raise InvalidDocument('Превышен лимит: 20 листов в книге.')
        cells = 0
        for sheet in workbook.worksheets:
            if (sheet.max_row or 0) > MAX_ROWS or (sheet.max_column or 0) > MAX_CELLS:
                raise InvalidDocument('Превышены допустимые размеры листа Excel.')
            buffer.add(f'[Лист: {sheet.title}]', content=False)
            # Limits are also enforced during iteration for missing/false dimensions.
            for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                cells += len(row)
                if number > MAX_ROWS or cells > MAX_CELLS:
                    raise InvalidDocument('Превышен лимит: 50 000 строк на лист или 100 000 ячеек на книгу.')
                values = ['' if value is None else str(value) for value in row]
                if any(values):
                    buffer.add(f'Строка {number}: ' + ' | '.join(values))
    finally:
        workbook.close()
    return buffer.finish('В XLSX не найдены доступные значения. Формулы не вычисляются; доступны только сохранённые результаты.')


def extract_pdf(path):
    import pymupdf
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    with path.open('rb') as file:
        if b'%PDF-' not in file.read(1024):
            raise InvalidDocument('Содержимое файла не соответствует формату PDF.')
    buffer = TextBuffer()
    with pymupdf.open(path) as document:
        if not document.is_pdf:
            raise InvalidDocument('Содержимое файла не соответствует формату PDF.')
        if document.needs_pass:
            raise InvalidDocument('PDF защищён паролем. Загрузите доступную незашифрованную копию.')
        if document.page_count > MAX_PDF_PAGES:
            raise InvalidDocument('Превышен лимит: 200 страниц PDF.')
        empty_pages = 0
        for index, page in enumerate(document):
            text = page.get_text('text', sort=True).strip()
            buffer.add(f'[Страница {index + 1}]', content=False)
            buffer.add(text)
            if not text:
                empty_pages += 1
        result = buffer.finish('Текстовый слой не найден. Возможно, это скан. OCR на этапе QMS-004 не поддерживается.')
        if result.status == 'ready' and empty_pages:
            result.notice += f' Страниц без доступного текста: {empty_pages}; OCR не выполнялся.'
        return result


def extract(path: Path):
    try:
        parser = {'.docx': extract_docx, '.xlsx': extract_xlsx, '.pdf': extract_pdf}.get(path.suffix.lower())
        if parser is None:
            raise InvalidDocument('Формат не поддерживается.')
        return parser(path)
    except InvalidDocument as exc:
        return ExtractionResult(status='error', notice=str(exc))
    except (MemoryError, OverflowError):
        return ExtractionResult(status='error', notice='Превышен лимит памяти или сложности документа.')
    except Exception:
        # Parser exceptions may contain document text, paths or passwords.
        return ExtractionResult(status='error', notice='Не удалось прочитать документ. Проверьте формат, целостность и отсутствие пароля.')


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    except ImportError:
        pass  # Windows: bounded traversal and parent timeout still apply.
    result = extract(Path(sys.argv[1]))
    sys.stdout.write(result.model_dump_json())


if __name__ == '__main__':
    main()
