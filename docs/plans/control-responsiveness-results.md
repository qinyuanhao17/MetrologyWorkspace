# 控件响应优化实施与验证记录

日期：2026-10-07 至 2026-10-08。范围：延续本地当前版本，保留原有未提交工作；没有发布、打包、修改用户设置或保存原始桌面 WKB。本轮是[完整方案](control-responsiveness-optimization.md)的一部分，不代表六个阶段全部完成。

## 根因与本轮修改

| 可观察问题 | 已验证的原因 | 实施 |
| --- | --- | --- |
| 大 Raw Data 表 Ctrl+A / 回到单个格 | Qt header 检查整列是否选中，逐行调用 Python flags | 普通等权限 sheet/projection 用选择范围计算 header 高亮；自定义禁用单元格 model 保留原 Qt 路径；复制、清空和 Undo 仍映射到原始行 |
| Preview/Final 热态切换 | 重建图、mapping 控件及同源分组准备 | 保留每个 stage 的绘图实例，最多两套；来源/映射/身份变化仍失效；最多两个分组准备快照 |
| Group Apply | 同一个有效输入重复构造 GroupPlan；隐藏 Group plots 也立即绘制 | 复用已验证的当前准备；隐藏页保留最新逻辑结果，显示/导出时画当前结果 |
| 联动子窗口重复工作/切回图页 | 多个 setter 发布中间选择；最后一次恢复绘图改变堆叠页 | 完整输入事务只发布一个最终 plan，结束后恢复用户正看的子页；未变的 Preview Map 不重新加载 |
| 大 NOVA Trend Ctrl+wheel | 全数据虚线 QPainter.drawPath；zoom 时重建未变的 scatter | 保留完整数组与动态范围保护；单个持久进程独占 QImage，绘制原始全路径；GUI 只显示完成的图像 |
| 保存过的 Correlation/Trend 恢复 | 每 wafer 的宽表 assign/dropna/sort 多次复制 | 先计算有限 Die Seq 的稳定行顺序，再取一次表；保留缺失参数、真实 Die Seq 和非 RangeIndex |
| Map 恢复 zoom 被旧布局任务覆盖 | unowned Fit-width 回调在显式恢复之后执行 | QObject 所有的可取消、合并 timer；执行时再检查当前 zoom，restore 停止旧任务 |

绘图后台任务仅携带序列化的 QPainterPath/QPen/transform 和尺寸，不携带 widget、Qt model、scene item 或 live artist。每条曲线最多一个已提交任务和一个最新请求；旧数据 revision 的图像不会提交。屏幕缓存最大 4,000,000 像素/条曲线，超出或遇到不支持的画笔/填充走原绘制路径。缩放过程中可暂时变换同一数据版本的旧完整图像；完成后使用精确新图像。首次进程启动/图像生成不是同步完成的，等待指针提示仍在绘制。

Qt QWidget PNG 捕获和 PyQtGraph export mode 始终绘制当前完整路径，不导出屏幕预览缓存。没有减少点数、改变拟合/插值、忽略 NaN、放宽阈值或改变文件格式。Windows spawn 启动入口加入 freeze_support；源码已测试，冻结 EXE 尚未重新打包验证。

## 测量方法

基准源码冻结于本轮开始的独立 scratch 目录；它包含当时已有用户改动，而非只取 Git HEAD。主要夹具为桌面 `matching-analysis_nova_multi_param.wkb` 的只读冻结副本，7,731 行、33 列、3 个实际映射参数。fixture SHA256 为 `2e5c35c62af4b8b7ab917b1f46444db0538c87430cca43942805e3e89af7be18`。用户在早期测量之间修改过桌面文件，所以不混用不同 hash 的数据。

固定 Windows conda Python、Qt offscreen、1500 × 950、新建 scratch 设置/recovery；前后使用同一个 `benchmarks/benchmark_controls.py`，独立进程顺序执行。热态每项 30 次。10 ms timer 的最大间隔覆盖直接回调和后续 400 ms 的布局/dirty/重绘；P95 是该 30 次样本的经验分位数，不是统计置信界。首次打开包括已保存状态恢复；`open_call_ms` 与包含固定 600 ms settle 的 `open_settled_ms` 分开，后者不能当作加载时间。

普通滚轮滚动与 Ctrl+wheel 缩放分别测量。对可见目标 Trend，额外等待完整曲线图像完成并记录 `render_ready_ms`，不会把按钮返回或预览图像当作最终绘制完成。离屏结果不等同于真实 Windows 连续滚动帧率。

