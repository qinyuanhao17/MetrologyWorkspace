# 任务：Trend（Correlation and Trend）面板"叠加对比"功能

> 这是给编码代理（Codex）的实现指令。请先写测试再写实现，不要扩大范围。

## 实现审查（2026-10-01）

整体交互与范围合理，已按以下必要修正实现：

- `overlay_spec` 必须接收两组数值，否则无法判断“量级差 > 10×”；实际接口增加了可选的
  `primary_values` / `secondary_values`，不传时仍可只做单位轴判定。
- Matplotlib 不能先用 `finite` 删除 NaN 再画线，否则会跨缺失点连线；实际实现直接把含 NaN
  的数组交给 Matplotlib，让线段在缺失处断开。
- 项目持久化使用 `settings.py` 的 YAML，而不是 Qt `QSettings`；`trend_overlay` 写入应用设置，
  仍不进入 WKB schema。
- Correlation and Trend 已按后续产品要求改为 Ref Data / Raw Data 两个数据页，且 Trend 默认按
  Reference 后 Raw Data 分面板排列；叠加功能在每个来源的参数面板上保持相同语义。

## 0. 背景与目标

`metrology_app` 是 Python 3.10+ / PyQt6 的计量数据应用。"Correlation and Trend" 工作区的
`3. Trend` 页（`metrology_app/sequence_page.py` 的 `SequencePage`）当前是**一个参数一张图**。

用户的需求：

- **默认行为必须保持"一个参数一张图"**，这个功能不是每次都用的。
- 偶尔需要把**两个**参数拉到同一张图里，对比它们的趋势是否一致或接近。
- 合并必须是**用户显式发起、可随时解除**的一次性动作。

已确认的产品决策：

1. **发起方式**：在 Trend 面板上**右键 → "叠加对比…"**，弹窗列出当前已勾选的其他参数，
   选中后确定即合并；再次右键 → **"解除对比"** 还原。
2. **Y 轴判定**：
   - 两个参数**单位相同** → 共用一根左轴（不做"量级相近"判断，同单位即同轴）。
   - 单位**不同** → 自动增加**右侧第二根 Y 轴**，该轴的刻度与轴标签使用被叠参数的颜色。
   - 单位**无法确定** → 按"不同单位"处理，走第二根 Y 轴，并在图例标注 `(unit?)`。
   - **量级差 > 10× 且单位不同** → 同上，并在状态栏提示"已使用第二根 Y 轴，交叉点无物理含义"。
3. **渲染约定**：颜色 = 参数，线型 = 数据来源（`Reference` 实线 / `Raw Data` 虚线）。
4. X 轴、`W01/W02/W03` 的 wafer 名称轴、分隔虚线**完全不变**。
5. 面板标题由 `DP` 变成 `DP + EW（对比）`，并在标题区提供一个 `[解除对比]` 小按钮。
6. 对比状态是**一次性、可解除**的界面偏好：记入 `QSettings`（与 `font_size` / `resolution` 同级），
   **不修改 `.wkb` schema**。下一次 `Draw selected` 时若两个参数仍被勾选，对比自动恢复；否则静默丢弃。
7. 只支持**第二个参数**（两根 Y 轴上限）。第三个参数被选择时拒绝并给出明确提示。
8. 被叠参数的曲线范围：**与发起面板使用同一批测量集（wafer / 测量集 key）**，保证两条曲线严格对齐。

## 1. 硬约束（违反即失败）

- **默认必须是分面板**。`tests/test_correlation.py:117` 断言
  `len(window.sequence_page.plot_widgets) == 2`，默认路径下必须继续通过。
- **禁止修改 `.wkb` SQLite schema**。不得给 `ParameterMapping`
  （`metrology_app/matching/analysis.py:124`）新增 `unit` 字段，不得改 schema 8 的表结构。
- **禁止静默推断物理单位**。无法确定单位时宁可用第二根 Y 轴，也不要猜。
- **不得改变现有导出语义**：`Export PNG` / `Copy PNG` / `Ctrl+C` 的输出尺寸上限
  （`MAX_EXPORT_PIXELS` / `MAX_COPY_PIXELS`）与 DPI 上限提示逻辑保持不变。
- **不得改动 `2. Correlation` 页**（`metrology_app/correlation_page.py`）与
  `metrology_app/matching/` 下的匹配计算逻辑。
- 保留源测量字符串与行映射语义，不做任何数据清洗或重采样。

## 2. 关键文件与现状（已核实）

