# size-match 年份尺寸演变可视化：Claude 实施 Startup

日期：2026-10-13。本文是实施任务书；代码路径与现状已经本地检查。本文交付的是技术文档，功能尚未实施。

## 1. 目标与交付范围

在现有 `size-match.html` 中集成可视化：用户选择车型或匹配结果后点击「可视化」，查看各年份的长度演变，联动查看宽度、高度，并通过图例选择车型、版本、TYPE、座位配置，同时看到实际 SIZE 和长度余量的变化。

确定采用：**长度区间阶梯主图 + 宽高联动小图 + SIZE 年份时间带**。使用大尺寸弹窗，可切换全屏；保留现有检索、表格、大纲、复制、排序、筛选和 SIZE hover 功能。

本轮 Claude 必须完成首期全部功能和本地验收；精确命中规则叠加作为明确的后续增强，不得为实现首期擅自改变上游匹配算法或 CSV 接口。完成后交付改动、测试结果、截图及运行方式。此次实施交付范围是本地网站，不包含 NAS 部署。

### 首期必做

1. 车型可视化入口、结果行入口、跨页多选对比入口。
2. 长度主图，宽/高可展开，统一年份轴、缩放和悬浮定位。
3. 车型/版本/TYPE/座位筛选、配置图例开关；皮卡增加 CAB/BED。
4. 当前筛选与完整车型历史两种范围，默认完整历史，高亮命中记录。
5. 每个配置一行的 SIZE 时间带，实际尺寸、长度余量、匹配异常提示。
6. 年份区间、缺口、重叠、重复、缺失尺寸的确定处理。
7. 明确区分国别匹配结果和店铺发货结果；显示数据来源版本。
8. 持久化源码进入站点构建流程，重建后功能仍存在。

### 后续增强

保留精确匹配尺码与命中规则标识后，再叠加规则长上限、适配长度范围和 RU 宽高上限。首期不显示未经确认的唯一命中规则边界。PNG 导出、书签链接、批量下载也不作为首期完成条件。

## 2. 仓库与现有实现

网站仓库：`D:\Licheng\Repo\pipeline_carstable_to_webapp`。

上游仓库：`D:\Licheng\Repo\all_cars_data`。更改上游前必须阅读根目录及 `A0.尺码计算/AGENTS.md`，遵守规则在 data、生成后发布、不可修改历史 artifact 的约定。

| 路径 | 当前职责 / 实施用途 |
| --- | --- |
| `public/size-match.html` | 页面壳；`window.SIZE_CHART_VIEWER` 指定 search 模式和全量匹配数据路径 |
| `public/assets/app/viewer.js` | IIFE 原生 JS；检索状态、分片加载、结果表/大纲、单位切换、SIZE 规则 hover |
| `public/assets/app/viewer.css` | 页面布局和结果表样式 |
| `tools/build_size_match_data.py` | 验证 A0 manifest SHA256，生成地区/店铺 + kind + MAKE 分片 |
| `tools/build_size_rules_data.py` | 从 A0 已发布报告解析规则、容差、店铺货架 |
| `tools/build_publish_site.py` | 生成 public；保留部分旧前端，再叠加 site_overrides，并更新资源版本 |
| `site_overrides/` | 项目自有页面/脚本的构建覆盖入口 |
| `configs/pipeline.yaml` | 输入路径、流水线步骤、NAS 发布步骤 |
| `tests/test_build_size_match_data.py` | 分片、地区/店铺、字段、年份解析相关测试 |
| `tests/test_build_size_rules_data.py` | 规则报告解析测试 |
| `tools/validate_publish_site.py` | 构建站点数据结构检查 |

建议首先阅读的 viewer.js 函数：

