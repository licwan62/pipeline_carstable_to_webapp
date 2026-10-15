// node --test tests/js/viewer-rules.test.cjs
// viewer-rules.js 是 2026-10-15 从 viewer.js 拆出的 SIZE 规则索引与悬停 HTML（拆分时与原实现在真实 size-rules.json /
// store-groups.json 上逐项比对一致）；这里固定其行为。
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP = path.join(__dirname, "..", "..", "site_overrides", "assets", "app");
const R = require(path.join(APP, "viewer-rules.js"));

const RULES = {
  source: { version: "20261013_28" },
  regions: {
    US: {
      headers: ["尺码", "分类", "尺码池", "长上限", "插片指数上限", "插片指数下限", "车型白名单", "备注", "规则ID"],
      length_tolerance: 550,
      rows: [
        { 尺码: "2M", 分类: "两厢车", 尺码池: "H", 长上限: "4500", 插片指数上限: "999", 插片指数下限: "", 车型白名单: "", 备注: "", 规则ID: "aaa" },
        { 尺码: "3M", 分类: "两厢车", 尺码池: "H", 长上限: "4800", 插片指数上限: "1.2", 插片指数下限: "0.8", 车型白名单: "Golf", 备注: "<注>", 规则ID: "bbb" },
        { 尺码: "2M", 分类: "重复", 长上限: "1", 规则ID: "ccc" }
      ]
    },
    EU: {
      headers: ["尺码", "模式", "分类", "版本", "长上限", "规则ID"],
      length_tolerance: 550,
      rows: [{ 尺码: "2M", 模式: "标准", 分类: "两厢车", 版本: "v2", 长上限: "4400", 规则ID: "eee" }]
    },
    RU: {
      headers: ["亚马逊尺码", "OZON尺码", "发货尺码", "分类", "长_mm", "宽_mm", "高_mm", "余量长上限_mm", "规则ID"],
      length_tolerance: 635,
      rows: [{ 亚马逊尺码: "YS-380", OZON尺码: "XS", 发货尺码: "S", 分类: "轿车", 长_mm: "3800", 宽_mm: "1700", 高_mm: "1500", 余量长上限_mm: "", 规则ID: "rrr" }]
    }
  }
};
const GROUPS = { stores: { HNT: [{ 匹配尺码: "2M", 发货尺码: "SH1" }, { 匹配尺码: "3M", 发货尺码: "SH1" }, { 匹配尺码: "3M", 发货尺码: "SH2" }] } };
const GROUP_OF = { US: "US", HNT: "US", EU: "EU", RU: "RU" };
const MM = { measurement: (mm) => String(Math.round(mm)), unit: "mm" };
const CM = { measurement: (mm) => String(Math.round(mm * 0.1)), unit: "cm" };

function index() {
  const rules = R.createRuleIndex({ sourceGroup: (name) => GROUP_OF[name] || name });
  rules.load(RULES, GROUPS);
  return rules;
}

test("scope picks region by source group; stores fall back to US", () => {
  const rules = index();
  assert.deepEqual({ ...rules.scope("EU"), index: undefined }, { region: "EU", store: "", index: undefined });
  assert.equal(rules.scope("HNT").store, "HNT");
  assert.equal(rules.scope("HNT").region, "US");
  assert.equal(rules.scope("XX").region, "");
  assert.equal(rules.scope("XX").index, undefined);
});

test("first row per size wins; store shipping size lists every matching size", () => {
  const rules = index();
  const us = rules.ruleFor(" 2m ", "US");
  assert.equal(us.size, "2m");
  assert.deepEqual(us.matchSizes, ["2M"]);
  assert.equal(us.rows[0]["规则ID"], "aaa");
  assert.equal(us.tolerance, 550);
  const store = rules.ruleFor("sh1", "HNT");
  assert.deepEqual(store.matchSizes, ["2M", "3M"]);
  assert.deepEqual(store.rows.map((row) => row["规则ID"]), ["aaa", "bbb"]);
  assert.equal(rules.ruleFor("2M", "HNT"), null, "店铺 SIZE 是发货尺码，匹配尺码本身查不到");
  assert.equal(rules.ruleFor("", "US"), null);
  assert.equal(rules.ruleFor("2M", "XX"), null);
});

