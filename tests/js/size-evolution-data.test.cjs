// node --test tests/js/size-evolution-data.test.cjs
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const data = require(path.join(__dirname, "..", "..", "site_overrides", "assets", "app", "size-evolution-data.js"));

function rawRecord(values, extra = {}) {
  return {
    make: values.MAKE,
    model: values.MODEL,
    year: values.YEAR,
    years: extra.years || [],
    construct: values["结构"] || "",
    type: values["结构"] || "",
    cab: values.CAB || "",
    bed: values.BED || "",
    size: values["自动尺码"] || "",
    kind: extra.kind || "nonpick",
    values: {
      "版本": "", CAB: "", BED: "", "代际": "", "候选": "", "原因": "", "相差数值": "",
      ...values,
      TYPE: values["结构"] || "",
      SIZE: values["自动尺码"] || "",
      "长度余量": values["自动长度余量"] === undefined ? "" : values["自动长度余量"]
    }
  };
}

function normalizeAll(records, source) {
  data.assignRecordKeys(records, source);
  return data.dedupeRecords(records.map((record) => data.normalizeRecord(record, { source })));
}

// 2026-10-13 A0 US MINI Countryman（未注明版本 + JCW 2016）
function countryman() {
  const base = { MAKE: "MINI", MODEL: "Countryman", "结构": "SUV", SOURCE: "US" };
  return [
    rawRecord({ ...base, "DIMENSION-ID": "MINI Countryman JCW SUV 2016 US", "版本": "JCW", "代际": "gen1", YEAR: "2016", "L-MM": "4143", "W-MM": "1788", "H-MM": "1562", "自动尺码": "YM", "自动长度余量": "487" }),
    rawRecord({ ...base, "DIMENSION-ID": "MINI Countryman SUV 2011-2015 US", "代际": "gen1", YEAR: "2011-2015", "L-MM": "4110", "W-MM": "1788", "H-MM": "1562", "自动尺码": "YM", "自动长度余量": "520" }),
    rawRecord({ ...base, "DIMENSION-ID": "MINI Countryman SUV 2017-2024 US", "代际": "gen2", YEAR: "2017-2024", "L-MM": "4313", "W-MM": "1821", "H-MM": "1557", "自动尺码": "YM", "自动长度余量": "317" }),
    rawRecord({ ...base, "DIMENSION-ID": "MINI Countryman SUV 2025-2026 US", "代际": "gen3", YEAR: "2025-2026", "L-MM": "4448", "W-MM": "1844", "H-MM": "1656", "自动尺码": "YM", "自动长度余量": "182" })
  ];
}

test("年份：单年、含两端区间、各种 dash", () => {
  assert.deepEqual(data.parseYearIntervals("2016").intervals, [{ startYear: 2016, endYear: 2016 }]);
  assert.deepEqual(data.parseYearIntervals("2017-2024").intervals, [{ startYear: 2017, endYear: 2024 }]);
  assert.deepEqual(data.parseYearIntervals("2017–2024").intervals, [{ startYear: 2017, endYear: 2024 }]);
  assert.deepEqual(data.parseYearIntervals("2017 — 2024").intervals, [{ startYear: 2017, endYear: 2024 }]);
  assert.deepEqual(data.parseYearIntervals("2024-2024").intervals, [{ startYear: 2024, endYear: 2024 }]);
});

test("年份：离散年份不补缺口；years 数组按缺口断开", () => {
  assert.deepEqual(data.parseYearIntervals("2011,2013").intervals, [{ startYear: 2011, endYear: 2011 }, { startYear: 2013, endYear: 2013 }]);
  assert.deepEqual(data.parseYearIntervals("2008-2010, 2014-2016").intervals, [{ startYear: 2008, endYear: 2010 }, { startYear: 2014, endYear: 2016 }]);
  // 上游 years 数组（如旧数据把 2011,2013 填满）只在原文不可用时使用
  const fallback = data.parseYearIntervals("", [2001, 2002, 2005, 2006, 2007]);
  assert.deepEqual(fallback.intervals, [{ startYear: 2001, endYear: 2002 }, { startYear: 2005, endYear: 2007 }]);
  assert.equal(fallback.from, "years");
});

