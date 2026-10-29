# v4.3.5 源码标签快照

2026-10-29，用户授权把当前已验证的 Correlation 优化同步为 GitHub 新标签 `v4.3.5`。该授权更新了此前 P1-A 阶段只保留本地的交付要求。本次只推送标签，不推送 main 或其他分支，不创建 GitHub Release 或安装包。

基线为 `v4.3.4` / `adeafe018ac3ce65b33780e28f398d690b067da4`。本标签包含 Correlation 分批图形创建、旧画面保留、版本取消与关闭保护，以及仅在 Correlation 启用的均匀符号准备优化；拟合、源数据、Workbook/Undo/WKB 协议不变。用户的 `AGENTS.md`、`.vscode/settings.json`、`docs/todos/` 不纳入提交。

本次未修改已验证的生产源码，SHA-256 与最后全量一致：

- `metrology_app/correlation_page.py`：`b6be84c4ffdc822b5efcbaad274089a8448bef33ce63f5d252021ac79cea2877`
- `metrology_app/plotting/curve.py`：`29ce7a5ff2d058334a93e38aa02c4605cb5ac3b40b2ba764bdcee50810edc014`

现有证据：相关专项 170/170；最后一次全量 1,241 项、1,238 通过、3 项耗时失败，1,213.129s。失败为 Map 关闭 361.12ms（<250ms）、Dirty 111.22ms（<100ms）、Writer 编码 308.71ms（<300ms）。关闭后的父源数据与 Writer 全部原始字符串已独立补验，不替代原耗时失败；不能称为全绿。

10k 行、50 个 Raw 参数、24 图的三轮同机中位数：缓存页面完整更新 420.12→205.81ms，首绘完成 1437.38→913.77ms。数组逐值和完整页面逐像素一致。该测量仅包括绘图，完整 Workbook V/Z/Y 总延迟不在其内。三轮普通运行中临时 Peak Working Set 600.33→695.81MiB；关闭后 GC 诊断可回收先前对象，长期资源趋势仍需后续验证。

详细历史验证记录保持原状态，见：

- `docs/plans/p1a-correlation-render-2026-10-29.md`
- `docs/plans/p1a-correlation-retained-2026-10-29.md`
- `docs/validation/p1a-correlation-render-2026-10-29.json`
- `docs/validation/p1a-correlation-retained-2026-10-29.json`

发布前远端只有 main，提交为 `aa5281dd38bbe58688a51b27e86c70635aef7a77`，远端无 `v4.3.5`。推送使用精确 refspec `refs/tags/v4.3.5:refs/tags/v4.3.5`；成功后再核对远端标签及所有分支头。推送结果记录在本地自有 QA 目录，最终以远端核验结果为准。
