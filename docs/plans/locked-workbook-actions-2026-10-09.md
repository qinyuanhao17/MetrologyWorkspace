# Wafer Map 锁定后的剪切、Copy 和 selection 修复

采用最新用户要求：metadata 锁保护源数据，不禁用选择操作；Copy from WKB 与粘贴同样不能覆盖锁住的位置。
本记录覆盖早先“混合剪切整体拒绝”“关闭 Copy 时所有选择项禁用”和“TEM Map 不可显式 Copy”的规则。

## 根因及改动

- Ctrl+X 的整区 editable 检查遇到锁列就退出。现在共享普通表格复制完整选区，正常模型 edit 只清除未锁列，
  一次 Undo 恢复此次清除。计算结果和其他非metadata只读限制仍拒绝剪切，复制失败仍不清空来源。
- 关闭 Copy 原先加载空表，连同锁数据和锁状态一起删掉。现在有锁的表按原位置保留锁列名、精确字符串及行数，
  仅清空其余单元格和列名；无锁时仍清空输入。
- 重新 Copy 原先直接替换来源。现在 Wafer Map 调用同一位置合并规则，保留 X/Y 等锁定列，更新未锁数据。
  已清空的未锁列可留下重复空白列名，重新复制时不再误判为重复的命名字段；有内容的重复名称仍拒绝。
- 锁定的混合来源作为真实子窗口草稿保存，不把它当作可丢弃的派生表；实际 WKB 保存重开保留锁、列名和数值。
- Map 的 Match Workbook selection、Full data、Data selection 不受锁或 Copy 关闭影响。
  对手动/锁定的 Map，选择范围仅改变当前表中参与绘图的记录，不重载数据、不弹出丢弃数据确认、不改变 Copy 状态。
  重新 Copy 时有锁则保留当前选择范围，避免把 Full data 擅自切回 Match selection 后造成行数不匹配。
- TEM Map 仍默认独立表、初始不勾 Copy，Raw 更新不会自动覆盖它；Data 菜单现在允许显式复制当前阶段的 WKB Raw。
  该显式复制不新增 Card 转换。Dynamic 独立表和 Correlation 输入开关保持原规则。
- 小锁继续为此前一半宽高、50% 不透明度，保留点击区域；锁功能仍仅在 Wafer Map metadata 列提供。

## 安全边界

Copy 与粘贴一样按原列/行位置保护，不猜测 Wafer/Die 对齐。复制的行数不同或缺少锁列位置时仍需要先解锁。
取消 Copy 确认或复制校验失败，旧数据、锁和选项保持不变；不会先清空后报错。
Full data 在此表示不应用 WKB participation，子窗口自己的 Data selection 仍有效。
有锁时切换 selection 保留当前表的全部源行，只切换参与状态，不重新引入原本未复制进来的行。

## 最小验证

沿用 tdd、bdd、ponytail：使用已确认的表格剪切/粘贴、Data 菜单、选择对话框和 WKB Save/Open 接口，
分别先复现 Ctrl+X 退出、Copy 取消删锁、选择禁用、TEM Copy 禁用、Copy 擅自改变范围，再作最小修改。
没有新增持久化格式、依赖、异步架构或性能策略。

相关测试限定为：`tests.test_workbook_copy_data`、`tests.test_metadata_locks`，以及已有两项剪切安全和两项 TEM 独立表检查。
覆盖普通/锁定表、手动/复制模式、NOVA/TEM、精确字符串、一次 Undo、实际 WKB 保存重开、
鼠标点击实际菜单、选择对话框、取消、行数拒绝、只读结果保护及原先 Correlation 工作流。
最终 **26 项全部通过，5.691 秒**；这是限定范围的功能验证，不是全量或响应性测量。
执行输出在 `.cache/locked-workbook-actions/focused-tests.txt`。

所有设置、recovery、临时 WKB 和 Matplotlib 缓存均使用 scratch，未修改原始桌面 WKB。
未运行全量测试、延迟基准、打包或 GitHub 推送；其余待确认任务不在本次范围内。
