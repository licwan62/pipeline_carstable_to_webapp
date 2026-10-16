// 尺码配对页浏览器验收（Playwright 无头 Chromium）：在真实页面上操作「视图」切换、全局搜索、来源展开与列筛选。
// node tests/acceptance/size_match_browser.cjs --url http://127.0.0.1:8000/ --site <同一站点目录> [--out <结果 JSON>]
// Playwright 模块：环境变量 SIZE_MATCH_PLAYWRIGHT（模块目录），否则依次尝试本仓库 node_modules 与 ../4Afitment 的安装；找不到时退出码 3。
// 需求编号见 docs/size-match-acceptance.md。期望数量由同一站点数据按页面规则算出（size_match_lib.cjs），与页面显示逐项比较。
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { readJson, Site } = require("./size_match_lib.cjs");

const ROOT = path.resolve(__dirname, "..", "..");
const PLAYWRIGHT_CANDIDATES = [
  process.env.SIZE_MATCH_PLAYWRIGHT,
  "playwright",
  path.join(ROOT, "..", "4Afitment", "scrapers", "4afitment", "node_modules", "playwright")
].filter(Boolean);
// 本地预览没有 NAS 上的多项目登记文件，404 属预期
const EXPECTED_404 = /_publishers\/registry\.json/;

function args() {
  const result = {};
  for (let index = 2; index < process.argv.length; index += 2) result[process.argv[index].replace(/^--/, "")] = process.argv[index + 1];
  if (!result.url || !result.site) throw new Error("--url and --site are required");
  result.scenarios = result.scenarios || path.join(__dirname, "size-match-scenarios.json");
  return result;
}