- `render()`、`bind()`：页面重绘和事件绑定。
- `updateSearchResults()`：先计算完整 matches，再分页成 visibleMatches。
- `getSearchMatches()`、`queryFilteredRecords()`：筛选和关键词检索。
- `loadConfiguredMatchManifest()`、`loadConfiguredMatchSource()`：分片清单及缓存加载。
- `loadConfiguredMatchIndexes()`：source / kind / MAKE 加载；当前函数会修改搜索状态，不能直接把它作为无副作用图表加载 API。
- `renderResultsTable()`、`resultRowMarkup()`、`renderResultsOutline()`：入口和选择框植入点。
- `recordSourceName()`、`resultColumnValue()`：来源和字段读取。
- `sizeRuleScope()`、`sizeRuleFor()`、`sizeRuleLengthMarkup()`、`sizeRuleRuMarkup()`：现有规则解释，仅可作为参考。
- `measurementDisplay()`、`dimensionDisplay()`：单位与显示；内部计算仍统一 mm。

### 构建注意事项

`public/` 会被构建器删除后重新生成。当前 `PRESERVED_FRONTEND_FILES` 会把已有 viewer.js/css 等复制到构建 workspace，之后 `apply_site_overrides()` 再将 site_overrides 覆盖到 public。

推荐把本次修改的 `size-match.html`、`assets/app/viewer.js`、`assets/app/viewer.css` 以及新增模块、ECharts 资源放入 `site_overrides/`，作为此次变更的维护源，再物化到 public。首次提升 viewer.js/css 时，复制当前完整实现后做增量改动，不得用骨架版本覆盖现有功能。确认构建复制顺序和缓存版本实际生效。

只改 public、只改某个历史 artifact 或外部 publish repo，均不算完成。viewer 被多个页面共用，可视化必须用明确页面配置开关启用，避免出现在 size-chart / size-match-code 页面。

## 3. 数据口径

正式输入只读以下上游 output；不要从 NAS 发布目录或历史 artifact 取默认输入：

```text
A0.尺码计算/output/
  manifest.json
  US/全量/全量表.csv
  US/店铺/店铺全量_HNT.csv
  US/店铺/店铺全量_TM.csv
  US/店铺/店铺全量_TM_拆分.csv
  EU/全量/全量表.csv
  RU/全量/全量表.csv
  US/尺码匹配报告.md
  EU/尺码匹配报告.md
  RU/尺码匹配报告.md
```

页面读取：`size-match-full.json` 及其 MAKE 分片；规则/货架为 `size-rules.json`、`store-groups.json`。`size-ref.json` 是尺码参考尺寸，不能代替实际匹配规则。

现有 record 外层提供 make、model、year、years、construct/type、cab、bed、size、kind；`values` 保留原始 CSV 字段，并增加 TYPE、SIZE、SOURCE、长度余量等别名。多数可视化字段无需新增上游 CSV 列。

| 数据字段 | 图表口径 |
| --- | --- |
| MAKE + MODEL | 车型身份；不得仅按 MODEL 合并不同品牌 |
| 版本 | 保留原文；空值标签为「未注明版本」，不能假定它一定是标准版 |
| TYPE / 结构 | 当前 TYPE 来自 A0「结构」，不是车形/SHAPE |
| YEAR | 车型年份/年份区间，不是采集日期或年度销量观测 |
| 代际 | 区间标签及冲突分支识别，不按它拆成互不相干的车型 |
| L-MM / W-MM / H-MM | 车型外部尺寸，内部数值单位 mm |
| 自动长度余量 / 长度余量 | 使用上游发布数值，不能用参考尺码尺寸重新推算 |
| SIZE / 自动尺码 | 国别源表示其自动匹配结果；HNT/TM/TM_拆分表示店铺发货结果 |
| OZON尺码 / 发货尺码 | RU 已有字段时在详情显示，不能套用 US 店铺语义 |
| 候选 / 原因 / 相差数值 | 未匹配状态的解释，保留到 tooltip |
| DIMENSION-ID | 原始追踪身份；仍需包含 source 以区分同车型的国别/店铺记录 |

截至本文检查：网页 manifest origin 为 `20261010_01`；A0 manifest 为 `20261013_12`。实施时重新读取实时 manifest，不硬编码这两个版本。构建必须让全量分片、规则和货架来自同一 A0 发布版本。页面展示来源版本；版本不一致时展示可理解的状态，禁用规则叠加，不把版本混用当作有效匹配解释。

