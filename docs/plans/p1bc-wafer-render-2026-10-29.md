# P1-B / P1-C：Wafermap 分批渲染与联动调度

状态：本轮本地实现与验证已结束，性能部分达标。最新完整回归 1264 项，1261 通过、3 项耗时失败，无测试错误，1197.615 秒；不能宣称全绿。P1-C 小表重图的整体耗时明显退化，性能验收未通过。没有提交、推送或扩展下一阶段。

50 图新页面首次绘制的最大 GUI 方法区间中位数从 1217ms 降为 318ms，数值更新从 1296ms 降为 323ms。完整双窗口更新仍约 34–36 秒，小表重图的完整刷新反而变慢；本轮没有达到整体 Ctrl+V/Z/Y 小于 300ms。

## 基线与范围

- 基线和当前 HEAD：`v4.3.5`，`3d01f1c847f95772dc38aa7a5f57cdd6e5985be7`。
- 保留用户 `.vscode/settings.json`、`AGENTS.md`、`docs/todos/` 等既有工作；没有提交、推送、发布或创建 worktree。
- P1-A 的 `correlation_page.py` 和 `plotting/curve.py` 保持原文件 SHA-256。
- Python：`F:\Anaconda3\envs\octs\python.exe`；性能对照用 Windows Qt 平台，普通专项与全量用隔离 offscreen runner。现有 QA lxml 依赖路径保留，没有依赖升级。
- 原始配置只做哈希保护；测试和基准设置、Recovery、数据均在自有临时目录。用户 WKB 未用作可写试验对象。

## 根因与实现

原始 50 图 profile：SurfaceJob 约 26.57 秒在后台，不是同等长度的 GUI 阻塞。GUI 同步创建/布局约 1.80 秒，其中布局 1.39 秒、标签 1.22 秒；首次 viewport 绘制还约 573ms。

1. `WaferMapGrid` 使用自己拥有的 QTimer，每次创建两个面板。候选层由 QObject 拥有，但不进入已显示场景，避免每一批都触发旧页面重绘。全部候选有效后才发布；generation、页面 revision 及关闭取消检查共同拒绝过期回调。
2. 保留完整旧页面和成功结果；`PlotPage.result`、绘图状态、导出按钮只在完整发布时推进。失败保留旧画面但标为 stale，禁止旧图冒充最新导出。
3. 几何和文字路径仅在数据、坐标、字体和格式全部匹配时复用。空间分箱保留原来的严格重叠判定和贪心顺序，减少 O(n²) 标签扫描。样式候选的 options 独立；相同数值时复制只读文本准备结果，发布时复用原 ImageItem。未改变插值、数值、分辨率或选中的 map 数量。
4. Contour 保持原有可见面板惰性准备语义；不预先强制计算整个离屏网格的所有等高线。所有面板和数值仍完整创建，首次可见绘制及导出不减少内容。
5. 页面选择以发布时的当前 `page_intent` 为准；翻页、settle、恢复滚动回调使用页面拥有的计时器。关闭停止回调，释放已发布 Map、结果和 Matplotlib axes，保留保存所需的成功选择/设置。
6. 7,168 cells 小表同时画 24 个 Correlation 面板和 50 Map 时，原来仅依据 `<8192` 走同步刷新。实测同步 Correlation/提交是热点，因此仅对跟随 Workbook 且当前 Correlation/Trend 面板超过 6、或 Map 超过 8 的子窗口，使用已经存在的后台 prepare / 分步 commit 路径。小表轻图和独立输入保留原语义，没有新任务框架。
   没有根据焦点或当前是否查看绘图区来跳过刷新；悬浮 Raw Data 编辑时，已打开且跟随来源的子窗口仍会完成其最新有效绘图。
7. `analysis_export.py` 的必要小改动：把现有 live 导出检查和 saved-export 专用等待扩展到绘图批次 pending；普通刷新没有增加 processEvents 或阻塞 wait。
8. 原生联动基准揭露了“相同最终来源”边界：空取消不能把已成功发布的结果误标 dirty；已经同步好的子表若其绘图任务被取消，不能被相同表快捷返回漏掉最后一次绘图。保留来源 pending 期间的导出保护，并在必要时重放原成功选择。新增受控 blocked-worker 测试实际先红后绿。
9. 首次全量又发现导出保护挡住原有即时小数位更新。最终版本只对来源和图形都有效的当前页，同步 flush 原有点值/精度覆盖层；数据、样式候选或新页面仍 pending 时不允许导出。没有改变数据精度或重算插值。
10. 来源暂停期间收到全局小数位更新，且来源暂停先于覆盖层完成时，原来导出按钮可能保持禁用。独立测试实际先红；覆盖层完成后仅在来源有效、没有脏数据或待处理任务时恢复按钮。该五行修复后的 62 项定向回归通过。

