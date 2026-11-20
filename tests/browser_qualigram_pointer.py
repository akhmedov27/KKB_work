"""Pointer interactions on an isolated server seeded with terminal_diagram()."""
import os,json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
url=os.environ['QMS_TEST_URL'];draft=os.environ.get('QMS_STU_ID','1')
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path=os.environ.get('QMS_CHROMIUM_PATH'))
 page=browser.new_page(viewport={'width':1600,'height':1100});errors=[];external=[]
 page.on('pageerror',lambda error:errors.append(str(error)))
 page.on('request',lambda r:external.append(r.url) if r.url.startswith(('http://','https://')) and not r.url.startswith(url) else None)
 page.goto(url+'/stu/'+draft);pid=json.loads(page.locator('#stu-data').text_content())['content']['process_ids'][0]
 page.goto(url+f'/stu/{draft}/qualigrams/{pid}')
 paper=page.locator('#q-paper');nodes=paper.locator('[data-node-id]');edges=paper.locator('[data-edge-id]')
 def node(nid):return paper.locator(f'[data-node-id="{nid}"]')
 def field(name):return page.get_by_label(name,exact=True)
 def geom():return {name:float(field(label).input_value()) for name,label in [('x','X'),('y','Y'),('width','Ширина'),('height','Высота')]}
 def settle():page.wait_for_timeout(450)
 def drag(locator,dx,dy,keys=(),first=None):
  locator.scroll_into_view_if_needed();box=locator.bounding_box();x=box['x']+box['width']/2;y=box['y']+box['height']/2
  for key in keys:page.keyboard.down(key)
  page.mouse.move(x,y);page.mouse.down()
  if first:page.mouse.move(x+first[0],y+first[1],steps=3)
  page.mouse.move(x+dx,y+dy,steps=5);page.mouse.up()
  for key in reversed(keys):page.keyboard.up(key)
  settle()
 def select():node('n').click(position={'x':80,'y':40})
 expect(nodes).to_have_count(3);select();original=geom()
 expect(node('n').locator('[data-q-handle]')).to_have_count(8)
 drag(node('n').locator('[data-q-handle="e"]'),45,30)
 resized=geom();assert resized['width']>original['width'] and resized['height']==original['height'] and resized['x']==original['x']
 page.locator('#q-undo').click();assert geom()==original
 page.locator('#q-redo').click();assert geom()==resized
 # Corner handle adjusts both dimensions but fixes the opposite bottom/right sides.
 drag(node('n').locator('[data-q-handle="nw"]'),-20,-15)
 corner=geom();assert corner['width']>resized['width'] and corner['height']>resized['height']
 assert corner['x']+corner['width']==resized['x']+resized['width']
 page.locator('#q-undo').click();page.locator('#q-undo').click();settle();assert geom()==original
 # A click with Ctrl creates no copy. Drag creates a deep copy, without links.
 node('n').click(position={'x':80,'y':40},modifiers=['Control']);expect(nodes).to_have_count(3)
 drag(node('n'),100,50,keys=['Control']);expect(nodes).to_have_count(4);expect(edges).to_have_count(2)
 copied=paper.locator('[data-node-id].q-selected');copy_id=copied.get_attribute('data-node-id');assert copy_id!='n'
 expect(field('Текст')).to_have_value('Одно действие');copy_geom=geom();assert copy_geom['width']==original['width']
 page.locator('#q-undo').click();expect(nodes).to_have_count(3);assert geom()==original
 page.locator('#q-redo').click();expect(nodes).to_have_count(4);assert geom()==copy_geom
 page.locator('#q-undo').click();settle()
 # Shift locks the initially dominant direction even if the other delta later grows.
 drag(node('n'),55,90,keys=['Shift'],first=(20,2));assert geom()['y']==original['y'] and geom()['x']>original['x']
 page.locator('#q-undo').click();settle();assert geom()==original
 drag(node('n'),90,55,keys=['Shift'],first=(2,20));assert geom()['x']==original['x'] and geom()['y']>original['y']
 page.locator('#q-undo').click();settle();assert geom()==original
 drag(node('n'),90,70,keys=['Control','Shift'],first=(20,2));expect(nodes).to_have_count(4);assert geom()['y']==original['y']
 page.locator('#q-undo').click();settle();expect(nodes).to_have_count(3)
 # Direct lane editing, undo/redo, and persistence.
 header=paper.locator('[data-lane-id="a"]');header.dblclick();inline=page.locator('.q-inline-editor textarea');expect(inline).to_be_visible()
 inline.fill('Заведующий отделением');inline.press('Enter');settle();expect(header).to_contain_text('Заведующий отделением')
 page.locator('#q-undo').click();settle();expect(header).to_contain_text('Руководитель')
 page.locator('#q-redo').click();settle();expect(header).to_contain_text('Заведующий отделением')
 # Native one-line centering and external terminal captions are in the preview.
 expect(node('n').locator('text')).to_have_count(1);expect(node('n').locator('text')).to_have_attribute('text-anchor','middle')
 expect(node('s').locator('circle')).to_have_attribute('fill','#CCFFCC');expect(node('e').locator('circle')).to_have_attribute('fill','#FFCCFF')
 select();page.screenshot(path='/tmp/qualigram-pointer-ui.png',full_page=True)
 page.get_by_role('button',name='Сохранить схему',exact=True).click();expect(page.locator('#q-status')).to_have_text('Схема сохранена')
 page.reload();expect(nodes).to_have_count(3);expect(header).to_contain_text('Заведующий отделением');expect(page.locator('#q-undo')).to_be_disabled()
 for label,ext in [('PNG','png'),('Visio 2007 · VDX','vdx')]:
  with page.expect_download() as download:page.get_by_role('button',name=label,exact=True).click()
  download.value.save_as('/tmp/qualigram-pointer.'+ext)
 assert Path('/tmp/qualigram-pointer.png').read_bytes().startswith(b'\x89PNG')
 assert 'Окончание процесса' in Path('/tmp/qualigram-pointer.vdx').read_text()
 response=page.request.get(url+f'/stu/{draft}/export.docx');assert response.status==200;Path('/tmp/qualigram-pointer.docx').write_bytes(response.body())
 page.locator('#theme').click();page.set_viewport_size({'width':390,'height':850});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
 assert not errors,errors
 assert not external,external
 browser.close();print('PASS: 8 handles, resizing and undo, Ctrl-copy/no click copy, Shift axis lock, Ctrl+Shift, lane edit, terminal circles, centering, persistence, PNG/VDX/DOCX, dark/mobile, no external requests')
