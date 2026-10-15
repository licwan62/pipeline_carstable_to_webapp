// 尺码配对页 SIZE 规则（viewer.js 的 SIZE 悬停与车型可视化规则叠加）：规则索引、店铺发货尺码换回匹配尺码、按 规则ID 精确查找、悬停 HTML。
// 数据来自 size-rules.json（A0 <国别>/尺码规则.json）与 store-groups.json（A0 US/店铺货架.json）。不依赖 DOM 与页面状态：
// 来源分组（sourceGroup）由页面注入，长度显示单位每次调用传入 format = { measurement(mm) → 字符串, unit }。
// 浏览器下挂到 window.SizeViewerRules（须在 viewer-data.js 之后、viewer.js 之前加载），Node 下 module.exports 供 node --test 使用。
// 2026-10-15 从 viewer.js 拆出，查找与 HTML 结果与拆分前逐项一致。
(function (root, factory) {
  const isNode = typeof module === "object" && module.exports;
  const api = factory(isNode ? require("./viewer-data.js") : root.SizeViewerData);
  if (isNode) module.exports = api;
  else root.SizeViewerRules = api;
})(typeof self !== "undefined" ? self : this, function ({ cleanField, escapeHtml }) {
  // 规则索引：国别 → 尺码 → 规则行、国别 → 规则ID → 规则行、国别 → 余量长容差、店铺 → 发货尺码 → [匹配尺码]
  function createRuleIndex({ sourceGroup }) {
    const sizeRuleIndexes = new Map();
    const sizeRuleTolerances = new Map();
    // 全量表 规则ID → 该国别规则表中的行（A0 规则表末列）；只在全量数据与规则来自同一 A0 版本时用于精确解释（版本由页面判断）
    const sizeRuleIdIndexes = new Map();
    const storeShippingSizes = new Map();

    function load(rules, groups) {
      sizeRuleIndexes.clear();
      sizeRuleTolerances.clear();
      storeShippingSizes.clear();
      sizeRuleIdIndexes.clear();
      Object.entries(rules?.regions || {}).forEach(([region, payload]) => {
        const keyField = (payload.headers || [])[0];
        const index = new Map();
        const byId = new Map();
        (payload.rows || []).forEach((row) => {
          const key = cleanField(row[keyField]).toUpperCase();
          if (key && !index.has(key)) index.set(key, row);
          const id = cleanField(row["规则ID"]);
          if (id && !byId.has(id)) byId.set(id, row);
        });
        sizeRuleIndexes.set(region.toUpperCase(), index);
        sizeRuleIdIndexes.set(region.toUpperCase(), byId);
        sizeRuleTolerances.set(region.toUpperCase(), payload.length_tolerance);
      });
      Object.entries(groups?.stores || {}).forEach(([store, rows]) => {
        const shipping = new Map();
        (rows || []).forEach((row) => {
          const shipSize = cleanField(row["发货尺码"]).toUpperCase();
          const matchSize = cleanField(row["匹配尺码"]);
          if (shipSize && matchSize) shipping.set(shipSize, [...(shipping.get(shipSize) || []), matchSize]);
        });
        storeShippingSizes.set(store.toUpperCase(), shipping);
      });
    }

    function scope(sourceName) {
      const store = cleanField(sourceName).toUpperCase();
      const isStore = storeShippingSizes.has(store);
      const group = cleanField(sourceGroup(sourceName)).toUpperCase();
      const region = sizeRuleIndexes.has(group) ? group : (isStore ? "US" : "");
      return { region, store: isStore ? store : "", index: sizeRuleIndexes.get(region) };
    }

    function ruleFor(value, sourceName) {
      const ruleScope = scope(sourceName);
      const key = cleanField(value).toUpperCase();
      if (!ruleScope.index || !key) return null;
      // 店铺列表的 SIZE 是发货尺码：多个匹配尺码可发同一个发货尺码，逐个列出对应规则
      const matchSizes = ruleScope.store ? (storeShippingSizes.get(ruleScope.store).get(key) || []) : [key];
      const rows = matchSizes.map((size) => ruleScope.index.get(cleanField(size).toUpperCase())).filter(Boolean);
      if (!rows.length) return null;
      return { ...ruleScope, size: cleanField(value), matchSizes, rows, tolerance: sizeRuleTolerances.get(ruleScope.region) };
    }

    // 记录的 规则ID（命中规则）；版本一致性由调用方先判断
    function exactForRecord(record, sourceName) {
      const ruleId = cleanField(record?.values?.["规则ID"]);
      if (!ruleId) return null;
      const ruleScope = scope(sourceName);
      const row = sizeRuleIdIndexes.get(ruleScope.region)?.get(ruleId);
      if (!row) return null;
      const matchSize = cleanField(record.values["匹配尺码"]) || (ruleScope.store ? "" : cleanField(record.values["SIZE"] || record.size));
      return { ruleId, row, region: ruleScope.region, store: ruleScope.store, matchSize, tolerance: sizeRuleTolerances.get(ruleScope.region) };
    }

    // SIZE 单元格悬停：带 规则ID 时只显示命中的那一条，查不到退回按尺码列出
    function exactFor(ruleId, sourceName, size, matchSize) {
      const ruleScope = scope(sourceName);
      const row = sizeRuleIdIndexes.get(ruleScope.region)?.get(cleanField(ruleId));
      if (!row) return ruleFor(size, sourceName);
      return { ...ruleScope, exact: true, ruleId: cleanField(ruleId), size: cleanField(size), matchSizes: [cleanField(matchSize) || cleanField(size)], rows: [row], tolerance: sizeRuleTolerances.get(ruleScope.region) };
    }

    return { load, scope, ruleFor, exactForRecord, exactFor };
  }

  function ruleMarkup(rule, format) {
    const sections = rule.rows.map((row, index) => {
      const matchSize = cleanField(rule.matchSizes[index]);
      const via = rule.store && (rule.exact || rule.rows.length > 1 || matchSize.toUpperCase() !== rule.size.toUpperCase())
        ? `<div class="size-reference-meta">匹配尺码 ${escapeHtml(matchSize)} → 发货 ${escapeHtml(rule.size)}</div>`
        : "";
      return `${via}${rule.region === "RU" ? ruMarkup(row, rule, format) : lengthMarkup(row, rule, format)}`;
    }).join('<hr class="size-reference-divider">');
    const scope = rule.store ? `${rule.region} · 店铺 ${rule.store}` : rule.region;
    const heading = rule.exact ? `命中规则 ${rule.ruleId}` : "尺码规则";
    return `
      <div class="size-reference-title">${escapeHtml(rule.size)}<small>${escapeHtml(scope)} ${escapeHtml(heading)}</small></div>
      ${sections}
    `;
  }

  // US/EU：车长 ≤ 长上限 且 长上限 − 车长 ≤ 余量长容差，适配车长即 [长上限 − 容差, 长上限]
  function lengthMarkup(row, rule, format) {
    const meta = rule.region === "EU"
      ? [cleanField(row["模式"]), cleanField(row["分类"]), cleanField(row["版本"]) && `版本 ${cleanField(row["版本"])}`]
      : [cleanField(row["分类"]), cleanField(row["尺码池"]) && `尺码池 ${cleanField(row["尺码池"])}`];
    const lengthMax = Number(cleanField(row["长上限"]) || NaN);
    const tolerance = Number(rule.tolerance ?? NaN);
    const hasRange = Number.isFinite(lengthMax) && Number.isFinite(tolerance) && tolerance > 0;
    const items = [
      ["适配车长", hasRange ? rangeDisplay(lengthMax - tolerance, lengthMax, format) : ""],
      ["长上限", Number.isFinite(lengthMax) ? dimensionDisplay(lengthMax, format) : ""],
      ["余量容差", hasRange ? `≤ ${dimensionDisplay(tolerance, format)}` : ""],
      ["插片指数", insertDisplay(row["插片指数上限"], row["插片指数下限"])],
      ["白名单", cleanField(row["车型白名单"])],
      ["备注", cleanField(row["备注"])]
    ];
    return `${metaMarkup(meta)}${itemsMarkup(items)}`;
  }

  // RU：车型长宽高均不超过规则长宽高，且 长_mm − 车长 ≤ 余量长上限_mm（缺省用报告的余量长容差）
  function ruMarkup(row, rule, format) {
    const meta = [
      cleanField(row["分类"]),
      cleanField(row["OZON尺码"]) && `OZON ${cleanField(row["OZON尺码"])}`,
      cleanField(row["发货尺码"]) && `发货 ${cleanField(row["发货尺码"])}`
    ];
    const lengthMax = Number(cleanField(row["长_mm"]) || NaN);
    const rowTolerance = Number(cleanField(row["余量长上限_mm"]) || NaN);
    const tolerance = Number.isFinite(rowTolerance) ? rowTolerance : Number(rule.tolerance ?? NaN);
    const hasRange = Number.isFinite(lengthMax) && Number.isFinite(tolerance) && tolerance > 0;
    const items = [
      ["适配车长", hasRange ? rangeDisplay(lengthMax - tolerance, lengthMax, format) : ""],
      ["余量容差", hasRange ? `≤ ${dimensionDisplay(tolerance, format)}` : ""]
    ];
    return `${metaMarkup(meta)}
      <div class="size-reference-dims">
        ${dimensionMarkup("长上限", row["长_mm"], format)}
        ${dimensionMarkup("宽上限", row["宽_mm"], format)}
        ${dimensionMarkup("高上限", row["高_mm"], format)}
      </div>
      ${itemsMarkup(items)}`;
  }

  function metaMarkup(parts) {
    const text = parts.filter(Boolean).join(" · ");
    return text ? `<div class="size-reference-common">${escapeHtml(text)}</div>` : "";
  }

  function itemsMarkup(items) {
    const visible = items.filter(([, value]) => value);
    return visible.length
      ? `<dl class="size-reference-rows">${visible.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>`
      : "";
  }

  function rangeDisplay(low, high, format) {
    return `${format.measurement(Math.max(0, low))} – ${format.measurement(high)} ${format.unit}`;
  }

  // 插片指数上限 999 表示不限
  function insertDisplay(upper, lower) {
    const max = Number(cleanField(upper) || NaN);
    const min = cleanField(lower);
    const parts = [];
    if (min) parts.push(`> ${min}`);
    if (Number.isFinite(max) && max < 999) parts.push(`≤ ${max}`);
    return parts.join("，");
  }

  function dimensionMarkup(label, value, format) {
    const display = dimensionDisplay(value, format);
    return `<span><em>${escapeHtml(label)}</em><strong>${escapeHtml(display || "-")}</strong></span>`;
  }

  function dimensionDisplay(value, format) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return cleanField(value);
    }
    return `${format.measurement(number)} ${format.unit}`;
  }

  return { createRuleIndex, ruleMarkup, insertDisplay, dimensionMarkup, dimensionDisplay };
});
