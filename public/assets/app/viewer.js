(function () {
  const {
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
    searchQueryTokens,
    expandMatchShard,
    recordMatchesSearchToken,
    filterBySearchTokens,
    queryVehicleKind,
    cleanField,
    cleanText,
    escapeHtml
  } = window.SizeViewerData; // 数据纯函数，见 viewer-data.js
  const config = window.SIZE_CHART_VIEWER;
  const app = document.getElementById("app");

  if (!config || !app) {
    return;
  }

  const directories = config.directories || [];
  const pageMode = config.pageMode || "search";
  // 侧栏高亮：搜索页是尺码配对，Size Chart 页是 chart
  const navKey = config.navKey || (pageMode === "charts" ? "chart" : "match");
  const defaultViewConfig = {
    filters: {
      construct: { label: "CONSTRUCT", empty_label: "All constructs", source: "CONST", atomize: true },
      cab: { label: "CAB", empty_label: "All cabs", source: "CAB", atomize: true },
      bed: { label: "BED", empty_label: "All beds", source: "BED", atomize: true }
    },
    table_fields: {
      const: { label: "CONST", source: "CONST" },
      cab: { label: "CAB", source: "CAB" },
      bed: { label: "BED", source: "BED" }
    },
    excel_source: {
      match_data_path: "data/generated/size-match.json"
    },
    size_colors: {
      a: "#1777c8",
      c: "#d62828",
      h: "#00a6a6",
      s: "#f28c28",
      other: "#6b7280",
      text: "#ffffff"
    },
    match_sources: [],
    size_reference: {
      data_path: "data/generated/size-ref.json",
      match_field: "通用尺码"
    }
  };
  let activeChartSelection = "all";
  const sidebarStorageKey = "sizeChartSidebarCollapsed";
  let sidebarCollapsed = readSidebarCollapsed();
  let settingsOpen = false;
  let viewConfig = defaultViewConfig;
  const frameStates = new Map();
  const directoryIndexes = new Map();
  const directoryMetadata = new Map();
  const tsvIndexes = new Map();
  const configuredMatchIndexPromises = new Map();
  const configuredMatchManifestPromises = new Map();
  const matchDataOrigins = new Map();
  const sizeReferenceIndex = new Map();
  const sizeReferenceOrder = new Map();
  // 尺码配对 SIZE hover：按记录所属国别（US/EU/RU）读取 A0 尺码规则，店铺来源再按货架把发货尺码换回匹配尺码（viewer-rules.js）
  const sizeRules = window.SizeViewerRules.createRuleIndex({ sourceGroup: (name) => sourceGroup(name) });
  const initialSearchQuery = initialQuery();
  const searchState = {
    scopeKey: "",
    records: [],
    columns: [],
    query: initialSearchQuery,
    selectedSource: "",
    vehicleKind: "nonpick",  // 非皮卡与皮卡分开检索：只加载并显示当前类别的分片
    selectedMake: "",
    selectedSize: "",
    selectedModel: "",
    selectedYear: "",
    selectedConstruct: "",
    selectedCab: "",
    selectedBed: "",
    columnFilters: {},
    openFilter: "",
    columnWidths: {},  // 用户拖动设定的列宽；未设定的列按表头与内容自动计算
    filterSearch: "",  // 当前筛选弹层里的选项搜索词
    resetResultScroll: false,
    visibleColumns: null,
    fieldOrder: [...(config.fieldOrder || [])],  // 页面可指定初始列顺序；表格设置里仍可调整
    dimensionUnit: "cm",
    resultView: "table",
    tableFontSize: "md",
    resultLimit: 200,
    resultPage: 1,
    sortField: "",
    sortDirection: "asc",
    status: "idle",
    message: "",
    availableMakes: [],
    requiresMakeSelection: false,
    tableMode: initialTableMode()  // 压缩表 / 全量表：同一份分片的两种视图（config.tableModes），?view= 可直接指定
  };
  const maxResultPageSize = 500;
  const VEHICLE_KINDS = [["nonpick", "非皮卡"], ["pick", "皮卡"]];
  let searchLoadToken = 0;
  let globalSearchTimer = 0;
  let frameSearchTimer = 0;
  let headerFilterCloseTimer = 0;
  let copyFeedbackTimer = 0;
  // 压缩代号页：已展开来源车型的记录（记录对象随数据缓存常驻，重绘后保持展开）与当前表格渲染的记录
  const expandedSourceRecords = new WeakSet();
  let renderedResultRecords = [];
  // 车型代码表（CODE 前四位 → MAKE、MODEL、类别），有搜索词时才加载，用于 8 位代码解析与按车型自动切换类别；
  // 首屏的 ?q= 只在首次渲染时检查一次。lastAutoKind：上次按查询识别出的类别，识别结果不变时不再切换（保留用户随后的手动选择）
  let vehicleCodes = null;
  let vehicleCodesPromise = null;
  let initialVehicleCodeChecked = false;
  let lastAutoKind = "";
  // 本次搜索因会清空结果而被忽略的词（filterBySearchTokens），显示在结果摘要里
  let ignoredSearchTokens = [];
  // 车型尺寸演变可视化（size-evolution.js）：只在页面配置 evolution.enabled 时启用（size-chart 不启用）。
  // 选择状态按稳定 recordKey 存储，翻页、排序、切换表格/大纲时保留；source 或类别切换时清空。
  const evolutionConfig = config.evolution || {};
  const evolutionData = window.SizeEvolutionData || null;
  const evolutionAvailable = pageMode === "search" && Boolean(evolutionConfig.enabled && evolutionData && window.SizeEvolution);
  const EVOLUTION_COLUMN = "__evolution__";
  const evolutionSelection = new Map();
  let evolutionSelectionScope = "";
  let evolutionMatches = [];
  let evolutionPageRecords = new Map();
  let evolutionOutlineGroups = [];
  let sizeRulesOrigin = null;
  let storeGroupsOrigin = null;
  // SHAPE（车罩外形分类）中文名与说明：数据清单 shape_labels 提供，SHAPE 单元格悬停显示
  let shapeLabels = {};

  // 尺码配对页：压缩表视图是 A1 压缩记录（来源行带 DIMENSION-ID），全量表视图是 A0 行；车型可视化历史读同一份分片的全量行
  function evolutionOn() {
    return evolutionAvailable;
  }

  function applyPageMatchConfig() {
    if (!config.matchDataPath) return;
    viewConfig = {
      ...viewConfig,
      excel_source: { ...(viewConfig.excel_source || {}), match_data_path: config.matchDataPath },
      match_sources: config.matchSources || []
    };
  }

  function initialQuery() {
    return new URLSearchParams(window.location.search).get("q") || "";
  }

  // 尺码配对页的数据视图：页面声明 tableModes 时显示「视图」切换；同一份分片，切换只改显示逻辑，不重新下载
  function tableModes() {
    return Array.isArray(config.tableModes) ? config.tableModes.filter((mode) => mode && mode.key) : [];
  }

  function initialTableMode() {
    const modes = tableModes().map((mode) => mode.key);
    if (!modes.length) return "full";
    const requested = new URLSearchParams(window.location.search).get("view");
    if (modes.includes(requested)) return requested;
    return modes.includes(config.defaultTableMode) ? config.defaultTableMode : modes[0];
  }

  function tableModeLabel(key) {
    return tableModes().find((mode) => mode.key === key)?.label || key;
  }

  function syncTableModeUrl() {
    if (!tableModes().length || !window.history?.replaceState) return;
    const url = new URL(window.location.href);
    url.searchParams.set("view", searchState.tableMode);
    window.history.replaceState(window.history.state, "", url);
  }

  function readSidebarCollapsed() {
    try {
      return window.localStorage.getItem(sidebarStorageKey) === "true";
    } catch (error) {
      return false;
    }
  }

  function saveSidebarCollapsed(value) {
    try {
      window.localStorage.setItem(sidebarStorageKey, value ? "true" : "false");
    } catch (error) {
      // Ignore storage failures; the in-page state still updates.
    }
  }

  function pagePath(directory, file) {
    return `${config.basePath}${directory.name}/${file}`;
  }

  function chartDirectories() {
    if (activeChartSelection === "all") {
      return directories;
    }
    if (activeChartSelection.startsWith("source:")) {
      const source = activeChartSelection.slice("source:".length);
      return directories.filter((directory) => topSource(directory.name) === source);
    }
    if (activeChartSelection.startsWith("dir:")) {
      const name = activeChartSelection.slice("dir:".length);
      return directories.filter((directory) => directory.name === name);
    }
    return directories;
  }

  function chartSelectionLabel() {
    if (activeChartSelection === "all") {
      return "All";
    }
    if (activeChartSelection.startsWith("source:")) {
      return activeChartSelection.slice("source:".length);
    }
    if (activeChartSelection.startsWith("dir:")) {
      return activeChartSelection.slice("dir:".length);
    }
    return config.rootLabel;
  }

  function chartOutlineMarkup() {
    const sources = [];
    directories.forEach((directory) => {
      const source = topSource(directory.name);
      if (source && !sources.includes(source)) {
        sources.push(source);
      }
    });

    return `
      <ol class="chart-outline-list">
        <li>
          <button class="chart-outline-node${activeChartSelection === "all" ? " is-active" : ""}" type="button" data-chart-scope="all">
            <span class="chart-outline-dot"></span>
            <span>All</span>
          </button>
        </li>
        ${sources.map((source) => {
        const children = directories.filter((directory) => topSource(directory.name) === source);
          return `
            <li>
              <button class="chart-outline-node${activeChartSelection === `source:${source}` ? " is-active" : ""}" type="button" data-chart-scope="source:${escapeHtml(source)}">
                <span class="chart-outline-dot"></span>
                <span>${escapeHtml(source)}</span>
              </button>
              <ol class="chart-outline-list chart-outline-children">
                ${children.map((directory) => {
            const value = `dir:${directory.name}`;
                  return `
                    <li>
                      <button class="chart-outline-node chart-outline-leaf${activeChartSelection === value ? " is-active" : ""}" type="button" data-chart-scope="${escapeHtml(value)}">
                        <span class="chart-outline-dot"></span>
                        <span>${escapeHtml(directoryLeaf(directory.name))}</span>
                      </button>
                    </li>
                  `;
                }).join("")}
              </ol>
            </li>
          `;
        }).join("")}
      </ol>
    `;
  }

  function storeOptions() {
    const group = sourceGroup(searchState.selectedSource);
    return (viewConfig.match_sources || []).filter((source) => sourceGroup(source.name) === group);
  }

  function sourceGroup(name) {
    const configured = (viewConfig.match_sources || []).find((source) => source.name === name);
    return cleanField(configured?.group) || cleanField(name);
  }

  function sourceOutlineMarkup() {
    const configuredSources = uniqueInOrder((viewConfig.match_sources || []).map((source) => sourceGroup(source.name)).filter(Boolean));
    const loadedSources = uniqueInOrder(searchState.records.map((record) => sourceGroup(sourceFilterValue(record))));
    const sources = uniqueInOrder([...configuredSources, ...loadedSources]);
    return `
      <ol class="chart-outline-list source-outline-list">
        ${sources.map((source) => `
          <li>
            <button class="chart-outline-node source-outline-node${sourceGroup(searchState.selectedSource) === source ? " is-active" : ""}" type="button" data-sidebar-source="${escapeHtml(source)}" aria-pressed="${sourceGroup(searchState.selectedSource) === source ? "true" : "false"}">
              <span class="chart-outline-dot"></span>
              <span>${escapeHtml(sourceLabel(source))}</span>
            </button>
          </li>
        `).join("")}
      </ol>
    `;
  }

  function directoryLeaf(directoryName) {
    const parts = String(directoryName || "").split(/[\\/]/);
    return parts[parts.length - 1] || directoryName;
  }

  function chartFileCount(scopeDirectories) {
    return scopeDirectories.reduce((total, directory) => total + directory.files.length, 0);
  }

  function render() {
    const selectedChartDirectories = chartDirectories();
    const selectedChartLabel = chartSelectionLabel();
    const selectedChartFileCount = chartFileCount(selectedChartDirectories);
    const isSearchPage = pageMode !== "charts";
    app.innerHTML = `
      <main class="viewer-main viewer-shell${sidebarCollapsed ? " is-sidebar-collapsed" : ""}">
        <aside class="viewer-side" aria-label="Page outline">
          <div class="sidebar-head">
            <button class="sidebar-toggle" type="button" aria-label="${sidebarCollapsed ? "展开侧栏" : "收起侧栏"}" aria-expanded="${sidebarCollapsed ? "false" : "true"}">
              <span>☰</span>
            </button>
          </div>
          <nav class="sidebar-nav" aria-label="Pages">
            <a href="index.html" title="首页"><span class="nav-icon">首</span><span class="nav-label">首页</span></a>
            <a class="${!isSearchPage ? "is-active" : ""}" href="size-chart.html" title="Size Chart"><span class="nav-icon">S</span><span class="nav-label">Size Chart</span></a>
            <a href="size-ref.html" title="尺码参考"><span class="nav-icon">参</span><span class="nav-label">尺码参考</span></a>
            <a class="${navKey === "match" || navKey === "code" ? "is-active" : ""}" href="size-match.html" title="尺码配对（含压缩代号）"><span class="nav-icon">尺</span><span class="nav-label">尺码配对</span></a>
          </nav>
          ${isSearchPage ? `
            <nav class="sidebar-outline source-outline" aria-label="Source filter">
              <div class="sidebar-filter-title">Source</div>
              <div class="chart-outline" aria-label="Source filter">
                ${sourceOutlineMarkup()}
              </div>
            </nav>
          ` : ""}
          ${!isSearchPage ? `
            <nav class="sidebar-outline size-chart-outline" aria-label="Size chart outline">
              <div class="chart-outline" aria-label="Size chart folders">
                ${chartOutlineMarkup()}
              </div>
            </nav>
          ` : ""}
          ${isSearchPage ? `
            <div class="sidebar-tools">
              <div class="unit-toggle size-unit-toggle sidebar-unit-toggle" role="group" aria-label="长宽高单位">
                ${["mm", "cm", "in"].map((unit) => `<button type="button" data-size-unit="${unit}" class="${searchState.dimensionUnit === unit ? "is-active" : ""}" aria-pressed="${searchState.dimensionUnit === unit ? "true" : "false"}">${unit.toUpperCase()}</button>`).join("")}
              </div>
              <button class="settings-launch" type="button" data-open-settings>表格设置</button>
            </div>
          ` : ""}
        </aside>
        <div class="viewer-content">
        ${isSearchPage ? `
        <section class="search-panel" aria-label="Size chart search">
          <div class="global-search">
            <label>
              <span>GLOBAL</span>
              <input class="global-search-input" type="search" value="${escapeHtml(searchState.query)}" placeholder="${escapeHtml(config.searchPlaceholder || "Search nonpick, pick, 宏能图, TM, code, make, model, type, size, year...")}" autocomplete="off">
            </label>
            <button class="search-reset" type="button">Reset</button>
          </div>
          <div class="lazy-load-scope">
            <div class="vehicle-kind-field"><span>类别</span><div class="result-view-toggle vehicle-kind-toggle" role="group" aria-label="车型类别">
              ${VEHICLE_KINDS.map(([value, label]) => `<button type="button" data-vehicle-kind="${value}" class="${searchState.vehicleKind === value ? "is-active" : ""}" aria-pressed="${searchState.vehicleKind === value ? "true" : "false"}" ${searchState.status === "loading" ? "disabled" : ""}>${label}</button>`).join("")}
            </div></div>
            ${tableModes().length ? `<div class="vehicle-kind-field table-mode-field"><span>视图</span><div class="result-view-toggle table-mode-toggle" role="group" aria-label="数据视图">
              ${tableModes().map((mode) => `<button type="button" data-table-mode="${escapeHtml(mode.key)}" class="${searchState.tableMode === mode.key ? "is-active" : ""}" aria-pressed="${searchState.tableMode === mode.key ? "true" : "false"}" title="${escapeHtml(mode.key === "full" ? "A0 全量表：每个车型年份段一行" : "A1 压缩尺码表：同尺码合并，点 CODE 展开来源车型")}">${escapeHtml(mode.label || mode.key)}</button>`).join("")}
            </div></div>` : ""}
            <label${storeOptions().length > 1 ? "" : " hidden"}><span>店铺</span><select class="search-select" data-lazy-source ${searchState.status === "loading" ? "disabled" : ""}>
              ${storeOptions().map((source) => `<option value="${escapeHtml(source.name)}"${searchState.selectedSource === source.name ? " selected" : ""}>${escapeHtml(cleanField(source.label) || sourceLabel(source.name))}</option>`).join("")}
            </select></label>
            <label>
              <span>MAKE</span>
              <select class="search-select" data-lazy-make ${searchState.status === "loading" || !searchState.availableMakes.length ? "disabled" : ""}>
                <option value="">全部 MAKE</option>
                ${searchState.availableMakes.map((make) => `<option value="${escapeHtml(make)}"${searchState.selectedMake === make ? " selected" : ""}>${escapeHtml(make)}</option>`).join("")}
              </select>
            </label>
            <label><span>SIZE</span><select class="search-select" data-lazy-size ${searchState.status !== "ready" ? "disabled" : ""}><option value="">全部尺码</option></select></label>
          </div>
          <div class="search-result-toolbar">
            <div class="search-summary" role="status"></div>
            ${evolutionOn() ? '<div class="evolution-toolbar" data-evolution-toolbar hidden></div>' : ""}
            <div class="result-view-toggle" role="group" aria-label="结果视图">
              ${[
                ["table", "表格"],
                ["outline", "大纲"]
              ].map(([value, label]) => `<button type="button" data-result-view="${value}" class="${searchState.resultView === value ? "is-active" : ""}" aria-pressed="${searchState.resultView === value ? "true" : "false"}">${label}</button>`).join("")}
            </div>
          </div>
          <div class="active-filter-chips" aria-label="Active filters"></div>
          <div class="search-results"></div>
          <div class="copy-feedback" role="status" aria-live="polite"></div>
        </section>
        ${sizeSettingsModalMarkup()}
        ` : `
        <section class="page-stack size-charts-panel" aria-label="Size Chart">
          <div class="size-charts-header">
            <div>
              <h2>Size Chart</h2>
              <p>${selectedChartLabel} · ${selectedChartFileCount} HTML</p>
            </div>
          </div>
          <div class="page-card-list">
            ${selectedChartDirectories.flatMap((directory) => directory.files.map((file) => `
              <article class="page-card">
                <div class="page-card-header">
                  <div class="page-name">${directory.name}/${file}</div>
                  <a class="open-link" href="${pagePath(directory, file)}">打开</a>
                </div>
                <div class="frame-shell">
                  <iframe class="page-frame" title="${directory.name}/${file}" src="${pagePath(directory, file)}"></iframe>
                </div>
              </article>
            `)).join("")}
          </div>
        </section>
        `}
        </div>
      </main>
    `;

    bind();
    if (isSearchPage) {
      updateSearchControls();
      updateSearchResults();
      if (initialVehicleCodeChecked) {
        loadSearchIndex(currentSearchDirectories());
      } else {
        initialVehicleCodeChecked = true;
        // 首屏 URL 明确指定了 ?view= 时保持该视图，只切换类别
        const keepView = new URLSearchParams(window.location.search).has("view");
        applyQueryVehicleKind({ keepView }).then(() => loadSearchIndex(currentSearchDirectories()));
      }
    } else {
      resizeFrames();
    }
  }

  function sizeFilterControlsMarkup() {
    return `
      <div class="sidebar-filter-title">字段筛选</div>
      <div class="sidebar-filter-list">
        <label>
          <span>MAKE</span>
          <select class="search-select" data-search-field="make" ${searchState.status === "loading" ? "disabled" : ""}>
            <option value="">All makes</option>
          </select>
        </label>
        <label>
          <span>MODEL</span>
          <select class="search-select" data-search-field="model" ${searchState.status === "loading" ? "disabled" : ""}>
            <option value="">All models</option>
          </select>
        </label>
        <label>
          <span>YEAR</span>
          <select class="search-select" data-search-field="year" ${searchState.status === "loading" ? "disabled" : ""}>
            <option value="">All years</option>
          </select>
        </label>
        <label>
          <span>${escapeHtml(filterConfig("construct").label)}</span>
          <select class="search-select" data-search-field="construct" ${searchState.status === "loading" ? "disabled" : ""}>
            <option value="">${escapeHtml(filterConfig("construct").empty_label)}</option>
          </select>
        </label>
        <label>
          <span>${escapeHtml(filterConfig("cab").label)}</span>
          <select class="search-select" data-search-field="cab" ${searchState.status === "loading" ? "disabled" : ""}>
            <option value="">${escapeHtml(filterConfig("cab").empty_label)}</option>
          </select>
        </label>
        <label>
          <span>${escapeHtml(filterConfig("bed").label)}</span>
          <select class="search-select" data-search-field="bed" ${searchState.status === "loading" ? "disabled" : ""}>
            <option value="">${escapeHtml(filterConfig("bed").empty_label)}</option>
          </select>
        </label>
      </div>
    `;
  }

  function sizeSettingsModalMarkup() {
    return `
      <div class="settings-overlay${settingsOpen ? " is-open" : ""}" data-settings-overlay>
        <section class="settings-dialog" role="dialog" aria-modal="true" aria-label="表格设置">
          <div class="settings-dialog-header">
            <div>
              <h3>表格设置</h3>
              <p>显示字段和排序</p>
            </div>
            <button type="button" class="settings-close" data-close-settings aria-label="关闭">×</button>
          </div>
          <div class="settings-dialog-body">
            <section class="settings-block">
              <h4>显示字段</h4>
              <div class="field-menu-panel settings-field-list">
                <div class="field-menu-heading">
                  <span>字段</span>
                  <span>顺序</span>
                </div>
                ${sizeDisplayFields().map((field) => `
                  <div class="field-option">
                    <label>
                      <input type="checkbox" data-size-field-toggle value="${escapeHtml(field.key)}" ${isSizeColumnVisible(field.key) ? "checked" : ""}>
                      <span>${escapeHtml(field.label)}</span>
                    </label>
                    <div class="field-order-actions">
                      <button type="button" data-size-move-field="${escapeHtml(field.key)}" data-move-direction="-1" title="上移">↑</button>
                      <button type="button" data-size-move-field="${escapeHtml(field.key)}" data-move-direction="1" title="下移">↓</button>
                    </div>
                  </div>
                `).join("")}
              </div>
            </section>
            <section class="settings-block">
              <h4>表格字号</h4>
              <div class="settings-segmented" role="group" aria-label="表格字号">
                ${[
                  ["sm", "紧凑"],
                  ["md", "标准"],
                  ["lg", "舒展"]
                ].map(([value, label]) => `
                  <button type="button" data-size-font="${value}" class="${searchState.tableFontSize === value ? "is-active" : ""}">${label}</button>
                `).join("")}
              </div>
            </section>
            <section class="settings-block">
              <h4>排序</h4>
              <div class="settings-sort-row">
                <label class="sort-control">
                  <span>排序字段</span>
                  <select class="search-select" data-size-sort-field ${searchState.status === "loading" ? "disabled" : ""}>
                    <option value="">默认顺序</option>
                    ${sizeDisplayFields().map((field) => `<option value="${escapeHtml(field.key)}"${searchState.sortField === field.key ? " selected" : ""}>${escapeHtml(field.label)}</option>`).join("")}
                  </select>
                </label>
                <button class="sort-direction" type="button" data-size-sort-direction title="切换排序方向">${searchState.sortDirection === "asc" ? "↑" : "↓"}</button>
              </div>
            </section>
          </div>
        </section>
      </div>
    `;
  }

  function bind() {
    const sidebarToggle = app.querySelector(".sidebar-toggle");
    sidebarToggle.addEventListener("click", () => {
      sidebarCollapsed = !sidebarCollapsed;
      saveSidebarCollapsed(sidebarCollapsed);
      render();
    });

    app.querySelectorAll("[data-open-settings]").forEach((button) => {
      button.addEventListener("click", () => {
        settingsOpen = true;
        render();
      });
    });

    app.querySelectorAll("[data-close-settings]").forEach((button) => {
      button.addEventListener("click", () => {
        settingsOpen = false;
        render();
      });
    });

    app.querySelectorAll("[data-settings-overlay]").forEach((overlay) => {
      overlay.addEventListener("click", (event) => {
        if (event.target === overlay) {
          settingsOpen = false;
          render();
        }
      });
    });

    app.querySelectorAll("[data-sidebar-source]").forEach((button) => {
      button.addEventListener("click", () => {
        searchState.selectedSource = button.dataset.sidebarSource || "";
        searchState.scopeKey = "";
        searchState.selectedMake = "";
        searchState.selectedSize = "";
        searchState.availableMakes = [];
        searchState.requiresMakeSelection = false;
        searchState.selectedModel = "";
        searchState.selectedYear = "";
        searchState.selectedConstruct = "";
        searchState.selectedCab = "";
        searchState.selectedBed = "";
        searchState.columnFilters = {};
        searchState.openFilter = "";
        searchState.sortField = "";
        searchState.sortDirection = "asc";
        searchState.resultPage = 1;
        render();
      });
    });

    const lazyMakeSelect = app.querySelector("[data-lazy-make]");
    if (lazyMakeSelect) {
      lazyMakeSelect.addEventListener("change", () => {
        searchState.selectedMake = lazyMakeSelect.value;
        searchState.selectedSize = "";
        searchState.selectedModel = "";
        searchState.selectedYear = "";
        searchState.selectedConstruct = "";
        searchState.selectedCab = "";
        searchState.selectedBed = "";
        searchState.columnFilters = {};
        searchState.openFilter = "";
        searchState.sortField = "";
        searchState.sortDirection = "asc";
        searchState.resultPage = 1;
        searchState.scopeKey = "";
        loadSearchIndex(currentSearchDirectories());
      });
    }

    const lazySourceSelect = app.querySelector("[data-lazy-source]");
    if (lazySourceSelect) lazySourceSelect.addEventListener("change", () => {
      searchState.selectedSource = lazySourceSelect.value;
      searchState.selectedMake = "";
      searchState.selectedSize = "";
      searchState.availableMakes = [];
      searchState.scopeKey = "";
      searchState.resultPage = 1;
      render();
    });
    app.querySelectorAll("[data-vehicle-kind]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.vehicleKind === searchState.vehicleKind) return;
        searchState.vehicleKind = button.dataset.vehicleKind;
        searchState.availableMakes = [];
        resetSearchFilters();
        render();
      });
    });
    // 压缩表 / 全量表：保留搜索词、来源、类别、MAKE、SIZE 与 MODEL 等选择，只清列筛选与排序（两种视图的列不同）；
    // 分片已缓存，切换不重新下载
    app.querySelectorAll("[data-table-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        const nextMode = button.dataset.tableMode;
        if (nextMode === searchState.tableMode || !tableModes().some((mode) => mode.key === nextMode)) return;
        searchState.tableMode = nextMode;
        searchState.scopeKey = "";
        searchState.columnFilters = {};
        searchState.openFilter = "";
        searchState.sortField = "";
        searchState.sortDirection = "asc";
        searchState.resultPage = 1;
        searchState.resetResultScroll = true;
        syncTableModeUrl();
        render();
      });
    });
    const lazySizeSelect = app.querySelector("[data-lazy-size]");
    if (lazySizeSelect) lazySizeSelect.addEventListener("change", () => {
      searchState.selectedSize = lazySizeSelect.value;
      searchState.resultPage = 1;
      updateSearchResults();
    });

    app.querySelectorAll("[data-dir]").forEach((button) => {
      button.addEventListener("click", () => {
        if (directories.some((directory) => directory.name === button.dataset.dir)) {
          activeChartSelection = `dir:${button.dataset.dir}`;
          frameStates.clear();
          render();
          window.scrollTo({ top: 0, behavior: "instant" });
        }
      });
    });

    app.querySelectorAll("[data-chart-scope]").forEach((button) => {
      button.addEventListener("click", () => {
        activeChartSelection = button.dataset.chartScope;
        frameStates.clear();
        render();
      });
    });

    const globalInput = app.querySelector(".global-search-input");
    if (!globalInput) {
      app.querySelectorAll(".page-frame").forEach((frame) => {
        frame.addEventListener("load", () => {
          measureFrame(frame);
          resizeFrames();
        });
      });
      return;
    }
    globalInput.addEventListener("input", () => {
      window.clearTimeout(globalSearchTimer);
      searchState.query = globalInput.value;
      resetSearchFilters();
      updateSourceOutlineState();
      searchLoadToken += 1;
      globalSearchTimer = window.setTimeout(async () => {
        const query = searchState.query;
        await applyQueryVehicleKind();
        if (query !== searchState.query) return;
        loadSearchIndex(currentSearchDirectories());
      }, 180);
    });

    app.querySelectorAll("[data-search-field]").forEach((select) => {
      select.addEventListener("change", () => {
        if (select.dataset.searchField === "make") {
          searchState.selectedMake = select.value;
          searchState.selectedModel = "";
          searchState.selectedYear = "";
          searchState.selectedConstruct = "";
          searchState.selectedCab = "";
          searchState.selectedBed = "";
        } else if (select.dataset.searchField === "model") {
          searchState.selectedModel = select.value;
          searchState.selectedYear = "";
          searchState.selectedConstruct = "";
          searchState.selectedCab = "";
          searchState.selectedBed = "";
        } else if (select.dataset.searchField === "year") {
          searchState.selectedYear = select.value;
          searchState.selectedConstruct = "";
          searchState.selectedCab = "";
          searchState.selectedBed = "";
        } else if (select.dataset.searchField === "construct") {
          searchState.selectedConstruct = select.value;
          searchState.selectedCab = "";
          searchState.selectedBed = "";
        } else if (select.dataset.searchField === "cab") {
          searchState.selectedCab = select.value;
          searchState.selectedBed = "";
        } else if (select.dataset.searchField === "bed") {
          searchState.selectedBed = select.value;
        }
        searchState.resultPage = 1;
        updateSearchControls();
        updateSearchResults();
      });
    });

    app.querySelectorAll("[data-size-table-filter]").forEach((select) => {
      select.addEventListener("change", () => {
        const key = select.dataset.sizeTableFilter;
        if (select.value) {
          searchState.columnFilters[key] = select.value;
        } else {
          delete searchState.columnFilters[key];
        }
        searchState.resultPage = 1;
        updateSearchResults();
      });
    });

    app.querySelectorAll("[data-size-multi-filter]").forEach((input) => {
      input.addEventListener("change", () => {
        updateMultiColumnFilter(input.dataset.sizeMultiFilter);
      });
    });

    app.querySelectorAll("[data-size-range-filter]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.dataset.sizeRangeFilter;
        const side = input.dataset.rangeSide;
        const current = typeof searchState.columnFilters[key] === "object" ? searchState.columnFilters[key] : {};
        const next = { ...current, [side]: input.value };
        if (next.min || next.max) {
          searchState.columnFilters[key] = next;
        } else {
          delete searchState.columnFilters[key];
        }
        searchState.resultPage = 1;
        updateSearchResults();
      });
    });

    app.querySelectorAll("[data-result-limit]").forEach((control) => {
      control.addEventListener("change", () => {
        searchState.resultLimit = Math.min(maxResultPageSize, Math.max(1, Number(control.value) || 200));
        searchState.resultPage = 1;
        searchState.resetResultScroll = true;
        updateSearchResults();
      });
    });

    app.querySelectorAll("[data-size-field-toggle]").forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        ensureSizeFieldState();
        if (checkbox.checked) {
          searchState.visibleColumns.add(checkbox.value);
        } else {
          searchState.visibleColumns.delete(checkbox.value);
        }
        searchState.resultPage = 1;
        updateSearchResults();
      });
    });

    app.querySelectorAll("[data-size-unit]").forEach((button) => {
      button.addEventListener("click", () => {
        const nextUnit = button.dataset.sizeUnit || "cm";
        if (nextUnit === searchState.dimensionUnit) return;
        searchState.dimensionUnit = nextUnit;
        Object.keys(searchState.columnFilters).forEach((key) => {
          if (isRangeFilterColumn(key)) delete searchState.columnFilters[key];
        });
        if (isDimensionColumn(searchState.sortField) || isLengthMarginColumn(searchState.sortField)) {
          searchState.sortField = "";
          searchState.sortDirection = "asc";
        }
        searchState.openFilter = "";
        searchState.resultPage = 1;
        ensureSizeFieldState();
        render();
      });
    });

    app.querySelectorAll("[data-result-view]").forEach((button) => {
      button.addEventListener("click", () => {
        const nextView = button.dataset.resultView === "outline" ? "outline" : "table";
        if (nextView === searchState.resultView) return;
        searchState.resultView = nextView;
        app.querySelectorAll("[data-result-view]").forEach((item) => {
          const active = item.dataset.resultView === nextView;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", active ? "true" : "false");
        });
        updateSearchResults();
      });
    });

    app.querySelectorAll("[data-size-font]").forEach((button) => {
      button.addEventListener("click", () => {
        searchState.tableFontSize = button.dataset.sizeFont || "md";
        render();
      });
    });

    app.querySelectorAll("[data-size-move-field]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        moveSizeField(button.dataset.sizeMoveField, Number(button.dataset.moveDirection));
        render();
      });
    });

    const sizeSortSelect = app.querySelector("[data-size-sort-field]");
    if (sizeSortSelect) {
      sizeSortSelect.addEventListener("change", () => {
        searchState.sortField = sizeSortSelect.value;
        searchState.resultPage = 1;
        updateSearchResults();
      });
    }

    const sizeSortDirection = app.querySelector("[data-size-sort-direction]");
    if (sizeSortDirection) {
      sizeSortDirection.addEventListener("click", () => {
        searchState.sortDirection = searchState.sortDirection === "asc" ? "desc" : "asc";
        sizeSortDirection.textContent = searchState.sortDirection === "asc" ? "↑" : "↓";
        searchState.resultPage = 1;
        updateSearchResults();
      });
    }

    const resetButton = app.querySelector(".search-reset");
    resetButton.addEventListener("click", () => {
      window.clearTimeout(globalSearchTimer);
      searchState.query = "";
      resetSearchFilters({ resetSource: true });
      updateSourceOutlineState();
      const globalInput = app.querySelector(".global-search-input");
      if (globalInput) {
        globalInput.value = "";
      }
      loadSearchIndex(currentSearchDirectories());
      updateSearchControls();
      updateSearchResults();
    });

    app.querySelectorAll(".page-frame").forEach((frame) => {
      frame.addEventListener("load", () => {
        measureFrame(frame);
        resizeFrames();
        if (searchState.status === "error") {
          scheduleFrameSearchIndex();
        }
      });
    });
  }

  function resetSearchFilters({ resetSource = false } = {}) {
    searchState.scopeKey = "";
    if (resetSource) {
      searchState.selectedSource = defaultSourceFilter();
    }
    searchState.selectedMake = "";
    searchState.selectedSize = "";
    searchState.requiresMakeSelection = false;
    searchState.selectedModel = "";
    searchState.selectedYear = "";
    searchState.selectedConstruct = "";
    searchState.selectedCab = "";
    searchState.selectedBed = "";
    searchState.columnFilters = {};
    searchState.openFilter = "";
    searchState.sortField = "";
    searchState.sortDirection = "asc";
    searchState.resultPage = 1;
  }

  function currentSearchDirectories() {
    return directories;
  }

  async function loadSearchIndex(scopeDirectories) {
    // 配置了 match_sources 时数据来自清单，不依赖 size chart 目录（压缩代号页 directories 为空）
    if (!scopeDirectories.length && !viewConfig.match_sources?.length) {
      return;
    }

    const token = ++searchLoadToken;
    const usesConfiguredSources = Boolean(viewConfig.match_sources?.length);
    const scopeKey = usesConfiguredSources
      ? `configured:${searchState.tableMode}:${searchState.selectedSource}:${searchState.vehicleKind}:${searchState.selectedMake || "all-makes"}`
      : scopeDirectories.map((directory) => directory.name).join("|");
    if (searchState.scopeKey === scopeKey && (searchState.status === "ready" || searchState.status === "loading")) {
      updateSearchControls();
      updateSearchResults();
      return;
    }
    searchState.scopeKey = scopeKey;
    searchState.records = [];
    searchState.columns = [];
    searchState.status = "loading";
    searchState.message = searchState.selectedMake ? `Loading ${searchState.selectedMake} records...` : "正在加载全部 MAKE...";
    updateLazyMakeControl();
    updateSearchControls();
    updateSearchResults();

    try {
      const indexes = usesConfiguredSources
        ? await loadConfiguredMatchIndexes(searchState.selectedSource, searchState.selectedMake)
        : await Promise.all(scopeDirectories.map(loadDirectoryIndex));

      if (token !== searchLoadToken) {
        return;
      }

      const records = [];
      const columns = [];
      indexes.forEach((index) => {
        records.push(...index.records);
        index.columns.forEach((column) => {
          if (column && !columns.includes(column)) {
            columns.push(column);
          }
        });
      });
      setSearchIndex(scopeKey, records, columns);
    } catch (error) {
      if (token !== searchLoadToken) {
        return;
      }
      searchState.status = "error";
      searchState.message = scopeDirectories.length === 1
        ? "Waiting for page previews to finish loading..."
        : "Unable to load all folders for global search.";
      updateLazyMakeControl();
      updateSearchControls();
      updateSearchResults();
      if (scopeDirectories.length === 1) {
        scheduleFrameSearchIndex();
      }
    }
  }

  async function loadDirectoryIndex(directory) {
    if (directoryIndexes.has(directory.name)) {
      return directoryIndexes.get(directory.name);
    }

    const pages = await Promise.all(directory.files.map(async (file) => {
      const response = await fetch(pagePath(directory, file));
      if (!response.ok) {
        throw new Error(`Cannot load ${directory.name}/${file}`);
      }
      return { file, html: await response.text() };
    }));

    const parser = new DOMParser();
    const records = [];
    const columns = [];
    pages.forEach((page) => {
      const doc = parser.parseFromString(page.html, "text/html");
      records.push(...extractRecords(doc, page.file, directory, columns));
    });
    await enrichRecordsFromSource(directory, records);

    const index = { records, columns };
    directoryIndexes.set(directory.name, index);
    return index;
  }

  function scheduleFrameSearchIndex() {
    window.clearTimeout(frameSearchTimer);
    frameSearchTimer = window.setTimeout(() => {
      const fallbackDirectory = chartDirectories()[0] || directories[0];
      if (!fallbackDirectory || searchState.scopeKey !== fallbackDirectory.name) {
        return;
      }
      const records = [];
      const columns = [];
      app.querySelectorAll(".page-frame").forEach((frame) => {
        try {
          const file = frame.getAttribute("src").split("/").pop();
          if (frame.contentDocument) {
            records.push(...extractRecords(frame.contentDocument, file, fallbackDirectory, columns));
          }
        } catch (error) {
          // Some browsers block file previews from being inspected.
        }
      });
      if (records.length) {
        setSearchIndex(fallbackDirectory.name, records, columns);
      } else {
        searchState.status = "error";
        searchState.message = "Unable to read the preview pages in this browser.";
        updateSearchControls();
        updateSearchResults();
      }
    }, 120);
  }

  function setSearchIndex(scopeKey, records, columns, emptyMessage) {
    searchState.scopeKey = scopeKey;
    searchState.records = records;
    searchState.columns = columns;
    searchState.status = "ready";
    searchState.message = records.length
      ? `已按需索引 ${formatCount(records.length)} 条记录。`
      : (emptyMessage || "未读取到表格记录。");
    ensureSizeFieldState();
    if (pageMode !== "charts") {
      updateLazyMakeControl();
      updateSearchControls();
      updateSearchResults();
      return;
    }
    updateSearchControls();
    updateSearchResults();
  }

  async function enrichRecordsFromSource(directory, records) {
    try {
      const metadata = await loadDirectoryMetadata(directory);
      if (!metadata.inputPath) {
        return;
      }

      const tsvRows = await loadTsvRows(metadata.inputPath);
      let matchingRows = tsvRows.filter((row) => !metadata.storeValue || cleanField(row["店铺"]) === metadata.storeValue);
      if (!matchingRows.length && metadata.storeValue) {
        matchingRows = tsvRows;
      }

      if (metadata.profile !== "pickup") {
        const lookup = new Map();
        matchingRows.forEach((row) => {
          const key = nonPickupKey({
            make: row.MAKE,
            model: row["SHORT-MODEL"] || row.MODEL,
            year: row.YEAR,
            type: row.TYPE || row["LONG-TYPE"] || row.CONST,
            size: row.SIZE
          });
          if (!lookup.has(key)) {
            lookup.set(key, []);
          }
          lookup.get(key).push(row);
        });

        records.forEach((record) => {
          const row = (lookup.get(nonPickupKey({
            make: record.make,
            model: record.model,
            year: record.values.YEAR,
            type: record.values.TYPE,
            size: record.values.SIZE
          })) || []).shift() || matchingRows.find((candidate) => (
            sameText(candidate.MAKE, record.make)
              && sameText(candidate["SHORT-MODEL"] || candidate.MODEL, record.model)
              && cleanField(candidate.YEAR) === cleanField(record.values.YEAR)
              && cleanField(candidate.SIZE) === cleanField(record.values.SIZE)
          ));

          if (row) {
            record.construct = cleanField(row.CONST || row.CONSTRUCT);
            record.searchText = `${record.searchText} ${Object.values(row).join(" ")}`;
          }
        });
        return;
      }

      const lookup = new Map();
      matchingRows.forEach((row) => {
        const key = pickupKey({
          title: row.TITLE,
          year: row.YEAR,
          cab: row["SHORT-CAB"] || row.CAB,
          bed: row.BED,
          size: row.SIZE
        });
        if (!lookup.has(key)) {
          lookup.set(key, []);
        }
        lookup.get(key).push(row);
      });

      records.forEach((record) => {
        const row = (lookup.get(pickupKey({
          title: record.title,
          year: record.values.YEAR,
          cab: record.values.CAB,
          bed: record.values.BED,
          size: record.values.SIZE
        })) || []).shift() || matchingRows.find((candidate) => (
          sameText(candidate.TITLE, record.title)
            && cleanField(candidate.YEAR) === cleanField(record.values.YEAR)
            && cleanField(candidate.SIZE) === cleanField(record.values.SIZE)
        )) || matchingRows.find((candidate) => (
          sameText(candidate.TITLE, record.title) && cleanField(candidate.YEAR) === cleanField(record.values.YEAR)
        ));

        if (!row) {
          record.searchText = `${record.title} ${record.description}`;
          return;
        }

        record.make = cleanField(row.MAKE);
        record.model = cleanField(row.MODEL || row["SHORT-MODEL"]);
        record.construct = cleanField(row.CONST || row.CONSTRUCT);
        record.cab = cleanField(row.CAB);
        record.bed = cleanField(row.BED);
        record.type = cleanField(row.TYPE || row["LONG-TYPE"] || row.VERSION || row.CONST);
        record.searchText = Object.values(row).join(" ");
      });
    } catch (error) {
      records.forEach((record) => {
        record.searchText = `${record.title} ${record.description}`;
      });
    }
  }

  async function loadDirectoryMetadata(directory) {
    if (directoryMetadata.has(directory.name)) {
      return directoryMetadata.get(directory.name);
    }

    const metadata = { profile: "", inputPath: "", storeValue: "" };
    try {
      const response = await fetch(`${config.basePath}${directory.name}/output_generation.log`);
      if (response.ok) {
        const log = await response.text();
        metadata.profile = (log.match(/Profile:\s*([^\r\n]+)/) || [])[1]?.trim() || "";
        metadata.inputPath = ((log.match(/-\s*(data[^\r\n]+)/) || [])[1] || "").trim().replace(/\\/g, "/");
        metadata.storeValue = (log.match(/Store value:\s*([^\r\n]+)/) || [])[1]?.trim() || "";
      }
    } catch (error) {
      // The generated HTML is still searchable without source metadata.
    }
    const tags = sourceTags(directory.name);
    if (!metadata.profile && tags.includes("pick")) {
      metadata.profile = "pickup";
    }
    if (!metadata.inputPath && tags.includes("pick")) {
      metadata.inputPath = "data/input/0630/pick.tsv";
    }
    if (!metadata.storeValue && tags.includes("pick")) {
      metadata.storeValue = directory.name.split(/[\\/]/)[0].replace(/^pick-/, "");
    }
    directoryMetadata.set(directory.name, metadata);
    return metadata;
  }

  async function loadTsvRows(path) {
    if (tsvIndexes.has(path)) {
      return tsvIndexes.get(path);
    }

    const response = await fetch(path);
    if (!response.ok) {
      throw new Error(`Cannot load ${path}`);
    }
    const rows = parseTsv(await response.text());
    tsvIndexes.set(path, rows);
    return rows;
  }

  function updateSearchControls() {
    const makeSelect = app.querySelector('[data-search-field="make"]');
    const modelSelect = app.querySelector('[data-search-field="model"]');
    const yearSelect = app.querySelector('[data-search-field="year"]');
    const constructSelect = app.querySelector('[data-search-field="construct"]');
    const cabSelect = app.querySelector('[data-search-field="cab"]');
    const bedSelect = app.querySelector('[data-search-field="bed"]');
    if (!makeSelect || !modelSelect || !yearSelect || !constructSelect || !cabSelect || !bedSelect) {
      return;
    }

    const ready = searchState.status === "ready";
    const makeRecords = queryFilteredRecords();
    const sourceRecords = makeRecords.filter((record) => !searchState.selectedSource || sourceFilterValue(record) === searchState.selectedSource);
    const modelRecords = sourceRecords.filter((record) => !searchState.selectedMake || sameText(record.make, searchState.selectedMake));
    const yearRecords = modelRecords.filter((record) => !searchState.selectedModel || record.model === searchState.selectedModel);
    const constructRecords = yearRecords.filter((record) => !searchState.selectedYear || record.years.includes(Number(searchState.selectedYear)));
    const cabRecords = constructRecords.filter((record) => !searchState.selectedConstruct || filterAtoms(record, "construct").includes(searchState.selectedConstruct));
    const bedRecords = cabRecords.filter((record) => !searchState.selectedCab || filterAtoms(record, "cab").includes(searchState.selectedCab));

    fillSelect(makeSelect, "All makes", unique(sourceRecords.map((record) => record.make)), searchState.selectedMake);
    fillSelect(modelSelect, "All models", unique(modelRecords.map((record) => record.model)), searchState.selectedModel);
    fillSelect(yearSelect, "All years", uniqueYears(yearRecords), searchState.selectedYear);
    fillSelect(constructSelect, filterConfig("construct").empty_label, unique(constructRecords.flatMap((record) => filterAtoms(record, "construct"))), searchState.selectedConstruct);
    fillSelect(cabSelect, filterConfig("cab").empty_label, unique(cabRecords.flatMap((record) => filterAtoms(record, "cab"))), searchState.selectedCab);
    fillSelect(bedSelect, filterConfig("bed").empty_label, unique(bedRecords.flatMap((record) => filterAtoms(record, "bed"))), searchState.selectedBed);

    makeSelect.disabled = !ready;
    modelSelect.disabled = !ready || !modelRecords.length;
    yearSelect.disabled = !ready || !yearRecords.length;
    constructSelect.disabled = !ready || !constructRecords.length;
    cabSelect.disabled = !ready || !cabRecords.length;
    bedSelect.disabled = !ready || !bedRecords.length;
  }

  function updateSearchResults() {
    const summary = app.querySelector(".search-summary");
    const results = app.querySelector(".search-results");
    if (!summary || !results) {
      return;
    }

    // 加载状态与视图标在结果摘要上（idle/loading/ready/error），供验收脚本等待（tests/acceptance/size_match_browser.cjs）
    summary.dataset.status = searchState.status;
    summary.dataset.viewMode = searchState.tableMode;
    syncEvolutionSelectionScope();
    if (searchState.status === "loading" || searchState.status === "error") {
      summary.textContent = searchState.message;
      results.innerHTML = "";
      updateEvolutionToolbar([]);
      return;
    }

    const queryRecords = queryFilteredRecords();
    if (!queryRecords.length) {
      summary.textContent = searchState.query.trim() ? `${vehicleCodeHint()}未找到匹配记录。` : searchState.message;
      results.innerHTML = "";
      updateEvolutionToolbar([]);
      return;
    }

    const matches = sortSizeRows(getSearchMatches());
    const limit = pageSizeFor(matches.length);
    const maxPage = Math.max(1, Math.ceil(matches.length / limit));
    searchState.resultPage = Math.min(maxPage, Math.max(1, searchState.resultPage || 1));
    const start = (searchState.resultPage - 1) * limit;
    const visibleMatches = matches.slice(start, start + limit);
    evolutionPageRecords = new Map(visibleMatches.filter((record) => record.recordKey).map((record) => [record.recordKey, record]));
    evolutionOutlineGroups = [];
    const summaryText = vehicleCodeHint() + ignoredTokenHint() + (matches.length > visibleMatches.length
      ? `匹配结果：${formatCount(matches.length)} 条记录，当前第 ${formatCount(searchState.resultPage)} / ${formatCount(maxPage)} 页。`
      : `匹配结果：${formatCount(matches.length)} 条记录。`);
    renderSearchSummary(summary, summaryText, matches);
    updateActiveFilterChips();
    bindActiveFilterChips();
    // 重绘前记下表格与筛选弹层的滚动位置：打开/修改筛选、排序时表格不跳回左上角；翻页时回到顶部
    const previousWrap = results.querySelector(".size-results-wrap");
    const previousScroll = previousWrap ? [previousWrap.scrollLeft, searchState.resetResultScroll ? 0 : previousWrap.scrollTop] : null;
    const optionScroll = results.querySelector(".header-option-scroll")?.scrollTop || 0;
    searchState.resetResultScroll = false;
    results.innerHTML = searchState.resultView === "outline"
      ? renderResultsOutline(visibleMatches, matches.length, maxPage)
      : renderResultsTable(visibleMatches, matches.length, maxPage);
    const wrap = results.querySelector(".size-results-wrap");
    if (wrap && previousScroll) [wrap.scrollLeft, wrap.scrollTop] = previousScroll;
    const optionList = results.querySelector(".header-option-scroll");
    if (optionList) optionList.scrollTop = optionScroll;
    bindResultColumnResizers();
    bindSizeLinkedRows();
    bindSizeHeaderFilterPopovers();
    bindSizeTableFilters();
    bindSizeReferenceHovers();
    bindShapeHovers();
    bindSourceToggles();
    updateEvolutionToolbar(matches);
    bindEvolutionResultControls();
  }

  function getSearchMatches() {
    return queryFilteredRecords().filter((record) => {
      if (searchState.selectedMake && !sameText(record.make, searchState.selectedMake)) {
        return false;
      }
      if (searchState.selectedSource && sourceFilterValue(record) !== searchState.selectedSource) {
        return false;
      }
      if (searchState.selectedSize && !sameText(resultColumnValue(record, "SIZE") || record.size, searchState.selectedSize)) return false;
      if (searchState.selectedModel && record.model !== searchState.selectedModel) {
        return false;
      }
      if (searchState.selectedYear && !record.years.includes(Number(searchState.selectedYear))) {
        return false;
      }
      if (searchState.selectedConstruct && !filterAtoms(record, "construct").includes(searchState.selectedConstruct)) {
        return false;
      }
      if (searchState.selectedCab && !filterAtoms(record, "cab").includes(searchState.selectedCab)) {
        return false;
      }
      if (searchState.selectedBed && !filterAtoms(record, "bed").includes(searchState.selectedBed)) {
        return false;
      }
      for (const [key, value] of Object.entries(searchState.columnFilters)) {
        if (!value) continue;
        if (Array.isArray(value)) {
          if (!value.length) continue;
          const recordValues = sizeColumnFilterValues(record, key);
          if (!value.some((item) => recordValues.includes(item))) return false;
        } else if (typeof value === "object") {
          const numeric = Number(sizeColumnFilterValue(record, key));
          if (!Number.isFinite(numeric)) return false;
          if (value.min && numeric < Number(value.min)) return false;
          if (value.max && numeric > Number(value.max)) return false;
        } else if (!sizeColumnFilterValues(record, key).includes(value)) return false;
      }
      return true;
    });
  }

  function configuredMatchPath() {
    return viewConfig.excel_source?.match_data_path || defaultViewConfig.excel_source.match_data_path;
  }

  async function loadConfiguredMatchManifest() {
    return loadMatchManifest(configuredMatchPath());
  }

  async function loadMatchManifest(path) {
    if (!configuredMatchManifestPromises.has(path)) {
      configuredMatchManifestPromises.set(path, fetch(path, { cache: "no-cache" }).then(async (response) => {
        if (!response.ok) {
          throw new Error(`Cannot load ${path}`);
        }
        const payload = await response.json();
        matchDataOrigins.set(path, payload.origin || null);
        if (payload.shape_labels) shapeLabels = { ...shapeLabels, ...payload.shape_labels };
        return { path, payload };
      }).catch((error) => {
        configuredMatchManifestPromises.delete(path);
        throw error;
      }));
    }
    return configuredMatchManifestPromises.get(path);
  }

  function updateLazyMakeControl() {
    const makeSelect = app.querySelector("[data-lazy-make]");
    if (!makeSelect) return;
    makeSelect.innerHTML = `
      <option value="">全部 MAKE</option>
      ${searchState.availableMakes.map((make) => `<option value="${escapeHtml(make)}">${escapeHtml(make)}</option>`).join("")}
    `;
    makeSelect.value = searchState.selectedMake;
    makeSelect.disabled = searchState.status === "loading" || !searchState.availableMakes.length;
    app.querySelectorAll("[data-vehicle-kind], [data-lazy-source]").forEach((control) => {
      control.disabled = searchState.status === "loading";
    });
    const sizeSelect = app.querySelector("[data-lazy-size]");
    if (sizeSelect) {
      const kindRecords = searchState.records.filter((record) => recordKind(record) === searchState.vehicleKind);
      const sizes = unique(kindRecords.map((record) => resultColumnValue(record, "SIZE") || record.size).filter(Boolean));
      sizeSelect.innerHTML = `<option value="">全部尺码</option>${sizes.map((size) => `<option value="${escapeHtml(size)}">${escapeHtml(size)}</option>`).join("")}`;
      sizeSelect.value = searchState.selectedSize;
      sizeSelect.disabled = searchState.status !== "ready" || !sizes.length;
    }
  }

  function updateSourceOutlineState() {
    app.querySelectorAll("[data-sidebar-source]").forEach((button) => {
      const active = button.dataset.sidebarSource === sourceGroup(searchState.selectedSource);
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function resolveManifestDataPath(manifestPath, recordsPath) {
    return new URL(recordsPath, new URL(manifestPath, document.baseURI)).href;
  }

  async function fetchJsonWithRetry(url, attempts = 3) {
    let lastError;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`Cannot load ${url}`);
        }
        return await response.json();
      } catch (error) {
        lastError = error;
        await new Promise((resolve) => window.setTimeout(resolve, 200 * (attempt + 1)));
      }
    }
    throw lastError;
  }

  async function loadConfiguredMatchSource(manifestPath, payload, source, configured, makeGroup) {
    const shard = makeGroup || source;
    const cacheKey = `${manifestPath}|${source.name}|${shard.records_path || "inline"}`;
    if (!configuredMatchIndexPromises.has(cacheKey)) {
      const promise = (async () => {
        let sourcePayload = shard;
        if (shard.records_path) {
          const recordsPath = resolveManifestDataPath(manifestPath, shard.records_path);
          sourcePayload = await fetchJsonWithRetry(recordsPath);
        }

        const sourceName = sourcePayload.name || source.name;
        if (sourceName !== source.name) {
          throw new Error(`Configured source mismatch: expected ${source.name}, received ${sourceName}`);
        }
        if (makeGroup && cleanField(sourcePayload.make) !== cleanField(makeGroup.make)) {
          throw new Error(`Configured make mismatch: expected ${makeGroup.make}, received ${sourcePayload.make}`);
        }
        // 一份分片两种视图：full = A0 全量行，compressed = A1 压缩记录（来源行按 refs 从全量行还原）
        const views = expandMatchShard({ ...sourcePayload, records: sourcePayload.records || source.records || [] });
        const label = `${source.name}${makeGroup ? ` / ${makeGroup.make}` : ""}`;
        if (shard.record_count !== undefined && Number(shard.record_count) !== views.full.records.length) {
          throw new Error(`Record count mismatch for ${label}`);
        }
        if (views.compressed && shard.compressed_count !== undefined && Number(shard.compressed_count) !== views.compressed.records.length) {
          throw new Error(`Compressed record count mismatch for ${label}`);
        }
        const prepare = (view, fallbackColumns) => {
          const columns = csvList(configured.columns).length ? csvList(configured.columns) : (view.columns.length ? view.columns : fallbackColumns);
          const records = view.records.map((record) => ({
            ...record,
            title: record.title || [record.make, record.model].filter(Boolean).join(" "),
            description: record.description || "",
            directory: source.name,
            source: source.label || configured.label || source.name,
            sourceTags: [String(source.name || "").toLowerCase()],
            file: record.file || ""
          }));
          // 可视化与跨页选择用的稳定身份：在完整分片（source + kind + MAKE）上分配，不依赖分页行号
          if (evolutionData) evolutionData.assignRecordKeys(records, source.name);
          return { records, columns };
        };
        return {
          full: prepare(views.full, source.columns || payload.columns || []),
          compressed: views.compressed ? prepare(views.compressed, source.compressed_columns || []) : null
        };
      })().catch((error) => {
        configuredMatchIndexPromises.delete(cacheKey);
        throw error;
      });
      configuredMatchIndexPromises.set(cacheKey, promise);
    }
    return configuredMatchIndexPromises.get(cacheKey);
  }

  async function loadConfiguredMatchIndexes(selectedSource, selectedMake) {
    const { path, payload } = await loadConfiguredMatchManifest();
    const configuredSources = viewConfig.match_sources || [];
    const configuredNames = configuredSources.map((source) => source.name);
    const sources = (payload.sources || []).filter((source) => (
      (!configuredNames.length || configuredNames.includes(source.name))
      && (!selectedSource || source.name === selectedSource)
    ));

    const usesMakeGroups = sources.length > 0 && sources.every((source) => Array.isArray(source.make_groups));
    if (usesMakeGroups) {
      const kindGroups = (source) => source.make_groups.filter((group) => !group.kind || group.kind === searchState.vehicleKind);
      searchState.availableMakes = uniqueInOrder(
        sources.flatMap((source) => kindGroups(source).map((group) => cleanField(group.make)).filter(Boolean))
      ).sort((left, right) => left.localeCompare(right));
      const resolvedMake = cleanField(selectedMake);
      searchState.selectedMake = resolvedMake;
      searchState.requiresMakeSelection = false;

      return Promise.all(sources.flatMap((source) => {
        const configured = configuredSources.find((item) => item.name === source.name) || {};
        return kindGroups(source)
          .filter((group) => !resolvedMake || cleanField(group.make) === resolvedMake)
          .map((group) => loadConfiguredMatchSource(path, payload, source, configured, group).then(currentView));
      }));
    }

    searchState.requiresMakeSelection = false;
    return Promise.all(sources.map((source) => {
      const configured = configuredSources.find((item) => item.name === source.name) || {};
      return loadConfiguredMatchSource(path, payload, source, configured).then(currentView);
    }));
  }

  // 当前视图的记录与列：压缩表视图要求分片带压缩记录（旧格式数据只有全量行）
  function currentView(index) {
    if (searchState.tableMode === "compressed" && tableModes().length) {
      if (!index.compressed) throw new Error("数据清单没有压缩表视图");
      return index.compressed;
    }
    return index.full;
  }

  function queryFilteredRecords() {
    const tokens = searchQueryTokens(searchState.query);
    const kindRecords = searchState.records.filter((record) => recordKind(record) === searchState.vehicleKind);
    if (!tokens.length || !kindRecords.length) {
      ignoredSearchTokens = [];
      return kindRecords;
    }

    // 逐词收窄：无映射的词（如 short bed）忽略并提示，不把结果清空
    const result = filterBySearchTokens(kindRecords, tokens, recordMatchesToken);
    ignoredSearchTokens = result.ignored;
    return result.records;
  }

  function ignoredTokenHint() {
    return ignoredSearchTokens.length ? `未匹配的词已忽略：${ignoredSearchTokens.join("、")}；` : "";
  }

  // 非皮卡没有驾驶室/货箱，表格与表格设置都不显示 CAB、BED
  function hiddenForVehicleKind(column) {
    return searchState.vehicleKind === "nonpick" && (sameColumn(column, "CAB") || sameColumn(column, "BED"));
  }

  function renderResultsTable(records, totalCount, maxPage) {
    if (!records.length) {
      return '<div class="empty-results">No rows match the current selection.</div>';
    }

    renderedResultRecords = records;
    const columns = resultColumns(records);
    // 压缩记录：CODE 放首列并作为展开来源车型的开关（无 CODE 列时开关在 MAKE）；
    // 压缩表：SHAPE 属于来源车型（各年份），只在本页有展开的记录时显示该列，且只填在来源行；全量表每行就是一个车型年份段，直接显示
    const codeColumn = columns.find((column) => sameColumn(column, "CODE"));
    const showShape = searchState.tableMode === "full" || records.some((record) => recordSources(record).length && expandedSourceRecords.has(record));
    const otherColumns = columns.filter((column) => column !== codeColumn && (showShape || !sameColumn(column, "SHAPE")));
    const tableColumns = [
      ...(codeColumn ? [{ key: codeColumn, label: codeColumn }] : []),
      { key: "MAKE", label: "MAKE" },
      ...otherColumns.map((column) => ({
        key: column,
        label: column,
        dimension: isDimensionColumn(column),
        size: isSizeColumn(column)
      }))
    ];
    const toggleKey = sourceToggleKey(tableColumns);
    tableColumns.forEach((column, index) => {
      column.toggle = column.key === toggleKey && records.some((record) => recordSources(record).length);
      column.width = autoColumnWidth(column.key, column.label, records, column.toggle);
      // 右半部分的列（含右侧固定列）弹层向左展开，避免超出表格
      column.alignRight = index >= tableColumns.length / 2;
    });
    if (evolutionOn()) {
      tableColumns.unshift({ key: EVOLUTION_COLUMN, label: "", evolution: true, width: "36px" });
    }
    fitColumnsToContainer(tableColumns, records);
    const tableWidth = resultTableWidth(tableColumns);
    return `
      <div class="results-table-wrap size-results-wrap">
        <table class="results-table size-results-table table-font-${escapeHtml(searchState.tableFontSize)} ${searchState.dimensionUnit === "in" ? "dimension-theme-blue" : "dimension-theme-yellow"}" style="--result-table-width: ${tableWidth}px">
          <colgroup>
            ${tableColumns.map((column) => {
              const width = searchState.columnWidths[column.key] || column.width;
              return `<col data-col-key="${escapeHtml(column.key)}"${width ? ` style="width: ${escapeHtml(width)}"` : ""}>`;
            }).join("")}
          </colgroup>
          <thead>
            <tr>
              ${tableColumns.map((column) => column.evolution ? evolutionHeaderMarkup(records) : `
                <th class="${resultHeaderClass(column)}${searchState.openFilter === column.key ? " is-filter-open" : ""}" data-col-key="${escapeHtml(column.key)}">
                  ${sizeHeaderLabelMarkup(column)}
                  ${sizeHeaderFilterMarkup(column, tableColumns)}
                  <span class="col-resizer" data-col-key="${escapeHtml(column.key)}" title="拖动调整列宽" aria-hidden="true"></span>
                </th>
              `).join("")}
            </tr>
          </thead>
          <tbody>
            ${records.map((record, index) => resultRowMarkup(record, index, tableColumns)).join("")}
          </tbody>
        </table>
      </div>
      <div class="result-limit-bar">
        <span>第 ${formatCount(searchState.resultPage)} / ${formatCount(maxPage)} 页 · 显示 ${formatCount(records.length)} / ${formatCount(totalCount)}</span>
        <button class="result-page-button" type="button" data-result-page="prev" data-max-page="${maxPage}" ${searchState.resultPage <= 1 ? "disabled" : ""}>上一页</button>
        <button class="result-page-button" type="button" data-result-page="next" data-max-page="${maxPage}" ${searchState.resultPage >= maxPage ? "disabled" : ""}>下一页</button>
        <label>
          <span>显示数</span>
          <select class="search-select result-limit-select" data-result-limit>
            ${[200, 500].map((value) => `<option value="${value}"${searchState.resultLimit === value ? " selected" : ""}>${value}</option>`).join("")}
          </select>
        </label>
      </div>
    `;
  }

  // 记录带 sources（A1 压缩来源：该压缩记录覆盖的 A0 全量表行）时，点首列 CODE（无 CODE 列时 MAKE）展开/收回来源车型各年份长宽高与车形
  function resultRowMarkup(record, index, tableColumns) {
    const sources = recordSources(record);
    const expanded = sources.length > 0 && expandedSourceRecords.has(record);
    const cells = tableColumns.map((column) => {
      if (column.evolution) return evolutionCellMarkup(record);
      if (column.toggle && sources.length) return sourceToggleCellMarkup(record, column, index, sources.length, expanded);
      // 记录本身不显示 SHAPE（各年份车形在展开的来源行里）
      if (sources.length && sameColumn(column.key, "SHAPE")) return "<td></td>";
      return resultCellMarkup(record, column);
    }).join("");
    const keyAttr = evolutionOn() && record.recordKey ? ` data-record-key="${escapeHtml(record.recordKey)}"` : "";
    const row = `<tr class="copyable-result-row${sources.length ? " has-sources" : ""}${expanded ? " is-expanded" : ""}"${keyAttr}>${cells}</tr>`;
    if (!expanded) return row;
    return row + sources.map((source, position) => sourceRowMarkup(record, source, position === sources.length - 1, tableColumns)).join("");
  }

  function recordSources(record) {
    return Array.isArray(record.sources) ? record.sources : [];
  }

  function sourceToggleKey(tableColumns) {
    return (tableColumns.find((column) => sameColumn(column.key, "CODE")) || { key: "MAKE" }).key;
  }

  // 开关显示 CODE（EU/RU 没有 CODE 时显示 —），无 CODE 列时显示 MAKE
  function sourceToggleCellMarkup(record, column, index, count, expanded) {
    const hint = expanded ? "收回来源车型" : `展开 ${count} 条来源车型的各年份长宽高与车形`;
    const isCode = sameColumn(column.key, "CODE");
    const label = isCode ? cleanField(resultColumnValue(record, column.key)) : record.make;
    return `<td class="source-toggle-cell${isCode ? " code-cell" : ""}"><button class="source-toggle" type="button" data-source-toggle="${index}" aria-expanded="${expanded ? "true" : "false"}" title="${escapeHtml(hint)}"><span class="source-toggle-icon" aria-hidden="true"></span><strong class="source-toggle-make${label ? "" : " is-empty"}">${escapeHtml(label || "—")}</strong><em>${count}</em></button></td>`;
  }

  // 来源行按普通记录渲染（同列、同单位换算、点击复制车型信息/长宽高），CODE、销量、SIZE 留空
  function sourceRowMarkup(record, source, last, tableColumns) {
    const item = {
      ...record, model: source.MODEL, year: source.YEAR, construct: source.TYPE, type: source.TYPE, cab: source.CAB, bed: source.BED, sources: [],
      values: { ...source, MAKE: record.make, CONST: source.TYPE, SOURCE: record.values.SOURCE }
    };
    const cells = tableColumns.map((column) => {
      if (column.toggle) return `<td class="source-branch-cell" aria-hidden="true">${last ? "└" : "├"}</td>`;
      if (column.key === "MAKE") return "<td></td>";
      if (column.size) return '<td class="size-sticky-col size-sticky-size source-size-cell"></td>';
      if (column.dimension) return sourceDimensionCellMarkup(record, item, column);
      if (isSalesTotalColumn(column.key)) return "<td></td>";
      return resultCellMarkup(item, column);
    }).join("");
    // 来源行对应的 A0 历史 recordKey（不能用 item：它继承了压缩记录自身的 recordKey）
    const historyAttr = evolutionOn() ? ` data-history-key="${escapeHtml(evolutionData.recordKeyOf({ values: source }, recordSourceName(record)))}"` : "";
    return `<tr class="source-detail-row${last ? " is-last-source" : ""}" title="${escapeHtml(source["DIMENSION-ID"] || "")}"${historyAttr}>${cells}</tr>`;
  }

  function sourceDimensionCellMarkup(record, item, column) {
    const value = resultColumnValue(item, column.key);
    const isMax = Boolean(value) && Number(value) === Number(resultColumnValue(record, column.key));
    return `<td class="dimension-cell size-dimension-cell size-sticky-col ${sizeStickyClass(column.key)} dimension-copy-target${isMax ? " is-source-max" : ""}" tabindex="0" data-copy-text="${escapeHtml(copyDimensionsForRecord(item))}" title="${isMax ? "该记录的最大值，" : ""}点击复制长宽高"><strong>${escapeHtml(dimensionDisplay(column.key, value) || "-")}</strong></td>`;
  }

  function bindSourceToggles() {
    app.querySelectorAll("[data-source-toggle]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const record = renderedResultRecords[Number(button.dataset.sourceToggle)];
        if (!record) return;
        if (expandedSourceRecords.has(record)) expandedSourceRecords.delete(record);
        else expandedSourceRecords.add(record);
        updateSearchResults();
        app.querySelector(`[data-source-toggle="${button.dataset.sourceToggle}"]`)?.focus({ preventScroll: true });
      });
    });
  }

  // ---------- 车型尺寸演变可视化入口（size-evolution.js） ----------

  // 视图、source 或类别切换后，已选记录不再属于当前数据范围（压缩记录与全量行的 recordKey 不同），清空
  function syncEvolutionSelectionScope() {
    if (!evolutionOn()) return;
    const scope = `${searchState.tableMode}|${searchState.selectedSource}|${searchState.vehicleKind}`;
    if (scope !== evolutionSelectionScope) {
      evolutionSelectionScope = scope;
      evolutionSelection.clear();
    }
  }

  function evolutionModelKey(record) {
    return evolutionData.modelKeyForRecord(record, recordSourceName(record));
  }

  // 压缩表视图的记录是 A1 压缩记录，可视化历史是 A0 全量行：车型、配置与 recordKey 都按压缩记录覆盖的来源行（产线 + DIMENSION-ID）计算，
  // 与历史分片一一对应（压缩记录可能合并多个版本/年份段，不能直接用记录本身的字段）
  function evolutionRefs(record) {
    const sources = recordSources(record);
    if (!sources.length) return [record];
    return sources.map((source) => ({
      make: record.make, model: source.MODEL || record.model, kind: record.kind, directory: record.directory,
      values: { ...source, MAKE: record.make }
    }));
  }

  function evolutionHistoryKeys(record) {
    return evolutionRefs(record).map((ref) => evolutionData.recordKeyOf(ref, recordSourceName(ref)));
  }

  function evolutionRecordLabel(record) {
    return [cleanField(resultColumnValue(record, "YEAR") || record.year), record.make, record.model, cleanField(resultColumnValue(record, "版本")), cleanField(resultColumnValue(record, "TYPE"))].filter(Boolean).join(" ");
  }

  function evolutionHeaderMarkup(records) {
    const keys = records.map((record) => record.recordKey).filter(Boolean);
    const selected = keys.filter((key) => evolutionSelection.has(key)).length;
    return `<th class="evolution-heading" data-col-key="${EVOLUTION_COLUMN}"><label title="选择本页 ${formatCount(keys.length)} 条记录（不是全部搜索结果）"><input type="checkbox" class="evolution-select" data-evolution-page-select ${keys.length && selected === keys.length ? "checked" : ""} aria-label="选择本页"></label></th>`;
  }

  // 每行只有选择框：统一勾选后点「车型可视化」进入
  function evolutionCellMarkup(record) {
    if (!record.recordKey) return '<td class="evolution-cell"></td>';
    const label = escapeHtml(evolutionRecordLabel(record));
    return `<td class="evolution-cell"><input type="checkbox" class="evolution-select" data-evolution-select="${escapeHtml(record.recordKey)}" ${evolutionSelection.has(record.recordKey) ? "checked" : ""} aria-label="选择 ${label}"></td>`;
  }

  // 大纲 MODEL 组：一次勾选本页该车型的全部记录
  function evolutionGroupSelectMarkup(records) {
    const keys = records.map((record) => record.recordKey).filter(Boolean);
    if (!keys.length) return "";
    const index = evolutionOutlineGroups.push(keys) - 1;
    const selected = keys.filter((key) => evolutionSelection.has(key)).length;
    const label = escapeHtml(`${records[0].make} ${records[0].model}`);
    return `<label class="outline-group-select" title="勾选本页 ${label} 的 ${formatCount(keys.length)} 条记录"><input type="checkbox" class="evolution-select" data-evolution-group="${index}" ${selected === keys.length ? "checked" : ""} aria-label="选择本页 ${label} 的全部记录"></label>`;
  }

  function evolutionOutlineSelectMarkup(record, depth) {
    if (!record.recordKey) return "";
    const label = escapeHtml(evolutionRecordLabel(record));
    return `<div class="outline-tree-leaf outline-evolution-leaf" style="--outline-leaf-depth: ${depth}"><label class="outline-evolution-select"><input type="checkbox" class="evolution-select" data-evolution-select="${escapeHtml(record.recordKey)}" ${evolutionSelection.has(record.recordKey) ? "checked" : ""} aria-label="选择 ${label}">选择</label></div>`;
  }

  function updateEvolutionToolbar(matches) {
    if (!evolutionOn()) return;
    evolutionMatches = matches;
    const toolbar = app.querySelector("[data-evolution-toolbar]");
    if (!toolbar) return;
    const ready = searchState.status === "ready";
    toolbar.hidden = !ready;
    if (!ready) return;
    const matchKeys = new Set(matches.map((record) => record.recordKey));
    const outside = Array.from(evolutionSelection.keys()).filter((key) => !matchKeys.has(key)).length;
    const count = evolutionSelection.size;
    const title = count
      ? "可视化已勾选记录所属车型的完整历史（勾选的配置优先显示）"
      : "未勾选时：当前结果只有一个车型直接打开，否则先选择车型";
    const markup = `
      <button type="button" class="evolution-launch${count ? " has-selection" : ""}" data-evolution-launch ${count || matches.length ? "" : "disabled"} title="${title}">${count ? `车型可视化（已选 ${formatCount(count)}）` : "车型可视化"}</button>
      ${outside ? `<span class="evolution-selection-note">包含 ${formatCount(outside)} 条当前筛选外记录</span>` : ""}
      ${count ? '<button type="button" class="evolution-clear" data-evolution-clear>清空</button>' : ""}
    `;
    // 内容不变时保留原按钮元素：结果区重绘（字体加载、窗口缩放）不打断正在进行的点击
    if (toolbar.dataset.markup === markup) return;
    toolbar.dataset.markup = markup;
    toolbar.innerHTML = markup;
    toolbar.querySelector("[data-evolution-launch]")?.addEventListener("click", (event) => launchEvolution(event.currentTarget));
    toolbar.querySelector("[data-evolution-clear]")?.addEventListener("click", () => {
      evolutionSelection.clear();
      refreshEvolutionSelectionUi();
      app.querySelector("[data-evolution-launch]")?.focus({ preventScroll: true });
    });
  }

  function setCheckboxState(input, keys) {
    const selected = keys.filter((key) => evolutionSelection.has(key)).length;
    input.checked = Boolean(keys.length) && selected === keys.length;
    input.indeterminate = selected > 0 && selected < keys.length;
  }

  // 选择变化只刷新选择框和工具栏，不重绘表格（保留滚动位置）
  function refreshEvolutionSelectionUi() {
    app.querySelectorAll("[data-evolution-select]").forEach((input) => {
      input.checked = evolutionSelection.has(input.dataset.evolutionSelect);
    });
    app.querySelectorAll("[data-evolution-group]").forEach((input) => {
      setCheckboxState(input, evolutionOutlineGroups[Number(input.dataset.evolutionGroup)] || []);
    });
    const pageSelect = app.querySelector("[data-evolution-page-select]");
    if (pageSelect) setCheckboxState(pageSelect, Array.from(evolutionPageRecords.keys()));
    updateEvolutionToolbar(evolutionMatches);
  }

  function toggleEvolutionRecords(keys, checked) {
    keys.forEach((key) => {
      const record = evolutionPageRecords.get(key);
      if (checked && record) evolutionSelection.set(key, record);
      else if (!checked) evolutionSelection.delete(key);
    });
    refreshEvolutionSelectionUi();
  }

  function bindEvolutionResultControls() {
    if (!evolutionOn()) return;
    const stop = (event) => event.stopPropagation();
    app.querySelectorAll("[data-evolution-select]").forEach((input) => {
      input.addEventListener("click", stop);
      input.addEventListener("change", () => toggleEvolutionRecords([input.dataset.evolutionSelect], input.checked));
    });
    app.querySelectorAll("[data-evolution-group]").forEach((input) => {
      input.addEventListener("click", stop);
      input.addEventListener("change", () => toggleEvolutionRecords(evolutionOutlineGroups[Number(input.dataset.evolutionGroup)] || [], input.checked));
    });
    const pageSelect = app.querySelector("[data-evolution-page-select]");
    if (pageSelect) {
      pageSelect.addEventListener("click", stop);
      pageSelect.addEventListener("change", () => toggleEvolutionRecords(Array.from(evolutionPageRecords.keys()), pageSelect.checked));
    }
    refreshEvolutionSelectionUi();
  }

  // 「车型可视化」：有勾选时打开已选记录所属车型的完整历史（已选配置优先）；
  // 未勾选时全部匹配结果（不限当前分页）只有一个车型就直接打开，否则打开车型选择器
  function launchEvolution(trigger) {
    if (evolutionSelection.size) {
      const refs = Array.from(evolutionSelection.values()).flatMap(evolutionRefs);
      openEvolutionView({
        modelKeys: uniqueInOrder(refs.map(evolutionModelKey)),
        anchorRecordKeys: refs.map((ref) => evolutionData.recordKeyOf(ref, recordSourceName(ref))),
        selectedConfigurationKeys: uniqueInOrder(refs.map((ref) => evolutionData.configurationKeyForRecord(ref, recordSourceName(ref)))),
        trigger
      });
      return;
    }
    const matches = getSearchMatches();
    const models = new Map();
    matches.forEach((record) => {
      uniqueInOrder(evolutionRefs(record).map(evolutionModelKey)).forEach((key) => {
        const parsed = evolutionData.parseModelKey(key);
        if (!models.has(key)) models.set(key, { key, make: parsed.make, model: parsed.model, count: 0 });
        models.get(key).count += 1;
      });
    });
    if (!models.size) return;
    if (models.size === 1) {
      openEvolutionView({ modelKeys: [...models.keys()], anchorRecordKeys: [], selectedConfigurationKeys: [], trigger });
      return;
    }
    window.SizeEvolution.openModelPicker({
      models: [...models.values()].sort((left, right) => compareValues(left.make, right.make) || compareValues(left.model, right.model)),
      source: searchState.selectedSource,
      sourceLabel: evolutionSourceLabel(),
      kind: searchState.vehicleKind,
      matchCount: matches.length,
      returnFocus: trigger,
      onConfirm: (modelKeys) => openEvolutionView({ modelKeys, anchorRecordKeys: [], selectedConfigurationKeys: [], trigger })
    });
  }

  function evolutionSourceLabel() {
    const configured = (viewConfig.match_sources || []).find((source) => source.name === searchState.selectedSource);
    return cleanField(configured?.label) || sourceLabel(searchState.selectedSource);
  }

  // 页面已选的 TYPE / CAB / BED / 版本 作为弹窗的初始配置选择（用户可在弹窗内调整）
  function evolutionInitialFilters() {
    const columnValues = (key) => arrayFilterValue(searchState.columnFilters[Object.keys(searchState.columnFilters).find((item) => sameColumn(item, key))]);
    return {
      type: uniqueInOrder([searchState.selectedConstruct, ...columnValues("TYPE")]),
      cab: uniqueInOrder([searchState.selectedCab, ...columnValues("CAB")]),
      bed: uniqueInOrder([searchState.selectedBed, ...columnValues("BED")]),
      version: uniqueInOrder(columnValues("版本"))
    };
  }

  function openEvolutionView({ modelKeys, anchorRecordKeys, selectedConfigurationKeys, trigger }) {
    // 打开时冻结当前筛选快照（完整 matches，不是当前分页）
    const currentMatchRecordKeys = getSearchMatches().flatMap(evolutionHistoryKeys);
    window.SizeEvolution.open({
      modelKeys,
      anchorRecordKeys,
      selectedConfigurationKeys,
      source: searchState.selectedSource,
      sourceLabel: evolutionSourceLabel(),
      kind: searchState.vehicleKind,
      unit: searchState.dimensionUnit,
      currentMatchRecordKeys,
      initialFilters: evolutionInitialFilters(),
      echartsSrc: evolutionConfig.echartsPath || "assets/vendor/echarts/echarts.min.js",
      lookupRule: (record) => exactSizeRule(record),
      sizeColor: (value) => sizeBackground(value),
      sizeTextColor: sizeTextColor(),
      returnFocus: trigger,
      loadModelHistory: loadEvolutionHistory,
      onLocateRecord: locateEvolutionRecord
    });
  }

  // 读数据清单（evolution.historyDataPath，与表格同一份 size-match-data.json），按车型涉及的 MAKE 取同产线 + kind 的分片，
  // 再按 MAKE/MODEL 精确收窄；不改检索状态
  async function loadEvolutionHistory(modelKeys) {
    const models = modelKeys.map(evolutionData.parseModelKey).filter(Boolean);
    if (!models.length) throw new Error("没有可视化的车型");
    const { path, payload } = await loadMatchManifest(evolutionConfig.historyDataPath || configuredMatchPath());
    const sourceName = models[0].source;
    const source = (payload.sources || []).find((item) => item.name === sourceName);
    if (!source) throw new Error(`数据清单中没有来源 ${sourceName}`);
    const configured = (viewConfig.match_sources || []).find((item) => item.name === source.name) || {};
    const shards = Array.isArray(source.make_groups)
      ? source.make_groups.filter((group) => models.some((model) => (!group.kind || group.kind === model.kind) && cleanField(group.make) === model.make))
      : [undefined];
    const indexes = await Promise.all(shards.map((group) => loadConfiguredMatchSource(path, payload, source, configured, group)));
    const keys = new Set(modelKeys);
    // 历史永远是全量行（同一份分片的 full 视图），与表格当前是压缩表还是全量表无关
    const records = indexes.flatMap((index) => index.full.records).filter((record) => keys.has(evolutionModelKey(record)));
    return {
      records,
      group: source.group,
      origin: { data: payload.origin || null, rules: sizeRulesOrigin, stores: storeGroupsOrigin }
    };
  }

  // 定位原记录：在当前完整结果里按稳定 ID 找到所在页并滚动到该行；「查看该车型记录」先明确切换到该车型范围
  async function locateEvolutionRecord(target) {
    if (target.switchToModel) {
      window.clearTimeout(globalSearchTimer);
      searchState.query = "";
      resetSearchFilters();
      searchState.selectedMake = target.make;
      searchState.selectedModel = target.model;
      const globalInput = app.querySelector(".global-search-input");
      if (globalInput) globalInput.value = "";
      await loadSearchIndex(currentSearchDirectories());
    }
    // target 是 A0 历史行：找到覆盖它的压缩记录，翻到所在页并展开来源行，定位到对应年份
    const matches = sortSizeRows(getSearchMatches());
    const index = matches.findIndex((record) => evolutionHistoryKeys(record).includes(target.recordKey));
    const feedbackAnchor = app.querySelector(".search-summary") || app;
    if (index < 0) {
      showCopyFeedback(feedbackAnchor, "该记录不在当前结果中，可在可视化中使用「查看该车型记录」。", false);
      return;
    }
    const record = matches[index];
    if (recordSources(record).length) expandedSourceRecords.add(record);
    searchState.resultPage = Math.floor(index / pageSizeFor(matches.length)) + 1;
    updateSearchResults();
    const element = app.querySelector(`[data-history-key="${cssEscape(target.recordKey)}"]`)
      || app.querySelector(`[data-record-key="${cssEscape(record.recordKey)}"]`);
    if (!element) return;
    let parent = element.parentElement?.closest("details");
    while (parent) {
      parent.open = true;
      parent = parent.parentElement?.closest("details");
    }
    element.classList.remove("is-evolution-located");
    void element.offsetWidth;
    element.classList.add("is-evolution-located");
    element.scrollIntoView({ block: "center", behavior: "smooth" });
    element.querySelector("[data-evolution-select]")?.focus({ preventScroll: true });
  }

  function renderResultsOutline(records, totalCount, maxPage) {
    if (!records.length) {
      return '<div class="empty-results">No rows match the current selection.</div>';
    }

    const hierarchy = ["MAKE", "MODEL", "TYPE", "YEAR"];
    const dataColumns = ["SIZE", "长度余量", ...activeDimensionColumns()];
    return `
      <div class="results-outline-wrap">
        <div class="results-outline results-outline-tree table-font-${escapeHtml(searchState.tableFontSize)}">
          <div class="outline-tree" role="tree">
            ${outlineLevelMarkup(records, hierarchy, dataColumns, 0, 0)}
          </div>
        </div>
      </div>
      ${resultPaginationMarkup(records.length, totalCount, maxPage)}
    `;
  }

  function outlineLevelMarkup(records, hierarchy, dataColumns, depth, visualDepth) {
    if (depth >= hierarchy.length) {
      return records.map((record, index) => outlineRecordMarkup(record, dataColumns, index, visualDepth, "YEAR")).join("");
    }

    const field = hierarchy[depth];
    if (depth === hierarchy.length - 1) {
      return records.map((record, index) => (
        outlineRecordMarkup(record, dataColumns, index, visualDepth, field)
      )).join("");
    }

    const groups = new Map();
    records.forEach((record) => {
      const rawValue = resultColumnValue(record, field);
      const value = cleanField(rawValue) || null;
      if (!groups.has(value)) groups.set(value, []);
      groups.get(value).push(record);
    });

    return Array.from(groups.entries()).map(([value, groupRecords]) => {
      if (value === null) {
        return outlineLevelMarkup(groupRecords, hierarchy, dataColumns, depth + 1, visualDepth);
      }
      const countMarkup = groupRecords.length > 1
        ? `<em>${formatCount(groupRecords.length)} 条</em>`
        : "";
      return `
        <details class="outline-group outline-level-${depth}${visualDepth === 0 ? " outline-root" : ""}" open style="--outline-depth: ${visualDepth}" role="treeitem">
          <summary>
            <span class="outline-branch" aria-hidden="true"></span>
            <span class="outline-field-name">${escapeHtml(field)}</span>
            <strong>${escapeHtml(value)}</strong>
            ${countMarkup}
            ${evolutionOn() && sameColumn(field, "MODEL") ? evolutionGroupSelectMarkup(groupRecords) : ""}
          </summary>
          <div class="outline-children" role="group">
            ${outlineLevelMarkup(groupRecords, hierarchy, dataColumns, depth + 1, visualDepth + 1)}
          </div>
        </details>
      `;
    }).join("");
  }

  function outlineRecordMarkup(record, dataColumns, index, visualDepth, leafField) {
    const leafValue = cleanField(resultColumnValue(record, leafField)) || `记录 ${index + 1}`;
    const keyAttr = evolutionOn() && record.recordKey ? ` data-record-key="${escapeHtml(record.recordKey)}"` : "";
    return `<details class="outline-group outline-record-node" open style="--outline-depth: ${visualDepth}" role="treeitem"${keyAttr}><summary><span class="outline-branch" aria-hidden="true"></span><span class="outline-field-name">${escapeHtml(leafField)}</span><strong class="vehicle-copy-target" tabindex="0" data-copy-text="${escapeHtml(copyTextForRecord(record))}" title="点击复制车型信息">${escapeHtml(leafValue)}</strong></summary><div class="outline-record-fields" role="group">${evolutionOn() ? evolutionOutlineSelectMarkup(record, visualDepth + 1) : ""}${outlineCombinedLeafMarkup(record, ["SIZE", "长度余量"], visualDepth + 1, "size")}${outlineCombinedLeafMarkup(record, activeDimensionColumns(), visualDepth + 1, "dimensions")}</div></details>`;
  }

  function outlineCombinedLeafMarkup(record, columns, visualDepth, kind) {
    const items = columns.map((column) => {
      const value = resultColumnValue(record, column);
      const label = isSizeColumn(column) ? "SIZE" : isLengthMarginColumn(column) ? "长度余量" : outlineDimensionLabel(column);
      const display = isDimensionColumn(column) ? dimensionDisplay(column, value) : isLengthMarginColumn(column) ? lengthMarginDisplay(value) : (value || "NULL");
      const ref = isSizeColumn(column) ? sizeRefAttributes(record, value) : { attr: "", className: "" };
      const style = isSizeColumn(column) ? ` style="--outline-value-color: ${sizeBackground(value)}"` : isLengthMarginColumn(column) ? ` style="${escapeHtml(lengthMarginStyle(value))}"` : "";
      return `<span class="outline-combined-item outline-item-${isSizeColumn(column) ? "size" : isLengthMarginColumn(column) ? "margin" : cleanField(label)}${ref.className}"${ref.attr}${style}><b>${escapeHtml(label)}</b><strong>${escapeHtml(display || "-")}</strong></span>`;
    }).join('<i aria-hidden="true"></i>');
    const copyClass = kind === "dimensions" ? " dimension-copy-target" : "";
    const copyAttrs = kind === "dimensions" ? ` tabindex="0" data-copy-text="${escapeHtml(copyDimensionsForRecord(record))}" title="点击复制长宽高"` : "";
    return `<div class="outline-tree-leaf outline-combined-leaf outline-combined-${kind}${copyClass}"${copyAttrs} style="--outline-leaf-depth: ${visualDepth}">${items}</div>`;
  }

  function outlineDimensionLabel(column) {
    const key = cleanField(column).toUpperCase();
    return key.startsWith("L") ? "长" : key.startsWith("W") ? "宽" : key.startsWith("H") ? "高" : column;
  }

  function outlineDataCellMarkup(record, column) {
    const value = resultColumnValue(record, column);
    if (isSalesTotalColumn(column)) {
      return `<span class="outline-value outline-sales-total"><strong>${escapeHtml(formatSalesTotal(value) || "-")}</strong></span>`;
    }
    if (isDimensionColumn(column)) {
      return `<span class="outline-value outline-dimension"><strong>${escapeHtml(dimensionDisplay(column, value) || "-")}</strong></span>`;
    }
    if (isLengthMarginColumn(column)) {
      return `<span class="outline-value outline-dimension" style="${escapeHtml(lengthMarginStyle(value))}"><strong>${escapeHtml(lengthMarginDisplay(value) || "-")}</strong></span>`;
    }
    if (isSizeColumn(column)) {
      const ref = sizeRefAttributes(record, value);
      return `<span class="outline-value outline-size${ref.className}"${ref.attr} style="--size-bg: ${sizeBackground(value)}; --size-fg: ${sizeTextColor()}"><strong>${escapeHtml(value || "NULL")}</strong></span>`;
    }
    return `<span class="outline-value"><strong>${escapeHtml(value || "-")}</strong></span>`;
  }

  function resultPaginationMarkup(visibleCount, totalCount, maxPage) {
    return `
      <div class="result-limit-bar">
        <span>第 ${formatCount(searchState.resultPage)} / ${formatCount(maxPage)} 页 · 显示 ${formatCount(visibleCount)} / ${formatCount(totalCount)}</span>
        <button class="result-page-button" type="button" data-result-page="prev" data-max-page="${maxPage}" ${searchState.resultPage <= 1 ? "disabled" : ""}>上一页</button>
        <button class="result-page-button" type="button" data-result-page="next" data-max-page="${maxPage}" ${searchState.resultPage >= maxPage ? "disabled" : ""}>下一页</button>
        <label>
          <span>显示数</span>
          <select class="search-select result-limit-select" data-result-limit>
            ${[200, 500].map((value) => `<option value="${value}"${searchState.resultLimit === value ? " selected" : ""}>${value}</option>`).join("")}
          </select>
        </label>
      </div>
    `;
  }

  function pageSizeFor(totalCount) {
    return Math.min(maxResultPageSize, Math.max(1, Number(searchState.resultLimit) || 200), Math.max(1, totalCount));
  }

  function resultColumns(records) {
    const usedColumns = searchState.columns;
    const fallbackColumns = ["MODEL", "版本", "YEAR", "TYPE", "CAB", "BED", "销量合计", "SIZE"];
    const columns = usedColumns.length ? usedColumns : fallbackColumns;
    const withModel = records.some((record) => record.model) && !columns.some((column) => sameColumn(column, "MODEL"))
      ? ["MODEL", ...columns]
      : columns;
    const ordered = sortSizeFields(withModel.map((column) => ({ key: column, label: column }))).map((field) => field.key);
    const visible = ordered.filter((column) => !hiddenForVehicleKind(column) && (isSizeColumnVisible(column) || isSizeColumn(column)));
    const rightColumns = [...activeDimensionColumns(), "长度余量"].filter((column) => visible.some((item) => sameColumn(item, column)) || records.some((record) => resultColumnValue(record, column)));
    const withoutRight = visible.filter((column) => !isSizeColumn(column) && !isDimensionColumn(column) && !isLengthMarginColumn(column) && !rightColumns.some((item) => sameColumn(item, column)));
    const hasSize = withModel.some((column) => isSizeColumn(column)) || records.some((record) => record.values.SIZE || record.size);
    return hasSize ? [...withoutRight, ...rightColumns, "SIZE"] : [...withoutRight, ...rightColumns];
  }

  function resultCellMarkup(record, column) {
    const value = column.key === "MAKE" ? record.make : resultColumnValue(record, column.key);
    if (isSalesTotalColumn(column.key)) {
      return `<td class="sales-total-cell"><strong>${escapeHtml(formatSalesTotal(value) || "-")}</strong></td>`;
    }
    if (column.dimension || isLengthMarginColumn(column.key)) {
      const displayValue = isLengthMarginColumn(column.key) ? lengthMarginDisplay(value) : dimensionDisplay(column.key, value);
      const copyClass = column.dimension ? " dimension-copy-target" : "";
      const copyTitle = recordSources(record).length ? "来源车型最大值，点击复制长宽高" : "点击复制长宽高";
      const copyAttrs = column.dimension ? ` tabindex="0" data-copy-text="${escapeHtml(copyDimensionsForRecord(record))}" title="${copyTitle}"` : "";
      return `<td class="dimension-cell size-dimension-cell size-sticky-col ${sizeStickyClass(column.key)}${copyClass}"${copyAttrs} style="${escapeHtml(isLengthMarginColumn(column.key) ? lengthMarginStyle(value) : "")}"><strong>${escapeHtml(displayValue || "-")}</strong></td>`;
    }
    if (column.size) {
      const ref = sizeRefAttributes(record, value);
      const displayValue = value || "NULL";
      return `<td class="size-cell size-sticky-col size-sticky-size${ref.className}"${ref.attr} style="--size-bg: ${sizeBackground(value)}; --size-fg: ${sizeTextColor()}"><strong>${escapeHtml(displayValue)}</strong></td>`;
    }
    if (sameColumn(column.key, "SHAPE") && value) {
      return `<td class="shape-cell" tabindex="0" data-shape="${escapeHtml(value)}"><span>${escapeHtml(value)}</span></td>`;
    }
    if (sameColumn(column.key, "CODE") && value) {
      return `<td class="vehicle-copy-target code-cell" tabindex="0" data-copy-text="${escapeHtml(value)}" title="点击复制代号"><strong>${escapeHtml(value)}</strong></td>`;
    }
    const vehicleField = ["MAKE", "MODEL", "版本", "TYPE", "YEAR", "CAB", "BED", "销量合计"].some((key) => sameColumn(column.key, key));
    const vehicleAttrs = vehicleField ? ` class="vehicle-copy-target" tabindex="0" data-copy-text="${escapeHtml(copyTextForRecord(record))}" title="点击复制车型信息"` : "";
    return `<td${vehicleAttrs}>${escapeHtml(value || "")}</td>`;
  }

  function sizeHeaderLabelMarkup(column) {
    const isFiltered = hasColumnFilterValue(searchState.columnFilters[column.key]);
    const isOpen = searchState.openFilter === column.key;
    const sortState = headerSortState(column.key);
    const sortHint = sortState === "asc" ? "当前升序，点击改为降序" : sortState === "desc" ? "当前降序，点击取消排序" : "点击升序排序";
    return `
      <div class="th-label th-header-control${isFiltered ? " is-filtered" : ""}${sortState !== "none" ? " is-sorted" : ""}">
        <button class="th-sort-button sort-${escapeHtml(sortState)}" type="button" data-size-sort-toggle="${escapeHtml(column.key)}" aria-label="${escapeHtml(column.label)}：${sortHint}" title="${escapeHtml(sortHint)}">
          <span class="th-text">${escapeHtml(column.label)}</span><span class="th-sort-icon" aria-hidden="true"></span>
        </button>
        <button class="th-filter-button${isFiltered ? " is-filtered" : ""}${isOpen ? " is-open" : ""}" type="button" data-size-open-filter="${escapeHtml(column.key)}" aria-expanded="${isOpen ? "true" : "false"}" aria-label="筛选 ${escapeHtml(column.label)}" title="${isFiltered ? "已筛选，点击修改" : "筛选"} ${escapeHtml(column.label)}">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3h12l-4.6 5.4v4.4l-2.8 1.4V8.4z"/></svg>
        </button>
      </div>
    `;
  }

  function headerSortState(key) {
    return sameColumn(searchState.sortField, key) ? searchState.sortDirection : "none";
  }

  function sizeHeaderFilterMarkup(column, tableColumns) {
    if (searchState.openFilter !== column.key) return "";
    const key = escapeHtml(column.key);
    const sortState = headerSortState(column.key);
    const sortButton = (direction, label) => `<button type="button" class="filter-pop-sort-button${sortState === direction ? " is-active" : ""}" data-size-sort-set="${key}" data-sort-direction="${direction}">${label}</button>`;
    const sortRow = `
      <div class="filter-pop-section filter-pop-sort" role="group" aria-label="排序">
        ${sortButton("asc", "↑ 升序")}${sortButton("desc", "↓ 降序")}
        <button type="button" class="filter-pop-sort-button" data-size-sort-set="${key}" data-sort-direction=""${sortState === "none" ? " disabled" : ""}>不排序</button>
      </div>`;
    const isFiltered = hasColumnFilterValue(searchState.columnFilters[column.key]);
    const clearButton = `<button type="button" class="filter-pop-link" data-filter-clear="${key}"${isFiltered ? "" : " disabled"}>清除筛选</button>`;
    const align = column.alignRight ? " align-right" : "";
    if (isRangeFilterColumn(column.key)) {
      const value = typeof searchState.columnFilters[column.key] === "object" ? searchState.columnFilters[column.key] : {};
      return `
        <div class="header-filter-popover${align}" role="dialog" aria-label="${key} 排序与筛选">
          ${sortRow}
          <div class="filter-pop-section">
            <div class="filter-pop-title"><span>数值范围（含边界，回车生效）</span>${clearButton}</div>
            <div class="range-inputs">
              <input type="number" step="0.1" data-size-range-filter="${key}" data-range-side="min" value="${escapeHtml(value.min || "")}" placeholder="最小" aria-label="最小值">
              <input type="number" step="0.1" data-size-range-filter="${key}" data-range-side="max" value="${escapeHtml(value.max || "")}" placeholder="最大" aria-label="最大值">
            </div>
          </div>
        </div>
      `;
    }
    const selected = arrayFilterValue(searchState.columnFilters[column.key]);
    const options = sizeFilterOptions(column, tableColumns).filter((option) => option.value);
    const query = searchState.filterSearch.trim().toLowerCase();
    const matchesQuery = (option) => !query || option.label.toLowerCase().includes(query);
    return `
      <div class="header-filter-popover${align}" role="dialog" aria-label="${key} 排序与筛选">
        ${sortRow}
        <div class="filter-pop-section">
          <div class="filter-pop-title"><span>${selected.length ? `已选 ${formatCount(selected.length)} 项` : `共 ${formatCount(options.length)} 项`}</span>${clearButton}</div>
          <input class="filter-pop-search" type="search" data-filter-search="${key}" value="${escapeHtml(searchState.filterSearch)}" placeholder="搜索选项，回车只看结果" autocomplete="off" aria-label="搜索 ${key} 选项">
          <div class="header-option-scroll">
            ${options.map((option) => `
              <label class="header-multi-option"${matchesQuery(option) ? "" : " hidden"}>
                <input type="checkbox" data-size-multi-filter="${key}" value="${escapeHtml(option.value)}"${selected.includes(option.value) ? " checked" : ""}>
                <span>${escapeHtml(option.label)}</span><em>${option.count ? formatCount(option.count) : ""}</em>
              </label>
            `).join("")}
            <div class="filter-pop-empty"${options.some(matchesQuery) ? " hidden" : ""}>没有匹配的选项</div>
          </div>
          <div class="filter-pop-actions">
            <button type="button" class="filter-pop-link" data-filter-select-visible="${key}">选中可见项</button>
            <button type="button" class="filter-pop-link" data-filter-invert="${key}">反选可见项</button>
          </div>
        </div>
      </div>
    `;
  }

  function sizeFilterOptions(column, tableColumns) {
    const currentValue = searchState.columnFilters[column.key] || "";
    const records = getSearchMatchesIgnoringColumn(column.key);
    const counts = new Map();
    records.forEach((record) => uniqueInOrder(sizeColumnFilterValues(record, column.key)).forEach((value) => {
      if (value) counts.set(value, (counts.get(value) || 0) + 1);
    }));
    const values = sortedSizeFilterValues(column.key, [...counts.keys()]);
    const allLabel = `All ${column.label}`;
    const options = [{ value: "", label: allLabel }, ...values.map((value) => ({
      value,
      label: sameColumn(column.key, "SOURCE") ? sourceLabel(value) : value,
      count: counts.get(value)
    }))];
    arrayFilterValue(currentValue).forEach((selectedValue) => {
      if (!values.includes(selectedValue)) {
        options.push({
          value: selectedValue,
          label: sameColumn(column.key, "SOURCE") ? sourceLabel(selectedValue) : selectedValue
        });
      }
    });
    return options;
  }

  function sortedSizeFilterValues(key, values) {
    if (sameColumn(key, "YEAR")) {
      return [...values].sort((left, right) => Number(right) - Number(left));
    }
    if (isSizeColumn(key)) {
      return [...values].sort(compareSizeValues);
    }
    if (sameColumn(key, "BED")) {
      return [...values].sort(compareBedValues);
    }
    if (isRangeFilterColumn(key)) {
      return [...values].sort(compareValues);
    }
    return values;
  }

  function getSearchMatchesIgnoringColumn(ignoredKey) {
    const saved = searchState.columnFilters[ignoredKey];
    delete searchState.columnFilters[ignoredKey];
    const records = getSearchMatches();
    if (saved) {
      searchState.columnFilters[ignoredKey] = saved;
    }
    return records;
  }

  function updateActiveFilterChips() {
    const chips = app.querySelector(".active-filter-chips");
    if (!chips) return;
    const primaryFilters = [
      ["source", "SOURCE", searchState.selectedSource ? sourceLabel(searchState.selectedSource) : ""],
      ["make", "MAKE", searchState.selectedMake],
      ["model", "MODEL", searchState.selectedModel],
      ["year", "YEAR", searchState.selectedYear],
      ["construct", filterConfig("construct").label, searchState.selectedConstruct],
      ["cab", filterConfig("cab").label, searchState.selectedCab],
      ["bed", filterConfig("bed").label, searchState.selectedBed]
    ].filter(([, , value]) => value).map(([key, label, value]) => ({ kind: "primary", key, label, value }));
    const columnFilters = Object.entries(searchState.columnFilters)
      .filter(([, value]) => hasColumnFilterValue(value))
      .map(([key, value]) => {
        const label = columnFilterChipValue(key, value);
        return { kind: "column", key, label: key, value: label };
      });
    const items = [...primaryFilters, ...columnFilters];
    chips.innerHTML = items.map((item) => (
      `<button class="filter-chip" type="button" data-filter-chip-kind="${escapeHtml(item.kind)}" data-filter-chip-key="${escapeHtml(item.key)}" title="取消 ${escapeHtml(item.label)} 筛选"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.value)}</span><em aria-hidden="true">×</em></button>`
    )).join("");
  }

  function bindActiveFilterChips() {
    app.querySelectorAll("[data-filter-chip-kind]").forEach((chip) => {
      if (chip.dataset.bound === "true") return;
      chip.dataset.bound = "true";
      chip.addEventListener("click", () => {
        const primaryKey = chip.dataset.filterChipKind === "primary" ? chip.dataset.filterChipKey : "";
        if (chip.dataset.filterChipKind === "column") {
          delete searchState.columnFilters[chip.dataset.filterChipKey];
        } else {
          clearPrimaryFilter(chip.dataset.filterChipKey);
        }
        searchState.resultPage = 1;
        if ((primaryKey === "source" || primaryKey === "make") && viewConfig.match_sources?.length) {
          searchState.scopeKey = "";
          loadSearchIndex(currentSearchDirectories());
          return;
        }
        updateSearchControls();
        updateSearchResults();
      });
    });
  }

  function clearPrimaryFilter(key) {
    if (key === "source") {
      searchState.selectedSource = defaultSourceFilter();
      searchState.selectedMake = "";
      searchState.selectedModel = "";
      searchState.selectedYear = "";
      searchState.selectedConstruct = "";
      searchState.selectedCab = "";
      searchState.selectedBed = "";
    } else if (key === "make") {
      searchState.selectedMake = "";
      searchState.selectedModel = "";
      searchState.selectedYear = "";
      searchState.selectedConstruct = "";
      searchState.selectedCab = "";
      searchState.selectedBed = "";
    } else if (key === "model") {
      searchState.selectedModel = "";
      searchState.selectedYear = "";
      searchState.selectedConstruct = "";
      searchState.selectedCab = "";
      searchState.selectedBed = "";
    } else if (key === "year") {
      searchState.selectedYear = "";
      searchState.selectedConstruct = "";
      searchState.selectedCab = "";
      searchState.selectedBed = "";
    } else if (key === "construct") {
      searchState.selectedConstruct = "";
      searchState.selectedCab = "";
      searchState.selectedBed = "";
    } else if (key === "cab") {
      searchState.selectedCab = "";
      searchState.selectedBed = "";
    } else if (key === "bed") {
      searchState.selectedBed = "";
    }
  }

  function bindSizeTableFilters() {
    app.querySelectorAll("[data-size-table-filter]").forEach((select) => {
      if (select.dataset.bound === "true") return;
      select.dataset.bound = "true";
      select.addEventListener("change", () => {
        const key = select.dataset.sizeTableFilter;
        cancelHeaderFilterClose();
        if (select.value) {
          searchState.columnFilters[key] = select.value;
        } else {
          delete searchState.columnFilters[key];
        }
        searchState.openFilter = key;
        searchState.resultPage = 1;
        updateSearchResults();
      });
    });
    app.querySelectorAll("[data-size-multi-filter]").forEach((input) => {
      if (input.dataset.bound === "true") return;
      input.dataset.bound = "true";
      input.addEventListener("change", () => {
        updateMultiColumnFilter(input.dataset.sizeMultiFilter);
      });
    });
    app.querySelectorAll("[data-size-range-filter]").forEach((input) => {
      if (input.dataset.bound === "true") return;
      input.dataset.bound = "true";
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") input.dispatchEvent(new Event("change"));
      });
      input.addEventListener("change", () => {
        const key = input.dataset.sizeRangeFilter;
        const side = input.dataset.rangeSide;
        const current = typeof searchState.columnFilters[key] === "object" ? searchState.columnFilters[key] : {};
        const next = { ...current, [side]: input.value };
        cancelHeaderFilterClose();
        if (next.min || next.max) {
          searchState.columnFilters[key] = next;
        } else {
          delete searchState.columnFilters[key];
        }
        searchState.openFilter = key;
        searchState.resultPage = 1;
        updateSearchResults();
      });
    });
    app.querySelectorAll("[data-result-limit]").forEach((control) => {
      if (control.dataset.bound === "true") return;
      control.dataset.bound = "true";
      control.addEventListener("change", () => {
        searchState.resultLimit = Math.min(maxResultPageSize, Math.max(1, Number(control.value) || 200));
        searchState.resultPage = 1;
        searchState.resetResultScroll = true;
        updateSearchResults();
      });
    });
    app.querySelectorAll("[data-result-page]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", () => {
        const maxPage = Number(button.dataset.maxPage || "1");
        const direction = button.dataset.resultPage === "next" ? 1 : -1;
        searchState.resultPage = Math.min(maxPage, Math.max(1, searchState.resultPage + direction));
        searchState.resetResultScroll = true;
        updateSearchResults();
      });
    });
  }

  function updateMultiColumnFilter(key) {
    const values = Array.from(app.querySelectorAll(`[data-size-multi-filter="${cssEscape(key)}"]:checked`))
      .map((input) => input.value)
      .filter(Boolean);
    cancelHeaderFilterClose();
    if (values.length) {
      searchState.columnFilters[key] = uniqueInOrder(values);
    } else {
      delete searchState.columnFilters[key];
    }
    searchState.openFilter = key;
    searchState.resultPage = 1;
    updateSearchResults();
  }

  function hasColumnFilterValue(value) {
    if (Array.isArray(value)) return value.length > 0;
    if (value && typeof value === "object") return Boolean(value.min || value.max);
    return Boolean(value);
  }

  function arrayFilterValue(value) {
    return Array.isArray(value) ? value : (value ? [value] : []);
  }

  function columnFilterChipValue(key, value) {
    if (Array.isArray(value)) {
      const shown = value.slice(0, 4).join(", ");
      return value.length > 4 ? `${shown} +${value.length - 4}` : shown;
    }
    if (value && typeof value === "object") {
      return `${value.min || "-∞"} - ${value.max || "+∞"}`;
    }
    return sameColumn(key, "SOURCE") ? sourceLabel(value) : value;
  }

  function bindSizeHeaderFilterPopovers() {
    app.querySelectorAll("[data-size-open-filter]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const key = button.dataset.sizeOpenFilter;
        searchState.filterSearch = "";
        searchState.openFilter = searchState.openFilter === key ? "" : key;
        updateSearchResults();
        if (searchState.openFilter) {
          app.querySelector(".header-filter-popover .filter-pop-search, .header-filter-popover input[data-range-side='min']")?.focus({ preventScroll: true });
        }
      });
    });
    app.querySelectorAll("[data-size-sort-toggle]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        cycleHeaderSort(button.dataset.sizeSortToggle);
      });
    });
    app.querySelectorAll("[data-size-sort-set]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", () => {
        const direction = button.dataset.sortDirection;
        searchState.sortField = direction ? button.dataset.sizeSortSet : "";
        searchState.sortDirection = direction || "asc";
        searchState.resultPage = 1;
        updateSearchResults();
      });
    });
    app.querySelectorAll("[data-filter-search]").forEach((input) => {
      if (input.dataset.bound === "true") return;
      input.dataset.bound = "true";
      // 只在弹层内显示/隐藏选项，不重绘表格，输入不丢焦点
      input.addEventListener("input", () => {
        searchState.filterSearch = input.value;
        const query = input.value.trim().toLowerCase();
        const popover = input.closest(".header-filter-popover");
        let shown = 0;
        popover.querySelectorAll(".header-multi-option").forEach((option) => {
          const visible = !query || option.querySelector("span").textContent.toLowerCase().includes(query);
          option.hidden = !visible;
          if (visible) shown += 1;
        });
        popover.querySelector(".filter-pop-empty").hidden = shown > 0;
      });
      input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        // 回车：只保留可见项（搜索结果）作为筛选条件
        event.preventDefault();
        setColumnFilterFromVisible(input.dataset.filterSearch, "only");
      });
    });
    app.querySelectorAll("[data-filter-clear]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", () => {
        delete searchState.columnFilters[button.dataset.filterClear];
        searchState.filterSearch = "";
        searchState.resultPage = 1;
        updateSearchResults();
      });
    });
    app.querySelectorAll("[data-filter-select-visible], [data-filter-invert]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", () => {
        const key = button.dataset.filterSelectVisible || button.dataset.filterInvert;
        setColumnFilterFromVisible(key, button.dataset.filterInvert ? "invert" : "add");
      });
    });
  }

  function setColumnFilterFromVisible(key, mode) {
    const options = Array.from(app.querySelectorAll(`.header-filter-popover [data-size-multi-filter="${cssEscape(key)}"]`));
    const visible = options.filter((input) => !input.closest(".header-multi-option").hidden);
    const selected = new Set(arrayFilterValue(searchState.columnFilters[key]));
    if (mode === "only") {
      selected.clear();
      visible.forEach((input) => selected.add(input.value));
    } else {
      visible.forEach((input) => {
        if (mode === "invert" && selected.has(input.value)) selected.delete(input.value);
        else selected.add(input.value);
      });
    }
    if (selected.size) searchState.columnFilters[key] = [...selected];
    else delete searchState.columnFilters[key];
    searchState.resultPage = 1;
    updateSearchResults();
  }

  function closeHeaderFilter() {
    if (!searchState.openFilter) return;
    searchState.openFilter = "";
    searchState.filterSearch = "";
    updateSearchResults();
  }

  function cycleHeaderSort(key) {
    if (!sameColumn(searchState.sortField, key)) {
      searchState.sortField = key;
      searchState.sortDirection = "asc";
    } else if (searchState.sortDirection === "asc") {
      searchState.sortDirection = "desc";
    } else {
      searchState.sortField = "";
      searchState.sortDirection = "asc";
    }
    searchState.resultPage = 1;
    searchState.openFilter = "";
    updateSearchResults();
  }

  function cancelHeaderFilterClose() {
    if (headerFilterCloseTimer) {
      window.clearTimeout(headerFilterCloseTimer);
      headerFilterCloseTimer = 0;
    }
    app.querySelectorAll(".header-filter-popover.is-closing").forEach((popover) => popover.classList.remove("is-closing"));
  }

  function bindSizeLinkedRows() {
    app.querySelectorAll(".vehicle-copy-target[data-copy-text], .dimension-copy-target[data-copy-text]").forEach((row) => {
      row.addEventListener("click", (event) => { event.preventDefault(); event.stopPropagation(); copyResultRow(row); });
      row.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        event.stopPropagation();
        copyResultRow(row);
      });
    });
  }

  async function copyResultRow(row) {
    const text = cleanField(row.dataset.copyText);
    if (!text) return;
    try {
      await writeClipboardText(text);
      showCopyFeedback(row, `已复制：${text}`, true);
    } catch (error) {
      showCopyFeedback(row, "复制失败，请重试。", false);
    }
  }

  async function writeClipboardText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const input = document.createElement("textarea");
    input.value = text;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.left = "-9999px";
    document.body.appendChild(input);
    input.select();
    input.setSelectionRange(0, text.length);
    const copied = typeof document.execCommand === "function" && document.execCommand("copy");
    input.remove();
    if (!copied) throw new Error("Clipboard API is unavailable.");
  }

  function showCopyFeedback(row, message, succeeded) {
    const feedback = app.querySelector(".copy-feedback");
    if (!feedback) return;
    if (copyFeedbackTimer) window.clearTimeout(copyFeedbackTimer);
    app.querySelectorAll(".copyable-result-row.is-copied, .vehicle-copy-target.is-copied, .dimension-copy-target.is-copied").forEach((item) => item.classList.remove("is-copied"));
    row.classList.toggle("is-copied", succeeded);
    feedback.textContent = message;
    feedback.classList.toggle("is-error", !succeeded);
    feedback.classList.add("is-open");
    copyFeedbackTimer = window.setTimeout(() => {
      row.classList.remove("is-copied");
      feedback.classList.remove("is-open", "is-error");
      copyFeedbackTimer = 0;
    }, 1800);
  }

  function sizeColumnFilterValue(record, key) {
    if (sameColumn(key, "SOURCE")) return sourceFilterValue(record);
    if (sameColumn(key, "MAKE")) return record.make;
    if (sameColumn(key, "MODEL")) return record.model || resultColumnValue(record, key);
    if (sameColumn(key, "YEAR")) return cleanField(resultColumnValue(record, key) || record.year);
    if (sameColumn(key, "CONST")) return configuredRecordValue(record, "const") || record.construct;
    if (sameColumn(key, "CAB")) return configuredRecordValue(record, "cab");
    if (sameColumn(key, "BED")) return configuredRecordValue(record, "bed");
    if (sameColumn(key, "TYPE")) return record.type || resultColumnValue(record, key);
    if (sameColumn(key, "SIZE")) return resultColumnValue(record, key) || "NULL";
    if (isDimensionColumn(key)) {
      return numericDisplayValue(dimensionDisplay(key, resultColumnValue(record, key)));
    }
    if (isLengthMarginColumn(key)) {
      // 与长宽高一致：按当前显示单位（MM/CM/IN）筛选，和表格里看到的数值相同
      return numericDisplayValue(lengthMarginDisplay(resultColumnValue(record, key)));
    }
    return resultColumnValue(record, key);
  }

  function sizeColumnFilterValues(record, key) {
    const value = sizeColumnFilterValue(record, key);
    if (!value) return [];
    if (isRangeFilterColumn(key) || isSizeColumn(key)) {
      return [value];
    }
    if (sameColumn(key, "YEAR")) {
      const years = Array.isArray(record.years) ? record.years.map((year) => String(year)) : [];
      return uniqueInOrder([...years, ...fieldAtomicValues(value)]);
    }
    return fieldAtomicValues(value);
  }

  function sourceFilterValue(record) {
    return cleanField(topSource(record.directory) || record.source) || "__missing__";
  }

  function sourceLabel(value) {
    return value === "__missing__" ? "未指定" : cleanField(value);
  }

  function sizeReferenceFor(value) {
    return sizeReferenceIndex.get(cleanField(value).toUpperCase());
  }

  function bindSizeReferenceHovers() {
    const cells = app.querySelectorAll("[data-size-ref]");
    if (!cells.length) return;
    const floating = ensureSizeReferenceFloating();
    cells.forEach((cell) => {
      const show = () => {
        const rule = cell.dataset.sizeRuleId
          ? exactSizeRuleFor(cell.dataset.sizeRuleId, cell.dataset.sizeSource, cell.dataset.sizeRef, cell.dataset.sizeMatch)
          : sizeRuleFor(cell.dataset.sizeRef, cell.dataset.sizeSource);
        const ref = rule ? null : sizeReferenceIndex.get(cell.dataset.sizeRef);
        if (!rule && !ref) return;
        floating.innerHTML = rule ? sizeRuleMarkup(rule) : sizeReferenceMarkup(cell.textContent, ref);
        floating.classList.add("is-open");
        positionSizeReferenceFloating(floating, cell.getBoundingClientRect());
      };
      cell.addEventListener("mouseenter", show);
      cell.addEventListener("focus", show);
      cell.addEventListener("mousemove", () => positionSizeReferenceFloating(floating, cell.getBoundingClientRect()));
      cell.addEventListener("mouseleave", () => floating.classList.remove("is-open"));
      cell.addEventListener("blur", () => floating.classList.remove("is-open"));
    });
  }

  // SHAPE 悬停：压缩记录覆盖多个车形时（A / B）逐个列出中文名与说明
  function bindShapeHovers() {
    const cells = app.querySelectorAll("[data-shape]");
    if (!cells.length) return;
    const floating = ensureSizeReferenceFloating();
    cells.forEach((cell) => {
      const show = () => {
        floating.innerHTML = shapeMarkup(cell.dataset.shape);
        floating.classList.add("is-open");
        positionSizeReferenceFloating(floating, cell.getBoundingClientRect());
      };
      cell.addEventListener("mouseenter", show);
      cell.addEventListener("focus", show);
      cell.addEventListener("mouseleave", () => floating.classList.remove("is-open"));
      cell.addEventListener("blur", () => floating.classList.remove("is-open"));
    });
  }

  function shapeMarkup(value) {
    const shapes = value.split("/").map(cleanField).filter(Boolean);
    const items = shapes.map((shape) => {
      const info = shapeLabels[shape];
      return `<div class="shape-reference-item"><strong>${escapeHtml(info?.label || shape)}</strong><code>${escapeHtml(shape)}</code><p>${escapeHtml(info?.description || "暂无中文说明")}</p></div>`;
    }).join("");
    const note = shapes.length > 1 ? "该记录覆盖的年份含多种车形" : "车罩外形分类，不参与尺码计算";
    return `<div class="size-reference-meta">车形 SHAPE</div>${items}<div class="shape-reference-note">${note}</div>`;
  }

  function sizeRefAttributes(record, value) {
    const key = cleanField(value).toUpperCase();
    const sourceName = recordSourceName(record);
    const exact = exactSizeRule(record);
    if (key && exact) {
      return {
        attr: ` data-size-ref="${escapeHtml(key)}" data-size-source="${escapeHtml(sourceName)}" data-size-rule-id="${escapeHtml(exact.ruleId)}" data-size-match="${escapeHtml(exact.matchSize)}"`,
        className: " size-cell-has-ref"
      };
    }
    // 该国别有规则时只用规则；没有规则数据（如规则文件缺失）才退回旧 size-ref 参考
    if (!key || !(sizeRuleFor(key, sourceName) || (!sizeRuleScope(sourceName).index && sizeReferenceFor(key)))) {
      return { attr: "", className: "" };
    }
    return { attr: ` data-size-ref="${escapeHtml(key)}" data-size-source="${escapeHtml(sourceName)}"`, className: " size-cell-has-ref" };
  }

  function recordSourceName(record) {
    return cleanField(topSource(record?.directory)) || cleanField(searchState.selectedSource);
  }

  function sizeRuleScope(sourceName) {
    return sizeRules.scope(sourceName);
  }

  function sizeRuleFor(value, sourceName) {
    return sizeRules.ruleFor(value, sourceName);
  }

  // 表格数据所依据的 A0 版本（压缩表清单的 a0_version）与尺码规则同版本时才按规则ID 精确解释（版本混用不作为有效匹配解释）；
  // 可视化历史（A0 全量分片）与压缩表同 A0 版本由站点校验保证
  function sizeRuleVersionsConsistent() {
    const origin = matchDataOrigins.get(configuredMatchPath());
    const versions = [origin?.a0_version || origin?.version, sizeRulesOrigin?.version];
    return versions.every(Boolean) && versions[0] === versions[1];
  }

  function exactSizeRule(record) {
    if (!cleanField(record?.values?.["规则ID"]) || !sizeRuleVersionsConsistent()) return null;
    return sizeRules.exactForRecord(record, recordSourceName(record));
  }

  function exactSizeRuleFor(ruleId, sourceName, size, matchSize) {
    return sizeRules.exactFor(ruleId, sourceName, size, matchSize);
  }

  function sizeRuleMarkup(rule) {
    return window.SizeViewerRules.ruleMarkup(rule, dimensionFormat());
  }

  // 长度显示单位随页面切换（mm/cm/in），每次渲染时取当前值
  function dimensionFormat() {
    return { measurement: measurementDisplay, unit: searchState.dimensionUnit };
  }

  function ensureSizeReferenceFloating() {
    let floating = document.querySelector(".size-reference-floating");
    if (!floating) {
      floating = document.createElement("div");
      floating.className = "size-reference-floating";
      document.body.appendChild(floating);
    }
    return floating;
  }

  function positionSizeReferenceFloating(floating, rect) {
    const gap = 10;
    const width = floating.offsetWidth || 210;
    const left = Math.min(window.innerWidth - width - gap, Math.max(gap, rect.left + rect.width / 2 - width / 2));
    const top = Math.max(gap, rect.top - floating.offsetHeight - gap);
    floating.style.left = `${left}px`;
    floating.style.top = `${top}px`;
  }

  function sizeReferenceMarkup(size, ref) {
    const model = cleanField(ref["型号"]) || cleanField(size);
    const commonSize = cleanField(ref["通用尺码"]);
    return `
      <div class="size-reference-title">${escapeHtml(model)}</div>
      <div class="size-reference-common">${escapeHtml(commonSize ? `通用尺码 ${commonSize}` : `匹配 ${cleanField(size)}`)}</div>
      <div class="size-reference-dims">
        ${sizeReferenceDimension("长", ref["长_mm"])}
        ${sizeReferenceDimension("宽", ref["宽_mm"])}
        ${sizeReferenceDimension("高", ref["高_mm"])}
      </div>
    `;
  }

  function sizeReferenceDimension(label, value) {
    return window.SizeViewerRules.dimensionMarkup(label, value, dimensionFormat());
  }

  function sizeBackground(value) {
    const ref = sizeReferenceFor(value);
    const commonSize = cleanField(ref?.["通用尺码"]).toUpperCase();
    const colorKey = commonSize || cleanField(value).toUpperCase();
    const categoryFamilies = {
      "三厢车": "a",
      "跑车": "c",
      "两厢车": "h",
      "越野车": "s"
    };
    const keyedFamily = ["A", "C", "H", "S"].includes(colorKey[0]) ? colorKey[0].toLowerCase() : "";
    const family = keyedFamily || categoryFamilies[cleanField(ref?.["分类"])] || "other";
    const base = viewConfig.size_colors?.[family] || defaultViewConfig.size_colors[family];
    const commonLevel = Number((commonSize.match(/\d+/) || [""])[0]);
    const order = Number(ref?.["档位序号"]);
    const level = Number.isFinite(commonLevel) && commonSize
      ? commonLevel
      : (Number.isFinite(order) ? order % 10 : 0);
    return darkenHex(base, Math.min(0.34, Math.max(0, (level - 1) * 0.055)));
  }

  function sizeTextColor() {
    return viewConfig.size_colors?.text || defaultViewConfig.size_colors.text;
  }

  function darkenHex(hex, amount) {
    const normalized = cleanField(hex).replace(/^#/, "");
    if (!/^[0-9a-f]{6}$/i.test(normalized)) return hex;
    const value = Number.parseInt(normalized, 16);
    const ratio = 1 - Math.max(0, Math.min(1, amount));
    const red = Math.round(((value >> 16) & 255) * ratio);
    const green = Math.round(((value >> 8) & 255) * ratio);
    const blue = Math.round((value & 255) * ratio);
    return `rgb(${red}, ${green}, ${blue})`;
  }

  function lengthMarginStyle(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    if (number >= 127 && number <= 381) {
      return "--dimension-bg: #e6f6ec; --dimension-fg: #137333;";
    }
    const distance = number < 127 ? 127 - number : number - 381;
    const intensity = Math.min(1, distance / 381);
    const red = Math.round(244 - intensity * 80);
    const green = Math.round(226 - intensity * 150);
    const blue = Math.round(226 - intensity * 150);
    return `--dimension-bg: rgb(${red}, ${green}, ${blue}); --dimension-fg: #8a1f1f;`;
  }

  function lengthMarginDisplay(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return value;
    }
    return measurementDisplay(number);
  }

  function dimensionDisplay(column, value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return value;
    return isDimensionColumn(column) ? measurementDisplay(number) : value;
  }

  function measurementDisplay(millimetres) {
    const factors = { mm: 1, cm: 0.1, in: 1 / 25.4 };
    return String(Math.round(millimetres * (factors[searchState.dimensionUnit] || 1)));
  }

  function resultColumnValue(record, column) {
    if (sameColumn(column, "MODEL")) return record.values[column] || record.model || "";
    if (sameColumn(column, "MAKE")) return record.make || "";
    if (sameColumn(column, "CONST")) return configuredRecordValue(record, "const") || record.construct || record.values.CONST || record.values.CONSTRUCT || "";
    if (sameColumn(column, "CAB")) return configuredRecordValue(record, "cab") || record.values[column] || "";
    if (sameColumn(column, "BED")) return configuredRecordValue(record, "bed") || record.values[column] || "";
    if (sameColumn(column, "TYPE")) return record.values[column] || record.type || "";
    if (isDimensionColumn(column)) return dimensionSourceValue(record, column);
    if (isLengthMarginColumn(column)) return sourceValue(record, column) || record.values[column] || "";
    return record.values[column] || "";
  }

  function copyTextForRecord(record) {
    const year = cleanField(resultColumnValue(record, "YEAR") || record.year);
    const make = cleanField(record.make);
    const model = cleanField(resultColumnValue(record, "MODEL") || record.model);
    const type = cleanField(resultColumnValue(record, "TYPE") || record.type || record.construct);
    return [year, make, model, type].filter(Boolean).join(" ");
  }

  function copyDimensionsForRecord(record) {
    return activeDimensionColumns().map((column) => dimensionDisplay(column, resultColumnValue(record, column))).join("\t");
  }

  function salesTotalNumber(value) {
    const text = cleanField(value).replace(/,/g, "");
    if (!text) return null;
    const number = Number(text);
    return Number.isFinite(number) ? number : null;
  }

  function formatSalesTotal(value) {
    const number = salesTotalNumber(value);
    return number === null ? cleanField(value) : formatCount(number);
  }

  function renderSearchSummary(element, message, records) {
    element.textContent = "";
    const messageNode = document.createElement("span");
    messageNode.textContent = message;
    element.appendChild(messageNode);
    const salesValues = records.map((record) => salesTotalNumber(resultColumnValue(record, "销量合计"))).filter((value) => value !== null);
    if (!salesValues.length) return;
    const salesNode = document.createElement("strong");
    salesNode.className = "sales-total-summary";
    salesNode.textContent = `销量合计：${formatCount(salesValues.reduce((total, value) => total + value, 0))}`;
    element.appendChild(salesNode);
  }

  function sizeDisplayFields() {
    return allSizeDisplayFields().filter((field) => !hiddenForVehicleKind(field.key));
  }

  function allSizeDisplayFields() {
    const seen = new Set();
    const keys = ["MODEL", ...searchState.columns, ...activeDimensionColumns(), "版本", "TYPE", "YEAR", "CAB", "BED", "SIZE"].filter(Boolean);
    const fields = keys.filter((key) => {
      const normalized = cleanField(key).toUpperCase();
      if (seen.has(normalized)) return false;
      seen.add(normalized);
      return !sameColumn(key, "MAKE");
    }).map((key) => ({ key, label: sameColumn(key, "CONST") ? "CONST" : key }));
    return sortSizeFields(fields);
  }

  function ensureSizeFieldState() {
    const fields = allSizeDisplayFields();
    if (!searchState.fieldOrder.length) {
      searchState.fieldOrder = fields.map((field) => field.key);
    } else {
      const ordered = new Set(searchState.fieldOrder.map((field) => cleanField(field).toUpperCase()));
      fields.forEach((field) => {
        if (!ordered.has(cleanField(field.key).toUpperCase())) {
          searchState.fieldOrder.push(field.key);
          ordered.add(cleanField(field.key).toUpperCase());
        }
      });
    }
    if (!searchState.visibleColumns) {
      searchState.visibleColumns = new Set(fields.map((field) => field.key));
    } else {
      const visible = new Set(Array.from(searchState.visibleColumns).map((field) => cleanField(field).toUpperCase()));
      fields.forEach((field) => {
        if (!visible.has(cleanField(field.key).toUpperCase())) {
          searchState.visibleColumns.add(field.key);
          visible.add(cleanField(field.key).toUpperCase());
        }
      });
    }
  }

  function isSizeColumnVisible(key) {
    ensureSizeFieldState();
    return searchState.visibleColumns.has(key);
  }

  function sortSizeFields(fields) {
    const order = new Map(searchState.fieldOrder.map((key, index) => [cleanField(key).toUpperCase(), index]));
    return [...fields].sort((left, right) => {
      const leftIndex = order.has(cleanField(left.key).toUpperCase()) ? order.get(cleanField(left.key).toUpperCase()) : Number.MAX_SAFE_INTEGER;
      const rightIndex = order.has(cleanField(right.key).toUpperCase()) ? order.get(cleanField(right.key).toUpperCase()) : Number.MAX_SAFE_INTEGER;
      return leftIndex - rightIndex;
    });
  }

  function moveSizeField(key, direction) {
    const ordered = sizeDisplayFields().map((field) => field.key);
    const index = ordered.indexOf(key);
    const nextIndex = index + direction;
    if (index < 0 || nextIndex < 0 || nextIndex >= ordered.length) return;
    const [item] = ordered.splice(index, 1);
    ordered.splice(nextIndex, 0, item);
    // 当前类别隐藏的列留在原位，只重排可见列
    const merged = allSizeDisplayFields().map((field) => (hiddenForVehicleKind(field.key) ? field.key : ordered.shift()));
    const mergedSet = new Set(merged);
    searchState.fieldOrder = [...merged, ...searchState.fieldOrder.filter((field) => !mergedSet.has(field))];
  }

  function sortSizeRows(rows) {
    if (!searchState.sortField) return rows;
    const direction = searchState.sortDirection === "desc" ? -1 : 1;
    return [...rows].sort((left, right) => compareSortValues(left, right, searchState.sortField) * direction);
  }

  function compareSortValues(left, right, field) {
    if (isSizeColumn(field)) {
      return compareSizeValues(resultColumnValue(left, field), resultColumnValue(right, field));
    }
    if (isRangeFilterColumn(field)) {
      return compareValues(sizeColumnFilterValue(left, field), sizeColumnFilterValue(right, field));
    }
    return compareValues(resultColumnValue(left, field), resultColumnValue(right, field));
  }

  function compareSizeValues(left, right) {
    const leftRank = sizeReferenceRank(left);
    const rightRank = sizeReferenceRank(right);
    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }
    return compareValues(left, right);
  }

  function sizeReferenceRank(value) {
    const key = cleanField(value).toUpperCase();
    return sizeReferenceOrder.has(key) ? sizeReferenceOrder.get(key) : Number.MAX_SAFE_INTEGER;
  }

  function formatCount(value) {
    return new Intl.NumberFormat("en-US").format(value);
  }

  function recordFilterValue(record, column) {
    return cleanField(resultColumnValue(record, column));
  }

  function constructAtoms(record) {
    return filterAtoms(record, "construct");
  }

  function filterAtoms(record, key) {
    const value = configuredRecordValue(record, key);
    return filterConfig(key).atomize === false ? [cleanField(value)].filter(Boolean) : fieldAtoms(value);
  }

  function configuredRecordValue(record, key) {
    const source = filterConfig(key).source || tableFieldConfig(key).source;
    if (key === "construct") {
      return record.construct || sourceValue(record, source) || record.values.CONSTRUCT;
    }
    if (key === "const") {
      return record.construct || sourceValue(record, source) || record.values.CONSTRUCT;
    }
    if (key === "cab") {
      return record.cab || (source && !sameColumn(source, "CAB") ? sourceValue(record, source) : "");
    }
    if (key === "bed") {
      return record.bed || sourceValue(record, source);
    }
    return sourceValue(record, source);
  }

  function sourceValue(record, source) {
    return cleanField(record.values[source] || record.values[cleanField(source).toUpperCase()] || record.values[cleanField(source).toLowerCase()]);
  }

  function dimensionSourceValue(record, column) {
    const candidates = dimensionSourceColumns(column);
    for (const candidate of candidates) {
      const value = sourceValue(record, candidate) || record.values[candidate];
      if (cleanField(value)) return cleanField(value);
    }
    return "";
  }

  function dimensionSourceColumns(column) {
    if (["L-MM", "L-CM", "L-IN", "长_mm", "长_cm", "长_in"].some((item) => sameColumn(column, item))) {
      return ["L-MM", "长_mm"];
    }
    if (["W-MM", "W-CM", "W-IN", "宽_mm", "宽_cm", "宽_in"].some((item) => sameColumn(column, item))) {
      return ["W-MM", "宽_mm"];
    }
    if (["H-MM", "H-CM", "H-IN", "高_mm", "高_cm", "高_in"].some((item) => sameColumn(column, item))) {
      return ["H-MM", "高_mm"];
    }
    return [column];
  }

  function numericDisplayValue(value) {
    const number = Number(value);
    return Number.isFinite(number) ? String(Math.round(number)) : "";
  }

  function filterConfig(key) {
    return { ...(defaultViewConfig.filters[key] || {}), ...(viewConfig.filters?.[key] || {}) };
  }

  function tableFieldConfig(key) {
    return { ...(defaultViewConfig.table_fields[key] || {}), ...(viewConfig.table_fields?.[key] || {}) };
  }

  async function loadViewConfig() {
    if (!config.viewConfigPath) {
      return;
    }
    try {
      const response = await fetch(config.viewConfigPath, { cache: "no-cache" });
      if (response.ok) {
        viewConfig = mergeViewConfig(defaultViewConfig, parseSizeViewYaml(await response.text()));
      }
    } catch (error) {
      viewConfig = defaultViewConfig;
    }
    applyPageMatchConfig();
    searchState.selectedSource = defaultSourceFilter();
  }

  function defaultSourceFilter() {
    return cleanField(viewConfig.match_sources?.[0]?.name);
  }

  async function loadSizeReferences() {
    const path = viewConfig.size_reference?.data_path || config.sizeRefPath;
    if (!path) return;
    try {
      const response = await fetch(path, { cache: "no-cache" });
      if (!response.ok) return;
      const text = await response.text();
      const rows = path.endsWith(".json") ? (JSON.parse(text).rows || []) : parseTsv(text);
      const matchField = viewConfig.size_reference?.match_field || "通用尺码";
      sizeReferenceIndex.clear();
      sizeReferenceOrder.clear();
      rows.forEach((row, index) => {
        [row[matchField], row["型号"], row["内部尺码"], row["通用尺码"]].forEach((value) => {
          const key = cleanField(value).toUpperCase();
          if (key && !sizeReferenceIndex.has(key)) {
            sizeReferenceIndex.set(key, row);
          }
          if (key && !sizeReferenceOrder.has(key)) {
            sizeReferenceOrder.set(key, index);
          }
        });
      });
    } catch (error) {
      sizeReferenceIndex.clear();
      sizeReferenceOrder.clear();
    }
  }

  async function loadSizeRules() {
    const readJson = async (path) => {
      try {
        const response = await fetch(path, { cache: "no-cache" });
        return response.ok ? await response.json() : null;
      } catch (error) {
        return null;
      }
    };
    const [rules, groups] = await Promise.all([
      readJson(config.sizeRulesPath || "data/generated/size-rules.json"),
      readJson(config.storeGroupsPath || "data/generated/store-groups.json")
    ]);
    sizeRulesOrigin = rules?.source || null;
    storeGroupsOrigin = groups?.source || null;
    sizeRules.load(rules, groups);
  }

  function resultHeaderClass(column) {
    if (column.dimension) return `dimension-heading size-sticky-heading ${sizeStickyClass(column.key)}`;
    if (isLengthMarginColumn(column.key)) return `dimension-heading size-sticky-heading ${sizeStickyClass(column.key)}`;
    if (column.size) return "size-heading size-sticky-heading size-sticky-size";
    return "";
  }

  function resultTableWidth(columns) {
    return columns.reduce((total, column) => {
      const width = searchState.columnWidths[column.key] || column.width || defaultResultColumnWidth(column.key);
      const number = Number.parseFloat(width);
      return total + (Number.isFinite(number) ? number : 118);
    }, 0);
  }

  function defaultResultColumnWidth(column) {
    return autoColumnWidth(column, column);
  }

  // 自动列宽：不小于表头（小字列名 + 排序箭头 + 筛选按钮）所需宽度；内容取当前页最宽值。
  // 可换行的文本列先按内容完整宽度排，放不下时才由 fitColumnsToContainer 压缩（才会换行）。
  const textWidthCache = new Map();
  let measureContext;

  function tableFontPixels() {
    return { sm: 15, md: 17, lg: 19 }[searchState.tableFontSize] || 17;
  }

  function measureTextWidth(text, weight, scale = 1) {
    const size = tableFontPixels() * scale;
    const cacheKey = `${weight}|${size}|${text}`;
    if (textWidthCache.has(cacheKey)) return textWidthCache.get(cacheKey);
    if (measureContext === undefined) measureContext = document.createElement("canvas").getContext("2d");
    let width;
    if (measureContext) {
      measureContext.font = `${weight} ${size}px ${getComputedStyle(app).fontFamily || "sans-serif"}`;
      width = measureContext.measureText(text).width;
    } else {
      width = Array.from(text).reduce((total, char) => total + (char.charCodeAt(0) > 255 ? size : size * 0.6), 0);
    }
    textWidthCache.set(cacheKey, width);
    return width;
  }

  function columnWidthCap(column) {
    return isWrappableColumn(column) ? Infinity : 180;
  }

  function cellDisplayText(record, column) {
    if (sameColumn(column, "MAKE")) return record.make || "";
    const value = resultColumnValue(record, column);
    if (isSalesTotalColumn(column)) return formatSalesTotal(value) || "-";
    if (isLengthMarginColumn(column)) return lengthMarginDisplay(value) || "-";
    if (isDimensionColumn(column)) return dimensionDisplay(column, value) || "-";
    if (isSizeColumn(column)) return value || "NULL";
    return value || "";
  }

  // quantile < 1 时取该分位行的内容宽度（如 0.95：95% 的行放得下），用作压缩下限
  function contentColumnWidth(column, records, quantile = 1) {
    const widths = records.map((record) => {
      const text = cellDisplayText(record, column);
      return text ? measureTextWidth(text, 700) : 0;
    });
    if (!widths.length) return 18;
    widths.sort((a, b) => a - b);
    return widths[Math.ceil(quantile * widths.length) - 1] + 18;  // 单元格左右内边距 7px×2 + 余量
  }

  function isWrappableColumn(column) {
    return ["MODEL", "版本", "TYPE", "CONST", "CAB"].some((key) => sameColumn(column, key));
  }

  // 总宽超出可视区时，先把可换行的文本列压缩，减少被右侧固定列遮挡的列；下限为表头宽度与 95% 行内容宽度的较大者，
  // 只有少数超长值换行，再放不下就横向滚动（尽量不出现多行）。
  // 有富余时只把富余分给可换行的文本列，数字列保持紧凑（否则 table-layout: fixed 会按比例撑宽所有列）
  function fitColumnsToContainer(columns, records) {
    // 以表格容器外宽减去滚动条预留为准：渲染时容器和页面可能都还没有纵向滚动条（宽度偏大），
    // 渲染后出现会挤出横向滚动，所以两条都预留；首次渲染时容器尚不存在，用结果区宽度
    const wrap = app.querySelector(".size-results-wrap");
    const available = (wrap ? wrap.offsetWidth : app.querySelector(".search-results")?.clientWidth || 0) - 36;
    if (available <= 0) return;
    const pixels = (column) => Number.parseFloat(searchState.columnWidths[column.key] || column.width) || 0;
    const excess = columns.reduce((total, column) => total + pixels(column), 0) - available;
    const flexible = columns.filter((column) => !searchState.columnWidths[column.key] && isWrappableColumn(column.key));
    if (excess <= 0) {
      // 余下的几像素由表格 width: max(100%, …) 补满
      const slack = -excess;
      const total = flexible.reduce((sum, column) => sum + pixels(column), 0);
      if (slack <= 0 || !total) return;
      flexible.forEach((column) => {
        column.width = `${Math.floor(pixels(column) + slack * pixels(column) / total)}px`;
      });
      return;
    }
    const floor = (column) => Math.ceil(Math.max(headerColumnWidth(column.label), contentColumnWidth(column.key, records, 0.95)));
    const room = flexible.map((column) => Math.max(0, pixels(column) - floor(column)));
    const totalRoom = room.reduce((total, value) => total + value, 0);
    if (!totalRoom) return;
    const ratio = Math.min(1, excess / totalRoom);
    flexible.forEach((column, index) => {
      column.width = `${Math.floor(pixels(column) - room[index] * ratio)}px`;
    });
  }

  // 表头列名比单元格小一号（viewer.css .size-results-table th 0.8em），避免短内容列被列名撑宽
  const HEADER_FONT_SCALE = 0.8;

  function headerColumnWidth(label) {
    // 左右内边距 5+4 + 文字 + 间距 2 + 箭头 7 + 间距 2 + 筛选按钮 14 + 余量 2
    return measureTextWidth(String(label), 800, HEADER_FONT_SCALE) + 36;
  }

  function autoColumnWidth(column, label, records = [], hasToggle = false) {
    const header = headerColumnWidth(label);
    // 展开开关列（CODE，或无 CODE 时的 MAKE）带三角 + 来源条数（两位数徽标）+ 900 粗体，多留位置，避免徽标被挤到第二行
    const toggle = hasToggle ? 48 : 0;
    // SHAPE 以小字显示（viewer.css .shape-cell 0.78em），按缩小后的宽度留位置
    const scale = sameColumn(column, "SHAPE") ? 0.8 : 1;
    const content = Math.min(contentColumnWidth(column, records) * scale, columnWidthCap(column)) + toggle;
    return `${Math.ceil(Math.max(header, content, 56))}px`;
  }

  function bindResultColumnResizers() {
    const table = app.querySelector(".size-results-table");
    if (!table) return;
    updateStickyColumnOffsets(table);
    table.querySelectorAll(".col-resizer").forEach((handle) => {
      handle.addEventListener("pointerdown", (event) => {
        const key = handle.dataset.colKey;
        const col = table.querySelector(`col[data-col-key="${cssEscape(key)}"]`);
        if (!col) return;
        event.preventDefault();
        const startX = event.clientX;
        const startWidth = col.getBoundingClientRect().width || 96;
        document.body.classList.add("is-resizing-column");

        const onPointerMove = (moveEvent) => {
          const width = Math.max(56, Math.round(startWidth + moveEvent.clientX - startX));
          searchState.columnWidths[key] = `${width}px`;
          col.style.width = searchState.columnWidths[key];
          updateStickyColumnOffsets(table);
        };

        const stopResize = () => {
          document.body.classList.remove("is-resizing-column");
          document.removeEventListener("pointermove", onPointerMove);
          document.removeEventListener("pointerup", stopResize);
          document.removeEventListener("pointercancel", stopResize);
        };

        document.addEventListener("pointermove", onPointerMove);
        document.addEventListener("pointerup", stopResize);
        document.addEventListener("pointercancel", stopResize);
      });
    });
  }

  function updateStickyColumnOffsets(table) {
    const [lColumn, wColumn, hColumn] = activeDimensionColumns();
    const widthFor = (key, fallback) => {
      const col = table.querySelector(`col[data-col-key="${cssEscape(key)}"]`);
      if (!col) return "0px";  // 页面没有该列（如压缩代号页无 长度余量），右侧固定列不留空位
      const width = col.getBoundingClientRect().width;
      return Number.isFinite(width) && width > 0 ? `${Math.round(width)}px` : fallback;
    };
    table.style.setProperty("--sticky-l-width", widthFor(lColumn, "82px"));
    table.style.setProperty("--sticky-w-width", widthFor(wColumn, "82px"));
    table.style.setProperty("--sticky-h-width", widthFor(hColumn, "82px"));
    table.style.setProperty("--sticky-margin-width", widthFor("长度余量", "100px"));
    table.style.setProperty("--sticky-size-width", widthFor("SIZE", "104px"));
  }

  function isSizeColumn(column) {
    return sameColumn(column, "SIZE");
  }

  function isDimensionColumn(column) {
    return ["L-MM", "W-MM", "H-MM", "L-CM", "W-CM", "H-CM", "L-IN", "W-IN", "H-IN", "长_mm", "宽_mm", "高_mm", "长_cm", "宽_cm", "高_cm", "长_in", "宽_in", "高_in"].some((item) => sameColumn(column, item));
  }

  function isLengthMarginColumn(column) {
    return sameColumn(column, "长度余量");
  }

  function isSalesTotalColumn(column) {
    return sameColumn(column, "销量合计");
  }

  function isRangeFilterColumn(column) {
    return isDimensionColumn(column) || isLengthMarginColumn(column) || isSalesTotalColumn(column);
  }

  function sizeStickyClass(column) {
    if (["L-MM", "L-CM", "L-IN", "长_mm", "长_cm", "长_in"].some((item) => sameColumn(column, item))) return "size-sticky-l";
    if (["W-MM", "W-CM", "W-IN", "宽_mm", "宽_cm", "宽_in"].some((item) => sameColumn(column, item))) return "size-sticky-w";
    if (["H-MM", "H-CM", "H-IN", "高_mm", "高_cm", "高_in"].some((item) => sameColumn(column, item))) return "size-sticky-h";
    if (isLengthMarginColumn(column)) return "size-sticky-margin";
    if (sameColumn(column, "SIZE")) return "size-sticky-size";
    return "";
  }

  function activeDimensionColumns() {
    const suffix = searchState.dimensionUnit.toUpperCase();
    return [`L-${suffix}`, `W-${suffix}`, `H-${suffix}`];
  }

  function sameColumn(left, right) {
    return cleanField(left).toUpperCase() === cleanField(right).toUpperCase();
  }

  function pagePathByName(directoryName, file) {
    const directory = directories.find((item) => item.name === directoryName) || chartDirectories()[0] || directories[0];
    return directory ? pagePath(directory, file) : "#";
  }

  function topSource(directoryName) {
    return String(directoryName || "").split(/[\\/]/)[0] || directoryName;
  }

  function fillSelect(select, label, options, selectedValue) {
    select.innerHTML = `<option value="">${label}</option>${options.map((option) => (
      `<option value="${escapeHtml(option)}"${option === selectedValue ? " selected" : ""}>${escapeHtml(option)}</option>`
    )).join("")}`;
  }

  function recordMatchesToken(record, token) {
    const sourceOnlyTokens = ["pick", "nonpick", "tm", "宏能图"];
    if (sourceOnlyTokens.includes(token) && record.sourceTags.includes(token)) {
      return true;
    }
    if (sourceOnlyTokens.includes(token)) {
      return false;
    }
    if (record.sourceTags.some((tag) => tag === token || tag.replace(/[-_/]+/g, "") === token)) {
      return true;
    }
    const vehicleCode = decodeVehicleCode(token);
    if (vehicleCode && recordMatchesVehicleCode(record, vehicleCode)) {
      return true;
    }
    // 按字段语义匹配（viewer-data.js recordMatchesSearchToken）：数字只比年份、CODE、车型/版本单词，不再整行子串匹配
    return recordMatchesSearchToken(record, token, shapeLabels);
  }

  // 8 位车型代码 = MAKE_CODE(2) + MODEL_CODE(2) + 起始年(2) + 结束年(2)，如 01039426 = Ford Mustang 1994-2026。
  // 前四位查 vehicle-codes.json；两位年份不晚于明年按 20xx，否则按 19xx
  function decodeVehicleCode(token) {
    const match = /^(\d{4})(\d{2})(\d{2})$/.exec(token);
    const entry = match && vehicleCodes?.[match[1]];
    if (!entry) return null;
    const pivot = (new Date().getFullYear() + 1) % 100;
    const fullYear = (value) => (Number(value) <= pivot ? 2000 : 1900) + Number(value);
    const start = fullYear(match[2]);
    const end = fullYear(match[3]);
    if (start > end) return null;
    return { code: token, make: entry.make, model: entry.model, kinds: entry.kinds || [], start, end };
  }

  function queryVehicleCodes() {
    return searchTokens(searchState.query).map(decodeVehicleCode).filter(Boolean);
  }

  function vehicleCodeHint() {
    return queryVehicleCodes()
      .map((code) => `车型代码 ${code.code} = ${code.make} ${code.model} ${code.start}-${code.end}；`)
      .join("");
  }

  function loadVehicleCodes() {
    if (!vehicleCodesPromise) {
      vehicleCodesPromise = fetchJsonWithRetry(config.vehicleCodesPath || "data/generated/vehicle-codes.json")
        .then((payload) => { vehicleCodes = payload.codes || {}; })
        .catch(() => { vehicleCodes = {}; });  // 代码表缺失时退回普通文本检索（压缩代号页仍可按 CODE 列精确匹配）
    }
    return vehicleCodesPromise;
  }

  // 有搜索词时先加载代码表，按查询识别车型所在类别（皮卡/非皮卡）并切换：8 位代码按代码车型的类别（当前类别已包含时不动），
  // 否则按查询提到的 MAKE/MODEL（viewer-data.js queryVehicleKind）。识别为皮卡时同时切到全量表（keepView：首屏 URL 指定了视图）。
  // 识别结果与上次相同则不再切换，用户切换后继续输入不会被拉回。
  async function applyQueryVehicleKind({ keepView = false } = {}) {
    const tokens = searchQueryTokens(searchState.query);
    if (!tokens.length) {
      lastAutoKind = "";
      return;
    }
    await loadVehicleCodes();
    const codeKinds = uniqueInOrder(queryVehicleCodes().flatMap((code) => code.kinds));
    const kind = codeKinds.length
      ? (codeKinds.includes(searchState.vehicleKind) ? searchState.vehicleKind : codeKinds[0])
      : queryVehicleKind(tokens, vehicleCodes);
    if (kind === lastAutoKind) return;
    lastAutoKind = kind;
    if (!kind) return;
    const mode = kind === "pick" && !keepView && tableModes().some((item) => item.key === "full") ? "full" : searchState.tableMode;
    if (kind === searchState.vehicleKind && mode === searchState.tableMode) return;
    searchState.vehicleKind = kind;
    searchState.availableMakes = [];
    searchState.scopeKey = "";
    if (mode !== searchState.tableMode) {
      searchState.tableMode = mode;
      searchState.columnFilters = {};
      searchState.openFilter = "";
      searchState.sortField = "";
      searchState.sortDirection = "asc";
      searchState.resultPage = 1;
      searchState.resetResultScroll = true;
      syncTableModeUrl();
    }
    const toggle = (selector, key, value) => app.querySelectorAll(selector).forEach((button) => {
      const active = button.dataset[key] === value;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    toggle("[data-vehicle-kind]", "vehicleKind", searchState.vehicleKind);
    toggle("[data-table-mode]", "tableMode", searchState.tableMode);
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/"/g, '\\"');
  }

  function measureFrame(frame) {
    try {
      const doc = frame.contentDocument;
      const rootStyle = doc.defaultView.getComputedStyle(doc.documentElement);
      const bodyStyle = doc.defaultView.getComputedStyle(doc.body);
      const cssWidth = parseFloat(rootStyle.getPropertyValue("--page-width"));
      const cssHeight = parseFloat(rootStyle.getPropertyValue("--page-height"));
      const measuredWidth = Math.max(doc.documentElement.scrollWidth, doc.body.scrollWidth);
      const measuredHeight = Math.max(doc.documentElement.scrollHeight, doc.body.scrollHeight);

      frameStates.set(frame, {
        width: cssWidth || parseFloat(bodyStyle.minWidth) || measuredWidth || 2000,
        height: cssHeight || measuredHeight || 1800
      });
    } catch (error) {
      frameStates.set(frame, { width: 2000, height: 1800 });
    }
  }

  function resizeFrames() {
    app.querySelectorAll(".page-frame").forEach((frame) => {
      const shell = frame.closest(".frame-shell");
      const state = frameStates.get(frame) || { width: 2000, height: 1800 };
      const availableWidth = shell.clientWidth;
      const scale = availableWidth / state.width;

      frame.style.width = `${state.width}px`;
      frame.style.height = `${state.height}px`;
      frame.style.transform = `scale(${scale})`;
      shell.style.height = `${Math.ceil(state.height * scale)}px`;
    });
  }

  window.addEventListener("resize", resizeFrames);
  let tableRefitTimer = 0;
  window.addEventListener("resize", () => {
    if (!app.querySelector(".size-results-table")) return;
    window.clearTimeout(tableRefitTimer);
    tableRefitTimer = window.setTimeout(updateSearchResults, 150);  // 窗口宽度变化后重新适配列宽
  });
  document.addEventListener("pointerdown", (event) => {
    if (!searchState.openFilter) return;
    if (event.target.closest?.(".header-filter-popover, [data-size-open-filter]")) return;
    closeHeaderFilter();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && searchState.openFilter) closeHeaderFilter();
  });
  document.fonts?.ready.then(() => {
    textWidthCache.clear();
    if (app.querySelector(".size-results-table")) updateSearchResults();
  });
  loadViewConfig().then(() => Promise.all([loadSizeReferences(), loadSizeRules()])).then(render);
})();
