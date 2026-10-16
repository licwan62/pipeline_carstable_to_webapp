# 尺码配对页验收

尺码配对页（`size-match.html`）的设计需求与自动验收。改动该页面、它的数据（`tools/build_size_match_code_data.py`）或前端
（`site_overrides/assets/app/viewer*.js`）后，验收必须全部通过才算完成；需求变化时先改本文与场景清单，再改代码。

## 需求

| 编号 | 需求 |
| --- | --- |
| R1 | **两种视图**：同一页面用「视图」控件切换 **压缩表**（A1 压缩尺码表，CODE 在前，点 CODE 展开来源车型各年份）与 **全量表**（A0 全量表逐行）。默认压缩表；`?view=full` / `?view=compressed` 直达；切换保留搜索词、数据源、类别、MAKE、SIZE，只清列筛选与排序；URL 记录当前视图。 |
| R2 | **同一数据源，不重复存数据**：只发布一套 `data/generated/size-match-data.json` 与分片。每个分片（产线 × 类别 × MAKE）同时存 A0 全量行 `records` 与 A1 压缩记录 `compressed`；压缩记录只存聚合值与 `refs`（[行号, 被覆盖年份]），来源行由页面从全量行还原，且必须与 A1 `压缩来源.csv` 逐条一致。表格与车型可视化历史读同一份数据；不得再发布 `size-match-code*`、`size-match-full*`。切换视图不重新下载数据。 |
| R3 | **全局搜索只出现上下文内的车型**：按字段语义匹配，不在整行文本里做子串匹配。数字词只比四位年份（年份区间包含）、CODE 前缀（≥4 位）与车型/版本的整段数字（`bmw 7` → 7 / 7 Series，不出现 3、5 系、X7、i7、700）；字母词比身份字段（MAKE、MODEL、版本、TYPE、SHAPE、CAB、BED、SIZE、CODE）的单词前缀，连字符可省略（`f150`、`crv`）；长宽高、销量、长度余量不参与。两种视图同一规则；列筛选的候选项随之只含上下文内的值；8 位车型代码照常解析。 |
| R4 | **两种视图一致**：全量表命中且有尺码的行，都被压缩表命中记录的来源行覆盖；压缩记录展开的来源行属于同一车型。 |
| R5 | 页面无脚本错误、无失败请求（本地预览缺少 NAS 的 `_publishers/registry.json` 除外）。 |
| R6 | 旧的 `size-match-code.html` 已弃用，不得发布。 |

规则细节见 `site_overrides/assets/app/viewer-data.js` 中 `searchQueryTokens` / `recordMatchesSearchToken` / `expandMatchShard` 的注释。

## 验收层次

| 层 | 内容 | 何时运行 |
| --- | --- | --- |
| 单元 | `tests/js/viewer-search.test.cjs`（搜索规则、分片展开）、`tests/test_build_size_match_code_data.py`（数据构建、拒绝不一致输入）、`tests/test_match_page_views.py`（页面配置）、`tests/test_size_match_acceptance.py`（Node 套件 + 验收脚本自身） | `python -m pytest tests` |
| 结构 | `tools/validate_publish_site.py`：页面声明两种视图与同一数据路径、分片计数与 `refs` 完整、年份在来源行内、无重复数据族、旧页面不存在 | 每次构建（切换 public 前） |
| 数据 | `tests/acceptance/size_match_data.cjs`：用**站点自己发布的** `viewer-data.js` 展开真实数据，检查 R1/R2（含与 A1 `压缩来源.csv` 逐条对照）、R3/R4 的搜索场景 | 每次构建（切换 public 前，失败即不发布）；也可单独运行 |
| 浏览器 | `tests/acceptance/size_match_browser.cjs`：Playwright 无头 Chromium 打开页面，操作视图切换、搜索、列筛选、来源展开，页面数量与数据层按同一规则算出的数量逐项比较，并监听请求与报错 | 发布前手动运行 |

搜索场景在 `tests/acceptance/size-match-scenarios.json`（数据层与浏览器层共用；`browser_only` 只在浏览器层跑，如 8 位车型代码）。
发现新的误匹配时，先在这里加一条场景（期望的 MAKE/MODEL），确认验收失败，再修代码。

## 运行

```powershell
python tools/acceptance_size_match.py                                  # 验收 public/：结构 + 数据 + 浏览器
python tools/acceptance_size_match.py --site <站点目录> --a1 <A1 output> # 验收临时站点（A1 须与站点数据同版本）
python tools/acceptance_size_match.py --no-browser                     # 只跑结构与数据层
```

逐项结果打印到终端，报告写入 `logs/acceptance/size-match-<时间>.md`（不纳入 git）。任一项失败或未运行（找不到 Playwright）退出码为 1。
Playwright 默认依次尝试本仓库 `node_modules` 与 `../4Afitment/scrapers/4afitment/node_modules/playwright`，其他位置用环境变量 `SIZE_MATCH_PLAYWRIGHT` 指定。

变异验证（2026-10-16）：把站点副本中的搜索换回旧的整行子串匹配，数据层 S1、S2、S4–S8、S10 全部失败（`bmw 7` 混入 1/3/5 系等），证明验收能抓到原缺陷。
