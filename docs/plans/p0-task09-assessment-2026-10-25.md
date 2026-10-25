# Task 09 最小架构评估与 Astra 验收交接

评估在 Task 08、Task 07 和新增表格 checkpoint 依次保存后进行。当前生产代码
checkpoint 为 `078eb99d145b40e5719b5f9a46fd9d802471c211`，本项只更新文档。

## 结论：本阶段不再实施额外职责提取

遵照用户“收益不明显或风险较大可以建议不实施”的范围，不拆分整个
`matching_window.py`，不移动导出/Dirty/Recovery 逻辑，也不为了目录整齐改 import。
Task 09 的评估已完成；这不表示原 P0 全部性能目标已经达成或已通过最终产品验收。

| 候选 | 已有边界和实际耦合 | 决策 |
| --- | --- | --- |
| `_analysis_input_frame` | 静态函数只有 frame/headers/preserve_rows 输入，返回独立 DataFrame；没有窗口实例状态。`test_analysis_input_frame_fast.py` 可不启动完整 GUI 测精确字符串/空行/非法类型 fallback。当前约束主要是导入 Qt 协调器，非执行顺序耦合。四个生产调用点均在同一窗口内，没有独立模块调用者。 | 暂不提取。可候选 `prepare_analysis_input(frame, *, headers=None, preserve_rows=True)`；纯模块确实能减少测试导入 Qt 的依赖，但在当前使用范围内收益有限，单纯搬动约 40 行不改善已测热点或状态耦合。 |
| managed child 同步 | `_refresh_stage_workspace` 的 input_update 包裹 participation、sources 和 Group，再恢复视图/页面；`_commit_stage_workspace` 先检测独立草稿，提前返回，再按 kind/stage/source policy 更新和推进 baseline。职责混杂，但顺序表达数据所有权。 | 需要 Astra 先审核事务和接口契约，不能直接提取成通用 sync 并改变调用顺序。 |
| 只取 `.frames` 的 workspace_snapshot | 当前 snapshot 还捕获 UI/Group。同步前后两处都读取 frames，但分别用于“不能覆盖独立草稿”和“接受这次同步后的来源”，并非同一个时间点。 | `source_frames_for_sync()` 只作为接口候选。必须保留两次读取、来源 scope、copy policy、手工 Reference 和 GUI 线程即时比较的生命周期。未实施。 |
| Dirty 纯状态比较 | `same_snapshot/_same_state/_same_plain_state` 已有稳定 seam 和测试；严格保留键顺序、类型、signed zero、非法/循环状态及 JSON fallback。 | 不移动也不简化。此处缺口是性能边界和发布契约，而非缺少独立函数。不能用 dict equality 或 revision 缓存替代精确比较。 |
| Writer 单格撤销 | Cell 和 WriterDocument 已是纯业务模块；窗口的 `_remember/undo/redo` 使用完整序列化快照，单格与导入、Review、Resolve 混用同一历史。 | 不在本阶段更换历史表示或 Dirty 协议。候选是纯单格命令，必须保留整个 Cell 的 OCR 来源、原文、候选及历史，且与全量事务正确交错。 |

表格补充为解决明确热点新增的 `table_selection.py` 已提供必要的共享边界，不在 Task 09
重复计为一项新架构收益。它只处理 Qt 的范围通知和表头；不持有业务数据、不缓存选区、
不负责 Undo/存储。模型的 `uniform_selection_flags` 仅保证所有有效格 enabled/selectable，
不保证 editable 一致；因此与剪贴板权限契约 `uniform_selectable` 保持分离。自定义模型
不 opt-in 时回退原生路径；升级 Qt 时必须复核原生首格辅助功能事件实现，保留完整
selectionModel 信号和绘制失效。这比继续给各窗口复制辅助功能 workaround 更易验证。

## Task 01–09 最新状态

