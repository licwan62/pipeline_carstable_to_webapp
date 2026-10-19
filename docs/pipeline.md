# 车型尺码流水线

本项目采用 `上游发布物 + work + artifact + public` 模式：产线输入直接读取 all_cars_data 已发布的 A0 全量表与 A1.压缩尺寸信息 压缩表（按 manifest 校验 sha256）。上游目录由 `configs/pipeline.yaml` 的 `paths.a0_output_dir`、`paths.compressed_output_dir`（原名 `a2_output_dir`，旧键仍兼容）指定，代码中不写死。

```text
../all_cars_data/A0.尺码计算/output/      <国别>/全量/全量表.csv、US/店铺/店铺全量_<店铺>.csv、
                                    <国别>/尺码规则.json、US/店铺货架.json、US/新旧尺码对应.csv（机器接口）、
                                    <国别>/尺码匹配报告.md（供人阅读）
../all_cars_data/A1.压缩尺寸信息/output/  <国别>/压缩尺码表.csv、<国别>/压缩尺码表_皮卡.csv
input/                              旧的人工输入（仅 input.source 不是 all_cars_data 时使用）
configs/
  pipeline.yaml                     流水线配置
  user-size-rules.json              尺码和缩写规则的唯一活动来源
work/<批次>/                        中间工作目录（不纳入 git）：成功后删除，失败保留供诊断
artifact/
  2026-09-01_01_最后的老尺码/       迁移前历史产物，只读保留
  YYYY-MM-DD_NN_pipeline/           每次运行的批次清单与去重后的站点字节（v3，见下文）
public/                             当前可部署站点（只在构建并完整校验成功后切换）
logs/                               运行日志（不纳入 git）
bak/                                tools/backup.py 的本地备份（不纳入 git）；.bak/ 为早期备份，同样只在本地保留
```

## 运行

先在 all_cars_data 发布 A0/A1（`python scripts/publish_release.py`），然后执行：

```powershell
python tools/run_all.py              # 新批次：固定上游 → 构建 → 校验 → 切换 public → 发布 NAS
python tools/run_all.py --keep-work  # 成功后保留 work/<批次>/ 中间文件
python tools/run_all.py --dry-run    # 只打印各步骤命令
```

`tools/run_all.py` 只做编排，模块划分：

| 模块 | 职责 |
| --- | --- |
| `tools/pipeline_core.py` | 配置加载与旧键/旧步骤名迁移、变量展开、逐步执行 |
| `tools/upstream_pin.py` | 运行开始固定 A0/A1 发布物到 `work/<批次>/upstream/`，所有步骤读同一份 |
| `tools/import_compressed_tables.py` | 导入产线全量表与压缩表（原 `import_a2_compressed.py`，旧文件名保留兼容入口并打印迁移提示） |
| `tools/build_publish_site.py`、`tools/site_promote.py` | 在 work 内构建并完整校验站点，成功后切换 public，失败回滚 |
| `tools/site_batch.py` | v3 批次清单、站点字节去重存储与恢复 |
| `tools/run_legacy.py` | 旧手工输入的增量模式（需要外部 `compress_to_size_chart`） |

### 固定上游输入

运行开始时 `upstream_pin.py` 按 A0、A1 的 `output/manifest.json` 把全部交付物复制到 `work/<批次>/upstream/<键>/`，逐文件校验 sha256；复制后再读一次 manifest，期间上游重新发布或任一文件不一致即失败（此时尚未修改 public）。之后所有步骤（导入、尺码 JSON、尺码配对/规则数据、站点校验）只读固定副本，不会在不同步骤重新选择上游版本。运行上下文写入 `work/<批次>/run_context.json` 并登记到批次清单。

