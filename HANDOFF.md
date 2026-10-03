# Metrology Workspace handoff

更新日期：2026-10-02

## 快速开始

- 项目：`C:\Users\Yuanhao Qin\OneDrive\Desktop\MyCodes\MetrologyWorkspace`
- 入口：`main.py`
- 环境：`C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe`
- 完整背景：[docs/HANDOFF.md](docs/HANDOFF.md)

```powershell
& 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe' main.py
& 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe' -m unittest discover -s tests -v
& 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe' main.py --self-test
```

## 当前产品边界

主窗口以 registry 延迟创建四个可多开的工具，显示顺序为 Match Workbook、Wafer Map、Correlation and Trend、Dynamic。右侧 Activity 显示会话事件，底部可调高度的只读诊断 Log 横跨主窗口并记录运行环境、错误和 WKB 路径；用户拖动过 Log 分隔栏后，正常关闭会把尺寸写入设置并在下次启动恢复；空闲时不显示 `No tools open`。Log 使用系统等宽终端字体、跟随 Light/Dark 主题，并为日志级别提供语义颜色；左侧工具列表是唯一的启动入口。Shell 不再显示全局 Close all、Ready 文案、绿色状态点或占位状态栏。

所有 PyQtGraph 区域统一使用 `metrology_app.plotting.InteractivePlotWidget`：普通滚轮转发给最近的外层滚动区，只有 Ctrl+滚轮缩放图；Dynamic 不得退回直接实例化 `pg.PlotWidget`。

Match Workbook 的核心规则和 WKB schema 见 `metrology_app/matching/` 与 `docs/adr/`。它按行匹配 Reference/Raw Data，Preview 应用 Card，Final 使用独立且已加 Card 的 Raw Data。schema 5 另存 Preview/Final Map 与 Dynamic 工作区的独立精确表快照；schema 6 保存四个工作区各自右侧的 wafer/parameter 勾选；schema 7 保存 Wafer Map 首次成功绘制状态和实际框选；schema 8 再保存 Radius Plot 对应状态；schema 9 保存 Preview/Final Correlation and Trend 各自的 Ref/Raw 侧栏选择以及 Correlation/Trend 两页的成功绘制状态和框选。KLA/NOVA Map 无快照时从相应 Raw Data 初始化，TEM 无独立 Map 数据时保持空白，已编辑快照始终优先恢复。顶部按当前模式提供 Wafer Map / Radius、Dynamic，以及直接读取当前 Reference/Raw Data 的 Correlation and Trend 入口。输入、mapping 和结果共享纵向 splitter；自动重算必须保留用户布局、滚动位置和参数顺序，结果区不再提供 Reset。打开 WKB 后视图从页面顶部开始，但仍恢复保存的 splitter 与参数顺序。首次保存选择路径，之后 `Ctrl+S` 覆盖当前 WKB；`Ctrl+Shift+S` 另存为并切换后续保存目标。File 菜单保存最多 10 个最近 WKB，可跨重启直接打开；已有当前文件时可用 `Reveal WKB in Folder` 在系统文件管理器中定位。

WKB 右上角的 Correlation and Trend 与主窗口工具列表复用同一个 `CorrelationWindow`。Ref Data / Raw Data 是独立数据页；Raw 保留全部列，Ref 的 Wafer ID、Lot ID、PAD Name、Die Seq 逐行对齐 Raw。Correlation 和 Trend 都先列 Reference 再列 Raw Data，基础曲线分别为橙色/蓝色。Trend 默认一参数一图；每图右侧固定宽度的 `Add Compare` 控制栏可添加多个来源明确的候选项，不会改变图宽；新增曲线使用橙蓝以外的颜色与不同点形。`trend.overlay_spec` 的 Auto 模式按单位和中位绝对值倍率拆轴；Match Workbook 的 **Analysis ▸ Trend Y axes** 提供可输入小数的倍率 spinbox（默认 10×），以及 `Always two Y axes` / `Always one Y axis`。强制单轴混用不同单位时，图轴和状态栏明确标记 mixed units。工作簿打开的 Correlation 窗口隐藏页内控制，独立窗口保留相同的模式和倍率控件；两者均即时重画。Preview/Final 共用模式与倍率，写入 WKB metadata 的单份 `trend_axis_settings`（`mode` / `ratio`），无需子窗口打开也能保存。旧文件优先采用保存时所在 stage 的完整设置，再移除旧 stage 轴设置键；只有倍率时默认 Auto，各阶段勾选与绘制状态保持独立。普通单表叠加关系使用 YAML 的 `trend_overlay`，来源感知关系使用版本化的 `trend_source_overlay`，两者均不进入 WKB schema。

