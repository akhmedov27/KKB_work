import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.models import Base, ChatMessage, Document
from app.providers import ProviderUnavailable, get_provider
from app.storage import save_upload

ROOT = Path(__file__).parent
MODULES = {"knowledge": "База знаний", "documents": "Документы", "incidents": "Инциденты", "risks": "Риски", "audits": "Внутренние аудиты", "reports": "Отчётность", "settings": "Настройки"}


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
    engine = create_engine("sqlite:///" + (data / "qms.sqlite3").as_posix(), connect_args={"check_same_thread": False, "timeout": 15})
    sessions = sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
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
        return {"status": "ok", "provider": settings.ai_provider}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        with sessions() as db:
            messages = list(reversed(db.scalars(select(ChatMessage).order_by(ChatMessage.id.desc()).limit(100)).all()))
            documents = db.scalars(select(Document).order_by(Document.id.desc()).limit(5)).all()
        return render(request, "home.html", active="home", title="Главная", messages=messages, documents=documents)

    @app.get("/modules/{module}", response_class=HTMLResponse)
    def module_page(request: Request, module: str):
        if module not in MODULES:
            raise HTTPException(404)
        with sessions() as db:
            documents = db.scalars(select(Document).order_by(Document.id.desc()).limit(100)).all()
        return render(request, "module.html", active=module, title=MODULES[module], documents=documents)

    @app.post("/chat", response_class=HTMLResponse)
    def chat(request: Request, message: str = Form(..., min_length=1, max_length=4000)):
        message = message.strip()
        if not message:
            raise HTTPException(400, "Введите текст запроса.")
        try:
            answer = get_provider(settings.ai_provider).reply(message)
        except ProviderUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        with sessions() as db:
            messages = [ChatMessage(role="user", content=message), ChatMessage(role="assistant", content=answer)]
            db.add_all(messages)
            db.commit()
            for item in messages:
                db.refresh(item)
            response = render(request, "messages.html", messages=messages)
        logger.info("Сообщения чата сохранены")
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
