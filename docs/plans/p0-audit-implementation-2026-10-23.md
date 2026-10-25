# v4.2.0 P0 优化实施与验证记录

## 本地进度复核与独立导出续作（2026-10-26）

当前入口已为 v4.3.1 `991431d`，不是旧交接的 `017c10d`。
[本地进度复核](p0-status-reconciliation-2026-10-26.md)确认第 1 项初始化诊断已由
`b3fe61b` 完成，不重复改生产代码；该复核另存文档 checkpoint `e0ad1da`。
本机缺少当时原始 cache/profile 和 NOVA 副本，历史耗时与通过数不冒充本次重测。
本轮不继续性能热点 2-5，也不做 P1/P2 重构。用户追加的 Excel 原生 Die Seq 源
范围需求作为独立局部工作，见[导出续作](native-die-categories-2026-10-26.md)。

## 剩余专项续作：Workbook Undo（2026-10-25）

用户已明确排除主窗口 Tools 中尚未完成的 AutoWeighting Writer，后续不处理它。
本轮接续 `b3fe61b`，只优化完整 Match Workbook Undo 的字符串分类热点，详见
[专项报告](p0-workbook-undo-performance-2026-10-25.md)与
[配对统计](../validation/p0-workbook-undo-performance-2026-10-25.json)。
未新增缓存，混合类型 fallback、Undo/Redo、分析/绘图通知及所有权/存储协议保持。

三组新原生窗口的 100k×33 Raw Undo P50 1471.42→1281.14ms，按键 dispatch
234.30→112.25ms；Final 完整 Undo 1292.97→1190.62ms。10k×30 Raw 完整 Undo
392.08→383.77ms，改善很小。完整撤销和主线程长 gap 仍不合格，**06 保持部分完成**。
前后原生基准各 72 个动作样本通过；开发专项 10/10 通过。
原生单元专项 104 项中 102 项通过，相同两项 Clipboard 动画失败在冻结基线和当前
重测都复现；未放宽断言，未将该既有问题归为已修复。隔离全量 **1,087/1,087
通过，386.218s**；第一次全量仅受沙箱 `os.link` 限制，沙箱外完整重跑通过。
01/07/08 的剩余边界及 09 不额外重构结论不变；不将本次局部收益写成 P0 全部完成。

## 剩余专项第 1 项：新窗口初始化诊断（2026-10-25）

最新结论见[新窗口专项报告](p0-window-initialization-diagnosis-2026-10-25.md)及
[数据摘要](../validation/p0-window-initialization-2026-10-25.json)。上轮保留的几十秒
异常已在 Windows 原生环境复现，原因是基准的裸顶层 SheetView 放大 Qt 6.11 UIA
窗口查找兜底并枚举全表；不是由 Python GC 或本机内存耗尽引起。

同数据/模型/辅助功能仅加普通窗口容器，三次独立进程：10k×30 构造 P50
2089.92→44.70ms，100k×33 为 38180.98→45.57ms。**这是基准夹具修正，不是生产
软件提速声明。** 三个真实排序工作簿下的主界面新窗＋Qt 绘制约 0.14–0.17s；
三个完整恢复的原始 NOVA 下约 0.50–0.58s，仍含 Recent WKB 完整读取和现有绘图成本。
本轮只改 benchmark 和文档，保留九个既有未提交导出文件；不改生产数据所有权、
存储或异步协议。完成本项后停止，未进入 Writer/Workbook Undo、同步或批量编辑优化。
当前现场隔离全量 **1086/1086 通过，739.729s**；原生表格专项两轮共 52 个动作样本
通过。13 个入口文件哈希一致，详细现场范围和小样本限制见专项报告。

## 最新最终审核（2026-10-25）

以[最终质量审查](p0-final-quality-audit-2026-10-25.md)及其
[可复核摘要](../validation/p0-final-quality-audit-2026-10-25.json)为最新状态；
下方“6/9”“7/9”等是历史限定阶段口径，不能作为当前整体验收结论。
本轮复现并修复分页 Wafer Matplotlib Bias % 导出异常，审核后的七个既有导出
文件保存于 `06a9d15a5a2b43f56d4defdd5bb1139d6ce012b1`。全量、原生专项、
三轮冷表格对照、Dirty 和 120 张 Map 精确对照见最新报告。

100k×33 首次 Ctrl+A P50 6698.23→21.47ms；Shift 取消/勾选
7164.91/7166.62→15.33/15.30ms。完整 Workbook Undo 仍约 1.01–1.33s，
Writer Undo 4.22s，五窗 Group/阶段切换 5.88/5.33s，**整体 P0 流畅度不予无保留通过**。
本轮修正了 Workbook-only 基准仍创建三个无关大表的隔离问题；原始初始化异常
和诊断日志保留，多大表组合的初始化表现没有因此被视为已修复。

Task 02–05 在已定义范围内通过复核；01 基础基准完成但瞬时 CPU 峰值/长时等
扩展指标未覆盖；06–08 仍为部分完成；09 架构评估完成且不继续重构。
旧测试确有随既有 All Dies 取消和图像布局变更而删除/替换，不能声称“全部原样保留”；
原性能阈值没有放宽，细目和功能变更归属见最新报告。

## 范围与版本