新旧尺码对应优先读取固定的 A0 发布物 `US/新旧尺码对应.csv`；A0 尚未发布该文件时退回 `paths.size_code_map_file`（A0 `data/`，兼容模式，打印警告并把该文件快照进批次 `extra/`）。尺码规则与店铺货架同理：A0 manifest 登记了 `<国别>/尺码规则.json`、`US/店铺货架.json` 时读 JSON，否则兼容模式解析 `尺码匹配报告.md` 的表格。

## 批次（v3）

每次不带 `--artifact` 的执行都会分配一个新批次 `artifact/YYYY-MM-DD_NN_pipeline/`，中间文件写在 `work/<批次>/`：

```text
work/<批次>/                       # 不纳入 git；成功后删除（--keep-work 保留），失败保留
  upstream/<键>/...                固定的上游发布物副本
  run_context.json                 固定时的上游版本、文件 sha256、来源 artifact
  00_input/pipeline.generated.json、00_input/tables/*.csv
  01_compressed_fitment/**/*.csv
  02_user_size.json
  03_store_csv/**/*.csv
  04_store_html/
  05_site_workspace/_site/         临时站点（构建、叠加、校验都在这里完成）
  site_manifest.json、nas_publish.json

artifact/<批次>/                   # 不可变记录
  artifact.json                    清单：状态、各步骤状态、上游引用、仓库 commit、配置哈希、public/NAS 发布状态
  site_files.json                  最终站点文件清单 [{path, sha256, bytes, stored_in}]
  site/<path>                      本批次新出现的站点字节（与已有 v3 批次相同的只记引用，不复制）
  upstream/<键>/manifest.json      上游 manifest 副本；无法引用的上游文件快照（gzip）
  config/<path>                    未提交或已修改的配置快照
  external/<仓库>.diff.gz          外部工具仓库未提交改动快照
  extra/*.gz                       中间大表（gzip）与人工核对清单
```

- **输入**：已发布的上游交付物记引用（节点、版本、上游仓库 commit、`artifact_file`、sha256），不记当前 `output/` 路径；上游 artifact 文件缺失或字节不一致时才快照。
- **代码与配置**：登记本仓库及实际使用的外部仓库（`publish_tables_to_webapp`、`generate_size_chart_html`）的 commit 与未提交改动；旧模式压缩工具 `compress_to_size_chart` 以 `required: false` 登记版本，正式模式不要求存在。`configs/` 下文件记 sha256，未提交的复制快照。
- **状态**：构建成功（`publish.public`：`promoted`/`failed`）与 NAS 发布（`publish.nas`：`published`/`failed`/`disabled`）分别记录。
- 不再把整个站点工作区永久复制进批次（旧批次的 `05_site_workspace/` 约 1.5 GB 即由此而来）。

查看与恢复：

```powershell
python tools/site_batch.py show 2026-10-14_01_pipeline
python tools/site_batch.py restore 2026-10-14_01_pipeline --dest <空目录> --validate   # 按 site_files.json 还原完整站点并逐文件校验 sha256
```

v1/v2 旧批次只读识别，不改写。

## 批次恢复执行

查看步骤：

```powershell
python tools/run_all.py --list-steps
```

从未完成的批次的某一步继续：

```powershell
python tools/run_all.py --artifact 2026-10-14_01_pipeline --from-step build_user_size_json
```

`--from-step` 必须同时指定 `--artifact`。只有状态为 `running`/`failed`/`partial` 且 `work/<批次>/` 仍在的 v3 批次允许恢复；恢复时校验固定的上游副本未被改动。已完成的批次不能恢复，重跑会创建新批次。也可以用 `--to-step` 创建新批次并停在指定步骤。

当前六个步骤统一采用“动作 + 产物”命名：

