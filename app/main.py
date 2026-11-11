"""Local incident analytics and hospital standard constructor."""
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.config import Settings
from app.database import SCHEMA_VERSION, build_engine, initialize_database
from app.models import IncidentBatch, StuDraft
from app.incident_routes import make_router as incident_router
from app.stu_routes import make_router as stu_router

ROOT=Path(__file__).parent
MODULES={'incidents':'Инциденты','stu':'Конструктор СТУ','audits':'Внутренние аудиты','reports':'Отчётность','settings':'Настройки'}

def create_app(settings:Settings|None=None):
 settings=settings or Settings();data=settings.data_dir.resolve()
 for folder in [data,data/'logs']:folder.mkdir(parents=True,exist_ok=True)
 logger=logging.getLogger(f'qms.{data}');logger.setLevel(logging.INFO)
 if not logger.handlers:
  handler=RotatingFileHandler(data/'logs'/'app.log',maxBytes=1000000,backupCount=3,encoding='utf-8')
  handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));logger.addHandler(handler)
 engine=build_engine(data/'qms.sqlite3');sessions=sessionmaker(engine)
 @asynccontextmanager
 async def lifespan(app):
  try:initialize_database(engine,data/'qms.sqlite3')
  except Exception as exc:logger.error('Ошибка обновления базы: %s',type(exc).__name__);engine.dispose();raise
  logger.info('Приложение запущено; локальная аналитика и СТУ')
  yield
  engine.dispose()
 app=FastAPI(title='QMS Assistant KKB',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
 app.state.settings=settings;app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
 templates=Jinja2Templates(directory=ROOT/'templates')
 def render(request,template,**context):
  return templates.TemplateResponse(request=request,name=template,context={'modules':MODULES,'settings':settings,**context})
 @app.exception_handler(StarletteHTTPException)
 async def http_error(request,exc):
  logger.warning('Ошибка HTTP %s; путь=%s',exc.status_code,request.url.path)
  if exc.status_code==404 and 'text/html' in request.headers.get('accept',''):
   response=render(request,'error.html',active='',title='Страница не найдена',detail='Проверьте адрес или выберите раздел в меню.');response.status_code=404;return response
  return JSONResponse({'detail':exc.detail if isinstance(exc.detail,str) and exc.status_code!=404 else 'Страница не найдена.'},status_code=exc.status_code)
 @app.exception_handler(RequestValidationError)
 async def validation_error(request,exc):return JSONResponse({'detail':'Проверьте заполнение полей и допустимую длину текста.'},status_code=422)
 @app.exception_handler(Exception)
 async def unexpected_error(request,exc):
  logger.error('Необработанная ошибка: %s; путь=%s',type(exc).__name__,request.url.path)
  return JSONResponse({'detail':'Внутренняя ошибка. Проверьте локальный журнал приложения.'},status_code=500)
 @app.get('/health')
 def health():
  with sessions() as db:db.execute(select(StuDraft.id).limit(1))
  return {'status':'ok','provider':'disabled','schema_version':SCHEMA_VERSION}
 @app.get('/')
 def home(request:Request):
  with sessions() as db:
   drafts=db.scalar(select(func.count()).select_from(StuDraft))
   batches=db.scalar(select(func.count()).select_from(IncidentBatch).where(IncidentBatch.state=='confirmed'))
  return render(request,'workspace.html',active='home',title='Главная',draft_count=drafts,batch_count=batches)
 app.include_router(incident_router(sessions,settings,render,logger));app.include_router(stu_router(sessions,render))
 @app.get('/modules/{module}')
 def module_page(request:Request,module:str):
  if module not in MODULES:raise HTTPException(404)
  if module=='settings':return render(request,'local_settings.html',active=module,title='Настройки')
  title,description,limitation=(MODULES[module],'Отчётность системы менеджмента качества.','Доступен отчёт по инцидентам за месяц или квартал с экспортом Word и Excel.') if module=='reports' else (MODULES[module],'Планирование и сопровождение внутренних аудитов.','Модуль пока не реализован.')
  return render(request,'module.html',active=module,title=title,description=description,limitation=limitation)
 return app

app=create_app()
