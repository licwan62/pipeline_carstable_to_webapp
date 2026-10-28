// node tests/acceptance/market_potential_browser.cjs --url http://127.0.0.1:8766/ --out reports/market-potential/browser.json
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.SIZE_MATCH_PLAYWRIGHT || path.resolve(__dirname, '../../../4Afitment/scrapers/4afitment/node_modules/playwright'));
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, values) => i % 2 ? pairs : [...pairs, [value.replace(/^--/, ''), values[i + 1]]], []));
const base = args.url || 'http://127.0.0.1:8766/';
const out = args.out || 'reports/market-potential/browser.json';
fs.mkdirSync(path.dirname(out), { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  const errors = [], results = [];
  page.on('pageerror', error => errors.push(error.message));
  const ready = () => page.waitForSelector('.search-summary[data-status="ready"]', { timeout: 60000 });
  const open = async (query, mode = 'full', source = 'US') => {
    await page.goto(`${base}size-match.html?q=${encodeURIComponent(query)}&view=${mode}`);
    await ready();
    if (source !== 'US') {
      if (['EU', 'RU'].includes(source)) await page.click(`[data-sidebar-source="${source}"]`);
      else await page.selectOption('[data-lazy-source]', source);
      await ready();
    }
  };
  const launch = async () => {
    await page.click('[data-evolution-launch]');
    await page.waitForSelector('[data-evo-chart] canvas', { timeout: 30000 });
  };
  const chart = () => page.evaluate(() => {
    const option = echarts.getInstanceByDom(document.querySelector('[data-evo-chart]')).getOption();
    return { titles: option.title.map(t => t.text), series: option.series.map(s => ({ id:s.id, data:s.data })), axes: option.xAxis.map(a => a.type) };
  });
  const check = async (name, run) => {
    try { await run(); results.push({ name, status:'passed' }); console.log(`PASS ${name}`); }
    catch (error) { results.push({ name, status:'failed', error:error.message }); console.error(`FAIL ${name}: ${error.message}`); }
  };
  try {
    await check('full table: decimal potential, numeric sorting/filter, summary', async () => {
      await open('toyota camry');
      assert.ok(await page.locator('th[data-col-key="市场潜力"]').count());
      assert.match(await page.locator('.search-summary').innerText(), /市场潜力合计/);
      await page.click('[data-size-sort-toggle="市场潜力"]');
      const values = await page.locator('.potential-cell').allTextContents();
      const numbers = values.map(v => Number(v.replace(/,/g, '')));
      assert.ok(numbers.length > 1);
      assert.deepEqual(numbers, [...numbers].sort((a,b) => a-b));
      await page.click('[data-size-open-filter="市场潜力"]');
      assert.ok(await page.locator('[data-size-range-filter="市场潜力"]').count() === 2);
      await page.press('[data-size-range-filter="市场潜力"][data-range-side="min"]', 'Escape');
      await page.click('[data-size-open-filter="市场潜力"]');
    });
    await check('default potential bars: unique records, full width, legend below', async () => {
      await launch();
      assert.equal(await page.getAttribute('[data-evo-metric="potential"]', 'aria-pressed'), 'true');
      const option = await chart();
      const bars = option.series.find(s => s.id === 'market-potential');
      assert.ok(bars.data.length > 1);
      assert.equal(new Set(bars.data.map(d => d.meta.recordKey)).size, bars.data.length);
      assert.ok(option.axes.includes('category'));
      const width = await page.locator('[data-evo-chart-wrap]').boundingBox();
      const main = await page.locator('.evo-main').boundingBox();
      const legend = await page.locator('.evo-legend-panel').boundingBox();
      assert.ok(width.width >= main.width - 2);
      assert.ok(legend.y >= width.y + width.height);
      await page.screenshot({ path: path.join(path.dirname(out), 'desktop.png') });
    });
    await check('bar tooltip and record locking include potential breakdown and ID', async () => {
      await page.locator('[data-evo-chart]').scrollIntoViewIfNeeded();
      const point = await page.evaluate(() => {
        const el = document.querySelector('[data-evo-chart]'), instance = echarts.getInstanceByDom(el);
        const option = instance.getOption(), series = option.series.find(s => s.id === 'market-potential');
        const x = instance.convertToPixel({ xAxisIndex:series.xAxisIndex }, 0);
        const y = instance.convertToPixel({ yAxisIndex:series.yAxisIndex }, series.data[0].value / 2);
        const rect = el.getBoundingClientRect();
        return { x:rect.x+x, y:rect.y+y };
      });
      await page.mouse.move(point.x, point.y);
      await page.waitForSelector('[data-evo-tooltip]:not([hidden])');
      assert.match(await page.locator('[data-evo-tooltip]').innerText(), /销量潜力调整/);
      assert.match(await page.locator('[data-evo-tooltip]').innerText(), / US/);
      await page.mouse.click(point.x, point.y);
      assert.match(await page.locator('[data-evo-detail]').innerText(), /已锁定记录/);
    });
    await check('metric switching preserves annual sales and year-window potential is not multiplied', async () => {
      const before = (await chart()).series.find(s => s.id === 'market-potential').data;
      await page.click('[data-evo-metric="sales"]');
      await page.waitForFunction(() => echarts.getInstanceByDom(document.querySelector('[data-evo-chart]')).getOption().series.some(s => s.id.startsWith('sales|')));
      assert.ok((await chart()).titles.includes('年度预估销量（辆）'));
      await page.fill('[data-evo-year="from"]','2020');
      await page.fill('[data-evo-year="to"]','2026');
      await page.press('[data-evo-year="to"]','Enter');
      await page.click('[data-evo-metric="potential"]');
      const after = (await chart()).series.find(s => s.id === 'market-potential').data;
      assert.ok(after.length < before.length);
      const expected = new Map(before.map(d => [d.meta.recordKey,d.value]));
      for (const item of after) assert.equal(item.value, expected.get(item.meta.recordKey));
      await page.click('[data-evo-year-reset]');
      await page.click('[data-evo-legend-only]');
      assert.match(await page.locator('.evo-legend-count').innerText(), /已显示 1/);
      await page.click('[data-evo-fullscreen]');
      assert.equal(await page.getAttribute('[data-evo-fullscreen]','aria-pressed'),'true');
      await page.click('[data-evo-fullscreen]');
      await page.click('[data-evo-close]');
    });
    await check('compressed and store tables publish potential and visualize full history', async () => {
      await open('toyota camry','compressed');
      assert.ok(await page.locator('.potential-cell').count());
      await launch();
      assert.ok((await chart()).series.some(s=>s.id==='market-potential'));
      await page.click('[data-evo-close]');
      await open('toyota camry','full','HNT');
      await launch();
      assert.ok((await chart()).series.some(s=>s.id==='market-potential'));
      await page.click('[data-evo-close]');
    });
    await check('multi-model and pickup configuration controls remain available', async () => {
      await open('toyota');
      await page.click('[data-evolution-launch]');
      await page.locator('[data-picker-index]').nth(0).check();
      await page.locator('[data-picker-index]').nth(1).check();
      await page.click('[data-picker-confirm]');
      await page.waitForSelector('[data-evo-chart] canvas');
      assert.match(await page.locator('#evo-title').innerText(), /2 个车型/);
      await page.click('[data-evo-close]');
      await open('ford f150');
      await launch();
      assert.match(await page.locator('.evo-top-filters').innerText(), /CAB/);
      assert.ok((await chart()).series.find(s=>s.id==='market-potential').data.length);
      await page.click('[data-evo-close]');
    });
    await check('EU has no invented potential values', async () => {
      await open('bmw 7','full','EU');
      await launch();
      assert.match(await page.locator('[data-evo-sales-status]').innerText(), /暂无同口径市场潜力/);
      assert.ok(!(await chart()).series.some(s=>s.id==='market-potential'));
      await page.click('[data-evo-close]');
    });
    await check('annual sales loading failure can be retried after metric switch', async () => {
      await page.route('**/sales-year-data*', route => route.abort());
      await open('toyota camry');
      await launch();
      await page.click('[data-evo-metric="sales"]');
      await page.waitForSelector('[data-evo-sales-retry]');
      await page.unroute('**/sales-year-data*');
      await page.click('[data-evo-sales-retry]');
      await page.waitForFunction(() => echarts.getInstanceByDom(document.querySelector('[data-evo-chart]')).getOption().series.some(s => s.id.startsWith('sales|')));
      await page.click('[data-evo-close]');
    });
    await check('390px viewport: full-width plot, collapsible legend, no document overflow', async () => {
      await page.setViewportSize({width:390,height:844});
      await open('toyota camry');
      await launch();
      const overflow = await page.evaluate(() => document.querySelector('.evo-dialog').scrollWidth > 390);
      assert.equal(overflow,false);
      const chartWidth = await page.locator('[data-evo-chart]').boundingBox();
      assert.ok(chartWidth.width > 340);
      await page.locator('[data-evo-chart]').scrollIntoViewIfNeeded();
      await page.screenshot({ path:path.join(path.dirname(out),'narrow.png') });
      await page.click('.evo-legend-panel > summary');
      assert.equal(await page.locator('.evo-legend-panel').getAttribute('open'),null);
    });
    await check('no browser script errors', async () => assert.deepEqual(errors,[]));
  } finally {
    await browser.close();
    fs.writeFileSync(out, JSON.stringify({ base, results, errors },null,2));
  }
  if (results.some(r=>r.status!=='passed')) process.exitCode=1;
})().catch(error=>{ console.error(error);process.exitCode=1; });