| Task | 状态 | 仍需注意的边界 |
| --- | --- | --- |
| 01 基准 | 前阶段限定范围已验收，本轮继续补测 | 已有原生窗口、规模、P50/P95、gap、CPU/内存；不是 DWM FPS 或长期稳定性证明。冷/热和键返回/完整刷新分开。 |
| 02 恢复性能 | 已验收，保留 | 原发布环境 2.086s 未在本机重现，未放宽旧测试或改写历史结果。 |
| 03 Dirty | 已验收，保留 | 全量继续通过，精确 JSON fallback 未变；不把 Writer 的长比较说成所有 Dirty 场景都已流畅。 |
| 04 Recovery | 已验收，保留 | 既有持久化、生命周期和多窗保护不改；未来异步/所有权方案需重新验收。 |
| 05 配置安全 | 已验收，保留 | 使用隔离路径；本批验证前后真实 settings/源 WKB/两份用户 Excel hash 一致。 |
| 06 大表 | 既有阶段已验收；新增要求部分达标 | 冷 Shift 两个方向、首次全选和纯 Sheet Undo 降到 ms；完整 Workbook/Writer Undo 和宽表 Copy/Paste 仍有长停顿。新增要求未整体标完成。 |
| 07 多窗口 | 本轮低风险范围完成，最终性能验收待审 | 0/1/3/5 linked 矩阵和独立草稿保护通过；五窗 Group/阶段切换仍数秒。只优化实测无效转换，不改所有权/发布协议。 |
| 08 绘图 | 本轮低风险范围完成，最终性能验收待审 | 五类 prepare/render/layout 已测，字体/字幕刷新显著提速；Dynamic、Map 大页完整 Draw/paint 仍有可见成本。 |
| 09 架构 | 评估完成，建议不再实施额外重构 | 当前没有收益明确且可在本阶段安全落地的额外提取；高风险候选交 Astra。 |

旧记录的“6/9”“7/9”是当时限定阶段口径。不能将本表解读成九项全部完成或软件
所有大表操作已流畅；最终验收仍需 Astra High，尤其是用户新增的完整撤销目标。

## 本轮 checkpoint 与修改文件

| 完整 SHA | 范围 |
| --- | --- |
| `ff3c1336520965227572a91f88ad90d3b06a74bd` | Task 08：`dynamic_trend.py`、`plot_page.py`、`radius_page.py`；`benchmark_plot_stages.py`；`test_dynamic_compare_export.py`、`test_plot_labels.py`；两份进度文档及 Task 08 comparison JSON。 |
| `2192a04c72498b0a2d083e763e9f88c75707eef0` | Task 07：`matching_window.py`；`benchmark_workspace_sync.py`；两份进度文档及 Task 07 comparison JSON。 |
| `078eb99d145b40e5719b5f9a46fd9d802471c211` | 表格新增要求：下面列出的 19 文件。 |
| 本评估所在的文档 commit | Task 09：本文件、P0 实施进度和 Ultra 交接索引；无新增生产代码。准确 SHA 见 `git log -1` 和最终交接消息。 |

表格 checkpoint 文件清单：

```text
benchmarks/benchmark_sheet_workflows.py
docs/plans/p0-audit-implementation-2026-10-23.md
docs/plans/p0-ultra-handoff-2026-10-24.md
docs/plans/p0-table-cold-handoff-2026-10-25.md
docs/validation/p0-table-cold-comparison-2026-10-25.json
metrology_app/auto_weighting.py
metrology_app/auto_weighting_window.py
metrology_app/data_selection.py
metrology_app/dynamic_page.py
metrology_app/match_group_ui.py
metrology_app/matching_window.py
metrology_app/sheet.py
metrology_app/table_selection.py
tests/test_analysis_input_frame_fast.py
tests/test_group_control_source_reuse.py
tests/test_reference_edit_controls.py
tests/test_sheet_bounds.py
tests/test_table_selection_notifications.py
tests/test_writer_cell_serialization.py
```

完整目录以 `git show --name-only <SHA>` 为准；上表 Task 08/07 的短文件名分别在
`metrology_app/`、`benchmarks/`、`tests/` 对应目录，详见 Ultra 记录。前阶段
Task 03/01/06 的 SHA 和范围在 `p0-serial-handoff-2026-10-24.md`，没有覆盖其成果。

## 性能与测试交接

