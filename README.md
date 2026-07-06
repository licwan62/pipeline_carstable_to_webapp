# Fitment Pipeline

这个目录是三个 repo 的总控层：把 `data/input` 里的 Excel 自动识别成任务，然后按 `configs/pipeline.yaml` 里的步骤依次调用并传递产物。

默认会串起：

1. `compress_to_size_chart`
2. `generate_size_chart_html`
3. `publish_tables_to_webapp`

## 目录

```text
pipeline_carstable_to_webapp/
├─ run_all.py
├─ requirements.txt
├─ configs/
│  ├─ pipeline.yaml
│  ├─ compress-field-profile.yaml
│  ├─ html-user-size-preference.yaml
│  └─ html-direct-from-compress-preference.yaml
├─ data/
│  ├─ input/
│  ├─ middle/
│  ├─ output/
│  └─ template/
│     └─ 尺码适配表.xlsx
└─ logs/
```

## 基本命令

先安装依赖：

```powershell
pip install -r requirements.txt
```

把待处理的 `.xlsx` 放进：

```text
data/input/
```

试跑，不真正执行外部步骤：

```powershell
python run_all.py --dry-run
```

正式运行全部任务：

```powershell
python run_all.py
```

只跑一个文件，例如 `data/input/0706.xlsx`：

```powershell
python run_all.py --case 0706
```

如果要指定另一份流程配置：

```powershell
python run_all.py --config configs/pipeline.yaml --case 0706
```

## 断点续跑

查看可续跑的步骤名：

```powershell
python run_all.py --list-steps
```

当前默认步骤：

```text
compress
user_size_template
user_size_validate
user_size_export_all
user_size_export_tm
user_size_export_hnt
html_all
html_tm
html_hnt
publish
```

常用断点：

```powershell
# 已经生成/保存过用户尺码模板，从校验和导出继续
python run_all.py --case 0706 --from-step user_size_validate

# 已经导出过用户尺码 TSV，只重新生成 HTML 和发布
python run_all.py --case 0706 --from-step html_all

# 只跑到用户尺码模板生成
python run_all.py --case 0706 --to-step user_size_template

# 只重新导出用户尺码 TSV
python run_all.py --case 0706 --from-step user_size_export_all --to-step user_size_export_hnt
```

`--from-step` 和 `--to-step` 可以组合使用，避免每次从压缩第一步重跑。

## 默认流程

1. `compress`：调用 `compress_to_size_chart/process_tsv.py`，读取输入 Excel 的尺码匹配工作表，输出压缩 TSV 到 `data/middle/<任务名>/01_compress/`。
2. `user_size_template`：基于 `data/template/尺码适配表.xlsx` 生成三个中间工作簿到 `data/middle/<任务名>/02_user_size_workbooks/`。
3. 人工打开中间工作簿，让模板公式计算用户展示尺码 `SIZE`，按需调整后保存。
4. `user_size_validate`：校验三个中间工作簿结构是否完整。
5. `user_size_export_*`：把中间工作簿导出成 HTML 专用 TSV，并过滤 `SIZE` 空白或 `无可用尺码` 的行。
6. `html_*`：分别生成 ALL/TM/HNT HTML。
7. `publish`：复制 HTML 到 webapp，运行发布构建，并输出到 `data/output/<任务名>/site/`。

## 配置文件

### `configs/pipeline.yaml`

主流程配置。最常改的是：

```yaml
repos:
  compress: "../compress_to_size_chart"
  html: "../generate_size_chart_html"
  publish: "../publish_tables_to_webapp"

paths:
  input_dir: "data/input"
  middle_dir: "data/middle"
  output_dir: "data/output"
  logs_dir: "logs"
```

用户尺码模板相关必要设置：

```yaml
variables:
  user_size_template: "{root}/data/template/尺码适配表.xlsx"
  user_size_non_pickup_table_name: "非皮卡高度压缩表"
  user_size_pickup_table_name: "皮卡高度压缩表"
```

这里指定 `user_size_template` 用哪个 Excel 模板；`user_size_non_pickup_table_name` 和 `user_size_pickup_table_name` 指定贴入模板的数据源，默认都是高度压缩表。

每个步骤支持：

```yaml
command:        # 要执行的命令
check_exists:   # 步骤完成后必须存在的文件或目录
copy_before:    # 步骤前复制文件/目录
copy_after:     # 步骤后复制文件/目录
pause_after:    # 需要人工处理时暂停提示
```

### `configs/compress-field-profile.yaml`

压缩输入字段映射。它告诉 `process_tsv.py` 读取哪些 Excel sheet，以及输入列如何映射到压缩脚本的标准字段。

关键设置：

```yaml
input:
  sheets:
    - ALL尺码匹配
    - TM尺码匹配
    - HNT尺码匹配

columns:
  最终尺码:
    - 确认尺码
    - 自动尺码
    - 最终尺码
    - 对应尺码
```

如果输入工作簿名或列名变化，优先改这里。

### `configs/html-user-size-preference.yaml`

HTML 生成配置。它面向 `user_size_export_*` 导出的 TSV，核心是使用用户展示尺码 `SIZE`：

```yaml
exclude_rows: SIZE=""; BACKSIZE=无可用尺码
non_pickup_size_column: SIZE
pickup_size_column: SIZE
```

这里也保留了页面尺寸、列宽、字体、颜色等样式配置，来源逻辑参考 `generate_size_chart_html/configs/combined-preference.yaml`。

### `configs/html-direct-from-compress-preference.yaml`

备用配置：直接从压缩 TSV 生成 HTML 时使用。当前默认流程不用它，因为默认流程必须经过用户尺码模板和 `SIZE` 导出。

## 用户尺码模板

模板文件：

```text
data/template/尺码适配表.xlsx
```

它必须包含：

- `非皮卡压缩表`
- `皮卡压缩表`

`user_size_template` 步骤会从第二行开始贴入压缩数据：

非皮卡：

```text
店铺 / CAR / MAKE / MODEL / YEAR / VERSION / CONST / BACKSIZE
```

皮卡：

```text
店铺 / MAKE / MODEL / YEAR / VERSION / CAB / BED / BACKSIZE
```

其他计算列会沿用模板第二行的公式和样式向下填充，并自动扩展 Excel 表格范围。

## 输出位置

```text
data/middle/<任务名>/01_compress/              压缩 TSV 和压缩工作簿
data/middle/<任务名>/02_user_size_workbooks/  用户尺码中间工作簿
data/middle/<任务名>/03_user_size_exports/    HTML 专用 TSV
data/middle/<任务名>/02_html/                 生成的 HTML/CSS
data/output/<任务名>/site/                    最终静态站点
logs/<运行时间>/<任务名>/                     每步日志
```

发布项目构建时会自动扫描 `data/source/html/` 下包含 `output_*.html` 的目录，并把列表写入生成的网站页面。
