(() => {'use strict';
const init=JSON.parse(document.querySelector('#q-data').textContent),g=init.diagram,base='/stu/'+init.id+'/qualigrams/'+init.pid;
const $=s=>document.querySelector(s),paper=$('#q-paper'),status=$('#q-status'),props=$('#q-properties');
const NS='http://www.w3.org/2000/svg',history=new window.QualigramHistory(g);
let version=init.version,savedJSON=JSON.stringify(g),dirty=false,busy=false,selected=null,edgeSelected=null,connect=false,from=null;
let timer,sequence=0,dragging=false,inlineEdit=null,undoButton,redoButton,orientationInput;
const kinds={action:'Действие',start:'Начало',end:'Окончание',dept_in:'Отдел — вход',dept_out:'Отдел — выход',department:'Внешний отдел',and:'И',or:'ИЛИ',and_or:'И/ИЛИ',note:'Пояснение',document:'Документ',date:'Дата',number:'Номер'};
const width=()=>g.orientation==='portrait'?1200:1697,height=()=>g.orientation==='portrait'?1697:1200,id=()=>crypto.randomUUID().replaceAll('-','');
const selection=()=>({node:selected,edge:edgeSelected});
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function button(parent,text,fn){const b=el('button',text);b.type='button';b.onclick=async()=>{try{await fn();}catch(e){status.textContent=e.message;}};parent.append(b);return b;}
function historyButtons(){if(undoButton)undoButton.disabled=!history.canUndo;if(redoButton)redoButton.disabled=!history.canRedo;}
function schedule(){clearTimeout(timer);++sequence;timer=setTimeout(preview,180);}
function change(label='Изменение схемы',key=null){history.record(g,selection(),label,key);dirty=JSON.stringify(g)!==savedJSON;historyButtons();status.textContent=dirty?'Есть несохранённые изменения':'Схема соответствует сохранённой';schedule();paintSelection();}
async function api(path,options={}){const r=await fetch(base+path,options);if(!r.ok){let d;try{d=await r.json();}catch{d={};}throw Error(d.detail||'Ошибка запроса');}return r;}
async function preview(){
 clearTimeout(timer);const seq=++sequence,snapshot=JSON.stringify(g);
 try{const response=await api('/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:snapshot}),data=await response.json();
  if(seq!==sequence||snapshot!==JSON.stringify(g))return null;
  $('#q-errors').replaceChildren(...[...data.errors,...data.warnings].map(s=>el('li',s)));
  if(!dragging&&!inlineEdit){const xml=new DOMParser().parseFromString(data.svg,'image/svg+xml');paper.replaceChildren(document.importNode(xml.documentElement,true));wire();paintSelection();}
  return data;
 }catch(e){if(seq===sequence)status.textContent=e.message;return null;}
}
function input(parent,label,obj,key,type='text',choices,after){
 const wrap=el('label',label),n=el(choices?'select':type==='textarea'?'textarea':'input');
 if(choices){for(const [value,text] of choices)n.append(new Option(text,value));}else if(type!=='textarea')n.type=type;
 n.value=obj[key]??'';if(type==='textarea')n.maxLength=2000;if(type==='number')n.step='1';
 const write=()=>{obj[key]=type==='number'?(n.value===''?null:Number(n.value)):n.value;if(after)after();change(label,choices?null:'field:'+(obj.id||'root')+':'+key);};
 if(choices)n.onchange=write;else{n.oninput=write;n.onchange=()=>history.breakMerge();n.onblur=()=>history.breakMerge();}wrap.append(n);parent.append(wrap);return n;
}
function setSelection(node,edge,focus=true){selected=node;edgeSelected=edge;history.select(selection());inspect();paintSelection();if(focus)paper.focus({preventScroll:true});}
function nodeGroup(nid){return paper.querySelector(`[data-node-id="${nid}"]`);}
function liveNode(n){const group=nodeGroup(n.id);if(!group)return;group.setAttribute('transform',`translate(${n.x} ${n.y})`);const body=group.querySelector('[data-q-live-body]');if(body)body.setAttribute('transform',`scale(${n.width/Number(body.dataset.width)} ${n.height/Number(body.dataset.height)})`);}
function startResize(event,n,handle,group){
 event.preventDefault();event.stopPropagation();if(dragging||!['x','y','width','height'].every(key=>Number.isFinite(n[key])))return;
 const before={x:n.x,y:n.y,width:n.width,height:n.height},svg=paper.querySelector('svg'),box=svg.getBoundingClientRect(),sx=width()/box.width,sy=height()/box.height,startX=event.clientX,startY=event.clientY;
 let body=group.querySelector('[data-q-live-body]');if(!body){body=document.createElementNS(NS,'g');body.dataset.qLiveBody='true';body.dataset.width=n.width;body.dataset.height=n.height;for(const child of [...group.childNodes])if(!(child instanceof Element&&child.hasAttribute('data-q-selection')))body.append(child);group.prepend(body);}
 dragging=true;group.setPointerCapture(event.pointerId);paper.focus({preventScroll:true});
 group.onpointermove=e=>{Object.assign(n,window.QualigramGeometry.resize(before,handle,Math.round((e.clientX-startX)*sx),Math.round((e.clientY-startY)*sy),width(),height()));liveNode(n);paintSelection();dirty=JSON.stringify(g)!==savedJSON;};
 const finish=cancel=>{dragging=false;group.onpointermove=null;group.onpointerup=null;group.onpointercancel=null;if(cancel)Object.assign(n,before);liveNode(n);inspect();if(cancel){schedule();paintSelection();}else change('Изменение размера блока');};
 group.onpointerup=()=>finish(false);group.onpointercancel=()=>finish(true);
}
function paintSelection(){
 paper.querySelectorAll('[data-q-selection]').forEach(n=>n.remove());
 paper.querySelectorAll('[data-node-id]').forEach(group=>{
  const active=group.dataset.nodeId===selected;group.classList.toggle('q-selected',active);group.setAttribute('aria-pressed',String(active));
  if(active){const n=g.nodes.find(n=>n.id===selected);if(!n)return;liveNode(n);const rect=document.createElementNS(NS,'rect');
   for(const [key,value]of Object.entries({'data-q-selection':'true',x:-5,y:-5,width:n.width+10,height:n.height+10,fill:'none',stroke:'#1678D3','stroke-width':3,'pointer-events':'none','vector-effect':'non-scaling-stroke'}))rect.setAttribute(key,value);group.append(rect);
   const scale=paper.querySelector('svg').getBoundingClientRect().width/width(),size=Math.min(10,Math.max(5,Math.min(n.width,n.height)*scale/3))/scale;
   for(const [handle,x,y]of [['nw',-5,-5],['n',n.width/2,-5],['ne',n.width+5,-5],['e',n.width+5,n.height/2],['se',n.width+5,n.height+5],['s',n.width/2,n.height+5],['sw',-5,n.height+5],['w',-5,n.height/2]]){
    const marker=document.createElementNS(NS,'rect');for(const [key,value]of Object.entries({'data-q-selection':'true','data-q-handle':handle,x:x-size/2,y:y-size/2,width:size,height:size,fill:'white',stroke:'#1678D3','stroke-width':2,'vector-effect':'non-scaling-stroke'}))marker.setAttribute(key,value);
    marker.style.cursor=handle+'-resize';marker.addEventListener('pointerdown',event=>startResize(event,n,handle,group));group.append(marker);
   }}
 });
 paper.querySelectorAll('[data-edge-id]').forEach(group=>{const active=group.dataset.edgeId===edgeSelected;group.classList.toggle('q-selected',active);group.setAttribute('aria-pressed',String(active));});
}
function refresh(){
 if(!g.nodes.some(n=>n.id===selected))selected=null;if(!g.edges.some(e=>e.id===edgeSelected))edgeSelected=null;
 connect=false;from=null;laneList();inspect();$('#q-description').value=g.description;if(orientationInput)orientationInput.value=g.orientation;paintSelection();
}
function undoRedo(redo=false){
 if(dragging)return;if(inlineEdit)inlineEdit.finish(true);const state=redo?history.redo():history.undo();if(!state)return;
 for(const key of Object.keys(g))delete g[key];Object.assign(g,state.data);selected=state.selection.node;edgeSelected=state.selection.edge;
 refresh();dirty=JSON.stringify(g)!==savedJSON;historyButtons();status.textContent=(redo?'Действие повторено':'Действие отменено')+(dirty?' · есть несохранённые изменения':' · сохранённая схема');schedule();
}
function laneList(){
 const host=$('#q-lanes');host.replaceChildren();g.lanes.forEach((lane,i)=>{const row=el('div');input(row,'Исполнитель '+(i+1),lane,'name').maxLength=200;
 button(row,'↑',()=>{if(i){[g.lanes[i],g.lanes[i-1]]=[g.lanes[i-1],g.lanes[i]];laneList();change('Порядок дорожек');}});
 button(row,'Удалить дорожку',()=>{if(!confirm('Удалить дорожку и её назначения в блоках?'))return;g.lanes.splice(i,1);for(const n of g.nodes){n.lanes=n.lanes.filter(v=>v!==lane.id);if(n.responsible===lane.id)n.responsible=null;}laneList();inspect();change('Удаление дорожки');});host.append(row);
 });button(host,'Добавить дорожку',()=>{if(g.lanes.length>=5){status.textContent='Допускается до пяти дорожек.';return;}g.lanes.push({id:id(),name:'Исполнитель '+(g.lanes.length+1)});laneList();change('Добавление дорожки');});
}
function align(n){if(!n.lanes.length)return;const indices=n.lanes.map(v=>g.lanes.findIndex(l=>l.id===v)),w=(width()-40)/g.lanes.length;n.x=20+Math.min(...indices)*w+12;n.width=(Math.max(...indices)-Math.min(...indices)+1)*w-24;}
function preset(n){const size=init.presets[n.kind];if(!size)return;const cx=n.x+n.width/2,cy=n.y+n.height/2;Object.assign(n,size);n.x=Math.max(20,Math.min(width()-20-n.width,cx-n.width/2));n.y=Math.max(140,Math.min(height()-20-n.height,cy-n.height/2));}
function add(kind){
 if(g.nodes.length>=100)return;const n={id:id(),kind,text:kind==='start'?'Начало процесса':kind==='end'?'Окончание процесса':kinds[kind],x:40,y:Math.min(height()-150,160+g.nodes.length*110),width:200,height:90,lanes:[],responsible:null,number:null,font_size:16};
 if(kind==='action'&&g.lanes.length){n.lanes=[g.lanes[0].id];n.responsible=g.lanes[0].id;align(n);}if(['start','end','number'].includes(kind)){n.width=100;n.height=80;}
 if(init.presets[kind]){Object.assign(n,init.presets[kind]);if(['department','dept_in','dept_out'].includes(kind))n.text='Отдел';}
 g.nodes.push(n);selected=n.id;edgeSelected=null;inspect();change('Добавление блока');paper.focus({preventScroll:true});
}
function removeSelection(){
 if(selected){const nid=selected;g.nodes=g.nodes.filter(n=>n.id!==nid);g.edges=g.edges.filter(e=>e.source!==nid&&e.target!==nid);selected=null;edgeSelected=null;inspect();change('Удаление блока и связей');}
 else if(edgeSelected){g.edges=g.edges.filter(e=>e.id!==edgeSelected);edgeSelected=null;inspect();change('Удаление связи');}
}
function inspect(){
 props.replaceChildren();const n=g.nodes.find(n=>n.id===selected),e=g.edges.find(e=>e.id===edgeSelected);
 if(n){
  input(props,'Тип',n,'kind','text',Object.entries(kinds),()=>{preset(n);inspect();});input(props,'Текст',n,'text','textarea');
  for(const [k,label]of[['x','X'],['y','Y'],['width','Ширина'],['height','Высота'],['font_size','Размер шрифта'],['number','Номер действия (необязательно)']])input(props,label,n,k,'number');
  if(init.presets[n.kind])button(props,'Размер как в образце',()=>{preset(n);inspect();change('Размер по образцу');});
  button(props,'Подогнать высоту под текст',async()=>{const data=await preview(),current=g.nodes.find(row=>row.id===n.id);if(data&&current){current.height=Math.ceil(data.heights[n.id]);current.y=Math.min(current.y,height()-20-current.height);inspect();change('Высота блока');}});
  if(n.kind==='action'){
   props.append(el('h3','Исполнители'));g.lanes.forEach(l=>{const label=el('label'),c=el('input');c.type='checkbox';c.checked=n.lanes.includes(l.id);c.onchange=()=>{if(c.checked)n.lanes.push(l.id);else{n.lanes=n.lanes.filter(v=>v!==l.id);if(n.responsible===l.id)n.responsible=null;}inspect();change('Исполнители действия');};label.append(c,document.createTextNode(l.name));props.append(label);});
   input(props,'Ответственный',n,'responsible','text',[['','Выберите'],...g.lanes.filter(l=>n.lanes.includes(l.id)).map(l=>[l.id,l.name])],()=>{if(n.responsible==='')n.responsible=null;});
   button(props,'Растянуть по дорожкам исполнителей',()=>{align(n);inspect();change('Ширина по исполнителям');});
  }button(props,'Удалить блок',removeSelection);
 }else if(e){
  input(props,'Подпись стрелки',e,'label').maxLength=500;input(props,'Вид',e,'kind','text',[['information','Информация — чёрная'],['defect','Брак — красная пунктирная'],['risk','Высокий риск — красная']]);
  for(const k of ['source','target'])input(props,k==='source'?'Откуда':'Куда',e,k,'text',g.nodes.map(n=>[n.id,n.text.slice(0,50)]));
  for(const k of ['source_port','target_port'])input(props,k==='source_port'?'Выход':'Вход',e,k,'text',[['auto','Автоматически'],['top','Сверху'],['right','Справа'],['bottom','Снизу'],['left','Слева']]);
  button(props,'Удалить стрелку',removeSelection);
 }else props.textContent='Выберите блок или стрелку.';
 const links=$('#q-edges');links.replaceChildren();g.edges.forEach((e,i)=>button(links,(i+1)+'. '+(e.label||'Связь без подписи'),()=>setSelection(null,e.id)));
}
function editText(kind,itemId,target){
 if(inlineEdit)inlineEdit.finish(true);const obj=kind==='node'?g.nodes.find(n=>n.id===itemId):kind==='lane'?g.lanes.find(l=>l.id===itemId):g.edges.find(e=>e.id===itemId);if(!obj)return;
 const key=kind==='node'?'text':kind==='lane'?'name':'label',original=obj[key],box=target.getBoundingClientRect(),area=paper.getBoundingClientRect();
 const host=el('div');host.className='q-inline-editor';host.setAttribute('role','group');host.setAttribute('aria-label','Редактирование текста на схеме');
 const label=el('label',kind==='node'?'Текст блока':kind==='lane'?'Должность':'Подпись стрелки'),text=el('textarea');text.maxLength=kind==='node'?2000:kind==='lane'?200:500;text.rows=kind==='node'?4:2;text.value=original;
 label.append(text);host.append(label);const controls=el('div');controls.className='stu-controls';host.append(controls);
 const editorWidth=Math.min(360,Math.max(240,paper.clientWidth-24));host.style.width=editorWidth+'px';host.style.left=Math.max(0,Math.min(paper.scrollWidth-editorWidth-12,box.left-area.left+paper.scrollLeft+(box.width-editorWidth)/2))+'px';host.style.top=Math.max(0,box.top-area.top+paper.scrollTop)+'px';
 const finish=commit=>{if(!inlineEdit)return;inlineEdit=null;host.remove();if(commit&&text.value!==original){obj[key]=text.value;if(kind==='lane')laneList();inspect();change(kind==='lane'?'Название должности':'Текст '+(kind==='node'?'блока':'связи'));}else schedule();paper.focus({preventScroll:true});};
 inlineEdit={host,input:text,original,finish};button(controls,'Готово',()=>finish(true));button(controls,'Отмена',()=>finish(false));
 text.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();finish(false);}else if(event.key==='Enter'&&((event.ctrlKey||event.metaKey)||(kind!=='node'&&!event.shiftKey))){event.preventDefault();event.stopPropagation();finish(true);}});
 paper.append(host);text.focus();text.select();
}
function wire(){
 const svg=paper.querySelector('svg');
 svg.querySelectorAll('[data-edge-id]').forEach(group=>{
  const eid=group.dataset.edgeId;group.setAttribute('tabindex','0');group.setAttribute('role','button');group.setAttribute('aria-label','Связь: '+(g.edges.find(e=>e.id===eid)?.label||'без подписи'));
  const first=group.querySelector('line'),polygon=group.querySelector('polygon');if(first&&polygon){const point=polygon.points.getItem(0),hit=document.createElementNS(NS,'line');for(const [k,v]of Object.entries({x1:first.getAttribute('x1'),y1:first.getAttribute('y1'),x2:point.x,y2:point.y,stroke:'transparent','stroke-width':14,'pointer-events':'stroke',class:'q-edge-hit'}))hit.setAttribute(k,v);group.prepend(hit);}
  group.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();event.stopPropagation();setSelection(null,eid);});
  group.addEventListener('focus',()=>setSelection(null,eid,false));group.addEventListener('dblclick',event=>{event.preventDefault();event.stopPropagation();setSelection(null,eid,false);editText('edge',eid,group);});
 });
 svg.querySelectorAll('[data-lane-id]').forEach(group=>{
  const lid=group.dataset.laneId;group.addEventListener('pointerdown',event=>{event.stopPropagation();setSelection(null,null,false);group.focus({preventScroll:true});});
  group.addEventListener('dblclick',event=>{event.preventDefault();event.stopPropagation();editText('lane',lid,group);});
  group.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();event.stopPropagation();editText('lane',lid,group);}});
 });
 svg.querySelectorAll('[data-node-id]').forEach(group=>wireNode(group,svg));
 svg.addEventListener('pointerdown',event=>{if(!event.target.closest('[data-node-id],[data-edge-id],[data-lane-id]')){setSelection(null,null);}});
}
function wireNode(group,svg){
 const nid=group.dataset.nodeId;group.addEventListener('focus',()=>setSelection(nid,null,false));
 group.addEventListener('dblclick',event=>{event.preventDefault();event.stopPropagation();setSelection(nid,null,false);editText('node',nid,group);});
 group.addEventListener('pointerdown',event=>{
  if(event.button!==0||dragging)return;const original=g.nodes.find(v=>v.id===nid);if(!original)return;event.preventDefault();event.stopPropagation();
  if(connect){setSelection(nid,null);if(!from){from=nid;status.textContent='Выберите блок назначения';}else if(from===nid){status.textContent='Выберите другой блок назначения';}else{if(g.edges.length<200)g.edges.push({id:id(),source:from,target:nid,source_port:'auto',target_port:'auto',kind:'information',label:''});from=null;connect=false;change('Добавление связи');}return;}
  setSelection(nid,null);if(event.detail>=2)return;
  const box=svg.getBoundingClientRect(),sx=width()/box.width,sy=height()/box.height,before={x:original.x,y:original.y,width:original.width,height:original.height},startX=event.clientX,startY=event.clientY,copy=event.ctrlKey||event.metaKey;
  let moved=false,axis=null,n=original,clone=null;
  dragging=true;group.setPointerCapture(event.pointerId);
  group.onpointermove=e=>{
   if(Math.hypot(e.clientX-startX,e.clientY-startY)<3&&!moved)return;
   if(!moved&&copy){if(g.nodes.length>=100){status.textContent='Не более 100 блоков.';return;}n=JSON.parse(JSON.stringify(original));n.id=id();g.nodes.push(n);clone=group.cloneNode(true);clone.dataset.nodeId=n.id;clone.querySelectorAll('[data-q-selection]').forEach(el=>el.remove());svg.append(clone);wireNode(clone,svg);selected=n.id;edgeSelected=null;inspect();}
   moved=true;const dx=(e.clientX-startX)*sx,dy=(e.clientY-startY)*sy;
   if(e.shiftKey){if(!axis)axis=Math.abs(dx)>=Math.abs(dy)?'x':'y';}else axis=null;
   Object.assign(n,window.QualigramGeometry.move(before,dx,dy,width(),height(),axis));liveNode(n);paintSelection();dirty=JSON.stringify(g)!==savedJSON;
  };
  const finish=cancel=>{dragging=false;group.onpointermove=null;group.onpointerup=null;group.onpointercancel=null;
   if(cancel){if(clone){g.nodes=g.nodes.filter(row=>row.id!==n.id);clone.remove();selected=original.id;}else Object.assign(n,{x:before.x,y:before.y});liveNode(original);}
   inspect();if(moved&&!cancel)change(copy?'Копирование блока':'Перемещение блока');else if(moved){schedule();paintSelection();}
  };
  group.onpointerup=()=>finish(false);group.onpointercancel=()=>finish(true);
 });
}

