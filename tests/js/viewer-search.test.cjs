// node --test tests/js/viewer-search.test.cjs
// 尺码配对：全局搜索按字段语义匹配（R3）与「一份分片两种视图」的还原（R1/R2），需求见 docs/size-match-acceptance.md。
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const D = require(path.join(__dirname, "..", "..", "site_overrides", "assets", "app", "viewer-data.js"));

function row(make, model, year, extra = {}) {
  const values = { MAKE: make, MODEL: model, YEAR: year, "结构": "Sedan", TYPE: "Sedan", SIZE: "3M-0", "L-MM": "4777", "销量合计": "17007", ...extra };
  return { make, model, year, years: D.spanYears(year), type: values.TYPE, size: values.SIZE, values };
}

function search(records, query) {
  const tokens = D.searchQueryTokens(query);
  return records.filter((record) => tokens.every((token) => D.recordMatchesSearchToken(record, token))).map((record) => record.model);
}

const BMW = [
  row("BMW", "3 Series", "2012-2018", { CODE: "19031218" }),
  row("BMW", "5 Series", "2017-2023", { CODE: "19051723", SIZE: "7M" }),
  row("BMW", "7 Series", "2016-2022", { CODE: "19071622" }),
  row("BMW", "X7", "2019-2026", { CODE: "19271926", TYPE: "SUV" }),
  row("BMW", "i7", "2023-2026", { CODE: "19287326" }),
  row("BMW", "1 Series", "2008-2013", { CODE: "19160813", SIZE: "3M-0" })
];

test("bmw 7 only returns the 7 Series (no years, sizes, sales, codes or X7/i7 leaking in)", () => {
  assert.deepEqual(search(BMW, "bmw 7"), ["7 Series"]);
  assert.deepEqual(search(BMW, "BMW 7 series"), ["7 Series"]);
  assert.deepEqual(search(BMW, "bmw 3"), ["3 Series"]);
  assert.deepEqual(search(BMW, "bmw x7"), ["X7"]);
});

test("numbers must match a whole model number: 7 is not 700 or 740i, 740 finds the 740i version", () => {
  const cars = [row("BMW", "7", "2015-2022"), row("BMW", "700", "1959-1965"), row("BMW", "75", "1990"),
    row("BMW", "7 Series", "2016-2022", { "版本": "740i" }), row("BMW", "5 Series", "2017-2023", { "版本": "540i" })];
  assert.deepEqual(search(cars, "bmw 7"), ["7", "7 Series"]);
  assert.deepEqual(search(cars, "bmw 740"), ["7 Series"]);
  assert.deepEqual(search(cars, "bmw 70"), []);
});

test("four-digit years match the record's year span, not text inside other numbers", () => {
  assert.deepEqual(search(BMW, "bmw 2017"), ["3 Series", "5 Series", "7 Series"]);
  assert.deepEqual(search(BMW, "7 series 2016-2017"), ["7 Series"]);
  assert.deepEqual(search(BMW, "bmw 2030"), []);
});

test("codes match by prefix of at least four digits; short numbers never hit CODE", () => {
  assert.deepEqual(search(BMW, "1907"), ["7 Series"]);
  assert.deepEqual(search(BMW, "19"), []);
});

test("hyphenated and compact model names, brand-prefixed models, multi-word makes", () => {
  const cars = [
    row("Ford", "F-150", "2015-2020"), row("Honda", "CR-V", "2017-2022"), row("Mazda", "3", "2019-2026"),
    row("Mazda", "CX-3", "2016-2021"), row("Mazda", "CX-30", "2020-2026"), row("Mazda", "Mazda6", "2014-2021"),
    row("Mercedes-Benz", "E-Class", "2017-2023"), row("Land Rover", "Defender", "2020-2026")
  ];
  assert.deepEqual(search(cars, "f150"), ["F-150"]);
  assert.deepEqual(search(cars, "f-150"), ["F-150"]);
  assert.deepEqual(search(cars, "cr-v"), ["CR-V"]);
  assert.deepEqual(search(cars, "crv"), ["CR-V"]);
  assert.deepEqual(search(cars, "mazda 3"), ["3"]);
  assert.deepEqual(search(cars, "mazda 6"), ["Mazda6"]);
  assert.deepEqual(search(cars, "cx-3"), ["CX-3", "CX-30"]);
  assert.deepEqual(search(cars, "benz e-class"), ["E-Class"]);
  assert.deepEqual(search(cars, "land rover"), ["Defender"]);
  assert.deepEqual(search(cars, "landrover"), ["Defender"]);
});