### 座位数

当前没有独立座位列。优先读取未来可能存在的明确 SEATS 字段，其次只识别版本中的明确表达，如 `5seat`、`7-seater`、`2-Seater`、`7座`，允许合理空白与大小写变化。只接受明确座位标记，不把 `L2H1`、车型数字或品牌 SEAT 当作座位数。

未命中返回 null，在 UI 中显示「未知」；多个矛盾座位标记返回未知并保留原文。版本原文不因提取座位而被删改。首期不建立猜测表；后续人工映射应在上游 data 中维护并随正式输出发布。

## 4. 页面交互契约

### 4.1 入口

- 结果工具栏增加「车型可视化」和「对比已选（N）」；明确选定 MAKE/MODEL 时直接进入完整历史。
- 尚未确定车型时，「车型可视化」打开车型选择器，选项来自全部匹配结果的去重车型，不限当前分页，不默认把成百上千个车型画进图。
- 表格每行增加独立图表按钮和选择框；保留现有点击复制动作，按钮阻止事件冒泡。
- 大纲模式提供车型组入口和叶子记录选择；两种视图共享同一选择状态。
- 单行入口打开同一 source + kind + MAKE + MODEL 的历史，默认突出该行配置，原始所选记录作为锚点。
- 多选入口打开已选车型的完整历史，默认显示已选配置；允许在图例面板添加这些车型的其他配置。

选择状态用稳定 recordKey 的 Set 存储，不用分页行号或对象引用。翻页、排序、切换表格/大纲时保留；source/kind 切换时清空并更新数量。筛选后隐藏的已选项仍计入总数，并提示「包含 N 条当前筛选外记录」，提供清空。全选文案为「选择本页」，不能暗示选择全部搜索结果。

### 4.2 范围

弹窗有两个选项：

1. **完整车型历史（默认）**：以已确定的 source、kind、MAKE、MODEL 为数据范围，读取未经过关键词、YEAR、SIZE、数值列筛选的记录。版本/TYPE/CAB/BED 当前选择作为初始配置选择，用户可以调整。
2. **仅当前筛选**：与打开时 `getSearchMatches()` 的完整结果一致，然后按已选车型或配置收窄；不取 visibleMatches。

YEAR、SIZE 和关键词等筛选不在完整历史模式下截掉年份；以原筛选结果 ID 集合标记命中区间。弹窗打开时冻结范围快照，避免后台搜索变化改变正在查看的图；关闭后重新打开取得新快照。无需从自由文本猜出 MODEL，车型必须来自实际选中记录或车型选择器。

### 4.3 弹窗与图例

- 弹窗宽度约 90vw、最大 1440px、高度约 90vh；移动端使用接近全屏的布局。
- 工具栏包含来源、范围、单位、年份窗口、展开宽高、全屏、关闭。
- 长度默认显示，宽高默认收起，SIZE 时间带默认显示。
- 配置筛选包括车型、版本、TYPE、座位；皮卡还显示 CAB、BED。
- 图例提供搜索、全选/取消、仅显示这一项；首次默认最多展示 6 个配置，已选配置优先，余下按稳定名称排序。超过 6 个时明确显示「已显示 6 / N 个配置」，用户可主动加选，不静默丢弃。
- 图例名称拼接 MAKE MODEL、版本、TYPE、座位；皮卡加 CAB/BED，空字段使用可理解的占位标签。
- 同一配置在三个尺寸面板保持同色；SIZE 有独立颜色与文字，不用曲线颜色表示尺码。
- 未知座位作为可选筛选值。长宽高重合的曲线在 tooltip 列出全部配置。

### 4.4 联动和详情

横轴为整数车型年份，所有面板和 SIZE 时间带共用窗口、缩放和年份指示。每张尺寸图有独立纵轴，同一张图内所有可见车型共用纵轴。纵轴标明 mm/cm/in，允许按所选数据自动缩放，不用双轴混画长度与宽高。

