from datetime import date, datetime, timezone
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text
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
