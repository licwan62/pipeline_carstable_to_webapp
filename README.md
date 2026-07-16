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
├─ backup.py
├─ cleanup.py
├─ requirements.txt
├─ bak/                       # 本地存档（默认不提交 Git）
├─ configs/
│  ├─ pipeline.yaml
│  ├─ pipeline-steps.yaml
│  ├─ compress-field-profile.yaml
│  ├─ html-style.yaml
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

## 存档与恢复

`data` 是单项目工作区；不同项目通过 `bak` 下的项目存档区分。`backup.py` 会把当前 `data` 和 `configs` 完整复制到同一个存档目录，并生成包含 SHA-256 的 `manifest.json`。当 `data/input` 只有一个 xlsx 时，默认使用其文件名作为项目存档名：

```text
bak/0706/
├─ data/
├─ configs/
└─ manifest.json
```

创建存档（省略命令时也默认创建）。如果同名项目已经存在，会在名称后追加时间：

```powershell
python backup.py create
# 或使用容易辨认的名字
python backup.py create --name before-adjustment
```

查看、校验已有存档：

```powershell
python backup.py list
python backup.py verify 0706
```

恢复存档需要明确加 `--force`。恢复前，脚本会先把当前内容另存为 `pre_restore_*` 安全存档：

```powershell
python backup.py restore 0706 --force
```

存档成功并通过校验后，立即清空当前工作区：

```powershell
python backup.py create --clean-workspace
# --clean 和 --no-keep-workspace 是同一选项的别名
```

也可以单独预览或执行清理。清理范围只有 `data/input`、`data/middle` 和 `data/output`，`data/template` 会保留：

```powershell
python cleanup.py --dry-run
python cleanup.py --force
```

`bak/` 已加入 `.gitignore`，避免把体积较大的本地存档提交到仓库。

## 基本命令

先安装依赖：

```powershell
pip install -r requirements.txt
```

把待处理的 `.xlsx` 放进：

```text
data/input/
```

工作区一次只处理一个项目。若 `data/input` 中有多个 xlsx，请只保留一个，或使用 `--case` 指定其中一个。

试跑，不真正执行外部步骤：

```powershell
python run_all.py --dry-run
```

正式运行全部任务：

```powershell
python run_all.py
```

当前工作区就是默认 case 目录，下面两条命令等价：

```powershell
python run_all.py
python run_all.py --case .
```

如果要指定另一份流程配置：

```powershell
python run_all.py --config configs/pipeline.yaml --case .
```

## 增量更新原项目

增量文件需要包含与原项目相同的三个工作表：`ALL尺码匹配`、`TM尺码匹配`、`HNT尺码匹配`。例如原项目为 `data/input/0706.xlsx`，新增车型文件为 `data/input/0706_new.xlsx`：

```powershell
# 只检查将执行的增量流程
python run_all.py --case . --incremental data/input/0706_new.xlsx --dry-run

# 正式增量更新
python run_all.py --case . --incremental data/input/0706_new.xlsx
```

`--case` 现在只表示包含 `data/` 的项目目录，不再区分 `--case` 和 `--bak-project`。如果原项目保存在 `bak`，直接指定存档目录：

```powershell
python run_all.py --case bak/20260716_111604 --incremental data/input/0716_incr.xlsx
```

程序会从该目录的 `data/input` 中唯一的基础 Excel 自动得到项目名。例如基础文件为 `0706.xlsx`：

- 新式结构读取 `data/middle/02_user_size_workbooks`。
- 旧式存档自动读取 `data/middle/0706/02_user_size_workbooks`。
- `01_compress`、`03_user_size_exports`、`04_html` 和 `output/site` 使用相同的结构识别规则。

增量模式会依次执行：

1. 在 `work/incremental/` 隔离目录中单独压缩增量文件。
2. 核验每条增量原子事实，只有全部为 `OK` 才继续。
3. 按车型键合并三个匹配表；完全重复的行跳过，相同车型键但内容不同则停止，旧车型修改应走全量更新。
4. 不再重新压缩完整项目；复用原项目 `01_compress`，把增量压缩表和原子事实去重合入。
5. 原子核验只覆盖新增原子，以及原项目中 `MAKE + MODEL + BACKSIZE` 组合键与新增数据重叠的历史原子；不会重新检查无关历史车型。
6. 同步用户尺码工作簿：所有自动公式列都以 `data/template/尺码适配表.xlsx` 第一条数据行的当前公式重新向下填充；人工改成固定值的 `SIZE` 会保留。
7. 完整构建成功后先创建 `bak/<项目>_pre_incremental_*` 安全存档，再事务式替换当前 `input/middle/output`。

增量执行失败时，当前工作区保持不变，隔离目录会保留用于排查。如果增量文件放在 `data/input`，成功合并后它会从工作区移除，但原文件仍保存在安全存档中。

为保证合并后的工作簿可以立即被压缩器稳定读取，三个“尺码匹配”工作表中的公式会固化为文件里已经计算并保存的值；其他工作表保持原结构。提交增量文件前应先用 Excel/WPS 打开并保存一次，确保公式缓存是最新的。

