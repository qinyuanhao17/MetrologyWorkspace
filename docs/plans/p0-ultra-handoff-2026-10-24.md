# P0 串行续作：Task 08 → 07 → 09

起点为同一工作区 `codex/v4-dev2` 的
`a97732bc32a758c85ffcd719d6cafc26887b230e`。此前 Task 01–06 的完成与限制见
`p0-serial-handoff-2026-10-24.md`；本阶段不重复计入其收益。没有创建 worktree
或分支，没有 reset、push、合并或修改用户 Excel/WKB。

## Task 08：绘图准备、呈现与布局

复用已有 `map_fixture`、Dynamic 130 行/26 参数夹具、Windows 内存采样及隔离
benchmark 入口，增加 `benchmarks/benchmark_plot_stages.py`。Trend/Correlation
读取真实 NOVA 7,731×33，限制为选择网格中的前两个参数、全部可用测量组；
Dynamic 使用 10 Cycle×13 Die×26 参数，包含一个缺测值和一个次轴比较；
Map/Radius 使用 12 wafer×10 参数（120 panel），每 wafer 69 个点，字幕带 PAD/LOT。

基准先记录数值准备、render、显式 grid 布局调用的 inclusive span，再处理 Qt
事件与同步 repaint。span 可能嵌套，不能相加当作完整耗时分解；Qt 剩余布局和
paint 成本包含在 paint_complete 中。Map 准备独立于页面呈现，其 direct_ms
才是数值准备时间，不能将当时旧页面 repaint 当作 Map 首帧。

原生 Windows，每项先预热一次再保留 5 次；P95 是这 5 次的最大值，不能作为
统计置信上界。before 为本阶段起点冻结的源码包，after 为当前源码，各独立进程
串行运行。cProfile 另跑，不纳入无 profile 配对。完整逐轮记录位于
`.cache/p0-audit/task08-{before,after}.json` 与
`task08-captions-{before,after}.json`，摘要保存为
`docs/validation/p0-task08-comparison-2026-10-24.json`。

| 操作 | 直接 P50 前→后 ms | 直接 P95 前→后 ms | Qt paint 收尾 P50 前→后 ms |
| --- | --- | --- | --- |
| Trend Draw | 185.42→185.91 | 190.87→196.68 | 252.79→253.66 |
| Correlation Draw | 42.15→41.74 | 56.76→111.22 | 77.74→84.43 |
| Dynamic Draw | 236.58→239.91 | 309.71→296.15 | 869.69→904.03 |
| Dynamic Trend Draw | 260.44→254.43 | 331.55→332.89 | 337.74→338.48 |
| Dynamic Trend 字号 | 227.46→4.33 | 302.53→7.55 | 334.56→67.73 |
| Map 数值准备 | 561.97→552.48 | 577.97→573.93 | 不适用 |
| Map 呈现 | 431.01→416.62 | 431.56→420.32 | 747.19→721.47 |
| Map 身份标题 | 177.91→0.09 | 179.98→0.10 | 326.46→156.33 |
| Radius Draw | 200.38→206.01 | 201.44→215.82 | 396.60→423.81 |
| Radius 身份标题 | 12.18→0.10 | 12.51→0.14 | 180.10→106.51 |

没有修改 Draw 数值准备或全页绘图路径，不把这些波动计为优化收益。主要剩余
成本包括 Dynamic 大量表格/绘图的 Qt 收尾与 Map 全页 paint，尚未达到所有操作
流畅。内存为末尾 RSS/private 和进程累计 peak，不是单操作独立峰值，不宣称
内存改善或 DWM FPS 改善。CPU/gap/内存及 span 数值均在摘要中。

Profile 定位到 Dynamic 改字号重建 26 个 PlotWidget；Map 改标题重跑 120 次
set_geometry，其中数字标签路径占主要时间。因此只改以下两类无数据变化刷新：

- `dynamic_trend.py` 字号原位更新标题与主轴 label，保留单位、前缀和其余 style，
  保留曲线、Die 选择、比较次轴和视图，失效延迟导出与复制缓存。
- `plot_page.py` / `radius_page.py` 身份标题只更新 Panel 的 caption 状态并
  `update()`。标题在 paint 中读取，边界固定，不重建 hover 坐标、数值标签、
  色条或散点；保留导出失效。没有省略必要 repaint。