可见主窗口 Trend 的固定夹具 30 次实测：

| 操作 | 优化前 GUI gap P95 / ms | 优化后 GUI gap P95 / ms | 前/后完整目标绘制 P95 / ms |
| --- | ---: | ---: | ---: |
| All parameter Trend Ctrl+wheel | 216.86 | 48.54 | 187.12 / 105.66 |
| All parameter Trend 普通滚动 | 75.83 | 21.92 | 75.80 / 23.06 |
| Correlation Trend Ctrl+wheel | 60.38 | 56.05 | 85.41 / 81.49 |
| Correlation Trend 普通滚动 | 22.84 | 22.30 | 23.49 / 22.82 |

以实际显示的目标图验证，不使用早期隐藏页的 146 → 39 ms 作为最终结论。图就绪和心跳间隔的分位数不是同一个采样序列；后续 400 ms 内还会发生 layout/dirty 工作，所以 GUI gap P95 不必小于 render-ready P95。

原始 JSON：scratch `performance-audit/nova-visible-wheel-before.txt`、`nova-visible-wheel-after.txt`。最终控件 30 次实测（同一冻结夹具）：

| 操作 | 前/后回调 P95 / ms | 前/后 GUI gap P95 / ms |
| --- | ---: | ---: |
| Ctrl+A | 0.30 / 0.59 | 294.09 / 21.68 |
| 全选后单格点击 | 0.46 / 1.05 | 21.46 / 21.76 |
| Preview/Final | 2384.16 / 68.95 | 2388.27 / 77.54 |
| Group Apply | 892.99 / 59.33 | 893.01 / 118.45 |

单格点击在本夹具中原本即较快；另有筛选投影表回归测试覆盖 8,000 行。首次未缓存 stage 的本次最大间隔仍为 653 ms，不混为热态响应。Stage、Group Apply 尚未达到方案的 50 ms 目标。原始 JSON：`nova-controls-final-before.txt`、`nova-controls-stable-after.txt`；未保留任何失败绘图方案作为交付实现。

真实 WKB 验证中遇到 Qt 原生 access violation。冻结旧版本正常；原绘制路径及原曲线实例对照缩小到新缓存的 Python QObject.destroyed 清理连接，仅断开该连接即通过。最终使用独立 QObject 缓存和原生 QGraphicsPixmapItem，不替换原生曲线、不覆盖其 Qt paint；任务清理由 weakref.finalize 捕获的 plain Future holder 执行，Qt owned timer 在 owner 销毁时自动停止。源数据、线型和导出保持完整。失败诊断的六个孤立 worker 经父 PID/启动参数核实后清理，没有关闭用户程序。

## 已建立的正确性验证

- 8,000 × 33 筛选/倒序投影表：真实 Ctrl+A 和单格点击，清空/Undo，原始源行映射、完整字符串及 dirty 状态。
- Preview/Final 独立数据、不同 Card，多次切换/Group Apply，保留已有布局和视图。
- 联动子窗口发布一次完整选择；选择面板、页号、zoom/scroll 不随父编辑跳转。
- 16,000 点/800 wafer Trend：实际 Ctrl+wheel，完整数组与点数保留，已有 100 ms 门槛不变。
- 6,000 点虚线含 NaN 缺口与窄峰：后台屏幕与原 Qt 全路径画法逐像素相等；新数据 revision 再比较；1× / 1.5× DPR 分别验证。
- 稀疏/非法/重复 Die Seq、非连续原始 index、preserved group order，输入表不修改。
- Map resize 先排队、之后显式恢复 200% 和横向偏移 70，旧 Fit-width 不覆盖最新视图。
- BDD 场景及其 executable unittest 对应关系见 `docs/features/control_responsiveness.feature` 和 `docs/features/README.md`；场景文件本身不充当测试通过证据。

真实输入验证日志：scratch `performance-audit/control-fixtures-final.txt`。7 个桌面 WKB（2 TEM、1 KLA、4 NOVA，含 6,958/7,731 参与行）全部通过完整 snapshot 往返、源字符串/顺序保留、独立斜率/截距/R²、Card/Bias/Bias % 以及 Group 去重/参与检查；3 个 sample CSV 导入通过，每个输入的前后 SHA256 相等。原件不写入，roundtrip 仅写 scratch。

恢复时的重复来源准备、Reference choices 刷新已合并；无来源的合法 draft 仍走完整验证/识别回退。相关 59 项 Correlation、恢复与 invalid draft 测试通过。全量结果另行记录，不用 targeted pass 替代 full suite。