1. `import_compressed_tables`（原 `import_a2_compressed`）：按 A1 发布的产线（US、HNT、TM、TM_拆分、EU、RU；`input.lines` 可限定）从固定副本导入 A0 全量表与 A1 高度压缩表，生成运行时 JSON。压缩与原子检查在 all_cars_data 的 `A1.压缩尺寸信息`。
2. `build_user_size_json`：应用尺码及缩写规则，生成紧凑 JSON。
3. `export_store_csv`：按店铺导出 HTML 输入 CSV。
4. `generate_store_html`：生成各店铺尺码表 HTML。
5. `build_public_site`：在 `work/<批次>/05_site_workspace/_site` 构建站点（骨架、页面叠加、尺码配对/规则数据、资源版本），运行完整站点校验，成功后切换 `public/`。
6. `publish_nas_site`：尝试将本流水线的站点文件发布到 NAS（只更新本流水线登记的文件，见“发布”）；NAS 不可用时记录失败，但不影响已切换的 `public/`。

旧名兼容：步骤名 `import_a2_compressed` 与 `import`、`prepare_inputs` 等别名仍可用于 `--from-step`/`--to-step`；配置中仍写旧步骤名或 `paths.a2_output_dir` 时自动迁移并打印提示，新旧名同时出现且不一致时报错。`--list-steps` 和新日志只显示标准名称。

## 规则

尺码、分类、车型/驾驶室/类型缩写全部由以下 JSON 维护：

```text
configs/user-size-rules.json
```

运行时不再读取或生成“尺码适配表”模板工作簿。历史批次中的 `template/` 仅是迁移快照，不参与当前流水线。

## 构建与发布

`build_public_site` 的顺序：

1. 外部站点骨架（`publish_tables_to_webapp`）只复制构建需要的源文件与资源（`assets/`、`config/`、`pages/`、构建脚本与 `data/generated/size-ref.json`），不复制可重新生成的数据；当前 `public/` 不参与构建，前端权威源码在 `site_overrides/`。
2. 在临时站点内完成店铺页面、页面叠加、尺码配对与规则数据、资源版本号处理，写出 `site_manifest.json`。
3. 对临时站点运行 `validate_publish_site`；失败则 public 的全部文件保持原字节，诊断信息写入批次 `artifact.json` 与 `extra/logs/`，中间文件留在 `work/<批次>/`。
4. 校验成功后由 `site_promote.py` 切换 `public/`：首选两次重命名（`public` → `.public.prev-<时间>`，临时站点 → `public`），被资源管理器/同步盘锁定时改为“完整备份 + 就地镜像”。切换后对新 `public/` 再校验一次，任一步失败恢复上一版。Windows 上这是多步操作，不是原子替换：两次重命名之间有极短的无 `public` 窗口；回滚本身失败时保留 `.public.prev-*` 副本并在错误中给出路径。
5. 之后才发布 NAS；NAS 状态单独记录。

成功运行后：

- 批次清单与新出现的站点字节保存在 `artifact/<批次>/`。
- 最新站点写入 `public/`。
- 流水线随后尝试将站点发布到 `\\NAS8824B4\Web\car`。
- GitHub Pages 工作流发布已提交的 `public/`（因此 `public/` 仍纳入 git）。

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

## 批次归档

```powershell
python tools/archive_artifacts.py --keep 5                     # 预演（默认）：列出将归档与受保护的批次
python tools/archive_artifacts.py --keep 5 --dest "\\NAS8824B4\Public\PQData\bak\pipeline_carstable_to_webapp\artifact" --execute
python tools/archive_artifacts.py --find <批次>                # 查归档位置
python tools/archive_artifacts.py --restore <批次>             # 复制回 artifact/ 并逐文件校验
```

受保护（不移动）：当前发布来源（内容与当前 public 一致的批次）、最近 N 个批次、可恢复的未完成批次、受保护批次 `site_files.json` 递归引用的批次、含未提交文件的批次。执行时逐批次复制、逐文件校验 sha256 后才删除本地，追加到仓库根目录 `artifact_archive.json`，目标根目录同步写 `ARCHIVE_INDEX.json`。

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
- `input.source`：`all_cars_data` 时按 A1 产线导入（产线名即 `{stem}`）；`input.lines` 可限定/排序产线。
- `input.store`：由产线名（或旧模式的文件名）生成店铺名和标签。
- `columns`：输入字段别名。
- `steps`：流水线命令和启停状态。

