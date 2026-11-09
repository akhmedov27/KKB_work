import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.models import ChatMessage, Conversation, Document, DocumentExtraction, DocumentMetadata, now
from app.database import SCHEMA_VERSION, build_engine, initialize_database
from app.history import latest_conversation, list_conversations, message_page, save_exchange
from app.providers import ProviderUnavailable, cloud_label, cloud_host
from app.storage import save_upload
from app.documents import process_document
from app.extraction import ProcessingBusy, STATUS_LABELS
from app.knowledge import MetadataInput, search_documents, PAGE_SIZE, STATUS_LABELS as DOCUMENT_STATUSES, CATEGORY_LABELS
from app.search import text_parts
from app.ai_service import AIService

ROOT = Path(__file__).parent
MODULES = {"knowledge": "База знаний", "documents": "Документы", "incidents": "Инциденты", "risks": "Риски", "audits": "Внутренние аудиты", "reports": "Отчётность", "settings": "Настройки"}


MODULE_INFO = {
    "knowledge": ("Локальное хранилище документов СМК.", "Доступны поиск, ручная классификация и реквизиты документов. Смысловой поиск и автоматические ответы ИИ по базе пока не подключены."),
    "documents": ("Рабочее пространство для документов СМК.", "Анализ структуры, сравнение версий и создание Word и Excel пока не реализованы."),
    "incidents": ("Данные об инцидентах и их анализ.", "Импорт Excel, расчёт показателей и анализ динамики пока не реализованы."),
    "risks": ("Оценка и управление рисками процессов.", "Реестр рисков, расчёт ранга и контроль мероприятий пока не реализованы."),
    "audits": ("Планирование и сопровождение внутренних аудитов.", "Программы, чек-листы, несоответствия и отчёты пока не реализованы."),
    "reports": ("Отчётность системы менеджмента качества.", "Сводные таблицы, диаграммы и экспорт отчётов пока не реализованы."),
    "settings": ("Текущие параметры приложения и оформление.", "ИИ подключается по конфигурации. Groq и DeepSeek требуют ключа, включения облачного режима и разрешения на каждый запрос."),
}


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    data = settings.data_dir.resolve()
    for folder in (data, data / "uploads", data / "logs"):
        folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"qms.{data}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(data / "logs" / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    engine = build_engine(data / "qms.sqlite3")
    sessions = sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(app):
        try:
            initialize_database(engine, data / "qms.sqlite3")
        except Exception as exc:
            logger.error("Не удалось обновить базу данных: %s", type(exc).__name__)
            engine.dispose()
            raise
        logger.info("Приложение запущено; провайдер=%s", settings.ai_provider)
        yield
        engine.dispose()

    app = FastAPI(title="QMS Assistant KKB", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    ai_service = AIService(settings)
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "templates")

    def render(request, template, **context):
        return templates.TemplateResponse(request=request, name=template, context={"modules": MODULES, "settings": settings, "extraction_labels": STATUS_LABELS, "document_statuses": DOCUMENT_STATUSES, "categories": CATEGORY_LABELS, "ai_status": ai_service.status(), "ai_key_present": bool(settings.cloud_api_key.get_secret_value().strip()), "cloud_label": cloud_label(settings), "cloud_host": cloud_host(settings), **context})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        logger.warning("Ошибка HTTP %s; путь=%s", exc.status_code, request.url.path)
        if exc.status_code == 404 and "text/html" in request.headers.get("accept", ""):
            response = render(request, "error.html", active="", title="Страница не найдена", status_code=404, detail="Проверьте адрес или выберите раздел в меню.")
            response.status_code = 404
            return response
        return JSONResponse({"detail": exc.detail if isinstance(exc.detail, str) and exc.status_code != 404 else "Страница не найдена."}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": "Проверьте заполнение полей и допустимую длину текста."}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        # Do not log user text, document contents or credentials.
        logger.error("Необработанная ошибка: %s; путь=%s", type(exc).__name__, request.url.path)
        return JSONResponse({"detail": "Внутренняя ошибка. Проверьте локальный журнал приложения."}, status_code=500)

    @app.get("/health")
    def health():
        with sessions() as db:
            db.execute(select(ChatMessage.id).limit(1))
        return {"status": "ok", "provider": settings.ai_provider, "schema_version": SCHEMA_VERSION}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, conversation_id: int | None = Query(None, ge=1),
             before_id: int | None = Query(None, ge=1), conversation_page: int = Query(1, ge=1, le=1000000)):
        with sessions() as db:
            conversation = db.get(Conversation, conversation_id) if conversation_id else latest_conversation(db)
            if conversation is None:
                raise HTTPException(404, "Диалог не найден.")
            messages, has_older = message_page(db, conversation.id, before_id)
            conversations, has_more_conversations = list_conversations(db, conversation_page)
            documents = db.scalars(select(Document).order_by(Document.id.desc()).limit(5)).all()
        return render(request, "home.html", active="home", title="Главная", messages=messages, documents=documents,
                      conversation=conversation, conversations=conversations, conversation_page=conversation_page,
                      has_more_conversations=has_more_conversations, has_older=has_older, before_id=before_id)

    @app.post("/conversations")
    def new_conversation(title: str = Form("Новый диалог", min_length=1, max_length=120)):
        title = title.strip()
        if not title:
            raise HTTPException(400, "Введите название диалога.")
        with sessions.begin() as db:
            conversation = Conversation(title=title)
            db.add(conversation)
            db.flush()
            conversation_id = conversation.id
        logger.info("Создан диалог; id=%d", conversation_id)
        return RedirectResponse(f"/?conversation_id={conversation_id}", status_code=303)

    @app.get("/modules/knowledge", response_class=HTMLResponse)
    def knowledge_page(request: Request, q: str = Query("", max_length=200),
                       status: Literal['all', 'unspecified', 'active', 'archived', 'cancelled'] = 'all',
                       category: Literal['all', 'unspecified', 'stu', 'oar', 'policy', 'instruction', 'regulation', 'procedure', 'audit', 'report', 'other'] = 'all',
                       department: str = Query("", max_length=150), page: int = Query(1, ge=1, le=1000000)):
        q, department = q.strip(), department.strip()
        with sessions() as db:
            results, total = search_documents(db, q, status, category, department, page)
        def page_url(number):
            return '/modules/knowledge?' + urlencode(dict(q=q, status=status, category=category, department=department, page=number))
        return render(request, 'knowledge.html', active='knowledge', title='База знаний', results=results,
                      q=q, status=status, category=category, department=department, total=total, page=page,
                      previous_url=page_url(page - 1) if page > 1 else None,
                      next_url=page_url(page + 1) if page * PAGE_SIZE < total else None)

    @app.get("/modules/{module}", response_class=HTMLResponse)
    def module_page(request: Request, module: str):
        if module not in MODULES:
            raise HTTPException(404)
        return render(request, "module.html", active=module, title=MODULES[module],
                      description=MODULE_INFO[module][0], limitation=MODULE_INFO[module][1])

    @app.post("/chat", response_class=HTMLResponse)
    def chat(request: Request, message: str = Form(..., min_length=1, max_length=4000),
             conversation_id: int | None = Form(None, ge=1),
             fragment: str = Form("", max_length=6000), cloud_consent: bool = Form(False)):
        origin = request.headers.get('origin')
        if settings.ai_provider == 'cloud' and origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, "Отправка в облако с другой страницы запрещена.")
        message = message.strip()
        if not message:
            raise HTTPException(400, "Введите текст запроса.")
        with sessions() as db:
            conversation = db.get(Conversation, conversation_id) if conversation_id else latest_conversation(db)
            if conversation is None:
                raise HTTPException(404, "Диалог не найден.")
            selected_id = conversation.id
        try:
            reply = ai_service.reply(message, fragment, cloud_consent)
        except ProviderUnavailable as exc:
            logger.warning("Запрос ИИ не выполнен; провайдер=%s; код=%d", settings.ai_provider, exc.status_code)
            raise HTTPException(exc.status_code, str(exc)) from exc
        # Network calls never hold a write transaction open. Persist only the
        # successfully received exchange; provider errors leave history intact.
        with sessions.begin() as db:
            conversation = db.get(Conversation, selected_id)
            messages = save_exchange(db, conversation, reply.user_text, reply.text, reply.provider, reply.model)
            response = render(request, "messages.html", messages=messages)
        response.headers["HX-Push-Url"] = f"/?conversation_id={selected_id}"
        logger.info("Сообщения чата сохранены; диалог=%d", selected_id)
        return response

    @app.get("/documents/{document_id}", response_class=HTMLResponse)
    def document_detail(request: Request, document_id: int):
        with sessions() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise HTTPException(404, "Документ не найден.")
            extraction = db.get(DocumentExtraction, document_id)
            metadata = db.get(DocumentMetadata, document_id)
        parts = text_parts(extraction.text, extraction.source_map_json) if extraction and extraction.status == 'ready' else []
        overdue = bool(metadata and metadata.lifecycle_status == 'active' and metadata.review_on and metadata.review_on < date.today())
        return render(request, "document.html", active="knowledge", title="Просмотр документа", document=document,
                      extraction=extraction, metadata=metadata, text_parts=parts, overdue=overdue)

    @app.post("/documents/{document_id}/metadata")
    def save_metadata(document_id: int, metadata: Annotated[MetadataInput, Form()]):
        with sessions.begin() as db:
            if db.get(Document, document_id) is None:
                raise HTTPException(404, "Документ не найден.")
            record = db.get(DocumentMetadata, document_id)
            if record is None:
                record = DocumentMetadata(document_id=document_id)
                db.add(record)
            for key, value in metadata.model_dump().items():
                setattr(record, key, value)
            record.updated_at = now()
        logger.info("Сохранены реквизиты; документ=%d", document_id)
        return {"message": "Реквизиты сохранены локально."}

    @app.post("/documents/{document_id}/extract")
    def extract_document(document_id: int):
        try:
            result = process_document(document_id, sessions, data / "uploads")
        except LookupError as exc:
            raise HTTPException(404, "Документ не найден.") from exc
        except ProcessingBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        logger.info("Извлечение текста; документ=%d; статус=%s", document_id, result.status)
        return {"status": result.status, "message": result.notice}

    @app.post("/uploads")
    async def upload(file: UploadFile = File(...)):
        name, stored, size = await save_upload(file, data / "uploads", settings.max_upload_mb * 1024 * 1024)
        try:
            def register():
                with sessions.begin() as db:
                    doc = Document(original_name=name, stored_name=stored, size=size)
                    db.add(doc)
                    db.flush()
                    return doc.id
            document_id = await run_in_threadpool(register)
        except Exception:
            (data / "uploads" / stored).unlink(missing_ok=True)
            raise
        logger.info("Файл сохранён локально; документ=%d; размер=%d", document_id, size)
        try:
            result = await run_in_threadpool(process_document, document_id, sessions, data / "uploads")
            status, notice = result.status, result.notice
        except ProcessingBusy as exc:
            status, notice = "unprocessed", str(exc)
        logger.info("Извлечение текста; документ=%d; статус=%s", document_id, status)
        return {"message": "Файл сохранён локально. " + notice, "name": name, "size": size,
                "id": document_id, "status": status, "url": f"/documents/{document_id}"}

    return app


app = create_app()
