// Local bounded history; saves and optimistic server versions are not undone.
window.QualigramHistory=class {
 constructor(data){this.entries=[{json:JSON.stringify(data),selection:{node:null,edge:null},label:'Начальное состояние'}];this.index=0;this.key=null;this.at=0;}
 get canUndo(){return this.index>0;}
 get canRedo(){return this.index<this.entries.length-1;}
 select(selection){this.entries[this.index].selection={...selection};}
 breakMerge(){this.key=null;}
 record(data,selection,label,key=null){
  const json=JSON.stringify(data),now=Date.now();
  if(json===this.entries[this.index].json){this.select(selection);return false;}
  const merge=key&&key===this.key&&now-this.at<700&&this.index===this.entries.length-1&&this.index>0;
  const entry={json,selection:{...selection},label};
  if(merge)this.entries[this.index]=entry;
  else{this.entries.splice(this.index+1);this.entries.push(entry);this.index++;}
  this.key=key;this.at=now;
  let bytes=this.entries.reduce((sum,e)=>sum+e.json.length*2,0);
  while(this.entries.length>1&&(this.entries.length>100||bytes>8*1024*1024)){bytes-=this.entries.shift().json.length*2;this.index--;}
  return true;
 }
 restore(){const entry=this.entries[this.index];return {data:JSON.parse(entry.json),selection:{...entry.selection}};}
 undo(){if(!this.canUndo)return null;this.key=null;this.index--;return this.restore();}
 redo(){if(!this.canRedo)return null;this.key=null;this.index++;return this.restore();}
};
