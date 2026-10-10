// Run with Playwright installed locally or UI_QA_MODULE pointing to its package.
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.UI_QA_MODULE || "playwright");
const output = resolve("../.runtime/ui-qa");
const baseUrl = process.env.UI_QA_URL || "http://127.0.0.1:5173/";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: [
    "--enable-webgl",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
  ],
});
const results = [];
try {
  for (const [width, height] of [
    [1920, 1080],
    [1440, 900],
    [768, 1024],
    [390, 844],
  ]) {
    const context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage(),
      errors = [];
    console.log(`${width}×${height}: loading actual model`);
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(baseUrl);
    await page
      .waitForFunction(
        () => document.querySelector("h1")?.textContent?.includes("에너지"),
        {},
        { timeout: 60000 },
      )
      .catch(async (e) => {
        await page.screenshot({ path: resolve(output, "load-error.png") });
        console.log(await page.locator("body").innerText(), errors);
        throw e;
      });
    await page.locator(".viewer canvas").waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(1000);
    const metrics = await page.evaluate(() => ({
      width: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      headerBottom: document.querySelector('.header').getBoundingClientRect().bottom,
      modeBottom: document.querySelector('.mode-switch').getBoundingClientRect().bottom,
      projectTop: document.querySelector('.project-bar').getBoundingClientRect().top,
      canvas: document
        .querySelector(".viewer canvas")
        .getBoundingClientRect()
        .toJSON(),
    }));
    assert(metrics.scrollWidth <= width, `horizontal overflow at ${width}`);
    assert(metrics.modeBottom <= metrics.headerBottom, `mode switch outside header at ${width}`);
    assert(metrics.projectTop >= metrics.headerBottom, `header overlaps project at ${width}`);
    assert(metrics.canvas.height >= 280, `viewer too short at ${width}`);
    await page.screenshot({
      path: resolve(output, `bim-${width}x${height}.png`),
      fullPage: true,
    });
    await page.getByRole("button", { name: "표시 설정", exact: true }).click();
    await page.getByRole("checkbox", { name: "벽체 표시" }).uncheck();
    await page.getByRole("checkbox", { name: "벽체 표시" }).check();
    await page.getByRole("checkbox", { name: "실 영역", exact: true }).check();
    await page.keyboard.press("Escape");
    console.log(`${width}: display checked`);
    assert.equal(await page.locator("#display-options").count(), 0);
    await page
      .getByRole("button", { name: "단면 · 층 분리", exact: true })
      .click();
    await page.getByLabel("단면 방향", { exact: true }).selectOption("x");
    await page.getByLabel("단면 위치", { exact: true }).fill("65");
    await page.getByLabel("층 분리 간격", { exact: true }).fill("4");
    await page.getByRole("button", { name: "단면 · 분리 초기화" }).click();
    assert.equal(
      await page.getByLabel("단면 방향", { exact: true }).inputValue(),
      "none",
    );
    await page.keyboard.press("Escape");
    console.log(`${width}: section checked`);
    await page.getByRole("button", { name: "평면", exact: true }).click();
    await page.getByRole("button", { name: "3D", exact: true }).click();
    await page.getByLabel("표시 층").selectOption("all");
    await page.getByRole("button", { name: "전체 맞춤", exact: true }).click();
    await page.getByLabel("표시 층").selectOption("f1");
    if (width <= 1100)
      await page
        .getByRole("button", { name: "객체 탐색", exact: true })
        .click();
    await page.getByLabel("건축 요소 종류").selectOption("column");
    await page.locator(".object-row").first().click();
    assert(await page.locator(".object-id").textContent());
    await page.getByRole('button',{name:'객체 형상 · 속성 편집',exact:true}).click();
    await page.getByRole('dialog').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog').count(),0);
    if (width <= 1100) {
      await page.screenshot({
        path: resolve(output, `inspector-${width}.png`),
      });
      await page.getByRole("button", { name: "속성 패널 닫기" }).click();
      await page
        .getByRole("button", { name: "속성 · 근거", exact: true })
        .click();
    }
    await page
      .getByLabel("BIM 건축물")
      .selectOption({ label: "공간이음 교육관 · 2층 예제" });
    if (width <= 1100)
      await page.getByRole("button", { name: "속성 패널 닫기" }).click();
    await page
      .getByRole("button", { name: "BF 경로 탐색", exact: true })
      .click();
    if (width <= 1100)
      await page
        .getByRole("button", { name: "경로 설정", exact: true })
        .click();
    await page.getByRole("button", { name: "세부 이동 조건" }).click();
    assert.equal(
      await page.locator(".conditions input[type=number]").count(),
      7,
    );
    await page.getByRole("button", { name: "세부 이동 조건" }).click();
    await page.getByRole("button", { name: "경로 탐색", exact: true }).click();
    await page
      .getByText("조건 충족 경로", { exact: true })
      .waitFor({ timeout: 30000 });
    const route = await page.locator(".result-metrics").innerText();
    if (width <= 1100)
      await page.getByRole("button", { name: "속성 패널 닫기" }).click();
    await page.waitForFunction(()=>!document.querySelector('.toast')?.textContent);
    await page.screenshot({
      path: resolve(output, `route-${width}.png`),
      fullPage: true,
    });
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "JSON", exact: true }).click();
    const download = await downloadPromise;
    await download.saveAs(resolve(output, `model-${width}.json`));
    const stream = await download.createReadStream();
    let text = "";
    for await (const chunk of stream) text += chunk;
    const exported = JSON.parse(text),
      source = await (
        await context.request.get(new URL('models/demo.json',baseUrl).href)
      ).json();
    assert.deepEqual(
      exported.elements.map((e) => [e.id, e.polygon, e.height]),
      source.elements.map((e) => [e.id, e.polygon, e.height]),
    );
    assert.equal(exported.revision, source.revision);
    assert.equal(errors.length, 0, errors.join("\n"));
    results.push({
      width,
      height,
      metrics,
      route,
      runtimeErrors: errors,
      checks:
        "display, section, floor, object, route, JSON geometry preservation",
    });
    console.log(`${width}×${height}: passed`);
    await context.close();
  }
  await writeFile(
    resolve(output, "results.json"),
    JSON.stringify(results, null, 2),
  );
} finally {
  await browser.close();
}