悬浮显示该年份覆盖的全部可见配置，列出原始年份区间、代际、长宽高、SIZE 含义、长度余量、匹配异常和来源；多条同年记录不能覆盖成最后一条。点击区间后锁定详情，展示原始 DIMENSION-ID，提供定位原记录动作。

定位动作先关闭弹窗、按稳定 ID 找原记录；如果该记录不在当前结果中，明确使用「查看该车型记录」动作切换到车型范围后定位，不能悄悄改掉用户筛选。大纲模式能定位到对应叶子。

弹窗初始化单位继承页面，内部切换不改变页面数值筛选。所有原值以 mm 存储：cm = mm / 10，in = mm / 25.4；只在显示时舍入，不先舍入后做判断。

Escape 关闭并恢复入口焦点；弹窗限制键盘焦点范围，有可访问名称，图例可键盘操作；提供文字详情供无法读取图形的用户使用。

## 5. 区间转换与冲突算法

### 5.1 标准化模型（建议，仅新增前端内部模型）

```ts
type EvolutionRecord = {
  recordKey: string;
  dimensionId: string | null;
  source: string;       // US / HNT / TM / TM_拆分 / EU / RU
  region: string;       // US / EU / RU；与 source 分开
  kind: 'nonpick' | 'pick';
  make: string;
  model: string;
  version: string | null;
  type: string | null;
  seats: number | null;
  cab: string | null;
  bed: string | null;
  generation: string | null;
  intervals: Array<{startYear: number; endYear: number}>;
  lengthMm: number | null;
  widthMm: number | null;
  heightMm: number | null;
  sizeValue: string | null;
  sizeMeaning: 'match' | 'shipping';
  lengthMarginMm: number | null;
  matchStatus: 'matched' | 'unmatched' | 'incomplete' | 'unknown';
  matchedSize: string | null; // 店铺首期通常未知，不能用 sizeValue 冒充
  candidate: string | null;
  reason: string | null;
  raw: object;
};
```

SIZE 缺失和明确「无可用尺码」「数据不全」分别处理；允许旧数据缺字段。RU sizeMeaning 以本源「自动尺码」的实际语义为 match，单独显示其发布的发货尺码。

configurationKey 使用结构化元组序列化，包含 source、kind、MAKE、MODEL、版本、TYPE、座位、CAB、BED；不靠空格拼接，避免名称碰撞；不包含 YEAR、SIZE、尺寸、代际，否则无法显示同配置的演变。

recordKey 首选 source + DIMENSION-ID，并在相同 ID 的冲突记录上附加语义内容指纹；无 ID 时使用来源、配置、年份、尺寸、代际、匹配结果组成稳定内容键。不得把文件行号或分页 index 当持久身份。精确重复行可合并，保留所有原始引用；同 ID 但内容不同的记录必须保留并标记冲突。

### 5.2 年份与数值

1. 明确单年为一个区间；`2017-2024` 为包含两端的区间。支持 ASCII 连字符及常见 en/em dash。
2. 多个离散年份/区间保留为多个区间，例如 `2011,2013` 不能补出 2012；禁止用第一个数字到最后一个数字直接填满所有输入。
3. 如果 raw YEAR 可可靠解析，用它生成区间；若只能使用 years 数组，把相邻整数压缩成独立连续区间，不能跨过缺口。
4. 倒置区间、无法解析文本、异常年份不画虚构年份，计入数据提示；保留原文供检查。支持范围用命名常量并说明，不把空数据变成当前年。
5. 维度空串、NULL、NaN、非数值及不合理的非正尺寸转 null；余量可以为 0 或负数，不能用 truthy 判断。

### 5.3 绘图几何

用数值年份轴，将包含两端的年份区间映射为 `[startYear - 0.5, endYear + 0.5]`，这样单年也有可点击宽度。tooltip 按实际整数年份和原区间解释。

所有记录先画独立水平区间段。仅在**同配置、前后年份连续且边界两侧各只有一个有效记录**时连接阶梯；跳变发生在年份边界，不平滑、不插值。缺失年份断开。同一维度缺失时只断开该维度，不隐藏其他已知尺寸和 SIZE。

