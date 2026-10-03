# ADR 0003：分类文档后缀、明确保存归属与独立副本

- 状态：Accepted，本地实现，不同步 GitHub
- 日期：2026-10-03
- 细化 ADR 0002；统一 SQLite 容器仍为 format_version=1。

## 决策

Match 保留 `.wkb`，独立 Map/Radius 使用 `.wmap`，Dynamic `.wdyn`，Correlation/Trend `.wct`。
内部类型决定路由；旧独立 `.wkb` 首次正式保存必须显式另存规范后缀，保留原件。

子窗口 Ctrl+S 保存本 scope 加父当前数据/公共设置；父 Ctrl+S 接受全部打开及恢复中尚未打开的草稿。
先构建候选快照，写盘成功后再接受；保存期间的新编辑仍 dirty。
子窗口移除 Save As 和 Ctrl+Shift+S，提供 Export Standalone Copy 和 Show Match Workbook。
副本物化实际数据及继承设置，原路径、角色、dirty 和基准不变，不提供双向同步。

每个 Match 只有一份聚合恢复文件，记录父正式基准、父当前值、各子基准和未接受草稿。
恢复专用 scope 的 state_version=2、payload_version=2；正式文件不携带恢复表。
旧恢复没有可靠基准时先整份另存，不能猜测子窗口局部 Discard 的依据。
共享第二 Y 轴仅父级为权威，子局部放弃不回滚公共字段。

关闭仍为 Save/Discard/Cancel。应用退出先收集所有决定，再完成必要保存，最后才执行 Discard/销毁。
多个独立文件各自提交；后续失败不撤回已成功保存的文件，但其他窗口和未执行的 Discard 保留。

## 安全与边界

复用临时 SQLite、完整后缀 `.bak`、排他 `.lock` 和 revision 检查，最终替换前再次复核。
原子替换后锁清理/UI 失败为辅助警告，不把已经提交的文件错误回滚为未保存。
副本和跨文档另存不得覆盖其他打开文档、备份、恢复文件或同文件链接别名。
独立修改的子表不自动覆盖；Use Workbook Data 必须确认，替换仍是待保存的局部草稿。

不改计算、单位、图形算法、Undo 模型；不新装数据库框架，不打包 EXE，不推送 GitHub。

## 验证入口

`tests/test_storage_v2.py`：归属、真实快捷键、当前编辑、三种可编辑副本、失败/关闭/恢复/迁移。
`tests/test_workspace_store.py`：后缀、保真、备份/锁/最终复核、类型与版本拒绝。
`tests/test_document_storage.py` 及既有 Match/绘图测试继续覆盖完整往返及旧格式。
场景文本见 `docs/features/workspace_storage.feature`，实现使用现有 Python unittest，不另装 Cucumber。
