"""Shared geometry for SVG preview, PNG and editable Visio XML."""
from html import escape
import textwrap
from math import hypot
import fitz
from app.qualigram_model import Qualigram

FILLS={'action':'#E7E7E7','start':'#D6F5D6','end':'#F5C9F0','dept_in':'#D8F2DE',
       'dept_out':'#F8CDD2','department':'#E7E7E7','and':'#FFFFFF','or':'#FFFFFF',
       'note':'#FFF4D6','document':'#FFF0B0','date':'#ED8500','number':'#FFFFFF'}


def wrap(text,width,font):
 result=[]
 for line in text.splitlines() or ['']:
  result.extend(textwrap.wrap(line,width=max(1,int(width/(font*.57))),replace_whitespace=False,drop_whitespace=True) or [''])
 return result


def node_lines(node):
 pad=24
 return wrap(node.text.strip(),max(12,node.width-pad),node.font_size)


def needed_height(node):
 return max(32,len(node_lines(node))*node.font_size*1.22+24)


def layout_errors(graph):
 return [f'Блок «{node.text[:45]}»: увеличьте высоту минимум до {needed_height(node):.0f} или уменьшите шрифт.'
         for node in graph.nodes if needed_height(node)>node.height+.01]


def anchor(node,side):
 return {'top':(node.x+node.width/2,node.y),'right':(node.x+node.width,node.y+node.height/2),
         'bottom':(node.x+node.width/2,node.y+node.height),'left':(node.x,node.y+node.height/2)}[side]


def endpoints(graph,edge):
 nodes={node.id:node for node in graph.nodes};a,b=nodes[edge.source],nodes[edge.target]
 dx=b.x+b.width/2-a.x-a.width/2;dy=b.y+b.height/2-a.y-a.height/2
 if a.y+a.height<=b.y:first='bottom'
 elif b.y+b.height<=a.y:first='top'
 elif a.x+a.width<=b.x:first='right'
 elif b.x+b.width<=a.x:first='left'
 else:first=('right' if dx>=0 else 'left') if abs(dx)>abs(dy) else ('bottom' if dy>=0 else 'top')
 last={'right':'left','left':'right','top':'bottom','bottom':'top'}[first]
 first=first if edge.source_port=='auto' else edge.source_port
 last=last if edge.target_port=='auto' else edge.target_port
 return anchor(a,first),anchor(b,last),first,last


def role_badges(graph,node):
 if node.kind!='action' or len(node.lanes)<2:return []
 width=(graph.width-40)/max(1,len(graph.lanes))
 result=[]
 for i,lane in enumerate(graph.lanes):
  if lane.id in node.lanes:
   center=max(node.x+32,min(node.x+node.width-32,20+(i+.5)*width))
   result.append((center-node.x,'Отв.' if lane.id==node.responsible else 'Уч.'))
 return result