依据桌面的 `MetrologyWorkspace_v4.2.0_P0_Audit_and_Codex_Tasks.md`。
最初核对的基线为 `3f1af6f3fcfef6e76d2cf6608ad63acc3c66cc79`，即报告固定的 v4.2.0。
它不是后续各阶段的当前 HEAD；实际 checkpoint 以最新 Git 与串行交接记录为准。
原有 `asdf.xlsx`、`matching-matplotlib.xlsx` 保留。此前未提交的成果已在串行接手时
保存到 `bec21bb`（接手现场 checkpoint，包含既有地图/导出修改）；未推送或发布。

本批包含 Task 01 的测试入口隔离与专项基线、Task 02/08 的 Correlation
热点优化、Task 05 的配置安全，以及 Task 07 的同步快照复制优化。
2026-10-24 续作增加 Task 06 的粘贴/删除优化与 Task 04 的 Correlation 恢复捕获优化。
**不代表九项任务或 Task 01 的全场景基线已全部完成。**

截至本轮 Dirty 专项开始：完整验收 3/9（02、04、05），部分完成 4 项
（01、06、07、08），03 已诊断待实现，09 尚未实施。下面逐项记录与总任务计数
分开，避免把一个热点的完成误算成整项全部完成。

**Sol 串行接手更新（2026-10-24）：限定的 03→01→06 三项已完成本阶段验收，当前
6/9 完成（01、02、03、04、05、06）。** Task 07、08 部分完成，09 尚未开始。
Task 06 的极大宽表长停顿仍按实测保留为未解决项，不代表所有场景均流畅。
本阶段仅按 03→01→06 串行推进，完成后停止，详细交接见
[本阶段记录](p0-serial-handoff-2026-10-24.md)。

**Ultra 串行续作（2026-10-24）：Task 08 已完成本阶段低风险范围，7/9 完成；
Task 07 待继续，09 待评估。** 五类页面已分段测量，局部消除 Dynamic Trend
字号重建与 Map/Radius 字幕几何重建。全量 **1,057 项通过，353.931 s**。
实际收益、剩余绘图停顿、数值/导出证据与回滚见
[Ultra 交接](p0-ultra-handoff-2026-10-24.md)。后续按 07→09 串行执行，不修改
数据所有权、generation 或持久化协议。

Task 07 续作已完成 0/1/3/5 命名窗口原生矩阵、五窗口混合覆盖及独立草稿保护，
仅消除同 schema 时无效的 rename 整表转换。当前工作区全量 **1,059 项通过，
359.544s**。较大的 Group context/事务发布优化按用户要求仅记录方案；五窗口
仍有数秒停顿，不视为全面流畅。本轮另收到大表冷操作与 Undo 的新增要求，将在
Task 07 独立 checkpoint 后单独处理，再评估 Task 09，详见 Ultra 交接。

**2026-10-25 大表新增要求复核：** 原 6.4s Qt gap 不能作为合格结果。原生辅助功能
开启、无 selection 预热的 100k×33 冷操作中，Ctrl+A 6332→22ms，Shift 取消/勾选
7361/7213→15/18ms，整表 Delete 后首次 Undo 1556→51ms。完整 Workbook Undo
仍约 1.0–1.4s，Writer 极限表格 Undo 12.7→4.8s，**新增的“所有表格均流畅”要求尚未
全部验收**，不能把按键返回等同完整刷新。修改、分位数、CPU/内存、数值与状态验证、
残留及回滚见[表格补充交接](p0-table-cold-handoff-2026-10-25.md)。Task 09 将在此项
checkpoint 后评估，仍不改 Dirty/Recovery/多窗口所有权协议。

此补充最终全量 **1,083/1,083 通过，362.503s**（`ultra-table-final-full.log`）。
首次运行的一个新增计时测试生命周期问题、独立进程旧实现失败和当前通过证据均保留在
补充交接中，未提高原阈值、删除断言或跳过必要刷新。

**Task 09 已在表格 checkpoint `078eb99d145b40e5719b5f9a46fd9d802471c211` 后完成
评估。** 当前纯输入 seam 已可独立测试；同步/snapshot 提取涉及所有权和事务顺序，
无明确收益的文件搬动不实施。本项仅文档，不继续改生产代码。Task 01–09 最新状态、
所有本轮 SHA、性能/测试、回滚及 Astra 待审缺口统一见
[最终评估与交接](p0-task09-assessment-2026-10-25.md)。停止本阶段开发；不能称九项
已全部达到最终流畅度目标。

## 证据与修改

| 结论 | 证据 | 修改 |
| --- | --- | --- |
| 测试入口可能沿用真实配置路径，且并发进程共用持久化目录 | 原 `isolate_settings()` 使用 `setdefault` 和固定目录；新增隔离测试在原代码失败 | 每次运行创建独立目录，覆盖 settings/recovery/reminders/MPL 路径；主入口退出时清理自己创建的目录 |
| 当前机器未复现报告的原始 2 秒超时 | 修改前 30 个独立进程全部通过原测试 | 保留 `<2.000 s` 及原测试全部断言，不宣称复现/解决同一机器上的原发布失败 |
| 来源感知 Correlation 散点在布局、纵向平移/缩放中重复提交未变数据 | cProfile 中 `ScatterPlotItem.updateSpots` 累计约 598 ms；新用例中 6 图各平移 20 次耗时 942.57 ms，超过 250 ms 门槛 | `CorrelationPage.render_interactive()` 复用 Trend 已有的 `ResponsivePlotDataItem`，不新增缓存策略或后台计算 |
| 正常文档的 Trend overlay 已有全局写入保护 | `CorrelationWindow.__init__()` 设置 `document_scoped=True`；`SequencePage._persist_overlay()` 提前返回 | 不把报告中的疑点直接作为已复现 Bug，不重复修复 |

