"""Cloud UI checks: intercept /chat in the browser; NEVER call a real provider API."""
import os
from playwright.sync_api import sync_playwright, expect

url = os.environ['QMS_TEST_URL']
label = os.environ.get('QMS_TEST_CLOUD_LABEL', 'DeepSeek')
with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('QMS_CHROMIUM_PATH'):
        options['executable_path'] = os.environ['QMS_CHROMIUM_PATH']
    browser = p.chromium.launch(**options)
    page = browser.new_page(viewport={'width': 1366, 'height': 900})
    errors, requests = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def chat_response(route):
        requests.append(route.request.post_data)
        if 'FORCE_ERROR' in (route.request.post_data or ''):
            route.fulfill(status=503, content_type='application/json', body='{"detail":"Тестовая ошибка подключения"}')
        else:
            route.fulfill(status=200, content_type='text/html; charset=utf-8', body='<article class="message assistant"><p>Синтетический ответ UI-теста</p></article>')
    page.route('**/chat', chat_response)
    page.goto(url)
    consent = page.locator('[name=cloud_consent]')
    expect(consent).to_be_visible()
    expect(page.locator('.cloud-consent')).to_contain_text(label)
    expect(page.locator('header')).to_contain_text(label)
    page.locator('#message').fill('Синтетический вопрос')
    page.get_by_role('button', name='Отправить').click()
    assert requests == []
    page.locator('.manual-context summary').click()
    page.locator('#fragment').fill('Синтетический фрагмент')
    consent.check()
    page.get_by_role('button', name='Отправить').click()
    expect(page.locator('.message.assistant').last).to_contain_text('Синтетический ответ UI-теста')
    expect(consent).not_to_be_checked()
    expect(page.locator('#fragment')).to_have_value('')
    assert len(requests) == 1 and 'cloud_consent=true' in requests[0]
    page.locator('#message').fill('FORCE_ERROR')
    page.locator('#fragment').fill('Не терять ввод')
    consent.check()
    page.get_by_role('button', name='Отправить').click()
    expect(page.locator('#chat-error')).to_contain_text('Тестовая ошибка подключения')
    expect(page.locator('#message')).to_have_value('FORCE_ERROR')
    expect(page.locator('#fragment')).to_have_value('Не терять ввод')
    expect(consent).not_to_be_checked()
    expect(page.get_by_role('button', name='Отправить')).to_be_enabled()
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors, errors
    browser.close()
print('Cloud UI checks passed with browser-intercepted test responses; no real cloud API request')