test("年份：倒置、非法、异常年份不画虚构年份并记入提示", () => {
  const inverted = data.parseYearIntervals("2024-2017", []);
  assert.deepEqual(inverted.intervals, []);
  assert.equal(inverted.issues[0].kind, "year-inverted");
  const junk = data.parseYearIntervals("unknown");
  assert.deepEqual(junk.intervals, []);
  assert.equal(junk.issues[0].kind, "year-unparsed");
  const outOfRange = data.parseYearIntervals("1850-1860");
  assert.deepEqual(outOfRange.intervals, []);
  assert.equal(outOfRange.issues[0].kind, "year-out-of-range");
  const empty = data.parseYearIntervals("");
  assert.deepEqual(empty.intervals, []);
  assert.equal(empty.issues[0].kind, "year-missing");
});

test("座位：只识别明确标记", () => {
  assert.equal(data.extractSeats("lwb 5seat").seats, 5);
  assert.equal(data.extractSeats("lwb 7seat").seats, 7);
  assert.equal(data.extractSeats("7-seater").seats, 7);
  assert.equal(data.extractSeats("2-Seater").seats, 2);
  assert.equal(data.extractSeats("7 Seats").seats, 7);
  assert.equal(data.extractSeats("7座").seats, 7);
  assert.equal(data.extractSeats("L2H1").seats, null);
  assert.equal(data.extractSeats("SEAT Leon").seats, null);
  assert.equal(data.extractSeats("Seat").seats, null);
  assert.equal(data.extractSeats("308").seats, null);
  assert.equal(data.extractSeats("").seats, null);
  const conflict = data.extractSeats("5seat 7seat");
  assert.equal(conflict.seats, null);
  assert.equal(conflict.conflict, true);
  // 明确的 SEATS 字段优先
  assert.equal(data.extractSeats("5seat", "7").seats, 7);
});

test("座位提取不修改版本原文", () => {
  const records = normalizeAll([rawRecord({ MAKE: "Ford", MODEL: "Transit connect", "结构": "MPV", "版本": "lwb 5seat", YEAR: "2013-2026", "DIMENSION-ID": "x", "L-MM": "4818", "W-MM": "1834", "H-MM": "1844", "自动尺码": "2XL", "自动长度余量": "12" })], "EU");
  assert.equal(records[0].version, "lwb 5seat");
  assert.equal(records[0].seats, 5);
});

test("数值：缺失尺寸为 null，长度余量 0 与负数保留", () => {
  assert.equal(data.toNumberOrNull("", { positive: true }), null);
  assert.equal(data.toNumberOrNull("NULL", { positive: true }), null);
  assert.equal(data.toNumberOrNull("NaN", { positive: true }), null);
  assert.equal(data.toNumberOrNull("abc", { positive: true }), null);
  assert.equal(data.toNumberOrNull("0", { positive: true }), null);
  assert.equal(data.toNumberOrNull("-5", { positive: true }), null);
  assert.equal(data.toNumberOrNull("0"), 0);
  assert.equal(data.toNumberOrNull("-12"), -12);
  assert.equal(data.toNumberOrNull("119.0"), 119);
  const [record] = normalizeAll([rawRecord({ MAKE: "A", MODEL: "B", YEAR: "2020", "DIMENSION-ID": "a", "L-MM": "", "W-MM": "1800", "H-MM": "1500", "自动尺码": "2L", "自动长度余量": "0" })], "US");
  assert.equal(record.lengthMm, null);
  assert.equal(record.widthMm, 1800);
  assert.equal(record.lengthMarginMm, 0);
  assert.ok(record.issues.some((issue) => issue.kind === "dimension-missing"));
});