五类数值摘要前后相同，包括 Trend 屏幕数组、Correlation 测量/预测/拟合系数、
Dynamic pivot、Map 原始点与插值表面、Radius 符号半径与值。专项另验证真实
PAD/LOT 字幕、hover、独立测量身份、坐标、NaN 缺口、图例比较及 Matplotlib
导出。新增字号测试先在旧实现失败（绘图组件被替换），再验证原位更新、主次轴
zoom 和导出数组不变；原字幕工作流增加几何与数组复用断言。数值 digest 不能
单独证明屏幕正确，保留原有绘图/导出测试。

专项 77 项通过（25.305 s）。一次首次命令误写不存在的模块名
`tests.test_correlation_sources`，属于调用错误；修正为仓库实际模块后全部通过，
没有删除或跳过测试。最终全量 **1,057/1,057 通过，353.931 s**，日志
`.cache/p0-audit/ultra-task08-full.log`；新增屏幕字号断言也在全量中通过。
Task 08 本阶段低风险测量/修改范围完成，剩余重负载停顿明确保留。

复现（使用仓库 conda Python，原生 Windows，所有持久化路径由 benchmark 隔离）：

```powershell
$env:QT_QPA_PLATFORM='windows'
& $py -X utf8 -m benchmarks.benchmark_plot_stages --wkb .cache/p0-audit/input/nova.wkb --count 5 --output .cache/p0-audit/task08-after.json
# before 追加 --code-root .cache/p0-audit/task08-baseline-source
# 字幕最终配对额外指定 --only map_caption radius_caption
# 插桩另跑 --count 1 --profile dynamic_font 或 --profile map_caption
```

回滚仅撤销本阶段三个生产文件的 diff（字号回到 relayout，字幕回到 grid
relayout），基准与测试可保留。无需迁移数据或改写任何 WKB/恢复文件。

## Task 07：命名窗口同步

增加 `benchmark_workspace_sync.py`，沿用隔离 benchmark 入口、NOVA WKB、原生
Windows 和现有内存采样。0/1/3/5 个同类命名 Correlation 子窗口分别在独立进程
运行，Raw/Mapping/Group/Preview–Final/子参数选择/Card/未变同步各预热一次、
保留 3 次。两个阶段先准备有效且互相独立的 Raw；每个 Correlation 有独立手工
Reference，并绘制两个参数的 Trend/Correlation。测量同时记录键/控件返回、
分析/同步/排队绘制收尾、10ms 心跳、CPU、同步调用次数与 inclusive span。

这是旧 Recovery 探针之外的新覆盖：旧探针编辑了全部子 Raw，因而窗口已经
脱离 Copy 链，不能替代 linked 同步测量。本探针主矩阵全部保持 linked；计时
后另在一个子窗口写入精确哨兵 `99.12345000`，再编辑父 Raw，验证独立 Raw、
Reference、accepted baseline 原样保留，其他 linked 兄弟继续跟随。0 窗口的
子参数项只是空对照，不代表存在一项真实子参数操作。

无 profile 配对之外，另做 GUI cProfile：单窗口一次 Raw 更新中
`_commit_stage_workspace` 的一次 fillna/astype 约 13ms；同列名的数值改变根本
不可能产生 rename，却仍规范化整张 7,731×33 Raw。只增加 columns 候选检查：
有潜在重命名才执行原转换和逐列精确比较。原碰撞规则、Draw 选择重命名、
类型转换及所有权检查保持原样，不跨调用缓存，不合并刷新前后两次帧读取。

最终原生配对摘要（完成含排队分析和同步 paint，ms）：

| 子窗口 | Raw P50 前→后 | Mapping P50 前→后 | Group P50 前→后 | 阶段切换 P50 前→后 |
| ---: | --- | --- | --- | --- |
| 0 | 309.64→305.59 | 362.97→356.40 | 621.25→625.37 | 207.60→206.82 |
| 1 | 888.55→924.72 | 843.53→832.58 | 1690.49→1670.50 | 1263.22→1251.68 |
| 3 | 2057.30→1943.56 | 1774.04→1713.31 | 4134.50→3724.25 | 3269.90→3219.21 |
| 5 | 3448.90→3223.78 | 2667.92→2604.97 | 6019.23→5889.33 | 5495.06→5478.33 |

5 窗口 Raw P50 本次下降约 6.5%，但单窗口 Raw 反而波动增高；只保留“无效
转换已消除”的明确结论，不宣称所有同步都提速或 5 窗口已经流畅。三样本 P95
仅为最大值；Mapping/Group/阶段按相同迭代位置切换状态，聚合中位数不可代替
所有分支。子参数、Card、未变同步、CPU、gap、RSS/private/累计 peak 与调用
次数均见 `docs/validation/p0-task07-comparison-2026-10-24.json`；原始文件为
`.cache/p0-audit/task07-{before,after}-{0,1,3,5}.json`。

