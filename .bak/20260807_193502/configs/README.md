# 配置维护指南

| 想修改的内容 | 修改文件 |
|---|---|
| 相邻项目路径、工作区、模板、步骤开关 | `pipeline.yaml` |
| Excel 工作表名或输入列名 | `compress-field-profile.yaml` |
| HTML 使用哪些数据列、过滤哪些记录 | `html-user-size-preference.yaml` |
| 页面尺寸、字体、颜色、列宽、Logo、尺码徽章 | `html-style.yaml` |
| 直接用压缩尺码 `BACKSIZE` 生成 HTML | `html-direct-from-compress-preference.yaml` |
| 脚本命令、中间目录结构、产物检查 | `pipeline-steps.yaml`（高级） |

## 最常用操作

关闭某一步：

```yaml
# pipeline.yaml
steps:
  publish:
    enabled: false
```

修改 HTML 页面背景：

```yaml
# html-style.yaml
page_background: "#ffffff"
```

修改 Excel 输入列的候选名称：

```yaml
# compress-field-profile.yaml
columns:
  最终尺码:
    - 确认尺码
    - 自动尺码
```

## 配置继承

- `pipeline.yaml` 用 `include` 载入 `pipeline-steps.yaml`，主文件中的同名值优先。
- 两份 HTML 数据配置用 `extends` 继承 `html-style.yaml`，数据字段和视觉样式互不重复。
- YAML 中 `#` 表示注释，因此十六进制颜色必须加引号。
