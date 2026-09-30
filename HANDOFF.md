# Metrology Workspace handoff

更新日期：2026-09-30

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

主窗口以 registry 延迟创建四个可多开的工具：Wafer Map、Correlation and Trend、Match Workbook、Dynamic。右侧 Activity 显示会话事件，底部可调高度的只读诊断 Log 横跨主窗口并记录运行环境、错误和 WKB 路径；Log 使用系统等宽终端字体、跟随 Light/Dark 主题，并为日志级别提供语义颜色；左侧工具列表是唯一的启动入口。

Match Workbook 的核心规则和 WKB schema 见 `metrology_app/matching/` 与 `docs/adr/`。它按行匹配 Reference/Raw Data，Preview 应用 Card，Final 使用独立且已加 Card 的 Raw Data。输入、mapping 和结果共享纵向 splitter；自动重算必须保留用户布局、滚动位置和参数顺序。打开 WKB 后视图从页面顶部开始，但仍恢复保存的 splitter 与参数顺序。首次保存选择路径，之后 `Ctrl+S` 覆盖当前 WKB；`Ctrl+Shift+S` 另存为并切换后续保存目标。

Dynamic 复用 `window.MainWindow` 的 Data 编辑和 Wafer/Lot/PAD measurement identity：

- `dynamic.py`：清理原表后附加的旧报表列、Cycle 推断、Cycle × Die Seq pivot、样本 3σ（`3 * std(ddof=1)`）。
- `dynamic_window.py`：Data + Dynamic 两个 tab。
- `dynamic_page.py`：只分析一个选中的 measurement set；参数来自 Data 勾选且不使用额外下拉框；多参数合并到同一透视表。两个参数生成一张分组对比图和两张单参数图，每张 510 × 330 px，横向滚动；最后一行和柱图均显示各 Die 的 3σ。
- 优先从 `Cur SME File Path` 的 `DYNAMIC/<run>` 推断 Cycle；没有该结构时，以有序 Die Seq 首次重复作为下一 Cycle。绝不静默平均重复的 Cycle/Die Seq。

## 修改纪律

- 先读 `AGENTS.md`；计算、状态与 bug 修复采用 TDD，用户可见流程同步维护 `docs/features/`。
- 不覆盖或移动旧 tag。当前交付目标是 `v2.0.0-dev.4`；`VERSION` 仍保持 `2.0.0-dev`。
- 不使用 `git reset --hard` 或 checkout 丢弃用户修改。
- 交付前必须跑完整 unittest 和 `main.py --self-test`。

## 已知后续范围

- Match Workbook 尚未实现按 Wafer ID、Slot ID、PAD Name 和坐标自动对齐未整理 Reference；当前仍是行序对应。
- Dynamic 要求恰好选择一个 measurement set；当前没有跨 measurement set 的合并比较。