同配置同年多个记录按原始区间/代际保留分支，SIZE 带也增加对应分支子行。不能取平均、逐维最大值、最后一条或按贪心最近尺寸合成一辆不存在的车。尺寸一致但 SIZE/代际不同仍保留出处；可以共享视觉段，但 tooltip 能展开所有原记录。

相邻区间只在尺寸、SIZE、版本、代际及匹配诊断均相同时才允许视觉合并；合并后仍保留原区间及 recordKey 列表。可先不合并，保证语义正确。

## 6. SIZE 时间带与规则增强

每个配置一行，横向范围与尺寸图严格一致；同年冲突增加子行，保持分支可追踪。色块显示原 SIZE，短块可以只在 tooltip 显示文字；颜色保持稳定，异常用灰色/纹理和明确文字，不能仅靠颜色识别。

国别源标题用「匹配 SIZE」；店铺源用「发货 SIZE」。Tooltip 中店铺 matchedSize 未知时显示「匹配尺码未记录」，不要显示反向映射候选之一为实际命中尺码。

### 后续规则叠加的前置条件

当前 `sizeRuleFor()` 按尺码建立索引，店铺会从一个发货尺码找出多个匹配尺码。这适合现有 hover 列出可能规则，但不足以确定本行实际使用哪条规则；同一尺码存在多条条件规则时也不能靠 Map 的首条决定。

精确增强应由上游保留：

- 店铺换码前的实际匹配尺码；
- 实际命中规则标识，绑定规则来源版本；建议对规则规范化字段内容生成稳定标识，并用版本限定其含义。

已确认的上游代码入口：`A0.尺码计算/src/generate_store_outputs.py` 的 `apply_shipping_sizes()` 会映射「自动尺码」「候选」；应在映射前保留真实值。具体落地方式需检查 `src/pandas_analysis.py` 的计算结果、schema 和所有下游兼容性，再选择新增列或正式伴随交付物。新增规则标识需要同时从 matcher 到报告/发布物、网站规则 JSON 全链路保存，不能仅在前端编造行号。

US/EU 的长度区间为 `[长上限 - 余量长容差, 长上限]`；仍有分类、版本、CAB、插片指数、白名单等条件，UI 标为「长度条件」，不能据此自行宣布适配。RU 使用本条规则的长度容差和长宽高上限。额外条件不全时只解释已知项。

上游变更必须走根目录 AGENTS.md 的运行、测试、artifact、manifest 和发布流程，不手改 output/CSV、manifest 或流水线状态.md。首期对此无依赖。

## 7. 前端实现组织

推荐维持原生 JS，不迁移 SPA 框架；ECharts 使用固定版本的本地资源及许可证，避免运行时依赖 CDN。实际版本由实施时验证兼容性后确定并记录。

```text
site_overrides/
  size-match.html
  assets/app/viewer.js                   # 当前实现的增量集成
  assets/app/viewer.css                  # 保留现有样式
  assets/app/size-evolution-data.js       # 纯函数：标准化、身份、区间、冲突
  assets/app/size-evolution.js            # 弹窗、图例、联动、生命周期
  assets/app/size-evolution.css
  assets/vendor/echarts/echarts.min.js
  assets/vendor/echarts/LICENSE
tests/
  js/size-evolution-data.test.cjs         # Node 内置测试；不要求引入完整打包系统
```

允许按实际实现调整模块名，但保持数据纯函数和 DOM/ECharts 代码分离。纯函数模块可用浏览器全局 + CommonJS 双出口，便于 Node 内置测试。

主 viewer 与弹窗通过小接口连接，而非暴露整个 searchState：

```ts
openEvolution({
  anchorRecordKeys,
  selectedConfigurationKeys,
  modelKeys,
  source,
  kind,
  unit,
  origin,
  currentMatchRecordKeys,
  loadModelHistory,
  onLocateRecord
});
```

