# P0 最终质量审查（2026-10-25）

## 范围与结论

本轮在原工作目录和 `codex/v4-dev2` 顺序审核；入口 HEAD 为
`983241677c3f23ac0d211a3af7d5666da8b57682`。没有新 worktree、分支、push 或稳定分支合并。
优先检查 Dirty/Recovery、表格通知与 Undo、父子同步、绘图刷新和导出高风险差异，
没有重新全仓开发。代码和当前测试证据优先于旧交接中的“6/9”“7/9”。

**功能回归与数据保护通过本轮已执行的检查；P0 整体流畅度仍不能全部验收。**
首次选择和 Shift 已有实质改善，但完整分析撤销、Writer 历史和多窗口同步仍有长阻塞。
Task 09 的“不再重构”决定保留，不能用它掩盖未完成的性能目标。

## 本轮确认并修复的问题

### 分页 Wafer 的 Matplotlib Bias % 导出异常

入口现场的七个未提交文件是已有导出布局工作，本轮纳入审核并保留。
`_write_parameter_block()` 在构造跨页面板时，将 `("Bias %", page_layout)`
作为两个列表元素展开；启用 percent 且 Wafer 超过一页，循环解包即抛出
`ValueError: too many values to unpack (expected 2)`，报告不能完成。

通过公开 `MatchingWindow.export_excel()` 增强已有 12 Wafer、双参数回归：
同时开启 Bias %，两种渲染模式均保存后重新加载，要求每个参数每页都有四个面板，
保留分页标签、完整来源类别和不重叠校验。旧写法实际失败；一行修复为展开
包含二元组的单元素 tuple 后通过。没有修改拟合、数据精度、分页身份或持久化协议。

- 失败证据：`.cache/p0-audit/final-audit-export-red.log`。
- 专项：39/39，19.121 秒；`.cache/p0-audit/final-audit-export-green.log`。
- 全量：1083/1083，361.444 秒；`.cache/p0-audit/final-audit-full.log`。
- 代码 checkpoint：`06a9d15a5a2b43f56d4defdd5bb1139d6ce012b1`。

该 checkpoint 包含既有七文件整体快照，不能把其 325 行新增全部归为本轮开发。
相对入口现场，本轮生产代码只改上述一行，测试增加 percent 覆盖。
入口差异备份为 `.cache/p0-audit/final-audit-incoming.patch`。

### Workbook-only 基准被无关大表干扰

原脚本即使带 `--workbook-only` / `--auxiliary-only`，仍先构建三个通用 Sheet
视图。本轮 100k×33 Workbook 原生运行在初始化阶段长期未产生按键样本，已人工终止；
随后 20 秒一次的调用栈显示停留位置包括菜单 SpinBox、Match type 控件和 Mapping
控件构建，不能将它解释为 Undo 耗时，也不能算验收通过。

诊断只取消这三个无关视图，保持原 benchmark 函数、数据、辅助功能、键盘事件、
全部语义断言和完整刷新等待，Preview/Final/Writer 均正常完成。因此对既有脚本作
三行分支隔离修正及截图空视图保护。独立诊断包装器执行的文本变换与最终脚本一致；
原 Sheet 前后对照路径不受此修改影响。没有禁用 Qt 辅助功能、GC 或必要刷新。

这修正的是基准场景的污染，**不是生产程序初始化提速**。本轮清洁 Workbook 数据
不能直接和旧报告中夹带三个通用大表的数字作百分比对照；大量宽表同时打开时的
原生初始化异常仍保留为未验收场景，内部 Qt/运行时原因没有充分归因，不擅自修生产代码。
证据：`final-audit-workbook-preview-diagnostic.log`，原始空日志保留为
`final-audit-workbook-preview-aborted.log`；当前正式 `-m` 入口已采用相同隔离分支。

基准修正后的最终源码再次执行隔离全量：**1083/1083 通过，369.817 秒**，
日志 `.cache/p0-audit/final-audit-final-full.log`。两次全量均保留，未因失败改阈值。

