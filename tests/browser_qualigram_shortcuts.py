"""Mutates/deletes only a seeded synthetic draft, on an isolated test server."""
import os,json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
url=os.environ['QMS_TEST_URL'];draft=os.environ.get('QMS_STU_ID','1')
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path=os.environ.get('QMS_CHROMIUM_PATH'))
 page=browser.new_page(viewport={'width':1600,'height':1100});errors=[];external=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('request',lambda r:external.append(r.url) if r.url.startswith(('http://','https://')) and not r.url.startswith(url) else None)
 page.goto(url+'/stu/'+draft);payload=json.loads(page.locator('#stu-data').text_content());pid=payload['content']['process_ids'][0]
 page.goto(url+f'/stu/{draft}/qualigrams/{pid}')
 nodes=page.locator('#q-paper [data-node-id]');edges=page.locator('#q-paper [data-edge-id]');paper=page.locator('#q-paper')
 expect(nodes).to_have_count(3);expect(page.locator('#q-undo')).to_be_disabled()
 def node(nid):return page.locator(f'#q-paper [data-node-id="{nid}"]')
 def edge(eid):return page.locator(f'#q-paper [data-edge-id="{eid}"]')
 node('n').click(position={'x':100,'y':50});expect(node('n')).to_have_class('q-selected');expect(node('n').locator('[data-q-selection]')).to_have_count(1)
 page.keyboard.press('ArrowRight');expect(page.get_by_label('X',exact=True)).to_have_value('41')
 page.keyboard.press('Shift+ArrowDown');expect(page.get_by_label('Y',exact=True)).to_have_value('330')
 page.keyboard.press('ArrowRight');expect(page.get_by_label('X',exact=True)).to_have_value('42')
 page.keyboard.press('Control+z');expect(page.get_by_label('X',exact=True)).to_have_value('40');expect(page.get_by_label('Y',exact=True)).to_have_value('320')
 page.keyboard.press('Control+y');expect(page.get_by_label('X',exact=True)).to_have_value('42')
 # Delete and arrows inside a text field remain text editing operations.
 text=page.get_by_label('Текст',exact=True);text.fill('Проверить заявку!');text.press('Home');text.press('Delete');text.press('ArrowLeft');expect(nodes).to_have_count(3)
 expect(page.get_by_label('X',exact=True)).to_have_value('42');paper.focus();page.keyboard.press('Control+z');expect(page.get_by_label('Текст',exact=True)).to_have_value('Проверить заявку')
 node('n').dblclick(position={'x':100,'y':50});inline=page.locator('.q-inline-editor textarea');expect(inline).to_be_visible();inline.fill('Первое действие\nВторое действие');inline.press('Control+Enter')
 expect(page.get_by_label('Текст',exact=True)).to_have_value('Первое действие\nВторое действие')
 node('n').dblclick(position={'x':100,'y':50});inline.fill('Отменить этот ввод');inline.press('Escape');expect(page.get_by_label('Текст',exact=True)).to_have_value('Первое действие\nВторое действие')
 page.keyboard.press('Control+z');expect(page.get_by_label('Текст',exact=True)).to_have_value('Проверить заявку')
 page.keyboard.press('Control+y');expect(page.get_by_label('Текст',exact=True)).to_have_value('Первое действие\nВторое действие')
 edge('e1').dblclick();expect(inline).to_be_visible();inline.fill('Получено');inline.press('Enter');expect(page.get_by_label('Подпись стрелки',exact=True)).to_have_value('Получено')
 expect(edge('e1')).to_have_class('q-selected');page.keyboard.press('Delete');expect(edges).to_have_count(1)
 page.keyboard.press('Control+z');expect(edges).to_have_count(2);expect(page.get_by_label('Подпись стрелки',exact=True)).to_have_value('Получено')
 node('n').click(position={'x':100,'y':50});page.keyboard.press('Delete');expect(nodes).to_have_count(2);expect(edges).to_have_count(0)
 page.keyboard.press('Control+z');expect(nodes).to_have_count(3);expect(edges).to_have_count(2)
 page.keyboard.press('Control+y');expect(nodes).to_have_count(2);page.keyboard.press('Control+z');expect(nodes).to_have_count(3)
 page.locator('#q-palette').get_by_role('button',name='И/ИЛИ',exact=True).click();expect(nodes).to_have_count(4)
 expect(page.locator('#q-redo')).to_be_disabled();expect(page.get_by_label('Ширина',exact=True)).to_have_value('64')
 hybrid=page.locator('#q-paper [data-node-id].q-selected');expect(hybrid).to_have_count(1);hybrid_id=hybrid.get_attribute('data-node-id')
 page.get_by_label('X',exact=True).fill('400');page.get_by_label('Y',exact=True).fill('800');paper.focus()
 expect(node(hybrid_id)).to_be_visible();x=float(page.get_by_label('X',exact=True).input_value());y=float(page.get_by_label('Y',exact=True).input_value())
 box=node(hybrid_id).bounding_box();page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down();page.mouse.move(box['x']+box['width']/2+60,box['y']+box['height']/2+50,steps=8);page.mouse.up()
 assert float(page.get_by_label('X',exact=True).input_value())>x
 page.locator('#q-undo').click();expect(page.get_by_label('X',exact=True)).to_have_value(str(int(x)));expect(page.get_by_label('Y',exact=True)).to_have_value(str(int(y)))
 page.locator('#q-redo').click();page.get_by_role('button',name='Сохранить схему',exact=True).click();expect(page.locator('#q-status')).to_have_text('Схема сохранена')
 page.locator('#q-undo').click();expect(page.locator('#q-status')).to_contain_text('несохранённые')
 page.locator('#q-redo').click();expect(page.locator('#q-status')).to_contain_text('сохранённая схема')
 page.screenshot(path='/tmp/qualigram-shortcuts-ui.png',full_page=False)
 page.reload();expect(nodes).to_have_count(4);expect(page.locator('#q-undo')).to_be_disabled();expect(page.locator('#q-redo')).to_be_disabled()
 assert any(n['kind']=='and_or' for n in json.loads(page.locator('#q-data').text_content())['diagram']['nodes'])
 for label,ext in [('PNG','png'),('Visio 2007 · VDX','vdx')]:
  with page.expect_download() as pending:page.get_by_role('button',name=label,exact=True).click()
  pending.value.save_as('/tmp/qualigram-shortcuts.'+ext)
 assert Path('/tmp/qualigram-shortcuts.png').read_bytes().startswith(b'\x89PNG')
 assert 'И/ИЛИ' in Path('/tmp/qualigram-shortcuts.vdx').read_text()
 page.locator('#theme').click();page.set_viewport_size({'width':390,'height':850});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
 page.goto(url+'/modules/stu');page.locator(f'a[href="/stu/{draft}/delete"]').click();expect(page.get_by_role('button',name='Удалить СТУ окончательно',exact=True)).to_be_visible()
 page.get_by_role('link',name='Отмена — вернуться к СТУ',exact=True).click();assert page.url.endswith('/stu/'+draft)
 page.goto(url+f'/stu/{draft}/delete');page.get_by_role('button',name='Удалить СТУ окончательно',exact=True).click();expect(page.locator(f'a[href="/stu/{draft}"]')).to_have_count(0)
 assert not errors,errors
 assert not external,external
 browser.close();print('PASS: selection, keys, native text editing, inline labels/cancel, undo/redo, cascade restore, branch, drag, save/reload, hybrid exports, dark/mobile and confirmed STU deletion')
