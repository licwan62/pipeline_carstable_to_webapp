(function () {
  const app = document.getElementById("app");
  const { esc, shell, bindSidebar, table, sourceText, getJson } = window.SiteCommon || {};
  if (!app || !shell) return;

  const regionFromHash = () => {
    const value = decodeURIComponent(location.hash.slice(1)).toUpperCase();
    return ["US", "EU", "RU"].includes(value) ? value : "US";
  };
  const state = { data: null, region: regionFromHash(), query: "", error: "" };

  function matches() {
    const tokens = state.query.toLowerCase().split(/\s+/).filter(Boolean);
    const rows = state.data.regions[state.region].rows;
    return tokens.length ? rows.filter((r) => tokens.every((t) => Object.values(r).join(" ").toLowerCase().includes(t))) : rows;
  }

  function render() {
    let body;
    if (state.error) {
      body = `<section class="search-panel"><div class="search-summary" role="status">${esc(state.error)}</div></section>`;
    } else if (!state.data) {
      body = '<section class="search-panel"><div class="search-summary" role="status">正在读取尺码规则...</div></section>';
    } else {
      const region = state.data.regions[state.region];
      body = `<section class="search-panel" aria-label="Size rules">
        <div class="global-search"><label><span>GLOBAL</span><input class="global-search-input" type="search" value="${esc(state.query)}" placeholder="搜索尺码、分类、白名单..." autocomplete="off"></label><button class="search-reset" type="button">Reset</button></div>
        <div class="search-summary" role="status"></div>
        <div class="search-results"></div>
        <p class="search-summary">${esc(sourceText(state.data.source))} · ${esc(region.file)} · <a href="store-groups.html">店铺分组 →</a></p>
      </section>`;
    }
    app.innerHTML = shell("ref", body, state.region);
    bindSidebar(app, render);
    const input = app.querySelector(".global-search-input");
    if (input) {
      input.addEventListener("input", (e) => { state.query = e.target.value; update(); });
      app.querySelector(".global-search .search-reset").addEventListener("click", () => {
        state.query = "";
        input.value = "";
        update();
      });
      update();
    }
  }

  function update() {
    const rows = matches();
    const region = state.data.regions[state.region];
    app.querySelector(".search-summary[role=status]").textContent = `${state.region} 尺码规则：${rows.length} / ${region.rows.length} 条。`;
    app.querySelector(".search-results").innerHTML = table(region.headers, rows);
  }

  window.addEventListener("hashchange", () => {
    state.region = regionFromHash();
    state.query = "";
    render();
  });
  render();
  getJson("data/generated/size-rules.json")
    .then((data) => { state.data = data; render(); })
    .catch(() => { state.error = "无法读取尺码规则，请先运行 tools/build_size_rules_data.py。"; render(); });
})();