## 已完成专项

- 新分批红测试在 v4.3.5 实际失败：10 个面板同步创建，超过每批 2 个要求。
- 标签空间索引与原贪心算法逐索引对照：随机、负坐标、边界接触、重复框均等价。
- 分批/数据版本/关闭删除/故障注入/样式/导出/页选择/资源专项通过。重复替换后旧面板弱引用释放，scene 数量回到当前页；关闭后只剩根 Item。
- `style-resource.log`：18/18；10 图完整呈现中位数 136ms，原 250ms 门槛保留。
- `integration.log`：88/88，覆盖已有异步任务、联动、Undo/Redo、参与选择、独立草稿、Recovery/保存及 Excel/Matplotlib 报表。
- 早期专项 offscreen 已修改 Map 关闭 602ms，原 `<250ms` 失败，记录保留。原生三轮旧/新同机对照均通过该原门槛；不能用后者覆盖前者，也不能据此称关闭性能已普遍修复。

## 三轮性能对照

所有值都是三轮中位数。GUI 列是该次操作中最大受测 GUI 方法 wall-time 的中位数；存在嵌套调用及既有 Correlation processEvents，不能将它冒充所有场景的连续冻结时间。Qt heartbeat gap 单独列出。完成时间等待了数值工作、全部图形批次，并实际重绘 viewport。

| Map 数/操作 | 完成秒：旧 → 新 | GUI 区间 ms：旧 → 新 | Qt 最大间隔 ms：旧 → 新 |
|---|---:|---:|---:|
| 10 首次绘制 | 12.448 → 12.330 | 298 → 301 | 804 → 1415 |
| 10 数据更新 | 13.100 → 12.600 | 311 → 300 | 1433 → 1361 |
| 10 样式更新 | 0.999 → 1.026 | 522 → 528 | 525 → 532 |
| 30 首次绘制 | 23.999 → 23.991 | 754 → 319 | 1341 → 1740 |
| 30 数据更新 | 24.542 → 23.861 | 766 → 319 | 1084 → 979 |
| 30 样式更新 | 1.064 → 1.125 | 527 → 535 | 530 → 540 |
| 50 首次绘制 | 28.191 → 28.063 | 1217 → 318 | 1222 → 438 |
| 50 数据更新 | 29.249 → 28.158 | 1296 → 323 | 1622 → 499 |
| 50 样式更新 | 0.982 → 1.104 | 446 → 452 | 450 → 457 |

50 图创建/更新的 GUI 区间改善约 74%/75%；10 图该项基本不变。样式完整耗时分别增加约 26/62/122ms，不能称样式变快。10、30 图首次绘制的 Qt 最大间隔没有改善，因此不能宣称整个事件循环已普遍低于 300ms。后台数值工作及调度还需单独隔离，不能仅凭此表把间隔变化归因于机器负载。

| 10k 双窗口操作 | 完成秒：旧 → 新 | 按键 dispatch ms：旧 → 新 | GUI 区间 ms：旧 → 新 | Qt 间隔 ms：旧 → 新 |
|---|---:|---:|---:|---:|
| Ctrl+A → V | 35.805 → 35.031 | 636 → 598 | 1742 → 1758 | 1767 → 2477 |
| Z | 34.044 → 34.246 | 47 → 49 | 1719 → 1804 | 2428 → 2512 |
| Y | 35.969 → 35.761 | 62 → 65 | 1719 → 1724 | 2456 → 1803 |
| 连续 VZY | 3.832 → 3.899 | 392 → 397 | 546 → 561 | 553 → 566 |

这一规模仍由现有 Correlation 保留网格更新与后台插值主导，整体完成时间基本持平，GUI 最大区间没有普遍改善。没有把 Map 局部提速说成整个 Workbook 提速。

| 128×56 重图操作 | 完成秒：旧 → 新 | GUI 区间 ms：旧 → 新 |
|---|---:|---:|
| V | 1.397 → 1.969 | 405 → 78 |
| Z | 1.288 → 1.841 | 341 → 45 |
| Y | 1.274 → 1.916 | 343 → 70 |
| 连续 VZY | 0.494 → 0.601 | 217 → 58 |

