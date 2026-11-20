// Development-only tests; Node is not an application dependency.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function setup(){let clock=0;const context={window:{},Date:{now:()=>clock}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../app/static/qualigram_history.js'),'utf8'),context);return {History:context.window.QualigramHistory,tick:n=>clock+=n};}
test('undo restores deleted nodes and their edges; editing after undo clears redo',()=>{
 const {History}=setup(),g={nodes:[{id:'n',text:'Пример'}],edges:[{id:'e',source:'n',target:'n'}]},h=new History(g);
 h.select({node:'n',edge:null});g.nodes=[];g.edges=[];h.record(g,{node:null,edge:null},'Удалить');
 const restored=h.undo();assert.equal(restored.data.nodes[0].text,'Пример');assert.equal(restored.data.edges[0].id,'e');assert.equal(restored.selection.node,'n');
 restored.data.nodes[0].text='Изменено';h.record(restored.data,restored.selection,'Текст');assert.equal(h.canRedo,false);assert.equal(h.undo().data.nodes[0].text,'Пример');assert.equal(h.redo().data.nodes[0].text,'Изменено');
});
test('repeated movement is one undo; save boundary breaks coalescing',()=>{
 const {History,tick}=setup(),g={x:10},h=new History(g);g.x=11;h.record(g,{},'Сдвиг','move');tick(10);g.x=12;h.record(g,{},'Сдвиг','move');assert.equal(h.undo().data.x,10);
 assert.equal(h.redo().data.x,12);h.breakMerge();g.x=13;h.record(g,{},'Сдвиг','move');assert.equal(h.undo().data.x,12);
});
test('no-op does not destroy redo; snapshots are isolated from later edits',()=>{
 const {History}=setup(),g={text:'А'},h=new History(g);g.text='Б';h.record(g,{},'Текст');h.undo();h.record({text:'А'},{},'Нет изменения');assert.equal(h.canRedo,true);
 const restored=h.redo();restored.data.text='Другое';assert.equal(h.restore().data.text,'Б');
});
test('state count and memory remain bounded without losing current state',()=>{
 const {History}=setup(),h=new History({value:0});for(let i=1;i<=200;i++)h.record({value:i},{},'Изменение');assert.equal(h.entries.length,100);assert.equal(h.restore().data.value,200);
 while(h.canUndo)h.undo();assert.equal(h.restore().data.value,101);
 const large=new History({value:0,pad:'x'.repeat(500000)});for(let i=1;i<=15;i++)large.record({value:i,pad:'x'.repeat(500000)},{},'Изменение');assert.ok(large.entries.reduce((n,e)=>n+e.json.length*2,0)<=8*1024*1024);assert.equal(large.restore().data.value,15);
});
