// Responsive workspace and interaction regression checks; uses an isolated context.
// Install Playwright outside the project, then set UI_QA_MODULE to its module path.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.UI_QA_MODULE || path.join(os.tmpdir(), 'spatial-bim-qa/node_modules/playwright'));
const origin = process.env.BIM_QA_URL || 'http://127.0.0.1:4175/energy-center-bim-bf/';
const output = process.env.BIM_QA_OUTPUT || '.runtime/workspace-qa';

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const errors = [], checks = [];
  const model = JSON.parse(fs.readFileSync('web/public/models/project.json', 'utf8'));
  const record = (name) => { checks.push(name); console.log('PASS:', name); };
  const ready = async (page) => {
    await page.waitForFunction(() => {
      const canvas = document.querySelector('.viewer canvas');
      return canvas && Number(canvas.dataset.triangles) > 0 && canvas.getBoundingClientRect().width > 100 && canvas.getBoundingClientRect().height > 100;
    }, null, { timeout: 90000 });
    await page.evaluate(() => document.fonts.ready);
  };
  const watch = (page) => {
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('response', r => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  };
  const fit = async (page) => { await page.getByRole('button', { name: '전체 맞춤', exact: true }).click(); await ready(page); };
  const screenshot = async (page, name) => { await ready(page); await page.screenshot({ path: `${output}/${name}.png` }); };
  const layout = async (page) => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth || document.documentElement.scrollHeight > innerHeight), false, 'Page must stay inside the viewport');
  try {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const page = await context.newPage(); watch(page);
    await page.goto(origin);
    await page.waitForFunction(() => document.querySelector('h1')?.textContent.includes('에너지'), null, { timeout: 90000 });
    await ready(page); await layout(page);
    assert.equal(await page.getByLabel('표시 층').inputValue(), 'all');
    assert.equal(await page.getByRole('button', { name: '속성 · 근거', exact: true }).getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('.viewer canvas').getAttribute('data-model-revision'), String(model.revision));
    assert.equal(await page.locator('.viewer canvas').getAttribute('data-model-components'), String(model.elements.reduce((n, e) => n + e.components.length, 0)));
    await screenshot(page, 'desktop-first-view'); record('Desktop first view: full model, closed inspector, local font, no overflow');

    await page.locator('.level-grid button').filter({ hasText: '지상 1층' }).click(); await ready(page);
    assert.equal(await page.getByLabel('표시 층').inputValue(), 'f1');
    const object = model.elements.find(e => e.floor_id === 'f1' && e.type === 'stair' && !e.excluded);
    await page.getByLabel('객체 검색').fill(object.id);
    await page.locator('.object-row').first().click();
    assert.equal(await page.getByRole('button', { name: '속성 · 근거', exact: true }).getAttribute('aria-expanded'), 'true');
    assert((await page.locator('.architectural-properties').innerText()).includes(object.id));
    await page.getByRole('button', { name: '선택 확대', exact: true }).click();
    await screenshot(page, 'desktop-selection'); record('Floor navigation synchronizes; selection opens properties');
    const before = Number(await page.locator('.viewer canvas').getAttribute('data-triangles'));
    await page.getByRole('button', { name: '선택 객체 숨기기', exact: true }).click(); await ready(page);
    assert(Number(await page.locator('.viewer canvas').getAttribute('data-triangles')) < before);
    await page.getByRole('button', { name: '1개 숨김 · 모두 표시', exact: true }).click(); await ready(page);
    assert.equal(Number(await page.locator('.viewer canvas').getAttribute('data-triangles')), before);
    record('Object hide and restore preserve model geometry');

    await page.getByRole('button', { name: '속성 · 근거', exact: true }).click();
    await page.getByLabel('객체 검색').fill('');
    await page.getByRole('button', { name: '정면 보기', exact: true }).click(); await fit(page);
    assert.equal(await page.getByRole('button', { name: '정면 보기', exact: true }).getAttribute('aria-pressed'), 'true');
    await page.getByRole('button', { name: '사선 보기', exact: true }).click(); await fit(page); record('Quick camera directions');
    await page.getByRole('button', { name: '사용 도움말', exact: true }).click();
    assert.equal(await page.locator('.help-popover').isVisible(), true);
    await page.keyboard.press('Escape'); assert.equal(await page.locator('.help-popover').count(), 0); record('Help opens and closes by keyboard');

    await page.getByLabel('BIM 건축물').selectOption({ label: '공간이음 교육관 · 2층 예제' });
    await page.getByRole('button', { name: 'BF 경로 탐색', exact: true }).click();
    const start = await page.getByLabel('출발지', { exact: true }).inputValue();
    const end = await page.getByLabel('목적지', { exact: true }).inputValue();
    await page.getByRole('button', { name: '출발지와 목적지 바꾸기' }).click();
    assert.equal(await page.getByLabel('출발지', { exact: true }).inputValue(), end);
    assert.equal(await page.getByLabel('목적지', { exact: true }).inputValue(), start);
    await page.getByRole('button', { name: '출발지와 목적지 바꾸기' }).click();
    await page.getByRole('button', { name: '경로 탐색', exact: true }).click();
    await page.getByText('조건 충족 경로', { exact: true }).waitFor({ timeout: 30000 });
    assert((await page.locator('.result-metrics').innerText()).includes('32.6'));
    assert((await page.locator('.result-metrics').innerText()).includes('71'));
    await screenshot(page, 'desktop-bf-route'); record('BF route: 32.6 m / 71 seconds; destination swap');
    await page.getByRole('button', { name: '세부 이동 조건', exact: true }).click();
    await page.getByLabel('최소 문 유효폭 (m)', { exact: true }).fill('3');
    assert.equal(await page.locator('.result-metrics').count(), 0); record('Changing mobility conditions invalidates an old route');
    await context.close();

    for (const viewport of [{ width: 390, height: 844 }, { width: 768, height: 1024 }, { width: 360, height: 740 }]) {
      const mobile = await browser.newContext({ viewport, isMobile: true, hasTouch: true });
      const mp = await mobile.newPage(); watch(mp);
      await mp.goto(origin);
      await mp.waitForFunction(() => document.querySelector('h1')?.textContent.includes('에너지'), null, { timeout: 90000 });
      await ready(mp); await layout(mp); await fit(mp);
      await screenshot(mp, `responsive-${viewport.width}`);
      await mp.getByRole('button', { name: '객체 탐색', exact: true }).click();
      assert.equal(await mp.getByLabel('BIM 건축물').isVisible(), true);
      await mp.getByLabel('BIM 건축물').selectOption({ label: '공간이음 교육관 · 2층 예제' });
      await mp.getByRole('button', { name: '객체 패널 닫기' }).click();
      await mp.getByRole('button', { name: '표시 설정', exact: true }).click();
      const pop = await mp.locator('#display-options').boundingBox();
      assert(pop.x >= 0 && pop.x + pop.width <= viewport.width);
      await layout(mp); await screenshot(mp, `mobile-tools-${viewport.width}`);
      await mp.keyboard.press('Escape');
      await mp.getByRole('button', { name: 'BF 경로 탐색', exact: true }).click();
      assert.equal(await mp.getByRole('button', { name: '경로 설정', exact: true }).getAttribute('aria-expanded'), 'true');
      await mp.getByRole('button', { name: '경로 탐색', exact: true }).click();
      await mp.getByText('조건 충족 경로', { exact: true }).waitFor({ timeout: 30000 });
      await mp.locator('.result-metrics').scrollIntoViewIfNeeded();
      await screenshot(mp, `mobile-route-${viewport.width}`); await layout(mp);
      await mp.getByRole('button', { name: '속성 패널 닫기' }).click();
      assert.equal(await mp.locator('.panel-scrim').count(), 0);
      record(`Responsive ${viewport.width}px: model, tools, project drawer, BF route, scroll, close`);
      await mobile.close();
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(`${output}/results.json`, JSON.stringify({ status: 'passed', origin, checks, errors, renderBackend: 'Chrome WebGL / SwiftShader; hardware FPS not assessed' }, null, 2));
  } catch (e) {
    fs.writeFileSync(`${output}/results.json`, JSON.stringify({ status: 'failed', error: String(e), checks, errors }, null, 2));
    throw e;
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
