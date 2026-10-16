// 尺码配对 / Size Chart 页面（viewer.js）的数据纯函数：TSV/YAML 解析、记录提取、年份展开、搜索分词、排序比较、文本清洗。
// 不依赖 DOM 与页面状态；浏览器下挂到 window.SizeViewerData（须在 viewer.js 之前加载），Node 下 module.exports 供 node --test 使用。
// 2026-10-14 从 viewer.js 原样拆出（函数体未改），viewer.js 首行按同名解构使用。
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SizeViewerData = api;
})(typeof self !== "undefined" ? self : this, function () {
  function extractRecords(doc, file, directory, columns) {
    const records = [];
    const tags = sourceTags(directory.name);
    doc.querySelectorAll(".brand-table").forEach((tableBlock) => {
      const isPickup = tableBlock.classList.contains("profile-pickup");
      const title = normalizeMake(cleanText(tableBlock.querySelector(".brand-title-main, h2")));
      const fallbackMake = isPickup ? logoMake(tableBlock) : title;
      const description = cleanText(tableBlock.querySelector(".brand-title-description"));
      const headers = Array.from(tableBlock.querySelectorAll("thead th")).map(cleanText);
      headers.forEach((header) => {
        if (header && !columns.includes(header)) {
          columns.push(header);
        }
      });

      tableBlock.querySelectorAll("tbody tr").forEach((row) => {
        const values = {};
        Array.from(row.children).forEach((cell, index) => {
          const header = headers[index] || `COL ${index + 1}`;
          values[header] = cleanText(cell);
        });
        const year = values.YEAR || values.Year || "";
        records.push({
          make: fallbackMake,
          model: values.MODEL || values.Model || "",
          year,
          years: expandYears(year),
          construct: values.CONST || values.CONSTRUCT || values.Const || "",
          values,
          title,
          description,
          searchText: "",
          directory: directory.name,
          source: `${directory.name}/${file}`,
          sourceTags: tags,
          file
        });
      });
    });
    return records;
  }

  function parseTsv(text) {
    const normalizedText = text
      .replace(/^\uFEFF/, "")
      .replace(/"([^"]*)\r?\n([^"]*)"/g, (_, before, after) => `"${before} ${after}"`);
    const lines = normalizedText.split(/\r?\n/).filter((line) => line.trim());
    if (!lines.length) {
      return [];
    }
    const headers = lines[0].split("\t").map((header) => header.trim().replace(/^"|"$/g, ""));
    return lines.slice(1).map((line) => {
      const cells = line.split("\t");
      const row = {};
      headers.forEach((header, index) => {
        row[header] = cleanField(cells[index]);
      });
      return row;
    });
  }

  function pickupKey(row) {
    return [
      cleanField(row.title).toUpperCase(),
      cleanField(row.year),
      cleanField(row.cab).toUpperCase(),
      cleanField(row.bed),
      cleanField(row.size).toUpperCase()
    ].join("|");
  }

  function nonPickupKey(row) {
    return [
      cleanField(row.make).toUpperCase(),
      cleanField(row.model).toUpperCase(),
      cleanField(row.year),
      cleanField(row.type).toUpperCase(),
      cleanField(row.size).toUpperCase()
    ].join("|");
  }

  function sameText(left, right) {
    return cleanField(left).toUpperCase() === cleanField(right).toUpperCase();
  }

  // 数据分片带 kind；旧数据按 TYPE=Pickup 或 分类=皮卡 判定
  function recordKind(record) {
    if (record.kind) return record.kind;
    return sameText(record.type || record.construct, "Pickup") || cleanField(record.values?.["分类"]) === "皮卡" ? "pick" : "nonpick";
  }

  function compareBedValues(left, right) {
    const leftNumber = firstNumber(left);
    const rightNumber = firstNumber(right);
    if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && leftNumber !== rightNumber) {
      return leftNumber - rightNumber;
    }
    if (Number.isFinite(leftNumber) !== Number.isFinite(rightNumber)) {
      return Number.isFinite(leftNumber) ? -1 : 1;
    }
    return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
  }

  function firstNumber(value) {
    const match = cleanField(value).match(/\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : Number.NaN;
  }

  function compareValues(left, right) {
    const leftNumber = Number(left);
    const rightNumber = Number(right);
    if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
      return leftNumber - rightNumber;
    }
    return String(left || "").localeCompare(String(right || ""), undefined, { numeric: true });
  }

  function fieldAtoms(value) {
    const text = cleanField(value);
    if (!text) {
      return [];
    }
    return uniqueInOrder(text.split(/\s*(?:\/|,|;|\||\+|&)\s*/).map(cleanField));
  }

  function fieldAtomicValues(value) {
    const text = cleanField(value);
    if (!text) {
      return [];
    }
    const years = expandYearRangeAtoms(text);
    if (years.length) {
      return years;
    }
    const pieces = text.split(/\s*(?:\/|\\|,|;|\|)\s*/).map(cleanField).filter(Boolean);
    return uniqueInOrder(pieces.length > 1 ? pieces : [text]);
  }

  function expandYearRangeAtoms(value) {
    const text = cleanField(value);
    const atoms = [];
    const rangePattern = /\b((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})\b/g;
    let match;
    while ((match = rangePattern.exec(text))) {
      const start = Number(match[1]);
      const end = Number(match[2]);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end < start || end - start > 100) {
        continue;
      }
      for (let year = start; year <= end; year += 1) {
        atoms.push(String(year));
      }
    }
    if (atoms.length) {
      return uniqueInOrder(atoms);
    }
    const singleYear = text.match(/^(?:19|20)\d{2}$/);
    return singleYear ? [text] : [];
  }

  function parseSizeViewYaml(text) {
    const result = { filters: {}, table_fields: {}, excel_source: {}, match_sources: [], size_reference: {}, size_colors: {} };
    let section = "";
    let keyName = "";
    let currentMatchSource = null;
    text.split(/\r?\n/).forEach((line) => {
      if (!line.trim() || line.trim().startsWith("#")) return;
      const indent = (line.match(/^\s*/) || [""])[0].length;
      const trimmed = line.trim();
      if (indent === 0 && trimmed.endsWith(":")) {
        section = trimmed.slice(0, -1);
        keyName = "";
        currentMatchSource = null;
        return;
      }
      if (section === "match_sources" && indent === 2 && trimmed.startsWith("- ")) {
        currentMatchSource = {};
        result.match_sources.push(currentMatchSource);
        const rest = trimmed.slice(2);
        if (rest.includes(":")) {
          const [rawKey, ...rawValue] = rest.split(":");
          currentMatchSource[rawKey.trim()] = parseYamlValue(rawValue.join(":").trim());
        }
        return;
      }
      if (section === "match_sources" && indent >= 4 && currentMatchSource && trimmed.includes(":")) {
        const [rawKey, ...rawValue] = trimmed.split(":");
        currentMatchSource[rawKey.trim()] = parseYamlValue(rawValue.join(":").trim());
        return;
      }
      if (indent === 2 && section === "excel_source" && trimmed.includes(":")) {
        const [rawKey, ...rawValue] = trimmed.split(":");
        result.excel_source[rawKey.trim()] = parseYamlValue(rawValue.join(":").trim());
        return;
      }
      if (indent === 2 && trimmed.endsWith(":") && (section === "filters" || section === "table_fields")) {
        keyName = trimmed.slice(0, -1);
        result[section][keyName] = result[section][keyName] || {};
        return;
      }
      if (indent === 2 && section === "size_reference" && trimmed.includes(":")) {
        const [rawKey, ...rawValue] = trimmed.split(":");
        result.size_reference[rawKey.trim()] = parseYamlValue(rawValue.join(":").trim());
        return;
      }
      if (indent === 2 && section === "size_colors" && trimmed.includes(":")) {
        const [rawKey, ...rawValue] = trimmed.split(":");
        result.size_colors[rawKey.trim()] = parseYamlValue(rawValue.join(":").trim());
        return;
      }
      if (indent >= 4 && keyName && trimmed.includes(":")) {
        const [rawKey, ...rawValue] = trimmed.split(":");
        result[section][keyName][rawKey.trim()] = parseYamlValue(rawValue.join(":").trim());
      }
    });
    return result;
  }

  function parseYamlValue(value) {
    const cleaned = value.replace(/^["']|["']$/g, "");
    if (/^(true|false)$/i.test(cleaned)) {
      return cleaned.toLowerCase() === "true";
    }
    return cleaned;
  }

  function mergeViewConfig(fallback, parsed) {
    const merged = {
      filters: { ...fallback.filters },
      table_fields: { ...fallback.table_fields },
      excel_source: { ...fallback.excel_source, ...(parsed.excel_source || {}) },
      match_sources: parsed.match_sources || fallback.match_sources || [],
      size_reference: { ...fallback.size_reference, ...(parsed.size_reference || {}) },
      size_colors: { ...fallback.size_colors, ...(parsed.size_colors || {}) }
    };
    Object.entries(parsed.filters || {}).forEach(([key, value]) => {
      merged.filters[key] = { ...(merged.filters[key] || {}), ...value };
    });
    Object.entries(parsed.table_fields || {}).forEach(([key, value]) => {
      merged.table_fields[key] = { ...(merged.table_fields[key] || {}), ...value };
    });
    return merged;
  }

  function csvList(value) {
    if (Array.isArray(value)) return value;
    return String(value || "").split(",").map(cleanField).filter(Boolean);
  }

  function unique(values) {
    return Array.from(new Set(values.filter(Boolean))).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  }

  function uniqueInOrder(values) {
    const result = [];
    values.filter(Boolean).forEach((value) => {
      if (!result.includes(value)) {
        result.push(value);
      }
    });
    return result;
  }

  function uniqueYears(records) {
    const years = new Set();
    records.forEach((record) => record.years.forEach((year) => years.add(year)));
    return Array.from(years).sort((a, b) => a - b).map(String);
  }

  function expandYears(value) {
    const text = String(value || "");
    const rangeMatch = text.match(/\b(19\d{2}|20\d{2})\s*[-–]\s*(19\d{2}|20\d{2})\b/);
    if (rangeMatch) {
      const start = Number(rangeMatch[1]);
      const end = Number(rangeMatch[2]);
      if (end >= start && end - start <= 150) {
        const years = [];
        for (let year = start; year <= end; year += 1) {
          years.push(year);
        }
        return years;
      }
    }
    return Array.from(new Set((text.match(/\b(?:19|20)\d{2}\b/g) || []).map(Number)));
  }

  function normalizeMake(value) {
    return String(value || "").replace(/\s+\d+\s*\/\s*\d+\s*$/, "").trim();
  }

  function logoMake(tableBlock) {
    const alt = cleanField(tableBlock.querySelector(".brand-title-logo")?.getAttribute("alt"));
    return alt.replace(/\s+logo$/i, "");
  }

  function sourceTags(directoryName) {
    const normalized = normalizeSearchText(directoryName);
    const tags = new Set(normalized.split(/\s+/).filter(Boolean));
    if (normalized.includes("nonpick")) {
      tags.add("nonpick");
    } else if (normalized.includes("pick")) {
      tags.add("pick");
    }
    return Array.from(tags);
  }

  function searchTokens(value) {
    return normalizeSearchText(value).split(/\s+/).filter(Boolean);
  }

  function normalizeSearchText(value) {
    return String(value || "").toLowerCase().replace(/[-_/]+/g, " ").replace(/\s+/g, " ").trim();
  }

  // 同 MAKE、同 MODEL，且记录年份与代码年份区间有交集
  function recordMatchesVehicleCode(record, vehicleCode) {
    if (!sameText(record.make, vehicleCode.make) || !sameText(record.model, vehicleCode.model)) {
      return false;
    }
    const years = Array.isArray(record.years) && record.years.length ? record.years : expandYears(record.year);
    return years.some((year) => year >= vehicleCode.start && year <= vehicleCode.end);
  }

  function recordSearchAtoms(record) {
    if (record.searchAtoms) {
      return record.searchAtoms;
    }
    const values = [
      record.source,
      record.make,
      record.model,
      record.type,
      record.year,
      record.title,
      record.description,
      record.searchText,
      ...Object.values(record.values || {})
    ];
    const atoms = [];
    values.forEach((value) => {
      const text = cleanField(value);
      if (!text) return;
      atoms.push(text, ...fieldAtomicValues(text));
    });
    if (Array.isArray(record.years)) {
      record.years.forEach((year) => atoms.push(String(year)));
    }
    record.searchAtoms = uniqueInOrder(atoms.map(normalizeSearchText).filter(Boolean));
    return record.searchAtoms;
  }

  // ---------- 尺码配对数据（size-match-data.json，format_version 4）：一份分片，两种视图 ----------
  // 分片 records = A0 全量行（全量表视图），compressed = A1 压缩记录 {values, refs: [[行号, 被覆盖年份], ...]}（压缩表视图）。
  // 压缩记录不重复存放 A0 行：来源行按 refs 从本分片 records 还原，字段同构建端 build_size_match_code_data.to_source。
  const PICKUP_TYPE = "Pickup";

  // 同构建端 parse_years：一个四位数取它本身，多个取首尾之间的连续年份
  function spanYears(value) {
    const numbers = (String(value || "").match(/\d{4}/g) || []).map(Number);
    if (numbers.length <= 1) return numbers;
    const years = [];
    for (let year = numbers[0]; year <= numbers[numbers.length - 1]; year += 1) years.push(year);
    return years;
  }

  function compressedSourceRow(row, year, pickup) {
    const values = (row && row.values) || {};
    const text = (key) => String(values[key] ?? "");
    return {
      "DIMENSION-ID": text("DIMENSION-ID"), MODEL: text("MODEL"), "版本": text("版本"), YEAR: String(year ?? ""),
      TYPE: pickup ? PICKUP_TYPE : text("结构"), CAB: text("CAB"), BED: text("BED"),
      "L-MM": text("L-MM"), "W-MM": text("W-MM"), "H-MM": text("H-MM"),
      SHAPE: text("SHAPE"), "长度余量": text("自动长度余量"), "规则ID": text("规则ID"), "匹配尺码": text("匹配尺码")
    };
  }

  // 返回 { full: { records, columns }, compressed: { records, columns } | null }；旧格式（只有 records）没有压缩视图
  function expandMatchShard(payload) {
    const rows = Array.isArray(payload?.records) ? payload.records : [];
    const full = { records: rows, columns: payload?.columns || [] };
    if (!Array.isArray(payload?.compressed)) return { full, compressed: null };
    const pickup = payload.kind === "pick";
    const records = payload.compressed.map((item, position) => {
      const values = item.values || {};
      const sources = (item.refs || []).map(([index, year]) => {
        if (!rows[index]) throw new Error(`Compressed record ${position} of ${payload.name}/${payload.make} refers to missing row ${index}`);
        return compressedSourceRow(rows[index], year, pickup);
      });
      const type = String(values.TYPE ?? "");
      return {
        make: String(values.MAKE || payload.make || ""), model: String(values.MODEL ?? ""), year: String(values.YEAR ?? ""),
        years: spanYears(values.YEAR), construct: type, type, cab: String(values.CAB ?? ""), bed: String(values.BED ?? ""),
        size: String(values.SIZE ?? ""), kind: payload.kind || (pickup ? "pick" : "nonpick"), values, sources
      };
    });
    return { full, compressed: { records, columns: payload.compressed_columns || [] } };
  }

  // ---------- 全局搜索：按字段语义匹配，不在整行文本里做子串匹配 ----------
  // 旧逻辑把整行（含年份、长宽高、销量、CODE、尺码）拼成一段做子串匹配，「bmw 7」里的 7 命中 2017、长宽高、销量等，
  // 结果混入 3/5 系等上下文之外的车型。查询按空格分词，词内连字符等分隔去掉（f-150 → f150，cr-v → crv），
  // 年份区间（2019-2021）拆成两个年份；每个词都要命中（AND）：
  // - 纯数字词：四位年份 → 记录年份包含该年；≥4 位 → CODE 前缀；其余只与 MODEL、版本 按空格分出的整词（去连字符）比较，
  //   要求整段数字相同（7 → 7、7 Series，不命中 X7/i7/700/740i/3 Series；740 → 740i；mazda 3 → 3，不命中 CX-3/CX-30）；
  //   车型名以品牌开头连写的（Mazda3）也可命中。
  // - 含中文的词：在身份字段文本（含 SHAPE 中文名）中做子串匹配。
  // - 其他词：身份字段（MAKE、MODEL、版本、TYPE、SHAPE、CAB、BED、SIZE、CODE；≥4 字符时含 规则ID）的单词前缀
  //   （含连字符拆开的部分，benz → Mercedes-Benz）或整段去分隔后的前缀（landrover → Land Rover）。长宽高、销量、长度余量、年份文本不参与。
  const IDENTITY_FIELDS = ["MAKE", "MODEL", "版本", "TYPE", "CONST", "结构", "SHAPE", "CAB", "BED", "SIZE", "CODE"];
  const NUMERIC_FIELDS = ["MODEL", "版本"];
  const RULE_ID_MIN_LENGTH = 4;
  const CJK = /[㐀-鿿]/;
  const WORD_SEPARATORS = /[-_/]+/g;

  function searchQueryTokens(value) {
    return String(value || "").toLowerCase().split(/\s+/).flatMap((part) => {
      const range = /^((?:19|20)\d{2})[-–]((?:19|20)\d{2})$/.exec(part);
      if (range) return [range[1], range[2]];
      const compact = part.replace(WORD_SEPARATORS, "");
      return compact ? [compact] : [];
    });
  }

  function fieldWords(text) {
    return normalizeSearchText(text).split(/\s+/).filter(Boolean);
  }

  function compactWords(text) {
    return String(text || "").toLowerCase().split(/\s+/).map((word) => word.replace(WORD_SEPARATORS, "")).filter(Boolean);
  }

  function recordSearchIndex(record, shapeLabels = {}) {
    if (record.searchIndex) return record.searchIndex;
    const values = record.values || {};
    const pick = (key) => cleanField(values[key] ?? (key === "MAKE" ? record.make : key === "MODEL" ? record.model : ""));
    const fields = {};
    IDENTITY_FIELDS.forEach((key) => { fields[key] = pick(key); });
    if (!fields.TYPE) fields.TYPE = cleanField(record.type || record.construct);
    if (!fields.SIZE) fields.SIZE = cleanField(record.size);
    // HTML 尺码表记录（Size Chart 页）没有结构化字段时退回标题与说明
    const hasFields = Object.values(fields).some(Boolean);
    const extra = hasFields ? [] : [record.title, record.description].map(cleanField).filter(Boolean);
    const shapes = fieldAtoms(fields.SHAPE).map((shape) => shapeLabels[shape]?.label || "").filter(Boolean);
    const texts = [...Object.values(fields), ...extra, ...shapes].filter(Boolean);
    const words = uniqueInOrder(texts.flatMap((text) => [...fieldWords(text), ...compactWords(text)]));
    const compacts = uniqueInOrder(texts.map((text) => normalizeSearchText(text).replace(/\s+/g, "")).filter(Boolean));
    const make = normalizeSearchText(fields.MAKE).replace(/\s+/g, "");
    const numericWords = uniqueInOrder([...NUMERIC_FIELDS.map((key) => fields[key]), ...extra].flatMap(compactWords).flatMap((word) => (
      make && word.length > make.length && word.startsWith(make) ? [word, word.slice(make.length)] : [word]
    )));
    const years = Array.isArray(record.years) && record.years.length ? record.years.map(Number) : expandYears(record.year || values.YEAR);
    record.searchIndex = {
      words, compacts, numericWords, years,
      code: normalizeSearchText(fields.CODE).replace(/\s+/g, ""),
      ruleId: normalizeSearchText(values["规则ID"]),
      text: normalizeSearchText(texts.join(" "))
    };
    return record.searchIndex;
  }

  function recordMatchesSearchToken(record, token, shapeLabels) {
    const index = recordSearchIndex(record, shapeLabels);
    if (/^\d+$/.test(token)) {
      if (token.length === 4 && index.years.includes(Number(token))) return true;
      if (token.length >= 4 && index.code.startsWith(token)) return true;
      // 整段数字：7 命中 7、7 Series、740i 的 740 不命中 7；不命中 700、75（7 后面紧跟数字的是另一个车型号）
      return index.numericWords.some((word) => word.startsWith(token) && !/\d/.test(word.charAt(token.length)));
    }
    if (CJK.test(token)) return index.text.includes(token);
    if (token.length >= RULE_ID_MIN_LENGTH && index.ruleId.startsWith(token)) return true;
    return index.words.some((word) => word.startsWith(token)) || index.compacts.some((compact) => compact.startsWith(token));
  }

  function cleanField(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function cleanText(element) {
    if (!element) {
      return "";
    }
    return element.textContent.replace(/\s+/g, " ").trim();
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  return {
    parseTsv,
    extractRecords,
    logoMake,
    sourceTags,
    pickupKey,
    nonPickupKey,
    sameText,
    recordKind,
    compareBedValues,
    firstNumber,
    compareValues,
    fieldAtoms,
    fieldAtomicValues,
    expandYearRangeAtoms,
    parseSizeViewYaml,
    parseYamlValue,
    mergeViewConfig,
    csvList,
    unique,
    uniqueInOrder,
    uniqueYears,
    expandYears,
    normalizeMake,
    searchTokens,
    normalizeSearchText,
    recordMatchesVehicleCode,
    recordSearchAtoms,
    searchQueryTokens,
    spanYears,
    compressedSourceRow,
    expandMatchShard,
    recordSearchIndex,
    recordMatchesSearchToken,
    cleanField,
    cleanText,
    escapeHtml
  };
});