| 文件 | 关键位置 | 说明 |
| --- | --- | --- |
| `metrology_app/sequence_page.py` | 类 `SequencePage`：`__init__:93`、`set_input:211`、`invalidate:227`、`_sequence_groups:263`、`draw_plot:302`、`build_export_figure:371`、`clear_interactive:443`、`render_interactive:459`、`reset_views:552`、`relayout:566`、`export_png:595`、`copy_png:617` | 主要改动对象 |
| 同上 | `LINE_COLOR:38`、`MAX_SEQUENCE_PLOTS:36`、`HOME_PADDING:37`、`BOUNDARY_COLOR:39` | 现有常量 |
| `metrology_app/plotting/grid.py` | `PlotPanel:10`（`heading` + `plot_widget`） | 标题区与解绑按钮的挂载点 |
| `metrology_app/plotting/interactive.py` | `_PlotViewBox:9`（重写 `autoRange`、用 `setLimits` 锁 X）、`InteractivePlotWidget:37`（`wheelEvent:55`、`_frame_axes:80`） | 第二个 ViewBox 必须复用此类的 X 锁定语义 |
| `metrology_app/correlation_window.py` | `CorrelationWindow:51`、`set_sources:80`、`update_plan:117`、`_source_frame:25` | 列名在此处被重命名为 `mapping.name`，单位信息在此丢失 |
| `metrology_app/window.py` | `update_plan:521`（构造 `selection`） | `selection` 结构来源 |
| `metrology_app/dynamic_page.py` | `SERIES_COLOURS:25`、`_add_comparison_plot:329` | 可直接复用的调色板与多序列图例写法 |
| `tests/test_correlation.py` | 模块级 `APP = QApplication(...)`:26；`:117`、`:846` 为会被影响的断言 | 测试基座 |

`selection` 字典结构（`window.py:527`）：
`{"wafers": [...], "metrics": [...], "wafer_column": str, "groups": {key: rows}, "labels": {key: label}}`，
`CorrelationWindow.update_plan:117` 会额外注入 `selection["sources"]`（Reference / Raw Data 两个条目）。
`SequencePage` 上用 `self.selection.get("sources")` 判断是否处于 WKB 双来源模式。

`SequencePage` 的现有内部状态：`self.metrics`（参数名列表）、`self.groups`、`self.view_groups`、
`self.cells`（`{(测量集 key, 参数名)}` 集合）、`self.x_range`、`self.plot_widgets`、
`self.panel_hosts`、`self.home_views`、`self.wafer_ticks`、`self.base_size`、`self.panel_pixels`。

## 3. 实现顺序

### 步骤 1 — 新建纯逻辑模块 `metrology_app/trend.py`（先写测试）

不依赖 Qt / pyqtgraph / matplotlib，便于单元测试。建议 API：

```python
UNIT_SUFFIX = re.compile(r"[\[(]\s*([^\]()]+?)\s*[\])]\s*$")

def parse_unit(column_name):
    """从列名尾部解析单位：'DP [nm]' -> 'nm'，'EW (V)' -> 'V'，无则 None。"""

def overlay_spec(primary, secondary):
    """决定叠加方式。

    返回 {"kind": "shared" | "second-axis",
          "unit": str | None, "secondary_unit": str | None,
          "magnitude_warning": bool}
    规则：单位都存在且相同 -> "shared"；否则 -> "second-axis"。
    magnitude_warning 在量级差 > 10 且单位不同时为 True。
    """

def overlay_series(frame, groups, metric, keys):
    """按给定测量集 key 取某参数的 (x, y) 序列，NaN 保留、不插值、不补线。"""
```

要求：

- `parse_unit` 保持大小写原样，仅去首尾空白；解析不到返回 `None`，**不得猜测单位**。
- 量级差用各序列有限值的量级（如 `|median|` 或 `max|value|`）比值判断，除零要安全。
- `overlay_series` 必须**逐测量集**返回，便于在图上按测量集边界断开/标注。

### 步骤 2 — `SequencePage` 增加对比状态与右键菜单

1. 新增实例状态：`self.overlay = {}`，形如 `{primary_metric: secondary_metric}`；
   另存 `self.overlay_units = {}`（从 `selection`/列名解析出的单位，供渲染与导出复用）。
2. 在 `render_interactive` 中为每个 `InteractivePlotWidget` 设置右键菜单：

   ```python
   widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
   widget.customContextMenuRequested.connect(
       lambda point, w=widget, m=metric: self.show_panel_menu(w, m, point))
   ```

   `show_panel_menu` 内构造 `QMenu`：

   - `叠加对比…`：仅当 `len(self.metrics) > 1` 且该面板未处于对比状态时启用。
     点击后弹出选择对话框（`QInputDialog.getItem` 即可），候选 = `self.metrics` 中
     **已勾选**（即出现在 `self.cells` 内）且不等于自身的参数。
   - `解除对比`：仅当该面板处于对比状态时启用。
   - 分隔线。
   - **保留 pyqtgraph 原生的 ViewBox 菜单**：`menu.addMenu(widget.getPlotItem().getViewBox().menu)`，
     不得丢失 Auto Range / X-Y 轴 / Export 等既有项。

   **注意**：`metrology_app/matching_window.py:339` 的 `_TrendPlotWidget` 是另一套
   Match Workbook 内部的 Card 对比组件，**与本次任务无关，不要改动它。**
