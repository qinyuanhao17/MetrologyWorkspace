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

## Task 01：完成

Task 03 checkpoint 为 `d3d57d1c183fc1e9a9722ba5f8e9d9448f334120`。
本任务没有改生产代码；扩展现有 `benchmark_sheet_workflows` 和
`benchmark_raw_paste_undo`，没有重建基准系统。既有 offscreen Correlation、Dirty、
Recovery 与多窗口结果仍按历史批次保留，不重复计算其净收益。

补齐内容：Windows 原生平台、视图暴露断言与同步 viewport paint、同一组视图持续
复用（每轮仅重置目标数据/历史）、排序、搜索、显示/隐藏未参与行、批量勾选和实际
Shift 鼠标连选；另补投影表粘贴/删除/Undo/Redo、真实 Workbook 的数值完成和可见
重绘。每次核对完整源表字符串、源行映射、隐藏行、单命令 Undo/Redo 与分析汇总。
剪贴板可读取的 MIME 格式在测试结束时恢复。输入 WKB 和真实 settings 运行前后
均核对 SHA-256。四个早期导入应用的旧脚本按文件直接执行时现在提前拒绝，提示
改用 `python -m benchmarks...`，避免绕过包入口的持久化隔离；新增入口测试通过。

### 环境与规模

Python 3.11.16、Qt 6.11.0、20 逻辑 CPU，Win32 原生 `windows` 平台；系统报告
build 26200，主屏逻辑 2048×1152、DPR 1.25、约 59.95 Hz，Fusion 与应用字体。
所有性能进程顺序运行，没有与测试、profile 或其他基准并行。

- 4 列确定性字符串 fixture：1k/10k/100k，每档 10 轮，同一组视图，30 轮通过。
- 真实 NOVA Raw（7,731×33）的切片/重复：1k/10k/100k，每档 3 轮，9 轮通过。
  100k 是重复的实际字符串负载，不冒充真实采集的 100k 独立 Workbook 分析。
- 反向隔行投影编辑补测：4 列三档、33 列 100k 各 1 次全部通过；这是规模与正确性
  验证，单次分位数没有长尾统计意义。
- 真实 Workbook 7,731×33：原生单格和整表 paste/undo 各 5 次，另各测连续五次 Undo
  一次，完整 Raw 与分析 summary 均一致，源文件哈希不变。

全量回归 **1,053/1,053 通过，352.077 s**，日志
`.cache/p0-audit/sol-task01-full.log`；新增投影基准随后通过真实原生操作验证。
生产代码与 Task 03 checkpoint 相同。

### 原生基线（不是本任务带来的速度提升）

| 100k 行操作 | 4 列 P50/P95 ms | NOVA 33 列 P50/P95 ms |
| --- | --- | --- |
| Ctrl+A | 11.89 / 773.75 | 17.80 / 6402.97 |
| Ctrl+C | 167.35 / 201.57 | 981.93 / 983.04 |
| Ctrl+V | 1352.03 / 1579.70 | 11470.66 / 12208.01 |
| Undo | 143.45 / 194.38 | 1284.55 / 1291.25 |
| Redo | 154.96 / 163.38 | 1425.09 / 1438.94 |
| Delete | 365.35 / 402.59 | 3739.62 / 3783.36 |
| 倒序隔行投影复制 | 189.79 / 203.24 | 1204.33 / 1204.40 |
| Die Seq 稳定降序 | 49.64 / 51.87 | 49.78 / 56.18 |
| 全表搜索 | 59.80 / 61.11 | 425.23 / 427.91 |
| Shift 取消勾选范围 | 4135.41 / 4494.45 | 11934.28 / 12214.85 |

CPU、Qt max gap、RSS/private/累计进程 peak 和全部小规模操作见已提交的
`docs/validation/p0-native-baseline-2026-10-24.json`；原始逐轮数据保留于
`.cache/p0-audit/task01-native-{repeated,nova-wide}.json`。4 列进程累计 peak
611.58 MiB，33 列 2783.83 MiB，含建模、Undo、缓存及首次窗口准备，不能解释为
单操作独占分配。两批 P95 为 nearest-rank，10 或 3 个样本时等于最大值。

4 列 100k Ctrl+A 首轮 773.75 ms、末轮 11.89 ms；Shift 取消首轮 4142.51 ms、
末轮 4193.42 ms。相同 Shift 事件结束后的 RSS 由 557.00→584.01 MiB；paste
结束后由 549.84→554.40 MiB。预热/分配器保留与潜在长期增长不能凭 10 轮区分，
不宣称无泄漏。首次全选与宽表粘贴仍是未解决的原生长停顿。

| 真实 Workbook 操作 | 回调 P50 ms | 数值完成 P50 ms | 可见重绘 P50 ms | Qt gap P95 ms |
| --- | ---: | ---: | ---: | ---: |
| 单格 paste | 26.69 | 407.57 | 495.77 | 273.03 |
| 单格 Undo | 19.68 | 408.74 | 495.94 | 315.58 |
| 整表 paste | 625.35 | 859.44 | 944.54 | 659.30 |
| 整表 Undo | 36.94 | 442.49 | 527.70 | 344.96 |

主 Workbook 的峰值分别为 813.10、838.53 MiB。连续五次 Undo 的可见完成耗时
638.49、604.95 ms（各仅一次）。Qt 可见窗口/同步 paint 与事件循环心跳已测，
不把它当作 DWM/显示器呈现 FPS，也不与历史 offscreen 4 列数据直接相减。

### 复现命令

沿用前文隔离 TEMP，`$py` 指向已核验的 conda Python；`--scratch` 使用独立目录。

```powershell
& $py -m benchmarks.benchmark_sheet_workflows --platform windows --rows 1000 10000 100000 --count 10 --reuse-views --interactions --output .cache/p0-audit/task01-native-repeated.json
& $py -m benchmarks.benchmark_sheet_workflows --platform windows --wkb .cache/p0-audit/input/nova.wkb --rows 1000 10000 100000 --count 3 --reuse-views --interactions --output .cache/p0-audit/task01-native-nova-wide.json
& $py -m benchmarks.benchmark_sheet_workflows --platform windows --rows 1000 10000 100000 --count 1 --projected-edits --output .cache/p0-audit/task01-projected-native.json
& $py -m benchmarks.benchmark_sheet_workflows --platform windows --wkb .cache/p0-audit/input/nova.wkb --rows 100000 --count 1 --projected-edits --output .cache/p0-audit/task01-projected-nova-wide.json
& $py -m benchmarks.benchmark_raw_paste_undo --code-root . --scratch .cache/p0-audit/task01-workbook-cell --wkb .cache/p0-audit/input/nova.wkb --platform windows --kind cell --count 5 --burst --output .cache/p0-audit/task01-workbook-cell.json
& $py -m benchmarks.benchmark_raw_paste_undo --code-root . --scratch .cache/p0-audit/task01-workbook-column --wkb .cache/p0-audit/input/nova.wkb --platform windows --kind column --count 5 --burst --output .cache/p0-audit/task01-workbook-column.json
```

`--profile-actions` 单独采集 profile，不能把插桩耗时混入上面的基线。

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