function loadPlaywright() {
  for (const candidate of PLAYWRIGHT_CANDIDATES) {
    try {
      return require(candidate);
    } catch (error) {
      // 试下一个
    }
  }
  return null;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

// 页面在结果摘要上标注 data-status（idle/loading/ready/error），只有 ready 才是加载完成后的结果
async function waitReady(page) {
  await page.waitForSelector('.search-summary[data-status="ready"]', { timeout: 60000 });
}

async function summaryCount(page) {
  const text = await page.locator(".search-summary").innerText();
  const match = /匹配结果：([\d,]+)/.exec(text);
  return match ? Number(match[1].replace(/,/g, "")) : (/未找到/.test(text) ? 0 : NaN);
}

// 表格当前页每行的 MAKE/MODEL（按表头 data-col-key 定位列）
async function tableRows(page) {
  return page.evaluate(() => {
    const keys = Array.from(document.querySelectorAll(".size-results-table thead th")).map((th) => th.dataset.colKey || "");
    return Array.from(document.querySelectorAll(".size-results-table tbody tr.copyable-result-row")).map((tr) => {
      const cells = Array.from(tr.children).map((td) => td.textContent.replace(/\s+/g, " ").trim());
      return { make: cells[keys.indexOf("MAKE")] || "", model: cells[keys.indexOf("MODEL")] || "" };
    });
  });
}

async function activeMode(page) {
  return page.locator('[data-table-mode][aria-pressed="true"]').getAttribute("data-table-mode");
}

async function openScenario(page, base, scenario, mode) {
  const url = new URL("size-match.html", base);
  url.searchParams.set("view", mode);
  url.searchParams.set("q", scenario.query);
  await page.goto(url.href);
  await waitReady(page);
  if (scenario.source && scenario.source !== "US") {
    await page.click(`[data-sidebar-source="${scenario.source}"]`);
    await waitReady(page);
  }
  if (scenario.kind === "pick" && !(await page.locator('[data-vehicle-kind="pick"][aria-pressed="true"]').count())) {
    await page.click('[data-vehicle-kind="pick"]');
    await waitReady(page);
  }
}

async function run() {
  const options = args();
  const playwright = loadPlaywright();
  if (!playwright) {
    console.error(`找不到 Playwright（试过：${PLAYWRIGHT_CANDIDATES.join("、")}）；设置 SIZE_MATCH_PLAYWRIGHT 指向 playwright 模块目录`);
    process.exit(3);
  }
  const site = new Site(path.resolve(options.site));
  const scenarios = readJson(options.scenarios);
  const results = [];
  const check = async (id, requirement, title, body) => {
    try {
      const detail = await body();
      results.push({ id, requirement, title, status: "pass", detail: detail || "" });
    } catch (error) {
      results.push({ id, requirement, title, status: "fail", detail: error.message.split("\n")[0] });
    }
  };

  const browser = await playwright.chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const requests = [];
  const problems = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error" && !EXPECTED_404.test(message.location()?.url || "")) problems.push(`console: ${message.text()}`);
  });
  page.on("response", (response) => { if (response.status() >= 400 && !EXPECTED_404.test(response.url())) problems.push(`${response.status()} ${response.url()}`); });

  try {
    await check("B1", "R1", "页面有「视图」切换（压缩表 / 全量表），默认压缩表", async () => {
      await page.goto(new URL("size-match.html", options.url).href);
      await waitReady(page);
      const labels = await page.locator("[data-table-mode]").allInnerTexts();
      assert(labels.join("|") === "压缩表|全量表", `视图按钮：${labels.join("|")}`);
      assert((await activeMode(page)) === "compressed", `默认视图：${await activeMode(page)}`);
      return labels.join(" / ");
    });

    await check("B2", "R2", "两种视图读同一份数据：切换视图不再下载数据，全程没有请求旧的 size-match-code / size-match-full", async () => {
      const url = new URL("size-match.html", options.url);
      url.searchParams.set("q", "bmw 7");
      await page.goto(url.href);
      await waitReady(page);
      const before = requests.length;
      await page.click('[data-table-mode="full"]');
      await page.waitForSelector('[data-table-mode="full"][aria-pressed="true"]');
      await waitReady(page);
      await page.click('[data-table-mode="compressed"]');
      await waitReady(page);
      const during = requests.slice(before).filter((item) => /\/data\//.test(item));
      assert(!during.length, `切换视图时又请求了数据：${during[0]}`);
      const legacy = requests.filter((item) => /size-match-(code|full)/.test(item));
      assert(!legacy.length, `请求了旧数据：${legacy[0]}`);
      return `切换前已请求 ${requests.filter((item) => /size-match-data/.test(item)).length} 个数据文件，切换时 0 个`;
    });

    await check("B3", "R1", "切换视图保留搜索词与类别，URL 记录视图（?view=），刷新后保持", async () => {
      const url = new URL("size-match.html", options.url);
      url.searchParams.set("q", "ford f150");
      await page.goto(url.href);
      await waitReady(page);
      await page.click('[data-vehicle-kind="pick"]');
      await waitReady(page);
      await page.click('[data-table-mode="full"]');
      await waitReady(page);
      assert(new URL(page.url()).searchParams.get("view") === "full", `URL：${page.url()}`);
      assert((await page.inputValue(".global-search-input")) === "ford f150", "搜索词丢失");
      assert(await page.locator('[data-vehicle-kind="pick"][aria-pressed="true"]').count(), "类别被重置");
      await page.goto(page.url());
      await waitReady(page);
      assert((await activeMode(page)) === "full", "刷新后视图未保持");
      return page.url().replace(options.url, "");
    });

    for (const scenario of scenarios.searches) {
      await check(scenario.id, scenario.requirement, `${scenario.title}（页面 ${scenario.source}/${scenario.kind}「${scenario.query}」）`, async () => {
        const counts = [];
        for (const mode of ["compressed", "full"]) {
          await openScenario(page, options.url, scenario, mode);
          assert((await activeMode(page)) === mode, `视图不是 ${mode}`);
          const count = await summaryCount(page);
          assert(count > 0, `${mode} 视图没有结果`);
          if (!scenario.browser_only) {
            const expected = site.search(site.views(scenario.source, scenario.kind)[mode], scenario.query).length;
            assert(count === expected, `${mode} 视图页面 ${count} 条，数据规则应为 ${expected} 条`);
          }
          const rows = await tableRows(page);
          const stray = rows.filter((row) => !scenario.expect.makes.includes(row.make) || !scenario.expect.models.includes(row.model));
          assert(!stray.length, `${mode} 视图出现上下文之外的车型：${stray[0]?.make} ${stray[0]?.model}`);
          // 列筛选的候选项也只有上下文内的车型
          await page.click('[data-size-open-filter="MODEL"]');
          const options_ = await page.locator('input[data-size-multi-filter="MODEL"]').evaluateAll((inputs) => inputs.map((input) => input.value).filter(Boolean));
          const strayOptions = options_.filter((value) => !scenario.expect.models.includes(value));
          assert(!strayOptions.length, `${mode} 视图 MODEL 筛选出现：${strayOptions.join(", ")}`);
          await page.keyboard.press("Escape");
          counts.push(`${mode === "compressed" ? "压缩" : "全量"} ${count}`);
        }
        return counts.join(" · ");
      });
    }

    await check("B4", "R4", "压缩表点 CODE 展开来源车型各年份，来源行属于同一车型", async () => {
      const url = new URL("size-match.html", options.url);
      url.searchParams.set("q", "bmw 7");
      await page.goto(url.href);
      await waitReady(page);
      const toggle = page.locator("[data-source-toggle]").first();
      const expected = Number(await toggle.locator("em").innerText());
      await toggle.click();
      await page.waitForSelector("tr.source-detail-row");
      const ids = await page.locator("tr.source-detail-row").evaluateAll((rows) => rows.map((row) => row.title));
      assert(ids.length === expected, `展开 ${ids.length} 行，按钮标注 ${expected}`);
      assert(ids.every((id) => /^BMW 7 Series /.test(id)), `来源行：${ids.find((id) => !/^BMW 7 Series /.test(id))}`);
      return `${ids.length} 行来源`;
    });

    await check("B5", "R5", "页面无脚本错误与失败请求（本地缺少 NAS 登记文件除外）", async () => {
      assert(!problems.length, problems.slice(0, 3).join("；"));
      return `${requests.length} 个请求`;
    });
  } finally {
    await browser.close();
  }

  for (const result of results) {
    console.log(`${result.status === "pass" ? "PASS" : "FAIL"} ${result.id} [${result.requirement}] ${result.title}${result.detail ? ` — ${result.detail}` : ""}`);
  }
  if (options.out) fs.writeFileSync(options.out, JSON.stringify({ layer: "browser", results }, null, 1));
  process.exitCode = results.every((result) => result.status === "pass") ? 0 : 1;
}

run().catch((error) => {
  console.error(error);
  process.exit(2);
});
