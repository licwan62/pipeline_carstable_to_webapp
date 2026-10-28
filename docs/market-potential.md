# 尺码配对页市场潜力

2026-10-28：市场潜力算法及积加、竞品来源CSV从 A0 迁入02销量评估的 `data/商业潜力调整/`。算法与参数保留，02内部输出 `市场潜力.csv`，A0 US和三个店铺全量表承接“市场潜力”“销量潜力调整”。来源维护与完整公式见上游该目录的 README。

A1按原有年份原子及同尺码命中关系汇总市场潜力；重复导出的同键原子先均分该键潜力，再向匹配记录分配，避免重复计入。6位小数使用最大余数法分配尾差。US及HNT/TM/TM_拆分各自的全量、压缩潜力总量均为396126.151697分；原子销量接口、A0原字段和A1原字段及行序保持不变。

网页全量、压缩表均展示潜力，提供数值排序、范围筛选和合计，最多显示6位小数。可视化共用柱状面板默认市场潜力，可切换年度销量；潜力每条尺寸记录一柱，年份窗口只选择相交记录，不折算或重复计入分数。提示及锁定详情展示基础、调整和DIMENSION-ID。年度销量保留原年轴、缺失值及加载重试。

图表占据整行，标题和筛选在上，配置图例在下且可折叠。EU/RU显示无同口径潜力数据。前端权威源码为 `site_overrides/`，构建生成 `public/`，资源版本20261028-1。

验证命令：

```powershell
python -m pytest tests -q
node --test tests/js/*.test.cjs
python tools/acceptance_size_match.py
node tests/acceptance/market_potential_browser.cjs --url http://127.0.0.1:8766/ --out reports/market-potential/browser.json
```

数据核对见 [data-validation.json](../reports/market-potential/data-validation.json)，浏览器结果见 [browser.json](../reports/market-potential/browser.json)，截图见 [桌面](../reports/market-potential/desktop.png) 与 [窄屏](../reports/market-potential/narrow.png)。构建批次2026-10-28_02_pipeline固定02 20261028_02、A0 20261028_03、A1 20261028_04。

上游原有尺码映射表头位于末尾，已恢复到首行并按已发布字段顺序排列，映射关系不变。全仓结构与追溯仍报告原有D2根节点登记缺失及D1规则未发布；本次02/A0/A1追溯均为OK，未修改D2现有工作。

部署使用现有 NAS 发布方登记流程和 main 分支 GitHub Pages 工作流。回退时重新部署之前提交中的完整 public；NAS只操作本发布方登记文件，不影响其他项目页面。
