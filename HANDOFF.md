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

主窗口以 registry 延迟创建四个可多开的工具：Wafer Map、Correlation and Trend、Match Workbook、Dynamic。右侧是只读诊断 Log，记录运行环境、窗口事件、错误和 WKB 路径；左侧工具列表是唯一的启动入口。

Match Workbook 的核心规则和 WKB schema 见 `metrology_app/matching/` 与 `docs/adr/`。它按行匹配 Reference/Raw Data，Preview 应用 Card，Final 使用独立且已加 Card 的 Raw Data。输入、mapping 和结果共享纵向 splitter；自动重算必须保留用户布局、滚动位置和参数顺序。打开 WKB 后视图从页面顶部开始，但仍恢复保存的 splitter 与参数顺序。

Dynamic 复用 `window.MainWindow` 的 Data 编辑和 Wafer/Lot/PAD measurement identity：

- `dynamic.py`：清理原表后附加的旧报表列、Cycle 推断、Cycle × Die Seq pivot、样本 3σ（`3 * std(ddof=1)`）。
- `dynamic_window.py`：Data + Dynamic 两个 tab。
- `dynamic_page.py`：只分析一个选中的 measurement set；参数来自 Data 勾选；最后一行和柱图均显示各 Die 的 3σ。
- 优先从 `Cur SME File Path` 的 `DYNAMIC/<run>` 推断 Cycle；没有该结构时，以有序 Die Seq 首次重复作为下一 Cycle。绝不静默平均重复的 Cycle/Die Seq。

## 修改纪律

- 先读 `AGENTS.md`；计算、状态与 bug 修复采用 TDD，用户可见流程同步维护 `docs/features/`。
- 不覆盖或移动旧 tag。当前交付目标是 `v2.0.0-dev.4`；`VERSION` 仍保持 `2.0.0-dev`。
- 不使用 `git reset --hard` 或 checkout 丢弃用户修改。
- 交付前必须跑完整 unittest 和 `main.py --self-test`。

## 已知后续范围

- Match Workbook 尚未实现按 Wafer ID、Slot ID、PAD Name 和坐标自动对齐未整理 Reference；当前仍是行序对应。
- Dynamic 当前一次展示一个所选参数；多个已勾选参数通过顶部 Parameter 切换，并要求恰好选择一个 measurement set。