Trend 的 Y 轴单位来自 `trend.parse_unit`：列名末尾的显式单位优先（`EW (V)`、`Si_SWA [rad]`）；否则名称含 `ratio` 视为无量纲 `1`，含 `SWA` 视为 `degree`，其余建模参数视为 `nm`。`data.inspect_table` 不把非建模列当作参数：除身份/坐标/路径列外，MSE、GOF、NGOF、LBH、fitTime、regIter（含 `reglter`）、CINDEX、Seq、Logical ID 都不会出现在参数列表里。Trend 重绘时先读取再恢复面板列表滚动位置（`SequencePage.restore_page_scroll`），并在替换网格期间关闭刷新，因此添加、切换或删除对比既不会跳回顶部，也不会出现“先上去再下来”的重绘过程。

Match Workbook 打开的 Wafer Map / Radius 与 Dynamic 会把「参数名 → Card(slope, intercept)」交给子窗口（`MatchingWindow._offer_parameter_cards()` → `MainWindow.set_parameter_cards()`），子窗口 Data 页 Parameters 卡片里的 **Card** 勾选框（`MainWindow.card_check`，默认不勾）决定 `recognize()` 里 `_frame` 是否走 `carded_frame()`；表格本身保持载入的原始数值，勾选只影响绘图与统计，独立窗口没有 Card 时该框禁用。子窗口因此拿到的是未加 Card 的 stage 表（`stage_frame(stage, apply_card=False)` / `dynamic_frame(stage, apply_card=False)`），WKB 里的工作区快照也随之保存原始值。Match 打开的 Correlation and Trend 在首次成功 `Draw selected` 后自动刷新改选方框；关闭子窗口时将独立的 Ref/Raw 勾选与 Correlation/Trend 两套方框写入当前 WKB。重开子窗口或完整关闭再打开 WKB 后，会恢复仍存在的选择并自动出图；Preview 和 Final 状态互不串用。

三个分析子窗口与 Match Workbook 的同步规则由 `MatchingWindow.sync_stage_windows()` 统一处理，在 `run_analysis()` 末尾按 `(reference, raw, mappings, match_type)` 是否变化触发：KLA/NOVA 下 Map/Radius 与 Correlation 跟随工作簿的 Ref/Raw 刷新（Map 由 Raw 经 Card 推导，Correlation 直接读 Ref/Raw），Dynamic 在任何模式下都是独立表：打开时只恢复它自己保存的 Dynamic 表，没有则空白，绝不复制 Raw/Map 数据，也不参与刷新，一旦用户编辑了某个子窗口的表格，该阶段就由它的快照冻结、不再被覆盖（因此 KLA/NOVA 打开与关闭窗口时都不再写快照，只有真正的编辑才写）；TEM 的 Map/Radius 是独立数据，不参与刷新，TEM 下每个按钮最多一个窗口（`_prepare_stage_window(kind, stage)` 命中已打开的同 kind+stage 窗口时把它带到前面并刷新，不再关掉其它两个）。同步期间 `_syncing_stage_windows` 会屏蔽 `model.changed` 回写，避免把刷新误记成用户编辑。刷新只更新数据：`_workspace_views()` / `_restore_workspace_views()` 把子窗口的当前 tab、可编辑网格的当前单元格与滚动位置还原（`MainWindow.set_table()` 与 `CorrelationWindow.set_sources()` 内部会 `tabs.setCurrentIndex(0)` 并把网格重置到 A1），`_workspace_pages()` / `_restore_workspace_pages()` 再把 Map/Radius/Correlation/Trend 页里“方框选择页 vs 绘图页”的切换还原。页面内部各自记住用户意图：`PlotPage.page_intent` 区分框选页/画布并在 `refresh_previous_selection` 走 `preserve_canvas=True`（恢复缩放与滚动），`RadiusPage.refresh_previous_selection` 用 `restore_canvas_view` 恢复缩放与滚动，`CorrelationPage.user_page`/`page_intent` 记住用户翻到的排名页与页内视图。Raw Data、Reference、Parameter mapping 三种触发共用这条路径，由 `MatchingWindowTests.test_refreshing_analysis_windows_keeps_their_active_tab` 与 `MatchingWindowTests.test_kla_refresh_keeps_each_windows_plot_view` 覆盖。

