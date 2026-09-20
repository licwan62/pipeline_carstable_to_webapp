# 车型尺码流水线

本项目采用 `input + artifact + public` 模式：

```text
input/                              人工输入，支持 CSV / XLSX / XLSM
configs/
  pipeline.yaml                     流水线配置
  user-size-rules.json              尺码和缩写规则的唯一活动来源
artifact/
  2026-09-01_01_最后的老尺码/       迁移前历史产物，只读保留
  YYYY-MM-DD_NN_pipeline/           每次新运行生成的独立批次
public/                             当前可部署站点
logs/                               运行日志
```

## 运行

把源文件放入 `input/`，然后执行：

```powershell
python run_all.py
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

中间结构化数据只使用 CSV 和 JSON，不生成中间 XLSX。XLSX/XLSM 只作为输入格式读取，并在 `00_input/tables/` 规范化为 CSV。外部压缩器和 HTML 生成器当前仍以 TSV 为接口，流水线只在系统临时目录中做短暂转换，不会把 TSV 写入 artifact。

## 批次恢复执行

查看步骤：

```powershell
python run_all.py --list-steps
```

从现有批次的某一步继续：

```powershell
python run_all.py --artifact 2026-09-17_02_pipeline --from-step build_user_size_json
```

`--from-step` 必须同时指定 `--artifact`，避免把不完整结果误写进新批次。也可以用 `--to-step` 创建新批次并停在指定步骤。

当前七个步骤统一采用“动作 + 产物”命名：

1. `normalize_store_inputs`：把每个店铺输入规范化为 CSV，并生成运行时 JSON。
2. `compress_store_fitment`：生成每个店铺的压缩匹配数据和原子检查结果。
3. `build_user_size_json`：应用尺码及缩写规则，生成紧凑 JSON。
4. `export_store_csv`：按店铺导出 HTML 输入 CSV。
5. `generate_store_html`：生成各店铺尺码表 HTML。
6. `build_public_site`：构建并更新 `public/`。
7. `publish_nas_site`：尝试将完整站点发布到 NAS；NAS 不可用时记录警告，但不影响 `public/` 构建成功。

旧步骤名仍可用于 `--from-step`/`--to-step`，但 `--list-steps` 和新日志只显示上述标准名称。

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
python backup.py create
python backup.py list
python backup.py verify <存档名>
python backup.py restore <存档名> --force
```

清理只移除当前输入和发布结果，历史 artifact 永远保留：

```powershell
python cleanup.py --dry-run
python cleanup.py --force
```

## 配置入口

主要配置在 `configs/pipeline.yaml`：

- `paths.input_dir`：源文件目录。
- `paths.artifact_root`：批次根目录。
- `paths.public_dir`：当前发布目录。
- `paths.nas_publish_dir`：NAS 发布目录。
- `file_rules.input_patterns`：输入格式，默认支持 CSV/XLSX/XLSM。
- `input.store`：由文件名生成店铺名和标签；每个输入文件就是一个店铺。
- `columns`：输入字段别名。
- `steps`：流水线命令和启停状态。

HTML 样式位于 `configs/html-style.yaml`，AI 缩写补全位于 `configs/ai-user-size.yaml`。
