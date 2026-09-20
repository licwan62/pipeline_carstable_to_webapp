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

`normalize_store_inputs` 会把每个店铺文件规范化为批次内的 `00_input/tables/*.csv`，并生成 `00_input/pipeline.generated.json`。后续步骤只读取这些 CSV 和 JSON，因此 XLSX 不会成为中间产物。

步骤名统一为：`normalize_store_inputs`、`compress_store_fitment`、`build_user_size_json`、`export_store_csv`、`generate_store_html`、`build_public_site`。

`input.store` 支持 `{stem}`、`{filename}` 和 `{suffix}`。其中 `{stem}` 默认就是店铺名，例如 `07-HNT.csv` 对应店铺 `07-HNT`。生成的 `header_row`、`columns` 等约束会写入运行时 JSON，并传递到发布站点。

尺码、分类和缩写规则统一维护在：

```text
configs/user-size-rules.json
```

旧的 Excel template 链路已移除。`html-style.yaml` 控制 HTML 外观，`ai-user-size.yaml` 控制可选的 AI 缩写补全。
