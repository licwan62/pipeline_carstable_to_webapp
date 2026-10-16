# 车型尺码流水线（网站发布）

目录约定：

| 目录 | 内容 |
| --- | --- |
| `tools/` | 全部 Python 脚本，入口是 `tools/run_all.py`，另有 `backup.py`、`cleanup.py` 和各步骤工具 |
| `docs/` | 全部 Markdown 文档：[流水线说明](docs/pipeline.md)、[配置说明](docs/configs.md) |
| `configs/` | 流水线、样式和尺码规则配置 |
| `site_overrides/` | 项目自有页面和前端脚本的权威源码，构建时叠加到站点（不再从 `public/` 回读） |
| `input/` | 旧的人工输入（默认产线输入改为 all_cars_data 的 A0/A1 发布物，见 [流水线说明](docs/pipeline.md)） |
| `work/` | 每次运行的中间工作目录 `work/<批次>/`（不纳入 git；成功后删除，失败保留诊断） |
| `artifact/` | 每次运行的不可变批次清单与去重后的站点字节（v3，见 [流水线说明](docs/pipeline.md)）；`tools/archive_artifacts.py` 归档旧批次 |
| `public/` | 当前可部署站点（构建并完整校验成功后才切换；GitHub Pages 部署已提交的 public，因此仍纳入 git） |
| `logs/`、`bak/`、`.bak/` | 运行日志、`tools/backup.py` 备份与早期备份，只在本地保留，不纳入 git |
| `tests/` | 自动测试（`conftest.py` 已把 `tools/` 加入导入路径） |

```powershell
python tools/run_all.py
python -m pytest tests
python tools/acceptance_size_match.py   # 尺码配对页验收（需求见 docs/size-match-acceptance.md）
```