## 高风险审核结果

| 范围 | 审核证据与结论 |
| --- | --- |
| Dirty | `_same_plain_state` 只走严格普通类型；未知类型、非法数值/循环、长整数等继续精确 JSON fallback。保持键序、浮点 signed zero、嵌套状态验证，早期差异不跳过后续非法值。无 revision 缓存。Snapshot oracle、Card/Mapping/过滤/绘图状态、精确 Undo→Clean 回归通过。 |
| Recovery/WKB | borrowed snapshot 在 GUI 线程 `freeze_snapshot()` 后才交后台，当前与 baseline/子草稿分离；保存/Discard 取消旧 future，candidate 原子发布与 revision 检查保留。WKB store/recovery 协议相对 v4.2.0 未改。阻塞 worker 后继续修改草稿和 baseline 的测试验证没有别名泄漏；失败写入、备份、取消、连续编辑、旧格式回归通过。 |
| 表格/Undo | 命令保存的修改集合只读，批量更新仍发送必要 `dataChanged/changed`；元数据锁、空白尾行、隐藏/排序映射和单步 Undo 保留。范围辅助功能优化仅 opt-in 均可选择的模型，保留完整 selectionModel delta，定制 flags/header 回退。Qt 版本升级必须重新检查该原生契约。 |
| 多窗口 | 同步前后读取 frames 分别负责草稿保护与接受新基准，未错误合并为一次；Ref 数值变化只有候选集合不变才保留控件，资格变化仍重建。Group 复用同时精确核对 Ref/Raw 和状态，复制 plan shell 后绑定当前来源。没有新增异步发布或修改所有权协议。 |
| 绘图 | Task 08 修改只省去字体/字幕变化时的无关重建；数值、坐标与已选 Die 不变，导出脏标记仍设置。Map revision、sender 检查及关闭时断连保护保留；关闭插值期间不能把迟到结果发回旧窗口的测试通过。 |
| 导出/资源 | 公式和原始文本、NaN 缺口、原生图与图片、串行/并行图像等价、取消和原子发布均有全量覆盖。入口的 `_Pictures.close` 使用 future 的正确 tuple 下标，队列和进程池退出会清理；本轮不另造导出缓存。没有发现本轮高风险 diff 导致的持久资源泄漏；这不是长时间压力运行证明。 |

## 测试是否被删减或放宽

没有提高原 Grouped Correlation `<2.000 s` 等原有性能阈值。新增 Writer serializer
300 ms 检查曾因共享测试进程状态失败，前阶段改为独立进程，数值门槛仍为 300 ms；
原失败日志保留。这只能验证独立进程场景，不能证明长时间使用也达到同一延迟。

**存在旧测试删除/替换，不能报告为“所有旧测试原样保留”。** 自 v4.2.0 的差异包括
Dynamic All Dies/多符号用例删除、比较模式测试改写，以及 Radius 图片高度、Hover、
导出布局断言更新。`map-hover-export-fixes-2026-10-24.md` 记录这些来自另一阶段的
功能/呈现调整（包括用户取消 All Dies），不是本轮为性能放宽测试。
旧 WKB 的 `view_mode` 因该已有功能调整被忽略；本轮不擅自恢复或继续改变该行为。
因此“数值/身份等价”不意味着与 v4.2.0 所有 UI 功能、图像像素都完全一致。

## 原生 Windows 与性能证据

执行入口：`.cache/p0-audit/final-audit-native.ps1`，异常后继续执行的清单为
`final-audit-native-remaining.ps1` 和 `final-audit-native-clean-workbooks.ps1`。
复用已有 benchmark，没有新建基准系统。
原始 JSON/log 在 `.cache/p0-audit/final-audit-*`；可提交摘要位于
`docs/validation/p0-final-quality-audit-2026-10-25.json`。

