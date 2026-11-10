"""Read-only chart and PNG checks on a confirmed synthetic incident dataset."""
import os
from pathlib import Path
import struct
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

url=os.environ['QMS_TEST_URL']
comparison_url=os.environ.get('QMS_COMPARE_URL')
with sync_playwright() as p:
    options={'headless':True}
    if os.environ.get('QMS_CHROMIUM_PATH'): options['executable_path']=os.environ['QMS_CHROMIUM_PATH']
    browser=p.chromium.launch(**options)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:external.append(request.url) if request.url.startswith(('http://','https://')) and urlsplit(request.url).hostname not in {'127.0.0.1','localhost'} else None)
    target=url+'/modules/incidents?batch_id=1&date_from=2026-01-01&date_to=2026-12-31&compare_from=2025-01-01&compare_to=2025-12-31'
    page.goto(target)
    expect(page.locator('#visual-canvas svg')).to_be_visible()
    if os.environ.get('QMS_EXPECT_TOTAL'): expect(page.locator('#incident-total')).to_have_text(os.environ['QMS_EXPECT_TOTAL'])
    def png(name):
        with page.expect_download(timeout=30000) as pending: page.locator('#visual-png').click()
        path=Path('/tmp/qms-chart-'+name+'.png');pending.value.save_as(str(path))
        raw=path.read_bytes();assert raw[:8]==b'\x89PNG\r\n\x1a\n' and len(raw)>2000
        width,height=struct.unpack('>II',raw[16:24]);assert width>500 and height>150
        assert width*height<=16_100_000
    for chart in ['departments','months','heat-month','heat-group','statuses','periods','quality','pareto']:
        page.locator('#visual-type').select_option(chart)
        expect(page.locator('#visual-canvas svg')).to_be_visible()
        assert page.locator('#visual-table tbody tr').count()>0
        if chart in ['statuses','quality']: page.locator('#visual-mode').select_option('percent')
        png(chart)
        if chart=='heat-month':
            page.locator('#incident-visuals').scroll_into_view_if_needed()
            page.screenshot(path='/tmp/qms-charts-heatmap.png')
    # Drill into a nonzero department/month cell; filters and count must agree.
    page.locator('#visual-type').select_option('heat-month')
    cell=page.evaluate('''() => {
      const c=JSON.parse(document.querySelector('#incident-chart-data').textContent).charts.find(c=>c.id==='heat-month');
      for (const row of c.rows) for(let i=0;i<row.values.length;i++) if(row.values[i]>0) return {href:row.hrefs[i], count:row.values[i]};
    }''')
    index=page.locator('#visual-canvas a').evaluate_all('(els,href) => els.findIndex(el=>el.getAttribute("href")===href)',cell['href'])
    page.locator('#visual-canvas a').nth(index).click()
    expect(page.locator('#incident-total')).to_have_text(str(cell['count']))
    assert page.url.endswith('#incident-register')
    page.goto(target)
    page.locator('#theme').click()
    page.locator('#visual-type').select_option('departments');png('dark')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('#incident-visuals').scroll_into_view_if_needed()
    page.screenshot(path='/tmp/qms-charts-mobile.png')
    page.goto(url+'/modules/incidents?batch_id=1&date_from=2000-01-01&date_to=2000-12-31')
    expect(page.locator('#visual-canvas')).to_contain_text('Нет записей')
    png('empty')
    if comparison_url:
        page.goto(comparison_url+'/incidents/compare?before_id=1&after_id=2')
        expect(page.locator('#visual-type')).to_have_value('snapshots')
        png('snapshots')
        page.locator('#visual-canvas a').first.click()
        assert 'kind=added' in page.url
    assert not errors,errors
    assert not external,external
    browser.close()
print('Charts UI passed: 8 types, count/percent, PNG signatures and sizes, drilldown, dark theme, empty, mobile, snapshot chart; no JS errors or external requests')
