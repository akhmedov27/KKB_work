const themeButton = document.querySelector('#theme');
function updateThemeButton() {
  const dark = document.documentElement.dataset.theme === 'dark';
  themeButton.setAttribute('aria-pressed', String(dark));
  themeButton.textContent = dark ? 'Светлая тема' : 'Тёмная тема';
}
updateThemeButton();
themeButton.addEventListener('click', () => {
  const value = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = value;
  try { localStorage.setItem('qms-theme', value); } catch { /* Session-only theme. */ }
  updateThemeButton();
});

const menuButton = document.querySelector('#menu-toggle');
function closeMenu() {
  document.body.classList.remove('menu-open');
  menuButton.setAttribute('aria-expanded', 'false');
  menuButton.textContent = 'Открыть меню';
}
menuButton.addEventListener('click', () => {
  const open = document.body.classList.toggle('menu-open');
  menuButton.setAttribute('aria-expanded', String(open));
  menuButton.textContent = open ? 'Закрыть меню' : 'Открыть меню';
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.body.classList.contains('menu-open')) {
    closeMenu(); menuButton.focus();
  }
});
window.matchMedia('(max-width: 700px)').addEventListener('change', closeMenu);

const chat = document.querySelector('#chat-form');
const messages = document.querySelector('#messages');
if (messages) messages.scrollTop = messages.scrollHeight;
function chatBusy(busy) {
  chat.setAttribute('aria-busy', String(busy));
  for (const field of chat.querySelectorAll('textarea')) field.readOnly = busy;
  const consent = chat.querySelector('[name=cloud_consent]');
  if (consent) consent.disabled = busy;
  chat.querySelector('button').disabled = busy;
  chat.querySelector('button').textContent = busy ? 'Отправка…' : 'Отправить ↑';
  document.querySelector('#chat-status').textContent = busy ? 'Ожидаем ответ выбранного провайдера…' : '';
}
document.body.addEventListener('htmx:beforeRequest', e => {
  if (e.detail.elt.id === 'chat-form') {
    document.querySelector('#chat-error').textContent = '';
    chatBusy(true);
  }
});
document.body.addEventListener('htmx:afterRequest', e => {
  if (e.detail.elt.id !== 'chat-form') return;
  chatBusy(false);
  const consent = chat.querySelector('[name=cloud_consent]');
  if (consent) consent.checked = false;
  const error = document.querySelector('#chat-error');
  if (e.detail.successful) {
    document.querySelector('.empty')?.remove();
    chat.reset(); error.textContent = '';
    messages.scrollTop = messages.scrollHeight;
    document.querySelector('#message').focus();
  } else {
    try { error.textContent = JSON.parse(e.detail.xhr.responseText).detail; }
    catch { error.textContent = 'Не удалось подтвердить результат. Обновите историю перед повторной отправкой: предыдущий запрос мог быть выполнен.'; }
  }
});
const upload = document.querySelector('#upload-form');
if (upload) upload.addEventListener('submit', async e => {
  e.preventDefault();
  const button = upload.querySelector('button'), result = document.querySelector('#upload-result');
  const file = upload.querySelector('input').files[0];
  result.classList.remove('error');
  if (!file) return;
  if (!/\.(docx|xlsx|pdf)$/i.test(file.name) || file.size === 0 || file.size > Number(upload.dataset.maxBytes)) {
    result.textContent = 'Выберите непустой DOCX, XLSX или PDF в пределах указанного лимита.';
    result.classList.add('error'); return;
  }
  button.disabled = true; button.textContent = 'Загрузка…';
  upload.setAttribute('aria-busy', 'true'); result.textContent = 'Сохраняем файл и извлекаем текст локально…';
  try {
    const response = await fetch('/uploads', {method: 'POST', body: new FormData(upload), signal: AbortSignal.timeout(60000)});
    const data = await response.json(); result.textContent = response.ok ? data.message : data.detail;
    result.classList.toggle('error', !response.ok || data.status === 'error');
    if (response.ok) {
      upload.reset();
      const link = document.createElement('a'); link.href = location.pathname; link.textContent = ' Обновить список'; result.append(link);
      const detail = document.createElement('a'); detail.href = data.url; detail.textContent = ' Открыть документ →'; result.append(detail);
    }
  } catch {
    result.textContent = 'Не удалось подтвердить загрузку. Обновите список перед повторной отправкой.';
    result.classList.add('error');
  } finally {
    button.disabled = false; button.textContent = 'Загрузить локально'; upload.setAttribute('aria-busy', 'false');
  }
});
const newConversation = document.querySelector('#new-conversation');
if (newConversation) {
  const title = newConversation.querySelector('input');
  title.addEventListener('input', () => title.setCustomValidity(''));
  newConversation.addEventListener('submit', e => {
    if (!title.value.trim()) {
      e.preventDefault(); title.setCustomValidity('Введите название диалога.'); title.reportValidity();
    }
  });
}

