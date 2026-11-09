"""Manual document metadata and paginated local search (no AI or network)."""
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, func, or_, select
from app.models import Document, DocumentExtraction, DocumentMetadata

DocumentStatus = Literal['unspecified', 'active', 'archived', 'cancelled']
Category = Literal['unspecified', 'stu', 'oar', 'policy', 'instruction', 'regulation', 'procedure', 'audit', 'report', 'other']
STATUS_LABELS = {'unspecified': 'Не указан', 'active': 'Действующий', 'archived': 'Архивный', 'cancelled': 'Отменённый'}
CATEGORY_LABELS = {'unspecified': 'Не указан', 'stu': 'СТУ', 'oar': 'ОАР', 'policy': 'Положение', 'instruction': 'Инструкция',
                   'regulation': 'Регламент', 'procedure': 'Процедура', 'audit': 'Документ аудита', 'report': 'Отчёт', 'other': 'Другое'}
PAGE_SIZE = 20


class MetadataInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    title: str = Field(default='', max_length=255)
    registration_number: str = Field(default='', max_length=100)
    version: str = Field(default='', max_length=60)
    department: str = Field(default='', max_length=150)
    lifecycle_status: DocumentStatus = 'unspecified'
    category: Category = 'unspecified'
    approved_on: date | None = None
    review_on: date | None = None

    @field_validator('approved_on', 'review_on', mode='before')
    @classmethod
    def empty_date(cls, value):
        return None if value == '' else value


def search_documents(db, query='', status='all', category='all', department='', page=1):
    body = case((DocumentExtraction.status == 'ready', DocumentExtraction.text), else_='')
    statement = select(Document, DocumentMetadata, DocumentExtraction.status,
                       func.qms_excerpt(body, query, DocumentExtraction.source_map_json))
    statement = statement.outerjoin(DocumentMetadata).outerjoin(DocumentExtraction)
    if query:
        needle = query.casefold()
        fields = [Document.original_name, DocumentMetadata.title, DocumentMetadata.registration_number, body]
        statement = statement.where(or_(*(func.instr(func.qms_casefold(field), needle) > 0 for field in fields)))
    if status != 'all':
        statement = statement.where(func.coalesce(DocumentMetadata.lifecycle_status, 'unspecified') == status)
    if category != 'all':
        statement = statement.where(func.coalesce(DocumentMetadata.category, 'unspecified') == category)
    if department:
        statement = statement.where(func.instr(func.qms_casefold(DocumentMetadata.department), department.casefold()) > 0)
    # Count only metadata IDs; full extracted texts never enter the result set.
    count = db.scalar(select(func.count()).select_from(statement.with_only_columns(Document.id).order_by(None).subquery()))
    rows = db.execute(statement.order_by(Document.id.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    results = []
    for document, metadata, extraction_status, raw_excerpt in rows:
        results.append({'document': document, 'metadata': metadata, 'extraction_status': extraction_status,
                        'excerpt': json.loads(raw_excerpt),
                        'overdue': bool(metadata and metadata.lifecycle_status == 'active' and metadata.review_on and metadata.review_on < date.today())})
    return results, count