绘图修改仅改变来源感知 Correlation 的散点项构建。保持散点大小、颜色、图例、
原始点、拟合线、轴交换和动态范围保护；未改拟合、插值、WKB schema、导出算法。

## 30 轮恢复性能对照

同一台 Windows、同一 conda Python 3.11.16、PyQt/Qt 6.11.0、20 逻辑 CPU，
Qt `offscreen`。本地不存在报告发布时使用的 `.venv`，因此不得直接把本结果与
发布记录的 2.086 秒相比。前后两批顺序运行，没有并行运行其他验证任务。

每轮为新 Python 进程，执行未改动的原恢复回归用例：6,000 Raw 行、29 个未映射列、
300 wafer × 20 die、两个 mapping；先准备 managed child，再同步完整恢复已保存绘图。
每轮仍校验 6 fits、各 fit 的 6,000 点、斜率/截距、12,000 Trend positions、
页面/选择与 Raw 原始表。属于“已准备窗口的恢复”测量，不是应用冷启动。

| 指标 | 修改前 | 修改后 | 解释 |
| --- | ---: | ---: | --- |
| restore P50 | 716.52 ms | 487.35 ms | 降低约 32.0% |
| restore P95 | 761.09 ms | 519.07 ms | 降低约 31.8% |
| restore 最慢 | 804.87 ms | 525.31 ms | 30/30 均严格小于 2 秒 |
| CPU time P50 | 718.75 ms | 484.38 ms | 进程 CPU 时间 |
| Qt gap P50 | 486.23 ms | 296.02 ms | 10 ms 心跳，含操作起止边界 |
| Qt gap P95 | 524.38 ms | 316.40 ms | 降低约 39.7% |
| Qt gap 最大值 | 531.83 ms | 318.46 ms | 仍存在同步阻塞，不等于无卡顿 |
| restore 后 working set P50 | 485,263,360 B | 485,298,176 B | 无有意义的内存下降 |
| 进程峰值 working set 最大值 | 485,875,712 B | 486,092,800 B | 包含 fixture 准备，不是操作独占峰值 |

P95 为 30 个样本的 nearest-rank 分位数；不是置信上界。离屏耗时不能代替
Windows 实际滚动帧率、显示器 DPI/电源模式对照或 EXE 测试。

基准 JSON：`.cache/p0-audit/before.json`、`after.json`；每轮独立 JSON 同目录。
原 profiler：`.cache/p0-audit/restore.prof`、`restore-profile.txt`。
插桩耗时约 2.18 秒，**不用于与未插桩基线比较或判断 2 秒验收**。

两批性能基准各自的真实 settings 前后 SHA-256 均为：
`97150d0e208a85a3780d12c9ffe162baf89add19955881429130df0c09d523fc`。
恢复 fixture 在内存生成，不打开或保存用户 WKB。

## 运行方法与测试

```powershell
$py = 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe'
$scratch = Join-Path (Get-Location) '.cache/p0-audit'
New-Item -ItemType Directory -Force "$scratch/temp" | Out-Null
$env:TEMP = (Resolve-Path "$scratch/temp").Path
$env:TMP = $env:TEMP
& $py -X utf8 -m benchmarks.benchmark_correlation_restore --count 30 --output "$scratch/after.json"
& $py -X utf8 run_tests.py tests.test_test_environment -v
& $py -X utf8 run_tests.py tests.test_performance_regressions.WorkbookPerformanceTests.test_source_correlation_pan_keeps_every_point_without_rebuilding_scatter -v
& $py -X utf8 run_tests.py
```

测试入口会覆盖外部持久化环境变量；`python -m benchmarks.*` 的包入口也会隔离
settings/recovery/reminders/MPL 路径。部分旧 benchmark 会再指定自己的 scratch；
显式 `--scratch` 必须使用专用目录。直接按文件路径执行旧 benchmark 不受包入口保护。
性能脚本使用 Windows `GetProcessMemoryInfo`，未增加 psutil 等依赖。
重复测量保留原始失败状态；`--profile` 单独使用，不混入普通测量。

已验证：隔离用例原代码失败、修改后通过；新增平移用例原代码失败、修改后通过；
原恢复用例前后各 30/30 通过。使用应用字体初始化后，同一批 6,000 点、相同
视口和平移的原生 PlotDataItem 与优化图元截图逐像素一致，截图 375×312。
证据在 `.cache/p0-audit/render.log`、`native.png`、`optimized.png`。

## YAML 安全与配置归属（Task 05）

`settings.save_settings()` 改为同目录临时文件、flush/fsync、原子 replace；
仅在 replace 成功后发布内存设置。使用 `QLockFile` 协调多个应用实例，
锁内比较上次读取的原始文件字节，发现外部修改即拒绝旧实例写入。
设置对话框另比较用户打开时看到的字段，防止同一进程的其他设置操作使表单过期。
冲突会显示提示、重新加载并保持对话框打开，由用户复核后再次保存。
磁盘失败时不关闭窗口、不应用候选设置；点标签精度也回到实际保存值。

损坏 YAML、非法根结构、无效 UTF-8 可以使用默认值启动，但禁止随后悄悄覆盖
原文件，要求修复文件并重新加载。缺失文件、空文件仍可正常首次保存。
未知键沿用旧行为：不进入有效设置、保存时不保留；未新增字段迁移。
不声称锁能约束不遵守锁协议的外部编辑器；强杀留下的临时文件不会替代正式文件。

