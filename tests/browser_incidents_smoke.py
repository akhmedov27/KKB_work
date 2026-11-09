"""Run only on a disposable server with synthetic XLSX. No AI calls."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

url = os.environ['QMS_TEST_URL']
source = Path(os.environ['QMS_INCIDENT_XLSX'])
expected = os.environ.get('QMS_EXPECT_UNIQUE')
with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('QMS_CHROMIUM_PATH'):
        options['executable_path'] = os.environ['QMS_CHROMIUM_PATH']
    browser = p.chromium.launch(**options)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url + '/modules/incidents')
    page.locator('details.incident-upload').evaluate('(el) => el.open = true')
    page.locator('#incident-file').set_input_files(source)
    page.get_by_role('button', name='Загрузить и выбрать столбцы').click()
    expect(page.locator('#map-external_id')).to_have_value('2')
    expect(page.locator('#map-occurred_on')).to_have_value('3')
    expect(page.locator('#map-department')).to_have_value('14')
    expect(page.locator('#map-registered_on')).to_have_value('6')
    page.get_by_role('button', name='Проверить данные').click()
    expect(page.locator('h1')).to_have_text('Проверка перед импортом', timeout=60000)
    expect(page.locator('#count-policy')).to_have_value('unique')
    page.get_by_role('button', name='Подтвердить импорт').click()
    expect(page.locator('#incident-total')).to_be_visible(timeout=60000)
    if expected:
        expect(page.locator('#incident-total')).to_have_text(expected)
    page.locator('#inc-from').fill('2026-01-01')
    page.locator('#inc-to').fill('2026-12-31')
    page.get_by_role('button', name='Рассчитать', exact=True).click()
    expect(page.locator('#inc-from')).to_have_value('2026-01-01')
    print('Filtered 2026 count:', page.locator('#incident-total').inner_text())
    with page.expect_download(timeout=60000) as pending:
        page.locator('#incident-export').click()
    pending.value.save_as('/tmp/incident-statistics-browser.xlsx')
    page.screenshot(path='/tmp/incident-dashboard.png', full_page=False)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors, errors
    print('Browser passed: real XLSX upload, mapping B/C/F/N, preview, unique import, period filters, export, mobile width; no JS errors')
    browser.close()