Correlation 不再截断为 Top 12：全部通过 R² 阈值的拟合保留并按 6/12/24 个每页分页，默认 12。上一页/下一页保留全局 R² rank；末页数量不足时保留既定列数和 350 px 行高，空单元留白，不再拉伸剩余图。Copy PNG 和 Export page 针对当前页，Export all 按页生成带 `_01`、`_02` 后缀的 PNG，避免单张超大图片。

所有可编辑数据表共用 `DuplicateHeaderBanner`：重复表头警告至少 48 px 高，并提供可撤销的 `Auto rename`。该修复入口覆盖通用 Data 页、Match 的 Reference 与 Preview/Final Raw Data，以及 Correlation 的 Ref Data；重命名只改第 1 行重复表头，不改数据行。

Dynamic 复用 `window.MainWindow` 的 Data 编辑和 Wafer/Lot/PAD measurement identity：

- `dynamic.py`：清理原表后附加的旧报表列、Cycle 推断、Cycle × Die Seq pivot、样本 3σ（`3 * std(ddof=1)`）、Trend 用的 `cycle_trend()`（同样的去重/校验，去掉派生的 3σ 行）和 `selected_measurement_rows()`（保留原始 Data 行号，供 pivot 编辑与趋势映射回写）。
- `dynamic_trend.py`：Dynamic 的第三个 tab。每个勾选参数一张交互图，横轴 Cycle，**每张图只画一个 Die**（`selected_dies` 按参数记忆，`select_die()` 只重画该面板并重新 autoRange），图右侧 `ScrollSafeComboBox` 选择 Die；不提供 Add Compare 控制栏，也没有曲线框选。参数与 Cycle 来自 Data 勾选与当前 measurement set，数据一改就重画并保留面板列表滚动位置。带 Columns 1/2、Font、Resolution、Reset views 与 Export / Copy PNG，导出标题为 `参数 · Die n`。`DIE_SYMBOLS` 必须同时是 pyqtgraph 和 Matplotlib 认得的符号（pyqtgraph 只有 `o s t t1 t2 t3 d + x star p h` 等，没有 `v`/`<`/`>`；对应 Matplotlib 用 `v`/`<`/`>`）——写错会让整张 Trend 页打不开，测试 `test_die_symbols_are_supported_by_both_render_backends` 守着这一点。
- `dynamic_window.py`：Data + Dynamic + Trend 三个 tab。第三个 tab 复用 `DynamicTrendPage`。
- Data 工作区通过 `selection_state()` / `restore_selection()` 与 `selection_changed` 暴露统一选择状态。整表替换会重新识别 measurement identity，但按列名/measurement key 恢复仍存在的选择并立即刷新；旧 wafer key 全部消失时采用新表的默认全选，避免空白分析。
- Match Workbook 分别缓存 Preview/Final × Map/Dynamic 四份选择。关闭子窗口再打开会恢复仍存在的参数和 wafer，不串用另一模式的选择；schema 8 会分别恢复 Wafer Map 与 Radius Plot 上次成功绘制的框选并立即自动出图，因此彻底重启后无需再次点击 `Draw selected`。
- Match Workbook 打开的 Map/Dynamic 通过 `set_managed_close_handler()` 托管关闭：先把当前表快照回写父窗口，不显示独立工具的 Discard/Cancel 提示；父窗口已有 `workbook_path` 时随即原子覆盖 WKB，没有路径时保留到首次保存。独立打开的工作区仍执行原未保存确认。
- 关闭 Match Workbook 本身时，父窗口会在自身控件仍存活时统一抓取 Map/Dynamic 最新表格与选择、只覆盖当前 WKB 一次，然后解除子窗口保存回调并关闭/销毁 Wafer Map、Dynamic 和 Correlation；不要把这个顺序改回父窗口先销毁，否则子窗口会访问已经删除的 Qt 控件。
- Wafer Maps 与 Radius Plot 各自记忆最后一次成功绘制的方框集合。只有纯数据变化（粘贴、打开、单元格编辑，wafer/参数勾选不变）才会自动重绘并保持图可见；方框改选、Wafer/Parameters 勾选变化会回到 selector，必须重新选择并点击 `Draw selected`。仍存在的组合精确保留，wafer key 全部变化时将上次参数应用到新 wafer。
- `dynamic_page.py`：只分析一个选中的 measurement set；参数来自 Data 勾选且不使用额外下拉框。页面删除重复标题，并拆为两个独立滚动区：上方纵向排列每个参数的 Cycle × Die Seq 表；下方先显示全部已选参数的彩色分色柱图，再显示各参数独立柱图，统一为 420 × 270 px 的三列网格，超过三张自动换行。合并图不显示 `DP + EW + …` 拼接标题，原标题行改为带 10 px 小色块的单行横向 legend；各参数独立图仍保留标题。柱图不叠加数据点。透视表数值格可编辑：`DynamicPivotModel` 把 (pivot 行列) 经 `cell_sources` 映射回 Data 表单元格，用 `DynamicWindow.model.edit()` 作为**唯一一步**写入共享的 SheetModel 撤销栈；`DynamicPivotView` 复用 Data 表的 Ctrl+C/V、Ctrl+Z/Y 与 Delete 键位（Ctrl+Z 只回退一步）。Cycle/Die 标签与派生的 `3 Sigma` 行为只读；每个参数标题旁的 **Restore** 用 `DynamicWindow.set_table()` 时保存的 `baseline` 一次性恢复该参数的全部格子。编辑后 `refresh()` 保留上层滚动位置与当前格子，不跳回顶部。
- 优先从 `Cur SME File Path` 的 `DYNAMIC/<run>` 推断 Cycle；没有该结构时，以有序 Die Seq 首次重复作为下一 Cycle。绝不静默平均重复的 Cycle/Die Seq。
- Dynamic 数值编辑与撤销改为局部更新：`changed_dynamic_parameters()` 在选择、行位置、表头及 Cycle/Die 推断输入不变时返回脏参数；DynamicPage 仅计算这些 pivot、用 `update_values()` 保留编辑器并更新原 BarGraphItem，DynamicTrendPage 原位更新当前 Die 的 PlotDataItem（其他 Die 编辑只更新导出表）。任何结构/有效 pivot 轴变化仍完整刷新。Dynamic 的 debounce 为 50 ms，统计和共享 Undo 栈不变。可复测 `python benchmarks/benchmark_dynamic_edits.py`，使用隔离设置、130 行/26 参数，记录编辑及撤销的中位 UI 刷新耗时，`--profile` 可定位热点。

## 修改纪律

- 先读 `AGENTS.md`；计算、状态与 bug 修复采用 TDD，用户可见流程同步维护 `docs/features/`。
- 不覆盖或移动旧 tag。当前交付目标是 `v2.0.0-dev.4`；`VERSION` 仍保持 `2.0.0-dev`。
- 不使用 `git reset --hard` 或 checkout 丢弃用户修改。
- 交付前必须跑完整 unittest 和 `main.py --self-test`。

## 已知后续范围

- Match Workbook 尚未实现按 Wafer ID、Slot ID、PAD Name 和坐标自动对齐未整理 Reference；当前仍是行序对应。
- Dynamic 要求恰好选择一个 measurement set；当前没有跨 measurement set 的合并比较。
- Wafer Map 阵列底部不显示 RBF / edge extension / 自动尺寸说明，尺寸摘要仍保留在绘制结果和状态信息中。
