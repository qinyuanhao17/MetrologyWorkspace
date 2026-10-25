# Wafer Map hover, export styling and map throughput

用户报告（2026-10-24，基于 v4.2.0 之后的现有代码）：

- Wafer Map / Radius Plot 的 hover 不再显示 Die 与数值。
- 导出 Excel 与 Matplotlib 时，Wafer Map 与 Radius 的图高不一致。
- Trend / Bias 的线和点偏细；勾选 Bias limit 后导出图里没有红色限值线。
- Dynamic 软件与导出图的标题要改成 `N cycles dynamic of <parameter> (nm)`。
- 用 `matching-analysis_nova_multi_param.wkb` 画 Wafer Map 仍慢，感觉和 Matplotlib 一样。

## 实现

### Hover（Die + 数值）

- `WaferPanel`（`metrology_app/wafer_graphics.py`）恢复 hover：缓存每个测量点的像素位置，
  取光标 12 px 内最近点，提示 `Wafer 标签 · Die <Die Seq> · <metric> = <值> · X/Y`，
  同时更新页面状态栏；离开时隐藏。
- `RadiusPanel`（`metrology_app/radius_graphics.py`）同样恢复 hover：
  `Wafer 标签 · Die <Die Seq> · <metric> = <值> · Signed radius = <R> <unit>`；
  `RadiusPage.draw_plot()` 现在把同一行 Raw Data 的 Die Seq 带入每个 radius 数据源，
  无效坐标/值使用同一掩码。
- 两个静态 pyqtgraph 面板都重新接受 hover 事件；图片子项仍不拦截事件。
- 首版 hover 在真实鼠标移动时不显示的根因：`QToolTip.showText()` 的 widget 参数收到的是
  `QGraphicsObject`（不是 `QWidget`），且当前 Qt 的 `screenPos()` 是 `QPoint`；
  现在先更新状态栏，再以场景所属 view 的 viewport 作为 tooltip 父控件。
  新增 `QTest.mouseMove` 的真实事件回归（不只调用 `hover_text()`）。

### 导出高度、粗细与 Bias limit

- `RadiusPage` 与 `RadiusGrid` 的每行高度从 370 px 改为 420 px，与 Wafer Map 一致；
  Excel 图片比例 `picture_ratio()` 对 `Wafer Map` 和 `Radius` 使用同一
  `rows × WAFER_MAP_CELL_HEIGHT_CM`，命名子窗口导出时记录 Radius 的 `(rows, columns)`。
- Trend / Bias 线宽与点大小：
  - 软件：Trend 2.2 → 3.0，点 5 → 6；Bias / Bias % 1.3 → **3.0**，点 5 → 6。
  - Matplotlib 导出：marker 4 → 6，line 1.8 → 2.6（`parameter_figure`）；
    分析导出图（Correlation/Trend）marker 4 → 5.5，line 1.8 → 2.4。
- Bias limit：`parameter_figure(panel="Bias")` 在 `show_bias_limit=True` 时绘制
  `±limit` 红色（#DC2626）虚线，并把限值纳入 Y 轴范围；Bias % 图不画 nm 限值。
  原生 Excel Bias 图追加两条 `numLit` 常量系列（±limit，红色虚线），不依赖新单元格。

### Dynamic 标题

- `DynamicPage` 每个参数的 3σ 图标题：`<N> Cycles Dynamic of <parameter> (nm)`；
- 导出（原生图表与 Matplotlib 图片）：参数图同样使用该标题；
  合并图的标题为 `<N> Cycles Dynamic of <p1>, <p2> (nm)`。

### Wafer Map 吞吐

实测 `matching-analysis_nova_multi_param.wkb`，选择 120 张图（12 wafer × 10 参数），
离屏 Qt：

| 阶段 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 总绘制 | 4.97 s | 2.82 s |
| `prepare_array`（插值） | 3.48 s | 1.32 s |
| `set_result`（面板构建） | 0.67 s | 0.68 s |
| 首帧 `paint` | 0.75 s | 0.75 s |

原因与修复：渲染器已经是 pyqtgraph/QPainter，但耗时约 70% 在 `prepare_array` 的
逐 wafer RBF 插值；每个 wafer 的 10 个参数已经共享一次求解，但 12 个 wafer 是串行的。
`array_plot.prepare_array()` 现在用 `ThreadPoolExecutor` 并行各 wafer 的独立求解
（最多 8 线程；单 wafer 仍单线程），**数值、点序、场景顺序、取消与错误语义不变**。
SciPy 的 RBF 求值释放 GIL，实测 12 个 batch：串行 2.76 s、8 线程 0.56 s。

## 验证

- 新增 `tests/test_export_hover_fixes.py`：Map/Radius hover 文本（Die + 值 + X/Y 或半径）、
  Bias 导出图红线和线宽/点大小、Map/Radius 图片同高、Dynamic 标题、原生 Bias 图限值系列。
- 更新 `tests/test_radius.py`（行高 420）与 `tests/test_dynamic.py`（新标题）。
- 相关回归：Array/Radius/Dynamic/Export 样式 **72 项通过**；
  趋势标题 + 新导出用例 + Radius/Dynamic/分组 **78 项通过**；
  主窗口、分组、性能与图注套件 **227 项中 226 项通过**，唯一失败是旧的
  Trend 点大小断言（5 → 6、2.2 → 3.0），更新后相关 78 项重新通过。
- `main.py --self-test` 在当前工作区失败，但在 **v4.2.0 HEAD 的独立副本上以相同方式失败**
  （conda 环境缺 `cv2`，以及 `shell.py` 关闭时向已删除的 activity 列表写入）；
  属既有环境/代码问题，与本轮修改无关。

## 边界

