"""Use an isolated server seeded with categories() from test_incident_filters."""
import os
from playwright.sync_api import sync_playwright,expect
url=os.environ['QMS_TEST_URL']
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path=os.environ.get('QMS_CHROMIUM_PATH'))
 page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
 page.on('pageerror',lambda error:errors.append(str(error)))
 page.goto(url+'/modules/incidents?batch_id=1')
 group=page.locator('#filter-group_name');subgroup=page.locator('#filter-subgroup')
 expect(page.locator('#filter-event_name')).to_have_count(0);expect(page.locator('#filter-root_cause')).to_have_count(0)
 def set_group(name):
  group.fill(name);group.press('Tab');expect(subgroup).to_be_enabled()
  expected={'Безопасность':{'','__empty__','Падения','Травмы'},'Лекарства':{'','Назначение','Травмы'},'__empty__':{'','__empty__'}}
  if name in expected:expect(subgroup.locator('option')).to_have_count(len(expected[name]))
 def values():return set(subgroup.locator('option').evaluate_all('(nodes)=>nodes.map(n=>n.value)'))
 set_group('Безопасность');assert values()=={'','__empty__','Падения','Травмы'}
 subgroup.select_option('Падения');set_group('Лекарства');expect(subgroup).to_have_value('');assert values()=={'','Назначение','Травмы'}
 expect(page.locator('#subgroup-status')).to_contain_text('сброшена')
 subgroup.select_option('Травмы');set_group('Безопасность');expect(subgroup).to_have_value('Травмы')
 set_group('');expect(subgroup.locator('option')).to_have_count(6);assert 'Назначение' in values()
 set_group('__empty__');subgroup.select_option('__empty__');page.locator('#incident-filters button[type="submit"]').click()
 expect(page.locator('#incident-total')).to_have_text('1')
 page.reload();expect(subgroup).to_have_value('__empty__')
 set_group('Лекарства');page.locator('#incident-filters button[type="submit"]').click();expect(page.locator('#incident-total')).to_have_text('2')
 with page.expect_download():page.locator('#incident-export').click()
 # Rapid parent changes must leave the last group's options visible.
 group.fill('Безопасность');group.fill('Лекарства');group.press('Tab');expect(subgroup).to_be_enabled()
 expect(subgroup.locator('option')).to_have_count(3);assert values()=={'','Назначение','Травмы'}
 page.screenshot(path='/tmp/incident-dependent-filters.png',full_page=False)
 page.goto(url+'/modules/incidents?batch_id=1&event_name=Падение&root_cause=R1')
 expect(page.locator('[data-chart-slice]')).to_have_count(2)
 page.get_by_role('button',name='Снять ограничение',exact=True).first.click();expect(page.locator('[data-chart-slice]')).to_have_count(1)
 page.get_by_role('button',name='Снять ограничение',exact=True).click();expect(page.locator('[data-chart-slice]')).to_have_count(0)
 expect(page.locator('#incident-total')).to_have_text('9')
 page.set_viewport_size({'width':390,'height':850});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
 assert not errors,errors
 browser.close()
 # No JavaScript: server still rejects an unrelated subgroup and renders valid options.
 context=p.chromium.launch(headless=True,executable_path=os.environ.get('QMS_CHROMIUM_PATH'))
 nojs=context.new_page(java_script_enabled=False)
 nojs.goto(url+'/modules/incidents?batch_id=1&group_name=Лекарства&subgroup=Падения')
 expect(nojs.locator('#incident-total')).to_have_text('2');expect(nojs.locator('#filter-subgroup')).to_have_value('')
 context.close()
 print('PASS: removed controls, dependent subgroups, reset/preserve, reload, empty group, Excel, rapid change, chart slice reset, mobile and no-JS fallback')