HTML 样式位于 `configs/html-style.yaml`，AI 缩写补全位于 `configs/ai-user-size.yaml`。

## 尺码参考、店铺分组与尺码配对数据源

- 产线输入不再手工复制到 `input/`：`import_compressed_tables` 读取运行开始时固定的 A0/A1 发布物并把来源版本写入 `pipeline.generated.json` 的 `sources`。
- `size-ref.html`（US/EU/RU）与 `store-groups.html` 读取 A0 机器接口 `output/<国别>/尺码规则.json`、`US/店铺货架.json`（A0 未发布时兼容解析 `尺码匹配报告.md` 的表格），`size-match.html` 的 US（含店铺下拉）/EU/RU 数据源读取 A0 国别全量表与店铺全量表；均校验上游 manifest 的 sha256。
- 尺码配对的非皮卡、皮卡分开检索：搜索区「类别」切换（默认非皮卡），数据按 类别 + MAKE 分片（清单 `make_groups[].kind`、`sources[].kind_counts`，记录带 `kind`），只加载当前类别的分片；A0 全量表按 `分类` 为“皮卡”判定（EU 的 Chassis Cab 等也归皮卡），A1 按来源表 `压缩尺码表_皮卡.csv` 判定。非皮卡的表格与表格设置不显示 CAB、BED。
- 尺码配对页（设计需求与自动验收见 [size-match-acceptance.md](size-match-acceptance.md)）读**一份数据** `size-match-data.json`，搜索区「视图」控件切换 **压缩表 / 全量表**（默认压缩表，`?view=full` 直达，切换保留搜索词、数据源、类别与 MAKE，只清列筛选与排序，不重新下载数据）。每个分片（产线 × 类别 × MAKE）同时存 A0 全量行 `records`（全量表视图，也是车型可视化的历史）与 A1 压缩记录 `compressed`（只存聚合值与 `refs` = [行号, 被覆盖年份]，来源行由页面 `expandMatchShard` 从全量行还原，不再内嵌 A0 行；旧的 `size-match-code*`、`size-match-full*` 两套数据不再发布）。全局搜索按字段语义匹配（`viewer-data.js` `recordMatchesSearchToken`）：数字词只比四位年份、≥4 位 CODE 前缀与车型/版本的整段数字（`bmw 7` 只出现 7 系），字母词比 MAKE/MODEL/版本/TYPE/SHAPE/CAB/BED/SIZE/CODE 的单词前缀（连字符可省略，`f150`、`crv`），长宽高、销量、长度余量不参与。年份区间（`2008-2026`）按与记录年份的交集匹配；逐词收窄，数据里没有对应值的词（`short bed`、`cab`）忽略并在摘要提示，不清空结果；查询提到的车型只属于皮卡时自动切到皮卡全量表（`queryVehicleKind`，依据 `vehicle-codes.json`，见验收文档 R7）。以下为压缩表视图。数据源 US 全量、US 店铺（HNT、TM、TM_拆分，店铺下拉切换）、EU、RU（侧栏 SOURCE 切换），即 A1 `output/<产线>/压缩尺码表[_皮卡].csv`（非皮卡表与皮卡表按类别分开检索）；列为 CODE、MODEL、版本、TYPE（皮卡为 Pickup）、SHAPE、YEAR、CAB、BED、销量合计（A1 尺码销量总和）、L/W/H（A1 最大长/宽/高-MM，记录来源车型的最大值，随单位切换）、长度余量、SIZE（A1 BACKSIZE，RU 为亚马逊尺码）。CODE = 02.代码映射 MAKE_CODE + MODEL_CODE + 年份码（由 A1 生成，只有 US 区域产线有，EU/RU 显示 —）；CODE 在首列（勾选框之后），点击展开/收回该记录覆盖的来源车型（A1 `<产线>/压缩来源.csv`：A0 全量表行及被覆盖年份），逐行显示各年份长宽高（最大值加粗）、SHAPE 与长度余量。SHAPE 属于来源车型：压缩表收起时不显示 SHAPE 列，本页有展开的记录时才出现，且只填在来源行；全量表视图每行就是一个车型年份段，直接显示 SHAPE。`tools/build_size_match_code_data.py` 校验 A1 manifest sha256，并要求 A1 manifest 登记的上游 A0 文件 sha256 与当前 A0 一致，再按 DIMENSION-ID 回查 A0 同产线全量表（店铺用 `US/店铺/店铺全量_<店铺>.csv`）（A1 `压缩来源.csv` 与 A0 行字段不一致、来源行跨 MAKE/类别、DIMENSION-ID 重复时构建失败），来源行带 A0 同行的 SHAPE、长度余量、规则ID、匹配尺码；记录的 SHAPE 为来源行车形去重（多个用 ` / ` 连接），长度余量取来源行最小值，来源行规则ID 一致时记录带规则ID（SIZE 悬停显示命中规则）；清单 `size-match-data.json`（format_version 4，`views` 声明两种视图的列）的 `origin.version` 为 A1 版本、`origin.a0_version` 为所依据的 A0 版本，`shape_labels` 为 SHAPE 中文名与说明（取自 03 车型族研究的标签定义，新车形缺说明时构建打印提示）。SHAPE 以小字显示，悬停显示中文名与说明（压缩记录含多种车形时逐个列出）。旧 `size-match-code.html` 已弃用，不再发布（`validate_publish_site.py` 发现站点中有该文件即失败），主页不再单独有压缩代号入口。前端资源版本号（`ASSET_VERSION`）由 `build_publish_site.py` 在构建后写入。
- 尺码配对的结果表（`site_overrides/assets/app/viewer.js`，构建时叠加到 `public/`）：列宽按表头文字与当前页内容自动计算，列名完整显示；总宽超出时先压缩可换行的 MODEL/版本/TYPE/CAB，减少被右侧固定列遮挡；点击列名循环 升序/降序/不排序，点击漏斗打开排序与筛选弹层（选项搜索、计数、多选，回车只保留搜索结果；数值列按当前单位填范围），点击外部或 Esc 关闭。
- 全局搜索支持 8 位车型代码：代码 = MAKE_CODE(2) + MODEL_CODE(2) + 起始年(2) + 结束年(2)，如 `01039426` = Ford Mustang 1994-2026，匹配同 MAKE、同 MODEL 且年份与该区间有交集的记录（两位年份不晚于明年按 20xx，否则按 19xx）；摘要行显示代码含义，代码车型不在当前类别时自动切换皮卡/非皮卡。前四位的对照表 `data/generated/vehicle-codes.json` 由 `build_size_match_code_data.py` 从 A1 压缩表 CODE 列生成（同一前四位对应不同车型时构建失败），`validate_publish_site.py` 检查 US 区域产线每条记录的前四位都已收录；页面只在查询含 8 位数字时加载它。
- SIZE 列悬停显示该尺码的规则（`size-rules.json`，与尺码参考页同源），按记录所属国别分别取 US/EU/RU 规则：US/EU 显示分类/尺码池（EU 为模式/版本）、适配车长 = [长上限 − 余量长容差, 长上限]、插片指数限制（上限 999 视为不限）、白名单与备注；RU 显示 OZON/发货尺码、长宽高上限与适配车长 = [长_mm − 余量长上限_mm, 长_mm]。余量长容差由 `build_size_rules_data.py` 从 `尺码规则.json` 的 `length_tolerance_mm`（兼容模式为报告正文）写入 `length_tolerance`。店铺来源（HNT/TM/TM_拆分）的 SIZE 是发货尺码，按 `store-groups.json` 换回对应的匹配尺码逐个列出。长度随页面单位（mm/cm/in）换算。
- 尺码配对的「车型尺寸演变」可视化（实施说明见 [size-match-visualization-startup.md](size-match-visualization-startup.md)）：表格每行只有选择框（表头为不带文字的「选择本页」勾选框，大纲的 MODEL 组可一次勾选本页该车型、叶子可单选），统一勾选后点结果工具栏「车型可视化（已选 N）」打开已选记录所属车型的完整历史（勾选的配置优先显示）。历史数据读同一份 `size-match-data.json` 的全量行（页面配置 `evolution.historyDataPath` = `matchDataPath`）：压缩表视图的车型、配置与锚点按压缩记录覆盖的来源行（产线 + DIMENSION-ID）计算，全量表视图直接用该行，「定位原记录」翻到覆盖该年份的压缩记录、展开来源行并高亮对应行；未勾选时全部匹配结果只有一个车型就直接打开，否则打开车型选择器。选择按压缩记录的稳定 recordKey 保存，A0 历史记录的 recordKey 为 source + DIMENSION-ID（同 ID 内容不同时加指纹），翻页/排序/表格大纲切换保留，压缩表/全量表、source 或类别切换清空。弹窗为长度区间阶梯主图 + 可展开的宽/高图 + 每配置一行的 SIZE 年份时间带（同年冲突分支各占子行），共用年份轴、缩放与悬浮年份；范围默认完整车型历史（命中当前筛选的记录加粗），可切到仅当前筛选（打开时快照）；配置按 版本/TYPE/座位（只认 5seat、7-seater、7座 等明确标记）/皮卡 CAB、BED 筛选，图例默认最多 6 个配置；点击区间锁定详情（DIMENSION-ID、定位原记录 / 查看该车型记录）。「规则叠加」按 A0 全量表的 `规则ID`（命中规则，见 A0 报告规则表末列）在同版本 `size-rules.json` 中查到规则：长度图画长度条件带 [长上限 − 余量长容差, 长上限] 与长上限虚线（标注尺码），RU 另在宽/高图画该规则的宽/高上限；分类、尺码池、版本、插片指数、白名单只在详情中说明，不据此判断适配；全量数据与规则版本不一致或规则ID 查不到时不叠加。店铺来源的 SIZE 是发货尺码，详情中的匹配尺码取 A0 店铺表的 `匹配尺码`（换码前）；SIZE 列悬停在记录带 规则ID 时只显示命中的那一条规则。SHAPE 为 03.车形分类核定 COVER_SHAPE 经 A0 回填，不参与尺码计算。源码：`site_overrides/assets/app/size-evolution-data.js`（纯函数，`node --test tests/js/size-evolution-data.test.cjs`）、`size-evolution.js`、`size-evolution.css`，本地 ECharts 5.6.0 在 `site_overrides/assets/vendor/echarts/`（Apache-2.0，首次打开时懒加载）；`build_publish_site.py` 的 `add_size_evolution` 只给 `size-match.html` 注入脚本与 `evolution.enabled` 开关，`validate_publish_site.py` 检查资源存在、其他页面未加载、历史路径与表格同为 size-match-data.json、数据 a0_version/规则/货架为同一 A0 版本，且全量行的每个规则ID 都能在 size-rules.json 中找到。
- 这些页面和数据由 `site_overrides/` 与 `tools/build_size_rules_data.py`、`tools/build_size_match_code_data.py`（A0 行转换在 `build_size_match_data.py`）在站点构建后叠加到 `public/`，切换 public 前运行结构校验与尺码配对数据层验收（`tests/acceptance/size_match_data.cjs`，失败即不发布）；size chart 按 6 条产线（US 全量、HNT、TM、TM_拆分 店铺发货尺码、EU、RU）生成。
