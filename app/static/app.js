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
  chat.querySelector('button').disabled = busy;
  chat.querySelector('button').textContent = busy ? 'Отправка…' : 'Отправить ↑';
  document.querySelector('#chat-status').textContent = busy ? 'Ожидаем тестовый ответ…' : '';
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
  const error = document.querySelector('#chat-error');
  if (e.detail.successful) {
    document.querySelector('.empty')?.remove();
    chat.reset(); error.textContent = '';
    messages.scrollTop = messages.scrollHeight;
    document.querySelector('#message').focus();
  } else {
    try { error.textContent = JSON.parse(e.detail.xhr.responseText).detail; }
    catch { error.textContent = 'Не удалось отправить запрос. Проверьте соединение с приложением и повторите попытку.'; }
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
  upload.setAttribute('aria-busy', 'true'); result.textContent = 'Сохраняем файл на этом компьютере…';
  try {
    const response = await fetch('/uploads', {method: 'POST', body: new FormData(upload), signal: AbortSignal.timeout(60000)});
    const data = await response.json(); result.textContent = response.ok ? data.message : data.detail;
    result.classList.toggle('error', !response.ok);
    if (response.ok) {
      upload.reset();
      const link = document.createElement('a'); link.href = location.pathname; link.textContent = ' Обновить список'; result.append(link);
    }
  } catch {
    result.textContent = 'Не удалось подтвердить загрузку. Обновите список перед повторной отправкой.';
    result.classList.add('error');
  } finally {
    button.disabled = false; button.textContent = 'Загрузить локально'; upload.setAttribute('aria-busy', 'false');
  }
});
