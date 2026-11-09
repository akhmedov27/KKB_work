"""UI checks on an isolated copy of a confirmed synthetic incident dataset."""
import os
from playwright.sync_api import sync_playwright, expect

url=os.environ['QMS_TEST_URL']
OAR='Анестезиология-реанимация №2 (кардиореанимация)'
GHO='Гнойная хирургия'
with sync_playwright() as p:
    options={'headless':True}
    if os.environ.get('QMS_CHROMIUM_PATH'):options['executable_path']=os.environ['QMS_CHROMIUM_PATH']
    browser=p.chromium.launch(**options)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(url+'/modules/incidents')
    if os.environ.get('QMS_EXPECT_UNIQUE'):
        expect(page.locator('#incident-total')).to_have_text(os.environ['QMS_EXPECT_UNIQUE'])
    def choose(alias,full):
        search=page.locator('#department-search');search.fill(alias)
        expect(page.locator('#department-results [role=option]')).to_have_count(1)
        expect(page.locator('#department-results [role=option]')).to_contain_text(full)
        search.press('Enter')
        expect(page.locator('#selected-departments')).to_contain_text(full)
        expect(search).to_have_value('')
    choose('гхо',GHO);choose('ОАР №2',OAR)
    expect(page.locator('#selected-departments input')).to_have_count(2)
    page.locator('#inc-from').fill('2026-01-01');page.locator('#inc-to').fill('2026-12-31')
    for label in ['Отменено','Удалено']:
        page.locator(f'input[name="exclude_statuses"][value="{label}"]').check()
    page.get_by_text('Сравнить с другим периодом той же выборки',exact=True).click()
    page.locator('#compare-from').fill('2025-01-01');page.locator('#compare-to').fill('2025-12-31')
    page.get_by_text('Настройки Парето и повторяемости',exact=True).click()
    page.locator('#pareto-by').select_option('root_cause');page.locator('#min-repeat').fill('3')
    page.get_by_role('button',name='Рассчитать',exact=True).click()
    expect(page.locator('#selected-departments input')).to_have_count(2)
    expect(page.locator('#selected-departments')).to_contain_text(OAR)
    expect(page.locator('.pareto-svg')).to_be_visible()
    expect(page.get_by_role('heading',name='Сравнение отделений по двум периодам',exact=True)).to_be_visible()
    expect(page.get_by_role('heading',name='Квартальная динамика',exact=True)).to_be_visible()
    print('Filtered full-name departments count:',page.locator('#incident-total').inner_text())
    with page.expect_download(timeout=60000) as pending:page.locator('#incident-export').click()
    pending.value.save_as('/tmp/incident-analytics-expanded.xlsx')
    page.locator('#pareto-analysis').scroll_into_view_if_needed()
    page.screenshot(path='/tmp/incident-analytics-expanded.png',full_page=False)
    # Escape dismisses suggestions; selecting reference-only OAR 1 creates no data.
    search=page.locator('#department-search');search.fill('оар')
    expect(page.locator('#department-results')).to_be_visible();search.press('Escape')
    expect(page.locator('#department-results')).to_be_hidden()
    while page.locator('#selected-departments button').count():
        page.locator('#selected-departments button').first.click()
    choose('ОАР1','Отделение анестезиологии-реанимации №1')
    page.get_by_role('button',name='Рассчитать',exact=True).click()
    expect(page.locator('#incident-total')).to_have_text('0')
    expect(page.locator('#pareto-analysis')).to_contain_text('Парето не рассчитывается')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors,errors
    browser.close()
print('Expanded incident UI passed: aliases, full names, multiple departments, exclusions, comparison, Pareto, export, future unit, mobile; no JS errors')
