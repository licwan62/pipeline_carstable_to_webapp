(function () {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const storageKey = "sizeChartSidebarCollapsed";
  let collapsed = false;
  try { collapsed = window.localStorage.getItem(storageKey) === "true"; } catch (error) { /* ignore */ }

  // active: 页面键；sub: 尺码参考下当前高亮的子项（US/EU/RU/stores）。
  function shell(active, body, sub) {
    const link = (key, href, icon, label) =>
      `<a class="${active === key && !sub ? "is-active" : ""}" href="${href}" title="${label}"><span class="nav-icon">${icon}</span><span class="nav-label">${label}</span></a>`;
    const node = (key, href, label) =>
      `<li><a class="chart-outline-node${sub === key ? " is-active" : ""}" href="${href}" aria-current="${sub === key ? "page" : "false"}"><span class="chart-outline-dot"></span><span>${label}</span></a></li>`;
    const outline = `
          <nav class="sidebar-outline size-chart-outline" aria-label="尺码参考大纲">
            <div class="sidebar-filter-title">尺码参考</div>
            <div class="chart-outline"><ol class="chart-outline-list">
              ${["US", "EU", "RU"].map((r) => node(r, "size-ref.html#" + r, r)).join("")}
              ${node("stores", "store-groups.html", "店铺分组")}
            </ol></div>
          </nav>`;
    return `
      <main class="viewer-main viewer-shell${collapsed ? " is-sidebar-collapsed" : ""}">
        <aside class="viewer-side" aria-label="Page outline">
          <div class="sidebar-head">
            <button class="sidebar-toggle" type="button" aria-label="${collapsed ? "展开侧栏" : "收起侧栏"}" aria-expanded="${collapsed ? "false" : "true"}"><span>☰</span></button>
          </div>
          <nav class="sidebar-nav" aria-label="Pages">
            ${link("home", "index.html", "首", "首页")}
            ${link("chart", "size-chart.html", "S", "Size Chart")}
            ${link("ref", "size-ref.html", "参", "尺码参考")}
            ${link("match", "size-match.html", "尺", "尺码配对")}
          </nav>
          ${outline}
        </aside>
        <div class="viewer-content">${body}</div>
      </main>`;
  }

  function bindSidebar(app, rerender) {
    const toggle = app.querySelector(".sidebar-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", () => {
      collapsed = !collapsed;
      try { window.localStorage.setItem(storageKey, collapsed ? "true" : "false"); } catch (error) { /* ignore */ }
      rerender();
    });
  }

  function table(headers, rows) {
    if (!rows.length) return '<div class="empty-results">未找到匹配记录。</div>';
    return `<div class="results-table-wrap size-ref-wrap"><table class="results-table size-ref-table"><thead><tr>${headers.map((h) => `<th><span class="th-label">${esc(h)}</span></th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((h) => `<td>${esc(row[h] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  const sourceText = (s) => `发布源：${s.node} ${s.version}（${String(s.published_at).slice(0, 10)}）`;
  const getJson = (path) => fetch(path, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(path); return r.json(); });

  window.SiteCommon = { esc, shell, bindSidebar, table, sourceText, getJson };
})();