P1-C 确认降低了小表重图的 GUI 提交区间，但完整刷新增加约 0.55–0.64 秒，V/Z/Y 分别约 +41%/+43%/+50%。这触及本轮“不允许较大程度恶化小数据场景”的要求，属于明确的性能验收未通过项。128×11、6 个 Correlation 面板和 2 Map 的轻图控制组仍走原快捷路径，V 完成 0.766 → 0.685 秒，Z 0.608 → 0.565 秒，Y 0.576 → 0.559 秒，未观察到明显退化。

阶段判定：P1-B 图形实现完成，50 图响应指标改善，但其余响应、样式耗时及内存目标仅部分得到证实；P1-C 联动调度和正确性实现完成，小表重图的整体性能验收未通过。不能将本轮报告解读为全部性能目标已满足或建议直接封版。

原始数据、逐轮值、CPU、方法区间、计数和内存快照保存在 `.cache/p1bc-wafer-20261029/comparison.json` 及相应 before/final 报告，正式机器证据为 `docs/validation/p1bc-wafer-render-2026-10-29.json`。Map 采用 `maps-final2.json`；两项来源协调修复后，联动采用 `*-final3.json`。随后只有导出精度、覆盖层完成后的按钮可用性和等待测试修正，渲染/数值核心未变；保留每份源码 SHA，不伪称所有测量来自同一个字节版本。

## 数值、图像和生命周期

- 63 组逐轮 Map 内容哈希全部匹配；覆盖数值层、插值数组、RGBA、像素位置和标签保留索引。9 个 linked initial_complete 没有记录 Map 哈希，不算进 63 组。
- 72 次父/子原始来源表断言通过，保留全部字符串、列和行序；Correlation 保留 1225 对及当前页 24 面板。现有专项另外覆盖 NaN、两来源拟合/排序、X/Y swap 和导出。
- 原生 10 图完整网格在首次绘制、数据更新、Viridis/透明度/等高线样式三个状态下，旧/新 PNG 字节级相同，并已查看网格。截图探针最初的 pyqtgraph 关键字调用错误只改了 QA 捕获，未归为应用错误。
- PNG/SVG/PDF、Copy PNG、关闭分析重建导出、Excel 原生图和 Matplotlib 报表保留现有科学数据与尺寸。精度即时导出、选择页导出和原 Artist 复用已由最终专项验证。
- Qt 图元在 GUI 线程创建，每批两面板。新页面准备时只公开完整旧页/新页；真实构造失败保留旧页为 stale，不能导出为新结果；最新版本、当前页选择、关闭和 sip.delete 都有执行回归。
- 每个 50 图页面：两次数值绘制各创建 50 面板；样式候选再创建 50，复用 50 个原 ImageItem 和匹配的几何/标签准备结果。普通基准每次有效数值更新仍只有一个 SurfaceJob，没有宣称本轮减少已不存在的重复插值。
- 重复替换后的旧面板弱引用已释放，deferred deletion 后无候选层，当前 scene 数量不积累；关闭后清除 published grid/result/axes，保存需要的成功选择不丢。Agg 已创建的 renderer 像素缓冲不等于 Figure.clear 后立即归还，长期重复导出后闭窗仍需另做基准。

## 内存观察及限制

Map 50 三轮 teardown Private Bytes：旧 1564.44/1564.45/1565.68MiB，新 1462.78/1612.96/1613.54MiB；新版本第二轮有约 150MiB 跳升，不能称完全无增长。对应新 Working Set 390.14/395.68/395.96MiB，低于旧约 479MiB，但 Working Set 降低不等于无泄漏。

10k 联动 teardown Private Bytes：旧 2046.07/2129.26/2162.70MiB，新 1937.08/2068.08/2122.72MiB。两侧都有增长，只有三轮，且 benchmark 的部分 Python 局部引用、缓存和分配器保留尚在；不是释放所有引用后的 GC 长时基线。这里仅证明已测试的 Map 图元/计时器取消与释放，没有据此宣布整个应用不存在泄漏。

## 全量与必要重跑

首次全量 `full.log`：1263 项，1258 通过、4 失败、1 错误，1184.451 秒。

- 两项即时精度/Artist 读取回归来自新导出等待检查；已恢复原快速 flush 语义。
- Map 视图恢复用例在 SurfaceJob 结束后、分批图形发布前读取 result；只扩展完成等待，保留原 15 秒截止及全部滚动/缩放断言。
- Dirty 三次最小值 110.777ms 超过 100ms；Writer 315.322ms 超过 300ms。没有改这两个模块或门槛。
- 修复后 `full-regressions-fixed.log` 39/39，通过即时精度、视图、分批、来源及资源测试；10 图原 250ms 门槛下中位数 144.827ms。

