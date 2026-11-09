import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.models import ChatMessage, Conversation, Document
from app.database import SCHEMA_VERSION, build_engine, initialize_database
from app.history import latest_conversation, list_conversations, message_page, save_exchange
from app.providers import ProviderUnavailable, get_provider
from app.storage import save_upload

ROOT = Path(__file__).parent
MODULES = {"knowledge": "База знаний", "documents": "Документы", "incidents": "Инциденты", "risks": "Риски", "audits": "Внутренние аудиты", "reports": "Отчётность", "settings": "Настройки"}


MODULE_INFO = {
    "knowledge": ("Локальное хранилище документов СМК.", "Доступна загрузка. Извлечение текста, классификация и поиск пока не реализованы."),
    "documents": ("Рабочее пространство для документов СМК.", "Анализ структуры, сравнение версий и создание Word и Excel пока не реализованы."),
    "incidents": ("Данные об инцидентах и их анализ.", "Импорт Excel, расчёт показателей и анализ динамики пока не реализованы."),
    "risks": ("Оценка и управление рисками процессов.", "Реестр рисков, расчёт ранга и контроль мероприятий пока не реализованы."),
    "audits": ("Планирование и сопровождение внутренних аудитов.", "Программы, чек-листы, несоответствия и отчёты пока не реализованы."),
    "reports": ("Отчётность системы менеджмента качества.", "Сводные таблицы, диаграммы и экспорт отчётов пока не реализованы."),
    "settings": ("Текущие параметры приложения и оформление.", "Работает только MockProvider. Локальный и облачный ИИ не подключены."),
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
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "templates")

    def render(request, template, **context):
        return templates.TemplateResponse(request=request, name=template, context={"modules": MODULES, "settings": settings, **context})

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

    @app.get("/modules/{module}", response_class=HTMLResponse)
    def module_page(request: Request, module: str):
        if module not in MODULES:
            raise HTTPException(404)
        with sessions() as db:
            documents = db.scalars(select(Document).order_by(Document.id.desc()).limit(100)).all()
        return render(request, "module.html", active=module, title=MODULES[module], documents=documents, description=MODULE_INFO[module][0], limitation=MODULE_INFO[module][1])

    @app.post("/chat", response_class=HTMLResponse)
    def chat(request: Request, message: str = Form(..., min_length=1, max_length=4000),
             conversation_id: int | None = Form(None, ge=1)):
        message = message.strip()
        if not message:
            raise HTTPException(400, "Введите текст запроса.")
        with sessions.begin() as db:
            conversation = db.get(Conversation, conversation_id) if conversation_id else latest_conversation(db)
            if conversation is None:
                raise HTTPException(404, "Диалог не найден.")
            try:
                answer = get_provider(settings.ai_provider).reply(message)
            except ProviderUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            messages = save_exchange(db, conversation, message, answer)
            response = render(request, "messages.html", messages=messages)
            selected_id = conversation.id
        response.headers["HX-Push-Url"] = f"/?conversation_id={selected_id}"
        logger.info("Сообщения чата сохранены; диалог=%d", selected_id)
        return response

    @app.post("/uploads")
    async def upload(file: UploadFile = File(...)):
        name, stored, size = await save_upload(file, data / "uploads", settings.max_upload_mb * 1024 * 1024)
        try:
            with sessions() as db:
                doc = Document(original_name=name, stored_name=stored, size=size)
                db.add(doc)
                db.commit()
        except Exception:
            (data / "uploads" / stored).unlink(missing_ok=True)
            raise
        logger.info("Файл сохранён локально; размер=%d", size)
        return {"message": "Файл сохранён локально. Содержимое не обрабатывалось.", "name": name, "size": size}

    return app


app = create_app()
