(function () {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const storageKey = "sizeChartSidebarCollapsed";
  let collapsed = false;
  try { collapsed = window.localStorage.getItem(storageKey) === "true"; } catch (error) { /* ignore */ }

  // 页面自定义大纲：{ title, items: [{ href, label, active, children: [...] }] }，文字由这里转义。
  function customOutline(spec) {
    const items = (list, depth) => (list || []).map((item) => {
      const children = item.children && item.children.length
        ? `<ol class="chart-outline-list chart-outline-children">${items(item.children, depth + 1)}</ol>` : "";
      const leaf = depth > 0 && !children ? " chart-outline-leaf" : "";
      return `<li><a class="chart-outline-node${leaf}${item.active ? " is-active" : ""}" href="${esc(item.href || "#")}" aria-current="${item.active ? "page" : "false"}"><span class="chart-outline-dot"></span><span>${esc(item.label)}</span></a>${children}</li>`;
    }).join("");
    return `
          <nav class="sidebar-outline size-chart-outline" aria-label="${esc(spec.title)}大纲">
            <div class="sidebar-filter-title">${esc(spec.title)}</div>
            <div class="chart-outline"><ol class="chart-outline-list">${items(spec.items, 0)}</ol></div>
          </nav>`;
  }

  // active: 页面键；sub: 尺码参考下当前高亮的子项（US/EU/RU/stores）；
  // options.outline: 页面自己的大纲（如其他项目登记的页面），替代默认的尺码参考大纲。
  function shell(active, body, sub, options) {
    const link = (key, href, icon, label) =>
      `<a class="${active === key && !sub ? "is-active" : ""}" href="${href}" title="${label}"><span class="nav-icon">${icon}</span><span class="nav-label">${label}</span></a>`;
    const node = (key, href, label) =>
      `<li><a class="chart-outline-node${sub === key ? " is-active" : ""}" href="${href}" aria-current="${sub === key ? "page" : "false"}"><span class="chart-outline-dot"></span><span>${label}</span></a></li>`;
    const outline = options && options.outline ? customOutline(options.outline) : `
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
            ${link("code", "size-match-code.html", "码", "压缩代号")}
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

  // 站点由多个项目共同发布：其他项目在 _publishers/registry.json 登记自己的页面入口。
  // 这里只读取并显示，不维护其内容；入口限于站点根目录下的 .html 页面。
  let extensions = [];
  const currentPage = () => decodeURIComponent(location.pathname.split("/").pop() || "index.html");
  const extensionLink = (e) =>
    `<a class="${currentPage() === e.href ? "is-active" : ""}" href="${esc(e.href)}" title="${esc(e.label)}" data-site-extension><span class="nav-icon">${esc(e.icon || e.label.slice(0, 1))}</span><span class="nav-label">${esc(e.label)}</span></a>`;
  const extensionCard = (e) =>
    `<a class="home-action" href="${esc(e.href)}" data-site-extension><span>${esc(e.label)}</span><strong>${esc(e.summary || "")}</strong></a>`;

  function applyExtensions() {
    if (!extensions.length) return;
    const missing = (root, e) => !root.querySelector(`a[href="${CSS.escape(e.href)}"]`);
    document.querySelectorAll(".sidebar-nav").forEach((nav) => {
      extensions.filter((e) => missing(nav, e)).forEach((e) => nav.insertAdjacentHTML("beforeend", extensionLink(e)));
    });
    document.querySelectorAll(".home-actions").forEach((home) => {
      extensions.filter((e) => missing(home, e)).forEach((e) => home.insertAdjacentHTML("beforeend", extensionCard(e)));
    });
  }

  fetch("_publishers/registry.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((registry) => {
      const publishers = (registry && registry.publishers) || {};
      extensions = Object.keys(publishers).sort().flatMap((name) => publishers[name].nav || [])
        .filter((e) => e && typeof e.label === "string" && /^[\w.-]+\.html$/.test(e.href || ""));
      applyExtensions();
      // 各页面会整体重绘侧栏（含 viewer.js 自带的侧栏），重绘后补回入口。
      if (extensions.length) new MutationObserver(applyExtensions).observe(document.body, { childList: true, subtree: true });
    })
    .catch(() => { /* 未部署登记文件（如 GitHub Pages）时只显示本站页面 */ });
})();
