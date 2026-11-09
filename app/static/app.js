const theme = localStorage.getItem('qms-theme');
if (theme === 'dark') document.documentElement.dataset.theme = 'dark';
document.querySelector('#theme').addEventListener('click', () => {
  const value = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = value;
  localStorage.setItem('qms-theme', value);
});
document.body.addEventListener('htmx:beforeRequest', e => {
  if (e.detail.elt.id === 'chat-form') e.detail.elt.querySelector('button').disabled = true;
});
document.body.addEventListener('htmx:afterRequest', e => {
  if (e.detail.elt.id !== 'chat-form') return;
  e.detail.elt.querySelector('button').disabled = false;
  const error = document.querySelector('#chat-error');
  if (e.detail.successful) {
    document.querySelector('.empty')?.remove();
    e.detail.elt.reset(); error.textContent = '';
    const messages = document.querySelector('#messages'); messages.scrollTop = messages.scrollHeight;
  } else {
    try { error.textContent = JSON.parse(e.detail.xhr.responseText).detail; }
    catch { error.textContent = 'Не удалось отправить запрос. Проверьте соединение с приложением.'; }
  }
});
const upload = document.querySelector('#upload-form');
if (upload) upload.addEventListener('submit', async e => {
  e.preventDefault();
  const button = upload.querySelector('button'), result = document.querySelector('#upload-result');
  button.disabled = true;
  try {
    const response = await fetch('/uploads', {method: 'POST', body: new FormData(upload)});
    const data = await response.json(); result.textContent = response.ok ? data.message : data.detail;
    if (response.ok) { upload.reset(); const link = document.createElement('a'); link.href = location.pathname; link.textContent = ' Обновить список'; result.append(link); }
  } catch { result.textContent = 'Не удалось загрузить файл. Проверьте соединение с приложением.'; }
  finally { button.disabled = false; }
});
