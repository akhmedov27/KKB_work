"""Read-only browser checks against two synthetic confirmed test datasets."""
import os
from playwright.sync_api import sync_playwright, expect

url = os.environ['QMS_TEST_URL']
before = os.environ.get('QMS_BEFORE_ID', '1')
after = os.environ.get('QMS_AFTER_ID', '2')
with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('QMS_CHROMIUM_PATH'):
        options['executable_path'] = os.environ['QMS_CHROMIUM_PATH']
    browser = p.chromium.launch(**options)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url + '/modules/incidents')
    page.get_by_role('link', name='Сравнить две выгрузки', exact=True).click()
    page.locator('#before_id').select_option(before)
    page.locator('#after_id').select_option(after)
    page.get_by_role('button', name='Сравнить выгрузки', exact=True).click()
    for kind in ['added', 'missing', 'changed', 'unchanged']:
        expect(page.locator('#count-' + kind)).to_have_text('1')
    expect(page.get_by_text('Диапазоны дат различаются.', exact=False)).to_be_visible()
    page.locator('summary').filter(has_text='Статус').click()
    expect(page.get_by_text('Стало: Закрыто', exact=True)).to_be_visible()
    page.screenshot(path='/tmp/incident-comparison.png', full_page=True)
    with page.expect_download() as download:
        page.locator('#comparison-export').click()
    download.value.save_as('/tmp/incident-comparison.xlsx')
    page.get_by_role('link', name='Отсутствуют в новом наборе: 1', exact=True).click()
    expect(page.get_by_role('cell', name='C', exact=True)).to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors, errors
    browser.close()
print('Snapshot comparison UI passed: categories, before/after fields, warning, download, pagination links, mobile; no JavaScript errors')
