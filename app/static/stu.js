(() => {
const source=document.querySelector('#stu-data');if(!source)return;
const initial=JSON.parse(source.textContent),state=initial.content,form=document.querySelector('#stu-form');
let version=initial.version,dirty=false,busy=false;
const status=document.querySelector('#stu-status'),errors=document.querySelector('#stu-errors');
function el(tag,text,attrs={}) {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;}
function changed(){dirty=true;status.textContent='Есть несохранённые изменения';}
function button(text,fn,parent){const b=el('button',text,{type:'button'});b.onclick=fn;parent.append(b);return b;}
function field(parent,label,obj,key,type='text'){
 const wrap=el('div'),id='stu-'+key+'-'+Math.random().toString(36).slice(2);wrap.append(el('label',label,{for:id}));
 let input;
 if(Array.isArray(type)){input=el('select');for(const choice of type)input.append(el('option',choice.label??choice,{value:choice.value??choice}));}
 else {input=el(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;}
 input.id=id;input.name=key;input.value=obj[key]??'';
 if(type==='number'){input.min='1';input.max='999';}
 if(type==='text'||type==='textarea')input.maxLength=key==='meaning'?5000:type==='textarea'?20000:500;
 input.addEventListener('input',()=>{obj[key]=type==='number'?Number(input.value):type==='date'?(input.value||null):Array.isArray(type)&&typeof obj[key]==='number'?Number(input.value):input.value;changed();if(key==='edition')updateEdition();});
 wrap.append(input);if(type==='date')button('Очистить дату',()=>{input.value='';obj[key]=null;changed();},wrap);parent.append(wrap);return input;
}
function section(title,open=false){const d=el('details',undefined,{class:'panel document-detail'});d.open=open;d.append(el('summary',title));const body=el('div',undefined,{class:'stu-section'});d.append(body);form.append(d);return body;}
function reorder(array,i,j){if(j<0||j>=array.length)return;[array[i],array[j]]=[array[j],array[i]];changed();}
function repeat(parent,key,fields,empty){
 const host=el('div');parent.append(host);
 function draw(){host.replaceChildren();state[key].forEach((row,i)=>{
  const card=el('div',undefined,{class:'stu-row'});card.append(el('h3','Строка '+(i+1)));const grid=el('div',undefined,{class:'metadata-grid'});
  fields.forEach(([k,label,type])=>field(grid,label,row,k,type));card.append(grid);
  if(key==='risks') {const rank=el('p','Ранг: '+row.probability*row.impact);card.append(rank);grid.addEventListener('input',()=>{rank.textContent='Ранг: '+row.probability*row.impact;});}
  const controls=el('div',undefined,{class:'stu-controls'});
  button('↑',()=>{reorder(state[key],i,i-1);draw();},controls).setAttribute('aria-label','Строка вверх');
  button('↓',()=>{reorder(state[key],i,i+1);draw();},controls).setAttribute('aria-label','Строка вниз');
  button('Удалить строку',()=>{if(confirm('Удалить эту строку с введёнными значениями?')){state[key].splice(i,1);changed();draw();}},controls);card.append(controls);host.append(card);
 });}
 button('Добавить строку',()=>{state[key].push({...empty});changed();draw();},parent);draw();
}
function names(parent,key,label){const host=el('div');parent.append(host);function draw(){host.replaceChildren();state[key].forEach((name,i)=>{const row=el('div',undefined,{class:'stu-row'});const holder={name};const input=field(row,label+' '+(i+1),holder,'name');input.addEventListener('input',()=>state[key][i]=holder.name);const controls=el('div',undefined,{class:'stu-controls'});button('↑',()=>{reorder(state[key],i,i-1);draw();},controls);button('↓',()=>{reorder(state[key],i,i+1);draw();},controls);button('Удалить',()=>{if(confirm('Удалить название?')){state[key].splice(i,1);changed();draw();}},controls);row.append(controls);host.append(row);});}button('Добавить '+label.toLowerCase(),()=>{state[key].push('');changed();draw();},parent);draw();}
let body=section('Реквизиты СТУ',true),grid=el('div',undefined,{class:'metadata-grid'});body.append(grid);
for(const [key,label,type] of [['number','Номер СТУ из реестра','text'],['title','Наименование СТУ','text'],['edition','Номер редакции','number'],['order_number','Номер приказа (можно оставить пустым)','text'],['order_date','Дата приказа (необязательно)','date'],['effective_date','Дата введения в действие (необязательно)','date']])field(grid,label,state,key,type);
body=section('Лист согласования');body.append(el('p','Подпись и дата остаются пустыми в Word.'));
repeat(body,'approvals',[['role','Ответственность',['Согласовал','Разработал']],['position','Должность','text'],['person','Фамилия, инициалы','text']],{role:'Разработал',position:'',person:''});
for(const [key,label] of [['annotation','Аннотация'],['purpose','1 НАЗНАЧЕНИЕ'],['scope','2 ОБЛАСТЬ ПРИМЕНЕНИЯ'],['references','3 НОРМАТИВНЫЕ ССЫЛКИ']])field(section(label),label,state,key,'textarea');
body=section('4 СОКРАЩЕНИЯ И ОБОЗНАЧЕНИЯ');
body.append(el('h3','Сокращения'));body.append(el('p','В Word: сокращение - расшифровка. При экспорте сокращения сортируются по алфавиту.'));
repeat(body,'abbreviation_rows',[['name','Сокращение','text'],['meaning','Расшифровка','textarea']],{name:'',meaning:''});
body.append(el('h3','Термины'));body.append(el('p','Термины выводятся после сокращений, в своём алфавитном порядке. Название термина будет жирным.'));
repeat(body,'term_rows',[['name','Термин','text'],['meaning','Определение','textarea']],{name:'',meaning:''});
if(state.abbreviations)field(body,'Ранее введённый текст (сохранён без изменений; можно перенести в строки выше)',state,'abbreviations','textarea');
body=section('5 ОТВЕТСТВЕННОСТЬ');field(body,'Кто несёт ответственность за разработку, внедрение и исполнение',state,'owner');
body.append(el('p','Ответственность за выполнение требований настоящего стандарта учреждения также возлагается на сотрудников подразделений в соответствии с таблицей 1 «Матрица ответственности».'));
const landscape=el('label'),box=el('input');box.type='checkbox';box.checked=state.matrix_landscape;box.onchange=()=>{state.matrix_landscape=box.checked;changed();};landscape.append(box,document.createTextNode(' Альбомная страница для матрицы (остальные страницы книжные)'));body.append(landscape);
const matrix=el('div');body.append(matrix);
function drawMatrix(){matrix.replaceChildren();const roles=el('div');roles.append(el('h3','Должности'));
 state.positions.forEach((name,i)=>{const row=el('div',undefined,{class:'stu-controls'}),input=el('input',undefined,{'aria-label':'Должность '+(i+1),maxlength:500});input.value=name;input.oninput=()=>{state.positions[i]=input.value;const th=matrix.querySelectorAll('th')[i+2];if(th)th.textContent=input.value;changed();};row.append(input);
 function move(j){if(j<0||j>=state.positions.length)return;reorder(state.positions,i,j);state.departments.forEach(r=>{[r.marks[i],r.marks[j]]=[r.marks[j],r.marks[i]];});drawMatrix();}
 button('←',()=>move(i-1),row);button('→',()=>move(i+1),row);button('Удалить должность',()=>{if(confirm('Удалить должность и её отметки во всех подразделениях?')){state.positions.splice(i,1);state.departments.forEach(r=>r.marks.splice(i,1));changed();drawMatrix();}},row);roles.append(row);
 });button('Добавить должность',()=>{if(state.positions.length>=20){alert('Не более 20 должностей. Для читаемости используйте альбомную страницу.');return;}state.positions.push('');state.departments.forEach(r=>r.marks.push(false));changed();drawMatrix();},roles);matrix.append(roles);
 const scroll=el('div',undefined,{class:'table-scroll'}),table=el('table'),head=el('tr');for(const title of ['№','Подразделение',...state.positions,'Действия'])head.append(el('th',title));table.append(head);
 state.departments.forEach((r,i)=>{const tr=el('tr');tr.append(el('td',i+1));const td=el('td'),name=el('input',undefined,{'aria-label':'Подразделение '+(i+1),maxlength:500});name.value=r.name;name.oninput=()=>{r.name=name.value;changed();};td.append(name);tr.append(td);
 r.marks.forEach((mark,j)=>{const cell=el('td'),check=el('input',undefined,{'aria-label':'Подразделение '+(i+1)+' — должность '+(j+1)});check.type='checkbox';check.checked=mark;check.onchange=()=>{r.marks[j]=check.checked;changed();};cell.append(check);tr.append(cell);});
 const c=el('td');button('Отметить всю строку',()=>{r.marks.fill(true);changed();drawMatrix();},c);button('Снять отметки',()=>{r.marks.fill(false);changed();drawMatrix();},c);button('↑',()=>{reorder(state.departments,i,i-1);drawMatrix();},c);button('↓',()=>{reorder(state.departments,i,i+1);drawMatrix();},c);button('Удалить подразделение',()=>{if(confirm('Удалить подразделение и его отметки?')){state.departments.splice(i,1);changed();drawMatrix();}},c);tr.append(c);table.append(tr);
 });scroll.append(table);matrix.append(scroll);button('Добавить подразделение',()=>{state.departments.push({name:'',marks:state.positions.map(()=>false)});changed();drawMatrix();},matrix);
 matrix.append(el('p','В Word отмеченные ячейки будут обозначены V. Если столбцов много, включите альбомную страницу.'));
}drawMatrix();
body=section('6 ОПИСАНИЕ ПРОЦЕССА');field(body,'Порядок … представлен в виде квалиграммы и текстового описания к ней. Вставка вместо многоточия:',state,'process_name');field(body,'Либо полностью свой текст вступления (имеет приоритет)',state,'process_custom','textarea');names(body,'processes','Процесс');body.append(el('p','Для каждого процесса: страница с названием, пустая страница «Квалиграмма» и пустая страница «Текстовое описание к квалиграмме».'));
repeat(section('7 ОЦЕНКА РИСКОВ'),'risks',[['event','Возможный прецедент','text'],['probability','Вероятность',[1,2,3,4,5]],['impact','Влияние',[1,2,3,4,5]]],{event:'',probability:1,impact:1});
const indicatorFields=[['name','Показатель'],['unit','Ед. изм.'],['criterion','Критерий для сбора данных'],['target','Нормативное значение'],['source','Источник данных'],['who','Кто вносит'],['what','Что вносит'],['where','Куда вносит'],['frequency','Периодичность анализа'],['responsible','Ответственный']];
repeat(section('8 ПОКАЗАТЕЛИ ПРОЦЕССА'),'indicators',indicatorFields.map(([k,label])=>[k,label,'text']),Object.fromEntries(indicatorFields.map(([k])=>[k,''])));
body=section('9 ВНЕСЕНИЕ ИЗМЕНЕНИЙ');field(body,'Кому передаются предложения',state,'proposals_to');field(body,'Кто вносит изменения совместно с менеджером СМК',state,'changes_owner');
section('10 ХРАНЕНИЕ').append(el('p','Текст о хранении и сетевых ресурсах ККБ будет включён по согласованному образцу.'));
names(section('Приложения'),'appendices','Приложение');
const changesSection=section('ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ');changesSection.append(el('p','Для редакций 2 и выше заполните изменения. Номер изменения присваивается автоматически, номер редакции берётся из реквизитов.'));
repeat(changesSection,'changes',[['pages','Страница изменения','text'],['kind','Вид изменения',['Введено впервые','Измененная редакция','Исключено']],['description','Краткое описание','text']],{pages:'',kind:'Измененная редакция',description:''});
const checked=el('input');checked.type='checkbox';checked.checked=state.changes_reviewed;checked.onchange=()=>{state.changes_reviewed=checked.checked;changed();};const confirmLabel=el('label');confirmLabel.append(checked,document.createTextNode(' Сведения об изменениях этой редакции проверены'));changesSection.append(confirmLabel);
function updateEdition(){changesSection.parentElement.hidden=state.edition===1;}updateEdition();
section('ВЕДОМОСТЬ ОБУЧЕНИЯ И ОЗНАКОМЛЕНИЯ').append(el('p','Пустая ведомость будет скопирована из шаблона ККБ. Заполняется после экспорта в Word.'));
async function save(){const snapshot=JSON.stringify(state);const response=await fetch('/stu/'+initial.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,content:JSON.parse(snapshot)})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Ошибка сохранения');version=result.version;dirty=JSON.stringify(state)!==snapshot;status.textContent=dirty?'Есть новые несохранённые изменения':'Черновик сохранён';errors.replaceChildren(...result.errors.map(msg=>el('li',msg)));return result;}
async function act(exportFile){if(busy)return;busy=true;form.inert=true;document.querySelector('#stu-save').disabled=true;document.querySelector('#stu-export').disabled=true;status.textContent='Сохраняем…';try{const result=await save();if(exportFile){if(result.errors.length)throw new Error('Черновик сохранён. Заполните пункты из списка перед экспортом.');const response=await fetch('/stu/'+initial.id+'/export.docx');if(!response.ok){const result=await response.json();throw new Error(result.detail||'Ошибка экспорта');}const blob=await response.blob(),url=URL.createObjectURL(blob),a=el('a',undefined,{href:url,download:'СТУ.docx'});a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);status.textContent='Сохранено. DOCX скачан.';}}catch(e){status.textContent=e.message;}finally{busy=false;form.inert=false;document.querySelector('#stu-save').disabled=false;document.querySelector('#stu-export').disabled=false;}}
document.querySelector('#stu-save').onclick=()=>act(false);document.querySelector('#stu-export').onclick=()=>act(true);
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
})();
