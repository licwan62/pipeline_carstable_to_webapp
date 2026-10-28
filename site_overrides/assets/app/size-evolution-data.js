// 尺码配对「车型尺寸演变」可视化的数据纯函数：记录标准化、稳定身份、年份区间、座位识别、单位换算、同年分支与阶梯连接。
// 不依赖 DOM / ECharts；浏览器下挂到 window.SizeEvolutionData，Node 下 module.exports 供 node --test 使用。
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SizeEvolutionData = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // 车型年份的合理范围：超出视为异常年份，不画到图上（不把空数据或异常值补成当前年）
  const MIN_MODEL_YEAR = 1900;
  const MAX_MODEL_YEAR = 2100;
  // 版本里的座位数只接受 1–20 的明确标记
  const MAX_SEATS = 20;
  // 店铺来源的 SIZE 是发货尺码；国别来源（US/EU/RU 全量）是自动匹配尺码
  const STORE_SOURCES = ["HNT", "TM", "TM_拆分"];
  const REGION_SOURCES = ["US", "EU", "RU"];
  const UNMATCHED_SIZE = "无可用尺码";
  const INCOMPLETE_SIZE = "数据不全";
  const EMPTY_LABELS = { version: "未注明版本", type: "未注明 TYPE", seats: "座位未知", cab: "未注明 CAB", bed: "未注明 BED" };
  const UNIT_FACTORS = { mm: 1, cm: 10, in: 25.4 };
  // YEAR 原文的单年 / 含两端区间（ASCII 连字符、en/em dash 等），以及允许出现的分隔符
  const YEAR_TOKEN = /(?<!\d)(\d{4})(?:\s*[-‐‑‒–—―~～至]\s*(\d{4}))?(?!\d)/g;
  const YEAR_SEPARATORS = /[\s,;，；、/|&]+/g;

  function clean(value) {
    return value === null || value === undefined ? "" : String(value).replace(/\s+/g, " ").trim();
  }

  function orNull(value) {
    const text = clean(value);
    return text ? text : null;
  }

  // 空串、NULL、NaN、非数值转 null；positive=true 时非正数也转 null（尺寸），余量允许 0 与负数
  function toNumberOrNull(value, { positive = false } = {}) {
    if (value === null || value === undefined) return null;
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return null;
      return positive && value <= 0 ? null : value;
    }
    const text = clean(value).replace(/,/g, "");
    if (!text || /^(null|nan|none|n\/a|-)$/i.test(text)) return null;
    if (!/^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/.test(text)) return null;
    const number = Number(text);
    if (!Number.isFinite(number)) return null;
    return positive && number <= 0 ? null : number;
  }

  function validYear(year) {
    return Number.isInteger(year) && year >= MIN_MODEL_YEAR && year <= MAX_MODEL_YEAR;
  }

  // 相邻整数压缩成互不相连的区间，跨过缺口时断开
  function compressYears(years) {
    const sorted = Array.from(new Set(years)).sort((a, b) => a - b);
    const intervals = [];
    sorted.forEach((year) => {
      const last = intervals[intervals.length - 1];
      if (last && year === last.endYear + 1) last.endYear = year;
      else intervals.push({ startYear: year, endYear: year });
    });
    return intervals;
  }

  // 解析 YEAR 原文：单年、含两端的区间（ASCII/en/em dash 等）、逗号等分隔的多个离散年份/区间。
  // 返回 { intervals, issues }；不能可靠解析时退回 years 数组（同样按缺口断开），仍不行则不画并记入 issues。
  function parseYearIntervals(rawYear, yearsFallback) {
    const text = clean(rawYear);
    const issues = [];
    const intervals = [];
    let reliable = Boolean(text);
    if (text) {
      // 逐个识别 "YYYY" 与 "YYYY–YYYY"；剩余文字只能是分隔符，否则原文不可靠
      const leftover = text.replace(YEAR_TOKEN, (match, startText, endText) => {
        const start = Number(startText);
        const end = endText === undefined ? start : Number(endText);
        if (!validYear(start) || !validYear(end)) issues.push({ kind: "year-out-of-range", text: match });
        else if (end < start) issues.push({ kind: "year-inverted", text: match });
        else intervals.push({ startYear: start, endYear: end });
        return " ";
      }).replace(YEAR_SEPARATORS, "");
      if (leftover) {
        reliable = false;
        intervals.length = 0;
        issues.push({ kind: "year-unparsed", text });
      }
    }
    if (reliable && intervals.length) return { intervals: mergeIntervals(intervals), issues, from: "raw" };
    if (reliable && issues.length) return { intervals: [], issues, from: "none" };
    const fallback = Array.isArray(yearsFallback) ? yearsFallback.map(Number).filter(validYear) : [];
    if (fallback.length) {
      return { intervals: compressYears(fallback), issues: text ? issues.concat([{ kind: "year-from-array", text }]) : issues, from: "years" };
    }
    if (!text) issues.push({ kind: "year-missing", text: "" });
    return { intervals: [], issues, from: "none" };
  }

  // 重叠或相接的区间合并（"2011-2013,2013-2015" → 2011–2015）；保留缺口
  function mergeIntervals(intervals) {
    const sorted = intervals.map((item) => ({ ...item })).sort((a, b) => a.startYear - b.startYear || a.endYear - b.endYear);
    const merged = [];
    sorted.forEach((item) => {
      const last = merged[merged.length - 1];
      if (last && item.startYear <= last.endYear + 1) last.endYear = Math.max(last.endYear, item.endYear);
      else merged.push(item);
    });
    return merged;
  }

  function intervalYears(intervals) {
    const years = [];
    intervals.forEach(({ startYear, endYear }) => {
      for (let year = startYear; year <= endYear; year += 1) years.push(year);
    });
    return years;
  }

  function coversYear(intervals, year) {
    return intervals.some(({ startYear, endYear }) => year >= startYear && year <= endYear);
  }

  function intervalsOverlap(left, right) {
    return left.some((a) => right.some((b) => a.startYear <= b.endYear && b.startYear <= a.endYear));
  }

  function formatIntervals(intervals) {
    return intervals.map(({ startYear, endYear }) => (startYear === endYear ? String(startYear) : `${startYear}–${endYear}`)).join(", ");
  }

  // 座位数：优先明确的 SEATS 字段，其次只识别版本里的明确表达（5seat、7-seater、2-Seater、7座）。
  // 不把 L2H1、车型数字或品牌 SEAT 当座位；多个矛盾标记返回 null 并标记 conflict。版本原文不改动。
  const SEAT_PATTERNS = [
    /(?:^|[^A-Za-z0-9])(\d{1,2})\s*[-_ ]?\s*seat(?:s|er|ers)?(?![A-Za-z])/gi,
    /(\d{1,2})\s*(?:座|人座)/g
  ];

  function extractSeats(version, explicitSeats) {
    const explicit = clean(explicitSeats);
    if (explicit && /^\d{1,2}$/.test(explicit)) {
      const value = Number(explicit);
      if (value >= 1 && value <= MAX_SEATS) return { seats: value, source: "field", conflict: false, matches: [explicit] };
    }
    const text = clean(version);
    if (!text) return { seats: null, source: "none", conflict: false, matches: [] };
    const found = [];
    SEAT_PATTERNS.forEach((pattern) => {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(text))) {
        const value = Number(match[1]);
        if (value >= 1 && value <= MAX_SEATS) found.push({ value, text: match[0].trim() });
      }
    });
    const values = Array.from(new Set(found.map((item) => item.value)));
    if (values.length === 1) return { seats: values[0], source: "version", conflict: false, matches: found.map((item) => item.text) };
    if (values.length > 1) return { seats: null, source: "version", conflict: true, matches: found.map((item) => item.text) };
    return { seats: null, source: "none", conflict: false, matches: [] };
  }

  function isStoreSource(source) {
    return STORE_SOURCES.includes(clean(source));
  }

  function regionOf(source, group) {
    const name = clean(source);
    if (REGION_SOURCES.includes(name)) return name;
    if (clean(group)) return clean(group);
    return isStoreSource(name) ? "US" : name;
  }

  function sizeMeaningOf(source) {
    return isStoreSource(source) ? "shipping" : "match";
  }

  function matchStatusOf(sizeValue) {
    const size = clean(sizeValue);
    if (!size) return "unknown";
    if (size === UNMATCHED_SIZE) return "unmatched";
    if (size === INCOMPLETE_SIZE) return "incomplete";
    return "matched";
  }

  // 稳定 JSON：键排序，供指纹与结构化元组序列化
  function stableStringify(value) {
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
    }
    return JSON.stringify(value === undefined ? null : value);
  }

  // FNV-1a 32 位指纹（base36），只用于区分同 ID 不同内容的记录
  function fingerprint(text) {
    let hash = 0x811c9dc5;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(36);
  }

  function rawValues(record) {
    return (record && record.values) || {};
  }

  function field(record, ...names) {
    const values = rawValues(record);
    for (const name of names) {
      const value = values[name];
      if (clean(value)) return clean(value);
    }
    return "";
  }

  function recordMake(record) { return clean(record.make) || field(record, "MAKE"); }
  function recordModel(record) { return clean(record.model) || field(record, "MODEL"); }
  function recordKind(record) {
    if (record.kind === "pick" || record.kind === "nonpick") return record.kind;
    return clean(record.type || record.construct).toUpperCase() === "PICKUP" || field(record, "分类") === "皮卡" ? "pick" : "nonpick";
  }
  function recordYearText(record) { return field(record, "YEAR") || clean(record.year); }
  function recordVersion(record) { return field(record, "版本"); }
  function recordType(record) { return field(record, "TYPE", "结构") || clean(record.type || record.construct); }
  function recordCab(record) { return clean(record.cab) || field(record, "CAB"); }
  function recordBed(record) { return clean(record.bed) || field(record, "BED"); }
  function recordSize(record) { return field(record, "SIZE", "自动尺码") || clean(record.size); }
  function recordMargin(record) {
    const values = rawValues(record);
    // 长度余量（网站别名）与 自动长度余量（A0 原列）同义；0 和负数是有效值，不能用真值判断
    for (const name of ["长度余量", "自动长度余量"]) {
      if (values[name] !== undefined && clean(values[name]) !== "") return values[name];
    }
    return null;
  }

  function modelKey(source, kind, make, model) {
    return stableStringify(["model", clean(source), clean(kind), clean(make), clean(model)]);
  }

  function modelKeyForRecord(record, source) {
    return modelKey(source, recordKind(record), recordMake(record), recordModel(record));
  }

  function parseModelKey(key) {
    try {
      const [, source, kind, make, model] = JSON.parse(key);
      return { source, kind, make, model };
    } catch (error) {
      return null;
    }
  }

  // 无 ID 时的稳定内容键：来源、配置、年份、尺寸、代际、匹配结果
  function contentKeyParts(record, source) {
    return [
      clean(source), recordKind(record), recordMake(record), recordModel(record), recordVersion(record), recordType(record),
      recordCab(record), recordBed(record), recordYearText(record), field(record, "L-MM"), field(record, "W-MM"), field(record, "H-MM"),
      field(record, "代际"), recordSize(record), clean(recordMargin(record)), field(record, "原因")
    ];
  }

  function semanticFingerprint(record) {
    return fingerprint(stableStringify(rawValues(record)));
  }

  // 给同一分片（source + kind + MAKE 的完整记录集）里的记录分配稳定 recordKey：
  // 首选 source + DIMENSION-ID；同 ID 而内容不同的记录追加语义指纹并标记 idConflict；精确重复得到同一个 key。
  function assignRecordKeys(records, source) {
    const byId = new Map();
    records.forEach((record) => {
      const id = field(record, "DIMENSION-ID");
      if (!id) return;
      if (!byId.has(id)) byId.set(id, new Set());
      byId.get(id).add(semanticFingerprint(record));
    });
    records.forEach((record) => {
      const id = field(record, "DIMENSION-ID");
      if (id) {
        const prints = byId.get(id);
        const conflict = prints.size > 1;
        record.recordKey = stableStringify(conflict ? ["id", clean(source), id, semanticFingerprint(record)] : ["id", clean(source), id]);
        record.recordIdConflict = conflict;
      } else {
        record.recordKey = stableStringify(["content", ...contentKeyParts(record, source)]);
        record.recordIdConflict = false;
      }
    });
    return records;
  }

  function recordKeyOf(record, source) {
    if (record.recordKey) return record.recordKey;
    const id = field(record, "DIMENSION-ID");
    return id ? stableStringify(["id", clean(source), id]) : stableStringify(["content", ...contentKeyParts(record, source)]);
  }

  // 配置身份：结构化元组，包含 source、kind、MAKE、MODEL、版本、TYPE、座位、CAB、BED；不含 YEAR、SIZE、尺寸、代际
  function configurationKeyOf(parts) {
    return stableStringify(["config", clean(parts.source), clean(parts.kind), clean(parts.make), clean(parts.model),
      parts.version || "", parts.type || "", parts.seats === null || parts.seats === undefined ? "" : String(parts.seats),
      parts.cab || "", parts.bed || ""]);
  }

  function configurationKeyForRecord(record, source) {
    const seats = extractSeats(recordVersion(record), field(record, "SEATS", "座位数", "座位"));
    return configurationKeyOf({
      source, kind: recordKind(record), make: recordMake(record), model: recordModel(record), version: recordVersion(record),
      type: recordType(record), seats: seats.seats, cab: recordCab(record), bed: recordBed(record)
    });
  }

  function matchedSizeOf(record, meaning, sizeValue) {
    if (matchStatusOf(sizeValue) !== "matched") return null;
    if (meaning === "match") return sizeValue;
    const matched = orNull(field(record, "匹配尺码"));
    return matched && matchStatusOf(matched) === "matched" ? matched : null;
  }

  // 命中规则的叠加几何（全部 mm）：US/EU 长度条件 = [长上限 − 余量长容差, 长上限]，其余条件（分类、尺码池、版本、CAB、
  // 插片指数、白名单）只作说明；RU 用本条规则的 长_mm / 宽_mm / 高_mm 上限与 余量长上限_mm（缺省用报告的余量长容差）。
  function ruleOverlay(rule) {
    if (!rule || !rule.row) return null;
    const row = rule.row;
    const region = clean(rule.region).toUpperCase();
    const number = (value) => toNumberOrNull(value);
    const text = (name) => clean(row[name]);
    const positive = (value) => (value !== null && value > 0 ? value : null);
    if (region === "RU") {
      const lengthMax = positive(number(row["长_mm"]));
      const tolerance = positive(number(row["余量长上限_mm"])) ?? positive(number(rule.tolerance));
      return {
        ruleId: clean(rule.ruleId), region, lengthMax, tolerance,
        fitLow: lengthMax !== null && tolerance !== null ? Math.max(0, lengthMax - tolerance) : null,
        widthMax: positive(number(row["宽_mm"])), heightMax: positive(number(row["高_mm"])),
        size: text("亚马逊尺码") || text("尺码"),
        conditions: [text("分类") && `分类 ${text("分类")}`, text("OZON尺码") && `OZON ${text("OZON尺码")}`, text("发货尺码") && `发货 ${text("发货尺码")}`].filter(Boolean)
      };
    }
    const lengthMax = positive(number(row["长上限"]));
    const tolerance = positive(number(rule.tolerance));
    const insertMax = number(row["插片指数上限"]);
    const insertMin = number(row["插片指数下限"]);
    const insert = [insertMin !== null && `> ${insertMin}`, insertMax !== null && insertMax < 999 && `≤ ${insertMax}`].filter(Boolean).join("，");
    return {
      ruleId: clean(rule.ruleId), region, lengthMax, tolerance,
      fitLow: lengthMax !== null && tolerance !== null ? Math.max(0, lengthMax - tolerance) : null,
      widthMax: null, heightMax: null,
      size: text("尺码") || text("内部尺码"),
      conditions: [
        text("分类") && `分类 ${text("分类")}`,
        text("模式") && `模式 ${text("模式")}`,
        text("尺码池") && `尺码池 ${text("尺码池")}`,
        text("版本") && `版本 ${text("版本")}`,
        text("CAB") && `CAB ${text("CAB")}`,
        insert && `插片指数 ${insert}`,
        text("车型白名单") && `白名单 ${text("车型白名单")}`
      ].filter(Boolean)
    };
  }

  function normalizeRecord(record, context = {}) {
    const source = clean(context.source || field(record, "SOURCE"));
    const yearText = recordYearText(record);
    const years = parseYearIntervals(yearText, record.years);
    const seatInfo = extractSeats(recordVersion(record), field(record, "SEATS", "座位数", "座位"));
    const sizeValue = orNull(recordSize(record));
    const meaning = sizeMeaningOf(source);
    const issues = years.issues.slice();
    const lengthMm = toNumberOrNull(field(record, "L-MM"), { positive: true });
    const widthMm = toNumberOrNull(field(record, "W-MM"), { positive: true });
    const heightMm = toNumberOrNull(field(record, "H-MM"), { positive: true });
    if (lengthMm === null || widthMm === null || heightMm === null) issues.push({ kind: "dimension-missing", text: "" });
    if (seatInfo.conflict) issues.push({ kind: "seats-conflict", text: seatInfo.matches.join(" / ") });
    if (record.recordIdConflict) issues.push({ kind: "id-conflict", text: field(record, "DIMENSION-ID") });
    const normalized = {
      recordKey: recordKeyOf(record, source),
      dimensionId: orNull(field(record, "DIMENSION-ID")),
      marketPotential: toNumberOrNull(field(record, "市场潜力")),
      potentialAdjustment: toNumberOrNull(field(record, "销量潜力调整")),
      source,
      sourceLabel: clean(context.sourceLabel) || source,
      region: regionOf(source, context.group),
      kind: recordKind(record),
      make: recordMake(record),
      model: recordModel(record),
      version: orNull(recordVersion(record)),
      type: orNull(recordType(record)),
      seats: seatInfo.seats,
      seatsConflict: seatInfo.conflict,
      seatsText: seatInfo.matches.join(" / "),
      cab: orNull(recordCab(record)),
      bed: orNull(recordBed(record)),
      generation: orNull(field(record, "代际")),
      yearText,
      intervals: years.intervals,
      yearsFrom: years.from,
      lengthMm,
      widthMm,
      heightMm,
      sizeValue,
      sizeMeaning: meaning,
      lengthMarginMm: toNumberOrNull(recordMargin(record)),
      matchStatus: matchStatusOf(sizeValue),
      // 实际匹配尺码：国别来源即 SIZE；店铺来源只认 A0 店铺表的「匹配尺码」（换码前），没有该列时为 null，不用发货 SIZE 冒充
      matchedSize: matchedSizeOf(record, meaning, sizeValue),
      // A0 全量表「规则ID」：本行命中的规则（未匹配为空）；含义以同版本 尺码匹配报告 规则表为准
      ruleId: orNull(field(record, "规则ID")),
      shape: orNull(field(record, "SHAPE")),
      ozonSize: orNull(field(record, "OZON尺码")),
      shippingSize: orNull(field(record, "发货尺码")),
      candidate: orNull(field(record, "候选")),
      reason: orNull(field(record, "原因")),
      difference: toNumberOrNull(field(record, "相差数值")),
      idConflict: Boolean(record.recordIdConflict),
      issues,
      raw: rawValues(record),
      rawRefs: [record]
    };
    normalized.configurationKey = configurationKeyOf(normalized);
    normalized.modelKey = modelKey(source, normalized.kind, normalized.make, normalized.model);
    return normalized;
  }

  // 精确重复（同 recordKey）合并为一条，保留全部原始引用
  function dedupeRecords(normalizedRecords) {
    const byKey = new Map();
    normalizedRecords.forEach((record) => {
      const existing = byKey.get(record.recordKey);
      if (existing) existing.rawRefs.push(...record.rawRefs);
      else byKey.set(record.recordKey, record);
    });
    return Array.from(byKey.values());
  }

  function configurationLabelParts(record, { includeModel = true } = {}) {
    const parts = [];
    if (includeModel) parts.push(`${record.make} ${record.model}`);
    parts.push(record.version || EMPTY_LABELS.version);
    parts.push(record.type || EMPTY_LABELS.type);
    parts.push(record.seats === null ? EMPTY_LABELS.seats : `${record.seats} 座`);
    if (record.kind === "pick") {
      parts.push(record.cab ? `CAB ${record.cab}` : EMPTY_LABELS.cab);
      parts.push(record.bed ? `BED ${record.bed}` : EMPTY_LABELS.bed);
    }
    return parts;
  }

  function configurationLabel(record, options) {
    return configurationLabelParts(record, options).join(" · ");
  }

  function compareText(left, right) {
    return String(left || "").localeCompare(String(right || ""), "en", { numeric: true, sensitivity: "base" });
  }

  function firstYear(record) {
    return record.intervals.length ? record.intervals[0].startYear : Number.POSITIVE_INFINITY;
  }

  // 同配置内按年份把记录分到互不重叠的分支（SIZE 带子行）：先到先占，同年冲突的记录进入下一条分支
  function assignBranches(records) {
    const lanes = [];
    const sorted = records.slice().sort((a, b) => firstYear(a) - firstYear(b)
      || compareText(a.generation, b.generation) || compareText(a.yearText, b.yearText) || compareText(a.recordKey, b.recordKey));
    sorted.forEach((record) => {
      if (!record.intervals.length) return;
      let lane = lanes.find((items) => !items.some((item) => intervalsOverlap(item.intervals, record.intervals)));
      if (!lane) { lane = []; lanes.push(lane); }
      lane.push(record);
      record.branchIndex = lanes.indexOf(lane);
    });
    return lanes;
  }

  // 同年覆盖计数：count > 1 的年份是同配置同年冲突/重叠
  function yearCoverage(records, pick) {
    const coverage = new Map();
    records.forEach((record) => {
      if (pick && !pick(record)) return;
      intervalYears(record.intervals).forEach((year) => {
        if (!coverage.has(year)) coverage.set(year, []);
        coverage.get(year).push(record);
      });
    });
    return coverage;
  }

  const DIMENSIONS = { length: "lengthMm", width: "widthMm", height: "heightMm" };

  // 阶梯连接：同配置、前后年份连续，且边界两侧各只有一个该维度有效的记录；跳变落在年份边界 (year + 0.5)
  function stepConnections(records, dimension) {
    const prop = DIMENSIONS[dimension] || dimension;
    const coverage = yearCoverage(records, (record) => record[prop] !== null);
    const connections = [];
    const seen = new Set();
    Array.from(coverage.keys()).sort((a, b) => a - b).forEach((year) => {
      const left = coverage.get(year);
      const right = coverage.get(year + 1);
      if (!right || left.length !== 1 || right.length !== 1) return;
      const [from] = left;
      const [to] = right;
      if (from === to) return;
      const endsHere = from.intervals.some((item) => item.endYear === year);
      const startsNext = to.intervals.some((item) => item.startYear === year + 1);
      if (!endsHere || !startsNext) return;
      const key = `${from.recordKey}>${to.recordKey}`;
      if (seen.has(key)) return;
      seen.add(key);
      connections.push({ year, x: year + 0.5, from: from[prop], to: to[prop], fromKey: from.recordKey, toKey: to.recordKey });
    });
    return connections;
  }

  // 包含两端的年份区间映射到数值轴 [start - 0.5, end + 0.5]，单年也有可点击宽度
  function intervalGeometry(interval) {
    return [interval.startYear - 0.5, interval.endYear + 0.5];
  }

  // 把标准化记录组织成配置集合：每个配置的记录、分支、同年重叠、阶梯连接
  function buildConfigurations(records, { selectedConfigurationKeys = [], anchorRecordKeys = [] } = {}) {
    const selected = new Set(selectedConfigurationKeys);
    const anchors = new Set(anchorRecordKeys);
    const byConfig = new Map();
    records.forEach((record) => {
      if (!byConfig.has(record.configurationKey)) byConfig.set(record.configurationKey, []);
      byConfig.get(record.configurationKey).push(record);
    });
    const models = new Set(records.map((record) => record.modelKey));
    const configurations = Array.from(byConfig.entries()).map(([key, items]) => {
      const sample = items[0];
      const lanes = assignBranches(items);
      const coverage = yearCoverage(items);
      const overlapYears = Array.from(coverage.entries()).filter(([, list]) => list.length > 1).map(([year]) => year).sort((a, b) => a - b);
      return {
        key,
        modelKey: sample.modelKey,
        source: sample.source,
        kind: sample.kind,
        make: sample.make,
        model: sample.model,
        version: sample.version,
        type: sample.type,
        seats: sample.seats,
        cab: sample.cab,
        bed: sample.bed,
        label: configurationLabel(sample, { includeModel: true }),
        shortLabel: configurationLabel(sample, { includeModel: models.size > 1 }),
        records: items,
        lanes,
        overlapYears,
        connections: {
          length: stepConnections(items, "length"),
          width: stepConnections(items, "width"),
          height: stepConnections(items, "height")
        },
        selected: selected.has(key),
        hasAnchor: items.some((item) => anchors.has(item.recordKey))
      };
    });
    configurations.sort((a, b) => compareText(a.make, b.make) || compareText(a.model, b.model)
      || compareText(a.version || "￿", b.version || "￿") || compareText(a.type, b.type)
      || (a.seats ?? 99) - (b.seats ?? 99) || compareText(a.cab, b.cab) || compareText(a.bed, b.bed) || compareText(a.key, b.key));
    configurations.forEach((configuration, index) => { configuration.colorIndex = index; });
    // 紧凑标签（SIZE 带行标题）：只保留各配置之间有差异的字段，避免截断后丢掉 CAB/BED 等区分信息
    const partLists = configurations.map((configuration) => configurationLabelParts(configuration.records[0], { includeModel: true }));
    const varying = (partLists[0] || []).map((part, index) => partLists.some((parts) => parts[index] !== part));
    configurations.forEach((configuration, index) => {
      const parts = partLists[index].filter((part, partIndex) => varying[partIndex]);
      configuration.compactLabel = parts.length ? parts.join(" · ") : configuration.shortLabel;
    });
    return configurations;
  }

  // 首次默认最多显示 limit 个配置：已选/锚点配置优先，其余按稳定名称顺序
  function defaultVisibleConfigurations(configurations, limit = 6) {
    const priority = configurations.filter((item) => item.selected || item.hasAnchor);
    const rest = configurations.filter((item) => !item.selected && !item.hasAnchor);
    return [...priority, ...rest].slice(0, Math.max(limit, priority.length)).map((item) => item.key);
  }

  function convertFromMm(mm, unit) {
    if (mm === null || mm === undefined || !Number.isFinite(mm)) return null;
    return mm / (UNIT_FACTORS[unit] || 1);
  }

  function convertToMm(value, unit) {
    if (value === null || value === undefined || !Number.isFinite(value)) return null;
    return value * (UNIT_FACTORS[unit] || 1);
  }

  // 只在显示时舍入：mm 取整，cm / in 保留 1 位小数
  function formatMeasure(mm, unit, { withUnit = true } = {}) {
    const value = convertFromMm(mm, unit);
    if (value === null) return "—";
    const digits = unit === "mm" ? 0 : 1;
    const text = value.toFixed(digits);
    return withUnit ? `${text} ${unit}` : text;
  }

  // 店铺来源的 SIZE 是发货尺码：有值只说明有发货尺码，不代表已知实际匹配尺码
  function matchStatusLabel(status, meaning) {
    if (status === "matched" && meaning === "shipping") return "有发货尺码";
    return { matched: "已匹配", unmatched: "无可用尺码", incomplete: "数据不全", unknown: "SIZE 缺失" }[status] || status;
  }

  function sizeHeading(meaning) {
    return meaning === "shipping" ? "发货 SIZE" : "匹配 SIZE";
  }

  // 记录按当前筛选（版本 / TYPE / 座位 / CAB / BED / 车型）收窄：filters[field] 为允许值数组（空数组 = 不限）
  const FILTER_FIELDS = ["model", "version", "type", "seats", "cab", "bed"];

  function filterValueOf(configuration, name) {
    if (name === "model") return configuration.modelKey;
    const value = configuration[name];
    return value === null || value === undefined ? "" : String(value);
  }

  function configurationMatchesFilters(configuration, filters) {
    return FILTER_FIELDS.every((name) => {
      const allowed = filters && filters[name];
      if (!allowed || !allowed.length) return true;
      return allowed.includes(filterValueOf(configuration, name));
    });
  }

  function issueSummary(records) {
    const counts = { yearInvalid: 0, yearFromArray: 0, dimensionMissing: 0, idConflict: 0, seatsConflict: 0, unmatched: 0, incomplete: 0, sizeMissing: 0 };
    records.forEach((record) => {
      record.issues.forEach((issue) => {
        if (issue.kind === "year-inverted" || issue.kind === "year-unparsed" || issue.kind === "year-out-of-range" || issue.kind === "year-missing") counts.yearInvalid += 1;
        if (issue.kind === "year-from-array") counts.yearFromArray += 1;
        if (issue.kind === "dimension-missing") counts.dimensionMissing += 1;
        if (issue.kind === "id-conflict") counts.idConflict += 1;
        if (issue.kind === "seats-conflict") counts.seatsConflict += 1;
      });
      if (record.matchStatus === "unmatched") counts.unmatched += 1;
      if (record.matchStatus === "incomplete") counts.incomplete += 1;
      if (record.matchStatus === "unknown") counts.sizeMissing += 1;
    });
    return counts;
  }

  // Unique DIMENSION-ID + year atoms; totals across configurations also deduplicate.
  function aggregateSales(configurations, records) {
    const totals = new Map();
    const add = (map, year, id, value) => {
      if (!map.has(year)) map.set(year, { year, known: 0, missing: 0, atomIds: [], seen: new Set() });
      const item = map.get(year);
      const key = `${id}|ATOM_YEAR=${year}`;
      if (item.seen.has(key)) return;
      item.seen.add(key);
      item.atomIds.push(key);
      if (value === null) item.missing += 1;
      else item.known += value;
    };
    const groups = configurations.map((configuration) => {
      const years = new Map();
      configuration.records.forEach((record) => {
        const pairs = new Map(records[record.dimensionId] || []);
        intervalYears(record.intervals).forEach((year) => {
          const value = pairs.has(year) ? pairs.get(year) : null;
          add(years, year, record.dimensionId || record.recordKey, value);
          add(totals, year, record.dimensionId || record.recordKey, value);
        });
      });
      return { configuration, years };
    });
    return { groups, totals };
  }

  // 潜力是整条尺寸记录的分数。年份窗口仅筛选相交记录，不按年重复或折算。
  function potentialRecords(configurations, zoom) {
    const seen = new Set();
    return configurations.flatMap((configuration) => configuration.records.map((record) => ({ configuration, record })))
      .filter(({ record }) => {
        const key = record.dimensionId || record.recordKey;
        if (seen.has(key) || record.marketPotential === null || !Number.isFinite(record.marketPotential) || record.marketPotential < 0) return false;
        if (zoom && !record.intervals.some((interval) => interval.endYear >= Math.ceil(zoom.startValue) && interval.startYear <= Math.floor(zoom.endValue))) return false;
        seen.add(key);
        return true;
      });
  }

  function createSalesLoader(fetchJson, manifestPath) {
    const cache = new Map();
    const get = (path) => {
      if (!cache.has(path)) cache.set(path, Promise.resolve().then(() => fetchJson(path)).catch((error) => { cache.delete(path); throw error; }));
      return cache.get(path);
    };
    return async (modelKeys) => {
      const models = modelKeys.map(parseModelKey).filter(Boolean);
      if (!models.length || models.some((model) => !["US", ...STORE_SOURCES].includes(model.source))) return { supported: false };
      const manifest = await get(manifestPath);
      if (manifest.format_version !== 1) throw new Error("年度销量数据版本不支持");
      const groups = manifest.make_groups.filter((group) => models.some((model) => model.kind === group.kind && model.make === group.make));
      const shards = await Promise.all(groups.map((group) => get(manifestPath.slice(0, manifestPath.lastIndexOf("/") + 1) + group.records_path)));
      const records = {};
      shards.forEach((shard) => models.filter((model) => model.kind === shard.kind && model.make === shard.make).forEach((model) => {
        (shard.models[model.model] || []).forEach((id) => { records[id] = shard.records[id]; });
      }));
      return { supported: true, records, origin: manifest.origin };
    };
  }

  return {
    aggregateSales,
    potentialRecords,
    createSalesLoader,
    MIN_MODEL_YEAR,
    MAX_MODEL_YEAR,
    STORE_SOURCES,
    EMPTY_LABELS,
    FILTER_FIELDS,
    clean,
    toNumberOrNull,
    parseYearIntervals,
    mergeIntervals,
    compressYears,
    intervalYears,
    coversYear,
    intervalsOverlap,
    formatIntervals,
    intervalGeometry,
    extractSeats,
    isStoreSource,
    regionOf,
    sizeMeaningOf,
    matchStatusOf,
    matchStatusLabel,
    sizeHeading,
    stableStringify,
    fingerprint,
    modelKey,
    modelKeyForRecord,
    parseModelKey,
    assignRecordKeys,
    recordKeyOf,
    configurationKeyOf,
    configurationKeyForRecord,
    configurationLabel,
    normalizeRecord,
    ruleOverlay,
    dedupeRecords,
    assignBranches,
    yearCoverage,
    stepConnections,
    buildConfigurations,
    defaultVisibleConfigurations,
    configurationMatchesFilters,
    filterValueOf,
    convertFromMm,
    convertToMm,
    formatMeasure,
    issueSummary
  };
});