for (const form of document.querySelectorAll('.extract-form')) {
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const button = form.querySelector('button'), result = form.querySelector('.extract-result');
    const label = button.textContent;
    button.disabled = true; button.textContent = 'Обработка…'; form.setAttribute('aria-busy', 'true');
    result.textContent = 'Извлекаем текст локально. Это может занять до 20 секунд.';
    try {
      const response = await fetch(form.action, {method: 'POST', signal: AbortSignal.timeout(60000)});
      const data = await response.json();
      if (response.ok) { location.reload(); return; }
      result.textContent = data.detail;
    } catch {
      result.textContent = 'Не удалось подтвердить обработку. Обновите страницу перед повторной попыткой.';
    } finally {
      button.disabled = false; button.textContent = label; form.setAttribute('aria-busy', 'false');
    }
  });
}

const metadataForm = document.querySelector('#metadata-form');
if (metadataForm) metadataForm.addEventListener('submit', async e => {
  e.preventDefault();
  const button = metadataForm.querySelector('button'), result = document.querySelector('#metadata-result');
  button.disabled = true; result.textContent = 'Сохраняем реквизиты…'; metadataForm.setAttribute('aria-busy', 'true');
  try {
    const response = await fetch(metadataForm.action, {method: 'POST', body: new FormData(metadataForm)});
    const data = await response.json();
    if (response.ok) { location.hash = 'document-metadata'; location.reload(); return; }
    result.textContent = data.detail;
  } catch { result.textContent = 'Не удалось подтвердить сохранение. Проверьте соединение и повторите попытку.'; }
  finally { button.disabled = false; metadataForm.setAttribute('aria-busy', 'false'); }
});

for (const form of document.querySelectorAll('.incident-form')) {
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const button = form.querySelector('button[type=submit]'), result = form.querySelector('.incident-result');
    button.disabled = true; form.setAttribute('aria-busy', 'true'); result.classList.remove('error');
    result.textContent = 'Проверяем и сохраняем данные локально…';
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), signal: AbortSignal.timeout(90000)});
      if (response.ok && response.redirected) { location.href = response.url; return; }
      const data = await response.json(); result.textContent = data.detail || 'Не удалось завершить операцию.'; result.classList.add('error');
    } catch { result.textContent = 'Не удалось подтвердить результат. Обновите страницу проверки перед повторной отправкой.'; result.classList.add('error'); }
    finally { button.disabled = false; form.setAttribute('aria-busy', 'false'); }
  });
}
const incidentFilters = document.querySelector('#incident-filters');
if (incidentFilters) incidentFilters.addEventListener('submit', e => {
  for (const [startName, endName] of [['date_from','date_to'], ['compare_from','compare_to']]) {
    const start = incidentFilters.elements[startName], end = incidentFilters.elements[endName];
    end.setCustomValidity('');
    if ((start.value && end.value && start.value > end.value) || (startName === 'compare_from' && Boolean(start.value) !== Boolean(end.value))) {
      e.preventDefault(); end.setCustomValidity('Укажите обе даты сравнения; начало периода не должно быть позже окончания.'); end.reportValidity();
    }
    end.addEventListener('input', () => end.setCustomValidity(''), {once: true});
    start.addEventListener('input', () => end.setCustomValidity(''), {once: true});
  }
});