| 字段/调用方 | 本次确认的契约 |
| --- | --- |
| theme、recent_wkbs、shell_splitter_sizes、recovery_interval_seconds | 全局偏好；最近文件 helper 先加载再保存；自动保存失败不会破坏旧文件 |
| point_value_decimals | 保留现有全局语义；写入失败回退控件与有效值 |
| resolution、font_size、color_map/range、fill_edge、shared_scale、point_values、measurement_points、scale_bar、contour、point_outline、opacity、min_rsq | 全局默认与现有 WKB 控件快照保持原契约；本次不改 schema 或默认值 |
| trend_overlay、trend_source_overlay | 普通 CorrelationWindow 已有 document_scoped 防护；当前文档修改不写全局、不污染另一个窗口，WCT 保存/重开保留当前值，Discard 不回写全局 |
| smoothing | 仍为全局计算输入；潜在跨环境再现性问题单独记录，不暗中新增 WKB 字段 |

已核对写入入口：`settings_dialog.py`、`plot_page.py` 的色标默认和精度、
`sequence_page.py` 的独立页面 overlay、`shell.py` 的 splitter，以及 settings 内
最近文件 helper。读取入口另包括 Correlation/Trend/Radius/Dynamic、表格主题和 Recovery。

### smoothing 兼容设计（本次不实施 schema 迁移）

当前每次启动 surface job 都读取全局 smoothing；已有 WKB 无法证明历史重算使用了
哪个值。后续设计应让新文档在创建时捕获一个有效值，并让数值计算、屏幕 Draw 与
导出使用同一个文档值。旧文件缺字段时继续采用全局默认，且明确属于兼容回退；
不能猜测历史值或悄悄改变旧文件。字段、schema 版本和“改变当前文档”交互另行设计，
确认后补旧/新文件、保存重开、全局默认变化、Undo/Discard、导出一致性测试。
本次保留现有科学计算语义，只做独立复现实验记录风险。
实验使用固定 3×3 坐标及 9 个非平面数值，60×60 网格、相同有效 mask、关闭
fill_edge，只把 smoothing 从 0 改为 0.06：1,600 个有效网格值改变，最大绝对差
0.0531515655、平均绝对差 0.0145605235（与输入数值同尺度，无推断物理单位）。
说明其确实影响数值，不能当作纯显示偏好。输入与结果在 `smoothing.json`，
复现脚本为 `smoothing_probe.py`（从项目根目录执行其内容）。

新增测试覆盖：replace/fsync 失败保持原文件及内存值；活锁拒绝；第二进程写入
冲突；写入阶段进程强退后的旧文件与死锁恢复；同进程过期对话框；非法配置保护；
旧 overlay、空 source_overlay、色标范围、非法精度及未知键兼容；跨文档 GUI 隔离。

## 多窗口同步（Task 07）

真实只读 NOVA fixture 为 7,731 行 × 33 列，源文件 SHA-256：
`fbe22da2a55571b136a1f3e17db1f69284c391e9a2fac86019c5abb919336b4f`。
原文件只读使用，基准操作在 `.cache/p0-audit/input/nova.wkb` 副本进行，运行后
再次校验源副本 hash。没有保存到输入 WKB。

profile 证实 `_commit_stage_workspace()` 为取得 `.frames` 而复制了完整 Group/UI
状态；插桩中三个 `workspace_snapshot` 累计约 290 ms。本次只把两处立即读取
改为现有 `readonly=True`。frame 原来的独立捕获、baseline 的 deep copy 和
`_workbook_source_frames` 的 deep copy 保留；只读状态不交给后台线程。
没有新增 revision 捷径、没有跳过真实 Mapping/Card/Raw 更新。

使用 `benchmark_workbook_windows --controls --input-controls --mapping-repeats 10`
在同一已准备的 Correlation、Map、Dynamic 窗口场景重复 off/on；前后分开运行。
对照源 `.cache/p0-audit/sync-baseline-source` 与修改后的生产代码只差这两处调用。
P95 为 10 样本 nearest-rank，因此等于最大值，不能当作稳定长尾估计。

| 操作 | 完成 P50 前→后 | 完成 P95 前→后 | Qt gap P95 前→后 |
| --- | --- | --- | --- |
| 取消 Mapping | 650.66 → 555.68 ms | 710.89 → 665.21 ms | 683.27 → 641.75 ms |
| 恢复 Mapping | 887.32 → 829.55 ms | 976.52 → 910.59 ms | 948.54 → 885.35 ms |

CPU P50 分别为 734.38→609.38 ms、945.31→859.38 ms。
证据：`sync-before.log`、`sync-after.log`、`sync-summary.json`。
改进有限，仍有长时间同步阻塞；未完成 0/1/3/5 个同类命名窗口的完整矩阵。

## Dirty、Recovery 与大表诊断（Task 03/04/06）

- Dirty：真实 NOVA 的 30 次精确检查 P50 87.59 ms、P95 92.62 ms。
  五次 profile 中 JSON 编码约 353/439 ms；frame 捕获约 21 ms。
  现有测试明确覆盖 baseline 原地修改、类型与顺序差异、非法状态验证；本次保留
  精确比较，未加入可能漏掉子窗口状态的缓存。见 `dirty-before.log`、`dirty-profile.txt`。
- 自动 Recovery：同 fixture 30 次，重复回调中位 57.12 ms，最大 UI gap 102.21 ms；
  仅首次写文件，后续保持文件不重写。没有把同步 `write_recovery()` 的耗时冒充
  自动回调耗时；未改变后台 snapshot 独占、取消、revision 或发布规则。
  见 `recovery-before.log`；此项只有诊断，没有宣称延迟/内存改善。
