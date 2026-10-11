# 第三项：Correlation / Trend 绘图样式统一

本轮只处理用户指定的绘图样式及最小相关测试。不做性能优化、全量测试或发布。

## 可观察行为

- Correlation 以 Workbook Match 图为准：蓝色圆点 `#4f8bd6`、橙色实线拟合 `#e09f3e`。
  独立数据、Ref / Raw 来源和静态导出保持一致；来源仍由标题及文字图例明确区分。
- Trend 的原始来源和比较曲线统一为圆点、实线，系列只用颜色区分，保留文字图例。
  单来源蓝色、5 像素圆点、2.2 线宽与 Workbook 基准一致。
- 分组、All parameter 和单 wafer Trend 的另一套方点/虚线也已统一。
  分类分界线不是数据曲线，其原有虚线语义保留。
- 不改变源字符串、行映射、选择、数值拟合、轴方向、缺失值断线或导出数据。
  X/Y 切换后继续使用统一样式。

## 方法与最小验证

沿用已确认的绘图及导出验证入口，先写失败用例再修改。
旧实现分别被蓝点颜色、比较曲线方点、分组点大小等断言捕获；修改后转为通过。
复用 `appearance.py` 的共享样式常量，未增加渲染框架或依赖。

采用 tdd 的先失败后通过、scientific-visualization / matplotlib 的源值保留及屏幕/导出双重检查，
并按 ponytail / codebase-design 保持改动小、共享样式不引入额外接口。
接受条件对应 `tests.test_analysis_plot_style` 的四个独立可执行用例，
分组行为对应 `tests.test_matching_window.MatchingWindowTests.test_trend_plots_share_the_raw_column_title_and_off_frame_legend`。
这些是用户示例的验收检查，不是新增 Cucumber 运行时。

最终最小回归 **13 项通过，2.002 秒**，包括：

- 新增四项屏幕/导出样式、数值及来源保留检查；
- 来源颜色、比较标签、部分来源行对齐；
- X/Y 独立切换及正确方向重新拟合；
- Workbook 标题、图例、分组/单 wafer 样式；
- 参数筛选复用原图和完整曲线值。

完整命令与输出记录于 `.cache/analysis-plot-style/focused-tests.txt`。
首次分组用例另遇到沙盒默认 Temp 清理权限错误，改用 workspace scratch TEMP 后重跑；
未修改产品代码或放宽测试断言来绕过权限问题。
设置、recovery、Matplotlib 缓存及临时测试文档均隔离到 scratch。
用户设置文件的哈希在本轮前后相同。

## 效果检查

截图来自实际 Qt 绘图控件，使用八条合成示例数据，不代表桌面 NOVA 的性能测量。
已目视核对圆点、实线、颜色、标题和坐标标签。

- `.cache/analysis-plot-style/correlation-style.png`
- `.cache/analysis-plot-style/trend-style.png`

本地修改与最小验证完成；未运行全量、延迟检查，未提交或推送。
