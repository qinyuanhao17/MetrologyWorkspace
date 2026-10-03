# ADR 0002：统一 WKB 文档与父子草稿

> 此文保留第一阶段决策历史。分类后缀、子窗口菜单、独立副本与分层恢复由
> [ADR 0003](0003-typed-workspaces-and-independent-copies.md) 细化并取代对应旧行为。

- 状态：Accepted，本地实现尚未上传
- 日期：2026-10-03
- 取代 ADR 0001 的新文件写入结构；继续兼容其 schema 1–10 读取。

## 决策

保留 `.wkb`，统一 SQLite 单文件容器，按 `workspace_type` 区分 Match、Wafer Map、
Dynamic、Correlation/Trend。一个 Match 文档拥有 Preview/Final 的三个子工具；独立工具
各自是一份文档。数据与配置保存，图形对象、缓存、undo 历史不保存。

使用一套 `save_workspace` / `load_workspace`：生成 SQL 表列标识，原表头与 dtype 放入
`frame_catalog`；用显式 `row_order` 保留行序，重复表头也能作为待修复草稿保存。
各作用域存版本化 JSON；映射的 JSON 是恢复来源，`parameter_mappings` 是便于 SQL 检查的同步关系表。
两者每次从同一份快照生成，不分别编辑。新 `format_version=1` 不沿用旧 Match 的 schema 编号。

保存先写同目录临时库，关闭 SQLite、同步并校验后原子替换，保留一份 `.wkb.bak`。
短暂排他 `.lock` 与文档 revision 防止并行保存和过期覆盖。不同窗口的测量数据不自动合并。

关闭有修改的文档显示 Save / Discard / Cancel。子窗口只有 Save 才把自身草稿接受到父文档；
其他子草稿不顺带接受。父 Save 接受全部子草稿；父 Discard 放弃全部。路径选择取消或保存失败
不得关闭窗口、丢编辑或标记已保存。子窗口 Save As 为父文档另存为，保持归属。

恢复草稿与正式文件分开，每 30 秒写一次；File → Recover draft 手动恢复且仍标记未保存。
不回放可执行对象，不存图像替代原数据，不逐次滚轮写 SQLite。

## 代价与边界

- 原子完整快照会暂时需要新库与上一版备份的磁盘空间，不采用运行时 WAL 文件作为交换格式。
- SHA-256 与表快照比较有线性成本；当前没有后台多线程保存，避免跨线程读取 Qt 状态。
- 恢复周期内、操作系统拒绝写入或存储设备损坏的草稿无法保证恢复。
- `.lock` 崩溃残留须在所有实例退出后手动清理，不能自动破坏活跃锁。
- 全局设置只提供新文档默认值；文档内色阶和对比关系不再写全局设置，以免 Discard 泄漏配置。
- 打开新容器的软件必须理解对应类型与状态版本；较老软件不支持新容器，应使用 CSV/Excel 交换。

## 验证

行为场景在 `docs/features/workspace_storage.feature`，公开接口测试在
`tests/test_workspace_store.py`、`tests/test_document_storage.py`，旧版本夹具独立维护。
完整回归用 `python run_tests.py`；可重复存储测量用 `python -m benchmarks.benchmark_workspace_store`。