最终全量 `python run_tests.py`：533 项，532 pass、1 performance fail，242.617 秒。唯一未过为 `test_saved_correlation_restores_complete_grouped_plots_promptly`：2.011 秒 > 原 2.000 秒预算；此项之前的来源、选择、完整绘图、数值及原始表格断言通过。冻结旧版本同项独立运行 2.051 秒 > 2 秒；当前 focused 59 项通过，但全量上下文仍未稳定低于门槛，因此不宣称全套通过、不放宽预算。日志：scratch `performance-audit/control-full-tests-final.txt`、`correlation-restore-no-duplicate-tests.txt`。没有新的 Qt 原生崩溃或 deleted-object 异常。测试的故意失败保存/文件移除路径仍会输出预期 diagnostic traceback；现有 modal 确认测试的一条 timer 回调也会记录 NoneType warning，不把它当成应用全量零告警。

`git diff --check` 通过（只有 Windows 行尾转换提示）。`config/settings.yaml` SHA256 保持 `d8a7fe3bf22ed512b0f67bf91ed9dd4452ed5c5e1fa92a153f7fe754b14970e3`。

源码启动 `main.py --self-test` exit 0，四个按需加载的工具均可构造并卸载。设置/recovery 使用 scratch；未打包新的 EXE。实施结果需要重新启动加载源码的应用才能生效。

## 尚未完成的方案部分

尚未实现完整的版本化编辑差异/数值准备缓存、文档级 latest-only 后台分析调度、dirty 分片账本、后台正式 WKB Save/导出写盘、异步 WKB 打开、独立 Agg Map 渲染或 20–30 分钟原生 Windows 长会话。首次切到未构造 stage 仍有冷态构建成本；源数据编辑/批量替换的整轮计算尚未全面移出 GUI。部分 Correlation Trend 的完整重绘仍高于 50 ms，不能宣称所有延迟消失。

本轮不改变 recovery 周期和存储安全合同；沿用用户现有恢复设置。

## 2026-10-08 03:05 单次续跑：首次使用与恢复

本次续跑冻结的是启动本轮时的整个未提交工作区，不是 Git HEAD 或上一轮优化前代码。生产代码基线放在 scratch `cold-start-audit/baseline`；原有改动全部保留。桌面多参数 NOVA 仍为 7,731 × 33、3 个 mapping，SHA256 为 `2e5c35c62af4b8b7ab917b1f46444db0538c87430cca43942805e3e89af7be18`。原 WKB 只读；衍生保存夹具、settings、recovery、Matplotlib 字体缓存均在 scratch。

新增 `benchmarks/benchmark_cold_workbook.py`，每个冷态样本使用独立 Python 进程，设置和字体缓存也是新的；不宣称清空了操作系统磁盘缓存。固定窗口 1500 × 950，10 ms GUI 心跳。分别记录回调返回、回调之后首次可验证最新数值状态、完整绘图/布局及实际视口重绘；第二项是结果当前的观察上界，不是纯拟合耗时。完整图等待全数据曲线任务结束，不把 selector、准备页面或按钮先返回算作绘图完成。心跳还观察操作后的 150 ms 排队工作。离屏重绘不是原生 Windows 帧率。

同一个进程内的首次、再次操作分别标记；Correlation-first 和 Map-first 用不同的独立进程，避免已导入 Matplotlib/SciPy 的 Map 被冒充为首次库加载。测试 Correlation 绘制时明确选全部 6 个来源参数、全部 1,530 个可用曲线格，并将该测量窗口的 R² 显示门槛设为 0，避免正常被筛掉的拟合被误计为空图完成；不修改原 WKB 或统计计算。Map 绘制为 2 wafer × 2 参数的有界样本，不代表一次画全部 255 wafer。

保留的修改：

- Trend 按原始行位置先筛选和稳定排序，再一次提取**所有源列**；不丢弃未映射列、非连续/重复 index、无效 Die Seq、重复 Die Seq 或字符串。
- 每个 Trend 参数的 wafer 边界仍全部存在，但合并为一个绘图对象。边界不参与数据 auto-range。原尺寸及缩放后的 Qt 图像与逐条原生 InfiniteLine 逐像素相同。
- Correlation Trend 的来源曲线也使用现有全分辨率曲线绘制模块，减少范围变化时重复构建散点。没有引入降采样、插值变更或新的 GPU/绘图依赖；屏幕/导出仍用原数据。
- 恢复 Correlation 的保存选择前取消被旧输入排队的自动 Trend 绘图，避免 Correlation 拟合处理 Qt 事件时提前重画 Trend、随后再按保存的格子重画一遍。新增确定性回归还证明：保存状态要求等待 Draw 时，旧任务不得自行画图。冻结版本该测试失败，保留实现通过。
- Correlation 的即时 dirty 比较使用 GUI 线程内只读状态视图；接受基准在 `mark_clean` 内只深复制一次。正常保存/恢复快照仍隔离，worker 不接收可变 GUI 状态视图。Save/Discard、revision、锁、校验、原子替换和恢复文件合同未改。

