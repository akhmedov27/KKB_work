"""Run only against an isolated test server and a synthetic STU draft."""
import os
from playwright.sync_api import sync_playwright,expect
url=os.environ['QMS_TEST_URL'];id=os.environ.get('QMS_STU_ID','1')
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path=os.environ.get('QMS_CHROMIUM_PATH'))
 page=browser.new_page(viewport={'width':1600,'height':1100});errors=[];external=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('request',lambda r:external.append(r.url) if not r.url.startswith(url) and not r.url.startswith('blob:') else None)
 page.goto(url+'/stu/'+id)
 section=page.locator('details').filter(has=page.get_by_text('6 ОПИСАНИЕ ПРОЦЕССА',exact=True));section.locator('summary').click()
 section.get_by_role('button',name='Открыть квалиграмму',exact=True).first.click()
 expect(page.locator('#q-paper svg')).to_be_visible()
 for i in range(2):page.get_by_role('button',name='Добавить дорожку',exact=True).click()
 page.get_by_label('Исполнитель 1',exact=True).fill('Руководитель');page.get_by_label('Исполнитель 1',exact=True).press('Tab')
 page.get_by_label('Исполнитель 2',exact=True).fill('Специалист');page.get_by_label('Исполнитель 2',exact=True).press('Tab')
 page.locator('#q-palette').get_by_role('button',name='Действие',exact=True).click()
 page.get_by_label('Текст',exact=True).fill('Проверить синтетическую заявку');page.get_by_label('Текст',exact=True).press('Tab')
 page.locator('#q-properties').get_by_label('Специалист',exact=True).check()
 page.get_by_role('button',name='Растянуть по дорожкам исполнителей',exact=True).click()
 expect(page.locator('#q-paper svg')).to_contain_text('Уч.')
 page.get_by_role('button',name='Составить из шагов',exact=True).click()
 expect(page.locator('#q-description')).to_have_value(__import__('re').compile('.*Ответственный: Руководитель.*',__import__('re').S))
 page.get_by_role('button',name='Сохранить схему',exact=True).click();expect(page.locator('#q-status')).to_have_text('Схема сохранена')
 page.reload();expect(page.locator('#q-paper svg')).to_contain_text('Проверить синтетическую заявку')
 node=page.locator('[data-node-id]').first;box=node.bounding_box();page.mouse.move(box['x']+35,box['y']+35);page.mouse.down();page.mouse.move(box['x']+50,box['y']+80,steps=5);page.mouse.up()
 expect(page.locator('#q-status')).to_have_text('Есть несохранённые изменения')
 for label,suffix in [('PNG','.png'),('Visio 2007 · VDX','.vdx')]:
  with page.expect_download() as download:page.get_by_role('button',name=label,exact=True).click()
  assert download.value.suggested_filename.endswith(suffix)
 page.screenshot(path='/tmp/qualigram-editor.png',full_page=True)
 page.set_viewport_size({'width':390,'height':850});assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
 assert not errors,errors
 assert not external,external
 browser.close();print('PASS: UI creation, shared action, description, save/reload, drag, PNG/VDX, mobile, no external requests')
