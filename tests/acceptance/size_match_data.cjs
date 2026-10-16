// 尺码配对页数据层验收：用页面自己的 viewer-data.js（与浏览器同一份代码）检查已构建站点的数据。
// node tests/acceptance/size_match_data.cjs --site <站点目录> [--a1 <A1 output 目录>] [--out <结果 JSON>]
// 需求编号见 docs/size-match-acceptance.md；构建（build_publish_site.build_staged_site）在切换 public 之前自动运行，失败即不发布。
"use strict";
const fs = require("node:fs");
const path = require("node:path");

const { MATCH_DATA, SOURCE_KINDS, TABLES, readJson, parseCsv, Site } = require("./size_match_lib.cjs");

function args() {
  const result = {};
  for (let index = 2; index < process.argv.length; index += 2) result[process.argv[index].replace(/^--/, "")] = process.argv[index + 1];
  if (!result.site) throw new Error("--site is required");
  result.scenarios = result.scenarios || path.join(__dirname, "size-match-scenarios.json");
  return result;
}

function check(results, id, requirement, title, run) {
  try {
    const detail = run();
    results.push({ id, requirement, title, status: "pass", detail: detail || "" });
  } catch (error) {
    results.push({ id, requirement, title, status: "fail", detail: error.message });
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function structureChecks(site, results) {
  const generated = path.join(site.root, "data", "generated");
  check(results, "D1", "R2", "只有一套尺码配对数据（size-match-data*），无 size-match-code*/size-match-full* 重复数据", () => {
    const duplicates = fs.readdirSync(generated).filter((name) => /^size-match-(code|full)/.test(name));
    assert(!duplicates.length, `仍发布了重复数据：${duplicates.slice(0, 3).join(", ")}`);
    const page = fs.readFileSync(path.join(site.root, "size-match.html"), "utf8");
    const paths = [...page.matchAll(/(?:matchDataPath|historyDataPath):\s*"([^"]+)"/g)].map((match) => match[1]);
    assert(paths.length >= 2 && paths.every((item) => item === MATCH_DATA), `表格与可视化历史必须读同一份 ${MATCH_DATA}：${paths.join(", ")}`);
    return `${fs.readdirSync(generated).filter((name) => name.startsWith("size-match-data")).length} 个文件`;
  });
  check(results, "D2", "R1", "每个数据源、每个类别都同时有压缩表与全量表视图", () => {
    assert(site.manifest.format_version === 4, "format_version 不是 4");
    assert(site.manifest.views?.compressed && site.manifest.views?.full, "清单未声明两种视图");
    const lines = [];
    for (const source of site.manifest.sources) {
      for (const kind of Object.keys(SOURCE_KINDS)) {
        const views = site.views(source.name, kind);
        if (!views.full.length && !views.compressed.length) continue;
        assert(views.full.length && views.compressed.length, `${source.name}/${kind} 缺少一种视图`);
        lines.push(`${source.name}/${kind} 压缩 ${views.compressed.length} · 全量 ${views.full.length}`);
      }
    }
    return lines.join("；");
  });
  check(results, "D3", "R2", "压缩记录的来源行全部由引用还原（不内嵌 A0 行），且都指向本分片的全量行", () => {
    let records = 0, refs = 0;
    for (const source of site.manifest.sources) {
      for (const kind of Object.keys(SOURCE_KINDS)) {
        const views = site.views(source.name, kind);
        const ids = new Set(views.full.map((row) => row.values["DIMENSION-ID"]));
        for (const record of views.compressed) {
          records += 1;
          assert(record.sources.length, `${source.name} ${record.make} ${record.model} ${record.year} 没有来源行`);
          for (const item of record.sources) {
            refs += 1;
            assert(ids.has(item["DIMENSION-ID"]), `${source.name} 来源行 ${item["DIMENSION-ID"]} 不在全量行中`);
          }
        }
      }
    }
    return `${records} 条压缩记录，${refs} 个来源引用`;
  });
}

// 与 A1 发布物逐条对照：页面从 refs 还原的来源行 = A1 压缩来源.csv（按记录 YEAR/SIZE/MODEL/版本 + 来源 DIMENSION-ID/YEAR/长宽高 做多重集合比较）
function a1Checks(site, a1Dir, results) {
  check(results, "D4", "R2", "页面还原的压缩来源与 A1 压缩来源.csv 逐条一致", () => {
    const a1Manifest = readJson(path.join(a1Dir, "manifest.json"));
    assert(a1Manifest.version === site.manifest.origin.version,
      `A1 版本 ${a1Manifest.version} 与站点数据 ${site.manifest.origin.version} 不同，无法对照（请对同一版本运行）`);
    const summary = [];
    for (const source of site.manifest.sources) {
      const tables = Object.fromEntries(Object.entries(TABLES).map(([kind, file]) => [kind, parseCsv(fs.readFileSync(path.join(a1Dir, source.name, file), "utf8"))]));
      const expected = new Map();
      const add = (map, key) => map.set(key, (map.get(key) || 0) + 1);
      for (const row of parseCsv(fs.readFileSync(path.join(a1Dir, source.name, "压缩来源.csv"), "utf8"))) {
        const record = tables[row["压缩类型"]][Number(row["记录序号"]) - 1];
        const size = record.BACKSIZE || record["亚马逊尺码"] || "";
        add(expected, [row["压缩类型"], record.MAKE, record.MODEL, record.VERSION || "", record.YEAR, size,
          row["DIMENSION-ID"], row.YEAR, row["L-MM"], row["W-MM"], row["H-MM"]].join("|"));
      }
      const actual = new Map();
      for (const kind of Object.keys(SOURCE_KINDS)) {
        for (const record of site.views(source.name, kind).compressed) {
          for (const item of record.sources) {
            add(actual, [SOURCE_KINDS[kind], record.make, record.model, record.values["版本"] || "", record.year, record.size,
              item["DIMENSION-ID"], item.YEAR, item["L-MM"], item["W-MM"], item["H-MM"]].join("|"));
          }
        }
      }
      const missing = [...expected].filter(([key, count]) => actual.get(key) !== count);
      const extra = [...actual].filter(([key]) => !expected.has(key));
      if (missing.length || extra.length) {
        throw new Error(`${source.name} 不一致：缺 ${missing.length}，多 ${extra.length}（如 ${(missing[0] || extra[0])[0]}）`);
      }
      summary.push(`${source.name} ${[...expected.values()].reduce((a, b) => a + b, 0)}`);
    }
    return `来源行：${summary.join("，")}`;
  });
}

function scenarioChecks(site, scenarios, results) {
  for (const scenario of scenarios.searches.filter((item) => !item.browser_only)) {
    check(results, scenario.id, scenario.requirement, `${scenario.title}（${scenario.source}/${scenario.kind}「${scenario.query}」）`, () => {
      const views = site.views(scenario.source, scenario.kind);
      const counts = {};
      for (const mode of ["compressed", "full"]) {
        const hits = site.search(views[mode], scenario.query);
        counts[mode] = hits.length;
        assert(hits.length, `${mode} 视图没有结果`);
        const strayMakes = [...new Set(hits.map((record) => record.make))].filter((make) => !scenario.expect.makes.includes(make));
        const strayModels = [...new Set(hits.map((record) => record.model))].filter((model) => !scenario.expect.models.includes(model));
        assert(!strayMakes.length && !strayModels.length, `${mode} 视图出现上下文之外的车型：${[...strayMakes, ...strayModels].join(", ")}`);
        if (scenario.expect.year) {
          assert(hits.every((record) => record.years.includes(scenario.expect.year)), `${mode} 视图有不含 ${scenario.expect.year} 年的记录`);
        }
        if (mode === "compressed") {
          // 压缩记录展开的来源车型也必须在上下文内
          const strayRows = hits.flatMap((record) => record.sources).filter((item) => !scenario.expect.models.includes(item.MODEL));
          assert(!strayRows.length, `压缩记录的来源行出现其他车型：${strayRows[0]?.MODEL}`);
        }
      }
      // 两种视图一致：全量视图命中的、有尺码的行都被压缩视图命中记录的来源行覆盖
      const covered = new Set(site.search(views.compressed, scenario.query).flatMap((record) => record.sources.map((item) => item["DIMENSION-ID"])));
      const lost = site.search(views.full, scenario.query).filter((row) => row.size && !covered.has(row.values["DIMENSION-ID"]));
      assert(!lost.length, `全量视图的 ${lost.length} 行在压缩视图中找不到（如 ${lost[0]?.values["DIMENSION-ID"]}）`);
      return `压缩 ${counts.compressed} 条 · 全量 ${counts.full} 行`;
    });
  }
}

function main() {
  const options = args();
  const site = new Site(path.resolve(options.site));
  const scenarios = readJson(options.scenarios);
  const results = [];
  structureChecks(site, results);
  if (options.a1) a1Checks(site, path.resolve(options.a1), results);
  scenarioChecks(site, scenarios, results);
  for (const result of results) {
    console.log(`${result.status === "pass" ? "PASS" : "FAIL"} ${result.id} [${result.requirement}] ${result.title}${result.detail ? ` — ${result.detail}` : ""}`);
  }
  if (options.out) fs.writeFileSync(options.out, JSON.stringify({ layer: "data", results }, null, 1));
  process.exitCode = results.every((result) => result.status === "pass") ? 0 : 1;
}

main();
