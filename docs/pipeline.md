# 车型尺码流水线

本项目采用 `上游发布物 + artifact + public` 模式：产线输入直接读取 all_cars_data 已发布的 A0 全量表与 A1.压缩尺寸信息 压缩表（按 manifest 校验 sha256）。上游目录由 `configs/pipeline.yaml` 的 `paths.a0_output_dir`、`paths.a2_output_dir` 指定，代码中不写死。

```text
../all_cars_data/A0.尺码计算/output/      <国别>/全量/全量表.csv、US/店铺/店铺全量_<店铺>.csv、<国别>/尺码匹配报告.md（规则与店铺货架表格）
../all_cars_data/A1.压缩尺寸信息/output/  <国别>/压缩尺码表.csv、<国别>/压缩尺码表_皮卡.csv
input/                              旧的人工输入（仅 input.source 不是 all_cars_data 时使用）
configs/
  pipeline.yaml                     流水线配置
  user-size-rules.json              尺码和缩写规则的唯一活动来源
artifact/
  2026-09-01_01_最后的老尺码/       迁移前历史产物，只读保留
  YYYY-MM-DD_NN_pipeline/           每次新运行生成的独立批次
public/                             当前可部署站点
logs/                               运行日志（不纳入 git）
bak/                                tools/backup.py 的本地备份（不纳入 git）；.bak/ 为早期备份，同样只在本地保留
```

## 运行

先在 all_cars_data 发布 A0/A2（`python scripts/publish_release.py`），然后执行：

```powershell
python tools/run_all.py
```

每次不带 `--artifact` 的执行都会分配一个新目录，例如：

```text
artifact/2026-09-17_01_pipeline/
artifact/2026-09-17_02_pipeline/
```

批次内部结构：

```text
00_input/
  pipeline.generated.json
  tables/*.csv
01_compressed_fitment/**/*.csv
02_user_size.json
03_store_csv/**/*.csv
04_store_html/
05_site_workspace/
artifact.json
```

中间结构化数据只使用 CSV 和 JSON，不生成中间 XLSX。`00_input/tables/` 是导入的产线全量表（供尺码配对页），`01_compressed_fitment/<产线>/compress/` 是导入的 A2 高度压缩表，`pipeline.generated.json` 记录店铺清单与来源版本（`sources`）。HTML 生成器当前仍以 TSV 为接口，只在系统临时目录中做短暂转换。

## 批次恢复执行

查看步骤：

```powershell
python tools/run_all.py --list-steps
```

从现有批次的某一步继续：

```powershell
python tools/run_all.py --artifact 2026-09-17_02_pipeline --from-step build_user_size_json
```

`--from-step` 必须同时指定 `--artifact`，避免把不完整结果误写进新批次。也可以用 `--to-step` 创建新批次并停在指定步骤。

当前六个步骤统一采用“动作 + 产物”命名：

1. `import_a2_compressed`：按 A1 发布的产线（US、HNT、TM、TM_拆分、EU、RU；`input.lines` 可限定）导入 A0 全量表与 A1 高度压缩表，校验 manifest，生成运行时 JSON。压缩与原子检查已移至 all_cars_data 的 `A1.压缩尺寸信息`（2026-10-09 前为 `A2.压缩尺寸信息`）。
2. `build_user_size_json`：应用尺码及缩写规则，生成紧凑 JSON。
3. `export_store_csv`：按店铺导出 HTML 输入 CSV。
4. `generate_store_html`：生成各店铺尺码表 HTML。
5. `build_public_site`：构建并更新 `public/`。
6. `publish_nas_site`：尝试将本流水线的站点文件发布到 NAS（只更新本流水线登记的文件，见“发布”）；NAS 不可用时记录警告，但不影响 `public/` 构建成功。

旧步骤名（`normalize_store_inputs`、`compress_store_fitment` 仍保留在旧手工输入模式中）仍可用于 `--from-step`/`--to-step`，但 `--list-steps` 和新日志只显示上述标准名称。

## 规则

尺码、分类、车型/驾驶室/类型缩写全部由以下 JSON 维护：

