"""Mutates only a separate prepared synthetic draft; use an isolated test server."""
import os
from playwright.sync_api import sync_playwright,expect
url=os.environ['QMS_TEST_URL'];id=os.environ.get('QMS_STU_ID','1')
with sync_playwright() as p:
 options={'headless':True}
 if os.environ.get('QMS_CHROMIUM_PATH'):options['executable_path']=os.environ['QMS_CHROMIUM_PATH']
 browser=p.chromium.launch(**options);page=browser.new_page(viewport={'width':1440,'height':1000})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(url+'/');expect(page.get_by_role('link',name='Конструктор СТУ',exact=True)).to_be_visible()
 assert page.get_by_role('navigation',name='Основная навигация').get_by_text('База знаний',exact=True).count()==0
 page.goto(url+'/stu/'+id)
 expect(page.locator('#stu-form details')).to_have_count(16)
 def open_section(title):
  details=page.locator('#stu-form details').filter(has=page.locator('summary').get_by_text(title,exact=True))
  if not details.evaluate('el=>el.open'):details.locator('summary').click()
  return details
 matrix=open_section('5 ОТВЕТСТВЕННОСТЬ')
 matrix.get_by_role('button',name='Добавить должность',exact=True).click()
 page.get_by_label('Должность 4',exact=True).fill('Фельдшер')
 expect(matrix.get_by_role('columnheader',name='Фельдшер',exact=True)).to_be_visible()
 matrix.get_by_role('button',name='Добавить подразделение',exact=True).click()
 page.get_by_label('Подразделение 3',exact=True).fill('Подразделение В')
 matrix.get_by_role('button',name='Отметить всю строку',exact=True).nth(2).click()
 expect(page.get_by_label('Подразделение 3 — должность 4',exact=True)).to_be_checked()
 page.get_by_label('Альбомная страница для матрицы',exact=False).check()
 page.locator('#stu-save').click();expect(page.locator('#stu-status')).to_have_text('Черновик сохранён')
 page.reload();matrix=open_section('5 ОТВЕТСТВЕННОСТЬ')
 expect(page.get_by_label('Подразделение 3',exact=True)).to_have_value('Подразделение В')
 expect(page.get_by_label('Подразделение 3 — должность 4',exact=True)).to_be_checked()
 matrix.get_by_role('button',name='Отметить всю строку',exact=True).nth(0).click()
 page.locator('#stu-save').click();expect(page.locator('#stu-status')).to_have_text('Черновик сохранён')
 # A stale save cannot overwrite another browser tab's changes.
 other=browser.new_page();other.goto(url+'/stu/'+id)
 page.get_by_label('Наименование СТУ',exact=True).fill('Стандарт для браузерной проверки')
 page.locator('#stu-save').click();expect(page.locator('#stu-status')).to_have_text('Черновик сохранён')
 other.get_by_label('Наименование СТУ',exact=True).fill('Конфликтующая вкладка');other.locator('#stu-save').click()
 expect(other.locator('#stu-status')).to_contain_text('другой вкладке')
 other.on('dialog',lambda dialog:dialog.accept());other.close()
 with page.expect_download(timeout=60000) as pending:page.locator('#stu-export').click()
 pending.value.save_as('/tmp/stu-browser.docx')
 # Edition 1 hides and omits the change register, while retaining draft entries.
 page.get_by_label('Номер редакции',exact=True).fill('1')
 expect(page.locator('summary').get_by_text('ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ',exact=True)).to_be_hidden()
 with page.expect_download(timeout=60000) as pending:page.locator('#stu-export').click()
 pending.value.save_as('/tmp/stu-browser-first.docx')
 page.locator('#theme').click();page.screenshot(path='/tmp/stu-editor-dark.png')
 page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 assert not errors,errors
 browser.close()
print('STU UI passed: editable roles/departments, row marks, save/reload, stale tab protection, DOCX, first edition, theme and mobile; no JS errors')
