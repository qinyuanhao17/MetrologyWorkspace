# 教程截图

将 SOP 使用的 PNG、JPEG 等静态图片放在这个文件夹。

例如正文在 `pages/example.md`，图片在 `images/example.png`，正文写：

```markdown
![操作界面](../images/example.png)
```

## 已使用的截图（2026-11-04）

| 文件 | 对应教程 | 内容与数据来源 |
| --- | --- | --- |
| `summarize_ref.png` | Summarize REF | Light 主题的实际解析界面，使用项目测试目录 `Data for Test/for Summary REF/PMISH/SGDEP`：3 个文件、78 条记录、3 个 Wafer ID。 |
| `correlation.png` | Correlation and Trend | Light 主题的实际拟合界面，使用两张逐行对齐的演示表；含 2 个晶圆、每片 6 个 Die，以及 Thickness / CD 两个参数。 |
| `trend.png` | Correlation and Trend | 同一演示数据的实际 Trend 界面；在 Raw Thickness 上叠加 Reference Thickness 和 Raw CD。 |

截图直接由当前版本的 Qt 窗口渲染，不是界面设计稿。演示数据不用于工艺判断。正文用 `<img ... width="680" />` 限制显示宽度，原图保留完整分辨率。

更新截图时应同步核对正文中的按钮名称与计算规则，并使用独立的设置、恢复文件及提醒事项路径，避免改变用户偏好或最近打开的文件列表。
