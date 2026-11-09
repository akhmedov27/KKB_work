"""SQLite initialization and versioned, atomic schema upgrades."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from app.models import Base

SCHEMA_VERSION = 1


def build_engine(path: Path) -> Engine:
    engine = create_engine('sqlite:///' + path.as_posix(), connect_args={'check_same_thread': False, 'timeout': 15})

    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    return engine


def initialize_database(engine: Engine, path: Path):
    # Explicit BEGIN is needed: sqlite3's legacy transaction mode otherwise
    # allows DDL to commit outside the SQLAlchemy transaction on Python 3.12.
    with engine.connect() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            version = connection.exec_driver_sql('PRAGMA user_version').scalar_one()
            if version > SCHEMA_VERSION:
                raise RuntimeError('База данных создана более новой версией приложения. Обновите приложение.')
            if version == SCHEMA_VERSION:
                connection.commit()
                return
            tables = set(connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars())
            legacy = 'chat_messages' in tables
            if legacy:
                columns = {row[1] for row in connection.exec_driver_sql('PRAGMA table_info(chat_messages)')}
                if columns != {'id', 'role', 'content', 'created_at'} or 'conversations' in tables:
                    raise RuntimeError('Неизвестная схема базы данных. Автоматическое обновление остановлено.')
                backup_dir = path.parent / 'backups'
                backup_dir.mkdir(exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                backup = backup_dir / f'qms-before-v1-{stamp}-{uuid4().hex[:8]}.sqlite3'
                # BEGIN IMMEDIATE prevents other writers. A separate reader can
                # safely snapshot the committed old schema using SQLite backup.
                with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as destination:
                    source.backup(destination)
                    if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Проверка резервной копии не пройдена.')
            Base.metadata.create_all(connection)
            if legacy:
                # Rebuild rather than add a nullable column: every message must
                # belong to an existing conversation, including imported history.
                conversation_id = connection.exec_driver_sql(
                    "INSERT INTO conversations(title, created_at, updated_at) VALUES (?, ?, ?)",
                    ('История до QMS-003', datetime.now(timezone.utc).isoformat(sep=" "), datetime.now(timezone.utc).isoformat(sep=" ")),
                ).lastrowid
                connection.exec_driver_sql('ALTER TABLE chat_messages RENAME TO chat_messages_legacy')
                Base.metadata.tables['chat_messages'].create(connection)
                connection.exec_driver_sql(
                    'INSERT INTO chat_messages(id, conversation_id, role, content, created_at) '
                    'SELECT id, ?, role, content, created_at FROM chat_messages_legacy', (conversation_id,),
                )
                connection.exec_driver_sql('DROP TABLE chat_messages_legacy')
            else:
                connection.exec_driver_sql(
                    'INSERT INTO conversations(title, created_at, updated_at) VALUES (?, ?, ?)',
                    ('Первый диалог', datetime.now(timezone.utc).isoformat(sep=" "), datetime.now(timezone.utc).isoformat(sep=" ")),
                )
            if connection.exec_driver_sql('PRAGMA foreign_key_check').first():
                raise RuntimeError('Нарушена целостность связей базы данных.')
            connection.exec_driver_sql(f'PRAGMA user_version={SCHEMA_VERSION}')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
