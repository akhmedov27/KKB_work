// Dependent local category choices; stale responses cannot replace newer ones.
(() => {
  const form=document.querySelector('#incident-filters');if(!form)return;
  const group=form.querySelector('#filter-group_name'),subgroup=form.querySelector('#filter-subgroup'),status=form.querySelector('#subgroup-status');
  let controller,timer,sequence=0,pending=false;
  const fold=value=>value.trim().toLocaleLowerCase('ru-RU');
  async function update(){
    clearTimeout(timer);const request=++sequence,selected=subgroup.value;
    if(controller)controller.abort();controller=new AbortController();pending=true;subgroup.disabled=true;status.textContent='Обновляем подгруппы…';
    try{
      const query=new URLSearchParams({batch_id:subgroup.dataset.batchId,group_name:group.value.trim(),selected});
      const response=await fetch('/incidents/subgroups?'+query,{signal:controller.signal});if(!response.ok)throw Error();
      const data=await response.json();if(request!==sequence)return;
      const match=data.items.find(item=>fold(item.value)===fold(selected));
      subgroup.replaceChildren(new Option('Все подгруппы',''),...data.items.map(item=>new Option(item.label,item.value)));
      subgroup.value=match?match.value:'';
      status.textContent=selected&&!match?'Подгруппа сброшена: она не относится к выбранной группе.':data.truncated?'Первые 500 подгрупп. Выберите группу для уточнения.':group.value.trim()?'Подгруппы выбранной группы':'Доступны все подгруппы набора';
    }catch(error){if(error.name!=='AbortError'&&request===sequence){subgroup.replaceChildren(new Option('Все подгруппы',''));status.textContent='Не удалось обновить список. Нажмите «Рассчитать», чтобы получить подгруппы с сервера.';}}
    finally{if(request===sequence){pending=false;subgroup.disabled=false;}}
  }
  group.addEventListener('input',()=>{clearTimeout(timer);++sequence;if(controller)controller.abort();pending=true;subgroup.disabled=true;timer=setTimeout(update,150);});
  group.addEventListener('change',update);
  // Let normal server rendering handle a submit during an outstanding lookup.
  form.addEventListener('submit',()=>{if(pending||timer){clearTimeout(timer);++sequence;if(controller)controller.abort();subgroup.disabled=false;}});
  form.querySelectorAll('[data-remove-slice]').forEach(button=>button.addEventListener('click',()=>{
    button.closest('[data-chart-slice]').remove();form.requestSubmit();
  }));
})();
