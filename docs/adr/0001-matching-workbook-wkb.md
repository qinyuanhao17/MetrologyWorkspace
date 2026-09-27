# ADR 0001: Matching Workbook 使用 SQLite-backed WKB

- 状态：Accepted
- 日期：2026-09-26

## 背景

Card Matching 需要保存最多 100,000 行、50 个参数的 Reference 与 Raw Data，并能在多个窗口中重新打开历史结果。Excel 是交付格式，但不适合作为频繁保存和回拨的内部工作文件；pickle 又不能作为可交换的安全格式。

## 决策

`.wkb` 使用 SQLite 文件。schema 1 保存 Reference、匹配 Raw Data、映射和设置；schema 2 新增可选的 Preview FullMap 与 Final Raw Data 表。metadata 还可以包含 Setup splitter 的三个尺寸与 parameter order；它们是兼容旧 schema 1/2 文件的可选 UI 设置，不存在时使用默认布局与映射顺序。`MatchWorkbook` 是稳定 interface，负责校验行序匹配、参数映射、Card 分析、FullMap 阶段转换和 WKB 保存/载入。Qt 窗口不直接读写 SQLite。

WKB 只存源表、映射和分析设置；Card 与派生序列在载入后重新计算。`MatchAnalysisResult` 只保留每个参数的系数，调用 `series(parameter)` 时才展开该参数的 Card Value、Evaluated Value 和 Bias。载入器兼容 schema 1；旧文件没有 Preview/Final FullMap，按空的可选输入处理。

保存过程先写同目录临时文件，提交并关闭 SQLite 句柄后再原子替换目标文件，避免 Windows 上的文件占用和半写入结果。

## 结果

- 历史工作簿可独立打开比较，不依赖 Excel 公式。
- 源数据只存一份，50 个参数的全部派生列不会长期占用内存或磁盘。
- SQLite 文件没有内建压缩；难压缩的 100,000×50 随机浮点双表基准约为 97.9 MB。
- schema 升级必须显式兼容、迁移或拒绝载入，不能静默误读。
- Excel 与 PNG 继续作为可选交付输出，不作为编辑状态的唯一来源。
