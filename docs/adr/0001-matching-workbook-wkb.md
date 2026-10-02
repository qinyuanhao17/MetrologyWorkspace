# ADR 0001: Matching Workbook 使用 SQLite-backed WKB

- 状态：Accepted
- 日期：2026-09-26

## 背景

Card Matching 需要保存最多 100,000 行、50 个参数的 Reference 与 Raw Data，并能在多个窗口中重新打开历史结果。Excel 是交付格式，但不适合作为频繁保存和回拨的内部工作文件；pickle 又不能作为可交换的安全格式。

## 决策

`.wkb` 使用 SQLite 文件。schema 1 保存 Reference、匹配 Raw Data、映射和设置；schema 2 新增可选的 Preview FullMap 与 Final Raw Data 表；schema 3 新增独立的 Final 匹配 Raw Data；schema 4/5 加入 Preview/Final Map/Dynamic 工作区的精确表快照；schema 6 加入 Map/Dynamic × Preview/Final 的 wafer/parameter 选择；schema 7/8 加入 Wafer Map/Radius 首次成功绘制状态；schema 9 保存 Preview/Final Correlation and Trend 的 Ref/Raw 侧栏选择与绘制状态；schema 10 支持 Trend 拆轴策略。当前将 Preview/Final 共用的策略保存为可选 metadata 字段 `trend_axis_settings`（`ratio` 缺省 10×，`mode` 为 `auto`/`dual`/`single`、缺省 `auto`）。早期 schema 10 的 stage `trend_axis_ratio` / `trend_axis_mode` 按保存时所在 tab 优先迁移为一份策略，不混用两阶段字段，迁移后不再写入 stage；勾选和绘制状态仍独立保存。metadata 还可以包含 Setup splitter 尺寸与 parameter order；旧文件缺省这些可选 UI 字段时使用默认布局和选择。`MatchWorkbook` 是负责校验、分析和 WKB 保存/载入的稳定 interface；Qt 窗口不直接读写 SQLite。

WKB 保存源表、Map/Dynamic 精确快照与选择、Wafer Map/Radius 自动绘制状态、Correlation/Trend 选择与自动绘制状态、Trend 拆轴模式和小数阈值、映射和分析设置；Card 与普通分析派生序列在载入后重新计算，但已编辑的工作区快照不重新生成。`MatchAnalysisResult` 只保留每个参数的系数，调用 `series(parameter)` 时才展开该参数的 Card Value、Evaluated Value 和 Bias。载入器兼容 schema 1–10；旧文件没有拆轴模式时默认 `auto`，已有倍率仍可读取。

保存过程先写同目录临时文件，提交并关闭 SQLite 句柄后再原子替换目标文件，避免 Windows 上的文件占用和半写入结果。

## 结果

- 历史工作簿可独立打开比较，不依赖 Excel 公式。
- 源数据只存一份，50 个参数的全部派生列不会长期占用内存或磁盘。
- SQLite 文件没有内建压缩；难压缩的 100,000×50 随机浮点双表基准约为 97.9 MB。
- schema 升级必须显式兼容、迁移或拒绝载入，不能静默误读。
- Excel 与 PNG 继续作为可选交付输出，不作为编辑状态的唯一来源。
