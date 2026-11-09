"""Optional UI smoke checks; run against a server with disposable synthetic data."""
import os
from playwright.sync_api import sync_playwright, expect

def synthetic_pdf():
    # A valid one-page PDF built without optional document dependencies.
    stream = b'BT /F1 12 Tf 72 720 Td (Synthetic QMS-004 quality text) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    result = b'%PDF-1.4\n'
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += str(index).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    start = len(result)
    result += b'xref\n0 6\n0000000000 65535 f \n'
    result += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    result += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF'
    return result


url = os.environ.get('QMS_TEST_URL', 'http://127.0.0.1:8002')
with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('QMS_CHROMIUM_PATH'):
        options['executable_path'] = os.environ['QMS_CHROMIUM_PATH']
    browser = p.chromium.launch(**options)
    page = browser.new_page(viewport={'width': 1366, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    for route in ['knowledge', 'documents', 'incidents', 'risks', 'audits', 'reports', 'settings']:
        page.locator(f'nav a[href="/modules/{route}"]').click()
        expect(page.locator('nav [aria-current="page"]')).to_have_attribute('href', f'/modules/{route}')
    page.locator('#theme').click()
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
    expect(page.locator('#theme')).to_have_attribute('aria-pressed', 'true')
    page.locator('nav a[href="/"]').click()
    page.locator('#message').fill('Синтетическая проверка QMS-002')
    page.get_by_role('button', name='Отправить').click()
    expect(page.locator('.message.assistant').last).to_contain_text('MockProvider')
    expect(page.locator('#message')).to_be_focused()
    page.route('**/chat', lambda route: route.fulfill(status=503, content_type='application/json', body='{"detail":"Тестовая ошибка"}'))
    page.locator('#message').fill('Повторный запрос')
    page.get_by_role('button', name='Отправить').click()
    expect(page.locator('#chat-error')).to_have_text('Тестовая ошибка')
    expect(page.locator('#message')).to_have_value('Повторный запрос')
    expect(page.get_by_role('button', name='Отправить')).to_be_enabled()
    page.unroute('**/chat')
    first_url = page.url
    page.locator('#conversation-name').fill('Отдельный диалог QMS-003')
    page.get_by_role('button', name='Создать диалог').click()
    expect(page.locator('#conversation-title')).to_have_text('Отдельный диалог QMS-003')
    expect(page.locator('.message')).to_have_count(0)
    page.locator('#message').fill('Только во втором диалоге')
    page.get_by_role('button', name='Отправить').click()
    expect(page.locator('.message.assistant')).to_have_count(1)
    page.reload()
    expect(page.locator('#messages')).to_contain_text('Только во втором диалоге')
    page.goto(first_url)
    expect(page.locator('#messages')).not_to_contain_text('Только во втором диалоге')
    expect(page.locator('.message.assistant')).to_have_count(1)
    page.locator('nav a[href="/modules/knowledge"]').click()
    page.locator('#file').set_input_files({'name': 'bad.txt', 'mimeType': 'text/plain', 'buffer': b'synthetic'})
    page.get_by_role('button', name='Загрузить локально').click()
    expect(page.locator('#upload-result')).to_contain_text('Выберите непустой')
    page.locator('#file').set_input_files({'name': 'test-qms002.pdf', 'mimeType': 'application/pdf', 'buffer': synthetic_pdf()})
    page.get_by_role('button', name='Загрузить локально').click()
    page.get_by_role('link', name='Открыть документ').click()
    expect(page.locator('.extracted-text')).to_contain_text('Synthetic QMS-004 quality text')
    with page.expect_navigation():
        page.get_by_role('button', name='Повторить извлечение').click()
    expect(page.locator('.extracted-text')).to_contain_text('Synthetic QMS-004 quality text')
    page.get_by_role('link', name='К списку документов').click()
    expect(page.locator('tbody')).to_contain_text('test-qms002.pdf')
    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.locator('#sidebar-nav')).to_be_hidden()
    page.locator('#menu-toggle').click()
    expect(page.locator('#sidebar-nav')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('#sidebar-nav')).to_be_hidden()
    expect(page.locator('#menu-toggle')).to_be_focused()
    expect(page.locator('#theme')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.locator('#menu-toggle').click()
    page.locator('nav a[href="/modules/settings"]').click()
    expect(page.locator('#sidebar-nav')).to_be_hidden()
    page.goto(url + '/missing')
    page.get_by_role('link', name='Вернуться на главную').click()
    expect(page.locator('h1')).to_contain_text('Порядок в процессах')
    assert not errors, errors
    browser.close()
    # A restrictive browser profile must not disable the rest of the UI.
    browser = p.chromium.launch(**options)
    page = browser.new_page()
    page.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('blocked')}})")
    page.goto(url)
    page.locator('#theme').click()
    expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
    browser.close()
print('UI checks passed: navigation, theme, chat/error, uploads, mobile menu, 404, restricted storage, separate conversations, PDF text preview/reprocessing')
