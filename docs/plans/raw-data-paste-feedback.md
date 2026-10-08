# Raw Data 粘贴反馈

日期：2026-10-08。基线：本次修改前的 `95d7f87`（v3.0.0）。

本页记录第一轮反馈功能的验证。后续已按用户要求删除 `Show changes`，加入复制 / 剪切虚线、
只选已有数据的 Ctrl+A；2026-10-09 已按最新要求改为粘贴后的原生选区，不加实线框与额外着色。最新行为与性能验证见
[Raw Data 粘贴、撤销与范围反馈](raw-data-paste-undo-responsiveness.md)。下面的 548 项全通过属于第一轮，不是最新全量结果。

## 目标与边界

用户重复更新相似的 Raw Data 时，需要确认是否真正更新，以及哪一列改变。
原有实现会写入数据，但只有表格值和 dirty 状态变化；右侧未显示的列尤其难以察觉。

复用既有 Raw Data 粘贴 / 批量更新、Undo 和文档往返的验证入口，
不添加确认弹窗，不更改粘贴范围、源字符串、参与身份、行映射、计算或存储合同。
没有提交、推送或重打 v3.0.0 tag。

## 交付行为

- Raw Data 上方显示最近一次粘贴结果：实际变化格数、涉及的数据行及列名 / 各列数量。
  不把整个粘贴矩形都算作变化；`2.10` → `2.100` 是源字符串变化。
  计数包括改变的 header 和清空的旧值，header、添加 / 删除行另行说明。
- 完全相同的内容显示 `No changes — pasted values match the existing table.`。
  只改变空白尾行数量的整表替换也会报告结构变化，不误报 No changes。
- 变化格使用浅琥珀底色和边框；选中范围内仍能看到边框。悬停查看 Before / After。
  后续取消 `Show changes` 定位按钮；保留变化摘要、源坐标上的高亮与 Before / After。
- 提示保留至下一次粘贴、实际编辑、Undo / Redo、表格重新加载或点击 ×。
  × 只清掉提示和高亮，不改变值、Undo、revision 或 dirty。
  Preview / Final 分别保留自己的反馈，切换时不会把另一阶段的提示贴到当前表。
- 支持格内 Ctrl+V、Ctrl+Shift+V、Raw Data 整表粘贴按钮和 combined clipboard。
  主窗口 / 分析子窗口的共享可编辑数据表也使用同一反馈组件。
  保持既有 Undo 语义：格内及 Ctrl+Shift+V 可撤销；整表导入按钮仍使用原有 load 路径，
  不额外改变该路径清空 Undo 的行为。
- `Paste complete` 仅表示数据粘贴完成，**不表示分析或绘图已经完成**。

## 模块与可执行例子

`sheet.py` 负责源坐标上的精确差异、只读 receipt 和共享表格呈现；
`ProjectedSheetModel` 仅翻译可见坐标。MatchingWindow / MainWindow 只连接既有粘贴入口。
反馈是临时 UI 元数据，不进入 dataframe、WKB、recovery 或导出；没有新依赖、逐格定时器或额外分析。

可执行例子在 `tests/test_paste_feedback.py`，不是只有场景文字：

| 给定 / 操作 | 可观察结果 | 测试 |
| --- | --- | --- |
| 两行、三列，仅 Value 改变 | 精确报告两个格 / 一列，其他字符串不变；Undo 恢复 | `test_nearly_identical_paste_reports_only_exact_string_changes` |
| 粘贴相同内容 | No changes；无高亮、无新增编辑 | `test_identical_paste_confirms_no_changes_without_an_edit_or_highlights` |
| 清表再粘贴较小数据 | 清空值也计入；完整 Undo / Redo；空白尾行计入结构变化 | 两个 `test_replacement_*` |
| 过滤 / 排序后粘贴 | 差异仍对应正确源记录；过滤不会修改其他行 | `test_filtered_paste_highlights_source_rows_after_sort_and_reports_hidden_changes` |
| Cancel 或超出过滤视图的范围 | 值及前次 receipt 不变 | `test_cancelled_or_out_of_bounds_paste_keeps_the_previous_receipt_and_values` |
| Preview / Final 切换及下一次文件加载 | 阶段提示独立；重新加载不遗留旧差异 | 两个窗口集成测试 |
| 选中的格、light / dark | 可见差异边框；不靠取消选择才能看见 | `test_changed_cell_outline_is_visible_inside_selection_in_both_themes` |
| 源值包含标记、换行 | 提示转义显示；文档仍保留字面字符串 | `test_tooltip_escapes_markup_but_clipboard_and_document_keep_literal_strings` |

## GitHub 参考

