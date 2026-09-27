# 数据查询静态网站

这是一个 GitHub Pages 静态网站。网页访问时读取已经整理好的静态文件，不会在浏览器里打开 Excel。

## 目录结构

```text
assets/
  fonts/                         字体
  app/
    viewer.css                   前端样式
    viewer.js                    尺码表浏览和车型配对逻辑
    size-ref.js                  尺码参考页逻辑

config/
  size-chart-view.yaml           Excel 工作表和查询字段配置

data/
  source/
    tables/                      表格来源
      车型数据尺码.xlsx
    html/                        HTML 来源
      ALL/
      HNT/
      TM/
      img_logos/
  generated/                     从 Excel 导出的网页查询 JSON
    size-match.json               数据源与品牌分片清单（不再内嵌全部记录）
    size-match-*.json             按数据源和品牌拆分、由页面按需加载的记录
    size-ref.json

pages/
  level-1/                       一级网页源码
    index.html
    size-chart.html
    size-match.html
    size-charts.html
    size-ref.html
  tools/                         本地辅助预览页

tools/
  export_xlsx_sources.py         从 Excel 导出 JSON
  build_site.py                  整理 GitHub Pages 发布目录
```

根目录下也保留了一份一级网页，方便本地直接打开或预览；发布时以 `pages/level-1/` 为准。

## 数据来源

- 表格来源（数据生成环境）：`data/source/tables/车型数据尺码.xlsx`；该 Excel 不保存在当前发布仓库中
- HTML 来源 / 二级网页：`data/source/html/<店铺>/<类型>/output_*.html`
- 网页查询数据：`data/generated/size-match.json`、同目录的 `size-match-*.json` 和 `data/generated/size-ref.json`

`size-match` 的长、宽、高和长度余量以整数毫米导出。导出器优先读取 `L-MM / W-MM / H-MM`，也能将旧的 IN/CM 列换算为 MM。页面可将标准毫米值切换为 MM/CM/IN 整数显示；尺码配色在 `config/size-chart-view.yaml` 的 `size_colors` 中维护。

`size-match.json` 只保存数据源和品牌清单；浏览器先读取轻量清单，选择品牌后才加载该品牌在 ALL/TM/HNT 等来源中的记录。记录分片文件名包含内容哈希，可以安全复用浏览器缓存。最终尺码与自动尺码一致、最终长度余量为空时，导出器会使用自动长度余量安全回填。

`config/size-chart-view.yaml` 控制 Excel 读取路径、工作表名、字段和 JSON 输出路径。

## 日常维护

1. 更新车型/尺码查询数据：在有源 Excel 的数据生成环境中运行 `tools/export_xlsx_sources.py`，并提交更新后的 `data/generated/size-match.json`、`size-match-*.json` 和 `size-ref.json`。
2. 更新尺码表页面：替换 `data/source/html/` 下对应店铺和类型的 HTML/CSS/图片。
3. 如果新增或删除 `output_*.html`，运行 `tools/build_site.py` 时会自动扫描 `data/source/html/` 并更新发布站点里的目录列表。
4. 如果改了一级网页，必要时同步根目录同名 HTML，方便本地直接预览。
5. 运行 `python tools/validate_generated_data.py`，确认配置字段、分源记录数和尺码参考字段一致。

## 本地预览

在项目根目录运行：

```powershell
python tools/build_site.py
python -m http.server 8765 --bind 127.0.0.1
```

如果需要从源 Excel 重新生成查询数据，请先将工作簿放到配置指定的位置，再运行：

```powershell
python -m pip install openpyxl
python tools/export_xlsx_sources.py
```

然后打开：

```text
http://127.0.0.1:8765/_site/
```

如果只想快速查看根目录页面，也可以打开：

```text
http://127.0.0.1:8765/
```

## 发布流程

正式站点统一由 `pipeline_carstable_to_webapp` 发布：

```text
https://licwan62.github.io/pipeline_carstable_to_webapp/
```

本仓库不再单独发布一份可能过期的数据站。GitHub Actions 的 `.github/workflows/static.yml` 只发布兼容跳转页：

1. 验证 `pages/redirect/index.html` 和 `404.html`
2. 将旧站首页和旧页面地址跳转到正式 pipeline 站点

Excel 不保存在当前仓库中。这里继续维护前端骨架、导出器和本地预览数据，pipeline 构建时会复用这些文件并执行完整数据契约校验。
