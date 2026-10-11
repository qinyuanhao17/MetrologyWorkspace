# 第四与第六项：不完整工作簿入口及参数映射加/减

根据最新用户确认，只做功能修改与最小相关测试，不做全量、延迟优化、打包或推送。

## 第四项

- Correlation and Trend、Wafer Map / Radius、Dynamic 的 Preview/Final 入口不再受匹配输入是否齐全限制。
- Reference 为空、Ref/Raw 行数不一致、Raw 缺失或整个工作簿为空时，也可打开独立的可编辑子窗口。
  有可用来源则呈现来源；无来源则呈现真实空表，可手动粘贴。Dynamic 仍使用自己的独立数据。
- 不放宽 MatchWorkbook 的行数、映射、列名或数值校验，不制造匹配结果或借用不对应的 Raw 行身份给 Reference。
  不完整时 Run analysis 仍禁用，窗口保留可见提示；完整未分析草稿沿用原按需分析流程。
- 在分析输入中忽略所有量测单元格均为空或仅空格的列，包括空表头和命名但没有数据的列。
  原始表格和 WKB draft 仍保留它们及精确源字符串；保留参与记录所需的空白源行。
  真正有数据的重复列名仍拒绝，拒绝前不改写旧表。
- 无有效匹配时不向子窗口提供旧 Card、不自动覆盖其独立草稿；子窗口自己的 Data selection 仍可使用。

## 第六项

- Parameter mapping 标题旁加入 + 和 −；不增加 Ref 比较选项，不改 `Raw Data column` 名称。
- − 删除 Use 勾选的映射行及其匹配结果绘图，不删除 Reference/Raw 的任何字段或单元格。
  没有剩余参与参数时清空旧匹配和 Group 绘图，避免继续显示已删除参数或触发陈旧结果的回调。
- + 使用原生选择对话框，从当前尚未映射的 Reference 参数中加入一项，可加回此前删除的映射。
  所有可用 Reference 参数均已在表中时禁用 +；需要更多参数时先提供相应 Reference 数据。
- 数据刷新不自动复活被删除的映射；删除状态保存到可选 `match_ui.removed_mapping_columns`。
  草稿及已分析 WKB 重开后保持删除状态；老文件缺字段时保持原先自动列出参数的行为。
  未变更 WKB 格式版本、源数据或拟合计算规则。

## 验证

沿用 tdd/bdd 的小步失败用例与可观察工作流、ponytail 的现有控件复用；
按 codebase-design 将独立编辑入口与严格匹配计算分开，并让 Group 绘图自行处理无结果状态。

- 新增 `tests.test_incomplete_workbook_workspaces`：6 项。
  包含边缘两列清空、命名空列、真重复列拒绝、三个实际按钮打开及真实 Ctrl+V、行数不一致不借用身份、
  空 Final 工作簿手动 Map 数据的实际 WKB 保存重开。
- 新增 `tests.test_mapping_row_controls`：3 项。
  包含删除勾选映射/绘图且不改原始来源、真实 + 选择对话框及取消的 Ref 功能未引入、草稿/已分析 WKB 重开。
- 另运行 13 个直接相关的现有输入、行映射、勾选、自动分析、TEM 独立表及锁定 Copy/selection 回归。

合计 **22 项全部通过，5.915 秒**，输出 `.cache/incomplete-workbook-workspaces/focused-tests.txt`。
设置、recovery、Matplotlib 缓存和临时 WKB 均使用 scratch，未写原始桌面 WKB。
这是限定范围功能验证，不是全量或性能测量；其余延期的全量和延迟优化仍未执行。
