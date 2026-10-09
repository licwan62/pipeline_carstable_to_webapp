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
6. `publish_nas_site`：尝试将完整站点发布到 NAS；NAS 不可用时记录警告，但不影响 `public/` 构建成功。

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
- `size-match-code.html`（「压缩代号」，侧栏与尺码配对平级，主页有入口）与尺码配对共用 `viewer.js` 搜索页（`navKey: "code"`），表格样式、列宽、复制、表头筛选/排序、分页与表格设置一致。数据为 A2 `output/<产线>/压缩尺码表[_皮卡].csv`（US、HNT、TM、TM_拆分；非皮卡与皮卡合为一个数据源，店铺下拉切换），列为 CODE、MODEL、版本、YEAR、TYPE（皮卡为 Pickup）、CAB、BED、销量合计（A2 尺码销量总和）、SIZE（A2 BACKSIZE）；CODE = 02.代码映射 MAKE_CODE + MODEL_CODE + 年份码（由 A2 生成），点击可复制。`tools/build_size_match_code_data.py` 校验 A2 manifest sha256 后按尺码配对相同格式写入 `data/generated/size-match-code*.json`。主页入口与各页面前端资源版本号（`ASSET_VERSION`）由 `build_publish_site.py` 在构建后写入。
- 尺码配对与压缩代号的结果表（`public/assets/app/viewer.js`，构建时保留）：列宽按表头文字与当前页内容自动计算，列名完整显示；总宽超出时先压缩可换行的 MODEL/版本/TYPE/CAB，减少被右侧固定列遮挡；点击列名循环 升序/降序/不排序，点击漏斗打开排序与筛选弹层（选项搜索、计数、多选，回车只保留搜索结果；数值列按当前单位填范围），点击外部或 Esc 关闭。尺码配对数据源不再有 CODE 列（A0 已取消 DIMENSION-CODE）。
- 这些页面和数据由 `site_overrides/` 与 `tools/build_size_rules_data.py`、`tools/build_size_match_data.py`、`tools/build_size_match_code_data.py` 在站点构建后叠加到 `public/`；size chart 按 6 条产线（US 全量、HNT、TM、TM_拆分 店铺发货尺码、EU、RU）生成。