一次横轴字体宽度缓存实验把首次 stage 同步回调从约 658 ms 增加到约 721 ms，虽有部分后续绘图耗时变化，仍撤掉。`cold-final-*`、`cold-map-final-*` 是该未保留实验的日志，不能作为交付数字。

下表为原 NOVA WKB、Correlation-first 各 3 个独立进程的中位数。基线日志 `cold-base-1..3.txt`，保留实现日志 `cold-after-1..3.txt`。单位 ms；回调与数值状态不同步时，数值列单独给出。

| 操作 | 回调 前 / 后 | 完整图或工作区重绘 前 / 后 | GUI 最大间隔的中位数 前 / 后 |
| --- | ---: | ---: | ---: |
| WKB 首次打开 | 2225.86 / 2164.15 | 2449.22 / 2393.08 | 2225.87 / 2164.17 |
| Preview/Final 首次切换 | 657.61 / 661.35 | 939.52 / 942.20 | 657.62 / 661.36 |
| Preview/Final 热态切换 | 75.62 / 75.09 | 225.37 / 225.90 | 75.63 / 75.11 |
| Group settings 首次打开 | 1.15 / 2.11 | 76.91 / 80.39 | 56.30 / 58.60 |
| Group Apply，无变更 | 54.77 / 55.83 | 104.19 / 104.69 | 54.80 / 55.85 |
| Group Apply，切换 Head groups | 736.73 / 740.65 | 1243.40 / 1256.25 | 736.75 / 740.66 |
| Raw Ctrl+A 首次 | 0.17 / 0.18 | 96.34 / 96.49 | 56.66 / 57.83 |
| 全选后首次单格点击 | 0.46 / 0.41 | 53.07 / 50.93 | 33.84 / 31.05 |
| Mapping 首次 uncheck | 1.41 / 0.95 | 174.85 / 172.57 | 71.97 / 71.38 |
| Mapping 再 check | 1.54 / 1.42 | 431.89 / 434.77 | 336.37 / 336.30 |
| Correlation/Trend 子窗口首次打开 | 2458.87 / 2333.24 | 2489.74 / 2363.36 | 2458.90 / 2333.27 |
| Correlation 首次实际绘图 | 420.51 / 453.21 | 665.92 / 698.86 | 415.00 / 447.91 |
| Trend 首次实际绘图 | 1481.38 / 806.47 | 1647.35 / 918.76 | 1481.40 / 806.48 |
| Trend 再次绘图 | 1532.82 / 741.00 | 1682.40 / 832.21 | 1532.84 / 741.02 |
| 已打开 Correlation 恢复完整绘图状态 | 2993.66 / 2175.78 | 3259.11 / 2382.66 | 2144.52 / 1336.73 |
| Map 打开（此前已开 Correlation） | 441.14 / 443.46 | 462.44 / 464.32 | 441.17 / 443.52 |
| Map 首次绘制 4 张图 | 2.48 / 2.49 | 1056.85 / 996.30 | 380.93 / 409.60 |

Mapping uncheck 的当前数值状态中位数为 60.59 / 57.67 ms；check 为 336.35 / 337.72 ms。表格操作的完整时间包含主动重绘工作区里未改动的图，不能当作表格本身的耗时。WKB/子窗口启动仅小幅变化，首次 stage、Group 变化、Mapping、Correlation 首绘没有实质改善；Map 主线程绘制仍存在，不能宣称这些阻塞已解决。真实 NOVA 6 参数恢复仍约 2.4 秒完整完成，与 6,000 行、2 mapping 的原 2 秒测试不是同一夹具。

新增回归：`test_first_wide_trend_draw_preserves_all_source_columns_promptly` 在冻结实现首次失败为 1.314 秒 > 1 秒，保留实现通过；原 2 秒 Correlation 恢复预算不变。`test_batched_wafer_edges_match_native_lines_after_zoom` 检查像素等价；`test_restore_disabled_trend_does_not_run_old_queued_draw` 覆盖错误自动绘图。两个旧测试改为检查实际全部边界位置，不再要求每条边界必须是独立 Qt 对象，数值断言未减少。