test("exact rule by 规则ID, with fallback to size lookup", () => {
  const rules = index();
  const record = { values: { 规则ID: "bbb", 匹配尺码: "", SIZE: "3M" } };
  assert.deepEqual(rules.exactForRecord(record, "US"), { ruleId: "bbb", row: RULES.regions.US.rows[1], region: "US", store: "", matchSize: "3M", tolerance: 550 });
  assert.equal(rules.exactForRecord({ values: { 规则ID: "bbb", SIZE: "SH1" } }, "HNT").matchSize, "", "店铺记录无 匹配尺码 时不拿发货尺码代替");
  assert.equal(rules.exactForRecord({ values: { 规则ID: "nope" } }, "US"), null);
  assert.equal(rules.exactForRecord({ values: {} }, "US"), null);
  const exact = rules.exactFor("bbb", "HNT", "SH1", "3M");
  assert.equal(exact.exact, true);
  assert.deepEqual(exact.matchSizes, ["3M"]);
  assert.deepEqual(rules.exactFor("nope", "HNT", "SH1", "3M"), rules.ruleFor("SH1", "HNT"));
});

test("load replaces previous data", () => {
  const rules = index();
  rules.load({ regions: {} }, {});
  assert.equal(rules.ruleFor("2M", "US"), null);
  assert.equal(rules.scope("HNT").store, "");
});

test("US markup: length range, unlimited insert index, escaped notes, store via-line", () => {
  const rules = index();
  const html = R.ruleMarkup(rules.ruleFor("SH1", "HNT"), MM);
  assert.match(html, /<div class="size-reference-title">SH1<small>US · 店铺 HNT 尺码规则<\/small><\/div>/);
  assert.match(html, /匹配尺码 2M → 发货 SH1/);
  assert.match(html, /<dt>适配车长<\/dt><dd>3950 – 4500 mm<\/dd>/);
  assert.match(html, /<dt>余量容差<\/dt><dd>≤ 550 mm<\/dd>/);
  assert.match(html, /<dt>插片指数<\/dt><dd>&gt; 0.8，≤ 1.2<\/dd>/, "上限 999 不显示，其余显示区间");
  assert.match(html, /<dd>&lt;注&gt;<\/dd>/);
  assert.equal((html.match(/size-reference-divider/g) || []).length, 1);
  assert.match(R.ruleMarkup(rules.ruleFor("2M", "US"), CM), /<dd>395 – 450 cm<\/dd>/, "单位随 format 切换");
  assert.match(R.ruleMarkup(rules.exactFor("aaa", "US", "2M", ""), MM), /US 命中规则 aaa/);
});

test("EU and RU markup", () => {
  const rules = index();
  assert.match(R.ruleMarkup(rules.ruleFor("2M", "EU"), MM), /标准 · 两厢车 · 版本 v2/);
  const ru = R.ruleMarkup(rules.ruleFor("ys-380", "RU"), MM);
  assert.match(ru, /轿车 · OZON XS · 发货 S/);
  assert.match(ru, /<em>宽上限<\/em><strong>1700 mm<\/strong>/);
  assert.match(ru, /<dt>适配车长<\/dt><dd>3165 – 3800 mm<\/dd>/, "行内 余量长上限_mm 为空时用报告容差 635");
});

test("dimension helpers", () => {
  assert.equal(R.dimensionMarkup("长", "4500", MM), "<span><em>长</em><strong>4500 mm</strong></span>");
  assert.equal(R.dimensionMarkup("长", "", MM), "<span><em>长</em><strong>0 mm</strong></span>");
  assert.equal(R.dimensionMarkup("长", "n/a", MM), "<span><em>长</em><strong>n/a</strong></span>");
  assert.equal(R.dimensionMarkup("长", undefined, MM), "<span><em>长</em><strong>-</strong></span>");
  assert.equal(R.insertDisplay("999", ""), "");
});

test("viewer.js delegates to viewer-rules.js and no longer keeps its own rule state", () => {
  const viewer = fs.readFileSync(path.join(APP, "viewer.js"), "utf8");
  assert.match(viewer, /window\.SizeViewerRules\.createRuleIndex\(/);
  for (const name of ["sizeRuleIndexes", "sizeRuleIdIndexes", "storeShippingSizes", "sizeRuleLengthMarkup", "sizeRuleRuMarkup", "sizeReferenceDimensionDisplay"]) {
    assert.ok(!viewer.includes(name), `${name} must live in viewer-rules.js`);
  }
});
