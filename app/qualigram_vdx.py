"""Editable Visio 2003 XML (.vdx), compatible with the Visio 2007 format family."""
from math import hypot, atan2
import xml.etree.ElementTree as ET
from app.qualigram_render import FILLS, endpoints, role_badges

NS='http://schemas.microsoft.com/visio/2003/core'
ET.register_namespace('',NS)

def vdx(graph,title=''):
 def child(parent,name,value=None,**attrs):
  e=ET.SubElement(parent,'{'+NS+'}'+name,{k:str(v) for k,v in attrs.items()})
  if value is not None:e.text=f'{value:.9f}' if isinstance(value,float) else str(value)
  return e
 root=ET.Element('{'+NS+'}VisioDocument',{'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
 props=child(root,'DocumentProperties');child(props,'Title',title);child(props,'Creator','QMS Assistant KKB')
 faces=child(root,'FaceNames');child(faces,'FaceName',ID=0,Name='Arial')
 pages=child(root,'Pages');page=child(pages,'Page',ID=0,NameU='Qualigram',Name='Квалиграмма')
 sheet=child(page,'PageSheet');pageprops=child(sheet,'PageProps')
 page_width,page_height=(8.267716535,11.692913386) if graph.orientation=='portrait' else (11.692913386,8.267716535)
 scale=page_width/graph.width
 child(pageprops,'PageWidth',page_width);child(pageprops,'PageHeight',page_height)
 shapes=child(page,'Shapes');serial=0
 def ident():
  nonlocal serial
  serial+=1;return serial
 def xform(shape,cx,cy,w,h,angle=0):
  x=child(shape,'XForm')
  for key,value in [('PinX',cx),('PinY',cy),('Width',w),('Height',h),('LocPinX',w/2),('LocPinY',h/2),('Angle',angle)]:child(x,key,value)
 def appearance(shape,fill='#FFFFFF',line='#111111',pattern=1,rounding=0,arrow=0):
  l=child(shape,'Line');child(l,'LineWeight',.009);child(l,'LineColor',line);child(l,'LinePattern',pattern);child(l,'EndArrow',arrow);child(l,'Rounding',rounding)
  f=child(shape,'Fill');child(f,'FillForegnd','#FFFFFF' if fill=='none' else fill);child(f,'FillBkgnd','#FFFFFF');child(f,'FillPattern',0 if fill=='none' else 1)
 def geometry(shape,w,h,kind='rect'):
  g=child(shape,'Geom',IX=0);child(g,'NoFill',0);child(g,'NoLine',0)
  if kind=='ellipse':
   e=child(g,'Ellipse',IX=1)
   for key,value in [('X',w/2),('Y',h/2),('A',w),('B',h/2),('C',w/2),('D',h)]:child(e,key,value)
  else:
   points=[(0,0),(w,0),(w,h),(0,h),(0,0)]
   if kind=='document':points=[(0,0),(w,0),(w,h-.12),(w-.12,h),(0,h),(0,0)]
   for i,(px,py) in enumerate(points,1):
    p=child(g,'MoveTo' if i==1 else 'LineTo',IX=i);child(p,'X',px);child(p,'Y',py)
 def text(shape,value,size,color='#111111',align=1,bold=False):
  c=child(shape,'Char',IX=0);child(c,'Font',0);child(c,'Size',size,Unit='PT');child(c,'Color',color);child(c,'Style',1 if bold else 0)
  p=child(shape,'Para',IX=0);child(p,'HorzAlign',align)
  block=child(shape,'TextBlock')
  for key,value2 in [('LeftMargin',.06),('RightMargin',.06),('TopMargin',.04),('BottomMargin',.04),('VerticalAlign',1)]:child(block,key,value2)
  child(shape,'Text',value)
 def rect(parent,x,y,w,h,value='',fill='#FFFFFF',font=16,bold=False,kind='rect',line='#111111',rounding=0):
  shape=child(parent,'Shape',ID=ident(),Type='Shape');xform(shape,(x+w/2)*scale,page_height-(y+h/2)*scale,w*scale,h*scale)
  appearance(shape,fill,line,rounding=rounding*scale);geometry(shape,w*scale,h*scale,kind)
  if value:text(shape,value,font*scale,bold=bold)
  return shape
 rect(shapes,20,5,graph.width-40,70,title,fill='none',font=20,bold=True,line='#FFFFFF')
 lane_width=(graph.width-40)/max(1,len(graph.lanes))
 for i,lane in enumerate(graph.lanes):
  rect(shapes,20+i*lane_width,80,lane_width,graph.height-100,fill='none',line='#999999')
  rect(shapes,20+i*lane_width,80,lane_width,60,lane.name,fill='#F4F4F4',font=16,bold=True,line='#777777')
 node_ids={}
 for node in graph.nodes:
  w,h=node.width*scale,node.height*scale
  group=child(shapes,'Shape',ID=ident(),Type='Group',NameU='Node_'+node.id)
  node_ids[node.id]=group.get('ID');xform(group,(node.x+node.width/2)*scale,page_height-(node.y+node.height/2)*scale,w,h)
  for i,(x,y,fx,fy) in enumerate([(w/2,h,'Width*0.5','Height'),(w,h/2,'Width','Height*0.5'),(w/2,0,'Width*0.5','0'),(0,h/2,'0','Height*0.5')]):
   c=child(group,'Connection',ID=i);child(c,'X',x,F=fx);child(c,'Y',y,F=fy);child(c,'DirX',0);child(c,'DirY',0);child(c,'Type',0)
  text(group,node.text,node.font_size*scale,color='#FFFFFF' if node.kind=='date' else '#111111',align=0 if node.kind in ('action','note','document') else 1)
  members=child(group,'Shapes')
  body=child(members,'Shape',ID=ident(),Type='Shape');xform(body,w/2,h/2,w,h)
  appearance(body,FILLS[node.kind],'#E88900' if node.kind in ('note','document') else '#111111',pattern=2 if node.kind=='note' else 1,rounding=.12 if node.kind in ('dept_in','dept_out','department','note','date','and','or') else 0)
  geometry(body,w,h,'ellipse' if node.kind in ('start','end','number') else 'document' if node.kind=='document' else 'rect')
  for x,label in role_badges(graph,node):
   badge=child(members,'Shape',ID=ident(),Type='Shape');xform(badge,x*scale,h+scale,56*scale,24*scale)
   appearance(badge,rounding=.08);geometry(badge,56*scale,24*scale);text(badge,label,16*scale)
  if node.number is not None:
   number=child(members,'Shape',ID=ident(),Type='Shape');xform(number,w-4*scale,scale,28*scale,28*scale)
   appearance(number);geometry(number,28*scale,28*scale,'ellipse');text(number,str(node.number),14*scale)
 connects=child(page,'Connects')
 port_index={'top':0,'right':1,'bottom':2,'left':3}
 for edge in graph.edges:
  a,b,first,last=endpoints(graph,edge)
  ax,ay=a[0]*scale,page_height-a[1]*scale;bx,by=b[0]*scale,page_height-b[1]*scale
  length=max(.001,hypot(bx-ax,by-ay));angle=atan2(by-ay,bx-ax)
  shape=child(shapes,'Shape',ID=ident(),Type='Shape',NameU='Edge_'+edge.id)
  xform(shape,(ax+bx)/2,(ay+by)/2,length,0,angle)
  one=child(shape,'XForm1D')
  for prefix,nid,side,x,y in [('Begin',node_ids[edge.source],first,ax,ay),('End',node_ids[edge.target],last,bx,by)]:
   offsets={'top':('','+Sheet.'+nid+'!Height*0.5'),'bottom':('','-Sheet.'+nid+'!Height*0.5'),
            'left':('-Sheet.'+nid+'!Width*0.5',''),'right':('+Sheet.'+nid+'!Width*0.5','')}
   ox,oy=offsets[side]
   child(one,prefix+'X',x,F=f'Sheet.{nid}!PinX{ox}');child(one,prefix+'Y',y,F=f'Sheet.{nid}!PinY{oy}')
   child(connects,'Connect',FromSheet=shape.get('ID'),FromCell=prefix+'X',FromPart=9 if prefix=='Begin' else 12,
         ToSheet=nid,ToCell=f'Connections.X{port_index[side]+1}',ToPart=100+port_index[side])
  appearance(shape,'none','#111111' if edge.kind=='information' else '#D22222',pattern=2 if edge.kind=='defect' else 1,arrow=4)
  g=child(shape,'Geom',IX=0);child(g,'NoFill',1);p=child(g,'MoveTo',IX=1);child(p,'X',0);child(p,'Y',0)
  p=child(g,'LineTo',IX=2);child(p,'X',length,F='Width');child(p,'Y',0)
  if edge.label:
   text(shape,edge.label,14*scale)
   tx=child(shape,'TextXForm')
   for key,value in [('TxtPinX',length/2),('TxtPinY',.10),('TxtWidth',min(length,1.8)),('TxtHeight',.35),('TxtLocPinX',min(length,1.8)/2),('TxtLocPinY',.175),('TxtAngle',-angle)]:child(tx,key,value)
 return ET.tostring(root,encoding='utf-8',xml_declaration=True)