- 表格：新增 `benchmark_sheet_workflows`，1k/10k/100k 行 × 4 列，每档 3 次，
  包含固定精度字符串、前导零、空值；实际 Qt Ctrl+A/C/V/Z/Y/Delete，另测
  反向且隔行投影的复制。每次核对完整文本、原模型不变、粘贴一次 Undo 还原、
  Redo/删除后 Undo 恢复。全部 9 轮通过。

| 行数 | 全选 P50 | 复制 P50 | 粘贴 P50 | Undo P50 | Redo P50 | 删除 P50 | 投影复制 P50 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 5.63 | 3.87 | 11.39 | 3.29 | 3.48 | 7.88 | 8.49 |
| 10,000 | 5.78 | 16.25 | 78.86 | 14.84 | 15.82 | 47.83 | 23.63 |
| 100,000 | 5.68 | 156.66 | 777.81 | 138.99 | 153.35 | 528.18 | 189.34 |

单位 ms。100k 粘贴 P95 837.47 ms、最大 Qt gap 831.93 ms；进程峰值约
496 MiB，包含 fixture/历史轮次的累计峰值，不能解读为单操作独占分配。
每档只有 3 样本，P95 等于最大值；这是同进程新视图的基线，不是前后提速证据。
该基准不包含完整 Workbook 分析订阅链，也不代表 33 列或 100k 真实工程文件。
完整各轮 wall/CPU/gap/RSS/private/peak 见 `sheet-baseline.json`。

```powershell
& $py -X utf8 -m benchmarks.benchmark_sheet_workflows --count 3 --output "$scratch/sheet-baseline.json"
& $py -X utf8 -m benchmarks.benchmark_workbook_windows --wkb "$scratch/input/nova.wkb" --controls --input-controls --mapping-repeats 10
```

## 回归记录

- 最终相关测试：72/72 通过（配置、文档、命名窗口、关闭、快照相等、Recovery 共享、入口隔离）。
- 前一轮 Correlation/窗口/文档集成：121/121 通过。
- 首轮全量：1,015 项，1,010 通过；2 failures + 3 errors。四项 OCR 导入/流程
  错误来自当前 conda 缺失 cv2 等声明依赖；一项 `os.link` 受沙箱权限限制。
  同样五项在原始固定 HEAD 的独立解压源码中复现，见 `baseline-failures.log`。
  OCR 模块导入失败导致整模块计为一个失败项，所以不能与发布环境的测试总数直接比较。
- 最新生产改动后的全量：1,027 项 / 385.507 s，3 failures + 6 errors。除上述
  五项外，三项配置/WKB 原子 replace 遇到 Windows WinError 5，另有一次关闭保存
  未成功。四项在 OneDrive 外的独立临时目录复测全部通过；硬链接保护在解除沙箱
  限制后 1/1 通过。没有删除失败测试或改变断言，不能凭复测称这轮全量通过。
- OCR 固定依赖及缺失的传递依赖只安装到 `.cache/p0-audit/ocr-deps`，不修改 conda
  环境。OCR 相关 18/18 复测通过，包括真实模型且禁止联网/下载的识别契约。
  隔离包清单在 `.cache/p0-audit/ocr-test-dependencies.txt`；这是针对测试补充的
  包集合，不是重新打包的完整运行环境（humanfriendly 的 Windows 交互式终端依赖
  pyreadline3 未安装，当前测试未使用该终端功能）。采用 OneDrive 外独立 TEMP
  与该 PYTHONPATH、解除沙箱硬链接限制后，最终全量 **1,032/1,032 通过，
  374.869 s**，日志为 `.cache/p0-audit/final-full-isolated.log`。
  测试数恢复增加 5 项是 OCR 模块由一次导入错误恢复为六个真实测试；没有删除、
  跳过或放宽失败测试。最终原配置与原始 NOVA 文件 SHA-256 仍与上述测量值相同。

最终验收环境命令（PowerShell 当前进程生效，未修改系统环境）：

```powershell
$env:TEMP = 'C:\Users\Yuanhao Qin\.codex\visualizations\2026\10\23\01a16668-d082-7c30-b9ff-82f7720b87ee\test-temp'
$env:TMP = $env:TEMP
$env:PYTHONPATH = (Resolve-Path '.cache/p0-audit/ocr-deps').Path
& $py -X utf8 run_tests.py
```

## 2026-10-24 续作：Sheet 粘贴和删除（Task 06）

先用单独的 cProfile 运行确认热点，再做无 profile 的顺序前后对照。100k 行
粘贴中，原路径在 paste、edit、CellEdit 三处重复读取/筛选旧值，且为约 38 万
个单元格重复读取仅四个列名；Delete 的单矩形选区为每个单元格创建 `any()`
生成器。profile 的耗时含插桩开销，不用于下面的速度比较。

最小修改：`SheetModel.edit()` 返回只读的 Undo 原值映射，paste 复用它，列名
每列只读取一次；空锁集合无需逐格查列锁；Delete 单矩形直接判断边界，多选区
及自定义 flags/投影路径保留。`OrderModel` 透传只读返回值，仍仅允许编辑第一列。
回执仍检查实际执行后的值，没有减少 changed/dataChanged 或改动历史命令数。

在原公开 edit 接口补充原值不可修改、锁列/no-op 不入回执、Undo/Redo 的测试：
先确认旧代码因无返回值而失败，再实现；另覆盖 Order 的派生列、多选区删除和
锁定元数据。相关表格、回执、锁列、边界、批量加载和分组测试 **93/93 通过**。
独立静态审查未发现调用者、投影映射或 Undo 语义回归。