Windows 10 build 26200、Python 3.11.16、Qt 6.11.0、20 逻辑 CPU；Qt 原生 `windows`
后端，表格显式请求 UI Automation。与旧基准的屏幕/DPI/缩放信息逐字段相同。
NOVA 原表 7,731×33，按原序重复/截取为 100k×33；完整原文字串、投影行序、
隐藏行操作和 Undo/Redo 都在计时之外执行等价断言。旧表格源码的 blob 已核对与
`2192a04` 一致，旧绘图对照与 `a97732b` 一致。

### 100k×33：同一基准的三轮首次操作对照

下表是前阶段优化的本轮复核，**不是本轮一行导出修复带来的收益**。单位 ms。

| 操作 | 旧版 P50 | 当前 P50 | 当前 P95 | 当前最大 Qt gap |
| --- | ---: | ---: | ---: | ---: |
| 首次 Ctrl+A | 6698.23 | 21.47 | 22.89 | 22.89 |
| 投影首次 Ctrl+A | 8997.32 | 26.03 | 26.28 | 26.28 |
| Shift 取消勾选 | 7164.91 | 15.33 | 20.85 | 15.33 |
| Shift 勾选 | 7166.62 | 15.30 | 19.70 | 15.30 |
| 粘贴后的首次 Undo | 1289.21 | 246.28 | 253.13 | 248.88 |
| 首次 Redo | 1467.71 | 50.56 | 50.90 | 40.29 |
| 删除后的首次 Undo | 1462.16 | 50.34 | 53.55 | 41.90 |
| 整表 Copy | 1000.03 | 992.95 | 1031.73 | 1020.61 |
| 整表 Paste | 11735.74 | 4363.15 | 4520.96 | 4504.95 |
| 整表 Delete | 3777.25 | 3203.82 | 3260.57 | 3250.96 |
| 搜索筛选 | 434.05 | 432.15 | 436.28 | 428.37 |

Shift 两个方向已经在同一量级，首次选择的主线程停顿显著下降。Copy、宽表
Paste/Delete、搜索筛选仍有明显停顿，不用窄表 4 列结果替代 33 列结果。
Ctrl+A CPU 时间 P50 为 6640.625→15.625ms，Shift 取消为 7187.5→15.625ms。
进程峰值 working set 3,255,349,248→3,256,532,992 B，**没有内存下降的证据**。
这里 CPU 是操作累计 CPU 时间，不是瞬时 CPU 利用率峰值。

### 完整 Workbook / Writer 单独场景

每项一个新窗口的首次样本，仅作为绝对延迟复核，不声称统计 P95 或相对旧混合场景收益。

| 表格/动作 | 完整耗时 ms | dispatch ms |
| --- | ---: | ---: |
| Workbook Raw Ctrl+A | 10.47 | 0.51 |
| Workbook Raw Undo | 1329.81 | 209.81 |
| Workbook Reference Ctrl+A | 6.39 | 0.20 |
| Workbook Reference Undo | 1012.27 | 7.94 |
| Workbook Order Ctrl+A | 5.08 | 1.91 |
| Workbook Order Undo | 271.86 | 269.57 |
| Workbook Final Ctrl+A | 12.16 | 0.51 |
| Workbook Final Undo | 1204.77 | 208.11 |
| Dynamic 10k×33 Ctrl+A | 16.22 | 0.84 |
| Writer 参数表 10k×4 Ctrl+A | 248.98 | 0.23 |
| Writer 步骤表 10k×41 Ctrl+A | 292.79 | 0.21 |
| Writer 单格编辑 | 1263.59 | 992.61 |
| Writer 首次 Undo | 4220.92 | 1754.75 |
| Writer 首次 Redo | 3067.54 | 2195.70 |

例如 Reference Undo 按键 7.94ms 返回，完整刷新却为 1012.27ms，不能宣称该撤销
已实现“第一次毫秒级流畅”。Writer 按既有文档契约最多 10k 行/20 steps，不伪造 100k Writer。

### 多窗口、绘图和数据保护

