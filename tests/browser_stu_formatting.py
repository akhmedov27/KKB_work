"""Glossary/optional-date acceptance on a separate, seeded synthetic draft."""
import os
from playwright.sync_api import sync_playwright, expect
url=os.environ['QMS_TEST_URL'];id=os.environ.get('QMS_STU_ID','1')
with sync_playwright() as p:
 options={'headless':True}
 if os.environ.get('QMS_CHROMIUM_PATH'):options['executable_path']=os.environ['QMS_CHROMIUM_PATH']
 browser=p.chromium.launch(**options);page=browser.new_page(viewport={'width':1440,'height':1000})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(url+'/stu/'+id)
 order=page.get_by_label('Дата приказа (необязательно)',exact=True)
 order.fill('2026-11-11')
 page.get_by_role('button',name='Очистить дату',exact=True).first.click()
 expect(order).to_have_value('')
 section=page.locator('#stu-form details').filter(has=page.locator('summary').get_by_text('4 СОКРАЩЕНИЯ И ОБОЗНАЧЕНИЯ',exact=True))
 section.locator('summary').click()
 for name,meaning in [('ЯМ','Последнее сокращение'),('АД','Первое сокращение')]:
  section.get_by_role('button',name='Добавить строку',exact=True).nth(0).click()
  section.get_by_label('Сокращение',exact=True).last.fill(name)
  section.get_by_label('Расшифровка',exact=True).last.fill(meaning)
 for name,meaning in [('Явление','Последний термин'),('Анализ','Первый термин')]:
  section.get_by_role('button',name='Добавить строку',exact=True).nth(1).click()
  section.get_by_label('Термин',exact=True).last.fill(name)
  section.get_by_label('Определение',exact=True).last.fill(meaning)
 page.locator('#stu-save').click();expect(page.locator('#stu-status')).to_have_text('Черновик сохранён')
 page.reload();section.locator('summary').click()
 expect(section.get_by_label('Сокращение',exact=True)).to_have_count(2)
 expect(section.get_by_label('Термин',exact=True)).to_have_count(2)
 expect(order).to_have_value('')
 with page.expect_download(timeout=60000) as download:page.locator('#stu-export').click()
 download.value.save_as('/tmp/stu-formatting-browser.docx')
 page.locator('#theme').click();page.set_viewport_size({'width':390,'height':844})
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 assert not errors,errors
 browser.close()
print('STU formatting UI passed: optional/cleared date, glossary rows, persistence, DOCX, dark theme and mobile; no JS errors')
