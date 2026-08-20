# 配置维护指南

项目保留三份 YAML 配置：

- `pipeline.yaml`：输入工作表、字段映射、目录、命令与步骤开关。
- `html-style.yaml`：HTML 数据列、过滤规则和全部视觉样式。
- `ai-user-size.yaml`：AI 接口、模型、超时和 MODEL/TYPE/CAB 最大长度。

`pipeline.yaml` 的 `input.sheets` 是工作表与店铺数据集的唯一来源。压缩输出目录、合并用户尺码工作簿、TSV 店铺目录和 HTML 店铺目录都由代码动态生成，不需要配置对应路径。

用户尺码规则保存在 `data/rules/user-size-rules.json`，流水线直接生成紧凑的 `data/middle/02_user_size.json`，不再依赖 Excel 公式计算或人工保存。

可选 AI 缩写补全只读取环境变量：`AI_ENRICH=1`、`AI_API_KEY`、`AI_MODEL`，兼容接口可另设 `AI_BASE_URL`。API Key 不写入 YAML；补全结果保存进规则 JSON 的 `ai_cache`，后续直接复用。

全量 `atom_validate` 默认关闭；压缩脚本仍保留每张表自身的 `--check-atom` 检查。
