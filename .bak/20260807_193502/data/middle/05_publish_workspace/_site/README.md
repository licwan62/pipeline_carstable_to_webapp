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
    size-match.json
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

- 表格来源：`data/source/tables/车型数据尺码.xlsx`
- HTML 来源 / 二级网页：`data/source/html/<店铺>/<类型>/output_*.html`
- 网页查询数据：`data/generated/size-match.json` 和 `data/generated/size-ref.json`

`config/size-chart-view.yaml` 控制 Excel 读取路径、工作表名、字段和 JSON 输出路径。

## 日常维护

1. 更新车型/尺码查询数据：替换 `data/source/tables/车型数据尺码.xlsx`。
2. 更新尺码表页面：替换 `data/source/html/` 下对应店铺和类型的 HTML/CSS/图片。
3. 如果新增或删除 `output_*.html`，运行 `tools/build_site.py` 时会自动扫描 `data/source/html/` 并更新发布站点里的目录列表。
4. 如果改了一级网页，必要时同步根目录同名 HTML，方便本地直接预览。
5. 推送到 `main` 后，GitHub Actions 会自动导出 JSON 并发布。

## 本地预览

在项目根目录运行：

```powershell
python -m pip install openpyxl
python tools/export_xlsx_sources.py
python tools/build_site.py
python -m http.server 8765 --bind 127.0.0.1
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

GitHub Actions 的 `.github/workflows/static.yml` 会执行：

1. 安装 Python 和 `openpyxl`
2. 读取 `data/source/tables/车型数据尺码.xlsx`
3. 导出 `data/generated/size-match.json` 和 `data/generated/size-ref.json`
4. 运行 `tools/build_site.py`
5. 将 `_site/` 发布到 GitHub Pages

线上不会发布 `data/source/tables/` 里的 Excel，只发布前端需要读取的 JSON 和 HTML 来源。