增量模式包含人工确认环节：三个用户尺码工作簿会复制到 `data/middle/02_user_size_workbooks`。请在这个目录打开文件，让新增行公式计算完成并保存，然后回到终端按 Enter；脚本会把修改同步回隔离区继续运行。非交互环境不会跳过这个确认。

## 断点续跑

查看可续跑的步骤名：

```powershell
python run_all.py --list-steps
```

当前默认步骤：

```text
compress
atom_validate
user_size_template
user_size_validate
inplace_table
get_html
publish
```

常用断点：

```powershell
# 已经生成/保存过用户尺码模板，从校验和导出继续
python run_all.py --case . --from-step user_size_validate

# 已经导出过用户尺码 TSV，只重新生成 HTML 和发布
python run_all.py --case . --from-step get_html

# 只跑到用户尺码模板生成
python run_all.py --case . --to-step user_size_template

# 只重新导出用户尺码 TSV
python run_all.py --case . --from-step inplace_table --to-step inplace_table
```

`--from-step` 和 `--to-step` 可以组合使用，避免每次从压缩第一步重跑。

## 默认流程

1. `compress`：调用 `compress_to_size_chart/process_tsv.py`，读取输入 Excel 的尺码匹配工作表，输出压缩 TSV 和原子检查表到 `data/middle/01_compress/`。
2. `atom_validate`：确认所有原子检查结果均为 `OK`，发现未命中、重复命中或尺码不一致时立即停止。
3. `user_size_template`：基于 `data/template/尺码适配表.xlsx` 生成三个中间工作簿到 `data/middle/02_user_size_workbooks/`。
4. 人工打开中间工作簿，让模板公式计算用户展示尺码 `SIZE`，按需调整后保存。
5. `user_size_validate`：校验三个中间工作簿结构是否完整。
6. `inplace_table`：把 ALL/TM/HNT 中间工作簿导出成 HTML 专用 TSV，并过滤 `SIZE` 空白或 `无可用尺码` 的行。
7. `get_html`：分别生成 ALL/TM/HNT HTML。
8. `publish`：在本项目的 `05_publish_workspace` 中临时复刻 webapp 构建结构，借用 `publish_tables_to_webapp/tools/build_site.py` 构建，并输出到 `data/output/site/`。

## 配置文件

### `configs/pipeline.yaml`

日常维护入口。这里只保留项目位置、工作区路径、输入规则和步骤开关：

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

需要临时关闭某个步骤时，修改对应的 `enabled`：

```yaml
steps:
  compress:
    enabled: true
  get_html:
    enabled: true
  publish:
    enabled: true
```

`pipeline.yaml` 通过 `include: pipeline-steps.yaml` 载入高级配置；主文件里的同名设置会覆盖高级配置。

### `configs/pipeline-steps.yaml`

高级流程定义，包含内部变量、具体命令、产物检查和人工暂停提示。日常运行不需要修改。只有新增步骤、替换脚本或调整中间目录结构时才改这个文件。

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

HTML 数据字段配置。它面向 `inplace_table` 导出的 TSV，核心是使用用户展示尺码 `SIZE`：

```yaml
exclude_rows: SIZE=""; BACKSIZE=无可用尺码
non_pickup_size_column: SIZE
pickup_size_column: SIZE
```

它通过 `extends: html-style.yaml` 继承公共视觉样式。

### `configs/html-style.yaml`

统一维护页面尺寸、分页、列宽、字体、颜色、Logo 和尺码徽章。两种 HTML 数据配置都会继承它，因此样式只需修改一次。十六进制颜色需要保留引号，例如 `"#ffffff"`。

### `configs/html-direct-from-compress-preference.yaml`

备用数据字段配置：直接从压缩 TSV 生成 HTML 时使用 `BACKSIZE`。当前默认流程不用它；它同样继承 `html-style.yaml`，不再重复保存整份视觉样式。

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
data/middle/01_compress/             压缩 TSV 和压缩工作簿
data/middle/02_user_size_workbooks/ 用户尺码中间工作簿
data/middle/03_user_size_exports/   HTML 专用 TSV
data/middle/04_html/                生成的 HTML/CSS，目录结构为 ALL/TM/HNT + nonpick/pick
data/middle/05_publish_workspace/   临时 webapp 构建工作区
data/output/site/                   最终静态站点
logs/<运行时间>/<任务名>/                     每步日志
```

发布时 `data/middle/04_html/ALL/TM/HNT` 会复制到本项目的 `data/middle/05_publish_workspace/data/source/html/`，不会写入 `publish_tables_to_webapp/data/source/html/`。目录要保持 `TM/nonpick/output_001.html`、`TM/pick/output_001.html` 这类结构，否则旧页面清单或缓存页面可能请求不到文件。

发布构建时会自动扫描临时工作区 `data/source/html/` 下包含 `output_*.html` 的目录，并把列表写入生成的网站页面。
