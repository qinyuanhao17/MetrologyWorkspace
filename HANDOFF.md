# Metrology Workspace handoff

更新日期：2026-10-01

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

Match Workbook 的核心规则和 WKB schema 见 `metrology_app/matching/` 与 `docs/adr/`。它按行匹配 Reference/Raw Data，Preview 应用 Card，Final 使用独立且已加 Card 的 Raw Data。schema 5 另存 Preview/Final Map 与 Dynamic 工作区的独立精确表快照；schema 6 保存四个工作区各自右侧的 wafer/parameter 勾选；schema 7 保存 Wafer Map 首次成功绘制状态和实际框选；schema 8 再保存 Radius Plot 对应状态。KLA/NOVA Map 无快照时从相应 Raw Data 初始化，TEM 无独立 Map 数据时保持空白，已编辑快照始终优先恢复。顶部按当前模式提供 Wafer Map / Radius、Dynamic，以及直接读取当前 Reference/Raw Data 的 Correlation and Trend 入口。输入、mapping 和结果共享纵向 splitter；自动重算必须保留用户布局、滚动位置和参数顺序，结果区不再提供 Reset。打开 WKB 后视图从页面顶部开始，但仍恢复保存的 splitter 与参数顺序。首次保存选择路径，之后 `Ctrl+S` 覆盖当前 WKB；`Ctrl+Shift+S` 另存为并切换后续保存目标。File 菜单保存最多 10 个最近 WKB，可跨重启直接打开；已有当前文件时可用 `Reveal WKB in Folder` 在系统文件管理器中定位。

WKB 右上角的 Correlation and Trend 不是独立简化窗口；它与主窗口工具列表复用同一个 `CorrelationWindow`。窗口使用 Ref Data / Raw Data 两个独立数据页；Raw 页保留全部列，Ref 页的 Wafer ID、Lot ID、PAD Name、Die Seq 逐行对齐 Raw，mapping 只为分析提供共用参数名。Correlation 先列 Reference 的来源内拟合，再列 Raw Data；Trend 也按 Reference 后 Raw Data 排列，颜色分别为橙色/蓝色。Trend 默认一参数一图；右键可显式叠加第二个参数，同单位共轴、异单位或未知单位用右轴，颜色表示参数、实线/虚线表示 Reference/Raw。叠加关系只保存在应用 YAML 的 `trend_overlay`，不进入 WKB schema。

Dynamic 复用 `window.MainWindow` 的 Data 编辑和 Wafer/Lot/PAD measurement identity：

- `dynamic.py`：清理原表后附加的旧报表列、Cycle 推断、Cycle × Die Seq pivot、样本 3σ（`3 * std(ddof=1)`）。
- `dynamic_window.py`：Data + Dynamic 两个 tab。
- Data 工作区通过 `selection_state()` / `restore_selection()` 与 `selection_changed` 暴露统一选择状态。整表替换会重新识别 measurement identity，但按列名/measurement key 恢复仍存在的选择并立即刷新；旧 wafer key 全部消失时采用新表的默认全选，避免空白分析。
- Match Workbook 分别缓存 Preview/Final × Map/Dynamic 四份选择。关闭子窗口再打开会恢复仍存在的参数和 wafer，不串用另一模式的选择；schema 8 会分别恢复 Wafer Map 与 Radius Plot 上次成功绘制的框选并立即自动出图，因此彻底重启后无需再次点击 `Draw selected`。
- Match Workbook 打开的 Map/Dynamic 通过 `set_managed_close_handler()` 托管关闭：先把当前表快照回写父窗口，不显示独立工具的 Discard/Cancel 提示；父窗口已有 `workbook_path` 时随即原子覆盖 WKB，没有路径时保留到首次保存。独立打开的工作区仍执行原未保存确认。
- 关闭 Match Workbook 本身时，父窗口会在自身控件仍存活时统一抓取 Map/Dynamic 最新表格与选择、只覆盖当前 WKB 一次，然后解除子窗口保存回调并关闭/销毁 Wafer Map、Dynamic 和 Correlation；不要把这个顺序改回父窗口先销毁，否则子窗口会访问已经删除的 Qt 控件。
- Wafer Maps 与 Radius Plot 各自记忆最后一次成功绘制的方框集合。之后 Data 的粘贴、打开、单元格编辑或勾选变化会自动重绘，不再把 Tab 2/3 强制切回 selector；仍存在的组合精确保留，wafer key 全部变化时将上次参数应用到新 wafer。`Select maps` 始终可手动重新选择；首次成功绘制后，改选方框会以 120 ms debounce 自动重绘，不再要求第二次点击 `Draw selected`。
- `dynamic_page.py`：只分析一个选中的 measurement set；参数来自 Data 勾选且不使用额外下拉框。页面删除重复标题，并拆为两个独立滚动区：上方纵向排列每个参数的 Cycle × Die Seq 表；下方先显示全部已选参数的彩色分组柱图，再显示各参数独立柱图，统一为 420 × 270 px 的三列网格，超过三张自动换行。合并图不显示 `DP + EW + …` 拼接标题，原标题行改为带 10 px 小色块的单行横向 legend；各参数独立图仍保留标题。柱图不叠加数据点。
- 优先从 `Cur SME File Path` 的 `DYNAMIC/<run>` 推断 Cycle；没有该结构时，以有序 Die Seq 首次重复作为下一 Cycle。绝不静默平均重复的 Cycle/Die Seq。

## 修改纪律

- 先读 `AGENTS.md`；计算、状态与 bug 修复采用 TDD，用户可见流程同步维护 `docs/features/`。
- 不覆盖或移动旧 tag。当前交付目标是 `v2.0.0-dev.4`；`VERSION` 仍保持 `2.0.0-dev`。
- 不使用 `git reset --hard` 或 checkout 丢弃用户修改。
- 交付前必须跑完整 unittest 和 `main.py --self-test`。

## 已知后续范围

- Match Workbook 尚未实现按 Wafer ID、Slot ID、PAD Name 和坐标自动对齐未整理 Reference；当前仍是行序对应。
- Dynamic 要求恰好选择一个 measurement set；当前没有跨 measurement set 的合并比较。
- Wafer Map 阵列底部不显示 RBF / edge extension / 自动尺寸说明，尺寸摘要仍保留在绘制结果和状态信息中。