参考 [AG Grid 的 CellFlashService](https://github.com/ag-grid/ag-grid/blob/latest/packages/ag-grid-community/src/rendering/cell/cellFlashService.ts)
与 [Highlighting Changes 文档](https://www.ag-grid.com/javascript-data-grid/change-cell-renderers/)：
只强调发生变化的单元格、批量安排呈现。此处不照搬逐格动画，而保留一份 receipt 并只绘制可见格。

参考 [Tabulator 的 History 模块](https://github.com/tabulator-tables/tabulator/blob/master/src/js/modules/History/History.js)：
记录 oldValue / newValue，并在清表时使旧历史失效。此处复用已有 Qt Undo，不引入第二套编辑历史。

## 大表测量与保真

固定只读 NOVA 夹具：7,731 × 33，3 个 mappings。
原桌面文件与 scratch 副本 SHA256 都为
`2e5c35c62af4b8b7ab917b1f46444db0538c87430cca43942805e3e89af7be18`。
比较冻结 HEAD 和本次实现，各 3 个独立进程，使用正常 configure_fonts、独立 settings / recovery / MPL 路径。
每个进程的纯表格重复 3 次，窗口入口各 1 次；以下为中位数，单位 ms。

| 入口 | 回调前 / 后 | 当前数值前 / 后 | 完整可见重绘前 / 后 |
| --- | ---: | ---: | ---: |
| 纯表格、相同整表 Ctrl+V | 123.32 / 118.89 | 123.33 / 118.89 | 124.23 / 121.22 |
| 纯表格、仅一列改变 Ctrl+V | 125.93 / 132.67 | 125.94 / 132.68 | 128.17 / 134.96 |
| NOVA 窗口、相同 Ctrl+V | 137.88 / 119.93 | 137.89 / 119.94 | 183.79 / 168.21 |
| NOVA 窗口、仅一列改变 Ctrl+V | 235.23 / 243.25 | 370.79 / 405.98 | 418.33 / 451.91 |
| NOVA 窗口、整表按钮仅一列改变 | 276.54 / 303.09 | 331.89 / 359.83 | 376.81 / 409.20 |

这是反馈功能的成本检查，**不是性能优化结论**。有变化的窗口粘贴回调增加约 8 / 27 ms，
完整重绘增加约 33 ms；相同内容的小幅波动不解释为提速。
现有整表 CSV 解析、同步输入与分析仍会占用 GUI，未声称所有粘贴延迟已消除。
数值当前及可见重绘分别等待，不把 receipt 出现当作分析 / 绘图完成。
离屏重绘不是原生 Windows 帧率或长会话测试。

实验只改变 `AACut_TCDoff` 列的字符串表示，数值相同；精确报告 7,731 个差异格。
每一格与预期 dataframe 比较，Undo 保真，独立检查数值转换及全部拟合 summary 不变。
正式 snapshot 在清除 receipt 前后相同，并通过新 scratch WKB 保存 / 读取完整往返。
light / dark、正常与窄窗口截图确认提示没有遮住表格、选中格仍有边框。

日志与只读 probe：scratch `raw-paste-feedback-audit` 下的 `probe.py`、
`before-fonts-1..3.txt`、`after-fonts-1..3.txt`。最早未 configure_fonts 的试跑不用于上表。
本次的 tdd/bdd 将差异提示绑定到可执行例子；codebase-design 将源坐标归属留在模型；
ponytail 复用 Qt 和原有 Undo，避免新增状态持久化或动画框架。

最终验证：

- 新增反馈回归 12 项通过；之前的表格 / Groups 针对性验证 81 项通过，后补两项边界例子也通过。
- `python run_tests.py` 通过 runner 的 scratch 设置入口执行：**548 项全部通过，245.319 秒**。
  原 Correlation 完整恢复的 2 秒门槛及 Raw Data 全选 / 单格性能门槛均未改并通过。
  日志 `raw-paste-feedback-audit/full-tests.txt`。
- 原 `config/settings.yaml` SHA256 仍为
  `d8a7fe3bf22ed512b0f67bf91ed9dd4452ed5c5e1fa92a153f7fe754b14970e3`；
  原桌面 WKB 的上述 hash 未变化。
- `git diff --check` 通过，只有既有 Windows 行尾提示。
- `main.py --self-test` 在独立 scratch 设置下 exit 0；没有打包或发布。
- 全量仍有既有 modal timer 的 `NoneType.confirm_button` warning、pandas 类型 FutureWarning
  及故意失败保存 / 文件缺失测试的预期 diagnostic traceback；没有新的反馈槽异常。
  不把 unittest 成功解读为全量零告警。