- 五个同类 Correlation 窗口，三轮完整 P50：Raw 3158.67ms，Mapping 2681.80ms，
  Group 5884.94ms，Preview/Final 5333.91ms；相应最大 Qt gap 为
  729.85、804.74、1210.79、1161.53ms。原 Task 07 配对 Raw 为
  3448.90→3223.78ms，本轮是当前版本复核，不能把两个日期结果算成新优化收益。
- 五个混合子窗口三轮：Raw 1920.86ms、Group 2814.92ms、阶段切换 2412.48ms。
  两批均验证手工独立草稿、baseline 和手工 Reference 不被父编辑覆盖。
  混合夹具为两个 Correlation、两个未 Draw Map 和一个空独立 Dynamic，
  **不等于五个都已完整绘图的大窗口压力测试**。原 0/1/3/5 矩阵报告继续保留。
- 当前绘图完整 paint P50（ms）：Trend 266.77、Correlation 77.42、Dynamic 959.20、
  Dynamic Trend 448.69、Map render 719.75、Radius draw 395.90。
  字号/字幕：Dynamic font 53.91、Map caption 146.55、Radius caption 78.32。
  五类数值 digest 与原 Task 08 对照完全相同；prepare/render/layout、P95、CPU、
  gap/内存见 JSON，inclusive spans 有重叠，不能相加。
- 原 Task 08 配对完整 paint P50：Dynamic 字号 334.56→67.73ms，Map 字幕
  326→156ms，Radius 字幕 180→106.51ms；当前更低的数字只作复核，未新增优化。
- Dirty 30 轮×8 场景，240 次判定通过。当前 Clean P50/P95 50.38/58.91ms、
  Undo 回基线 50.20/58.58ms。历史同条件配对为 88.75→49.83ms，本轮不改比较策略。
- 额外将 120 张 Map 当前并行计算与 blob 验证过的 v4.2.0 串行例程比较：
  **surface 数组、mask、原点/行序、options/limits 精确相等**，包含缺失坐标/数值。
  源 frame 未变化，退出后 ThreadPoolExecutor 线程已回收。
- Windows 原生专项 **68/68，通过，30.193s**：包含表格通知、文档保存/Discard/
  Recovery、关闭时迟到结果保护、Dynamic/Map/Radius 数值与导出视图等价。
- 真实 `config/settings.yaml`、只读 NOVA 副本及两份用户 Excel 的 SHA-256
  与审核开始相同。保护清单和测试日志 SHA-256 收录于最终 JSON。

测量界限：端到端包括 queued analysis 和同步 Qt paint，不是 DWM FPS；
RSS/private 为采样时值，peak 是含 fixture 的进程累计峰值；小样本 P95 等于最大值，
不作为统计置信界。三轮冷表格表示三组新建视图，各自首次操作，不是三个全新应用进程。
fixture 构建在操作计时之外，不能将 ms 级 Ctrl+A 解读为 ms 级打开/初始化文档。

## Task 01–09 严格状态

| Task | 最终状态 | 边界 |
| --- | --- | --- |
| 01 | 基础基准完成；扩展要求仍有边界 | 1k/10k/100k、原生 Windows、冷/热、P50/P95/gap、CPU 时间/内存峰值与保护哈希已有证据；瞬时 CPU 利用率峰值、DWM FPS、长时运行和发布 EXE 尚未测，不冒称全指标完成。 |
| 02 | 本机验收通过 | 原 `<2 s` 与 6 fits/12,000 positions 等断言保留；旧发布环境 2.086 s 未在本机复现，不宣称修复了同环境故障。 |
| 03 | 已完成并复核 | 精确 Dirty/Clean、嵌套与非法状态、回退基线、Card/Group/绘图/Recovery 通过；不代表所有 Writer Dirty 开销均已消除。 |
| 04 | 本阶段完成并复核 | 捕获隔离、失败保护、连续请求及保存/关闭/Discard 回归通过；大快照的冻结、后台完成和峰值内存仍有成本。 |
| 05 | 已完成并复核 | 原子 YAML、锁/冲突、损坏保护和文档 overlay 归属通过；真实文件保持不变；smoothing schema 迁移未实施。 |
| 06 | 部分完成 | 冷 Shift、首次 Ctrl+A 和纯 Sheet Undo 改善；完整 Workbook/Writer Undo、宽表复制粘贴仍未达到新增的整体流畅要求。 |
| 07 | 部分完成 | 低风险优化与所有权回归通过；五窗口 Group/阶段切换仍有秒级长等待，不能验收为整体流畅。 |
| 08 | 部分完成 | 局部 restyle/caption 优化与数值语义通过；完整 Draw/paint 成本仍在，未宣称五类页面都无卡顿。 |
| 09 | 架构评估完成，整体质量关卡有保留项 | 接受“不实施额外重构”；全量/原生验证见上，06/07/08 剩余流畅度阻止整体 P0 无保留通过。 |