Map-first 的 3 次独立进程（`cold-map-base-1..3.txt`、`cold-map-retained-1..3.txt`）：首次 Map 打开回调中位数 1159.15 / 1137.62 ms，完整工作区 1179.47 / 1158.47 ms，GUI 间隔 1159.17 / 1137.65 ms。两版均存在首次 Matplotlib/SciPy 加载阻塞，不能拿已开 Correlation 后的 440 ms 当它的冷态耗时。

另外用实际窗口保存一个全新 scratch WKB，包含已经画好的 Correlation、Trend 和 4 张 Map，未覆盖任何既有夹具；SHA256 为 `3ac9cf4eac0b0cddca53bdbdb8e4da5fb9cafac19f6e2c5264eba271c5842e30`。每版 3 次独立进程读这个相同文件（`cold-saved-base-1..3.txt`、`cold-saved-after-1..3.txt`）。保存状态的第一次子窗口打开必须等候恢复图完成；Map 的 debounce、SurfaceJob 和实际绘制也计入，不能因 callback 已返回而认为完成。恢复后的 Curve 元数据标记 `already_drawn: true`，之后的显式 Draw 是再次绘制，不当作首绘。

| 保存图窗夹具的首次操作 | 回调 前 / 后 / ms | 当前结果可验证 前 / 后 / ms | 完整工作区 前 / 后 / ms |
| --- | ---: | ---: | ---: |
| WKB 读取与主窗口状态恢复 | 2511.47 / 2398.78 | 2511.47 / 2398.78 | 2813.67 / 2691.61 |
| 第一次 Preview/Final 切换 | 666.75 / 671.51 | 666.75 / 671.51 | 999.94 / 1001.68 |
| 第一次打开并恢复 Correlation/Trend | 5689.43 / 4812.77 | 5689.44 / 4812.78 | 5844.73 / 4900.03 |
| 第一次打开并恢复保存的 Map | 974.90 / 986.21 | 1837.97 / 1851.93 | 1988.79 / 2000.68 |

恢复 Correlation/Trend 仍有约 3.08 秒最大 GUI 间隔，保存的 Map 完整恢复仍约 2 秒；这些冷态路径没有达到“100 ms 内加载提示、GUI 保持响应”的方案目标。衍生 WKB Save 的单次回调 1587 ms，仍同步；不是后台 Save 已实现的证据。最早一次写既有 scratch 夹具正确触发了覆盖确认，基准进程被终止；最终测量只使用全新目标。新的基准入口会拒绝已有目标，避免离屏等待确认，也没有绕过软件的覆盖保护。

真实可见 Correlation Trend 的 30 次操作（`wheel-baseline.txt`、`wheel-current.txt`）：Ctrl+wheel 回调 P95 51.53 / 4.27 ms，完整当前曲线 P95 76.87 / 29.86 ms，GUI 间隔 P95 51.54 / 33.86 ms、最大间隔 60.50 / 34.63 ms。普通滚动完整曲线 P95 24.13 / 24.62 ms，GUI 间隔 P95 23.58 / 24.65 ms，原本即较快，没有实质改善。完整数据与导出验证另由回归测试覆盖，不以缩短数据数组换取滚轮时间。

独立进程启动 shell 3 次（`startup-baseline-*`、`startup-current-*`）的完整首显中位数 334.71 / 333.77 ms，分析模块均未预载，软件 shell 启动没有退化，也没有明显改善。WKB 和图窗成本没有偷移到 shell 启动。

补充真实 shell 的第一步 Open：`benchmark_startup.py --wkb FILE` 直接执行 shell 的 `load_path`，包含首次 MatchingWindow 导入、文件类型路由和完整工作区创建，不将导入漏算在首次按钮里。各 3 个独立进程（`shell-wkb-baseline-*`、`shell-wkb-current-*`），回调中位数 2955.57 / 2889.25 ms，完整主图 3115.03 / 3049.87 ms，GUI 间隔 2956.23 / 2889.91 ms。两版都是阻塞；上表约 2.4 秒的 MatchingWindow 加载不能替代这个约 3.05 秒的真实首打开入口。此基准使用 shell 在离屏屏幕上的默认窗口尺寸，与固定 1500 × 950 的控件基准分开解释。