```text
configs/user-size-rules.json
```

运行时不再读取或生成“尺码适配表”模板工作簿。历史批次中的 `template/` 仅是迁移快照，不参与当前流水线。

## 发布

成功运行后：

- 完整构建过程保存在对应 `artifact/<批次>/`。
- 最新站点写入 `public/`。
- 流水线随后尝试将站点发布到 `\\NAS8824B4\Web\car`。
- GitHub Pages 工作流发布 `public/`。

### NAS 站点由多个项目共同维护

`\\NAS8824B4\Web\car` 不归本流水线独占：本流水线负责其他项目登记页面以外的全部页面（目前另有 Amazon_Competitor_Analysis 的 `asin_analysis.html`）。各项目互不引用对方路径，各自维护状态：

- `_publishers/<发布方>.json`：该发布方拥有的文件及 SHA-256，只由它自己改写。本流水线为 `pipeline_carstable_to_webapp.json`。
- `_publishers/registry.json`：每个发布方一项（`nav` 入口、发布时间），各自只改写自己的键。
- `tools/publish_site_copy.py` 只新增、更新、删除本流水线登记的文件，未变化的文件跳过；与其他发布方已登记的路径或无人登记的现有文件冲突时整体拒绝，不做改动。首次运行（尚无本流水线登记）时，把其他发布方未登记的现有文件视为本流水线此前整站发布的内容。
- `site-common.js` 读取 `registry.json`，把其他发布方的 `nav` 入口补进侧栏（含 `viewer.js` 自绘的侧栏）和主页卡片；构建时 `add_site_common_script` 让每个根目录页面都加载它。GitHub Pages 上没有登记文件，只显示本站页面。

发布站点校验：

```powershell
python tools/validate_publish_site.py public
```

## 备份与清理

备份包含 `input/`、`artifact/`、`public/` 和 `configs/`：

```powershell
python tools/backup.py create
python tools/backup.py list
python tools/backup.py verify <存档名>
python tools/backup.py restore <存档名> --force
```

清理只移除当前输入和发布结果，历史 artifact 永远保留：

```powershell
python tools/cleanup.py --dry-run
python tools/cleanup.py --force
```

## 配置入口

主要配置在 `configs/pipeline.yaml`：

- `paths.input_dir`：源文件目录。
- `paths.artifact_root`：批次根目录。
- `paths.public_dir`：当前发布目录。
- `paths.nas_publish_dir`：NAS 发布目录。
- `file_rules.input_patterns`：输入格式，默认支持 CSV/XLSX/XLSM。
- `input.source`：`all_cars_data` 时按 A2 产线导入（产线名即 `{stem}`）；`input.lines` 可限定/排序产线。
- `input.store`：由产线名（或旧模式的文件名）生成店铺名和标签。
- `columns`：输入字段别名。
- `steps`：流水线命令和启停状态。

HTML 样式位于 `configs/html-style.yaml`，AI 缩写补全位于 `configs/ai-user-size.yaml`。

## 尺码参考、店铺分组与尺码配对数据源