第二次全量 `full-final.log`：1263 项，1260 通过、2 项耗时失败、1 项测试错误，1177.658 秒。

- Dirty 三次最小值 **110.403ms，门槛 <100ms**；Writer **310.756ms，门槛 <300ms**。两个模块及原门槛均未改。
- `test_render_selected_and_full_export` 在 14 号字体更改后固定等待 250ms，随后读取 artists，此时新的图形批次仍 pending。这是旧测试未等待完整异步发布，不是最后字体或导出数据错误。
- 最后仅将该处测试等待改成已有的完整发布等待；保留所有字体、点值、坐标轴、图像尺寸、原始数据及 PNG/SVG/PDF 断言。`post-full-waiter.log` **54/54，94.043 秒**，包括该用例剩余所有断言。
- 第二次全量运行前后的四个生产文件 SHA 相同。测试等待修正后的 `post-full-waiter.log` 54/54 是定向补证，不冒充全量全绿。
- 随后 `source-overlay-red.log` 实际复现来源暂停/精度覆盖层交错后导出按钮未恢复的生产问题。五行修复后 `final-overlay-green.log` **62/62，111.081 秒**，因此撤回原“不做第三次全量”的安排。
- 第三次重跑由新确认的生产兼容性问题触发，不是为耗时门槛寻找一次绿灯；三次完整日志均保留。

最新全量 `full-last.log`：**1264 项，1261 通过、3 项耗时失败、0 错误，1197.615 秒**。

| 未过测试 | 本次实测 | 原门槛 |
|---|---:|---:|
| 已修改分析窗口关闭（Wafer Map） | 579.003ms | <250ms |
| 已保存宽表 Dirty 检查（三次最小值） | 110.960ms | <100ms |
| Writer 普通单元格编码 | 311.976ms | <300ms |

- 三个失败均在原耗时断言处，没有放宽阈值或删除用例。断言之后尚未执行的检查不计作本次通过；关闭后的源表保护另有原生定向证据，不冒充全量已执行。
- Dirty / Writer 是本轮只监控的既有失败类型，未修改其实现。本次 Wafer Map 关闭再次超标，不能称已经修复。原生三轮同机配对均满足原门槛，而 offscreen 全量与早期专项仍失败；尚无足够证据把差异完全归因于环境，也不能据此排除回归。
- 新增 23 项（分批 12、标签索引 4、重图联动 7）在此次全量通过；此前精度、导出及字体等待问题未再出现。
- 本次运行前后四个生产文件 SHA 相同，受保护文件哈希也相同。只在完成后整理文档/机器证据，未再改生产代码，不再追加全量。

## 文件、保护与复现

生产修改：

- `metrology_app/wafer_graphics.py`：标签索引、分批候选、生命周期/版本校验、完整发布及局部复用。
- `metrology_app/plot_page.py`：成功结果发布时机、来源/导出保护、样式合并、owned timers、视图恢复、关闭清理与原即时精度语义。
- `metrology_app/matching_window.py`：小表重图条件进入既有异步流程；相同来源但绘图已被取消时重放原选择。
- `metrology_app/analysis_export.py`：现有导出等待覆盖数值之后的图形批次。

新增 `benchmarks/benchmark_wafer_refresh.py` 和三份专项：`test_wafer_render_batches.py`、`test_wafer_label_index.py`、`test_linked_heavy_plot_refresh.py`。既有 Array、Excel、Map zoom、P0 audit、plot labels、performance regression 和 static wafer 测试只补真实异步完成等待或非突变结果引用，保留有效断言、输入规模与门槛。

可复现命令使用上述实际 Python 和现有 QA 依赖，调用 `run_tests.py` 以隔离 Settings/Recovery。基准示例：

```powershell
python benchmarks/benchmark_wafer_refresh.py --scenario maps --rows 10000 --parameters 50 --maps 10 30 50 --cycles 3 --baseline-tag v4.3.5 --output .cache/new-p1bc-check/maps-before.json
python benchmarks/benchmark_wafer_refresh.py --scenario maps --rows 10000 --parameters 50 --maps 10 30 50 --cycles 3 --output .cache/new-p1bc-check/maps-after.json
python benchmarks/benchmark_wafer_refresh.py --scenario linked --rows 128 --parameters 50 --cycles 3 --output .cache/new-p1bc-check/small-heavy.json
python benchmarks/benchmark_wafer_refresh.py --scenario linked --rows 10000 --parameters 50 --cycles 3 --output .cache/new-p1bc-check/linked.json
python benchmarks/benchmark_wafer_refresh.py --scenario linked --rows 128 --parameters 5 --light --cycles 3 --output .cache/new-p1bc-check/light.json
python run_tests.py
```