test("单位：往返不修改原始 mm，只在显示时舍入", () => {
  const mm = 4313;
  assert.equal(data.convertFromMm(mm, "cm"), 431.3);
  assert.equal(data.convertToMm(data.convertFromMm(mm, "in"), "in"), mm);
  assert.equal(data.formatMeasure(mm, "mm"), "4313 mm");
  assert.equal(data.formatMeasure(mm, "cm"), "431.3 cm");
  assert.equal(data.formatMeasure(mm, "in"), "169.8 in");
  assert.equal(data.formatMeasure(null, "cm"), "—");
});

test("身份：同品牌不同车型、同车型不同来源不混合；key 与顺序无关", () => {
  const us = normalizeAll(countryman(), "US");
  const hnt = normalizeAll(countryman().map((record) => ({ ...record, values: { ...record.values, SOURCE: "HNT" } })), "HNT");
  const keysUs = new Set(us.map((record) => record.recordKey));
  assert.ok(hnt.every((record) => !keysUs.has(record.recordKey)));
  assert.notEqual(us[0].configurationKey, hnt[0].configurationKey);
  assert.notEqual(us[0].modelKey, hnt[0].modelKey);
  const reversed = normalizeAll(countryman().reverse(), "US");
  assert.deepEqual(new Set(reversed.map((record) => record.recordKey)), keysUs);
  const other = normalizeAll([rawRecord({ MAKE: "MINI", MODEL: "Clubman", "结构": "SUV", YEAR: "2016", "DIMENSION-ID": "MINI Clubman 2016 US", "L-MM": "4253", "W-MM": "1800", "H-MM": "1441", "自动尺码": "2L" })], "US");
  assert.notEqual(other[0].modelKey, us[0].modelKey);
  // 不同 MAKE 的同名 MODEL 不合并
  assert.notEqual(data.modelKey("US", "nonpick", "FIAT", "500"), data.modelKey("US", "nonpick", "Fiat", "500"));
});

test("身份：配置键是结构化元组，不因空格拼接碰撞", () => {
  const left = data.configurationKeyOf({ source: "US", kind: "nonpick", make: "A", model: "B C", version: "D", type: "SUV", seats: null, cab: null, bed: null });
  const right = data.configurationKeyOf({ source: "US", kind: "nonpick", make: "A", model: "B", version: "C D", type: "SUV", seats: null, cab: null, bed: null });
  assert.notEqual(left, right);
});

test("身份：同 ID 不同内容保留并标记冲突；精确重复合并并保留引用", () => {
  const base = { MAKE: "A", MODEL: "B", "结构": "SUV", YEAR: "2020", "DIMENSION-ID": "same", "W-MM": "1800", "H-MM": "1500", "自动尺码": "2L" };
  const records = normalizeAll([rawRecord({ ...base, "L-MM": "4500" }), rawRecord({ ...base, "L-MM": "4600" })], "US");
  assert.equal(records.length, 2);
  assert.ok(records.every((record) => record.idConflict));
  assert.notEqual(records[0].recordKey, records[1].recordKey);
  const duplicates = normalizeAll([rawRecord({ ...base, "L-MM": "4500" }), rawRecord({ ...base, "L-MM": "4500" })], "US");
  assert.equal(duplicates.length, 1);
  assert.equal(duplicates[0].rawRefs.length, 2);
  assert.equal(duplicates[0].idConflict, false);
});

