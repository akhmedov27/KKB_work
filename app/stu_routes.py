import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import select, update
from starlette.concurrency import run_in_threadpool
from app.models import StuDraft, now
from app.stu_schema import StuContent
from app.stu_docx import generate


def make_router(sessions,render):
 router=APIRouter()
 def get(db,id):
  row=db.get(StuDraft,id)
  if row is None:raise HTTPException(404,'Черновик СТУ не найден.')
  return row
 @router.get('/modules/stu')
 def listing(request:Request,page:int=1):
  if not 1<=page<=1000000:raise HTTPException(400,'Некорректная страница.')
  with sessions() as db:
   rows=db.scalars(select(StuDraft).order_by(StuDraft.updated_at.desc(),StuDraft.id.desc()).offset((page-1)*50).limit(51)).all()
  return render(request,'stu_list.html',active='stu',title='Конструктор СТУ',drafts=rows[:50],page=page,has_more=len(rows)>50)
 @router.post('/stu')
 def create():
  with sessions.begin() as db:
   row=StuDraft(payload_json=StuContent().model_dump_json());db.add(row);db.flush();id=row.id
  return RedirectResponse(f'/stu/{id}',303)
 @router.get('/stu/{id}')
 def editor(request:Request,id:int):
  with sessions() as db:row=get(db,id)
  return render(request,'stu_editor.html',active='stu',title='Конструктор СТУ',draft=row,initial=json.loads(row.payload_json))
 @router.put('/stu/{id}')
 async def save(request:Request,id:int):
  body=await request.body()
  if len(body)>2*1024*1024:raise HTTPException(413,'Слишком большой черновик.')
  try:
   data=json.loads(body);version=data['version']
   if type(version) is not int or version<1:raise ValueError()
   content=StuContent.model_validate(data['content'])
  except (ValueError,KeyError,TypeError,ValidationError):raise HTTPException(400,'Проверьте длину полей, структуру матрицы и значения от 1 до 5.') from None
  with sessions.begin() as db:
   get(db,id)
   result=db.execute(update(StuDraft).where(StuDraft.id==id,StuDraft.version==version).values(title=content.title.strip() or 'Новый СТУ',payload_json=content.model_dump_json(),version=version+1,updated_at=now()))
   if result.rowcount!=1:raise HTTPException(409,'Черновик изменён в другой вкладке. Сохраните введённый текст отдельно и обновите страницу.')
  return {'version':version+1,'errors':content.export_errors()}
 @router.post('/stu/{id}/copy')
 def copy(id:int):
  with sessions.begin() as db:
   old=get(db,id);row=StuDraft(title=old.title+' — копия',payload_json=old.payload_json);db.add(row);db.flush();new_id=row.id
  return RedirectResponse(f'/stu/{new_id}',303)
 @router.get('/stu/{id}/export.docx')
 async def export(id:int):
  with sessions() as db:row=get(db,id)
  content=StuContent.model_validate_json(row.payload_json);errors=content.export_errors()
  if errors:raise HTTPException(400,'Заполните перед экспортом: '+'; '.join(errors))
  result=await run_in_threadpool(generate,content)
  return Response(result,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':'attachment; filename="stu.docx"'})
 return router