3. `PlotPanel`（`plotting/grid.py:10`）目前只接收 `heading` 和 `plot_widget`。标题区需要放
   `[解除对比]` 按钮，建议给 `PlotPanel` 增加一个**可选**参数（如 `heading_extra=None`），
   不传时行为与现在完全一致，避免影响 `plot_page.py` / `radius_page.py` / `correlation_page.py`
   等其它调用方。

### 步骤 3 — PyQtGraph 双 Y 轴渲染

**重要更正**：不要试图把两根 Y 轴塞进同一个 `ViewBox`。按 pyqtgraph 官方做法
（`examples/MultiplePlotAxes.py`）：**第二根 Y 轴使用新的 `ViewBox`，X 轴与主 ViewBox 互相 link**。

要求：

- 新 ViewBox 必须复用 `_PlotViewBox`（`plotting/interactive.py:9`）并传入**同一个 `auto_x_range`**，
  否则 `reset_views`（`sequence_page.py:552`）还原时两个 ViewBox 的 X 范围会不一致。
- 用 `setXLink` / `linkedView` 做 X 联动；X 不同步是本功能最典型的 bug。
- 第二根轴的刻度与轴标签使用被叠参数的颜色（`SERIES_COLOURS`，`dynamic_page.py:25`），
  轴标签写作 `"{metric} [{unit}]"`，无单位时写作 `"{metric} (unit?)"`。
- **图例**：不同 ViewBox 的 item 不能直接进同一个 legend。用代理曲线，或参照
  `dynamic_page.py:333` 手工构造 `LegendItem`（`colCount=2`）后手动 `addItem`。
  图例项文案为参数名（`Reference` 实线 / `Raw Data` 虚线由线型体现）。
- 面板标题改为 `"{primary} + {secondary}（对比）"`，`SequencePage.status` 同步说明当前对比关系。
- 对比状态下 `self.plot_widgets` / `self.panel_hosts` / `self.home_views` 的长度应等于**面板数**
  （即合并后减少 1），`reset_views` 需要能把主副两个 ViewBox 一起还原——
  建议把 `home_views` 的每一项从"一个 viewRange"扩展为能容纳主副两个 ViewBox 的结构，
  并同步修改 `remember_home_views`。
- 叠加时**不得补线**：延续现有 `connect="finite"`；Matplotlib 侧用
  `finite = np.isfinite(y)` 掩码后再 `plot(x[finite], y[finite])`。

### 步骤 4 — 修正 `cells` / `view_groups` / `x_range`

`draw_plot`（`sequence_page.py:302`）中：

```python
used = [group for group in groups
        if any((group["key"], metric) in cells for metric in self.metrics)]
self.view_groups = used or groups
```

叠加后，某参数可能因"属于对比组"而被绘制。判断必须扩展为
"该参数在 `cells` 中 **或** 它是某个在 `cells` 中参数的对比伙伴"，否则 X 范围会按未绘制的组计算，
第二条曲线的测量集段会被裁掉。

同时确认：被叠参数使用**与发起面板同一批测量集 key**，即
`{key for (key, metric) in self.cells if metric == primary}`。

### 步骤 5 — Matplotlib 导出镜像（`build_export_figure`）

按 Matplotlib 官方做法（`multiple_yaxis_with_spines`）：

```python
twin = ax.twinx()
twin.spines.right.set_position(("axes", 1.12))
```

要求：

- 需要给外侧轴留位置：现有 `subplots_adjust(left=.065, right=.985, ...)`
  （`sequence_page.py:440`）在对比面板上要把 `right` 收窄（约 `0.90`），并确保
  `figure.set_size_inches` 的宽度算法（`draw_plot:347` 的 `base_size`）仍合理。
- 第二根轴的 `set_ylabel` 与 `tick_params(axis="y", colors=...)` 使用该参数颜色。
- **`tests/test_correlation.py:846` 断言 `all(axis._die_sequence_values for axis in sequence.figure.axes)`**。
  新加的 twin 轴会让该断言失败。两种处理任选其一，但必须让全量测试通过：
  (a) 在 twin 轴上也设置 `_wafer_group_labels` / `_die_sequence_values` / `_wafer_ids`；
  (b) 把该断言改为只针对主 axes。
  **优先选 (a)**，因为这三个属性是导出后处理依赖的公开约定，twin 轴也应当具备。
- 对比面板的 `ax.set_title` 使用 `"{primary} + {secondary}"`。

### 步骤 6 — 持久化对比状态

