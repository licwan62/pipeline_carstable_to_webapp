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
│  ├─ html-style.yaml
│  └─ ai-user-size.yaml
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

增量模式包含人工确认环节：合并的用户尺码工作簿会复制到 `data/middle/02_user_size_workbooks`。请在这个目录打开文件，让新增行公式计算完成并保存，然后回到终端按 Enter；脚本会把修改同步回隔离区继续运行。非交互环境不会跳过这个确认。

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
export_images
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

1. `compress`：调用 `compress_to_size_chart/process_tsv.py`，读取输入 Excel 的尺码匹配工作表，输出压缩 TSV 到 `data/middle/<任务名>/01_compress/`。
2. `user_size_template`：读取 `data/rules/user-size-rules.json`，直接生成已缩写、排序的紧凑用户尺码 JSON。
3. `inplace_table`：按 JSON 中的“店铺”列导出各店铺 HTML 专用 TSV，并过滤 `SIZE` 空白或 `无可用尺码` 的行。
6. `get_html`：分别生成 ALL/TM/HNT HTML。
7. `export_images`：递归截图 `04_html` 中的 `output_*.html`，输出 JPG 到 `data/output/<任务名>/images/`，并保留 ALL/TM/HNT 与 nonpick/pick 目录层级。
8. `publish`：在本项目的 `05_publish_workspace` 中临时复刻 webapp 构建结构，借用 `publish_tables_to_webapp/tools/build_site.py` 构建，并输出到 `data/output/<任务名>/site/`。

`get_html` 的非皮卡表会固定 `YEAR` 列宽；当 `MODEL / TYPE` 文字溢出时，只在这两列之间重新分配宽度，再缩小单元格字体。相关列宽都在 `configs/html-style.yaml` 中设置。

`publish` 生成的 `size-match` 以 `L-MM / W-MM / H-MM / 长度余量` 作为标准数据：新表的毫米值直接四舍五入为整数，兼容旧表时会先将英寸或厘米换算为毫米。网页可在 MM/CM/IN 之间切换，显示值均为整数。`size-match` 的尺码配色会从 `configs/html-style.yaml` 同步至发布配置，与 size-chart 保持一致。

发布查询数据采用“来源 + 品牌”二级懒加载：`size-match.json` 是轻量清单，记录按 ALL、TM、HNT 等来源及 MAKE 写入带内容哈希的 `size-match-*.json`。页面选择品牌后才加载对应分片并复用浏览器缓存；结果始终分页显示，避免一次渲染数千行。最终尺码与自动尺码一致且最终长度余量为空时，自动长度余量会作为安全回退。构建和 Pages 工作流都会验证配置字段、分片记录数及尺码参考字段后再发布。

`user_size_template` 写入的店铺、车型、年份、版本、结构、尺码等源数据全部强制为 Excel 文本类型和 `@` 文本格式；复用已有中间工作簿时也会修正这些源数据列，同时保留人工内容。`user_size_validate` 会拒绝包含数字、日期或非文本单元格格式的源数据列，`inplace_table` 导出的所有 TSV 字段会再次统一转换为字符串。

如需让某一个店铺在 `get_html` 阶段显示 `BACKSIZE`、其他店铺仍显示 `SIZE`，在 `configs/html-style.yaml` 中设置 `special_store_value` 及对应尺码列。留空表示关闭特殊店铺覆盖。

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

`pipeline.yaml` 是唯一的流水线配置，包含输入工作表、字段映射、步骤命令、产物检查和人工暂停提示。

每个步骤支持：

```yaml
command:        # 要执行的命令
check_exists:   # 步骤完成后必须存在的文件或目录
copy_before:    # 步骤前复制文件/目录
copy_after:     # 步骤后复制文件/目录
pause_after:    # 需要人工处理时暂停提示
```

输入工作表和压缩字段映射也直接写在 `pipeline.yaml`：

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

`input.sheets` 是数据集的唯一来源；后续工作簿、TSV 和 HTML 目录由代码动态推导。

### `configs/html-style.yaml`

HTML 数据字段、过滤规则和视觉样式统一维护在这里：

```yaml
exclude_rows: SIZE=""; BACKSIZE=无可用尺码
non_pickup_size_column: SIZE
pickup_size_column: SIZE
```

同时维护页面尺寸、分页、列宽、字体、颜色、Logo 和尺码徽章。十六进制颜色需要保留引号，例如 `"#ffffff"`。

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
data/middle/<任务名>/04_html/                 生成的 HTML/CSS，目录结构为 ALL/TM/HNT + nonpick/pick
data/middle/<任务名>/05_publish_workspace/   临时 webapp 构建工作区
data/output/<任务名>/site/                    最终静态站点
logs/<运行时间>/<任务名>/                     每步日志
```

只导出某个任务的图片可运行：

```powershell
python run_all.py --case 0727 --from-step export_images --to-step export_images
```

也可以直接调用脚本；下面的命令会递归处理 HTML 并保留目录层级：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/Export-HtmlPagesToImages.ps1 `
  -InputDir data/middle/0727/04_html `
  -OutputDir data/output/0727/images `
  -HtmlPattern "output_*.html"
```

发布时 `data/middle/04_html/ALL/TM/HNT` 会复制到本项目的 `data/middle/05_publish_workspace/data/source/html/`，不会写入 `publish_tables_to_webapp/data/source/html/`。目录要保持 `TM/nonpick/output_001.html`、`TM/pick/output_001.html` 这类结构，否则旧页面清单或缓存页面可能请求不到文件。

发布构建时会自动扫描临时工作区 `data/source/html/` 下包含 `output_*.html` 的目录，并把列表写入生成的网站页面。

## GitHub Pages 与 Nginx 手动发布

将完整站点生成到 `data/output/site/` 并推送到 `main` 后，GitHub Actions 会同时：

1. 校验并发布 GitHub Pages。
2. 生成 `carstable-webapp-nginx-<提交 SHA>.zip`。ZIP 根目录直接包含 `index.html`、`assets/`、`config/` 和 `data/`，可在对应工作流运行页的摘要或 Artifacts 区域下载。

把 ZIP 解压到服务器目录，例如 `/var/www/carstable`，然后使用以下 Nginx 配置：

```nginx
server {
    listen 80;
    server_name example.com;

    root /var/www/carstable;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

启用配置后先执行 `sudo nginx -t`，验证成功再执行 `sudo systemctl reload nginx`。如果网站挂在域名的子路径下，还需为该子路径设置匹配的 `location` 和 `alias`；直接使用域名根路径时无需修改站点文件。
