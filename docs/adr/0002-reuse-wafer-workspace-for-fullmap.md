# ADR 0002: FullMap 复用现有 Wafer 工作区

- 状态：Accepted
- 日期：2026-09-26

## 背景

Card Matching 的 Preview 和 Final 都需要绘制 Wafer Map 与 Radius Plot。项目已有完整的 Data、Wafer Maps、Radius Plot 工作区；在 Matching 窗口再实现一套绘图会造成参数识别、坐标选择、导出和性能策略分叉。

## 决策

`MatchWorkbook.stage_frame(stage)` 是阶段边界，优先级如下：

- 已保存的 Preview/Final Map 精确快照直接恢复，不再次转换。
- Preview 使用独立 FullMap，对每个映射参数应用拟合 Card；Final 使用独立 Final Raw Data，参数值直接进入绘图，不再次应用 Card。
- KLA/NOVA 没有快照或独立 FullMap 时回退到相应匹配 Raw Data；TEM 没有独立 Map 数据时返回空表，不复制匹配 Raw Data。
- 两种阶段都保留 Wafer ID、坐标、PAD 等非参数列。

Matching 窗口只通过 `MainWindow.set_table(frame, source)` 把处理后的表交给现有 Wafer 工作区，并监听该工作区的数据表改动，把实际 Map 表作为 WKB 快照交回 `MatchWorkbook`。该工作区仍负责参数识别、Wafer Map、Radius Plot 和导出。

## 结果

- TEM 可以用少量点拟合 Card，再对后来取得的 FullMap 应用同一 Card。
- KLA/NOVA 可以直接复用匹配 FullMap，也可以输入独立 Preview FullMap。
- Final 不会误加第二次 Card。
- Wafer/Radius 的修复和性能优化只有一个实现位置。