- 产线输入不再手工复制到 `input/`：`import_a2_compressed` 直接读取 A0/A2 发布物并把来源版本写入 `pipeline.generated.json` 的 `sources`。
- `size-ref.html`（US/EU/RU）与 `store-groups.html` 读取 A0 `output/<国别>/尺码匹配报告.md` 中的尺码规则与店铺货架表格，`size-match.html` 的 US（含店铺下拉）/EU/RU 数据源读取 A0 国别全量表与店铺全量表；均校验上游 manifest 的 sha256。
- 尺码配对的非皮卡、皮卡分开检索：搜索区「类别」切换（默认非皮卡），数据按 类别 + MAKE 分片（清单 `make_groups[].kind`、`sources[].kind_counts`，记录带 `kind`），只加载当前类别的分片；A0 全量表按 `分类` 为“皮卡”判定（EU 的 Chassis Cab 等也归皮卡），A1 按来源表 `压缩尺码表_皮卡.csv` 判定。非皮卡的表格与表格设置不显示 CAB、BED。
- 尺码配对页只有一张表：A1 压缩尺码表（原「压缩代号」的显示方式），不再有数据视图切换。数据源 US 全量、US 店铺（HNT、TM、TM_拆分，店铺下拉切换）、EU、RU（侧栏 SOURCE 切换），即 A1 `output/<产线>/压缩尺码表[_皮卡].csv`（非皮卡表与皮卡表按类别分开检索）；列为 CODE、MODEL、版本、TYPE（皮卡为 Pickup）、SHAPE、YEAR、CAB、BED、销量合计（A1 尺码销量总和）、L/W/H（A1 最大长/宽/高-MM，记录来源车型的最大值，随单位切换）、长度余量、SIZE（A1 BACKSIZE，RU 为亚马逊尺码）。CODE = 02.代码映射 MAKE_CODE + MODEL_CODE + 年份码（由 A1 生成，只有 US 区域产线有，EU/RU 显示 —）；CODE 在首列（勾选框之后），点击展开/收回该记录覆盖的来源车型（A1 `<产线>/压缩来源.csv`：A0 全量表行及被覆盖年份），逐行显示各年份长宽高（最大值加粗）、SHAPE 与长度余量。SHAPE 属于来源车型：收起时表格不显示 SHAPE 列，本页有展开的记录时才出现，且只填在来源行。`tools/build_size_match_code_data.py` 校验 A1 manifest sha256，并要求 A1 manifest 登记的上游 A0 文件 sha256 与当前 A0 一致，再按 DIMENSION-ID 回查 A0 同产线全量表（店铺用 `US/店铺/店铺全量_<店铺>.csv`）给来源行补 SHAPE、长度余量、规则ID、匹配尺码；记录的 SHAPE 为来源行车形去重（多个用 ` / ` 连接），长度余量取来源行最小值，来源行规则ID 一致时记录带规则ID（SIZE 悬停显示命中规则）；清单 `size-match-code.json` 的 `origin.a0_version` 为所依据的 A0 版本，`shape_labels` 为 SHAPE 中文名与说明（取自 03 车型族研究的标签定义，新车形缺说明时构建打印提示）。SHAPE 以小字显示，悬停显示中文名与说明（压缩记录含多种车形时逐个列出）。旧 `size-match-code.html` 是跳转页（查询参数原样带到 `size-match.html`），主页不再单独有压缩代号入口。前端资源版本号（`ASSET_VERSION`）由 `build_publish_site.py` 在构建后写入。
- 尺码配对的结果表（`site_overrides/assets/app/viewer.js`，构建时叠加到 `public/`）：列宽按表头文字与当前页内容自动计算，列名完整显示；总宽超出时先压缩可换行的 MODEL/版本/TYPE/CAB，减少被右侧固定列遮挡；点击列名循环 升序/降序/不排序，点击漏斗打开排序与筛选弹层（选项搜索、计数、多选，回车只保留搜索结果；数值列按当前单位填范围），点击外部或 Esc 关闭。
- 全局搜索支持 8 位车型代码：代码 = MAKE_CODE(2) + MODEL_CODE(2) + 起始年(2) + 结束年(2)，如 `01039426` = Ford Mustang 1994-2026，匹配同 MAKE、同 MODEL 且年份与该区间有交集的记录（两位年份不晚于明年按 20xx，否则按 19xx）；摘要行显示代码含义，代码车型不在当前类别时自动切换皮卡/非皮卡。前四位的对照表 `data/generated/vehicle-codes.json` 由 `build_size_match_code_data.py` 从 A1 压缩表 CODE 列生成（同一前四位对应不同车型时构建失败），`validate_publish_site.py` 检查 US 区域产线每条记录的前四位都已收录；页面只在查询含 8 位数字时加载它。
- SIZE 列悬停显示该尺码的规则（`size-rules.json`，与尺码参考页同源），按记录所属国别分别取 US/EU/RU 规则：US/EU 显示分类/尺码池（EU 为模式/版本）、适配车长 = [长上限 − 余量长容差, 长上限]、插片指数限制（上限 999 视为不限）、白名单与备注；RU 显示 OZON/发货尺码、长宽高上限与适配车长 = [长_mm − 余量长上限_mm, 长_mm]。余量长容差由 `build_size_rules_data.py` 从 A0 报告正文读出写入 `length_tolerance`。店铺来源（HNT/TM/TM_拆分）的 SIZE 是发货尺码，按 `store-groups.json` 换回对应的匹配尺码逐个列出。长度随页面单位（mm/cm/in）换算。
- 尺码配对的「车型尺寸演变」可视化（实施说明见 [size-match-visualization-startup.md](size-match-visualization-startup.md)）：表格每行只有选择框（表头为不带文字的「选择本页」勾选框，大纲的 MODEL 组可一次勾选本页该车型、叶子可单选），统一勾选后点结果工具栏「车型可视化（已选 N）」打开已选记录所属车型的完整历史（勾选的配置优先显示）。表格是 A1 压缩记录，历史数据读 A0 全量分片（页面配置 `evolution.historyDataPath` = `size-match-full.json`）：车型、配置与锚点都按压缩记录覆盖的来源行（产线 + DIMENSION-ID）计算，「定位原记录」翻到覆盖该年份的压缩记录、展开来源行并高亮对应行；未勾选时全部匹配结果只有一个车型就直接打开，否则打开车型选择器。选择按压缩记录的稳定 recordKey 保存，A0 历史记录的 recordKey 为 source + DIMENSION-ID（同 ID 内容不同时加指纹），翻页/排序/视图切换保留，source 或类别切换清空。弹窗为长度区间阶梯主图 + 可展开的宽/高图 + 每配置一行的 SIZE 年份时间带（同年冲突分支各占子行），共用年份轴、缩放与悬浮年份；范围默认完整车型历史（命中当前筛选的记录加粗），可切到仅当前筛选（打开时快照）；配置按 版本/TYPE/座位（只认 5seat、7-seater、7座 等明确标记）/皮卡 CAB、BED 筛选，图例默认最多 6 个配置；点击区间锁定详情（DIMENSION-ID、定位原记录 / 查看该车型记录）。「规则叠加」按 A0 全量表的 `规则ID`（命中规则，见 A0 报告规则表末列）在同版本 `size-rules.json` 中查到规则：长度图画长度条件带 [长上限 − 余量长容差, 长上限] 与长上限虚线（标注尺码），RU 另在宽/高图画该规则的宽/高上限；分类、尺码池、版本、插片指数、白名单只在详情中说明，不据此判断适配；全量数据与规则版本不一致或规则ID 查不到时不叠加。店铺来源的 SIZE 是发货尺码，详情中的匹配尺码取 A0 店铺表的 `匹配尺码`（换码前）；SIZE 列悬停在记录带 规则ID 时只显示命中的那一条规则。SHAPE 为 03.车形分类核定 COVER_SHAPE 经 A0 回填，不参与尺码计算。源码：`site_overrides/assets/app/size-evolution-data.js`（纯函数，`node --test tests/js/size-evolution-data.test.cjs`）、`size-evolution.js`、`size-evolution.css`，本地 ECharts 5.6.0 在 `site_overrides/assets/vendor/echarts/`（Apache-2.0，首次打开时懒加载）；`build_publish_site.py` 的 `add_size_evolution` 只给 `size-match.html` 注入脚本与 `evolution.enabled` 开关，`validate_publish_site.py` 检查资源存在、其他页面未加载、历史路径指向 size-match-full.json、压缩表 a0_version/全量分片/规则/货架为同一 A0 版本、页面没有数据视图切换，且全量分片的每个规则ID 都能在 size-rules.json 中找到。
- 这些页面和数据由 `site_overrides/` 与 `tools/build_size_rules_data.py`、`tools/build_size_match_data.py`、`tools/build_size_match_code_data.py` 在站点构建后叠加到 `public/`；size chart 按 6 条产线（US 全量、HNT、TM、TM_拆分 店铺发货尺码、EU、RU）生成。
