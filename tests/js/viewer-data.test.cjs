// node --test tests/js/viewer-data.test.cjs
// viewer-data.js 是 2026-10-14 从 viewer.js 原样拆出的数据纯函数；这里固定其现有行为，防止后续拆分改变结果。
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const D = require(path.join(__dirname, "..", "..", "site_overrides", "assets", "app", "viewer-data.js"));

test("exports the functions viewer.js destructures", () => {
  const fs = require("node:fs");
  const viewer = fs.readFileSync(path.join(__dirname, "..", "..", "site_overrides", "assets", "app", "viewer.js"), "utf8");
  const block = viewer.match(/const \{([\s\S]*?)\} = window\.SizeViewerData;/);
  assert.ok(block, "viewer.js must destructure window.SizeViewerData at the top of its IIFE");
  const names = block[1].split(",").map((name) => name.trim()).filter(Boolean);
  assert.deepEqual(names.filter((name) => typeof D[name] !== "function"), []);
  for (const name of names) {
    assert.ok(!new RegExp(`\\n  function ${name}\\(`).test(viewer), `${name} must not also be declared in viewer.js`);
  }
});

test("search text is lower-cased, separators collapsed, tokens split", () => {
  assert.equal(D.normalizeSearchText("  Ford-F_150 / Super  Duty "), "ford f 150 super duty");
  assert.deepEqual(D.searchTokens("Land-Rover  Defender"), ["land", "rover", "defender"]);
});

test("years expand from ranges, single years and lists", () => {
  assert.deepEqual(D.expandYears("1994-1996"), [1994, 1995, 1996]);
  assert.deepEqual(D.expandYears("2019–2020"), [2019, 2020]);
  assert.deepEqual(D.expandYears("2010/2012, 2010"), [2010, 2012]);
  assert.deepEqual(D.expandYears(""), []);
  assert.deepEqual(D.uniqueYears([{ years: [2001, 1999] }, { years: [1999, 2003] }]), ["1999", "2001", "2003"]);
});

test("vehicle code matches same make/model with overlapping years", () => {
  const code = { make: "Ford", model: "Mustang", start: 1994, end: 2026 };
  assert.equal(D.recordMatchesVehicleCode({ make: "ford", model: "MUSTANG", year: "1990-1994" }, code), true);
  assert.equal(D.recordMatchesVehicleCode({ make: "Ford", model: "Mustang", years: [1990, 1993] }, code), false);
  assert.equal(D.recordMatchesVehicleCode({ make: "Ford", model: "Focus", year: "2000" }, code), false);
});

test("sorting compares numbers numerically and BED by first number", () => {
  assert.ok(D.compareValues("9", "10") < 0);
  assert.ok(D.compareValues("3L", "3XL") < 0);
  assert.deepEqual(["8ft", "5.5ft", "", "6.5ft"].sort(D.compareBedValues), ["5.5ft", "6.5ft", "8ft", ""]);
});

test("TSV parsing strips BOM, joins quoted line breaks and trims cells", () => {
  const rows = D.parseTsv("﻿MAKE\tMODEL\r\nFord\t\"Mus\ntang\"\r\n\r\nBMW\t X5 \r\n");
  assert.equal(rows.length, 2);
  assert.equal(rows[0].MAKE, "Ford");
  assert.equal(rows[1].MODEL, "X5");
});

test("small helpers keep their current behaviour", () => {
  assert.deepEqual(D.uniqueInOrder(["b", "a", "b", "", "c"]), ["b", "a", "c"]);
  assert.deepEqual(D.unique(["b10", "b2", "", "b2"]), ["b2", "b10"]);
  assert.deepEqual(D.csvList(" US, HNT ,,TM "), ["US", "HNT", "TM"]);
  assert.equal(D.escapeHtml('<a href="x">&</a>'), "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;");
  assert.equal(D.parseYamlValue('"True"'), true);
  assert.equal(D.parseYamlValue("'abc'"), "abc");
  assert.ok(Number.isNaN(D.firstNumber("n/a")));
});
