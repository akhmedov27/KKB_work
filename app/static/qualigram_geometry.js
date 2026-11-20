// Shared pointer geometry. Bounds are the drawable A4 area, not CSS pixels.
window.QualigramGeometry={
 resize(rect,handle,dx,dy,pageWidth,pageHeight){
  let left=rect.x,top=rect.y,right=left+rect.width,bottom=top+rect.height;
  if(handle.includes('w'))left=Math.max(20,Math.min(right-16,left+dx));
  if(handle.includes('e'))right=Math.min(pageWidth-20,Math.max(left+16,right+dx));
  if(handle.includes('n'))top=Math.max(140,Math.min(bottom-16,top+dy));
  if(handle.includes('s'))bottom=Math.min(pageHeight-20,Math.max(top+16,bottom+dy));
  return {x:left,y:top,width:right-left,height:bottom-top};
 },
 move(rect,dx,dy,pageWidth,pageHeight,axis=null){
  return {x:axis==='y'?rect.x:Math.max(20,Math.min(pageWidth-20-rect.width,Math.round((rect.x+dx)/10)*10)),
          y:axis==='x'?rect.y:Math.max(140,Math.min(pageHeight-20-rect.height,Math.round((rect.y+dy)/10)*10))};
 }
};