- 用 `metrology_app/settings.py` 的 `get_settings()` 读写，**不要**碰 WKB。
- 建议键：`trend_overlay`，值是 `{primary: secondary}` 的映射（存 JSON 字符串或 QSettings 可序列化形式）。
- `draw_plot` 成功出图后按 `self.overlay` 写回；恢复时若 primary/secondary 不在
  `self.metrics` 内则静默丢弃该条。
- 参考现有 `font_size` / `resolution` 的读写方式（`sequence_page.py:159`、`:166`）。

## 4. 边界情况（必须有明确行为）

| 情况 | 期望行为 |
| --- | --- |
| 只勾选 1 个参数后尝试叠加 | 菜单项禁用，"叠加对比…" 不可点 |
| 试图叠加第 3 个参数 | 拒绝并提示：仅支持两个参数叠加对比 |
| 两个参数单位相同 | 共用左轴，不新增轴 |
| 两个参数单位不同 | 新增右侧第二根 Y 轴，刻度/标签着色 |
| 单位无法解析 | 走第二根 Y 轴，图例标注 `(unit?)` |
| 量级差 > 10× 且单位不同 | 走第二根 Y 轴，`status` 提示"交叉点无物理含义" |
| 被叠参数在选定测量集内全为 NaN | 轴隐藏或曲线为空，`status` 说明该参数无有效值 |
| 某参数中间缺失 Die Seq | 曲线在缺失处断开，**绝不**跨缺失连线 |
| 解除对比 | 恢复一个参数一张图，X 范围与 Reset views 行为与普通模式一致 |
| 对比中取消勾选某个 wafer 后重绘 | X 范围按实际绘制的组收缩（与现有 `used` 逻辑一致），wafer 名轴同步 |
| 切换 `Columns` / `Font` / `Resolution` | 对比状态保持，重绘后仍然合并 |

## 5. 测试要求

### 纯逻辑测试 `tests/test_trend.py`（无需 Qt）

- `test_same_unit_parameters_share_one_axis`
- `test_unknown_units_use_a_second_axis`
- `test_unit_suffix_is_parsed_from_brackets_and_parentheses`
- `test_large_magnitude_gap_sets_warning_without_changing_axis_choice`
- `test_overlay_series_preserves_nan_without_interpolation`

### GUI 测试（追加到 `tests/test_correlation.py`，复用其模块级 `APP`）

- `test_trend_context_menu_offers_overlay_for_checked_parameters`
- `test_overlay_merges_two_panels_into_one_widget_with_two_axes`
- `test_overlay_uses_the_same_measurement_sets_for_both_parameters`
- `test_unlink_overlay_restores_one_panel_per_parameter`
- `test_third_parameter_overlay_is_rejected`
- `test_separate_panel_mode_still_renders_one_widget_per_parameter`（锁死旧契约）
- `test_export_figure_mirrors_the_overlay_and_keeps_wafer_labels`（含 twin 轴的三个私有属性）

### BDD 文档

在 `docs/features/README.md` 增加条目，**格式与该文件现有条目一致**（用反引号挂到上面这些
可执行测试名上，不能只写场景文字当证明）：

- 右键叠加两个参数 → 同单位共用一轴、不同单位自动加第二根 Y 轴
- 解除对比 → 恢复一个参数一张图

## 6. 验收

```
python -m unittest tests.test_trend -v
python -m unittest tests.test_correlation -v
python -m unittest discover -s tests -v
```

全量测试必须通过，尤其是 `tests/test_correlation.py:117` 与 `:846`。

## 7. 明确不做

- 不做归一化（index=100 / z-score）与差值图 — 本轮只做共享轴 + 双 Y 轴。
- 不支持 3 个及以上参数同图。
- 不做拖拽合并，不做全局"对比模式"工具栏按钮。
- 不改 `.wkb` schema，不给 `ParameterMapping` 加字段。
- 不改 `2. Correlation` 页、`metrology_app/matching/`、以及
  `matching_window.py:339` 的 `_TrendPlotWidget`。
- 不为了性能改动任何插值 / 回归 / 色阶 / 导出语义。

## 8. 参考实现（外部，供查阅）

- pyqtgraph 多图轴官方示例 `examples/MultiplePlotAxes.py`
- pyqtgraph X 轴联动：`ViewBox.setXLink` / `linkedView`
- pyqtgraph 已知问题：多 ViewBox 图例合并、多 ViewBox 边距、双轴不同 scale
- Matplotlib 官方示例 `subplots_axes_and_figures/multiple_yaxis_with_spines`
- Matplotlib 缺失数据：`lines_bars_and_markers/masked_demo`
- 设计依据：JMP `Create a Second Y Axis`（同物理量不同 scale 时双轴正当）；
  Brath & Hagerman, *Why Two Y-Axes (Y2Y)*, IV 2020（双轴用于观察局部形态）
