"""Read-only browser acceptance on a confirmed synthetic 2026 incident dataset."""
import os
from playwright.sync_api import sync_playwright, expect

url=os.environ['QMS_TEST_URL']
with sync_playwright() as p:
    options={'headless':True}
    if os.environ.get('QMS_CHROMIUM_PATH'): options['executable_path']=os.environ['QMS_CHROMIUM_PATH']
    browser=p.chromium.launch(**options)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:external.append(request.url) if request.url.startswith(('http://','https://')) and not request.url.startswith(url) else None)
    page.goto(url+'/modules/incidents?batch_id=1')
    if page.locator('#theme').get_attribute('aria-pressed')!='true':page.locator('#theme').click()
    assert page.locator('#inc-from').evaluate("el=>getComputedStyle(el).colorScheme")=='dark'
    page.locator('#inc-from').fill('2026-01-01')
    page.locator('#inc-from').scroll_into_view_if_needed()
    page.screenshot(path='/tmp/qms-date-dark.png')
    rect=page.locator('#inc-from').bounding_box()
    page.mouse.click(rect['x']+rect['width']-15,rect['y']+rect['height']/2)
    page.screenshot(path='/tmp/qms-calendar-dark.png')
    page.keyboard.press('Escape')
    page.locator('#theme').click()
    assert page.locator('#inc-from').evaluate("el=>getComputedStyle(el).colorScheme")=='light'
    page.locator('#theme').click()
    page.locator('#incident-period-report').click()
    page.locator('#report-kind').select_option('quarter')
    page.locator('#report-year').fill('2026')
    page.locator('#report-quarter').select_option('3')
    page.get_by_role('button',name='Сформировать предпросмотр').click()
    expect(page.locator('#report-total')).to_have_text('1727')
    expect(page.locator('#report-previous')).to_have_text('1846')
    page.locator('#report-comment').fill('Тестовый комментарий для отчёта. Требуется проверка полноты выгрузки.')
    with page.expect_download(timeout=60000) as pending:page.locator('#download-period-docx').click()
    pending.value.save_as('/tmp/qms-incident-period-report.docx')
    expect(page.locator('#report-comment')).to_have_value('Тестовый комментарий для отчёта. Требуется проверка полноты выгрузки.')
    with page.expect_download() as pending:page.locator('#period-report-excel').click()
    pending.value.save_as('/tmp/qms-incident-period-report.xlsx')
    page.locator('#report-kind').select_option('month');page.locator('#report-month').select_option('2')
    page.locator('#report-year').fill('2000')
    page.get_by_role('button',name='Сформировать предпросмотр').click()
    expect(page.locator('#report-total')).to_have_text('0')
    expect(page.locator('#report-comment')).to_have_value('')
    with page.expect_download() as pending:page.locator('#download-period-docx').click()
    pending.value.save_as('/tmp/qms-incident-empty-report.docx')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors,errors
    assert not external,external
    browser.close()
print('Report UI passed: dark/light calendar, quarterly counts 1727/1846, DOCX with comment, XLSX, empty period, mobile; no JS errors or external requests')
