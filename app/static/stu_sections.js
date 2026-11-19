// Two-level outline with stable IDs; all user text is assigned via DOM properties.
window.StuSections={render({state,parent,el,button,field,changed}){
 const uid=()=>crypto.randomUUID().replaceAll('-','');
 const textBlock=()=>({id:uid(),kind:'text',text:''});
 const host=el('div',undefined,{id:'stu-sections'});parent.append(el('p','Названия вводите без номера. Порядок разделов и подразделов определяет нумерацию и содержание Word. Удаление убирает выбранный элемент с его содержимым. До 50 разделов и подразделов, 200 блоков; таблица — до 10 столбцов и 50 строк; всего до 5000 ячеек.'));
 let opened=null;
 const sectionCount=()=>state.sections.reduce((sum,s)=>sum+1+s.subsections.length,0);
 const blockCount=()=>state.sections.reduce((sum,s)=>sum+s.blocks.length+s.subsections.reduce((n,c)=>n+c.blocks.length,0),0);
 const cellCount=()=>state.sections.flatMap(s=>[s,...s.subsections]).flatMap(s=>s.blocks).filter(b=>b.kind==='table').reduce((n,b)=>n+b.headers.length*(b.rows.length+1),0);
 function move(array,i,j){if(j<0||j>=array.length)return;[array[i],array[j]]=[array[j],array[i]];changed();}
 function cap(condition,message){if(condition){alert(message);return true;}return false;}
 function action(parent,label,fn,disabled=false){const b=button(label,fn,parent);b.disabled=disabled;return b;}
 function tableEditor(parent,block,number,bi){
  field(parent,'Название таблицы (необязательно)',block,'title');
  const controls=el('div',undefined,{class:'stu-controls'}),scroll=el('div',undefined,{class:'table-scroll'});parent.append(controls,scroll);
  function draw(){controls.replaceChildren();scroll.replaceChildren();
   action(controls,'Добавить столбец',()=>{if(cap(block.headers.length>=10||cellCount()+block.rows.length+1>5000,'Достигнут предел столбцов или ячеек документа.'))return;block.headers.push('');block.rows.forEach(row=>row.push(''));changed();draw();},block.headers.length>=10||cellCount()+block.rows.length+1>5000);
   action(controls,'Добавить строку таблицы',()=>{if(cap(block.rows.length>=50||cellCount()+block.headers.length>5000,'Достигнут предел строк или ячеек документа.'))return;block.rows.push(block.headers.map(()=>''));changed();draw();},block.rows.length>=50||cellCount()+block.headers.length>5000);
   const table=el('table',undefined,{class:'stu-free-table'}),head=el('thead'),tr=el('tr');tr.append(el('th','№'));
   block.headers.forEach((name,ci)=>{const th=el('th'),input=el('input',undefined,{'aria-label':`Заголовок столбца ${ci+1} таблицы в блоке ${bi+1} раздела ${number}`,maxlength:500});input.value=name;input.oninput=()=>{block.headers[ci]=input.value;changed();};th.append(input);
    const tools=el('div',undefined,{class:'stu-controls'});
    function shift(j){move(block.headers,ci,j);block.rows.forEach(row=>{[row[ci],row[j]]=[row[j],row[ci]];});draw();}
    action(tools,'←',()=>shift(ci-1),ci===0).setAttribute('aria-label','Столбец '+(ci+1)+' влево');
    action(tools,'→',()=>shift(ci+1),ci===block.headers.length-1).setAttribute('aria-label','Столбец '+(ci+1)+' вправо');
    action(tools,'Удалить столбец',()=>{if(!confirm('Удалить столбец и все его ячейки?'))return;block.headers.splice(ci,1);block.rows.forEach(row=>row.splice(ci,1));changed();draw();},block.headers.length===1);th.append(tools);tr.append(th);
   });tr.append(el('th','Действия'));head.append(tr);table.append(head);const body=el('tbody');
   block.rows.forEach((row,ri)=>{const tr=el('tr');tr.append(el('td',ri+1));row.forEach((value,ci)=>{const td=el('td'),input=el('textarea',undefined,{'aria-label':`Ячейка ${ri+1}, ${ci+1} таблицы в блоке ${bi+1} раздела ${number}`,maxlength:5000,rows:2});input.value=value;input.oninput=()=>{block.rows[ri][ci]=input.value;changed();};td.append(input);tr.append(td);});
    const td=el('td');action(td,'↑',()=>{move(block.rows,ri,ri-1);draw();},ri===0).setAttribute('aria-label','Строка '+(ri+1)+' вверх');action(td,'↓',()=>{move(block.rows,ri,ri+1);draw();},ri===block.rows.length-1).setAttribute('aria-label','Строка '+(ri+1)+' вниз');
    action(td,'Удалить строку таблицы',()=>{if(!confirm('Удалить строку таблицы?'))return;block.rows.splice(ri,1);changed();draw();});tr.append(td);body.append(tr);
   });table.append(body);scroll.append(table);
  }draw();
 }
 function blocks(parent,item,number){
  const host=el('div',undefined,{class:'stu-free-blocks'}),controls=el('div',undefined,{class:'stu-controls'});parent.append(host,controls);
  function draw(){host.replaceChildren();item.blocks.forEach((block,bi)=>{
   const card=el('div',undefined,{class:'stu-row','data-block-id':block.id});card.append(el('h4','Блок '+(bi+1)+' · '+(block.kind==='text'?'Текст':'Таблица')));
   if(block.kind==='text')field(card,`Текст раздела ${number}, блок ${bi+1}`,block,'text','textarea');else tableEditor(card,block,number,bi);
   const tools=el('div',undefined,{class:'stu-controls'});
   action(tools,'Блок вверх',()=>{move(item.blocks,bi,bi-1);draw();},bi===0);action(tools,'Блок вниз',()=>{move(item.blocks,bi,bi+1);draw();},bi===item.blocks.length-1);
   action(tools,'Удалить блок',()=>{if(!confirm('Удалить блок с содержимым?'))return;item.blocks.splice(bi,1);changed();draw();});card.append(tools);host.append(card);
  });}
  function add(kind){if(cap(kind==='table'&&cellCount()+4>5000,'Не более 5000 ячеек таблиц в документе.'))return;if(cap(blockCount()>=200||item.blocks.length>=50,'Достигнут предел блоков: 50 в одном разделе, 200 в документе.'))return;item.blocks.push(kind==='text'?textBlock():{id:uid(),kind:'table',title:'',headers:['Столбец 1','Столбец 2'],rows:[['','']]});changed();draw();}
  action(controls,'Добавить текст',()=>add('text'));action(controls,'Добавить таблицу',()=>add('table'));draw();
 }
 function drawItem(parent,item,number,array,index,isSub=false,rootId=null){
  const card=el(isSub?'section':'details',undefined,{class:'stu-row stu-free-section',[isSub?'data-subsection-id':'data-section-id']:item.id});
  if(!isSub)card.open=index===0||opened===item.id;
  const heading=el(isSub?'h3':'summary',number+' '+(item.title||'Без названия'));card.append(heading);
  const body=el('div',undefined,{class:'stu-section'});card.append(body);
  const input=field(body,'Название '+(isSub?'подраздела ':'раздела ')+number,item,'title');input.oninput=()=>{heading.textContent=number+' '+(item.title||'Без названия');};
  const tools=el('div',undefined,{class:'stu-controls'});body.append(tools);
  action(tools,isSub?'Подраздел вверх':'Раздел вверх',()=>{move(array,index,index-1);opened=isSub?rootId:item.id;draw();},index===0);
  action(tools,isSub?'Подраздел вниз':'Раздел вниз',()=>{move(array,index,index+1);opened=isSub?rootId:item.id;draw();},index===array.length-1);
  action(tools,isSub?'Удалить подраздел':'Удалить раздел',()=>{if(!confirm('Удалить '+(isSub?'подраздел':'раздел с подразделами')+' и его содержимое?'))return;array.splice(index,1);if(isSub)opened=rootId;changed();draw();});
  blocks(body,item,number);
  if(!isSub){
   item.subsections.forEach((child,i)=>drawItem(body,child,number+'.'+(i+1),item.subsections,i,true,item.id));
   action(body,'Добавить подраздел',()=>{if(cap(sectionCount()>=50||item.subsections.length>=20||blockCount()>=200,'Не более 50 разделов/подразделов в документе и 20 подразделов в одном разделе.'))return;item.subsections.push({id:uid(),title:'',blocks:[textBlock()]});opened=item.id;changed();draw();});
  }parent.append(card);
 }
 function draw(){host.replaceChildren();if(!state.sections.length)host.append(el('p','Добавьте первый раздел.'));state.sections.forEach((item,i)=>drawItem(host,item,String(i+1),state.sections,i));}
 action(parent,'Добавить раздел',()=>{if(cap(sectionCount()>=50||blockCount()>=200,'Не более 50 разделов и подразделов и 200 блоков.'))return;const item={id:uid(),title:'',blocks:[textBlock()],subsections:[]};state.sections.push(item);opened=item.id;changed();draw();});parent.append(host);draw();
}};
