# 配置维护指南

## 多文件输入

`pipeline.yaml` 的 `file_rules.input_patterns` 可以同时发现多个 Excel/CSV 文件。所有文件属于同一次流水线运行，每个文件自动生成一个匹配来源，不再需要手写固定的工作表清单。

```yaml
file_rules:
  input_patterns: ["*.xlsx", "*.xlsm", "*.csv"]

input:
  case_name: combined
  match_source:
    name: "{stem}"
    label: "{stem}尺码匹配表"
    sheet: "{stem}尺码匹配"
    header_row: 1
    columns: MODEL,版本,YEAR,TYPE,CAB,BED,L-MM,W-MM,H-MM,长度余量,SIZE
  csv:
    encoding: utf-8-sig
  header_aliases:
    S8MAKE: MAKE
  required_fields: [品牌, 前台车型, 年份区间, 最终尺码]
```

模板变量中，`{stem}` 是不含扩展名的文件名，`{filename}` 是完整文件名，`{suffix}` 是不带点的扩展名。例如 `ALL.csv` 会生成：

```yaml
- name: ALL
  label: ALL尺码匹配表
  sheet: ALL尺码匹配
  header_row: 1
  columns: MODEL,版本,YEAR,TYPE,CAB,BED,L-MM,W-MM,H-MM,长度余量,SIZE
```

`prepare_inputs` 会把所有输入统一写入 `data/middle/00_input/combined.xlsx`，并在同目录生成 `pipeline.generated.yaml`。后续步骤只读取这份运行时配置，因此 `match_sources` 的 `header_row`、`columns` 等规则仍然会严格传递到发布站点。

CSV 默认自动识别逗号、分号或 Tab 分隔符。Excel 文件如果只有一个工作表会自动选中；如果包含多个工作表，程序会优先匹配生成的 `sheet`、来源名或文件名，也可以在 `input.match_source` 中设置 `source_sheet` 模板明确指定。

`header_aliases` 会在写入合并工作簿前统一已知的表头别名或笔误。`required_fields` 按 `columns` 中的候选列校验每个来源，默认要求品牌、前台车型、年份区间和最终尺码，避免缺列数据进入后续步骤后被静默忽略。

项目保留三份 YAML 配置：

- `pipeline.yaml`：输入工作表、字段映射、目录、命令与步骤开关。
- `html-style.yaml`：HTML 数据列、过滤规则和全部视觉样式。
- `ai-user-size.yaml`：AI 接口、模型、超时和 MODEL/TYPE/CAB 最大长度。

`pipeline.yaml` 的 `input.sheets` 是工作表与店铺数据集的唯一来源。压缩输出目录、合并用户尺码工作簿、TSV 店铺目录和 HTML 店铺目录都由代码动态生成，不需要配置对应路径。

用户尺码规则保存在 `data/rules/user-size-rules.json`，流水线直接生成紧凑的 `data/middle/02_user_size.json`，不再依赖 Excel 公式计算或人工保存。

可选 AI 缩写补全只读取环境变量：`AI_ENRICH=1`、`AI_API_KEY`、`AI_MODEL`，兼容接口可另设 `AI_BASE_URL`。API Key 不写入 YAML；补全结果保存进规则 JSON 的 `ai_cache`，后续直接复用。

全量 `atom_validate` 默认关闭；压缩脚本仍保留每张表自身的 `--check-atom` 检查。