最终验证：

- `python run_tests.py`（通过 runner 的 scratch 设置入口执行）：**536 项全部通过，244.814 秒**。原 `test_saved_correlation_restores_complete_grouped_plots_promptly` 的 **2.000 秒预算未改并通过**；新首次宽表绘图 1 秒预算也通过。日志 `cold-start-audit/full-tests.txt`。不把此项的通过解读为所有真实 NOVA 图窗都已在 2 秒内完成。
- 针对性 Correlation、Trend、文档存储及性能回归 138 项通过；新的禁止旧排队 Draw 回归另有冻结红/当前绿记录。
- 1× 和独立进程 `QT_SCALE_FACTOR=1.5` 的 wafer 边界及全分辨率虚线屏幕/导出像素等价测试通过；包括 NaN 缺口、窄峰、线型与数据 revision 改变。日志 `boundary-pixels.txt`、`pixels-150.txt`。
- 7 个桌面 WKB 全部再次通过独立公式拟合、完整 snapshot 往返、参与行及 Group 检查；3 个 sample CSV 再次通过导入。每个原文件 SHA256 前后相等，日志 `fixtures-final.txt`。当前 sample_data 没有 Excel，未声称测试了不存在的 Excel。
- `main.py --self-test` exit 0，4 个按需加载的工具可构造/卸载；未打包 EXE。`git diff --check` 通过，仅有 Windows 行尾提示。原 `config/settings.yaml` SHA256 仍是 `d8a7fe3bf22ed512b0f67bf91ed9dd4452ed5c5e1fa92a153f7fe754b14970e3`。
- 全量日志仍包含既有测试 modal timer 的一次 `NoneType.confirm_button` warning，以及故意失败保存/移除文件测试的预期 diagnostic traceback；不把 unittest 成功当作全量零告警。没有新的原生崩溃或 deleted-object 异常。

仍未完成：文档级 latest-only 后台输入准备/分析、非阻塞首开/子窗口恢复、首次 stage 的分片或复用构建、Map 的 GUI 渲染隔离、后台正式 Save、原生 Windows 长会话验证。仅切换 Head groups 的首次 Apply 仍约 0.74 秒主线程阻塞；真实首开约 2.89 秒阻塞、保存 Correlation/Trend 首次恢复约 4.90 秒完整完成。下一步仍应按原方案的版本/所有权约束移出或分片这些工作，不再靠控件先返回或只测热态作完成结论。

本次沿用上文引用的 python-performance-optimization、diagnosing-bugs、systematic-debugging 进行归因和单变量对照；tdd 保留原预算并补充公开行为测试，codebase-design 将边界绘制收在已有绘图模块，ponytail 避免新框架和全目录改动，scientific-visualization 要求保留源数据、全部边界、NaN 和完整导出并验证像素等价。本次是单次续跑，没有新建任务、重复调度、打包或发布。

## 方法与参考

按用户指定的 [python-performance-optimization](<C:/Users/Yuanhao Qin/.codex/skills/python-performance-optimization/SKILL.md>)、[diagnosing-bugs](<C:/Users/Yuanhao Qin/.codex/skills/diagnosing-bugs/SKILL.md>)、[systematic-debugging](<C:/Users/Yuanhao Qin/.codex/skills/systematic-debugging/SKILL.md>) 执行复现、归因、单变量实验与原门槛回归。线程绘制仍因 Qt/GIL 阻塞；drawPolyline 的改善不稳定，均未保留。codebase-design 限制修改在现有准备/子窗口/绘图 seam，ponytail 避免全目录搬迁和新依赖；tdd/bdd 将触发路径连接到可执行测试。

Qt header 原生选择扫描参考 [Qt qheaderview.cpp](https://github.com/qt/qtbase/blob/6.11/src/widgets/itemviews/qheaderview.cpp)。后台绘制遵循 [Qt threading and painting](https://doc.qt.io/qt-6/threads-modules.html) 的独立 QImage 所有权；没有后台 QWidget 绘制。

scientific-visualization 影响了保留全部观测点、NaN 缺口、峰值、当前导出和像素等价验证。方法引用：Timothy Kassis, Vinayak Agarwal, Yuhuan He, Darshil Patel, Aubrey M. Brueckner, *Scientific Skills: The Missing Layer Between AI Agents and Scientific Expertise*, 2026, [doi:10.48550/arXiv.2609.00065](https://doi.org/10.48550/arXiv.2609.00065)。这不是性能数字的来源；性能依据为本地测量。