test("size, type, shape and rule id remain searchable", () => {
  const cars = [
    row("Toyota", "Camry", "2018-2024", { SIZE: "3L", SHAPE: "STANDARD_SEDAN", "规则ID": "Rb55fc98664" }),
    row("Toyota", "RAV4", "2019-2024", { SIZE: "YM", TYPE: "SUV", "结构": "SUV", SHAPE: "BOXY_SUV" })
  ];
  assert.deepEqual(search(cars, "3l"), ["Camry"]);
  assert.deepEqual(search(cars, "toyota suv"), ["RAV4"]);
  assert.deepEqual(search(cars, "boxy"), ["RAV4"]);
  assert.deepEqual(search(cars, "rb55f"), ["Camry"]);
  assert.deepEqual(search(cars, "r"), ["RAV4"], "短词不匹配规则ID（R 开头的规则ID 遍布所有记录）");
  const labels = { BOXY_SUV: { label: "方正 SUV" } };
  const tokens = D.searchQueryTokens("方正");
  assert.deepEqual(cars.map((record) => ({ ...record, searchIndex: undefined }))
    .filter((record) => tokens.every((token) => D.recordMatchesSearchToken(record, token, labels))).map((record) => record.model), ["RAV4"]);
});

const SHARD = {
  name: "US", make: "Acura", kind: "nonpick",
  columns: ["MODEL", "YEAR", "SIZE"],
  records: [
    { make: "Acura", model: "ADX", year: "2024", years: [2024], kind: "nonpick", values: { "DIMENSION-ID": "Acura ADX SUV 2024 US", MAKE: "Acura", MODEL: "ADX", YEAR: "2024", "结构": "SUV", "L-MM": "4690" } },
    { make: "Acura", model: "ADX", year: "2025-2026", years: [2025, 2026], kind: "nonpick", values: { "DIMENSION-ID": "Acura ADX SUV 2025-2026 US", MAKE: "Acura", MODEL: "ADX", "版本": "", YEAR: "2025-2026", "结构": "SUV", CAB: "", BED: "", "L-MM": "4719", "W-MM": "1842", "H-MM": "1621", SHAPE: "BOXY_SUV", "自动长度余量": "131", "规则ID": "Rb55fc98664", "匹配尺码": "YL" } }
  ],
  compressed_columns: ["CODE", "MODEL", "YEAR", "SIZE"],
  compressed: [{ values: { CODE: "25112526", MAKE: "Acura", MODEL: "ADX", YEAR: "2025-2026", TYPE: "SUV", CAB: "", BED: "", SIZE: "YL" }, refs: [[1, "2025"]] }]
};

test("one shard expands into the full view (A0 rows) and the compressed view (records + sources rebuilt from refs)", () => {
  const views = D.expandMatchShard(SHARD);
  assert.equal(views.full.records, SHARD.records, "全量表视图直接用分片的 A0 行，不复制");
  assert.deepEqual(views.full.columns, ["MODEL", "YEAR", "SIZE"]);
  assert.deepEqual(views.compressed.columns, ["CODE", "MODEL", "YEAR", "SIZE"]);
  const [record] = views.compressed.records;
  assert.deepEqual([record.make, record.model, record.year, record.years, record.type, record.size, record.kind],
    ["Acura", "ADX", "2025-2026", [2025, 2026], "SUV", "YL", "nonpick"]);
  assert.deepEqual(record.sources, [{
    "DIMENSION-ID": "Acura ADX SUV 2025-2026 US", MODEL: "ADX", "版本": "", YEAR: "2025", TYPE: "SUV", CAB: "", BED: "",
    "L-MM": "4719", "W-MM": "1842", "H-MM": "1621", SHAPE: "BOXY_SUV", "长度余量": "131", "规则ID": "Rb55fc98664", "匹配尺码": "YL"
  }]);
  assert.equal(D.expandMatchShard({ ...SHARD, kind: "pick" }).compressed.records[0].sources[0].TYPE, "Pickup");
});

test("legacy payloads without compressed records have only the full view; broken refs fail loudly", () => {
  assert.equal(D.expandMatchShard({ records: [] }).compressed, null);
  assert.throws(() => D.expandMatchShard({ ...SHARD, compressed: [{ values: {}, refs: [[5, "2025"]] }] }), /missing row 5/);
});

test("spanYears matches the builder's parse_years", () => {
  assert.deepEqual(D.spanYears("2019-2021"), [2019, 2020, 2021]);
  assert.deepEqual(D.spanYears("1987"), [1987]);
  assert.deepEqual(D.spanYears("2010/2012"), [2010, 2011, 2012]);
  assert.deepEqual(D.spanYears(""), []);
});
