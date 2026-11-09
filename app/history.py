"""Queries and transactional writes for local chat history."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import ChatMessage, Conversation, now

MESSAGE_PAGE_SIZE = 50
CONVERSATION_PAGE_SIZE = 20


def list_conversations(db: Session, page: int):
    rows = db.scalars(select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                      .offset((page - 1) * CONVERSATION_PAGE_SIZE).limit(CONVERSATION_PAGE_SIZE + 1)).all()
    return rows[:CONVERSATION_PAGE_SIZE], len(rows) > CONVERSATION_PAGE_SIZE


def latest_conversation(db: Session):
    return db.scalar(select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(1))


def message_page(db: Session, conversation_id: int, before_id: int | None):
    query = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    rows = db.scalars(query.order_by(ChatMessage.id.desc()).limit(MESSAGE_PAGE_SIZE + 1)).all()
    return list(reversed(rows[:MESSAGE_PAGE_SIZE])), len(rows) > MESSAGE_PAGE_SIZE


def save_exchange(db: Session, conversation: Conversation, message: str, answer: str):
    rows = [ChatMessage(conversation_id=conversation.id, role='user', content=message),
            ChatMessage(conversation_id=conversation.id, role='assistant', content=answer)]
    conversation.updated_at = now()
    db.add_all(rows)
    db.flush()
    return rows