额外五窗口混合冒烟（两个 Correlation、两个未绘制 Map、一个独立空 Dynamic）
通过相同七类动作和独立草稿检查；每项仅一个保留样本，用于覆盖，不当性能
统计。该次 Raw/Mapping/Group/阶段完成分别约 1976/1758/2884/2235ms，证据
`task07-mixed.json`。所有输入文件与真实设置 hash 保持不变。

复现沿用 Task 08 的 Python/隔离约束，每个 N 顺序运行：

```powershell
& $py -X utf8 -m benchmarks.benchmark_workspace_sync --wkb .cache/p0-audit/input/nova.wkb --children N --count 3 --output .cache/p0-audit/task07-after-N.json
# N 为 0/1/3/5；before 追加 --code-root .cache/p0-audit/task07-baseline-source
# 混合覆盖：--children 5 --kind mixed --count 1
# 插桩另跑：--children 1 --only raw --profile raw --count 1
```

回滚只撤销 `matching_window.py` 本阶段候选列检查，恢复无条件规范化；不改变
任何所有权状态或文档格式。Task 08 checkpoint 为
`ff3c1336520965227572a91f88ad90d3b06a74bd`。

Task 07 三项针对性回归通过（0.953s），最终当前工作区全量
**1,059/1,059 通过，359.544s**，日志 `.cache/p0-audit/ultra-task07-full.log`。
全量包含现场保留的两项新增导出测试，但相关外部修改不归入本阶段 checkpoint。
profile-after 中此分支的 fillna/astype 调用均消失；同步次数和保护分支未被跳过。
本阶段低风险范围完成，高风险方案和五窗口长停顿仍交 Astra High 审核。

### 交给 Astra High 的高风险方案（未实施）

1. `_refresh_stage_workspace` 在事务前调用 `set_workbook_participation` 准备旧
   Group context，后续 `set_sources` 清除、`set_workbook_groups` 又重建。正常
   linked 路径存在重复，但独立草稿、手动输入、空 Workbook 的提前返回仍依赖
   前面的 participation 更新。需要先明确各分支事务的输入和发布边界，再考虑
   一次性提交 context；不能直接删除第一次调用。
2. 两次 `workspace_snapshot(readonly=True).frames` 仍生成了不使用的 UI state。
   若要增设纯 source-frame 读取接口，必须分别保留刷新前草稿检测与刷新后
   baseline 推进，不能共用同一份旧 frames。新接口可能影响子窗口种类和所有权，
   此阶段仅记录，Task 09 再评估必要性。
3. 不在本轮引入 shared frame 缓存、revision/generation 或后台同步。若后续采用
   这些方案，评审需要覆盖五个混合子窗口连续 Raw/Mapping/阶段切换、故意倒序
   完成绘图任务及同时请求 Recovery 的发布顺序。既有单场景正确性测试不能证明
   新协议在该组合下正确。

### 本轮新增范围

用户在 Task 07 期间明确要求继续解决 100k×33 首次 Shift 取消勾选、所有表格
首次 Ctrl+A 和 Ctrl+Z 的长停顿。Task 08 checkpoint 已完成；本阶段先完成 Task
07 checkpoint，再单独做这一组表格修改，最后完成 Task 09 评估。此前 Task 06
的 6.4s gap 不作为本次新增验收的合格结果，也不能用热中位数掩盖冷操作。

工作区中途出现的 `excel_export.py`、`export_rendering.py`、相关导出测试及两份
导出文档修改属于本阶段之外的现场修改，保留且不混入 P0 checkpoint。

2026-10-25 此新增范围的独立测量、代码说明与验收限制见
[大表冷操作补充交接](p0-table-cold-handoff-2026-10-25.md)。首次连选、全选和纯表格
Undo 已消除原数秒枚举成本；完整分析 Undo 和 Writer Undo 仍不达全部流畅目标，
没有把这一新增要求整体计为完成。

表格独立 checkpoint：`078eb99d145b40e5719b5f9a46fd9d802471c211`，最终全量
**1,083/1,083 通过，362.503s**。之后 Task 09 仅评估，不做收益不明确的额外重构。
Task 01–09 最新状态、08/07/表格的完整 SHA 和文件、性能、验证、回滚及 Astra
具体待审项目见[最终评估与交接](p0-task09-assessment-2026-10-25.md)。本阶段停止开发。
