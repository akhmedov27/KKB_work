// Alias lookup stays on this server; chips always contain full source names.
const picker = document.querySelector('.department-picker');
if (picker) {
  const input = picker.querySelector('#department-search');
  const list = picker.querySelector('#department-results');
  const selected = picker.querySelector('#selected-departments');
  const status = picker.querySelector('#department-search-status');
  input.removeAttribute('name');
  let timer, controller, items = [], active = -1, sequence = 0;
  function close() {
    list.hidden = true; input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant'); active = -1;
  }
  function dismiss() { sequence++; controller?.abort(); clearTimeout(timer); close(); }
  function add(item) {
    if ([...selected.querySelectorAll('input')].some(el => el.value === item.value)) {
      status.textContent = 'Это отделение уже выбрано.';
    } else {
      const chip = document.createElement('span'); chip.className = 'department-chip';
      const text = document.createElement('span'); text.textContent = item.label;
      const hidden = document.createElement('input'); hidden.type = 'hidden'; hidden.name = 'departments'; hidden.value = item.value;
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×';
      remove.setAttribute('aria-label', `Убрать ${item.label}`);
      chip.append(text, hidden, remove); selected.append(chip);
      status.textContent = item.present ? `Добавлено: ${item.label}` : `Добавлено: ${item.label}. В этом наборе записей нет.`;
    }
    input.value = ''; sequence++; controller?.abort(); close(); input.focus();
  }
  selected.addEventListener('click', e => {
    const button = e.target.closest('button');
    if (button) { button.closest('.department-chip').remove(); input.focus(); status.textContent = 'Отделение убрано из выборки.'; }
  });
  async function search() {
    const query = input.value.trim(), current = ++sequence;
    controller?.abort(); close();
    if (!query) return;
    controller = new AbortController(); status.textContent = 'Ищем отделения…';
    try {
      const url = '/incidents/departments?' + new URLSearchParams({batch_id: picker.dataset.batchId, q: query});
      const response = await fetch(url, {signal: controller.signal});
      if (!response.ok) throw new Error('lookup');
      const data = await response.json();
      if (current !== sequence || input.value.trim() !== query) return;
      items = data.items; list.replaceChildren();
      items.forEach((item, index) => {
        const option = document.createElement('li'); option.id = `department-option-${index}`;
        option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false');
        const button = document.createElement('button'); button.type = 'button'; button.tabIndex = -1;
        button.textContent = item.label + (item.present ? '' : ' — в наборе нет записей');
        button.addEventListener('click', () => add(item)); option.append(button); list.append(option);
      });
      list.hidden = !items.length; input.setAttribute('aria-expanded', String(Boolean(items.length)));
      status.textContent = items.length ? `Найдено: ${items.length}. Выберите полное название.` : 'Не найдено. Попробуйте полное название; неизвестные варианты автоматически не объединяются.';
    } catch (error) {
      if (error.name !== 'AbortError' && current === sequence) status.textContent = 'Не удалось получить подсказки. Проверьте соединение с приложением.';
    }
  }
  input.addEventListener('input', () => {
    sequence++; controller?.abort(); close(); clearTimeout(timer);
    if (!input.value.trim()) { status.textContent = ''; return; }
    timer = setTimeout(search, 180);
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') { dismiss(); return; }
    if (e.key === 'Enter' && !list.hidden && (active >= 0 || items.length === 1)) {
      e.preventDefault(); add(items[active >= 0 ? active : 0]); return;
    }
    if (['ArrowDown','ArrowUp'].includes(e.key) && !list.hidden) {
      e.preventDefault(); active = (active + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      [...list.children].forEach((el,index) => el.setAttribute('aria-selected', String(index === active)));
      input.setAttribute('aria-activedescendant', list.children[active].id); list.children[active].scrollIntoView({block:'nearest'});
    }
  });
  document.addEventListener('click', e => { if (!picker.contains(e.target)) dismiss(); });
  input.form.addEventListener('submit', e => {
    if (!e.defaultPrevented && input.value.trim()) {
      e.preventDefault(); status.textContent = 'Выберите полное название из подсказок или очистите поле поиска.'; input.focus();
    }
  });
}
