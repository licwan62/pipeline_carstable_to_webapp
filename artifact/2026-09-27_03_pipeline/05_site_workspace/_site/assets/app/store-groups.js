(function () {
  const app = document.getElementById("app");
  const { esc, shell, bindSidebar, table, sourceText, getJson } = window.SiteCommon || {};
  if (!app || !shell) return;

  const state = { groups: null, rules: null, error: "" };

  function render() {
    let body;
    if (state.error) {
      body = `<section class="search-panel"><div class="search-summary" role="status">${esc(state.error)}</div></section>`;
    } else if (!state.groups) {
      body = '<section class="search-panel"><div class="search-summary" role="status">正在读取店铺分组...</div></section>';
    } else {
      const info = new Map(((state.rules && state.rules.regions.US.rows) || []).map((r) => [r["尺码"], r]));
      const sections = Object.entries(state.groups.stores).map(([store, mapping]) => {
        const rows = mapping.map((m) => {
          const ship = info.get(m["发货尺码"]) || {};
          return { "匹配尺码": m["匹配尺码"], "发货尺码": m["发货尺码"], "分类": ship["分类"] || "", "长上限": ship["长上限"] || "", "备注": ship["备注"] || "" };
        });
        return `<h3 id="${esc(store)}">${esc(store)}</h3><div class="search-summary">${rows.length} 个匹配尺码。匹配尺码按规则计算，发货尺码是该店铺实际货架。</div>${table(["匹配尺码", "发货尺码", "分类", "长上限", "备注"], rows)}`;
      });
      body = `<section class="search-panel" aria-label="Store groups">
        ${sections.join("")}
        <p class="search-summary">${esc(sourceText(state.groups.source))} · 分类与长上限取自发货尺码的 US 规则</p>
      </section>`;
    }
    app.innerHTML = shell("stores", body, "stores");
    bindSidebar(app, render);
  }

  render();
  Promise.all([getJson("data/generated/store-groups.json"), getJson("data/generated/size-rules.json").catch(() => null)])
    .then(([groups, rules]) => { state.groups = groups; state.rules = rules; render(); })
    .catch(() => { state.error = "无法读取店铺分组，请先运行 tools/build_size_rules_data.py。"; render(); });
})();
