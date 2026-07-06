(function () {
  const config = window.SIZE_CHART_VIEWER;
  const app = document.getElementById("app");

  if (!config || !app) {
    return;
  }

  const directories = config.directories || [];
  const pageMode = config.pageMode || "search";
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
  const sizeReferenceIndex = new Map();
  const defaultSourceFilter = "ALL";
  const searchState = {
    scopeKey: "",
    records: [],
    columns: [],
    query: initialQuery(),
    selectedSource: defaultSourceFilter,
    selectedMake: "",
    selectedModel: "",
    selectedYear: "",
    selectedConstruct: "",
    selectedCab: "",
    selectedBed: "",
    columnFilters: {},
    openFilter: "",
    columnWidths: {},
    visibleColumns: null,
    fieldOrder: [],
    dimensionUnit: "imperial",
    resultLimit: 200,
    resultPage: 1,
    sortField: "",
    sortDirection: "asc",
    status: "idle",
    message: ""
  };
  const resultRenderLimit = 200;
  let searchLoadToken = 0;
  let frameSearchTimer = 0;
  let headerFilterCloseTimer = 0;

  function initialQuery() {
    return new URLSearchParams(window.location.search).get("q") || "";
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

  function sourceOutlineMarkup() {
    const configuredSources = (viewConfig.match_sources || []).map((source) => source.name).filter(Boolean);
    const loadedSources = uniqueInOrder(searchState.records.map((record) => sourceFilterValue(record)));
    const sources = uniqueInOrder([...configuredSources, ...loadedSources]);
    return `
      <ol class="chart-outline-list source-outline-list">
        <li>
          <button class="chart-outline-node source-outline-node${searchState.selectedSource ? "" : " is-active"}" type="button" data-sidebar-source="">
            <span class="chart-outline-dot"></span>
            <span>全部</span>
          </button>
        </li>
        ${sources.map((source) => `
          <li>
            <button class="chart-outline-node source-outline-node${searchState.selectedSource === source ? " is-active" : ""}" type="button" data-sidebar-source="${escapeHtml(source)}">
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
            <a class="${!isSearchPage ? "is-active" : ""}" href="size-charts.html" title="Size Chart"><span class="nav-icon">S</span><span class="nav-label">Size Chart</span></a>
            <a href="size-ref.html" title="尺码参考"><span class="nav-icon">参</span><span class="nav-label">尺码参考</span></a>
            <a class="${isSearchPage ? "is-active" : ""}" href="size-chart.html" title="尺码配对"><span class="nav-icon">尺</span><span class="nav-label">尺码配对</span></a>
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
                <button type="button" data-size-unit="imperial" class="${searchState.dimensionUnit === "imperial" ? "is-active" : ""}">IN</button>
                <button type="button" data-size-unit="metric" class="${searchState.dimensionUnit === "metric" ? "is-active" : ""}">CM</button>
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
              <input class="global-search-input" type="search" value="${escapeHtml(searchState.query)}" placeholder="Search nonpick, pick, 宏能图, TM, make, model, type, size, year..." autocomplete="off">
            </label>
            <button class="search-reset" type="button">Reset</button>
          </div>
          <div class="search-summary" role="status"></div>
          <div class="active-filter-chips" aria-label="Active filters"></div>
          <div class="search-results"></div>
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
      loadSearchIndex(currentSearchDirectories());
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
        searchState.selectedMake = "";
        searchState.selectedModel = "";
        searchState.selectedYear = "";
        searchState.selectedConstruct = "";
        searchState.selectedCab = "";
        searchState.selectedBed = "";
        searchState.resultPage = 1;
        render();
      });
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
      searchState.query = globalInput.value;
      resetSearchFilters();
      loadSearchIndex(currentSearchDirectories());
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
        searchState.resultLimit = control.value === "all" ? "all" : Number(control.value);
        searchState.resultPage = 1;
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
        searchState.dimensionUnit = button.dataset.sizeUnit || "imperial";
        ensureSizeFieldState();
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
      searchState.query = "";
      resetSearchFilters();
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

  function resetSearchFilters() {
    searchState.selectedSource = defaultSourceFilter;
    searchState.selectedMake = "";
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
    if (!scopeDirectories.length) {
      return;
    }

    const token = ++searchLoadToken;
    const scopeKey = scopeDirectories.map((directory) => directory.name).join("|");
    if (searchState.scopeKey === scopeKey && (searchState.status === "ready" || searchState.status === "loading")) {
      updateSearchControls();
      updateSearchResults();
      return;
    }
    searchState.scopeKey = scopeKey;
    searchState.records = [];
    searchState.columns = [];
    searchState.status = "loading";
    searchState.message = "Loading records...";
    updateSearchControls();
    updateSearchResults();

    try {
      const indexes = viewConfig.match_sources?.length
        ? await loadConfiguredMatchIndexes()
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
      const response = await fetch(pagePath(directory, file), { cache: "no-store" });
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

  function setSearchIndex(scopeKey, records, columns) {
    searchState.scopeKey = scopeKey;
    searchState.records = records;
    searchState.columns = columns;
    searchState.status = "ready";
    searchState.message = records.length ? `全量尺码数据：已索引 ${formatCount(records.length)} 条记录。` : "未读取到表格记录。";
    ensureSizeFieldState();
    if (pageMode !== "charts") {
      render();
      return;
    }
    updateSearchControls();
    updateSearchResults();
  }

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
      const response = await fetch(`${config.basePath}${directory.name}/output_generation.log`, { cache: "no-store" });
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

    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Cannot load ${path}`);
    }
    const rows = parseTsv(await response.text());
    tsvIndexes.set(path, rows);
    return rows;
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
    const modelRecords = sourceRecords.filter((record) => !searchState.selectedMake || record.make === searchState.selectedMake);
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

    if (searchState.status === "loading" || searchState.status === "error") {
      summary.textContent = searchState.message;
      results.innerHTML = "";
      return;
    }

    const queryRecords = queryFilteredRecords();
    if (!queryRecords.length) {
      summary.textContent = searchState.query.trim() ? "未找到匹配记录。" : searchState.message;
      results.innerHTML = "";
      return;
    }

    const matches = sortSizeRows(getSearchMatches());
    const limit = pageSizeFor(matches.length);
    const maxPage = Math.max(1, Math.ceil(matches.length / limit));
    searchState.resultPage = Math.min(maxPage, Math.max(1, searchState.resultPage || 1));
    const start = (searchState.resultPage - 1) * limit;
    const visibleMatches = matches.slice(start, start + limit);
    summary.textContent = matches.length > visibleMatches.length
      ? `匹配结果：${formatCount(matches.length)} 条记录，当前第 ${formatCount(searchState.resultPage)} / ${formatCount(maxPage)} 页。`
      : `匹配结果：${formatCount(matches.length)} 条记录。`;
    updateActiveFilterChips();
    bindActiveFilterChips();
    results.innerHTML = renderResultsTable(visibleMatches, matches.length, maxPage);
    bindResultColumnResizers();
    bindSizeLinkedRows();
    bindSizeHeaderFilterPopovers();
    bindSizeTableFilters();
    bindSizeReferenceHovers();
  }

  function getSearchMatches() {
    return queryFilteredRecords().filter((record) => {
      if (searchState.selectedMake && record.make !== searchState.selectedMake) {
        return false;
      }
      if (searchState.selectedSource && sourceFilterValue(record) !== searchState.selectedSource) {
        return false;
      }
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

  async function loadConfiguredMatchIndexes() {
    const path = viewConfig.excel_source?.match_data_path || defaultViewConfig.excel_source.match_data_path;
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Cannot load ${path}`);
    }
    const payload = await response.json();
    const configuredSources = viewConfig.match_sources || [];
    const configuredNames = configuredSources.map((source) => source.name);
    const sources = (payload.sources || []).filter((source) => !configuredNames.length || configuredNames.includes(source.name));
    return sources.map((source) => {
      const configured = configuredSources.find((item) => item.name === source.name) || {};
      const columns = csvList(configured.columns).length ? csvList(configured.columns) : (source.columns || payload.columns || []);
      const records = (source.records || []).map((record) => ({
        ...record,
        directory: source.name,
        source: source.label || configured.label || source.name,
        sourceTags: [String(source.name || "").toLowerCase()]
      }));
      return { records, columns };
    });
  }

  function queryFilteredRecords() {
    const tokens = searchTokens(searchState.query);
    if (!tokens.length) {
      return searchState.records;
    }

    return searchState.records.filter((record) => tokens.every((token) => recordMatchesToken(record, token)));
  }

  function renderResultsTable(records, totalCount, maxPage) {
    if (!records.length) {
      return '<div class="empty-results">No rows match the current selection.</div>';
    }

    const columns = resultColumns(records);
    const tableColumns = [
      { key: "MAKE", label: "MAKE", width: "105px" },
      ...columns.map((column) => ({
        key: column,
        label: column,
        dimension: isDimensionColumn(column),
        size: isSizeColumn(column),
        width: defaultResultColumnWidth(column)
      }))
    ];
    const tableWidth = resultTableWidth(tableColumns);
    return `
      <div class="results-table-wrap size-results-wrap">
        <table class="results-table size-results-table ${searchState.dimensionUnit === "metric" ? "dimension-theme-yellow" : "dimension-theme-blue"}" style="--result-table-width: ${tableWidth}px">
          <colgroup>
            ${tableColumns.map((column) => {
              const width = searchState.columnWidths[column.key] || column.width;
              return `<col data-col-key="${escapeHtml(column.key)}"${width ? ` style="width: ${escapeHtml(width)}"` : ""}>`;
            }).join("")}
          </colgroup>
          <thead>
            <tr>
              ${tableColumns.map((column) => `
                <th class="${resultHeaderClass(column)}${searchState.openFilter === column.key ? " is-filter-open" : ""}" data-col-key="${escapeHtml(column.key)}">
                  ${sizeHeaderLabelMarkup(column)}
                  ${sizeHeaderFilterMarkup(column, tableColumns)}
                  <span class="col-resizer" data-col-key="${escapeHtml(column.key)}" title="拖动调整列宽" aria-hidden="true"></span>
                </th>
              `).join("")}
            </tr>
          </thead>
          <tbody>
            ${records.map((record) => `
              <tr>
                ${tableColumns.map((column) => resultCellMarkup(record, column)).join("")}
              </tr>
            `).join("")}
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
            <option value="all"${searchState.resultLimit === "all" ? " selected" : ""}>全部</option>
          </select>
        </label>
      </div>
    `;
  }

  function pageSizeFor(totalCount) {
    if (searchState.resultLimit === "all") {
      return Math.max(1, totalCount);
    }
    return Math.max(1, Number(searchState.resultLimit) || 200);
  }

  function resultColumns(records) {
    const usedColumns = searchState.columns;
    const fallbackColumns = ["MODEL", "版本", "YEAR", "TYPE", "CAB", "BED", "SIZE"];
    const columns = usedColumns.length ? usedColumns : fallbackColumns;
    const withModel = records.some((record) => record.model) && !columns.some((column) => sameColumn(column, "MODEL"))
      ? ["MODEL", ...columns]
      : columns;
    const ordered = sortSizeFields(withModel.map((column) => ({ key: column, label: column }))).map((field) => field.key);
    const visible = ordered.filter((column) => isSizeColumnVisible(column) || isSizeColumn(column));
    const rightColumns = [...activeDimensionColumns(), "长度余量"].filter((column) => visible.some((item) => sameColumn(item, column)) || records.some((record) => resultColumnValue(record, column)));
    const withoutRight = visible.filter((column) => !isSizeColumn(column) && !isDimensionColumn(column) && !isLengthMarginColumn(column) && !rightColumns.some((item) => sameColumn(item, column)));
    const hasSize = withModel.some((column) => isSizeColumn(column)) || records.some((record) => record.values.SIZE || record.size);
    return hasSize ? [...withoutRight, ...rightColumns, "SIZE"] : [...withoutRight, ...rightColumns];
  }

  function resultCellMarkup(record, column) {
    const value = column.key === "MAKE" ? record.make : resultColumnValue(record, column.key);
    if (column.dimension || isLengthMarginColumn(column.key)) {
      const displayValue = isLengthMarginColumn(column.key) ? lengthMarginDisplay(value) : dimensionDisplay(column.key, value);
      return `<td class="dimension-cell size-dimension-cell size-sticky-col ${sizeStickyClass(column.key)}" style="${escapeHtml(isLengthMarginColumn(column.key) ? lengthMarginStyle(value) : "")}"><strong>${escapeHtml(displayValue || "-")}</strong></td>`;
    }
    if (column.size) {
      const ref = sizeReferenceFor(value);
      const refAttr = ref ? ` data-size-ref="${escapeHtml(cleanField(value).toUpperCase())}"` : "";
      const refClass = ref ? " size-cell-has-ref" : "";
      const displayValue = value || "NULL";
      return `<td class="size-cell size-sticky-col size-sticky-size${refClass}"${refAttr} style="--size-bg: ${sizeBackground(value)}; --size-fg: #ffffff"><strong>${escapeHtml(displayValue)}</strong></td>`;
    }
    return `<td>${escapeHtml(value || "")}</td>`;
  }

  function sizeHeaderLabelMarkup(column) {
    const filterValue = searchState.columnFilters[column.key];
    const filteredClass = hasColumnFilterValue(filterValue) ? " is-filtered" : "";
    return `
      <button class="th-label th-filter-trigger${filteredClass}" type="button" data-size-open-filter="${escapeHtml(column.key)}" aria-expanded="${searchState.openFilter === column.key ? "true" : "false"}" title="筛选 ${escapeHtml(column.label)}">
        <span>${escapeHtml(column.label)}</span>
      </button>
    `;
  }

  function sizeHeaderFilterMarkup(column, tableColumns) {
    if (searchState.openFilter !== column.key) return "";
    if (isRangeFilterColumn(column.key)) {
      const value = typeof searchState.columnFilters[column.key] === "object" ? searchState.columnFilters[column.key] : {};
      return `
        <div class="header-filter-popover header-filter-popover-wide">
          <div class="header-range-filter">
            <div class="range-inputs">
              <input type="number" step="0.1" data-size-range-filter="${escapeHtml(column.key)}" data-range-side="min" value="${escapeHtml(value.min || "")}" placeholder="Min">
              <input type="number" step="0.1" data-size-range-filter="${escapeHtml(column.key)}" data-range-side="max" value="${escapeHtml(value.max || "")}" placeholder="Max">
            </div>
          </div>
        </div>
      `;
    }
    if (sameColumn(column.key, "YEAR")) {
      const selected = arrayFilterValue(searchState.columnFilters[column.key]);
      const options = sizeFilterOptions(column, tableColumns).filter((option) => option.value);
      return `
        <div class="header-filter-popover header-filter-popover-wide">
          <div class="header-multi-filter" data-size-multi-group="${escapeHtml(column.key)}">
            ${options.map((option) => `
              <label class="header-multi-option">
                <input type="checkbox" data-size-multi-filter="${escapeHtml(column.key)}" value="${escapeHtml(option.value)}"${selected.includes(option.value) ? " checked" : ""}>
                <span>${escapeHtml(option.label)}</span>
              </label>
            `).join("")}
          </div>
        </div>
      `;
    }
    return `
      <div class="header-filter-popover">
        <div class="header-option-list" role="listbox" aria-label="筛选 ${escapeHtml(column.label)}">
          ${sizeFilterOptions(column, tableColumns).map((option) => {
            const current = searchState.columnFilters[column.key] || "";
            const active = option.value === current;
            return `<button class="header-option-item${active ? " is-active" : ""}" type="button" data-size-option-filter="${escapeHtml(column.key)}" data-filter-value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</button>`;
          }).join("")}
        </div>
      </div>
    `;
  }

  function sizeFilterOptions(column, tableColumns) {
    const currentValue = searchState.columnFilters[column.key] || "";
    const records = getSearchMatchesIgnoringColumn(column.key);
    const values = sortedSizeFilterValues(column.key, uniqueInOrder(records.flatMap((record) => sizeColumnFilterValues(record, column.key)).filter(Boolean)));
    const allLabel = `All ${column.label}`;
    const options = [{ value: "", label: allLabel }, ...values.map((value) => ({
      value,
      label: sameColumn(column.key, "SOURCE") ? sourceLabel(value) : value
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
    if (sameColumn(key, "BED")) {
      return [...values].sort(compareBedValues);
    }
    return values;
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
        if (chip.dataset.filterChipKind === "column") {
          delete searchState.columnFilters[chip.dataset.filterChipKey];
        } else {
          clearPrimaryFilter(chip.dataset.filterChipKey);
        }
        searchState.resultPage = 1;
        updateSearchControls();
        updateSearchResults();
      });
    });
  }

  function clearPrimaryFilter(key) {
    if (key === "source") {
      searchState.selectedSource = "";
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
    app.querySelectorAll("[data-size-option-filter]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", () => {
        const key = button.dataset.sizeOptionFilter;
        const value = button.dataset.filterValue || "";
        cancelHeaderFilterClose();
        if (value) {
          searchState.columnFilters[key] = value;
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
        searchState.resultLimit = control.value === "all" ? "all" : Number(control.value);
        searchState.resultPage = 1;
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
    app.querySelectorAll(".size-results-table th[data-col-key]").forEach((cell) => {
      if (cell.dataset.headerHoverBound === "true") return;
      cell.dataset.headerHoverBound = "true";
      cell.addEventListener("mouseenter", () => {
        cancelHeaderFilterClose();
        if (searchState.openFilter !== cell.dataset.colKey) {
          searchState.openFilter = cell.dataset.colKey;
          updateSearchResults();
        }
      });
    });
    app.querySelectorAll("[data-size-open-filter]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("mouseenter", () => {
        cancelHeaderFilterClose();
        if (searchState.openFilter !== button.dataset.sizeOpenFilter) {
          searchState.openFilter = button.dataset.sizeOpenFilter;
          updateSearchResults();
        }
      });
    });
    app.querySelectorAll(".size-results-table th.is-filter-open").forEach((cell) => {
      if (cell.dataset.hoverBound === "true") return;
      cell.dataset.hoverBound = "true";
      cell.addEventListener("mouseenter", cancelHeaderFilterClose);
      cell.addEventListener("mouseleave", () => {
        if (cell.contains(document.activeElement)) return;
        scheduleHeaderFilterClose();
      });
      cell.addEventListener("focusout", () => {
        window.setTimeout(() => {
          if (cell.matches(":hover") || cell.contains(document.activeElement)) return;
          scheduleHeaderFilterClose();
        }, 0);
      });
    });
  }

  function scheduleHeaderFilterClose() {
    cancelHeaderFilterClose();
    const popover = app.querySelector(".size-results-table th.is-filter-open .header-filter-popover");
    if (popover) {
      popover.classList.add("is-closing");
    }
    headerFilterCloseTimer = window.setTimeout(() => {
      headerFilterCloseTimer = 0;
      searchState.openFilter = "";
      updateSearchResults();
    }, 170);
  }

  function cancelHeaderFilterClose() {
    if (headerFilterCloseTimer) {
      window.clearTimeout(headerFilterCloseTimer);
      headerFilterCloseTimer = 0;
    }
    app.querySelectorAll(".header-filter-popover.is-closing").forEach((popover) => popover.classList.remove("is-closing"));
  }

  function bindSizeLinkedRows() {}

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
    if (isDimensionColumn(key) && searchState.dimensionUnit === "metric") {
      return dimensionDisplay(key, resultColumnValue(record, key));
    }
    if (isLengthMarginColumn(key) && searchState.dimensionUnit === "metric") {
      const number = Number(resultColumnValue(record, key));
      return Number.isFinite(number) ? (number * 2.54).toFixed(1) : "";
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
        const ref = sizeReferenceIndex.get(cell.dataset.sizeRef);
        if (!ref) return;
        floating.innerHTML = sizeReferenceMarkup(cell.textContent, ref);
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
        ${sizeReferenceDimension("长", ref["长_in"])}
        ${sizeReferenceDimension("宽", ref["宽_in"])}
        ${sizeReferenceDimension("高", ref["高_in"])}
      </div>
    `;
  }

  function sizeReferenceDimension(label, value) {
    const display = sizeReferenceDimensionDisplay(value);
    return `<span><em>${escapeHtml(label)}</em><strong>${escapeHtml(display || "-")}</strong></span>`;
  }

  function sizeReferenceDimensionDisplay(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return cleanField(value);
    }
    if (searchState.dimensionUnit === "metric") {
      return `${(number * 2.54).toFixed(1)} cm`;
    }
    return `${cleanField(value)} in`;
  }

  function sizeBackground(value) {
    const text = cleanField(value).toUpperCase();
    const ref = sizeReferenceFor(value);
    const colorKey = cleanField(ref?.["通用尺码"] || value).toUpperCase();
    const base = ({ A: "#1777c8", C: "#d62828", H: "#00a6a6", S: "#f28c28", T: "#6b7280" })[colorKey[0]] || "#6b7280";
    const number = Number((colorKey.match(/\d+/) || ["0"])[0]);
    return darkenHex(base, Math.min(0.34, Math.max(0, (number - 1) * 0.055)));
  }

  function lengthMarginStyle(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    if (number >= 5 && number <= 15) {
      return "--dimension-bg: #e6f6ec; --dimension-fg: #137333;";
    }
    const distance = number < 5 ? 5 - number : number - 15;
    const intensity = Math.min(1, distance / 15);
    const red = Math.round(244 - intensity * 80);
    const green = Math.round(226 - intensity * 150);
    const blue = Math.round(226 - intensity * 150);
    return `--dimension-bg: rgb(${red}, ${green}, ${blue}); --dimension-fg: #8a1f1f;`;
  }

  function lengthMarginDisplay(value) {
    const number = Number(value);
    if (searchState.dimensionUnit !== "metric" || !Number.isFinite(number)) {
      return value;
    }
    return (number * 2.54).toFixed(1);
  }

  function dimensionDisplay(column, value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return value;
    return searchState.dimensionUnit === "metric" && isDimensionColumn(column) ? number.toFixed(1) : value;
  }

  function darkenHex(hex, amount) {
    const normalized = hex.replace("#", "");
    const value = Number.parseInt(normalized, 16);
    if (!Number.isFinite(value)) return hex;
    const r = Math.round(((value >> 16) & 255) * (1 - amount));
    const g = Math.round(((value >> 8) & 255) * (1 - amount));
    const b = Math.round((value & 255) * (1 - amount));
    return `rgb(${r}, ${g}, ${b})`;
  }

  function resultColumnValue(record, column) {
    if (sameColumn(column, "MODEL")) return record.values[column] || record.model || "";
    if (sameColumn(column, "MAKE")) return record.make || "";
    if (sameColumn(column, "CONST")) return configuredRecordValue(record, "const") || record.construct || record.values.CONST || record.values.CONSTRUCT || "";
    if (sameColumn(column, "CAB")) return configuredRecordValue(record, "cab") || record.values[column] || "";
    if (sameColumn(column, "BED")) return configuredRecordValue(record, "bed") || record.values[column] || "";
    if (sameColumn(column, "TYPE")) return record.values[column] || record.type || "";
    return record.values[column] || "";
  }

  function sizeDisplayFields() {
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
    const fields = sizeDisplayFields();
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
    const orderedSet = new Set(ordered);
    searchState.fieldOrder = [...ordered, ...searchState.fieldOrder.filter((field) => !orderedSet.has(field))];
  }

  function sortSizeRows(rows) {
    if (!searchState.sortField) return rows;
    const direction = searchState.sortDirection === "desc" ? -1 : 1;
    return [...rows].sort((left, right) => compareValues(resultColumnValue(left, searchState.sortField), resultColumnValue(right, searchState.sortField)) * direction);
  }

  function compareValues(left, right) {
    const leftNumber = Number(left);
    const rightNumber = Number(right);
    if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
      return leftNumber - rightNumber;
    }
    return String(left || "").localeCompare(String(right || ""), undefined, { numeric: true });
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

  function filterConfig(key) {
    return { ...(defaultViewConfig.filters[key] || {}), ...(viewConfig.filters?.[key] || {}) };
  }

  function tableFieldConfig(key) {
    return { ...(defaultViewConfig.table_fields[key] || {}), ...(viewConfig.table_fields?.[key] || {}) };
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

  async function loadViewConfig() {
    if (!config.viewConfigPath) {
      return;
    }
    try {
      const response = await fetch(config.viewConfigPath, { cache: "no-store" });
      if (response.ok) {
        viewConfig = mergeViewConfig(defaultViewConfig, parseSizeViewYaml(await response.text()));
      }
    } catch (error) {
      viewConfig = defaultViewConfig;
    }
  }

  function parseSizeViewYaml(text) {
    const result = { filters: {}, table_fields: {}, excel_source: {}, match_sources: [], size_reference: {} };
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
      size_reference: { ...fallback.size_reference, ...(parsed.size_reference || {}) }
    };
    Object.entries(parsed.filters || {}).forEach(([key, value]) => {
      merged.filters[key] = { ...(merged.filters[key] || {}), ...value };
    });
    Object.entries(parsed.table_fields || {}).forEach(([key, value]) => {
      merged.table_fields[key] = { ...(merged.table_fields[key] || {}), ...value };
    });
    return merged;
  }

  async function loadSizeReferences() {
    const path = viewConfig.size_reference?.data_path || config.sizeRefPath;
    if (!path) return;
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) return;
      const text = await response.text();
      const rows = path.endsWith(".json") ? (JSON.parse(text).rows || []) : parseTsv(text);
      const matchField = viewConfig.size_reference?.match_field || "通用尺码";
      sizeReferenceIndex.clear();
      rows.forEach((row) => {
        [row[matchField], row["型号"], row["内部尺码"], row["通用尺码"]].forEach((value) => {
          const key = cleanField(value).toUpperCase();
          if (key && !sizeReferenceIndex.has(key)) {
            sizeReferenceIndex.set(key, row);
          }
        });
      });
    } catch (error) {
      sizeReferenceIndex.clear();
    }
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
    if (sameColumn(column, "MODEL")) return "150px";
    if (sameColumn(column, "版本")) return "92px";
    if (sameColumn(column, "YEAR")) return "112px";
    if (sameColumn(column, "TYPE")) return "130px";
    if (sameColumn(column, "CAB")) return "110px";
    if (sameColumn(column, "BED")) return "90px";
    if (isLengthMarginColumn(column)) return "100px";
    if (isDimensionColumn(column)) return "82px";
    if (isSizeColumn(column)) return "104px";
    return "118px";
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
      const width = col?.getBoundingClientRect().width;
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
    return ["L-IN", "W-IN", "H-IN", "L-CM", "W-CM", "H-CM", "长_in", "宽_in", "高_in"].some((item) => sameColumn(column, item));
  }

  function isLengthMarginColumn(column) {
    return sameColumn(column, "长度余量");
  }

  function isRangeFilterColumn(column) {
    return isDimensionColumn(column) || isLengthMarginColumn(column);
  }

  function sizeStickyClass(column) {
    if (sameColumn(column, "L-IN") || sameColumn(column, "L-CM") || sameColumn(column, "长_in")) return "size-sticky-l";
    if (sameColumn(column, "W-IN") || sameColumn(column, "W-CM") || sameColumn(column, "宽_in")) return "size-sticky-w";
    if (sameColumn(column, "H-IN") || sameColumn(column, "H-CM") || sameColumn(column, "高_in")) return "size-sticky-h";
    if (isLengthMarginColumn(column)) return "size-sticky-margin";
    if (sameColumn(column, "SIZE")) return "size-sticky-size";
    return "";
  }

  function activeDimensionColumns() {
    return searchState.dimensionUnit === "metric" ? ["L-CM", "W-CM", "H-CM"] : ["L-IN", "W-IN", "H-IN"];
  }

  function sameColumn(left, right) {
    return cleanField(left).toUpperCase() === cleanField(right).toUpperCase();
  }

  function csvList(value) {
    if (Array.isArray(value)) return value;
    return String(value || "").split(",").map(cleanField).filter(Boolean);
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

  function recordMatchesToken(record, token) {
    const sourceOnlyTokens = ["pick", "nonpick", "tm", "宏能图"];
    if (sourceOnlyTokens.includes(token) && record.sourceTags.includes(token)) {
      return true;
    }
    if (sourceOnlyTokens.includes(token)) {
      return false;
    }
    if (record.sourceTags.includes(token)) {
      return true;
    }

    const haystack = normalizeSearchText([
      record.source,
      record.make,
      record.model,
      record.type,
      record.year,
      record.title,
      record.description,
      record.searchText,
      Object.values(record.values).join(" ")
    ].join(" "));
    return haystack.includes(token) || recordSearchAtoms(record).some((atom) => atom === token || atom.includes(token));
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

  function cleanField(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function cleanText(element) {
    if (!element) {
      return "";
    }
    return element.textContent.replace(/\s+/g, " ").trim();
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/"/g, '\\"');
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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
  loadViewConfig().then(loadSizeReferences).then(render);
})();
