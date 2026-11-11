from datetime import date, datetime, timezone
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_conversations_updated", "updated_at", "id"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), default="mock", server_default="mock")
    model: Mapped[str] = mapped_column(String(100), default="", server_default="")
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="RESTRICT"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_message_role"),
        Index("ix_messages_conversation_id", "conversation_id", "id"),
    )


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(50), unique=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text, default="")
    notice: Mapped[str] = mapped_column(Text, default="")
    source_map_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (CheckConstraint("status IN ('ready', 'empty', 'error')", name="ck_extraction_status"),)


class DocumentMetadata(Base):
    __tablename__ = "document_metadata"
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    registration_number: Mapped[str] = mapped_column(String(100), default="")
    version: Mapped[str] = mapped_column(String(60), default="")
    department: Mapped[str] = mapped_column(String(150), default="")
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="unspecified")
    category: Mapped[str] = mapped_column(String(30), default="unspecified")
    approved_on: Mapped[date | None] = mapped_column(Date)
    review_on: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (
        CheckConstraint("lifecycle_status IN ('unspecified','active','archived','cancelled')", name="ck_document_status"),
        CheckConstraint("category IN ('unspecified','stu','oar','policy','instruction','regulation','procedure','audit','report','other')", name="ck_document_category"),
        Index("ix_metadata_status_category", "lifecycle_status", "category"),
    )


class IncidentUpload(Base):
    __tablename__ = 'incident_uploads'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(50))
    sha256: Mapped[str] = mapped_column(String(64))
    inspection_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class IncidentBatch(Base):
    __tablename__ = 'incident_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[str] = mapped_column(ForeignKey('incident_uploads.id', ondelete='RESTRICT'))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    sheet_name: Mapped[str] = mapped_column(String(100))
    mapping_json: Mapped[str] = mapped_column(Text)
    summary_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default='draft')
    policy: Mapped[str] = mapped_column(String(20), default='')
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (CheckConstraint("state IN ('draft','confirmed')", name='ck_incident_batch_state'),)


class IncidentStagedRow(Base):
    __tablename__ = 'incident_staged_rows'
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('incident_batches.id', ondelete='RESTRICT'), index=True)
    source_row: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    errors_json: Mapped[str] = mapped_column(Text)
    warnings_json: Mapped[str] = mapped_column(Text)
    duplicate_of: Mapped[int | None] = mapped_column(Integer)
    conflict: Mapped[bool] = mapped_column(default=False)


class IncidentRecord(Base):
    __tablename__ = 'incident_records'
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('incident_batches.id', ondelete='RESTRICT'))
    source_row: Mapped[int] = mapped_column(Integer)
    external_id: Mapped[str] = mapped_column(String(64))
    occurred_on: Mapped[date] = mapped_column(Date)
    registered_on: Mapped[date | None] = mapped_column(Date)
    department: Mapped[str] = mapped_column(String(500))
    department_type: Mapped[str] = mapped_column(String(500))
    group_name: Mapped[str] = mapped_column(String(500))
    subgroup: Mapped[str] = mapped_column(String(500))
    event_name: Mapped[str] = mapped_column(Text)
    importance: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(500))
    urgent: Mapped[str] = mapped_column(String(500))
    source_method: Mapped[str] = mapped_column(String(500))
    root_cause: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index('ix_incidents_batch_date', 'batch_id', 'occurred_on'), UniqueConstraint('batch_id', 'source_row', name='uq_incident_source_row'))


class StuDraft(Base):
    __tablename__ = 'stu_drafts'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), default='Новый СТУ')
    payload_json: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