async function save(){
 if(inlineEdit)inlineEdit.finish(true);const snapshot=JSON.stringify(g),r=await api('',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,diagram:JSON.parse(snapshot)})});version=(await r.json()).version;savedJSON=snapshot;dirty=JSON.stringify(g)!==savedJSON;history.breakMerge();status.textContent=dirty?'Есть новые изменения':'Схема сохранена';
}
async function action(fmt){if(busy)return;busy=true;try{await save();if(fmt){const r=await api('/export.'+fmt),blob=await r.blob(),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='Квалиграмма.'+fmt;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}}finally{busy=false;}}
const bar=$('#q-toolbar');undoButton=button(bar,'Назад',()=>undoRedo());undoButton.id='q-undo';undoButton.title='Отменить действие (Ctrl+Z)';redoButton=button(bar,'Вперёд',()=>undoRedo(true));redoButton.id='q-redo';redoButton.title='Повторить действие (Ctrl+Y)';
button(bar,'Применить размеры образца',()=>{if(!confirm('Применить размеры образца к блокам И, ИЛИ, И/ИЛИ, отделений, начала и окончания?'))return;g.nodes.forEach(preset);inspect();change('Размеры по образцу');});
button(bar,'Сохранить схему',()=>action());button(bar,'PNG',()=>action('png'));button(bar,'Visio 2007 · VDX',()=>action('vdx'));
button(bar,'Соединить два блока',()=>{connect=!connect;from=null;status.textContent=connect?'Выберите исходный блок, затем конечный':'Соединение отменено';});
button(bar,'Убрать схему из СТУ',async()=>{if(busy||!confirm('Удалить сохранённую схему? Страницы в Word останутся пустыми.'))return;busy=true;try{await api('',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,diagram:null})});dirty=false;savedJSON=JSON.stringify(g);location.href='/stu/'+init.id;}finally{busy=false;}});
orientationInput=input(bar,'Ориентация',g,'orientation','text',[['portrait','Книжная'],['landscape','Альбомная']],()=>{for(const n of g.nodes){n.width=Math.min(n.width,width()-40);n.height=Math.min(n.height,height()-160);n.x=Math.min(n.x,width()-20-n.width);n.y=Math.min(n.y,height()-20-n.height);}inspect();});
for(const [k,v]of Object.entries(kinds))button($('#q-palette'),v,()=>add(k));
const desc=$('#q-description');desc.value=g.description;desc.oninput=()=>{g.description=desc.value;change('Текстовое описание','description');};desc.onblur=()=>history.breakMerge();
$('#q-describe').onclick=async()=>{if(desc.value&&!confirm('Заменить описание текстом из шагов?'))return;const data=await preview();if(data){g.description=data.description;desc.value=g.description;change('Описание из шагов');}};
function isEditing(target){return target instanceof Element&&Boolean(target.closest('input,textarea,select,[contenteditable="true"]'));}
document.addEventListener('pointerdown',event=>{if(inlineEdit&&!inlineEdit.host.contains(event.target))inlineEdit.finish(true);},true);
window.addEventListener('keydown',event=>{
 if(isEditing(event.target)||dragging||event.isComposing)return;
 const command=event.ctrlKey||event.metaKey;
 if(command&&(event.code==='KeyZ'||event.key.toLowerCase()==='z')){event.preventDefault();undoRedo(event.shiftKey);return;}
 if(command&&(event.code==='KeyY'||event.key.toLowerCase()==='y')){event.preventDefault();undoRedo(true);return;}
 if(command||event.altKey)return;
 if(event.key==='Delete'&&(selected||edgeSelected)){event.preventDefault();removeSelection();return;}
 if(event.key==='Escape'){connect=false;from=null;setSelection(null,null);return;}
 if(event.key==='Enter'&&(event.target===paper||event.target.closest?.('[data-node-id],[data-edge-id]'))){const target=paper.querySelector(selected?`[data-node-id="${selected}"]`:`[data-edge-id="${edgeSelected}"]`);if(target){event.preventDefault();editText(selected?'node':'edge',selected||edgeSelected,target);}return;}
 const steps={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
 const n=g.nodes.find(n=>n.id===selected);if(n&&steps[event.key]){event.preventDefault();const [dx,dy]=steps[event.key],step=event.shiftKey?10:1;n.x=Math.max(20,Math.min(width()-20-n.width,n.x+dx*step));n.y=Math.max(140,Math.min(height()-20-n.height,n.y+dy*step));const group=paper.querySelector(`[data-node-id="${n.id}"]`);if(group)group.setAttribute('transform',`translate(${n.x} ${n.y})`);inspect();change('Перемещение клавишами','move:'+n.id);}
});
window.addEventListener('beforeunload',event=>{if(JSON.stringify(g)!==savedJSON||(inlineEdit&&inlineEdit.input.value!==inlineEdit.original)){event.preventDefault();event.returnValue='';}});
laneList();historyButtons();preview();
})();