不能把本表简化为 9/9 全部完成。原任务对照以各项验收条件为准，新增“所有表格
第一次 ms 级”要求也算入 Task 06，而不是只沿用早期限定阶段的完成计数。

## 剩余工作与风险处置

1. Writer 单格 Undo/Redo 仍经完整文档历史序列化和 Dirty 比较。改为局部命令前，
   必须覆盖 OCR 原文/来源/候选/history、Review/Resolve 与全量导入交错事务；不是本轮
   可安全凭一处耗时就改的数据所有权问题。
2. Workbook 完整撤销包括 Group/Mapping/分析与绘图更新；不能跳过订阅或只统计
   dispatch。后续应对保存两次输入快照的业务契约做清晰接口设计，再逐个减少真实冗余。
3. 多窗口的 revision/generation、异步发布或接受基准变更需要单独方案和竞态验收；
   本轮没有把同步工作简单移到线程，也没有靠共享可变 DataFrame 提速。
4. 大页绘图仍受数值准备、图元数和 paint 成本影响；不能抽样丢点、桥接 NaN 或改变
   插值/拟合。CPU 高负载与系统缩放/辅助功能状态会影响长尾；长时资源稳定性未覆盖。
5. 多个 100k 宽表同时存在时，新窗口原生控件初始化异常在本轮复现；清洁单窗口
   基准消除干扰后通过，但这一多大表组合场景未修复。后续应单独采集 Qt/运行时
   profile，不能通过隐藏失败记录、关闭辅助功能或禁用 GC 把它归为已完成。

## Checkpoint、文件与回滚

- `06a9d15a5a2b43f56d4defdd5bb1139d6ce012b1`：审核后的导出现场和修复，完整文件列表：
  `docs/features/excel_export.feature`、`docs/plans/map-hover-export-fixes-2026-10-24.md`、
  `metrology_app/excel_export.py`、`metrology_app/export_rendering.py`、
  `tests/test_excel_report_layout.py`、`tests/test_export_hover_fixes.py`、
  `tests/test_export_template_layout.py`。
- `benchmarks/benchmark_sheet_workflows.py` 的隔离修正、本报告、进度索引和最终
  摘要另存验收 checkpoint；准确 SHA 见最终消息及 Git log。回滚此项只恢复
  基准夹具构建和文档，不改变生产 Undo/Dirty/存储逻辑。
  文档文件为 `docs/plans/p0-audit-implementation-2026-10-23.md`、本文件和
  `docs/validation/p0-final-quality-audit-2026-10-25.json`。
- 前阶段 checkpoint：Task 03 `d3d57d1`、01 `580c5d2`、06 `a97732b`、
  08 `ff3c133`、07 `2192a04`、冷表格 `078eb99`、09 评估 `9832416`。
- 回滚应逐项 `git revert <目标 SHA>`，不要 reset/tag 覆盖整个现场。撤销 `06a9d15`
  会连同此前未提交的布局工作一并撤销；若仅隔离本轮修复，反向还原该一行和对应
  percent 测试即可，但会重新引入已复现的导出失败。用户 `asdf.xlsx` 和
  `matching-matplotlib.xlsx` 未纳入提交、未覆盖。

本轮结束后停止开发；性能遗留不隐瞒，也不未经单独设计扩大高风险改动范围。
