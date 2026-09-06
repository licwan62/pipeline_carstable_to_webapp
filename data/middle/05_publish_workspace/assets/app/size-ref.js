(function () {
  const config = window.SIZE_REF_VIEWER;
  const app = document.getElementById("app");

  if (!config || !app) {
    return;
  }

  const state = {
    headers: [],
    rows: [],
    query: "",
    status: "loading",
    message: "正在读取尺码参考...",
    viewConfig: {
      size_colors: { a: "#1777c8", c: "#d62828", h: "#00a6a6", s: "#f28c28", other: "#6b7280", text: "#ffffff" },
      size_reference: {
        data_path: "data/generated/size-ref.json"
      }
    }
  };
  const sidebarStorageKey = "sizeChartSidebarCollapsed";
  let sidebarCollapsed = readSidebarCollapsed();

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

  function render() {
    app.innerHTML = `
      <main class="viewer-main viewer-shell size-ref-shell${sidebarCollapsed ? " is-sidebar-collapsed" : ""}">
        <aside class="viewer-side" aria-label="Page outline">
          <div class="sidebar-head">
            <button class="sidebar-toggle" type="button" aria-label="${sidebarCollapsed ? "展开侧栏" : "收起侧栏"}" aria-expanded="${sidebarCollapsed ? "false" : "true"}">
              <span>☰</span>
            </button>
          </div>
          <nav class="sidebar-nav" aria-label="Pages">
            <a href="index.html" title="首页"><span class="nav-icon">首</span><span class="nav-label">首页</span></a>
            <a href="size-chart.html" title="Size Chart"><span class="nav-icon">S</span><span class="nav-label">Size Chart</span></a>
            <a class="is-active" href="size-ref.html" title="尺码参考"><span class="nav-icon">参</span><span class="nav-label">尺码参考</span></a>
            <a href="size-match.html" title="尺码配对"><span class="nav-icon">尺</span><span class="nav-label">尺码配对</span></a>
          </nav>
        </aside>
        <div class="viewer-content">
          <section class="search-panel" aria-label="Size reference">
            <header class="size-ref-header"><div><span class="size-ref-eyebrow">SIZE REFERENCE</span><h1>尺码参考</h1><p>按型号查找分类与长宽高</p></div><span class="size-ref-unit">尺寸单位 · mm</span></header>
            <div class="global-search">
              <label>
                <span>GLOBAL</span>
                <input class="global-search-input" type="search" value="${escapeHtml(state.query)}" placeholder="搜索型号、分类、CAB、通用尺码..." autocomplete="off" ${state.status === "loading" ? "disabled" : ""}>
              </label>
              <button class="search-reset" type="button">Reset</button>
            </div>
            <div class="search-summary" role="status"></div>
            <div class="search-results"></div>
          </section>
        </div>
      </main>
    `;
    bind();
    updateResults();
  }

  function bind() {
    app.querySelector(".sidebar-toggle").addEventListener("click", () => {
      sidebarCollapsed = !sidebarCollapsed;
      saveSidebarCollapsed(sidebarCollapsed);
      render();
    });

    const input = app.querySelector(".global-search-input");
    if (input) {
      input.addEventListener("input", (event) => {
        state.query = event.target.value;
        updateResults();
      });
    }

    const resetButton = app.querySelector(".search-reset");
    if (resetButton) {
      resetButton.addEventListener("click", () => {
        state.query = "";
        const currentInput = app.querySelector(".global-search-input");
        if (currentInput) {
          currentInput.value = "";
        }
        updateResults();
      });
    }
  }

  async function load() {
    render();
    try {
      await loadViewConfig();
      const sourcePath = state.viewConfig.size_reference?.data_path || config.sourcePath;
      const response = await fetch(sourcePath, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Cannot load ${sourcePath}`);
      }
      const text = await response.text();
      const parsed = sourcePath.endsWith(".json") ? JSON.parse(text) : parseTsv(text);
      state.headers = parsed.headers;
      state.rows = parsed.rows;
      state.status = "ready";
      state.message = `全量尺码参考：已索引 ${formatCount(state.rows.length)} 条记录。`;
    } catch (error) {
      state.status = "error";
      state.message = "无法读取尺码参考。";
    }
    render();
  }

  async function loadViewConfig() {
    if (!config.viewConfigPath) {
      return;
    }
    try {
      const response = await fetch(config.viewConfigPath, { cache: "no-store" });
      if (!response.ok) return;
      state.viewConfig = mergeViewConfig(state.viewConfig, parseViewYaml(await response.text()));
    } catch (error) {
      // Keep the default generated JSON path.
    }
  }

  function parseViewYaml(text) {
    const result = { size_reference: {}, size_colors: {} };
    let section = "";
    text.split(/\r?\n/).forEach((line) => {
      if (!line.trim() || line.trim().startsWith("#")) return;
      const indent = (line.match(/^\s*/) || [""])[0].length;
      const trimmed = line.trim();
      if (indent === 0 && trimmed.endsWith(":")) {
        section = trimmed.slice(0, -1);
        return;
      }
      if (indent === 2 && ["size_reference", "size_colors"].includes(section) && trimmed.includes(":")) {
        const [rawKey, ...rawValue] = trimmed.split(":");
        result[section][rawKey.trim()] = rawValue.join(":").trim().replace(/^["']|["']$/g, "");
      }
    });
    return result;
  }

  function mergeViewConfig(fallback, parsed) {
    return {
      ...fallback,
      size_reference: { ...(fallback.size_reference || {}), ...(parsed.size_reference || {}) },
      size_colors: { ...(fallback.size_colors || {}), ...(parsed.size_colors || {}) }
    };
  }

  function updateResults() {
    const summary = app.querySelector(".search-summary");
    const results = app.querySelector(".search-results");
    if (!summary || !results) return;
    if (state.status !== "ready") {
      summary.textContent = state.message;
      results.innerHTML = "";
      return;
    }
    const rows = getMatches();
    summary.textContent = state.query.trim()
      ? `匹配结果：${formatCount(rows.length)} 条记录。`
      : state.message;
    results.innerHTML = renderTable(rows);
  }

  function getMatches() {
    const tokens = searchTokens(state.query);
    if (!tokens.length) return state.rows;
    return state.rows.filter((row) => {
      const text = normalizeSearchText(Object.values(row).join(" "));
      return tokens.every((token) => text.includes(token));
    });
  }

  function renderTable(rows) {
    if (!rows.length) {
      return '<div class="empty-results">未找到匹配记录。</div>';
    }
    return `
      <div class="results-table-wrap size-ref-wrap">
        <table class="results-table size-ref-table">
          <thead>
            <tr>${state.headers.map((header) => `<th scope="col" class="${dimensionHeaderClass(header)}"><span class="th-label">${escapeHtml(header.replace(/_(mm|in)$/, " ($1)"))}</span></th>`).join("")}</tr>
          </thead>
          <tbody>
            ${rows.map((row) => `<tr>${state.headers.map((header) => cellMarkup(row[header], header, row)).join("")}</tr>`).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function cellMarkup(value, header, row) {
    const label = `data-label="${escapeHtml(header.replace(/_(mm|in)$/, " ($1)"))}"`;
    if (/^[长宽高]_(mm|in)$/.test(header)) {
      return `<td ${label} class="dimension-cell"><strong>${escapeHtml(value || "-")}</strong></td>`;
    }
    if (header === "型号") {
      return `<td ${label} class="size-ref-code" style="${escapeHtml(sizeCellStyle(value, row))}"><strong>${escapeHtml(value || "-")}</strong></td>`;
    }
    if (header === "通用尺码") {
      return `<td ${label} class="size-ref-common-cell" style="${escapeHtml(sizeCellStyle(value, row))}"><strong>${escapeHtml(value || "-")}</strong></td>`;
    }
    return `<td ${label} class="size-ref-detail${cleanField(value) ? "" : " is-empty"}">${escapeHtml(value || "—")}</td>`;
  }

  function sizeCellStyle(value, row) {
    const commonSize = cleanField(row["通用尺码"]).toUpperCase();
    const colorKey = commonSize || cleanField(value).toUpperCase();
    const categories = { "三厢车": "a", "跑车": "c", "两厢车": "h", "越野车": "s" };
    const keyedFamily = ["A", "C", "H", "S"].includes(colorKey[0]) ? colorKey[0].toLowerCase() : "";
    const family = keyedFamily || categories[cleanField(row["分类"])] || "other";
    const base = state.viewConfig.size_colors[family];
    const commonLevel = Number((commonSize.match(/\d+/) || [""])[0]);
    const order = Number(row["档位序号"]);
    const level = Number.isFinite(commonLevel) && commonSize ? commonLevel : (Number.isFinite(order) ? order % 10 : 0);
    const background = darkenHex(base, Math.min(0.34, Math.max(0, (level - 1) * 0.055)));
    return `--size-bg: ${background}; --size-fg: ${state.viewConfig.size_colors.text};`;
  }

  function darkenHex(hex, amount) {
    const normalized = cleanField(hex).replace(/^#/, "");
    if (!/^[0-9a-f]{6}$/i.test(normalized)) return hex;
    const value = Number.parseInt(normalized, 16);
    const ratio = 1 - Math.max(0, Math.min(1, amount));
    return `rgb(${Math.round(((value >> 16) & 255) * ratio)}, ${Math.round(((value >> 8) & 255) * ratio)}, ${Math.round((value & 255) * ratio)})`;
  }

  function dimensionHeaderClass(header) {
    return /^[长宽高]_(mm|in)$/.test(header) ? "dimension-heading" : "";
  }

  function parseTsv(text) {
    const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter((line) => line.trim());
    const headers = lines.shift().split("\t").map((header) => header.trim());
    return {
      headers,
      rows: lines.map((line) => {
        const cells = line.split("\t");
        const row = {};
        headers.forEach((header, index) => {
          row[header] = cleanField(cells[index]);
        });
        return row;
      })
    };
  }

  function searchTokens(value) {
    return normalizeSearchText(value).split(/\s+/).filter(Boolean);
  }

  function normalizeSearchText(value) {
    return cleanField(value).toLowerCase();
  }

  function cleanField(value) {
    return String(value ?? "").trim();
  }

  function formatCount(value) {
    return new Intl.NumberFormat("en-US").format(value);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));
  }

  load();
})();
