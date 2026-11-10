// Local SVG rendering and PNG export. No CDN, network fetch or chart dependency.
(() => {
  const source = document.getElementById('incident-chart-data');
  if (!source) return;
  const data = JSON.parse(source.textContent);
  const select = document.getElementById('visual-type');
  const mode = document.getElementById('visual-mode');
  const host = document.getElementById('visual-canvas');
  const feedback = document.getElementById('visual-feedback');
  const download = document.getElementById('visual-png');
  const colors = ['#166a64','#4873ae','#b57924','#805ba5','#b84e62','#33838e','#668334','#666b78','#aa673c'];
  const NS = 'http://www.w3.org/2000/svg';
  const W = 1100, left = 400, span = 620;
  let svg, exporting = false;
  function node(tag, attrs = {}, text) {
    const el = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function put(tag, attrs, text, parent = svg) {
    const el = node(tag, attrs, text); parent.append(el); return el;
  }
  function words(value, width) {
    const result = [];
    let line = '';
    for (const word of String(value).split(/\s+/)) {
      if (line && (line + ' ' + word).length > width) { result.push(line); line = ''; }
      for (let start = 0; start < word.length; start += width) {
        const part = word.slice(start, start + width);
        if (start || (line && line.length + part.length + 1 > width)) { if (line) result.push(line); line = ''; }
        line += (line ? ' ' : '') + part;
      }
    }
    if (line) result.push(line);
    return result.length ? result : [''];
  }
  function label(value, x, y, width = 43, size = 13) {
    const lines = words(value, width);
    lines.forEach((line, i) => put('text', {x, y: y + i * 17, fill:'#24354b', 'font-size':size}, line));
    return lines.length * 17;
  }
  function mark(tag, attrs, title, href) {
    const parent = href ? put('a', {href, 'aria-label': title}) : svg;
    const el = put(tag, attrs, undefined, parent);
    put('title', {}, title, el);
    return el;
  }
  function table(chart) {
    const holder = document.getElementById('visual-table'); holder.replaceChildren();
    const el = document.createElement('table');
    const head = document.createElement('thead'), tr = document.createElement('tr');
    ['Категория', ...(chart.columns || chart.series)].forEach(text => {
      const th = document.createElement('th'); th.textContent = text; tr.append(th);
    });
    head.append(tr); el.append(head);
    const body = document.createElement('tbody');
    chart.rows.forEach(row => {
      const tr = document.createElement('tr');
      [row.label, ...row.values].forEach(text => { const td = document.createElement('td'); td.textContent = text; tr.append(td); });
      body.append(tr);
    });
    el.append(body); holder.append(el);
  }
  function draw() {
    const chart = data.charts.find(item => item.id === select.value) || data.charts[0];
    feedback.textContent = '';
    document.getElementById('visual-note').textContent = chart.note;
    document.getElementById('visual-mode-wrap').hidden = chart.type !== 'stack';
    svg = node('svg', {width: W, role:'img', 'aria-label': chart.title, 'font-family':'Segoe UI, Arial, sans-serif'});
    svg.append(node('rect', {x:0, y:0, width:'100%', height:'100%', fill:'#ffffff'}));
    host.replaceChildren(svg);
    put('title', {}, chart.title);
    put('desc', {}, chart.note + ' ' + data.context);
    let y = 35;
    y += label(chart.title, 20, y, 100, 20) + 12;
    y += label(data.context, 20, y, 135, 12) + 12;
    if (!chart.rows.length || !chart.rows.some(row => row.values.some(value => value > 0))) {
      y += label('Нет записей для этого графика. Для сравнения периодов задайте второй период.', 20, y, 100);
    } else if (chart.type === 'pareto') {
      const top = y + 30, bottom = top + 210, step = span / chart.rows.length;
      const max = Math.max(...chart.rows.map(row => row.values[0]), 1);
      put('text', {x:40, y:y+10, fill:'#24354b', 'font-size':12}, 'Количество: 0–' + max);
      put('text', {x:690, y:y+10, fill:'#24354b', 'font-size':12}, 'Накопленная доля: 0–100%');
      const points = [];
      chart.rows.forEach((row, i) => {
        const x = 70 + i * step, height = row.values[0] / max * 210;
        mark('rect', {x, y:bottom-height, width:step*.65, height, fill:colors[0]},
          row.label + ': ' + row.values[0] + '; накоплено ' + row.values[1] + '%', row.hrefs?.[0]);
        put('text', {x, y:bottom+22, fill:'#24354b', 'font-size':12}, i+1);
        points.push((x+step*.325)+','+(bottom-row.values[1]*2.1));
      });
      put('line', {x1:60,y1:bottom,x2:730,y2:bottom,stroke:'#64748b'});
      put('line', {x1:60,y1:bottom-chart.threshold*2.1,x2:730,y2:bottom-chart.threshold*2.1,stroke:'#b57924','stroke-dasharray':'5 4'});
      put('polyline', {points:points.join(' '),fill:'none',stroke:colors[1],'stroke-width':3,'pointer-events':'none'});
      [0,50,100].forEach(n => put('text',{x:745,y:bottom-n*2.1+4,fill:'#24354b','font-size':12},n+'%'));
      y = bottom + 55;
      chart.rows.forEach((row,i) => { const text = row.label.length > 180 ? row.label.slice(0,180)+'… (полный текст в таблице)' : row.label;
        y += label((i+1)+'. '+text,20,y,125,12)+5; });
    } else {
      const isHeat = chart.type === 'heat', stacked = chart.type === 'stack';
      const max = Math.max(1, ...chart.rows.flatMap(row => stacked ? [row.values.reduce((a,b)=>a+b,0)] : row.values));
      const percent = stacked && mode.value === 'percent';
      y += label(isHeat ? 'Количество: от 0 до '+max+'; темнее — больше.' : (percent ? 'Шкала: 0–100% внутри категории' : 'Шкала количества: 0–'+max),20,y,120,12)+12;
      if (isHeat) chart.columns.forEach((_,i) => put('text',{x:left+i*span/chart.columns.length+5,y,fill:'#24354b','font-size':12},i+1));
      y += isHeat ? 25 : 5;
      for (const row of chart.rows) {
        const lineHeight = Math.max(42, words(row.label,43).length*17+12);
        label(row.label,20,y+15);
        const total = row.values.reduce((a,b)=>a+b,0);
        let offset=0;
        row.values.forEach((count,i) => {
          const series = (chart.columns || chart.series)[i];
          const share = total ? count/total*100 : 0;
          const title = row.label+' · '+series+': '+count+(stacked ? ' ('+share.toFixed(2)+'%)' : '');
          let x,ypos,width,height,fill;
          if (isHeat) {
            const cell = span / chart.columns.length;
            x=left+i*cell;ypos=y;width=cell-2;height=lineHeight-4;
            fill=count ? `rgb(${Math.round(235-213*count/max)},${Math.round(246-140*count/max)},${Math.round(244-144*count/max)})` : '#f1f5f9';
          } else if (stacked) {
            width=(percent ? share/100 : count/max)*span;x=left+offset;offset+=width;ypos=y+4;height=24;fill=colors[i%colors.length];
          } else {
            x=left;width=count/max*span;ypos=y+i*22;height=17;fill=colors[i%colors.length];
          }
          // Zero cells remain clickable without suggesting nonzero bars.
          mark('rect',{x,y:ypos,width,height,fill,stroke:isHeat?'#e4e9f0':'none'},title,row.hrefs?.[i]);
          if (isHeat) put('text',{x:x+width/2,y:ypos+height/2+4,'text-anchor':'middle','font-size':11,fill:count/max>.55?'#ffffff':'#24354b','pointer-events':'none'},count);
          else if (!stacked) put('text',{x:Math.min(x+width+6,1060),y:ypos+13,fill:'#24354b','font-size':12},count);
        });
        if (stacked) put('text',{x:1030,y:y+21,fill:'#24354b','font-size':12},percent ? '100%' : total);
        y += Math.max(lineHeight, !isHeat && !stacked ? row.values.length*22+10 : 42);
      }
      y += 20;
      (chart.columns || chart.series).forEach((name,i) => {
        if (!isHeat) put('rect',{x:20,y:y-11,width:12,height:12,fill:colors[i%colors.length]});
        y += label((isHeat ? (i+1)+'. ' : '')+name, isHeat?20:42, y,125,12)+6;
      });
    }
    y += 15;
    y += label(chart.note,20,y,130,12)+20;
    svg.setAttribute('height',y); svg.setAttribute('viewBox',`0 0 ${W} ${y}`);
    download.disabled = exporting;
    table(chart);
  }
  select.addEventListener('change', draw); mode.addEventListener('change',draw);
  download.addEventListener('click', async () => {
    const exportId = select.value;
    exporting=true;download.disabled=true;feedback.textContent='Готовим PNG…';
    let objectURL;
    try {
      const clone = svg.cloneNode(true);
      clone.querySelectorAll('a').forEach(el => el.removeAttribute('href'));
      const image = new Image();
      objectURL=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)],{type:'image/svg+xml;charset=utf-8'}));
      await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src=objectURL;});
      const width=Number(clone.getAttribute('width')),height=Number(clone.getAttribute('height'));
      const scale=Math.min(2,16000/height,Math.sqrt(16000000/(width*height)));
      const canvas=document.createElement('canvas');canvas.width=Math.round(width*scale);canvas.height=Math.round(height*scale);
      const context=canvas.getContext('2d');if(!context)throw new Error('canvas');
      context.drawImage(image,0,0,canvas.width,canvas.height);
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw new Error('png');
      const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='qms-incidents-'+exportId+'.png';a.click();
      setTimeout(()=>URL.revokeObjectURL(url),10000);feedback.textContent='PNG сохранён через загрузки браузера.';
    } catch (_) {feedback.textContent='Не удалось сохранить PNG. Попробуйте другой браузер или используйте таблицы Excel.';}
    finally {if(objectURL)URL.revokeObjectURL(objectURL);exporting=false;download.disabled=false;}
  });
  draw();
})();