冻结本轮开始的生产包于 `.cache/p0-audit/sheet-baseline-source`，同一 conda、
offscreen Qt、数据和操作次序，1k/10k/100k × 4 列每档 10 次，前后各独立进程。
合计 60 轮均核对完整字符串、原模型不变、一次 Undo/Redo，以及倒序隔行投影
复制。保留前导零、长小数尾零和空值，不做数值转换。

| 行数 / 操作 | 完成 P50 前→后 (ms) | 完成 P95 前→后 (ms) | Qt gap P95 前→后 (ms) |
| --- | --- | --- | --- |
| 1k / paste | 11.11 → 9.70 | 22.55 → 19.44 | 17.37 → 14.48 |
| 1k / delete | 7.68 → 6.08 | 11.19 → 6.38 | 11.19 → 6.38 |
| 10k / paste | 70.21 → 55.39 | 83.76 → 65.79 | 78.84 → 60.72 |
| 10k / delete | 48.22 → 31.34 | 49.38 → 45.43 | 44.01 → 41.77 |
| 100k / paste | 764.50 → 604.84 | 799.51 → 631.29 | 794.53 → 626.13 |
| 100k / delete | 530.87 → 379.48 | 554.00 → 426.05 | 548.64 → 420.52 |

100k 粘贴 P50 降低 20.9%，删除降低 28.5%。CPU P50 分别为
765.63→593.75 ms、531.25→375.00 ms；CPU P95 为 781.25→625.00 ms、
562.50→406.25 ms。粘贴后 RSS P50 408.21→408.61 MiB，private P50
982.22→982.57 MiB；删除后 RSS 418.81→420.21 MiB，private
993.29→994.98 MiB。进程累计 peak 510.92→511.44 MiB，**没有证据表明内存下降**。

未改的 100k copy P50 156.35→159.46 ms，Undo 137.81→140.85 ms，
Redo 151.23→152.10 ms；不能把所有操作都称为提速。每档仅 10 样本，P95
为最大值；基准为独立 Sheet，不包含 Workbook 分析订阅链，也不是可见桌面 FPS。
100k 粘贴仍有约 626 ms 的最长阻塞，尚未达到完全流畅。

证据：`sheet-profile-100000-0-paste.profile.txt`、
`sheet-profile-100000-0-delete.profile.txt`、`sheet-before.json`、`sheet-after.json`。
复现命令（同上 TEMP 设置，逐个运行）：

```powershell
& $py -X utf8 -m benchmarks.benchmark_sheet_workflows --count 10 --code-root .cache/p0-audit/sheet-baseline-source --output .cache/p0-audit/sheet-before.json
& $py -X utf8 -m benchmarks.benchmark_sheet_workflows --count 10 --output .cache/p0-audit/sheet-after.json
```

## 2026-10-24 续作：Recovery 捕获（Task 04）

Correlation 的 `MainWindow.workspace_snapshot()` 原先先复制 Raw 为 input_data，
再覆盖 frames 并重新复制同一表。现改为类型分支，只捕获需要的表。自动恢复的
独立/managed Correlation 原先先 deepcopy `_match_groups`/`_local_view`，随后
`freeze_snapshot()` 再复制；现在借用 readonly 状态并在当前 GUI 调用栈中立即
冻结。没有事件循环或异步间隙；worker 仍然只收到独占输入，baseline 仍独立冻结。
AutoWeighting 等不支持 readonly 的窗口保留原调用。格式、单 writer、取消、
revision 校验、发布和原子替换不变。

新增两项测试通过真实 `request_recovery()` 和磁盘恢复文件验证：worker 尚未读
输入前用 Event 阻塞；捕获后修改 Raw、嵌套筛选、grouping record ID 和 accepted
baseline。第一次恢复严格等于捕获时 A，第二次严格等于最新 B，原正式文件 hash
不变。独立 Correlation 和 Workbook managed Correlation 均通过。
配置/文档生命周期、快照相等和 Recovery 共享等相关集共 67 项，66 通过；唯一
error 是沙箱禁止测试创建 `os.link`。随后采用已验证的沙箱外测试权限运行全量，
该项通过；没有改动其断言或跳过测试。

真实 NOVA 7,731 × 33，0/1/3/5 个有独立 Raw 改动的命名 Correlation 窗口，每档
10 次自动恢复，修改前后各独立进程，所有运行顺序执行。每轮等待后台完成；
最终核对父文档修改、每个子窗口完整快照、源文件/真实 settings hash。
前后每档均只写入一次恢复文件，重复请求不重写，恢复文件大小分别相等。

| 子窗口数 | 捕获 P50 前→后 (ms) | 捕获 P95 前→后 (ms) | 整周期 Qt gap P95 前→后 (ms) | 完成 P50 前→后 (ms) |
| ---: | --- | --- | --- | --- |
| 0 | 69.19 → 70.46 | 94.50 → 94.98 | 101.02 → 111.20 | 296.63 → 299.43 |
| 1 | 105.32 → 76.72 | 162.80 → 128.27 | 275.45 → 161.95 | 442.53 → 403.44 |
| 3 | 262.95 → 155.32 | 284.85 → 193.53 | 302.10 → 294.96 | 790.91 → 695.01 |
| 5 | 341.78 → 202.33 | 388.40 → 251.69 | 405.80 → 369.77 | 1077.81 → 936.88 |

