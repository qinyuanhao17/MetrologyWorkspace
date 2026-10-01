# ADR 0001: Matching Workbook 使用 SQLite-backed WKB

- 状态：Accepted
- 日期：2026-09-26

## 背景

Card Matching 需要保存最多 100,000 行、50 个参数的 Reference 与 Raw Data，并能在多个窗口中重新打开历史结果。Excel 是交付格式，但不适合作为频繁保存和回拨的内部工作文件；pickle 又不能作为可交换的安全格式。

## 决策

`.wkb` 使用 SQLite 文件。schema 1 保存 Reference、匹配 Raw Data、映射和设置；schema 2 新增可选的 Preview FullMap 与 Final Raw Data 表；schema 3 新增独立的 Final 匹配 Raw Data，使 Preview/Final 不再共享可编辑输入；schema 4 新增 Preview/Final Map 工作区的精确表快照，并以表是否存在区分“尚未初始化”和“用户明确保留空表”；schema 5 再加入 Preview/Final Dynamic 工作区的独立精确表快照；schema 6 在 metadata 中加入 Map/Dynamic × Preview/Final 四份 wafer/parameter 选择状态；schema 7 在 Map 选择状态中加入 Wafer Map 首次成功绘制标志和实际框选组合；schema 8 再加入 Radius Plot 的成功绘制标志和实际框选组合。metadata 还可以包含 Setup splitter 的三个尺寸与 parameter order；它们是兼容旧 schema 的可选 UI 设置，不存在时使用默认布局、映射顺序和工作区选择。`MatchWorkbook` 是稳定 interface，负责校验行序匹配、参数映射、Card 分析、Map/Dynamic 初始化与快照优先级，以及 WKB 保存/载入。Qt 窗口不直接读写 SQLite。

WKB 保存源表、Map/Dynamic 精确快照、四份工作区选择、Wafer Map/Radius 自动绘制状态、映射和分析设置；Card 与普通分析派生序列在载入后重新计算，但已编辑的工作区快照不重新生成。`MatchAnalysisResult` 只保留每个参数的系数，调用 `series(parameter)` 时才展开该参数的 Card Value、Evaluated Value 和 Bias。载入器兼容 schema 1–7；旧文件没有 Map 快照时按 Match Type 的默认规则初始化，没有 Dynamic 快照时由相应阶段数据初始化，没有工作区选择或绘制状态时采用当前默认选择并保留首次手动绘制行为。

保存过程先写同目录临时文件，提交并关闭 SQLite 句柄后再原子替换目标文件，避免 Windows 上的文件占用和半写入结果。

## 结果

- 历史工作簿可独立打开比较，不依赖 Excel 公式。
- 源数据只存一份，50 个参数的全部派生列不会长期占用内存或磁盘。
- SQLite 文件没有内建压缩；难压缩的 100,000×50 随机浮点双表基准约为 97.9 MB。
- schema 升级必须显式兼容、迁移或拒绝载入，不能静默误读。
- Excel 与 PNG 继续作为可选交付输出，不作为编辑状态的唯一来源。