def svg(graph:Qualigram,title='',selected=None):
 out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{graph.width}" height="{graph.height}" viewBox="0 0 {graph.width} {graph.height}" font-family="Arial, sans-serif">',
      f'<rect width="{graph.width}" height="{graph.height}" fill="white"/>',f'<title>{escape(title)}</title>']
 def text(value,x,y,size=16,anchor='start',fill='#111111',bold=False):
  out.append(f'<text font-family="Arial" x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}"'+(' font-weight="bold"' if bold else '')+'>'+escape(value)+'</text>')
 lines=wrap(title,graph.width-60,20)
 for i,line in enumerate(lines[:3]):text(line+('…' if i==2 and len(lines)>3 else ''),30,25+i*21,20,bold=True)
 lane_width=(graph.width-40)/max(1,len(graph.lanes))
 for i,lane in enumerate(graph.lanes):
  x=20+i*lane_width
  out.append(f'<rect x="{x}" y="80" width="{lane_width}" height="{graph.height-100}" fill="none" stroke="#999999" stroke-width="1"/>')
  out.append(f'<rect x="{x}" y="80" width="{lane_width}" height="60" fill="#F4F4F4" stroke="#777777"/>')
  font=18
  while font>8 and len(wrap(lane.name,lane_width-16,font))*font*1.1>52:font-=1
  labels=wrap(lane.name,lane_width-16,font)
  for j,line in enumerate(labels):text(line,x+lane_width/2,92+j*font*1.1,font,'middle',bold=True)
 for edge in graph.edges:
  a,b,_,_=endpoints(graph,edge);red=edge.kind!='information';color='#D22222' if red else '#111111'
  out.append(f'<g data-edge-id="{edge.id}">')
  if edge.kind=='defect':
   length=max(.001,hypot(b[0]-a[0],b[1]-a[1]));ux,uy=(b[0]-a[0])/length,(b[1]-a[1])/length
   for start in range(0,int(length)+1,13):
    stop=min(start+8,length)
    out.append(f'<line x1="{a[0]+start*ux}" y1="{a[1]+start*uy}" x2="{a[0]+stop*ux}" y2="{a[1]+stop*uy}" stroke="{color}" stroke-width="2"/>')
  else:out.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{color}" stroke-width="2"/>')
  dx,dy=b[0]-a[0],b[1]-a[1];length=max(.001,hypot(dx,dy));ux,uy=dx/length,dy/length
  out.append(f'<polygon points="{b[0]},{b[1]} {b[0]-12*ux+5*uy},{b[1]-12*uy-5*ux} {b[0]-12*ux-5*uy},{b[1]-12*uy+5*ux}" fill="{color}"/>')
  labels=wrap(edge.label,220,14);x=(a[0]+b[0])/2;y=(a[1]+b[1])/2
  if edge.label:
   out.append(f'<rect x="{x-114}" y="{y-17}" width="228" height="{len(labels)*17+4}" fill="white" fill-opacity=".9"/>')
   for j,line in enumerate(labels):text(line,x,y+j*17,14,'middle',color)
  out.append('</g>')
 for node in graph.nodes:
  w,h=node.width,node.height;fill=FILLS[node.kind]
  out.append(f'<g data-node-id="{node.id}" transform="translate({node.x} {node.y})" tabindex="0" role="button" aria-label="{escape(node.text,quote=True)}">')
  out.append(f'<title>{escape(node.text)}</title>')
  stroke='#E88900' if node.kind in ('note','document') else '#111111'
  if node.kind in ('start','end','number'):
   out.append(f'<ellipse cx="{w/2}" cy="{h/2}" rx="{w/2}" ry="{h/2}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
  elif node.kind=='document':
   out.append(f'<path d="M0,0 L{w-18},0 L{w},18 L{w},{h} L0,{h} Z M{w-18},0 L{w-18},18 L{w},18" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
  else:
   radius=18 if node.kind in ('department','dept_in','dept_out','and','or','date','note') else 0
   out.append(f'<rect width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"'+(' stroke-dasharray="7 4"' if node.kind=='note' else '')+'/>')
  lines=node_lines(node);line_height=node.font_size*1.22
  first=max(node.font_size+8,(h-len(lines)*line_height)/2+node.font_size)
  for i,line in enumerate(lines):
   left=node.kind in ('action','note','document')
   if node.kind=='action' and line.strip():
    text('•',7,first+i*line_height,node.font_size,fill='#0000CC')
   text(line,18 if left else w/2,first+i*line_height,node.font_size,'start' if left else 'middle','#FFFFFF' if node.kind=='date' else '#111111')
  for x,label in role_badges(graph,node):
   out.append(f'<rect x="{x-28}" y="-13" width="56" height="24" rx="12" fill="white" stroke="black" stroke-width="2"/>');text(label,x,5,16,'middle')
  if node.number is not None:
   out.append(f'<ellipse cx="{w-4}" cy="{h-1}" rx="14" ry="14" fill="white" stroke="black"/>');text(str(node.number),w-4,h+4,14,'middle')
  if node.id==selected:out.append(f'<rect x="-5" y="-5" width="{w+10}" height="{h+10}" fill="none" stroke="#1678B5" stroke-width="3" stroke-dasharray="7 4"/>')
  out.append('</g>')
 out.append('</svg>');return ''.join(out)


def png(graph,title=''):
 with fitz.open(stream=svg(graph,title).encode('utf-8'),filetype='svg') as doc:
  return doc[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False).tobytes('png')