- Task 08：Dynamic Trend 字号 direct P50 227.46→4.33ms；Map 字幕 177.91→0.09ms；
  Radius 字幕 12.18→0.10ms。完整 paint 仍计入，数值 digest 前后相同。77 项针对性
  通过；当阶段全量 1,057/1,057，353.931s。
- Task 07：五窗 Raw 完成 P50 3448.90→3223.78ms，但单窗 888.55→924.72ms，
  不宣称所有同步均提速。三项针对性及原生矩阵通过；当阶段全量 1,059/1,059，359.544s。
- 表格：100k×33 冷 Ctrl+A 完整 6332.42→22.43ms；冷 Shift 取消/勾选
  7360.94/7212.88→15.19/17.86ms；Delete 后首次 Undo 1556.42→51.08ms。
  Workbook 全部完整 Undo 及 Writer 残留见补充记录，不能以快键返回宣称完成。
- 最终当前生产代码全量 **1,083/1,083 通过，362.503s**；专项 48 项通过（8.249s）。
  新 serializer 保护改独立进程后，原 300ms 阈值仍在旧生产包失败；首次全量计时失败
  日志保留。Task 09 之后仅文档改动，没有为文档提交重复跑六分钟代码测试。

原始 logs/profiles/JSON 在 `.cache/p0-audit/`，可提交摘要在 `docs/validation/`：
`p0-task08-comparison-2026-10-24.json`、`p0-task07-comparison-2026-10-24.json`、
`p0-table-cold-comparison-2026-10-25.json`。具体环境、样本量、小样本 P95、同步
paint/CPU/内存峰值限制和复现命令保留；无内存改善、长期稳定或 DWM FPS 夸大结论。

## Astra High 具体待审缺口

1. **Task 08**：Dynamic 多参数页面和 Map/Radius 大页 paint；Workbook Undo 中
   measurement spans/身份准备与全页 draw。若引入跨结果复用或异步，先定义 scope、
   generation、取消和 GUI 生命周期，覆盖映射/参数/阶段连变及故意倒序完成，确认旧
   结果不能发布。仍须逐点、拟合、NaN gap、标签、坐标和导出等价。
2. **Task 07**：Group context 的 participation→sources→groups 重复，以及只取 frames
   的完整 snapshot。审核正常 linked、manual/copy off、独立草稿、空表及 reset 分支，
   再确定事务和帧读取接口。保留 pre/post 两个采样点。五个混合子窗口连续操作并同时
   Save/Discard/Recovery 的新发布协议组合仍需专门验收；现有单场景测试不足以证明。
3. **新增 Task 06**：完整 Workbook Undo 约 1.0–1.4s；Writer 10k×41 Undo 约 4.8s、
   Redo 约 3.0s。优先审查纯单格命令与全量历史交错，随后审查 snapshot/Dirty 成本，
   禁止只存 text 或引入无法覆盖嵌套可变状态的 revision 缓存。保留空白、原始精度、
   OCR history、候选、共享别名脱离及所有 Save/Discard/Recovery 行为。
4. **Task 09**：先审核以上职责的所有权和生命周期，再决定是否值得逐个提取。
   `_analysis_input_frame` 只有当确实需要无 Qt 的计算入口时才移动，保留原静态兼容
   入口和现有 golden tests。没有性能/维护收益时继续不实施大重构。

## 回滚与停止点

本 Task 09 是文档提交，撤销不影响运行。生产修改按单个 checkpoint revert，建议与
实际依赖顺序相反（表格→Task 07→Task 08）；回滚后运行对应保护与完整回归。
表格可以单独回退 Writer 序列化 diff，仍与旧存储格式兼容。不要 reset 到 tag 或覆盖
现场导出修改；应用 revert 前先妥善保存这些外部未提交工作。不能单独删除
`table_selection.py` 而保留六个调用模块的导入、继承及模型 opt-in 声明。

未创建 worktree/分支，未 push 或合并稳定分支。表格、Task 07/08 的已通过实现和所有
剩余问题留在本地交给 Astra High。此处停止开发，不自行开展新的高风险优化。