test("MINI Countryman：2016 在未注明版本配置上断开，JCW 是另一配置，余量缩小而 SIZE 保持 YM", () => {
  const records = normalizeAll(countryman(), "US");
  const configurations = data.buildConfigurations(records);
  assert.equal(configurations.length, 2);
  const standard = configurations.find((item) => item.version === null);
  const jcw = configurations.find((item) => item.version === "JCW");
  assert.ok(standard && jcw);
  assert.equal(standard.label.includes("未注明版本"), true);
  assert.equal(standard.records.length, 3);
  // 2015→2017 不连续：不连接；2024→2025 连续：长度阶梯跳变落在 2024.5
  assert.deepEqual(standard.connections.length.map((item) => item.x), [2024.5]);
  assert.equal(standard.connections.length[0].from, 4313);
  assert.equal(standard.connections.length[0].to, 4448);
  const covered = data.intervalYears(standard.records.flatMap((record) => record.intervals));
  assert.equal(covered.includes(2016), false);
  const margins = standard.records.map((record) => record.lengthMarginMm);
  assert.deepEqual(margins.sort((a, b) => b - a), [520, 317, 182]);
  assert.ok(standard.records.every((record) => record.sizeValue === "YM"));
  assert.equal(standard.lanes.length, 1);
});

test("同年重叠的不同尺寸完整保留为分支，不取平均也不连接", () => {
  const base = { MAKE: "Ford", MODEL: "Transit connect", "结构": "MPV", "版本": "swb", "W-MM": "1834", "自动尺码": "2L+" };
  const records = normalizeAll([
    rawRecord({ ...base, "DIMENSION-ID": "a", YEAR: "2013-2026", "L-MM": "4417", "H-MM": "1852", "代际": "II" }),
    rawRecord({ ...base, "DIMENSION-ID": "b", YEAR: "2018-2026", "L-MM": "4425", "H-MM": "1844", "代际": "II facelift" }),
    rawRecord({ ...base, "DIMENSION-ID": "c", YEAR: "2002-2013", "L-MM": "4277", "H-MM": "1814", "代际": "I" })
  ], "EU");
  const [configuration] = data.buildConfigurations(records);
  assert.equal(configuration.records.length, 3);
  assert.deepEqual(configuration.records.map((record) => record.lengthMm).sort(), [4277, 4417, 4425]);
  assert.ok(configuration.overlapYears.includes(2013));
  assert.ok(configuration.overlapYears.includes(2020));
  assert.ok(configuration.lanes.length >= 2);
  // 2013 同年有两条记录：边界两侧不唯一，不画阶梯连接
  assert.deepEqual(configuration.connections.length, []);
});

test("缺失尺寸只断开该维度", () => {
  const base = { MAKE: "A", MODEL: "B", "结构": "SUV", "自动尺码": "2L" };
  const records = normalizeAll([
    rawRecord({ ...base, "DIMENSION-ID": "1", YEAR: "2010-2012", "L-MM": "4500", "W-MM": "1800", "H-MM": "1500" }),
    rawRecord({ ...base, "DIMENSION-ID": "2", YEAR: "2013-2015", "L-MM": "4600", "W-MM": "", "H-MM": "1510" })
  ], "US");
  const [configuration] = data.buildConfigurations(records);
  assert.equal(configuration.connections.length.length, 1);
  assert.equal(configuration.connections.width.length, 0);
  assert.equal(configuration.connections.height.length, 1);
});

test("座位配置：5seat / 7seat 分开，未知座位单独成配置", () => {
  const base = { MAKE: "Ford", MODEL: "Transit connect", "结构": "MPV", YEAR: "2013-2026", "L-MM": "4818", "W-MM": "1834", "自动尺码": "2XL" };
  const records = normalizeAll([
    rawRecord({ ...base, "DIMENSION-ID": "5", "版本": "lwb 5seat", "H-MM": "1844" }),
    rawRecord({ ...base, "DIMENSION-ID": "7", "版本": "lwb 7seat", "H-MM": "1839" }),
    rawRecord({ ...base, "DIMENSION-ID": "x", "版本": "lwb", "H-MM": "1981" })
  ], "EU");
  const configurations = data.buildConfigurations(records);
  assert.equal(configurations.length, 3);
  assert.deepEqual(configurations.map((item) => item.seats).sort(), [5, 7, null].sort());
  assert.ok(configurations.find((item) => item.seats === null).label.includes("座位未知"));
});

