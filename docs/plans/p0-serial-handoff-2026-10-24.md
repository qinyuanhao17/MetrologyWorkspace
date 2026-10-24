# P0 串行接手：Task 03 → 01 → 06

## 接手范围

同一目录、同一分支 `codex/v4-dev2`，没有创建 worktree、重置 tag 或覆盖既有成果。
接手现场已保存为 `bec21bb2c62ed33b2eb2c1942fd3262574563e3f`，该提交保留已有
P0、地图 hover、导出布局与样式等工作；这些不计为本阶段新实现。用户的两份 Excel
未入提交。后续仅执行 Task 03、01、06，完成后停止，不开始 07、08、09。

## Task 03：完成

原日志 `full-dirty-2026-10-24.log` 实际已结束：1,041/1,041，587.828 s。
交接中的“停在 779/1037”已经过时。但其后接手源码又增加地图/导出工作，故没有
把历史结果冒充最新验证。

接手源码全量首次：1,052 项，4 failures，357.832 s，日志
`.cache/p0-audit/sol-task03-full.log`。四项失败分别是旧 Radius 30 cm 高度断言
（2 项）与旧禁止 hover 断言（2 项），与接手前
`map-hover-export-fixes-2026-10-24.md` 及新 hover/同高测试记录的契约冲突。
只同步四处测试：Map/Radius 同为每行 8 cm，面板接受 hover；锚点、宽高比、
源数据不变、图像子项不拦截、禁止独立鼠标导航等断言保留。没有更改任何生产
Dirty、Recovery、WKB、多窗口、地图或导出实现，没有放宽性能阈值。

四项单独复测 4/4 通过；随后当前源码完整回归 **1,052/1,052 通过，352.311 s**，
日志 `.cache/p0-audit/sol-task03-full-final.log`。现有精确 JSON fallback 原样保留，
包括 nested/NumPy/大整数/非法数值/循环/类型及键顺序校验，Card/Group/绘图状态、
源表身份、Dirty/Clean、Undo/Redo、保存取消和 Recovery 所有权均由原套件验证。

测试使用 conda `metrology-workspace` Python、OneDrive 外独立 TEMP、隔离 settings/
recovery/reminders/MPL 目录及已有 `.cache/p0-audit/ocr-deps`，不改 conda 环境。
原 `os.link` 保护用例在允许临时硬链接的测试权限下通过。

复用现有 Dirty 基准对当前代码再测 8 场景 × 30 次，240 次均通过：Clean
P50/P95 为 50.36/58.97 ms，Qt gap P95 59.33 ms；标题检查 P50 50.04 ms，
Raw Undo P50 50.04 ms，修改 baseline 最后一条记录 P50 50.01 ms。
与历史优化后 49.83 ms 接近；原 88.75→49.83 ms 的前后结论保留为历史对照，
不把不同批次直接相减来声称新的净收益。JSON 与日志为
`.cache/p0-audit/sol-task03-dirty-current.{json,log}`。结构变化仍回退 JSON，未略过
Mapping 重新勾选后保留的 UI 状态差异。

本阶段保护基准（与历史运行不同，以接手时实际文件为准）：

| 文件 | SHA-256 |
| --- | --- |
| config/settings.yaml | 44dc79ca55747eaa3be9b94e7650cd9663275c7c804aae7d93ef0a3ee8d69191 |
| 原始 NOVA WKB | fbe22da2a55571b136a1f3e17db1f69284c391e9a2fac86019c5abb919336b4f |
| asdf.xlsx | 24bb76f47f1aa7b164f42827881ea6c1820a460709372e8fa6c37f2dbdc17f36 |
| matching-matplotlib.xlsx | 419a3ad6b0d98912ea989a38808dc7e73fdb4b978e88c923a71339c03b6a9f3a |

最新全量后四份文件哈希均相同。

## Task 01：待继续

既有基准已覆盖 offscreen 表格 1k/10k/100k、恢复、Dirty、多窗口控件、CPU/
RSS/private/累计 peak。接下来仅补原生 Windows GUI、持续复用视图、多次操作趋势、
更宽的真实 NOVA 表以及排序/筛选/隐藏行/批量操作的缺口，复用现有 benchmark。

## Task 06：待继续

保留已有 100k paste 764→605 ms、delete 531→379 ms 的修改，不重复优化。
待 Task 01 checkpoint 完成后，先 profile 尚未验收的交互，再选择局部修改。

## 尚未接手的后续任务

- 07：同 stage 0/1/3/5 命名窗口的 Raw/Card/Mapping 同步矩阵、独立草稿不覆盖、
  prepare/sync/draw 的主成本与父子接受顺序。
- 08：Correlation 散点以外的 Trend/Dynamic/Map 各页面 prepare/render/layout
  分段、原生 GUI 缩放/重绘、数值/NaN gap/色标/轴/导出语义等价和失效任务发布。
  接手前地图/导出工作保留，但不视为本阶段新开展 Task 08。
- 09：热点与所有权稳定后的有限纯职责提取、清晰接口、独立测试与回滚；不做目录重排。
