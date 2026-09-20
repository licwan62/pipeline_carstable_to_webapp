# 车型尺码流水线（网站发布）

目录约定：

| 目录 | 内容 |
| --- | --- |
| `tools/` | 全部 Python 脚本，入口是 `tools/run_all.py`，另有 `backup.py`、`cleanup.py` 和各步骤工具 |
| `docs/` | 全部 Markdown 文档：[流水线说明](docs/pipeline.md)、[配置说明](docs/configs.md) |
| `configs/` | 流水线、样式和尺码规则配置 |
| `site_overrides/` | 站点构建后叠加到 `public/` 的项目自有页面和脚本 |
| `input/` | 人工输入（按日期分目录，含 `input-provenance.json`） |
| `artifact/` | 每次运行的不可变批次 |
| `public/` | 当前可部署站点 |
| `tests/` | 自动测试（`conftest.py` 已把 `tools/` 加入导入路径） |

```powershell
python tools/run_all.py
python -m pytest tests
```
