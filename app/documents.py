"""Document processing without holding a database transaction during parsing."""
from pathlib import Path
import json
from app.extraction import ExtractionResult, extract_local
from app.models import Document, DocumentExtraction, now


def process_document(document_id, sessions, folder: Path):
    with sessions() as db:
        document = db.get(Document, document_id)
        if document is None:
            raise LookupError('Документ не найден.')
        path = (folder / document.stored_name).resolve()
    if path.parent != folder.resolve():
        result = ExtractionResult(status='error', notice='Некорректный путь к исходному файлу.')
    else:
        result = extract_local(path)
    with sessions.begin() as db:
        stored = db.get(DocumentExtraction, document_id)
        if stored is None:
            stored = DocumentExtraction(document_id=document_id)
            db.add(stored)
        stored.status, stored.text, stored.notice = result.status, result.text, result.notice
        stored.source_map_json = json.dumps([source.model_dump() for source in result.sources], ensure_ascii=False)
        stored.processed_at = now()
    return result