- 只增加 hover 与导出样式；插值算法、分辨率、色标、采样、参与行与 WKB 格式未改。
- 并行只发生在相互独立的 wafer 之间；任一 batch 的异常仍只标记该 batch 的场景。
- 100+ 张图的页面耗时仍包含面板构建与首帧绘制（约 1.4 s），与地图数量线性相关。

## 追加：取消 Dynamic Trend「All Dies」

用户看过 All Dies（多 Y 轴后仍密集）反馈"看不清，取消"；随后又确认
"Single Die" 这个仅剩一项的选择框也不需要。决定：

- `DynamicTrendPage` **移除整个视图模式下拉框**（`view_mode`）；`All Dies` 选项与
  按 Die 分轴的代码全部移除。每个参数仍显示一个选中的 Die（面板里的 Die 下拉框可切换），
  可用 `Add Compare` 叠加其他参数
  （比较参数各用自己的右轴），并可切换该面板的 Die。
- 导出图恢复为每面板一条左轴（参数名）+ 比较参数右轴；标题为
  `<parameter> · Die <n>`，不再按所有 Die 展开。
- 旧 WKB 里保存的 `view_mode` 控件值在恢复时被忽略（页面已没有该控件），
  不会重建 All Dies。
- 回归：`tests/test_dynamic.py`（无视图模式下拉框、单轴导出）、
  `tests/test_dynamic_compare_export.py`、`tests/test_requested_plot_controls.py`
  与 Export/Hover 套件 **46 项通过**。

## 追加：统一 Trend / Bias 样式与内容紧贴的 Group / Wafer 导出

- 软件内所有 Trend、Bias、Bias % 数据曲线统一为 `width=2.5`、实心圆
  `symbolSize=6`；不按屏幕 DPI 换算。
- Excel 原生图和 Matplotlib 图片的数据曲线统一为 `2.5 pt` 线宽和 `6 pt`
  圆点；Match 散点、Correlation 拟合、Bias limit 和零基准线保持辅助样式。
- Match Original 保留 25 cm Die Seq 基线。Match Group 不再强制与 Original
  同宽，也不设置最大宽度。
- `Match Group` 始终只显示 Group：最小 Group 紧贴完整标签，其他 Group
  按有限测量点数量成比例增长，从而为整张长图确定紧贴总宽度。
- Group 名称在 x 轴使用单行文本。Native 与 Matplotlib 的所有 identity
  caption 都在真实区间中心落位；需要避让时只做最小位移，不再绘制拉线。
  文字框不换行且透明，分界线不会在 caption 后方断开。
- WKB 有 Show Wafer Group 时额外生成 `Match Group show Wafer`。未 Show Wafer
  的 Group 沿用 group-only 宽度；Show Wafer 的 Group 独立按完整 Wafer / LOT /
  PAD 标签和完整分界线确定宽度。WO 阶段因 Excel 31 字符限制省略名称中的
  一个空格，使用 `Match Group show Wafer(WO Card)`。
- Native 长图使用 3 cm 左边距和 0.7 cm 右边距；Matplotlib 使用同一物理边距，
  身份 caption、Wafer/Group 分界线与绘图区同步对齐。
- Match Wafer 对全部 Wafer 应用同一紧贴规则，所有当前启用的
  Wafer / LOT / PAD 行均保留，不省略，也不再按 45 cm 分页。Trend / Bias
  保持一张完整长图，标题不附加 `Page x/y`；Die Seq 刻度在每个可见
  Wafer span 内按可用宽度取样，不再用全表固定步长跨过整片 Wafer。
- Excel 原生图和 Matplotlib 图片共享每个 Group/Wafer 面板计算出的物理宽度。
- Group/Wafer 的 Native 长图使用 `_Plot data` 中的 cell-bound numeric x，
  与分析数据、remap 后的 caption 和分界线共用同一坐标；隐藏自动数值刻度，
  并由 chart userShapes 重新绘制稀疏、可随单元格更新的 Die Seq 刻度和标题，
  避免 Excel 将非等宽 Group 重新按等距 category 绘制。Trend、Bias 和 Bias %
  使用绑定单元格 X/Y 的数值 XY series，而不是带数值 category 的 LineChart；
  因此拉长 Show Wafer Group 会同时拉长曲线数据，且 Excel 的源数据选框仍可拖动。
- 每个单独的 `Match <Group>` 始终展示该 Group 的全部 Wafer，作为唯一的 Group
  Wafer 明细视图；`Show wafer` 不再改变单 Group 页面，只决定组合
  `Match Group show Wafer` 是否采用该明细宽度。组合页仍按 Group span 拼接，
  因而未勾选 Group 保持 `Match Group` 宽度，勾选 Group 与该 Group 单独页使用
  同一 Wafer 宽度和标签中心。
- FullMap 的 Wafer Map 与 Radius 取两者可见行数的最大值统一定高，
  保存后的图片高度一致。
- Match 页的 Match、Trend、Bias 图改为绝对物理定位：横向图间距固定 1 cm，
  纵向参数行间距固定 5 mm，避免 Excel 行高/列宽导致一边过疏、一边过密。
- Match 放在左侧方形面板；Trend、Bias、Bias % 在右侧顺序纵向堆叠，
  下一参数从完整面板组下方开始。
- Trend 和 Bias 的 Y 轴在数据范围之外保留约 3% 的 marker 半径余量；实测
  AA Trend 为 13.7–24.3，Bias 为 -0.318–0.318，边界圆点不再被图框裁切。
- 可执行覆盖：`test_export_hover_fixes`、`test_excel_report_layout`、
  `test_export_opening_layout`、`test_analysis_plot_style`、`test_dynamic`、
  `test_dynamic_compare_export`、`test_matching_window`、`test_excel_export`。