test("SIZE 语义：国别为匹配 SIZE，店铺为发货 SIZE，店铺不宣称匹配尺码", () => {
  const [us] = normalizeAll(countryman().slice(1, 2), "US");
  const [hnt] = normalizeAll(countryman().slice(1, 2), "HNT");
  assert.equal(us.sizeMeaning, "match");
  assert.equal(us.matchedSize, "YM");
  assert.equal(hnt.sizeMeaning, "shipping");
  assert.equal(hnt.matchedSize, null);
  assert.equal(data.sizeHeading(hnt.sizeMeaning), "发货 SIZE");
  assert.equal(data.matchStatusOf("无可用尺码"), "unmatched");
  assert.equal(data.matchStatusOf("数据不全"), "incomplete");
  assert.equal(data.matchStatusOf(""), "unknown");
});

test("默认最多显示 6 个配置，已选配置优先", () => {
  const records = [];
  for (let index = 0; index < 9; index += 1) {
    records.push(rawRecord({ MAKE: "A", MODEL: "B", "结构": "SUV", "版本": `v${index}`, YEAR: "2020", "DIMENSION-ID": `id${index}`, "L-MM": "4500", "W-MM": "1800", "H-MM": "1500", "自动尺码": "2L" }));
  }
  const normalized = normalizeAll(records, "US");
  const target = normalized.find((record) => record.version === "v8");
  const configurations = data.buildConfigurations(normalized, { selectedConfigurationKeys: [target.configurationKey] });
  const visible = data.defaultVisibleConfigurations(configurations, 6);
  assert.equal(visible.length, 6);
  assert.equal(visible[0], target.configurationKey);
});

test("配置筛选：空数组不限，未知座位可作为筛选值", () => {
  const configuration = { modelKey: "m", version: "lwb", type: "MPV", seats: null, cab: null, bed: null };
  assert.equal(data.configurationMatchesFilters(configuration, { seats: [] }), true);
  assert.equal(data.configurationMatchesFilters(configuration, { seats: [""] }), true);
  assert.equal(data.configurationMatchesFilters(configuration, { seats: ["5"] }), false);
});

test("紧凑标签只保留配置间不同的字段（皮卡 CAB/BED 不丢失）", () => {
  const base = { MAKE: "Ford", MODEL: "F-150", "结构": "Pickup", YEAR: "2021-2026", "L-MM": "5900", "W-MM": "2000", "H-MM": "1960", "自动尺码": "PK-L", "分类": "皮卡" };
  const records = normalizeAll([
    rawRecord({ ...base, "DIMENSION-ID": "a", CAB: "SuperCrew", BED: "5.5" }, { kind: "pick" }),
    rawRecord({ ...base, "DIMENSION-ID": "b", CAB: "SuperCrew", BED: "6.5" }, { kind: "pick" }),
    rawRecord({ ...base, "DIMENSION-ID": "c", CAB: "Regular", BED: "6.5" }, { kind: "pick" })
  ], "US");
  const configurations = data.buildConfigurations(records);
  assert.equal(configurations.length, 3);
  assert.deepEqual(configurations.map((item) => item.compactLabel).sort(), ["CAB Regular · BED 6.5", "CAB SuperCrew · BED 5.5", "CAB SuperCrew · BED 6.5"]);
  assert.ok(configurations.every((item) => item.label.includes("Ford F-150")));
});

