# 配置说明

`pipeline.yaml` 是流水线入口配置。输入目录、artifact 批次根目录和发布目录分别为：

```yaml
paths:
  input_dir: input
  artifact_root: artifact
  public_dir: public
```

输入支持 CSV、XLSX 和 XLSM：

```yaml
file_rules:
  input_patterns: ["*.xlsx", "*.xlsm", "*.csv"]
```

默认 `input.source: all_cars_data`：`import_a2_compressed` 读取 `paths.a1_output_dir` / `paths.a2_output_dir`（all_cars_data 的 A1/A2 output），按 A2 产线生成 `00_input/tables/*.csv`、`01_compressed_fitment/` 与 `00_input/pipeline.generated.json`。旧的手工输入模式（`input/` + 本仓库压缩）需去掉 `input.source`，并在 `steps` 中恢复 `normalize_store_inputs`、`compress_store_fitment` 两步（配置见 git 历史）。

步骤名统一为：`import_a2_compressed`、`build_user_size_json`、`export_store_csv`、`generate_store_html`、`build_public_site`、`publish_nas_site`。

`input.store` 支持 `{stem}`、`{filename}` 和 `{suffix}`。其中 `{stem}` 默认就是店铺名，例如 `07-HNT.csv` 对应店铺 `07-HNT`。生成的 `header_row`、`columns` 等约束会写入运行时 JSON，并传递到发布站点。

尺码、分类和缩写规则统一维护在：

```text
configs/user-size-rules.json
```

旧的 Excel template 链路已移除。`html-style.yaml` 控制 HTML 外观，`ai-user-size.yaml` 控制可选的 AI 缩写补全。