复测使用新的输出目录或文件 stem，确保首轮隔离设置没有沿用旧运行的配色偏好。before/after 组按相同顺序串行执行，不是随机交错实验。第一轮冷窗口与后续应用缓存预热均保留，不能将每个 fresh page 称为每轮新进程冷启动。CPU 是包含所有进程线程的 Windows process time，内存是快照/历史峰值，不作额外精度承诺。

真实配置、只读 QA NOVA WKB、`correlation_page.py` 和 `plotting/curve.py` 在开始、三次全量前后及收尾核对保持一致；具体 SHA 见 JSON。QA lxml 实际来自现有 `p0-die-axis-20261026/dependencies/lxml/etree.cp310-win_amd64.pyd`，OpenPyXL LXML=True。没有升级依赖、调整数值算法、改 WKB/Recovery 格式或修改用户原始数据。

Git HEAD 仍为 `3d01f1c847f95772dc38aa7a5f57cdd6e5985be7`，没有创建 checkpoint、提交、分支、tag、PR 或推送。`.vscode/settings.json`、`AGENTS.md`、`docs/todos/` 和初始无实际 diff 的 `tests/test_linked_table_versions.py` 保留为用户既有工作。

## 未解决的性能边界

- `CorrelationPage.render_interactive()` / 现有 retained-grid 更新仍能占据约 1.7–1.8 秒方法区间；本轮按范围保留 P1-A，不擅自改它或 `plotting/curve.py`。
- `SurfaceJob.run()` / `prepare_array()` 的完整插值仍为数十秒后台工作。没有减点、降分辨率或改变插值来换时间；GUI gap 中后台数值与调度的具体贡献还未完整归因。
- `StaticMapView.paintEvent()` 的可见标签、点和等高线重绘仍约 0.3–0.5 秒，是剩余局部上限。
- 原始剪贴板/Workbook 分析及子表提交仍有成本；不能用按键 dispatch 代替所有窗口完成延迟。本轮没有进入 Undo、状态所有权或持久化协议重写。
- P1-C 小表重图的完成延时退化应在下一次独立 profiling 中核实，而非默认推广这个条件到更多模式。

方法限制必须保留：

- 10k×50 Raw，主 Match 配置 2 个映射；Correlation 为 1,225 对、当前页 24 图；50 Map 是 10 Wafer×5 参数，每 Wafer 500 点，并不是 50 个 Map 参数。
- 完整耗时包含数值 worker、数据提交、全部图形批次和真实 viewport paint；只对实际可见的 viewport 绘制计时，不伪称离屏所有像素都被显示过。
- GUI 方法是包含子调用的 wall time，不可相加，也不总等于连续冻结；Qt heartbeat gap 单独报告，包含线程调度/GIL/系统负载因素。
- linked 的 `initial_complete` 是已经 settle 后的重绘，不是首次拟合总耗时；首次完整绘制使用 maps/first_draw。
- rapid VZY 从 redo 后相同最终值开始，可证明最终状态合并，不能单独证明进行中数值任务的取消压力；取消安全由独立的 blocked-worker 与 GUI 批次测试验证。
- 内存是操作前后 Private Bytes/Working Set，以及进程历史 Peak Working Set；不是每操作精确峰值。三轮不能单凭增长或下降判定存在/不存在泄漏。
- 尚未直接测得严格的主线程最长连续冻结时间、各操作精确峰值内存和长时间释放所有 Python 引用后的内存斜率。方法区间、heartbeat 与生命周期 Peak Working Set 是替代证据，不将这些验证缺口记为通过。本轮未追加更长压力测试或扩展 Correlation/插值算法优化。
- 历史 v4.3.5 全量：1241 项、1238 通过、3 项耗时失败（Map 关闭、Dirty、Writer）。本轮结果另列，不以历史结果代替当前验证。

## 回滚与停止边界

修改仅保留在当前工作区。需要回滚时，按本报告文件清单从本轮 diff 反向撤销自己的补丁；不得 reset/clean 用户工作，也不得回退整个仓库。未修改 WKB/Recovery 协议、Undo 事务、OLS、P1-A 或 Workbook 总体刷新架构。完成本轮验证和报告后停止，不进入 P2。
