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
