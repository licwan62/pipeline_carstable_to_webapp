// 尺码配对「车型尺寸演变」弹窗：长度区间阶梯主图 + 宽高联动小图 + SIZE 年份时间带。
// 只由 viewer.js 通过 window.SizeEvolution.open(...) 调用；数据计算在 size-evolution-data.js，ECharts 首次打开时懒加载。
(function () {
  "use strict";

  const D = window.SizeEvolutionData;
  if (!D) return;

  const DEFAULT_VISIBLE = 6;
  const MAX_PICKER_MODELS = 8;
  const LINE_COLORS = ["#1f6feb", "#d1495b", "#2a9d8f", "#e09f1f", "#7b5ea7", "#3d405b", "#e76f51", "#118ab2", "#8d6e63", "#43aa8b"];
  const LINE_DASHES = [null, [7, 4], [2, 3]];
  const PANEL_TITLES = { length: "长度", width: "宽度", height: "高度" };
  const PANEL_PROPS = { length: "lengthMm", width: "widthMm", height: "heightMm" };
  const UNITS = ["mm", "cm", "in"];
  const FILTER_LABELS = { model: "车型", version: "版本", type: "TYPE", seats: "座位", cab: "CAB", bed: "BED" };

  let echartsPromise = null;
  let overlay = null;
  let session = null;
  let openToken = 0;

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatCount(value) {
    return new Intl.NumberFormat("en-US").format(value);
  }

  function loadEcharts(src) {
    if (window.echarts) return Promise.resolve(window.echarts);
    if (!echartsPromise) {
      echartsPromise = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.async = true;
        script.dataset.sizeEvolutionVendor = "echarts";
        script.onload = () => (window.echarts ? resolve(window.echarts) : reject(new Error("ECharts 未正确加载")));
        script.onerror = () => {
          script.remove();
          reject(new Error(`无法加载图表组件：${src}`));
        };
        document.head.appendChild(script);
      }).catch((error) => {
        echartsPromise = null;  // 失败后允许重试
        throw error;
      });
    }
    return echartsPromise;
  }

  function colorFor(index) {
    return LINE_COLORS[index % LINE_COLORS.length];
  }

  function dashFor(index) {
    return LINE_DASHES[Math.floor(index / LINE_COLORS.length) % LINE_DASHES.length];
  }

  function swatch(index) {
    const dash = dashFor(index);
    return `<span class="evo-swatch${dash ? " is-dashed" : ""}" style="--evo-color:${colorFor(index)}" aria-hidden="true"></span>`;
  }

  // ---------- 弹窗外壳、焦点与生命周期 ----------

  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.className = "evo-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
      <section class="evo-dialog" role="dialog" aria-modal="true" aria-labelledby="evo-title" tabindex="-1">
        <header class="evo-header">
          <div class="evo-heading">
            <h3 id="evo-title">车型尺寸演变</h3>
            <p class="evo-subtitle" data-evo-subtitle></p>
          </div>
          <div class="evo-header-actions">
            <button type="button" class="evo-icon-button" data-evo-fullscreen aria-pressed="false" title="全屏">全屏</button>
            <button type="button" class="evo-icon-button evo-close" data-evo-close aria-label="关闭可视化">×</button>
          </div>
        </header>
        <div class="evo-body" data-evo-body></div>
      </section>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener("mousedown", (event) => {
      if (event.target === overlay) close();
    });
    overlay.querySelector("[data-evo-close]").addEventListener("click", close);
    overlay.querySelector("[data-evo-fullscreen]").addEventListener("click", () => {
      const dialog = overlay.querySelector(".evo-dialog");
      const next = !dialog.classList.contains("is-fullscreen");
      dialog.classList.toggle("is-fullscreen", next);
      const button = overlay.querySelector("[data-evo-fullscreen]");
      button.setAttribute("aria-pressed", next ? "true" : "false");
      button.textContent = next ? "退出全屏" : "全屏";
      if (session) session.fullscreen = next;
      scheduleResize();
    });
    return overlay;
  }

  function onDocumentKeydown(event) {
    if (!overlay || overlay.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(overlay.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'))
      .filter((element) => element.offsetParent !== null || element === document.activeElement);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!overlay.contains(document.activeElement)) {
      event.preventDefault();
      first.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function showOverlay(returnFocus) {
    ensureOverlay();
    overlay.hidden = false;
    document.body.classList.add("evo-scroll-lock");
    document.addEventListener("keydown", onDocumentKeydown, true);
    const dialog = overlay.querySelector(".evo-dialog");
    dialog.classList.remove("is-fullscreen");
    const fullscreenButton = overlay.querySelector("[data-evo-fullscreen]");
    fullscreenButton.setAttribute("aria-pressed", "false");
    fullscreenButton.textContent = "全屏";
    overlay.querySelector("[data-evo-close]").focus({ preventScroll: true });
    return returnFocus;
  }

  function disposeSession() {
    if (!session) return;
    if (session.resizeObserver) session.resizeObserver.disconnect();
    if (session.resizeTimer) window.clearTimeout(session.resizeTimer);
    if (session.chart) {
      session.chart.dispose();
      session.chart = null;
    }
    session = null;
  }

  function close() {
    openToken += 1;  // 迟到的异步响应不再渲染
    const returnFocus = session?.returnFocus || null;
    disposeSession();
    if (overlay) {
      overlay.hidden = true;
      overlay.querySelector("[data-evo-body]").innerHTML = "";
      overlay.querySelector(".evo-dialog").classList.remove("is-fullscreen");
    }
    document.body.classList.remove("evo-scroll-lock");
    document.removeEventListener("keydown", onDocumentKeydown, true);
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
  }

  function isOpen() {
    return Boolean(overlay && !overlay.hidden);
  }

  function setSubtitle(text) {
    overlay.querySelector("[data-evo-subtitle]").textContent = text || "";
  }

  function body() {
    return overlay.querySelector("[data-evo-body]");
  }

  // ---------- 车型选择器 ----------

  function openModelPicker(options) {
    const token = ++openToken;
    disposeSession();
    showOverlay();
    session = { token, returnFocus: options.returnFocus || null };
    overlay.querySelector("#evo-title").textContent = "选择要可视化的车型";
    setSubtitle(`${options.sourceLabel || options.source} · ${options.kind === "pick" ? "皮卡" : "非皮卡"} · 来自全部 ${formatCount(options.matchCount || 0)} 条匹配结果，共 ${formatCount(options.models.length)} 个车型`);
    const chosen = new Set();
    body().innerHTML = `
      <div class="evo-picker">
        <div class="evo-picker-tools">
          <input type="search" class="evo-search" data-picker-search placeholder="搜索 MAKE / MODEL" aria-label="搜索车型" autocomplete="off">
          <span class="evo-picker-count" data-picker-count role="status"></span>
          <button type="button" class="evo-primary" data-picker-confirm disabled>可视化所选</button>
        </div>
        <p class="evo-hint">可多选对比（最多 ${MAX_PICKER_MODELS} 个车型）；点「查看」直接打开单个车型的完整历史。</p>
        <ul class="evo-picker-list" data-picker-list>
          ${options.models.map((model, index) => `
            <li data-picker-row data-text="${escapeHtml(`${model.make} ${model.model}`.toLowerCase())}">
              <label><input type="checkbox" data-picker-index="${index}"><span><strong>${escapeHtml(model.make)}</strong> ${escapeHtml(model.model)}</span><em>${formatCount(model.count)} 条</em></label>
              <button type="button" class="evo-link" data-picker-open="${index}">查看</button>
            </li>
          `).join("")}
        </ul>
      </div>
    `;
    const confirm = body().querySelector("[data-picker-confirm]");
    const count = body().querySelector("[data-picker-count]");
    const refresh = () => {
      confirm.disabled = !chosen.size;
      confirm.textContent = chosen.size ? `可视化所选（${chosen.size}）` : "可视化所选";
      count.textContent = chosen.size >= MAX_PICKER_MODELS ? `已达上限 ${MAX_PICKER_MODELS} 个` : "";
      body().querySelectorAll("[data-picker-index]").forEach((input) => {
        input.disabled = !input.checked && chosen.size >= MAX_PICKER_MODELS;
      });
    };
    body().querySelectorAll("[data-picker-index]").forEach((input) => {
      input.addEventListener("change", () => {
        const model = options.models[Number(input.dataset.pickerIndex)];
        if (input.checked) chosen.add(model.key);
        else chosen.delete(model.key);
        refresh();
      });
    });
    body().querySelectorAll("[data-picker-open]").forEach((button) => {
      button.addEventListener("click", () => {
        if (token !== openToken) return;
        options.onConfirm([options.models[Number(button.dataset.pickerOpen)].key]);
      });
    });
    confirm.addEventListener("click", () => {
      if (token !== openToken || !chosen.size) return;
      options.onConfirm(Array.from(chosen));
    });
    const search = body().querySelector("[data-picker-search]");
    search.addEventListener("input", () => {
      const query = search.value.trim().toLowerCase();
      body().querySelectorAll("[data-picker-row]").forEach((row) => {
        row.hidden = Boolean(query) && !row.dataset.text.includes(query);
      });
    });
    refresh();
    search.focus({ preventScroll: true });
  }

  // ---------- 打开可视化 ----------

  async function open(options) {
    const token = ++openToken;
    const returnFocus = session?.returnFocus || options.returnFocus || null;
    disposeSession();
    showOverlay();
    session = { token, returnFocus, options, chart: null };
    overlay.querySelector("#evo-title").textContent = "车型尺寸演变";
    setSubtitle(`${options.sourceLabel || options.source} · ${options.kind === "pick" ? "皮卡" : "非皮卡"}`);
    body().innerHTML = `<div class="evo-status" role="status"><span class="evo-spinner" aria-hidden="true"></span>正在加载车型历史与图表组件…</div>`;
    try {
      const [, history] = await Promise.all([loadEcharts(options.echartsSrc), options.loadModelHistory(options.modelKeys)]);
      if (token !== openToken) return;
      initialiseSession(history);
      renderSession();
      loadSales();
    } catch (error) {
      if (token !== openToken) return;
      body().innerHTML = `
        <div class="evo-status is-error" role="alert">
          <p>可视化加载失败：${escapeHtml(error?.message || error)}</p>
          <p class="evo-hint">原检索表不受影响，可关闭弹窗继续使用，或重试。</p>
          <button type="button" class="evo-primary" data-evo-retry>重试</button>
        </div>
      `;
      body().querySelector("[data-evo-retry]").addEventListener("click", () => open({ ...options, returnFocus }));
      body().querySelector("[data-evo-retry]").focus({ preventScroll: true });
    }
  }

  function initialiseSession(history) {
    const options = session.options;
    if (history.origin) options.origin = history.origin;
    const hits = new Set(options.currentMatchRecordKeys || []);
    const anchors = new Set(options.anchorRecordKeys || []);
    const normalized = D.dedupeRecords((history.records || []).map((record) => D.normalizeRecord(record, {
      source: options.source, sourceLabel: options.sourceLabel, group: history.group
    })));
    normalized.forEach((record) => {
      record.isHit = hits.has(record.recordKey) || record.rawRefs.some((ref) => hits.has(ref.recordKey));
      record.isAnchor = anchors.has(record.recordKey);
      // 命中规则：viewer 按 规则ID 在同版本规则表中查找；版本不一致或找不到时为 null，不叠加
      record.rule = record.ruleId && options.lookupRule ? D.ruleOverlay(options.lookupRule(record.rawRefs[0])) : null;
    });
    const ruleResolved = normalized.filter((record) => record.rule).length;
    const ruleUnresolved = normalized.filter((record) => record.ruleId && !record.rule).length;
    const allConfigurations = D.buildConfigurations(normalized, {
      selectedConfigurationKeys: options.selectedConfigurationKeys, anchorRecordKeys: options.anchorRecordKeys
    });
    const colorIndex = new Map(allConfigurations.map((item) => [item.key, item.colorIndex]));
    const years = normalized.flatMap((record) => record.intervals.flatMap((item) => [item.startYear, item.endYear]));
    const modelCount = new Set(normalized.map((record) => record.modelKey)).size;
    const filters = initialFilters(options.initialFilters || {}, allConfigurations);
    const initiallyFiltered = allConfigurations.filter((item) => D.configurationMatchesFilters(item, filters));
    Object.assign(session, {
      records: normalized,
      rawCount: (history.records || []).length,
      colorIndex,
      modelCount,
      extent: years.length ? [Math.min(...years), Math.max(...years)] : null,
      scope: "full",
      unit: UNITS.includes(options.unit) ? options.unit : "mm",
      showWidthHeight: false,
      showSales: true,
      metric: "potential",
      salesState: "loading",
      sales: null,
      showSizeBand: true,
      filters,
      visibleKeys: new Set(D.defaultVisibleConfigurations(initiallyFiltered.length ? initiallyFiltered : allConfigurations, DEFAULT_VISIBLE)),
      legendQuery: "",
      zoom: null,
      locked: null,
      hoverYear: null,
      ruleResolved,
      ruleUnresolved,
      showRules: ruleResolved > 0,
      hitTotal: normalized.filter((record) => record.isHit).length
    });
  }

  // 页面上已选的 TYPE/CAB/BED 作为初始配置筛选；不在本车型中出现的值忽略
  function initialFilters(initial, configurations) {
    const filters = {};
    D.FILTER_FIELDS.forEach((name) => {
      const wanted = (initial[name] || []).map(String);
      const present = new Set(configurations.map((item) => D.filterValueOf(item, name)));
      filters[name] = wanted.filter((value) => present.has(value));
    });
    return filters;
  }

  function scopeRecords() {
    return session.scope === "filtered" ? session.records.filter((record) => record.isHit) : session.records;
  }

  function computeView() {
    const records = scopeRecords();
    const configurations = D.buildConfigurations(records, {
      selectedConfigurationKeys: session.options.selectedConfigurationKeys, anchorRecordKeys: session.options.anchorRecordKeys
    });
    configurations.forEach((item) => { item.colorIndex = session.colorIndex.get(item.key) ?? item.colorIndex; });
    const filtered = configurations.filter((item) => D.configurationMatchesFilters(item, session.filters));
    const visible = filtered.filter((item) => session.visibleKeys.has(item.key));
    return { records, configurations, filtered, visible };
  }

  function releaseChart() {
    if (session.resizeObserver) session.resizeObserver.disconnect();
    session.resizeObserver = null;
    if (session.resizeTimer) window.clearTimeout(session.resizeTimer);
    if (session.chart) session.chart.dispose();
    session.chart = null;
    session.layout = null;
  }

  function renderSession() {
    releaseChart();  // 重建弹窗内容前释放旧实例，避免实例与监听累积
    const view = computeView();
    session.view = view;
    const options = session.options;
    const meaning = D.sizeMeaningOf(options.source);
    const isPick = options.kind === "pick";
    const models = Array.from(new Set(session.records.map((record) => `${record.make} ${record.model}`)));
    overlay.querySelector("#evo-title").textContent = models.length === 1 ? `${models[0]} · 尺寸演变` : `${models.length} 个车型对比 · 尺寸演变`;
    setSubtitle(`${options.sourceLabel || options.source} · ${isPick ? "皮卡" : "非皮卡"} · ${D.sizeHeading(meaning)}${meaning === "shipping" ? "（店铺发货结果）" : "（国别匹配结果）"}`);
    body().innerHTML = `
      <div class="evo-layout">
        <div class="evo-toolbar" role="toolbar" aria-label="可视化工具栏">
          <fieldset class="evo-segmented" aria-label="数据范围">
            <legend class="evo-sr-only">数据范围</legend>
            ${[["full", "完整车型历史"], ["filtered", "仅当前筛选"]].map(([value, label]) => `
              <label class="${session.scope === value ? "is-active" : ""}"><input type="radio" name="evo-scope" value="${value}" ${session.scope === value ? "checked" : ""}>${label}</label>
            `).join("")}
          </fieldset>
          <div class="evo-segmented evo-units" role="group" aria-label="单位">
            ${UNITS.map((unit) => `<button type="button" data-evo-unit="${unit}" class="${session.unit === unit ? "is-active" : ""}" aria-pressed="${session.unit === unit}">${unit.toUpperCase()}</button>`).join("")}
          </div>
          <div class="evo-year-window" role="group" aria-label="年份窗口">
            <span>年份</span>
            <input type="number" data-evo-year="from" aria-label="起始年份" step="1">
            <span aria-hidden="true">–</span>
            <input type="number" data-evo-year="to" aria-label="结束年份" step="1">
            <button type="button" class="evo-link" data-evo-year-reset>全部</button>
          </div>
          <button type="button" class="evo-toggle" data-evo-toggle="wh" aria-pressed="${session.showWidthHeight}">${session.showWidthHeight ? "收起宽高" : "展开宽高"}</button>
          <button type="button" class="evo-toggle" data-evo-toggle="sales" aria-pressed="${session.showSales}">${session.showSales ? "收起柱状图" : "展开柱状图"}</button>
          <div class="evo-segmented" role="group" aria-label="柱状图指标">
            ${[["potential", "市场潜力"], ["sales", "年度销量"]].map(([key, label]) => `<button type="button" data-evo-metric="${key}" class="${session.metric === key ? "is-active" : ""}" aria-pressed="${session.metric === key}">${label}</button>`).join("")}
          </div>
          <button type="button" class="evo-toggle" data-evo-toggle="size" aria-pressed="${session.showSizeBand}">SIZE 时间带</button>
          <button type="button" class="evo-toggle" data-evo-toggle="rules" aria-pressed="${session.showRules}" ${session.ruleResolved ? "" : "disabled"} title="${session.ruleResolved ? "叠加命中规则的长度条件与长上限（RU 另有宽/高上限）" : "没有可按同版本规则表解析的规则ID，无法叠加规则"}">规则叠加</button>
        </div>
        <div class="evo-meta" data-evo-meta>${metaMarkup(view)}</div>
        <div class="evo-main">
          <div class="evo-top-filters" aria-label="配置筛选">${filtersMarkup(view, isPick)}</div>
          <div class="evo-chart-column">
            <div class="evo-sales-status" data-evo-sales-status></div>
            <div class="evo-chart-wrap" data-evo-chart-wrap>
              <div class="evo-chart" data-evo-chart role="img" aria-label="车型年份尺寸演变图，详细数据见下方文字详情"></div>
              <div class="evo-tooltip" data-evo-tooltip hidden></div>
              <div class="evo-empty" data-evo-empty hidden></div>
            </div>
            <details class="evo-legend-panel" open><summary>配置图例（可折叠）</summary><div class="evo-legend" data-evo-legend>${legendMarkup(view)}</div></details>
            <div class="evo-detail" data-evo-detail aria-live="polite">${detailMarkup()}</div>
            <div data-evo-sales-details></div>
            ${textDetailsMarkup(view)}
          </div>
        </div>
      </div>
    `;
    bindSession();
    mountChart();
    refreshSales();
  }

  function metaMarkup(view) {
    const options = session.options;
    const origin = options.origin || {};
    const dataVersion = origin.data?.a0_version || origin.data?.version || "未知";
    const versions = [["数据", origin.data?.a0_version || origin.data?.version], ["规则", origin.rules?.version], ["货架", origin.stores?.version]];
    const known = versions.filter(([, value]) => value);
    const mismatch = new Set(known.map(([, value]) => value)).size > 1;
    const counts = D.issueSummary(view.records);
    const overlapConfigs = view.configurations.filter((item) => item.overlapYears.length).length;
    const merged = view.records.reduce((total, record) => total + record.rawRefs.length - 1, 0);
    const notes = [
      overlapConfigs && `同年重叠/分支 ${overlapConfigs} 个配置`,
      counts.yearInvalid && `年份无法解析 ${counts.yearInvalid} 条（未绘制）`,
      counts.yearFromArray && `年份按 years 数组绘制 ${counts.yearFromArray} 条`,
      counts.dimensionMissing && `缺失尺寸 ${counts.dimensionMissing} 条`,
      counts.unmatched && `无可用尺码 ${counts.unmatched} 条`,
      counts.incomplete && `数据不全 ${counts.incomplete} 条`,
      counts.sizeMissing && `SIZE 缺失 ${counts.sizeMissing} 条`,
      counts.idConflict && `同 ID 内容冲突 ${counts.idConflict} 条`,
      counts.seatsConflict && `座位标记矛盾 ${counts.seatsConflict} 条（记为未知）`,
      merged && `精确重复已合并 ${merged} 条`
    ].filter(Boolean);
    const hitText = session.scope === "full"
      ? (session.hitTotal && session.hitTotal < session.records.length
        ? `完整历史 ${formatCount(view.records.length)} 条，其中 ${formatCount(session.hitTotal)} 条命中当前筛选（加粗显示）`
        : `完整历史 ${formatCount(view.records.length)} 条${session.hitTotal ? "，全部在当前筛选内" : "，均不在当前筛选内"}`)
      : `当前筛选内 ${formatCount(view.records.length)} 条（打开时的筛选快照）`;
    return `
      <div class="evo-meta-line">
        <span>来源 <strong>${escapeHtml(options.sourceLabel || options.source)}</strong></span>
        <span>${known.map(([label, value]) => `${label} ${escapeHtml(value)}`).join(" · ") || `数据 ${escapeHtml(dataVersion)}`}</span>
        <span>${escapeHtml(hitText)}</span>
      </div>
      ${mismatch ? `<div class="evo-notice is-warning" role="note">数据、规则、货架来自不同 A0 发布版本：图中只显示该版本数据自身的 SIZE 与余量，不叠加任何规则解释。</div>` : ""}
      ${D.sizeMeaningOf(options.source) === "shipping" ? `<div class="evo-notice" role="note">${view.records.some((record) => record.matchedSize)
        ? "店铺来源的 SIZE 是发货尺码；详情中的匹配尺码与命中规则取自 A0 店铺表换码前的记录。"
        : "店铺来源的 SIZE 是发货尺码；换码前的实际匹配尺码与命中规则未记录，图中不推断唯一匹配尺码。"}</div>` : ""}
      ${session.ruleResolved ? `<div class="evo-notice" role="note">规则叠加：灰色带为命中规则的<strong>长度条件</strong> [长上限 − 余量长容差, 长上限]，灰色虚线为长上限（标注尺码）${session.records.some((record) => record.rule?.widthMax) ? "，宽/高图虚线为该规则的宽/高上限" : ""}。分类、尺码池、版本、插片指数、白名单等条件只在详情中说明，不据此判断适配。</div>` : ""}
      ${session.ruleUnresolved ? `<div class="evo-notice is-warning" role="note">${session.ruleUnresolved} 条记录的规则ID 未能在同版本规则表中找到（数据与规则版本不一致或规则表缺少规则ID），这些记录不叠加规则。</div>` : ""}
      ${notes.length ? `<div class="evo-issue-list">${notes.map((note) => `<span class="evo-issue">${escapeHtml(note)}</span>`).join("")}</div>` : ""}
    `;
  }

  function filterOptionLabel(name, value, configuration) {
    if (name === "model") return `${configuration.make} ${configuration.model}`;
    if (!value) return D.EMPTY_LABELS[name] || "未注明";
    return name === "seats" ? `${value} 座` : value;
  }

  function filtersMarkup(view, isPick) {
    const fields = D.FILTER_FIELDS.filter((name) => (name === "cab" || name === "bed" ? isPick : true) && (name !== "model" || session.modelCount > 1));
    return `
      <div class="evo-filters" data-evo-filters>
        <div class="evo-side-title">配置筛选</div>
        ${fields.map((name) => {
          const values = new Map();
          view.configurations.forEach((item) => {
            const value = D.filterValueOf(item, name);
            if (!values.has(value)) values.set(value, { value, label: filterOptionLabel(name, value, item), count: 0 });
            values.get(value).count += 1;
          });
          const selected = session.filters[name] || [];
          const optionsList = Array.from(values.values()).sort((a, b) => (a.value === "") - (b.value === "") || a.label.localeCompare(b.label, "en", { numeric: true }));
          if (optionsList.length <= 1 && !selected.length) return "";
          return `
            <div class="evo-filter-group" role="group" aria-label="${FILTER_LABELS[name]}">
              <span class="evo-filter-name">${FILTER_LABELS[name]}</span>
              <div class="evo-chips">
                ${optionsList.map((option) => `
                  <button type="button" class="evo-chip${selected.includes(option.value) ? " is-active" : ""}" data-evo-filter="${name}" data-value="${escapeHtml(option.value)}" aria-pressed="${selected.includes(option.value)}">${escapeHtml(option.label)}<em>${option.count}</em></button>
                `).join("")}
              </div>
            </div>
          `;
        }).join("")}
      </div>
    `;
  }

  function legendMarkup(view) {
    const query = session.legendQuery.trim().toLowerCase();
    const shown = view.filtered.filter((item) => !query || item.label.toLowerCase().includes(query));
    const total = view.filtered.length;
    const visibleCount = view.visible.length;
    return `
      <div class="evo-side-title">图例 <span class="evo-legend-count" role="status">已显示 ${visibleCount} / ${total} 个配置</span></div>
      ${total > visibleCount ? `<p class="evo-hint">还有 ${total - visibleCount} 个配置未显示，可勾选加入（默认只显示 ${DEFAULT_VISIBLE} 个，已选配置优先）。</p>` : ""}
      <div class="evo-legend-tools">
        <input type="search" class="evo-search" data-evo-legend-search value="${escapeHtml(session.legendQuery)}" placeholder="搜索配置" aria-label="搜索配置" autocomplete="off">
        <button type="button" class="evo-link" data-evo-legend-all>全选</button>
        <button type="button" class="evo-link" data-evo-legend-none>取消</button>
      </div>
      <ul class="evo-legend-list">
        ${shown.map((item) => `
          <li class="${session.visibleKeys.has(item.key) ? "is-visible" : ""}">
            <label>
              <input type="checkbox" data-evo-legend-key="${escapeHtml(item.key)}" ${session.visibleKeys.has(item.key) ? "checked" : ""}>
              ${swatch(item.colorIndex)}
              <span class="evo-legend-label">${escapeHtml(item.shortLabel)}${item.hasAnchor ? '<b class="evo-tag">锚点</b>' : ""}${item.overlapYears.length ? '<b class="evo-tag is-warn">同年分支</b>' : ""}</span>
              <em>${item.records.length}</em>
            </label>
            <button type="button" class="evo-link" data-evo-legend-only="${escapeHtml(item.key)}" aria-label="仅显示 ${escapeHtml(item.shortLabel)}">仅此项</button>
          </li>
        `).join("") || '<li class="evo-hint">没有符合筛选的配置</li>'}
      </ul>
    `;
  }

  // ---------- 详情 ----------

  function measure(mm) {
    return D.formatMeasure(mm, session.unit);
  }

  function statusMarkup(record) {
    const parts = [];
    if (record.matchStatus !== "matched") {
      parts.push(`<b class="evo-status-tag is-${record.matchStatus}">${escapeHtml(D.matchStatusLabel(record.matchStatus, record.sizeMeaning))}</b>`);
      if (record.candidate) parts.push(`候选 ${escapeHtml(record.candidate)}`);
      if (record.reason) parts.push(`原因 ${escapeHtml(record.reason)}`);
      if (record.difference !== null) parts.push(`相差 ${escapeHtml(measure(record.difference))}`);
    }
    return parts.join(" · ");
  }

  function sizeTextMarkup(record) {
    const heading = D.sizeHeading(record.sizeMeaning);
    const size = record.sizeValue || "—";
    const extra = [];
    if (record.sizeMeaning === "shipping" && record.matchStatus === "matched") extra.push(record.matchedSize ? `匹配尺码 ${escapeHtml(record.matchedSize)} → 发货` : "匹配尺码未记录");
    if (record.ozonSize) extra.push(`OZON尺码 ${escapeHtml(record.ozonSize)}`);
    if (record.shippingSize) extra.push(`发货尺码 ${escapeHtml(record.shippingSize)}`);
    return `${heading} <strong>${escapeHtml(size)}</strong>${extra.length ? `（${extra.join(" · ")}）` : ""}`;
  }

  function ruleMarkup(record, { full }) {
    const rule = record.rule;
    if (!rule) {
      return record.ruleId ? `<span class="evo-rule">规则 <code>${escapeHtml(record.ruleId)}</code>（同版本规则表中未找到）</span>` : "";
    }
    const parts = [`规则 <code>${escapeHtml(rule.ruleId)}</code>`];
    if (rule.lengthMax !== null) parts.push(`长上限 ${escapeHtml(measure(rule.lengthMax))}`);
    if (rule.fitLow !== null) parts.push(`长度条件 ${escapeHtml(D.formatMeasure(rule.fitLow, session.unit, { withUnit: false }))}–${escapeHtml(measure(rule.lengthMax))}`);
    if (rule.widthMax !== null) parts.push(`宽上限 ${escapeHtml(measure(rule.widthMax))}`);
    if (rule.heightMax !== null) parts.push(`高上限 ${escapeHtml(measure(rule.heightMax))}`);
    if (full && rule.tolerance !== null) parts.push(`余量容差 ≤ ${escapeHtml(measure(rule.tolerance))}`);
    if (full && rule.conditions.length) parts.push(escapeHtml(rule.conditions.join(" · ")));
    return `<span class="evo-rule">${parts.join(" · ")}</span>`;
  }

  function recordLineMarkup(record, { actions = false } = {}) {
    const status = statusMarkup(record);
    return `
      <div class="evo-record${record.isHit && session.scope === "full" ? " is-hit" : ""}">
        <div class="evo-record-main">
          <span>YEAR <strong>${escapeHtml(record.yearText || "—")}</strong>${record.intervals.length > 1 ? `（${escapeHtml(D.formatIntervals(record.intervals))}）` : ""}</span>
          ${record.generation ? `<span>代际 ${escapeHtml(record.generation)}</span>` : ""}
          <span>长 ${escapeHtml(measure(record.lengthMm))} · 宽 ${escapeHtml(measure(record.widthMm))} · 高 ${escapeHtml(measure(record.heightMm))}</span>
          <span>${sizeTextMarkup(record)}</span>
          <span>市场潜力 ${potentialNumber(record.marketPotential)} · 基础 ${potentialNumber(record.marketPotential === null || record.potentialAdjustment === null ? null : Math.max(0, record.marketPotential - record.potentialAdjustment))} · 销量潜力调整 ${potentialNumber(record.potentialAdjustment)}</span>
          <span>长度余量 ${escapeHtml(record.lengthMarginMm === null ? "—" : measure(record.lengthMarginMm))}</span>
          ${record.shape ? `<span>SHAPE ${escapeHtml(record.shape)}</span>` : ""}
          ${ruleMarkup(record, { full: actions })}
          ${status ? `<span>${status}</span>` : ""}
          ${record.isHit && session.scope === "full" && session.hitTotal < session.records.length ? '<span class="evo-hit-mark">命中当前筛选</span>' : ""}
          ${record.idConflict ? '<span class="evo-status-tag is-unmatched">同 ID 内容冲突</span>' : ""}
          ${record.rawRefs.length > 1 ? `<span>精确重复 ${record.rawRefs.length} 条已合并</span>` : ""}
        </div>
        ${actions ? `
          <div class="evo-record-id">
            <code>${escapeHtml(record.dimensionId || "（无 DIMENSION-ID）")}</code>
            <span>${escapeHtml(record.sourceLabel)}</span>
            ${record.isHit
              ? `<button type="button" class="evo-primary is-small" data-evo-locate="${escapeHtml(record.recordKey)}">定位原记录</button>`
              : `<button type="button" class="evo-secondary is-small" data-evo-locate-model="${escapeHtml(record.recordKey)}" title="该记录不在当前检索结果中：将切换到该车型范围（清除当前筛选）后定位">查看该车型记录</button>`}
          </div>
        ` : ""}
      </div>
    `;
  }

  function recordsCoveringYear(year) {
    const view = session.view;
    return view.visible.map((configuration) => ({
      configuration,
      records: configuration.records.filter((record) => D.coversYear(record.intervals, year))
    })).filter((entry) => entry.records.length);
  }

  function yearSummaryMarkup(year, { actions = false } = {}) {
    const entries = recordsCoveringYear(year);
    if (!entries.length) return `<div class="evo-detail-title">${year} 年 · 可见配置均无记录</div>`;
    return `
      <div class="evo-detail-title">${year} 年 · ${entries.length} 个配置 · ${entries.reduce((total, entry) => total + entry.records.length, 0)} 条记录</div>
      ${salesYearMarkup(year, { showAtomIds: !actions })}
      ${entries.map((entry) => `
        <div class="evo-detail-config">
          <div class="evo-detail-config-name">${swatch(entry.configuration.colorIndex)}${escapeHtml(entry.configuration.label)}${entry.records.length > 1 ? `<b class="evo-tag is-warn">同年 ${entry.records.length} 条</b>` : ""}</div>
          ${entry.records.map((record) => recordLineMarkup(record, { actions })).join("")}
        </div>
      `).join("")}
    `;
  }

  function detailMarkup() {
    const locked = session.locked;
    if (!locked) {
      return `<p class="evo-hint">悬停查看某一年覆盖的全部可见配置；点击区间锁定详情（含 DIMENSION-ID 与定位原记录），点击空白处锁定该年份。</p>`;
    }
    const close = `<button type="button" class="evo-link" data-evo-unlock>取消锁定</button>`;
    if (locked.type === "year") {
      return `<div class="evo-detail-head"><span>已锁定年份</span>${close}</div>${yearSummaryMarkup(locked.year, { actions: true })}`;
    }
    const record = session.records.find((item) => item.recordKey === locked.recordKey);
    if (!record) return `<p class="evo-hint">锁定的记录不在当前范围内。</p>`;
    const configuration = session.view.configurations.find((item) => item.key === record.configurationKey);
    const siblings = configuration
      ? configuration.records.filter((item) => item !== record && D.intervalsOverlap(item.intervals, record.intervals))
      : [];
    return `
      <div class="evo-detail-head"><span>已锁定记录</span>${close}</div>
      <div class="evo-detail-config">
        <div class="evo-detail-config-name">${swatch(session.colorIndex.get(record.configurationKey) || 0)}${escapeHtml(D.configurationLabel(record))}</div>
        ${recordLineMarkup(record, { actions: true })}
      </div>
      ${siblings.length ? `
        <div class="evo-detail-config">
          <div class="evo-detail-config-name">同配置同年的其他原记录（${siblings.length}）</div>
          ${siblings.map((item) => recordLineMarkup(item, { actions: true })).join("")}
        </div>
      ` : ""}
    `;
  }

  function textDetailsMarkup(view) {
    const rows = view.visible.flatMap((configuration) => configuration.records
      .slice()
      .sort((a, b) => (a.intervals[0]?.startYear ?? 0) - (b.intervals[0]?.startYear ?? 0))
      .map((record) => ({ configuration, record })));
    const meaning = D.sizeMeaningOf(session.options.source);
    return `
      <details class="evo-text-details">
        <summary>文字详情（可见 ${view.visible.length} 个配置 · ${rows.length} 条记录）</summary>
        <div class="evo-table-wrap">
          <table class="evo-table">
            <thead><tr><th>配置</th><th>YEAR</th><th>代际</th><th>SHAPE</th><th>长</th><th>宽</th><th>高</th><th>${D.sizeHeading(meaning)}</th>${meaning === "shipping" ? "<th>匹配尺码</th>" : ""}<th>长度余量</th><th>规则ID</th><th>长度条件</th><th>状态</th><th>DIMENSION-ID</th><th></th></tr></thead>
            <tbody>
              ${rows.map(({ configuration, record }) => `
                <tr class="${record.isHit && session.scope === "full" ? "is-hit" : ""}">
                  <td>${swatch(configuration.colorIndex)}${escapeHtml(configuration.shortLabel)}</td>
                  <td>${escapeHtml(record.yearText || "—")}${record.intervals.length ? "" : " ⚠"}</td>
                  <td>${escapeHtml(record.generation || "")}</td>
                  <td>${escapeHtml(record.shape || "")}</td>
                  <td>${escapeHtml(measure(record.lengthMm))}</td>
                  <td>${escapeHtml(measure(record.widthMm))}</td>
                  <td>${escapeHtml(measure(record.heightMm))}</td>
                  <td>${escapeHtml(record.sizeValue || "—")}</td>
                  ${meaning === "shipping" ? `<td>${escapeHtml(record.matchedSize || "未记录")}</td>` : ""}
                  <td>${escapeHtml(record.lengthMarginMm === null ? "—" : measure(record.lengthMarginMm))}</td>
                  <td>${record.ruleId ? `<code>${escapeHtml(record.ruleId)}</code>` : ""}</td>
                  <td>${record.rule && record.rule.fitLow !== null ? escapeHtml(`${D.formatMeasure(record.rule.fitLow, session.unit, { withUnit: false })}–${measure(record.rule.lengthMax)}`) : ""}</td>
                  <td>${statusMarkup(record) || escapeHtml(D.matchStatusLabel(record.matchStatus, record.sizeMeaning))}</td>
                  <td><code>${escapeHtml(record.dimensionId || "")}</code></td>
                  <td>${record.isHit
                    ? `<button type="button" class="evo-link" data-evo-locate="${escapeHtml(record.recordKey)}">定位</button>`
                    : `<button type="button" class="evo-link" data-evo-locate-model="${escapeHtml(record.recordKey)}">查看该车型记录</button>`}</td>
                </tr>
              `).join("") || '<tr><td colspan="15">没有可见记录</td></tr>'}
            </tbody>
          </table>
        </div>
      </details>
    `;
  }

  // ---------- 事件 ----------

  function bindSession() {
    const root = body();
    root.querySelectorAll('input[name="evo-scope"]').forEach((input) => {
      input.addEventListener("change", () => {
        session.scope = input.value === "filtered" ? "filtered" : "full";
        session.locked = null;
        renderSession();
        root.ownerDocument.querySelector(`input[name="evo-scope"][value="${session.scope}"]`)?.focus({ preventScroll: true });
      });
    });
    root.querySelectorAll("[data-evo-unit]").forEach((button) => {
      button.addEventListener("click", () => {
        session.unit = button.dataset.evoUnit;
        rerenderKeepingFocus(`[data-evo-unit="${session.unit}"]`);
      });
    });
    root.querySelectorAll("[data-evo-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.evoToggle === "wh") session.showWidthHeight = !session.showWidthHeight;
        else if (button.dataset.evoToggle === "sales") session.showSales = !session.showSales;
        else if (button.dataset.evoToggle === "rules") session.showRules = !session.showRules;
        else session.showSizeBand = !session.showSizeBand;
        rerenderKeepingFocus(`[data-evo-toggle="${button.dataset.evoToggle}"]`);
      });
    });
    root.querySelectorAll("[data-evo-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        const name = button.dataset.evoFilter;
        const value = button.dataset.value;
        const current = new Set(session.filters[name] || []);
        if (current.has(value)) current.delete(value);
        else current.add(value);
        session.filters[name] = Array.from(current);
        ensureSomeVisible();
        rerenderKeepingFocus(`[data-evo-filter="${name}"][data-value="${cssEscape(value)}"]`);
      });
    });
    root.querySelectorAll("[data-evo-metric]").forEach((button) => button.addEventListener("click", () => {
      session.metric = button.dataset.evoMetric;
      rerenderKeepingFocus(`[data-evo-metric="${session.metric}"]`);
    }));
    bindLegend();
    bindDetailActions(root);
    root.querySelectorAll("[data-evo-year]").forEach((input) => {
      input.addEventListener("change", applyYearInputs);
      input.addEventListener("keydown", (event) => { if (event.key === "Enter") applyYearInputs(); });
    });
    root.querySelector("[data-evo-year-reset]")?.addEventListener("click", () => {
      session.zoom = null;
      if (session.chart) session.chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
      syncYearInputs();
    });
  }

  function bindLegend() {
    const legend = body().querySelector("[data-evo-legend]");
    if (!legend) return;
    legend.querySelectorAll("[data-evo-legend-key]").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) session.visibleKeys.add(input.dataset.evoLegendKey);
        else session.visibleKeys.delete(input.dataset.evoLegendKey);
        refreshAfterLegend(`[data-evo-legend-key="${cssEscape(input.dataset.evoLegendKey)}"]`);
      });
    });
    legend.querySelectorAll("[data-evo-legend-only]").forEach((button) => {
      button.addEventListener("click", () => {
        session.visibleKeys = new Set([button.dataset.evoLegendOnly]);
        refreshAfterLegend(`[data-evo-legend-only="${cssEscape(button.dataset.evoLegendOnly)}"]`);
      });
    });
    const shownKeys = () => {
      const query = session.legendQuery.trim().toLowerCase();
      return session.view.filtered.filter((item) => !query || item.label.toLowerCase().includes(query)).map((item) => item.key);
    };
    legend.querySelector("[data-evo-legend-all]")?.addEventListener("click", () => {
      shownKeys().forEach((key) => session.visibleKeys.add(key));
      refreshAfterLegend("[data-evo-legend-all]");
    });
    legend.querySelector("[data-evo-legend-none]")?.addEventListener("click", () => {
      shownKeys().forEach((key) => session.visibleKeys.delete(key));
      refreshAfterLegend("[data-evo-legend-none]");
    });
    const search = legend.querySelector("[data-evo-legend-search]");
    search?.addEventListener("input", () => {
      session.legendQuery = search.value;
      const caret = search.selectionStart;
      legend.innerHTML = legendMarkup(session.view);
      bindLegend();
      const next = legend.querySelector("[data-evo-legend-search]");
      next.focus({ preventScroll: true });
      next.setSelectionRange(caret, caret);
    });
  }

  // 图例 / 筛选变化：只重算视图、图例、详情与图，不重建整个弹窗
  function refreshAfterLegend(focusSelector) {
    session.view = computeView();
    const root = body();
    root.querySelector("[data-evo-legend]").innerHTML = legendMarkup(session.view);
    bindLegend();
    root.querySelector("[data-evo-detail]").innerHTML = detailMarkup();
    const details = root.querySelector(".evo-text-details");
    const wasOpen = details?.open;
    details?.insertAdjacentHTML("afterend", textDetailsMarkup(session.view));
    details?.remove();
    if (wasOpen) root.querySelector(".evo-text-details").open = true;
    bindDetailActions(root);
    updateChart();
    if (focusSelector) root.querySelector(focusSelector)?.focus({ preventScroll: true });
  }

  function rerenderKeepingFocus(selector) {
    const detailsOpen = body().querySelector(".evo-text-details")?.open;
    const legendOpen = body().querySelector(".evo-legend-panel")?.open;
    const scrollTop = body().scrollTop;
    renderSession();
    if (detailsOpen) body().querySelector(".evo-text-details").open = true;
    if (legendOpen !== undefined) body().querySelector(".evo-legend-panel").open = legendOpen;
    body().scrollTop = scrollTop;
    if (selector) body().querySelector(selector)?.focus({ preventScroll: true });
  }

  // 筛选把所有已显示的配置排除后，自动显示筛选结果里的前几个，避免空图
  function ensureSomeVisible() {
    const view = computeView();
    if (view.visible.length || !view.filtered.length) return;
    view.filtered.slice(0, DEFAULT_VISIBLE).forEach((item) => session.visibleKeys.add(item.key));
  }

  function bindDetailActions(root) {
    root.querySelectorAll("[data-evo-unlock]").forEach((button) => {
      button.onclick = () => {
        session.locked = null;
        root.querySelector("[data-evo-detail]").innerHTML = detailMarkup();
        bindDetailActions(root);
      };
    });
    root.querySelectorAll("[data-evo-locate]").forEach((button) => {
      button.onclick = () => locate(button.dataset.evoLocate, false);
    });
    root.querySelectorAll("[data-evo-locate-model]").forEach((button) => {
      button.onclick = () => locate(button.dataset.evoLocateModel, true);
    });
  }

  function locate(recordKey, switchToModel) {
    const record = session.records.find((item) => item.recordKey === recordKey);
    const callback = session.options.onLocateRecord;
    if (!record || !callback) return;
    const target = { recordKey, make: record.make, model: record.model, source: record.source, kind: record.kind, switchToModel };
    session.returnFocus = null;  // 定位后焦点交给结果表中的原记录
    close();
    callback(target);
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/["\\]/g, "\\$&");
  }

  function applyYearInputs() {
    const from = Number(body().querySelector('[data-evo-year="from"]').value);
    const to = Number(body().querySelector('[data-evo-year="to"]').value);
    if (!session.extent || !Number.isFinite(from) || !Number.isFinite(to)) return;
    const start = Math.max(session.extent[0], Math.min(from, to));
    const end = Math.min(session.extent[1], Math.max(from, to));
    session.zoom = { startValue: start - 0.5, endValue: end + 0.5 };
    if (session.chart) session.chart.dispatchAction({ type: "dataZoom", startValue: session.zoom.startValue, endValue: session.zoom.endValue });
    syncYearInputs();
  }

  function syncYearInputs() {
    const fromInput = body().querySelector('[data-evo-year="from"]');
    const toInput = body().querySelector('[data-evo-year="to"]');
    if (!fromInput || !toInput || !session.extent) return;
    const [min, max] = session.extent;
    const start = session.zoom ? Math.round(session.zoom.startValue + 0.5) : min;
    const end = session.zoom ? Math.round(session.zoom.endValue - 0.5) : max;
    [fromInput, toInput].forEach((input) => { input.min = String(min); input.max = String(max); });
    fromInput.value = String(Math.max(min, start));
    toInput.value = String(Math.min(max, end));
  }

  // ---------- 图表 ----------

  function isNarrow() {
    return window.matchMedia && window.matchMedia("(max-width: 760px)").matches;
  }

  function layout(view) {
    const narrow = isNarrow();
    const panels = [];
    let top = 34;
    const gap = 46;
    const add = (id, height) => { panels.push({ id, top, height }); top += height + gap; };
    add("length", narrow ? 210 : 250);
    if (session.showSales && session.metric === "potential" && potentialEntries().length) {
      add("potential", narrow ? 200 : 230);
      top += 38;
    }
    if (session.showSales && session.metric === "sales" && session.sales?.supported) add("sales", narrow ? 180 : 210);
    if (session.showWidthHeight) {
      add("width", narrow ? 120 : 140);
      add("height", narrow ? 120 : 140);
    }
    const lanes = sizeLanes(view);
    if (session.showSizeBand && lanes.length) add("size", Math.max(30, lanes.length * (narrow ? 22 : 24)));
    return { panels, height: top + 24, left: narrow ? 70 : 86, right: narrow ? 12 : 24, narrow, lanes };
  }

  // SIZE 带行：每个可见配置一行，同年冲突分支各占一子行
  function sizeLanes(view) {
    const lanes = [];
    view.visible.forEach((configuration) => {
      configuration.lanes.forEach((records, branch) => {
        lanes.push({ configuration, branch, branchCount: configuration.lanes.length, records });
      });
    });
    return lanes;
  }

  function mountChart() {
    const element = body().querySelector("[data-evo-chart]");
    if (!element || !window.echarts) return;
    session.chart = window.echarts.init(element, null, { renderer: "canvas" });
    const chart = session.chart;
    chart.on("click", (params) => {
      const data = params.data && params.data.meta;
      if (!data || !data.recordKey) return;
      session.locked = { type: "record", recordKey: data.recordKey };
      session.clickHandled = true;
      refreshDetail();
    });
    chart.on("datazoom", () => {
      const option = chart.getOption();
      const zoom = option.dataZoom && option.dataZoom[0];
      if (zoom && Number.isFinite(zoom.startValue) && Number.isFinite(zoom.endValue)) {
        session.zoom = zoom.start === 0 && zoom.end === 100 ? null : { startValue: zoom.startValue, endValue: zoom.endValue };
      }
      syncYearInputs();
      if (session.metric === "potential") updateChart();
      else refreshSales();
    });
    const zr = chart.getZr();
    zr.on("mousemove", (event) => showHover(event.offsetX, event.offsetY));
    zr.on("globalout", hideHover);
    zr.on("click", (event) => {
      if (session.clickHandled) { session.clickHandled = false; return; }
      const year = yearAtPixel(event.offsetX, event.offsetY);
      if (year === null) return;
      session.locked = { type: "year", year };
      refreshDetail();
    });
    session.resizeObserver = new ResizeObserver(scheduleResize);
    session.resizeObserver.observe(body().querySelector("[data-evo-chart-wrap]"));
    updateChart();
  }

  function scheduleResize() {
    if (!session || !session.chart) return;
    window.clearTimeout(session.resizeTimer);
    session.resizeTimer = window.setTimeout(() => {
      if (!session || !session.chart) return;
      const narrowNow = isNarrow();
      if (session.lastNarrow !== undefined && session.lastNarrow !== narrowNow) updateChart();
      else session.chart.resize();
    }, 80);
  }

  function refreshDetail() {
    const root = body();
    root.querySelector("[data-evo-detail]").innerHTML = detailMarkup();
    bindDetailActions(root);
  }

  function yearAtPixel(x, y) {
    if (!session.chart || !session.layout || !session.extent) return null;
    const gridIndex = session.layout.panels.findIndex((panel, index) => session.chart.containPixel({ gridIndex: index }, [x, y]));
    if (gridIndex < 0 || session.layout.panels[gridIndex].id === "potential") return null;
    const point = session.chart.convertFromPixel({ gridIndex }, [x, y]);
    const year = Math.round(Array.isArray(point) ? point[0] : Number.NaN);
    if (!Number.isFinite(year) || year < session.extent[0] || year > session.extent[1]) return null;
    return year;
  }

  function showHover(x, y) {
    const tooltip = body().querySelector("[data-evo-tooltip]");
    if (!tooltip) return;
    const potentialIndex = session.layout?.panels.findIndex((panel) => panel.id === "potential");
    const onPotential = potentialIndex >= 0 && session.chart.containPixel({ gridIndex: potentialIndex }, [x, y]);
    const year = yearAtPixel(x, y);
    if (onPotential) {
      const point = session.chart.convertFromPixel({ gridIndex: potentialIndex }, [x, y]);
      const entry = potentialEntries()[Math.round(point[0])];
      if (!entry) { hideHover(); return; }
      tooltip.innerHTML = `<strong>${escapeHtml(entry.configuration.label)}</strong>${recordLineMarkup(entry.record)}<code>${escapeHtml(entry.record.dimensionId || "")}</code><p>整条 YEAR 区间的潜力分，非年度销量。</p>`;
      session.hoverYear = null;
    } else if (year === null) { hideHover(); return; }
    else if (session.hoverYear !== year) {
      session.hoverYear = year;
      tooltip.innerHTML = yearSummaryMarkup(year);
    }
    tooltip.hidden = false;
    const wrap = body().querySelector("[data-evo-chart-wrap]");
    const width = tooltip.offsetWidth;
    const height = tooltip.offsetHeight;
    const maxLeft = wrap.clientWidth - width - 8;
    let left = x + 16;
    if (left > maxLeft) left = Math.max(8, x - width - 16);
    const top = Math.max(4, Math.min(y + 12, wrap.clientHeight - height - 4));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function hideHover() {
    const tooltip = body().querySelector("[data-evo-tooltip]");
    if (tooltip) tooltip.hidden = true;
    if (session) session.hoverYear = null;
  }

  function lineRenderer(color, dash) {
    return (params, api) => {
      const x1 = api.value(0);
      const x2 = api.value(1);
      const y1 = api.value(2);
      const y2 = api.value(3);
      const kind = api.value(4);  // 0 区间段, 1 年份边界阶梯连接
      const emphasis = api.value(5);  // 0 普通, 1 命中, 2 非命中（弱化）
      const anchor = api.value(6) === 1;
      const p1 = api.coord([x1, y1]);
      const p2 = api.coord([x2, y2]);
      if (kind === 1) {
        return {
          type: "line",
          silent: true,
          shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] },
          style: { stroke: color, lineWidth: 1.5, lineDash: [3, 3], opacity: emphasis === 2 ? 0.35 : 0.85 }
        };
      }
      const width = emphasis === 1 ? 4.5 : 3;
      const children = [
        { type: "rect", shape: { x: p1[0], y: p1[1] - 7, width: Math.max(1, p2[0] - p1[0]), height: 14 }, style: { fill: "rgba(0,0,0,0)" } },
        { type: "line", shape: { x1: p1[0] + 1, y1: p1[1], x2: p2[0] - 1, y2: p2[1] }, style: { stroke: color, lineWidth: width, lineDash: dash || null, lineCap: "butt", opacity: emphasis === 2 ? 0.4 : 1 } },
        { type: "line", silent: true, shape: { x1: p1[0] + 1, y1: p1[1] - 4, x2: p1[0] + 1, y2: p1[1] + 4 }, style: { stroke: color, lineWidth: 1.5, opacity: emphasis === 2 ? 0.4 : 1 } },
        { type: "line", silent: true, shape: { x1: p2[0] - 1, y1: p2[1] - 4, x2: p2[0] - 1, y2: p2[1] + 4 }, style: { stroke: color, lineWidth: 1.5, opacity: emphasis === 2 ? 0.4 : 1 } }
      ];
      if (anchor) {
        const cx = (p1[0] + p2[0]) / 2;
        children.push({ type: "polygon", silent: true, shape: { points: [[cx, p1[1] - 7], [cx + 6, p1[1]], [cx, p1[1] + 7], [cx - 6, p1[1]]] }, style: { fill: "#ffffff", stroke: color, lineWidth: 2 } });
      }
      return { type: "group", children };
    };
  }

  function sizeRenderer(data, sizeColor, sizeText) {
    return (params, api) => {
      const x1 = api.value(0);
      const x2 = api.value(1);
      const row = api.value(2);
      const status = api.value(3);  // 0 已匹配, 1 无可用尺码/数据不全, 2 SIZE 缺失
      const hit = api.value(4) === 1;
      const label = data[params.dataIndex]?.meta?.size || "";
      const p1 = api.coord([x1, row]);
      const p2 = api.coord([x2, row]);
      const bandHeight = api.size([0, 1])[1] * 0.72;
      const rect = { x: p1[0] + 1, y: p1[1] - bandHeight / 2, width: Math.max(2, p2[0] - p1[0] - 2), height: bandHeight };
      const clipped = window.echarts.graphic.clipRectByRect(rect, {
        x: params.coordSys.x, y: params.coordSys.y, width: params.coordSys.width, height: params.coordSys.height
      });
      if (!clipped) return null;
      const abnormal = status !== 0;
      const fill = abnormal ? "#eceff3" : sizeColor(label);
      const textFits = clipped.width > Math.max(26, label.length * 7.2 + 6);
      return {
        type: "rect",
        shape: { ...clipped, r: 3 },
        style: {
          fill,
          stroke: abnormal ? "#6b7280" : (hit ? "#172033" : "rgba(23,32,51,0.18)"),
          lineWidth: abnormal ? 1.2 : (hit ? 1.6 : 1),
          lineDash: abnormal ? [4, 3] : null
        },
        textContent: textFits ? {
          style: { text: label, fill: abnormal ? "#374151" : sizeText, fontSize: 11, fontWeight: 700, fontFamily: "D-DIN-PRO, Arial, sans-serif" }
        } : undefined,
        textConfig: textFits ? { position: "inside" } : undefined
      };
    };
  }

  const RULE_COLOR = "#475569";

  // 规则叠加：长度条件带（fitLow–上限）+ 上限虚线（标注尺码）；宽/高只画上限虚线。
  // 同一规则在同一年份段只画一次（多个配置命中同一规则时不叠加加深）；y 轴范围只纳入上限，带的下沿超出时按网格裁切
  function ruleRenderer(labels, withBand) {
    return (params, api) => {
      const x1 = api.value(0);
      const x2 = api.value(1);
      const low = api.value(2);
      const high = api.value(3);
      const top = api.coord([x1, high]);
      const right = api.coord([x2, high]);
      const grid = { x: params.coordSys.x, y: params.coordSys.y, width: params.coordSys.width, height: params.coordSys.height };
      const children = [];
      if (withBand && Number.isFinite(low)) {
        const bottom = api.coord([x1, low]);
        const band = window.echarts.graphic.clipRectByRect({ x: top[0], y: top[1], width: right[0] - top[0], height: bottom[1] - top[1] }, grid);
        if (band) children.push({ type: "rect", silent: true, shape: band, style: { fill: "rgba(71, 85, 105, 0.07)" } });
      }
      if (top[1] >= grid.y && top[1] <= grid.y + grid.height) {
        const left = Math.max(grid.x, top[0]);
        const end = Math.min(grid.x + grid.width, right[0]);
        children.push({ type: "line", silent: true, shape: { x1: left, y1: top[1], x2: end, y2: top[1] }, style: { stroke: RULE_COLOR, lineWidth: 1.2, lineDash: [5, 4], opacity: 0.8 } });
        const label = labels[params.dataIndex] || "";
        if (label && end - left > label.length * 7 + 12) {
          children.push({ type: "text", silent: true, style: { x: left + 4, y: top[1] - 2, text: label, fill: RULE_COLOR, fontSize: 10, fontWeight: 600, verticalAlign: "bottom" } });
        }
      }
      return children.length ? { type: "group", children } : null;
    };
  }

  function ruleSeries(view, panelIndex, unit) {
    if (!session.showRules) return [];
    const series = [];
    [["length", "lengthMax", true, "长上限"], ["width", "widthMax", false, "宽上限"], ["height", "heightMax", false, "高上限"]].forEach(([dimension, prop, withBand, title]) => {
      if (!panelIndex.has(dimension)) return;
      const index = panelIndex.get(dimension);
      // 同一上限（及长度条件下沿）合并为一条：可见记录覆盖的年份合并相接/重叠区间，标签列出命中的尺码
      const byLimit = new Map();
      view.visible.forEach((configuration) => {
        configuration.records.forEach((record) => {
          const rule = record.rule;
          if (!rule || rule[prop] === null) return;
          const key = `${rule[prop]}|${withBand ? rule.fitLow : ""}`;
          if (!byLimit.has(key)) byLimit.set(key, { rule, sizes: new Set(), intervals: [] });
          const entry = byLimit.get(key);
          entry.sizes.add(rule.size || rule.ruleId);
          entry.intervals.push(...record.intervals);
        });
      });
      const data = [];
      const labels = [];
      byLimit.forEach(({ rule, sizes, intervals }) => {
        D.mergeIntervals(intervals).forEach((interval) => {
          const [x1, x2] = D.intervalGeometry(interval);
          const low = withBand && rule.fitLow !== null ? D.convertFromMm(rule.fitLow, unit) : Number.NaN;
          data.push([x1, x2, low, D.convertFromMm(rule[prop], unit)]);
          labels.push(`${[...sizes].join(" / ")} ${title}`);
        });
      });
      if (!data.length) return;
      series.push({
        id: `rule|${dimension}`,
        name: `规则${title}`,
        type: "custom",
        xAxisIndex: index,
        yAxisIndex: index,
        silent: true,
        z: 1,
        renderItem: ruleRenderer(labels, withBand),
        encode: { x: [0, 1], y: 3 },
        data,
        animation: false
      });
    });
    return series;
  }

  function emphasisOf(record) {
    if (session.scope !== "full" || !session.hitTotal || session.hitTotal >= session.records.length) return 0;
    return record.isHit ? 1 : 2;
  }

  function buildOption(view, plan) {
    const unit = session.unit;
    const options = session.options;
    const [minYear, maxYear] = session.extent;
    const panelIndex = new Map(plan.panels.map((panel, index) => [panel.id, index]));
    const axisColor = "#667084";
    const grid = plan.panels.map((panel) => ({ left: plan.left, right: plan.right, top: panel.top, height: panel.height, containLabel: false }));
    const entries = potentialEntries();
    const xAxis = plan.panels.map((panel, index) => panel.id === "potential" ? {
      type: "category", gridIndex: index, data: entries.map(({ record }) => record.recordKey),
      axisLabel: { color: axisColor, fontSize: 10, rotate: 20, hideOverlap: true, formatter: (_, i) => `${entries[i]?.configuration.compactLabel || ""}\n${entries[i]?.record.yearText || ""}` },
      axisTick: { alignWithLabel: true }, axisPointer: { show: false }
    } : ({
      type: "value",
      gridIndex: index,
      min: minYear - 0.5,
      max: maxYear + 0.5,
      minInterval: 1,
      splitNumber: plan.narrow ? 4 : 10,
      axisLabel: { color: axisColor, fontSize: 11, formatter: (value) => (Number.isInteger(value) ? String(value) : "") },
      axisLine: { lineStyle: { color: "#c3cad6" } },
      splitLine: { show: panel.id !== "size", lineStyle: { color: "#eef1f5" } },
      axisPointer: {
        show: true,
        snap: false,
        triggerTooltip: false,
        lineStyle: { color: "#172033", width: 1, type: "dashed" },
        label: { show: index === plan.panels.length - 1, formatter: ({ value }) => String(Math.round(value)), backgroundColor: "#172033" }
      }
    }));
    const titles = plan.panels.map((panel) => ({
      text: panel.id === "potential" ? "市场潜力（分 · 每条尺寸记录）" : panel.id === "sales" ? "年度预估销量（辆）" : panel.id === "size" ? `${D.sizeHeading(D.sizeMeaningOf(options.source))} 年份时间带` : `${PANEL_TITLES[panel.id]}（${unit}）`,
      left: 8,
      top: panel.top - 26,
      textStyle: { fontSize: 13, fontWeight: 700, color: "#172033" }
    }));
    const yAxis = plan.panels.map((panel, index) => {
      if (panel.id === "potential") return { type: "value", gridIndex: index, min: 0, axisLabel: { color: axisColor, fontSize: 11 }, splitLine: { lineStyle: { color: "#eef1f5" } } };
      if (panel.id === "sales") return { type: "value", gridIndex: index, min: 0, minInterval: 1, axisLabel: { color: axisColor, fontSize: 11 }, splitLine: { lineStyle: { color: "#eef1f5" } } };
      if (panel.id === "size") {
        return {
          type: "category",
          gridIndex: index,
          inverse: true,
          data: plan.lanes.map((lane) => lane.configuration.key + "#" + lane.branch),
          axisTick: { show: false },
          axisLine: { show: false },
          axisLabel: {
            fontSize: 11,
            color: "#172033",
            width: plan.left - 14,
            overflow: "truncate",
            formatter: (value, laneIndex) => {
              const lane = plan.lanes[laneIndex];
              if (!lane) return "";
              const suffix = lane.branchCount > 1 ? ` · 分支${lane.branch + 1}` : "";
              return `{c${lane.configuration.colorIndex % LINE_COLORS.length}|■} ${lane.configuration.compactLabel}${suffix}`;
            },
            rich: Object.fromEntries(LINE_COLORS.map((color, colorIndex) => [`c${colorIndex}`, { color, fontSize: 12 }]))
          },
          splitLine: { show: true, interval: 0, lineStyle: { color: "#f1f3f7" } }
        };
      }
      return {
        type: "value",
        gridIndex: index,
        scale: true,
        splitNumber: panel.height > 180 ? 5 : 3,
        axisLabel: { color: axisColor, fontSize: 11, formatter: (value) => (unit === "mm" ? String(Math.round(value)) : String(Number(value.toFixed(1)))) },
        splitLine: { lineStyle: { color: "#eef1f5" } },
        name: "",
        nameLocation: "end",
        nameGap: 8,
        nameTextStyle: { color: axisColor, fontSize: 11, align: "right" }
      };
    });
    const series = ruleSeries(view, panelIndex, unit);
    ["length", "width", "height"].forEach((dimension) => {
      if (!panelIndex.has(dimension)) return;
      const index = panelIndex.get(dimension);
      const prop = PANEL_PROPS[dimension];
      view.visible.forEach((configuration) => {
        const data = [];
        configuration.records.forEach((record) => {
          if (record[prop] === null) return;
          const value = D.convertFromMm(record[prop], unit);
          record.intervals.forEach((interval) => {
            const [x1, x2] = D.intervalGeometry(interval);
            data.push({ value: [x1, x2, value, value, 0, emphasisOf(record), record.isAnchor ? 1 : 0], meta: { recordKey: record.recordKey } });
          });
        });
        configuration.connections[dimension].forEach((connection) => {
          const fromRecord = configuration.records.find((record) => record.recordKey === connection.fromKey);
          const toRecord = configuration.records.find((record) => record.recordKey === connection.toKey);
          const weak = emphasisOf(fromRecord) === 2 && emphasisOf(toRecord) === 2 ? 2 : 0;
          data.push({ value: [connection.x, connection.x, D.convertFromMm(connection.from, unit), D.convertFromMm(connection.to, unit), 1, weak, 0], meta: null });
        });
        if (!data.length) return;
        series.push({
          id: `${dimension}|${configuration.key}`,
          name: configuration.label,
          type: "custom",
          xAxisIndex: index,
          yAxisIndex: index,
          clip: true,
          z: 2,
          renderItem: lineRenderer(colorFor(configuration.colorIndex), dashFor(configuration.colorIndex)),
          encode: { x: [0, 1], y: [2, 3] },
          data,
          animation: false
        });
      });
    });
    if (panelIndex.has("size")) {
      const index = panelIndex.get("size");
      const sizeColor = options.sizeColor || (() => "#6b7280");
      const data = [];
      plan.lanes.forEach((lane, row) => {
        lane.records.forEach((record) => {
          const status = record.matchStatus === "matched" ? 0 : (record.matchStatus === "unknown" ? 2 : 1);
          const label = record.matchStatus === "unknown" ? "SIZE 缺失" : (record.sizeValue || "");
          record.intervals.forEach((interval) => {
            const [x1, x2] = D.intervalGeometry(interval);
            data.push({ value: [x1, x2, row, status, emphasisOf(record) === 1 ? 1 : 0], meta: { recordKey: record.recordKey, size: label } });
          });
        });
      });
      series.push({
        id: "size-band",
        name: "SIZE",
        type: "custom",
        xAxisIndex: index,
        yAxisIndex: index,
        renderItem: sizeRenderer(data, sizeColor, options.sizeTextColor || "#ffffff"),
        encode: { x: [0, 1], y: 2 },
        data,
        animation: false
      });
    }
    if (panelIndex.has("sales")) {
      const index = panelIndex.get("sales");
      const aggregated = salesAggregation();
      aggregated.groups.forEach(({ configuration, years }, slot) => {
        const count = aggregated.groups.length;
        series.push({
          id: `sales|${configuration.key}`, name: configuration.label, type: "custom",
          xAxisIndex: index, yAxisIndex: index, clip: true, animation: false,
          encode: { x: 0, y: 1 },
          data: Array.from(years.values()).filter((item) => item.atomIds.length > item.missing).map((item) => ({ value: [item.year, item.known], meta: { year: item.year } })),
          renderItem: (params, api) => {
            const year = api.value(0), value = api.value(1);
            const left = year - 0.4 + slot * 0.8 / count;
            const a = api.coord([left, value]), b = api.coord([left + 0.72 / count, 0]);
            const shape = window.echarts.graphic.clipRectByRect({ x: a[0], y: Math.min(a[1], b[1] - 1), width: Math.max(1, b[0] - a[0]), height: Math.max(1, b[1] - a[1]) }, params.coordSys);
            return shape ? { type: "rect", shape, style: { fill: colorFor(configuration.colorIndex), opacity: 0.86 } } : null;
          }
        });
      });
    }
    if (panelIndex.has("potential")) {
      const index = panelIndex.get("potential");
      series.push({ id: "market-potential", name: "市场潜力", type: "bar", xAxisIndex: index, yAxisIndex: index,
        barMaxWidth: 42, animation: false,
        data: entries.map(({ configuration, record }) => ({ value: record.marketPotential,
          itemStyle: { color: colorFor(configuration.colorIndex), opacity: emphasisOf(record) === 2 ? 0.4 : 0.86 },
          meta: { recordKey: record.recordKey } })) });
    }
    const allAxes = plan.panels.flatMap((panel, index) => panel.id === "potential" ? [] : [index]);
    const zoom = session.zoom || {};
    return {
      animation: false,
      title: titles,
      grid,
      xAxis,
      yAxis,
      series,
      axisPointer: { link: [{ xAxisIndex: allAxes }], triggerOn: "mousemove" },
      tooltip: { show: false },
      dataZoom: [
        { type: "inside", xAxisIndex: allAxes, filterMode: "none", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false, moveOnMouseMove: true, minValueSpan: 3, ...zoomRange(zoom) },
        {
          type: "slider", xAxisIndex: allAxes, filterMode: "none", height: 18, bottom: 4, left: plan.left, right: plan.right,
          minValueSpan: 3, labelFormatter: (value) => String(Math.round(value)), brushSelect: false, ...zoomRange(zoom)
        }
      ]
    };
  }

  function zoomRange(zoom) {
    return Number.isFinite(zoom.startValue) ? { startValue: zoom.startValue, endValue: zoom.endValue } : { start: 0, end: 100 };
  }

  function updateChart() {
    if (!session || !session.chart) return;
    refreshSales();
    const view = session.view;
    const element = body().querySelector("[data-evo-chart]");
    const empty = body().querySelector("[data-evo-empty]");
    hideHover();
    if (!session.extent || !view.visible.length) {
      empty.hidden = false;
      empty.textContent = !session.extent
        ? "所选范围没有可解析年份的记录，无法绘图；请查看文字详情。"
        : (view.filtered.length ? "图例中未勾选任何配置。" : "没有符合配置筛选的记录。");
      session.chart.clear();
      session.layout = null;
      element.style.height = "160px";
      session.chart.resize();
      syncYearInputs();
      return;
    }
    empty.hidden = true;
    const plan = layout(view);
    session.layout = plan;
    session.lastNarrow = plan.narrow;
    element.style.height = `${plan.height}px`;
    session.chart.resize();
    session.chart.setOption(buildOption(view, plan), { notMerge: true });
    syncYearInputs();
  }

  async function loadSales() {
    const current = session;
    current.salesState = "loading";
    refreshSales();
    try {
      const sales = current.options.loadModelSales ? await current.options.loadModelSales(current.options.modelKeys) : { supported: false };
      if (session !== current) return;
      const a0 = current.options.origin?.data?.a0_version || current.options.origin?.data?.version;
      if (sales.supported && a0 && sales.origin.a0_version !== a0) throw new Error("年度销量与车型历史的 A0 版本不一致，请刷新页面");
      current.sales = sales;
      current.salesState = "ready";
    } catch (error) {
      if (session !== current) return;
      current.salesState = "error";
      current.salesError = error.message || String(error);
    }
    refreshSales();
    updateChart();
    refreshDetail();
  }

  function salesAggregation() {
    if (session.salesView !== session.view || session.salesInput !== session.sales) {
      session.salesView = session.view;
      session.salesInput = session.sales;
      session.salesAggregated = D.aggregateSales(session.view.visible, session.sales.records);
    }
    return session.salesAggregated;
  }

  function salesValue(item) {
    if (!item) return "无记录";
    if (item.missing) return `已知销量小计 ${formatCount(item.known)} 辆＋缺失 ${item.missing} 条`;
    return `${formatCount(item.known)} 辆`;
  }

  function salesYearMarkup(year, { showAtomIds = false } = {}) {
    if (!session.sales?.supported) return "";
    const data = salesAggregation();
    const origin = session.sales.origin;
    return `<div class="evo-sales-year"><strong>${year} 年 · 可见配置合计：${salesValue(data.totals.get(year))}</strong>
      ${data.groups.filter((group) => group.years.has(year)).map(({ configuration, years }) => `<div>${swatch(configuration.colorIndex)} ${escapeHtml(configuration.label)}：${salesValue(years.get(year))}<details ${showAtomIds ? "open" : ""}><summary>原子 ID（${years.get(year).atomIds.length}）</summary><div class="evo-sales-ids">${years.get(year).atomIds.map(escapeHtml).join("<br>")}</div></details></div>`).join("")}
      <small>预估销量版本 ${escapeHtml(origin.sales_version)} · A0 ${escapeHtml(origin.a0_version)}</small></div>`;
  }

  function potentialEntries() {
    return D.potentialRecords(session.view.visible, session.zoom);
  }

  function potentialNumber(value) {
    return value === null || !Number.isFinite(value) ? "—" : Math.round(value).toLocaleString("en-US");
  }

  function refreshSales() {
    const status = body().querySelector("[data-evo-sales-status]");
    const details = body().querySelector("[data-evo-sales-details]");
    if (!status || !details) return;
    status.hidden = !session.showSales;
    details.hidden = !session.showSales;
    if (session.metric === "potential") {
      const entries = potentialEntries();
      const supported = ["US", "HNT", "TM", "TM_拆分"].includes(session.options.source);
      status.textContent = !supported ? "暂无同口径市场潜力数据" : `市场潜力 · 单位：分 · ${entries.length} 条尺寸记录 · 合计 ${potentialNumber(entries.reduce((sum, entry) => sum + entry.record.marketPotential, 0))} · 年份窗口仅筛选相交记录，分数不按年重复或折算`;
      details.innerHTML = "";
      return;
    }
    if (session.salesState === "loading") status.textContent = "年度预估销量加载中…";
    else if (session.salesState === "error") {
      status.innerHTML = `年度预估销量加载失败：${escapeHtml(session.salesError)} <button type="button" class="evo-link" data-evo-sales-retry>重试销量</button>`;
      status.querySelector("button").addEventListener("click", loadSales);
    } else if (!session.sales?.supported) status.textContent = "暂无同口径年度销量数据";
    else status.textContent = `美国车型预估销量 · 单位：辆 · ${D.isStoreSource(session.options.source) ? "车型市场预估销量；不代表店铺订单量 · " : ""}销量版本 ${session.sales.origin.sales_version} · 缺失不补零`;
    if (!session.sales?.supported) { details.innerHTML = ""; return; }
    const wasOpen = details.querySelector("details")?.open;
    const data = salesAggregation();
    const years = Array.from(data.totals.keys()).sort((a, b) => a - b).filter((year) => !session.zoom || (year >= Math.ceil(session.zoom.startValue) && year <= Math.floor(session.zoom.endValue)));
    details.innerHTML = `<details class="evo-sales-details" ${wasOpen ? "open" : ""}><summary>年度预估销量文字明细（${years.length} 年）</summary>${years.map(salesYearMarkup).join("")}</details>`;
  }

  window.SizeEvolution = { open, openModelPicker, close, isOpen };
})();