`loadModelHistory` 只读 manifest、按 modelKeys 涉及的 MAKE 取对应 kind/source 分片，复用 `loadConfiguredMatchSource()` 的缓存，并按 MAKE/MODEL 精确收窄。不为了图表额外加载 EU/RU 全部品牌；需要提取加载帮助函数时，消除它对搜索 UI 的副作用。

实现两个独立概念：搜索结果选择状态、弹窗视图状态。关闭弹窗释放 ECharts 实例、ResizeObserver、事件订阅、全屏状态和滚动锁；可缓存原始数据。异步打开使用 token/取消标志，关闭后或切 source 后迟到响应不得重新弹出旧图。重复打开不得累计监听器。

SIZE 时间带可用 ECharts custom series 或与主图坐标同步的 SVG 实现，但必须统一年份坐标和 dataZoom；不要用与年份跨度不成比例的普通等宽标签代替时间带。

ECharts 资源只在启用可视化的页面加载，推荐首次打开时懒加载并显示加载状态。失败允许重试，原检索表仍可用。新脚本和样式必须进入资源版本更新流程；vendor 路径不会被当前只匹配 assets/app 的正则自动处理，需用内容版本路径或明确更新机制。

参考官方文档：

- [Step Line](https://apache.github.io/echarts-handbook/en/how-to/chart-types/line/step-line/)
- [Legend](https://echarts.apache.org/handbook/en/concepts/legend/)
- [Axis](https://echarts.apache.org/handbook/en/concepts/axis/)
- [Event and Action](https://echarts.apache.org/handbook/en/concepts/event/)

tooltip 中来自 CSV 的文本必须转义；ECharts HTML tooltip 不得直接插入原始版本/车型字符串。

## 8. 实施顺序

1. 检查 git status、现有源码、构建覆盖顺序和 manifest；记录当前基线，不覆盖已有未提交工作。
2. 建立数据纯函数和少量关键测试，先解决身份、年份、重叠、座位、单位和匹配语义。
3. 增加稳定选择状态与三个入口，保持复制和分页行为。
4. 接入弹窗和长度区间主图，实现历史/筛选范围。
5. 加入宽高联动、图例、SIZE 带、详情、原记录定位。
6. 完成异常状态、移动端、键盘、资源加载和清理。
7. 源码进入 site_overrides，刷新最新已发布数据，本地重建；完成自动检查和真实浏览器验收。
8. 提交实施结果说明：改动文件、关键决策、测试和截图、本地启动命令、明确的后续增强。

工作开始后持续推进至首期全部验收项满足；不要只交静态 mock、只做长度图或把图例筛选作为未完成事项。不存在精确规则 ID 不构成首期阻塞。

## 9. 验证与验收

### 自动验证重点

至少覆盖以下可导致错误解释的数据情形，不写仅镜像 DOM 的测试：

- 同品牌不同车型、同车型不同地区/店铺身份不混合，稳定 key 不受分页/排序影响。
- 单年、连续范围、离散年份、倒置/非法 YEAR，缺口没有插值。
- 同年重叠不同尺寸完整保留；同 ID 冲突不被覆盖；精确重复可去重并保留引用。
- `5seat`、`7-seater`、`2-Seater` 正确，品牌 SEAT、L2H1 不误识别；未知/矛盾座位保留未知。
- 缺失尺寸为 null，长度余量 0/负数保留；单位往返不修改原始 mm。
- 年份窗口/图例开关同时作用于三张尺寸图和 SIZE 带。
- 当前分页只有 200 行时，图表仍使用完整历史或全部筛选记录。
- 同发货尺码对应两个匹配尺码时，店铺图不宣称唯一命中规则。
- 构建后新增源码/本地 ECharts 资源/配置开关存在，来源版本一致。

建议命令（在网站仓库执行；按实际新增测试文件调整）：

```powershell
python -m pytest tests
node --test tests/js/size-evolution-data.test.cjs
python tools/run_all.py --to-step build_public_site --dry-run
python tools/run_all.py --to-step build_public_site
python tools/validate_publish_site.py public
python -m http.server 8765 --directory public --bind 127.0.0.1
```

实际构建会生成新的网站 artifact 并更新 public；使用新的批次，不在旧批次恢复执行此次功能验收。`--to-step build_public_site` 停在本地构建。**不要直接运行不带范围的 run_all.py：默认配置还包含 publish_nas_site。** 本地预览地址为 `http://127.0.0.1:8765/size-match.html`。

### 真实数据案例

当前 A0 US 的 MINI Countryman 未注明版本记录：

| YEAR | L-MM | W-MM | H-MM | SIZE | 长度余量 mm |
| --- | ---: | ---: | ---: | --- | ---: |
| 2011–2015 | 4110 | 1788 | 1562 | YM | 520 |
| 2017–2024 | 4313 | 1821 | 1557 | YM | 317 |
| 2025–2026 | 4448 | 1844 | 1656 | YM | 182 |

预期：2016 在此配置上断开；JCW 2016 是另一配置。车长增大而 SIZE 保持 YM，余量缩小。以上是 2026-10-13 检查样例，不作为永久尺码规则；若上游后续发布改变结果，以新 manifest 数据为准。

EU Ford Transit connect 的 `lwb 5seat` / `lwb 7seat` 可检查座位图例和高度差；现有不同起始年但相同尺寸的重叠区间必须可追踪。任选皮卡检查 CAB/BED 不同造成的长度分支；任选店铺检查发货 SIZE 语义；RU 检查发货/OZON详情。

### 浏览器验收清单

- [ ] 车型、单行、多选三种入口均可用；表格与大纲都能进入。
- [ ] 长度为主、宽高可展开，缩放/悬浮/图例/SIZE 时间带同步。
- [ ] 切换年份和 SIZE 筛选后，完整历史仍显示变更前后的区间。
- [ ] 多配置重合或同年冲突时，全部原记录能从详情找到。
- [ ] 多选跨页、排序、视图切换不丢失；source/kind 切换正确清空。
- [ ] mm/cm/in 数值正确，无误将毫米当厘米或寸的情况。
- [ ] 异常匹配、未知座位、空尺寸和单年记录可理解。
- [ ] 无规则 ID 的店铺记录没有虚构的匹配尺码或规则线。
- [ ] 关闭、重开、缩放窗口、全屏/退出、异步加载失败/重试正常，无重复事件或旧图回弹。
- [ ] Escape、焦点恢复、键盘图例正常；至少检查 1440px 桌面和 390px 移动视口。
- [ ] 原有复制、筛选、排序、分页、SIZE hover 正常；size-chart 和 size-match-code 无新增回归。
- [ ] 构建后打开网页再次验收；网络请求为本地资源且控制台无错误。
- [ ] 数据来源、规则来源和货架来源一致；真实数据案例与最新 CSV 一致。

性能目标：图表打开只处理所选车型，不绘制整库；缓存后 6 个配置的常规历史视图应在约 2 秒内可交互。记录浏览器、测试设备及测量结果；性能问题优先检查重复实例、全库扫描、过多分支和事件累计。

## 10. 可直接发送给 Claude 的开工指令

```text
请实施 D:\Licheng\Repo\pipeline_carstable_to_webapp\docs\size-match-visualization-startup.md。

工作仓库是 D:\Licheng\Repo\pipeline_carstable_to_webapp。
先阅读文档、README、相关代码和 git status，再完成文档中的首期全部功能。
主方案已经确定：长度区间阶梯主图 + 宽高联动小图 + SIZE 年份时间带，ECharts 本地资源。
保留现有检索、复制、筛选、分页和共享页面行为，源码必须纳入 site_overrides 并经本地重建验证。
不要猜测座位，不要把店铺发货 SIZE 当作唯一匹配尺码，不要对重叠年份取平均或平滑插值。
精确命中规则叠加是后续增强，本轮不改上游匹配算法和 CSV 接口。
本轮完成本地实施和验收，不部署 NAS。使用 --to-step build_public_site 停在本地构建。
完成后给出改动清单、测试结果、桌面与移动端截图、本地预览方式及后续增强说明。
```