5 窗口捕获 P50 降低 40.8%，但整周期 gap P95 只降低约 8.9%；未涉及的零子窗口
对照无改善。上述 P95 包括首次文件写入，10 样本下等于最大值，不能把捕获收益
套用到整个后台写入周期或所有文档类型。

| 子窗口数 | 捕获 CPU P50 前→后 (ms) | 捕获后 RSS P50 前→后 (MiB) | private P50 前→后 (MiB) | 进程累计 peak 前→后 (MiB) |
| ---: | --- | --- | --- | --- |
| 0 | 70.31 → 70.31 | 539.58 → 540.21 | 1110.64 → 1111.48 | 570.99 → 572.13 |
| 1 | 109.38 → 85.94 | 734.56 → 733.83 | 1905.28 → 1904.67 | 810.00 → 802.29 |
| 3 | 265.63 → 148.44 | 947.85 → 946.99 | 2119.80 → 2119.38 | 1091.87 → 1088.34 |
| 5 | 335.94 → 195.31 | 1161.98 → 1158.70 | 2334.41 → 2331.61 | 1379.10 → 1375.11 |

进程内存含建窗和后台工作，峰值只小幅波动，**不宣称显著降低内存**。
证据为 `recovery-{0,1,3,5}-{before,after}.log` 与
`recovery-window-summary.json`。基准已加入 code-root、子窗口数、CPU/RSS/private/
peak 和完整子状态核验。单独 `--capture-profile` 仅分析 GUI 捕获，不冒充 worker
profile，也不纳入无插桩的对照指标。

3 子窗口的单独 GUI profile（重复请求，含插桩）：Correlation snapshot 累计
396→14 ms；8 次 `freeze_snapshot` 保持 315→321 ms，冻结的次数与状态节点数
不变；`document_frame` 从 12 次降到 9 次。证据
`recovery-capture-before-1.txt`、`recovery-capture-after-1.txt` 支持节省来自重复
deepcopy 和被丢弃的 Raw 副本，而非跳过冻结。没有用该 profile 推断后台线程成本。

```powershell
# N 依次为 0、1、3、5；前后顺序运行，沿用本记录的隔离 TEMP。
& $py -X utf8 -m benchmarks.benchmark_workbook_recovery --wkb .cache/p0-audit/input/nova.wkb --automatic --iterations 10 --correlation-windows N --code-root .cache/p0-audit/sheet-baseline-source
& $py -X utf8 -m benchmarks.benchmark_workbook_recovery --wkb .cache/p0-audit/input/nova.wkb --automatic --iterations 10 --correlation-windows N
```

本轮覆盖自动恢复，未声称完成多窗口 Mapping/Raw/Card 同步的 0/1/3/5 矩阵。

## 2026-10-24 最终回归

本轮所有生产修改后，执行仓库要求的 `python run_tests.py`：
**1,037/1,037 通过，375.309 s，无失败、无错误**。沿用上文 OneDrive 外 TEMP、
独立 settings/recovery/reminders、隔离 OCR 依赖和允许临时硬链接的测试权限。
日志：`.cache/p0-audit/full-2026-10-24.log`。相比上一轮新增 3 项表格行为测试
与 2 项恢复所有权测试。原性能阈值、绘图数值/点数、文件保护与失败断言未放宽。

最终 `git diff --check` 通过。再次确认真实 settings SHA-256 为
`97150d0e208a85a3780d12c9ffe162baf89add19955881429130df0c09d523fc`，原始 NOVA
为 `fbe22da2a55571b136a1f3e17db1f69284c391e9a2fac86019c5abb919336b4f`，均与
本轮测量前一致。没有修改原始用户 Excel 文件，没有提交、推送或发布。

## 2026-10-24 续作：精确 Dirty 比较（Task 03）

profile 已确认真实 NOVA 的状态 JSON 约 10.96 M 字符，编码占五次 Dirty 检查
的 353/439 ms。先测去除格式空格的方案：单次编码中位 36.12→35.92 ms，
只有约 0.6% 差异，未纳入生产修改。

最终修改仅在 `same_snapshot()` 内增加普通 JSON 状态的逐层比较。它遍历全部
值（即使已发现差异），保留字典顺序、bool/int/float 区分、负零及原始字符串。
遇到结构变化、非字符串键、NumPy/其他特殊类型、大整数、非有限数或递归异常，
仍使用原 `_comparison_json()` 判等及校验。不缓存 baseline，不依赖单一 Undo
revision，不省略 frame.equals，正式保存的 JSON 与 WKB 格式没有变化。

第一版仅加速相同状态，会让末尾字段变化触发第二遍编码。新增性能断言复现
106 ms 的退化后，改为在同一遍中验证普通状态并返回精确结果。最终保留未变
和末尾变更两种 `<60 ms` 断言；原代码的未变情况为 91–93 ms，未放宽门槛。

新增保护包括：提前出现差异不能漏检后面的非法值、500 组固定随机种子的嵌套
状态与原编码器结果/异常类型对照、Unicode/代理字符、NumPy 值、大整数和编码
位数限制。真实窗口另验证 Card、参数筛选、R² 控件变化为 Dirty，精确回退为
Clean，纯焦点改变保持 Clean，accepted baseline 不被检查改写。既有 managed
Correlation/Undo、Recovery 独占、Save/Discard/取消等相关 47 项通过；新增 GUI
状态检查与快照测试 7 项通过。最终全量结果另记录。