test("店铺匹配尺码只取 A0「匹配尺码」，没有时不用发货 SIZE 冒充", () => {
  const base = { MAKE: "MINI", MODEL: "Countryman", "结构": "SUV", YEAR: "2020", "DIMENSION-ID": "x", "L-MM": "4313", "W-MM": "1821", "H-MM": "1557", "自动尺码": "YM" };
  const [withMatch] = normalizeAll([rawRecord({ ...base, "匹配尺码": "YL", "规则ID": "Rabc", SHAPE: "SUV-C" })], "HNT");
  assert.equal(withMatch.sizeValue, "YM");
  assert.equal(withMatch.matchedSize, "YL");
  assert.equal(withMatch.ruleId, "Rabc");
  assert.equal(withMatch.shape, "SUV-C");
  const [legacy] = normalizeAll([rawRecord(base)], "HNT");
  assert.equal(legacy.matchedSize, null);
  assert.equal(legacy.ruleId, null);
  const [unmatched] = normalizeAll([rawRecord({ ...base, "自动尺码": "无可用尺码", "匹配尺码": "无可用尺码" })], "HNT");
  assert.equal(unmatched.matchedSize, null);
});

test("规则叠加：US/EU 长度条件为 [长上限 − 容差, 长上限]，附加条件只作说明", () => {
  const overlay = data.ruleOverlay({ ruleId: "R1", region: "US", tolerance: 550, row: { "尺码": "YM", "分类": "越野车", "尺码池": "S", "长上限": "4630", "插片指数上限": "999", "插片指数下限": "", "车型白名单": "" } });
  assert.equal(overlay.lengthMax, 4630);
  assert.equal(overlay.fitLow, 4080);
  assert.equal(overlay.widthMax, null);
  assert.deepEqual(overlay.conditions, ["分类 越野车", "尺码池 S"]);
  const limited = data.ruleOverlay({ ruleId: "R2", region: "US", tolerance: 550, row: { "长上限": "5000", "插片指数上限": "120", "插片指数下限": "60", "车型白名单": "仅 Ford Bronco 1966-1977" } });
  assert.ok(limited.conditions.includes("插片指数 > 60，≤ 120"));
  assert.ok(limited.conditions.some((item) => item.startsWith("白名单")));
  // 容差缺失时不画长度范围，只保留长上限
  assert.equal(data.ruleOverlay({ region: "EU", row: { "长上限": "4500" } }).fitLow, null);
});

test("规则叠加：RU 用本条规则的长宽高上限与余量长上限", () => {
  const overlay = data.ruleOverlay({ ruleId: "R3", region: "RU", tolerance: 635, row: { "亚马逊尺码": "3M", "OZON尺码": "3M", "发货尺码": "L", "分类": "三厢车", "长_mm": "4520", "宽_mm": "2100", "高_mm": "1780", "余量长上限_mm": "500" } });
  assert.deepEqual([overlay.lengthMax, overlay.fitLow, overlay.widthMax, overlay.heightMax], [4520, 4020, 2100, 1780]);
  const fallback = data.ruleOverlay({ region: "RU", tolerance: 635, row: { "长_mm": "4520", "宽_mm": "2100", "高_mm": "1780" } });
  assert.equal(fallback.fitLow, 3885);
  assert.equal(data.ruleOverlay(null), null);
});


test("potential counts each dimension once, preserves fractions/zero and only filters intersecting intervals", () => {
  const record = (id, start, end, value) => ({ dimensionId: id, recordKey:id, marketPotential:value, intervals:[{startYear:start,endYear:end}] });
  const a=record("a",2010,2020,1.234567), b=record("b",2020,2026,0), missing=record("missing",2020,2026,null);
  const configs=[{key:"one",records:[a,a,b,missing]},{key:"two",records:[a,record("old",1990,2000,10)]}];
  const all=data.potentialRecords(configs,null);
  assert.equal(all.length,3);
  const window=data.potentialRecords(configs,{startValue:2019.5,endValue:2021.5});
  assert.deepEqual(window.map(e=>e.record.dimensionId),["a","b"]);
  assert.equal(window.reduce((sum,e)=>sum+e.record.marketPotential,0),1.234567);
  assert.equal(data.potentialRecords(configs,{startValue:2030,endValue:2040}).length,0);
});