新增 `benchmark_dirty_checks`：真实 NOVA，8 类状态，每类前后各 30 次，合计
480 次；单进程复用窗口，前后顺序独立运行，计时范围仅为状态检查，不包含前置
编辑/分析。旧文件首次编辑会重排部分 group metadata，因此在测量前执行相同
的编辑/Undo 预热并确认完整源表字符串不变，再建立基线。Mapping 重新勾选仍可能
保留绘图/选择状态变化；其期望值由原 JSON 编码器独立计算，本 fixture 前后均为
Dirty，没有为了显示 Clean 而忽略这些差异。

| 场景 | Dirty | P50 前→后 (ms) | P95 前→后 (ms) | Qt gap P95 前→后 (ms) |
| --- | --- | --- | --- | --- |
| 未修改 | 否 | 88.75 → 49.83 | 98.16 → 58.33 | 98.31 → 58.44 |
| 未修改，更新标题 | 否 | 88.63 → 49.76 | 90.79 → 57.66 | 90.88 → 57.76 |
| Raw 修改 | 是 | 13.45 → 13.23 | 21.43 → 20.83 | 21.54 → 21.31 |
| Raw Undo | 否 | 89.21 → 49.75 | 98.00 → 58.45 | 98.12 → 58.58 |
| 取消 Mapping | 是 | 88.87 → 89.65 | 91.24 → 97.32 | 95.08 → 97.49 |
| Mapping 重新勾选 | 是 | 83.08 → 49.95 | 84.55 → 56.90 | 86.54 → 60.59 |
| 修改 baseline 最后一条记录 | 是 | 83.66 → 50.57 | 89.25 → 58.88 | 89.40 → 59.00 |
| 恢复 baseline 原值 | 否 | 85.14 → 50.20 | 89.79 → 57.32 | 89.93 → 57.45 |

未修改检查 P50 降低 43.9%，CPU P50 93.75→46.88 ms；RSS P50
515.56→512.63 MiB，private 1086.05→1083.12 MiB，整个过程累计 peak
554.51→549.54 MiB。内存变化较小，不宣称显著降低内存。取消 Mapping 因结构变化
回退原编码，未改善，P95 本次略高；Raw 修改沿用 frame 不同的提前退出路径。

证据：`dirty-checks-before.json`、`dirty-checks-after.json`、`dirty-focused.log`。
冻结源码为 `.cache/p0-audit/dirty-baseline-source`。复现（同上隔离环境，逐个运行）：

该冻结目录也保留了上一批 Sheet/Recovery 优化后的生产包；前面的性能数据是
当时批次的结果，不将本次 Dirty 的额外收益计入前面的历史指标。

```powershell
& $py -X utf8 -m benchmarks.benchmark_dirty_checks --wkb .cache/p0-audit/input/nova.wkb --code-root .cache/p0-audit/dirty-baseline-source --count 30 --output .cache/p0-audit/dirty-checks-before.json
& $py -X utf8 -m benchmarks.benchmark_dirty_checks --wkb .cache/p0-audit/input/nova.wkb --count 30 --output .cache/p0-audit/dirty-checks-after.json
```

## 剩余范围与回滚

- Task 01 已补原生 Windows、持续复用视图、1k/10k/100k 的 4/33 列负载、投影编辑及真实 Workbook 订阅链，并治理四个旧脚本的非隔离文件入口；长期运行/DWM FPS 和更多组件规模仍作为明确的后续测量限制，见串行交接记录。
- Task 03 的逐层精确比较和原 JSON fallback 已实现，尚未引入缓存；结构变化仍保持原路径。Task 04 已减少 Correlation 重复捕获并验证隔离与多窗口对照，仍有后台完成阶段的阻塞和内存成本。
- Task 05 安全保存和 overlay 契约已实现/验证；smoothing 实验与兼容设计已记录，当前保留原契约，未进行 schema 迁移。
- Task 06 已补 4/33 列原生规模、投影编辑与真实 Workbook 订阅链验收，并针对 profile 证实的 participation flags/Shift 连选重复通知做局部优化；1056 项最终回归通过。33 列极大粘贴、首次全选和原生选区构建仍有长停顿，详见串行交接记录。
- Task 07 已减少同步时废弃的状态复制；更多命名窗口规模与主要剩余调用链需继续测量。
- Task 08 只验证本批 Correlation 散点热点，未声称其他页面都已优化。
- Task 09 未额外拆分 UI 协调器；本次复用已有绘图类与只读快照接口，避免为目录外观重构。
- 回滚业务修改：恢复 `correlation_page.py` 本批 diff 中原来的 `plot.plot()` 创建方式及 import。
  测试基础设施可以独立保留；不需要迁移用户数据。回滚时仅撤销本批 diff，不重置用户工作区。
- YAML 修改可独立撤销 settings/settings_dialog/point precision 相关 diff，但将恢复旧的非原子写入风险；无需改写现有 YAML。
- 同步修改只需撤销 matching_window 两处 `readonly=True`；保留测量脚本与数据独立副本保护。
- 表格续作可独立撤销 sheet.py 和 OrderModel 返回值相关 diff；测试与基准可保留，无文件格式变化。
- Recovery 续作可独立撤销 window.py 的帧分支与 workspace_document.py 的 Correlation readonly 调用，恢复旧的先复制再冻结路径；不需要改写恢复文件或用户 WKB。
- Dirty 续作可独立将 same_snapshot 最后一项恢复为两次 `_comparison_json()` 比较，并移除 `_same_state`/`_same_plain_state` 与 math import；不影响其他优化或任何用户文件。
