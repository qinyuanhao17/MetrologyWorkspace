# P1 第一阶段：内存与持久化基准（2026-10-26）

## 范围、入口和发布边界

本轮在同一目录、分支顺序执行，没有 worktree 或并行 agent。
实际入口为 `79b5910550b05f6888053a4bc0408b798b8d8f39`，不是 `017c10d`。
已读 AGENTS.md、CONTEXT.md、P0 审核 Markdown/JSON 及后续进度。
旧 P0 的 1083/1083、68/68、240 Dirty 和 120 Map 是历史证据；最近一次
全量为 1095 项、1091 通过、4 项耗时断言失败，1062.839 秒。

用户先授权发布入口代码，再要求 P1 仅保留本地。
已创建并只推送 `refs/tags/v4.3.2:refs/tags/v4.3.2`，tag object 为
`ef3c357540e7bfbf6c0501c50c665001d7ca5034`，解引用到上述入口。
推送前后所有远端 heads 一致：仅 main，SHA
`aa5281dd38bbe58688a51b27e86c70635aef7a77`。没有推分支、打包或创建 Release。
AGENTS.md、.vscode/settings.json、docs/todos/ 的用户工作不纳入本轮提交。

## 基准方法

复用 `run_tests.isolate_settings()`、现有 Windows `memory_info()`、Shell
真实组件创建/关闭、WkbDocument/WorkspaceSnapshot 及现有绘图调用。
新增 `benchmarks.benchmark_memory_storage`，可设置循环数、行列数、场景、
绘图 wafer 数、GC 周期、原生/offscreen 平台、tracemalloc 和 JSON 输出。
只能输出专用 JSON，不能把配置或工作文档作为输出目标。

合成数据逐列保持原文字串：Die `001`、12 位小数、显式 Cycle/XY/身份列。
30/33 是完整 Raw 列数；映射两个参数，其他量测列完整保留。
每种规模/场景使用独立进程，CPU 密集任务顺序运行，不并行跑测试。

- Workbook：打开、单格编辑、Undo/Redo、保存、新编辑、两次后台 Recovery
  请求交错、恢复到新窗口、重新读取正式文件，校验正式文件哈希、原文字串、
  恢复快照和分析 summary，再关闭。
- Mixed：同一 Workbook 下 Correlation/Trend、Map/Radius、Dynamic 同时存在，
  绘图后切换映射、分组、Final/Preview，再编辑、Undo/Redo 和关闭。
  最终 verified 运行明确给 Dynamic 独立完整宽表，按现有规则只选一个
  measurement set、两个参数，并逐列核对除既有推导 Cycle 外的源字符串。
- Tasks：真实 SurfaceJob 完整绘图后再次启动工作并立即关闭，等待取消队列
  完成，检查没有迟到发布或永久任务资源。10k 选择 10 wafer × 2 参数；
  100k 压力场景选择 12 wafer × 2 参数，完整表仍保留。
- Settings：真实模态设置窗口连续 Cancel；专项测试另覆盖两个持久应用进程
  交替保存、冲突后的显式重新加载和八次取消。

每轮记录打开时、关闭后 GC 前和可选 GC 后：Private Bytes、Working Set、累计
Peak Working Set、Windows handles、Python/Qt 线程、Qt 对象/窗口/计时器、
活动文档、SurfaceJob/取消队列、DataFrame/Figure/PlotDataItem/ImageItem。
最终 traced 运行还记录 `tracemalloc.get_tracemalloc_memory()` 的跟踪器簿记开销。
另记累计 CPU 时间、执行时间和 20ms Qt heartbeat 最大 gap。
Qt 计数为从应用/顶层窗口可达的原生子对象，不等于全部 C++ 分配；Python
线程数不等于 Windows 全部线程。GC 是诊断干预；另有自然 GC 对照。
Tasks 的关闭后采样发生在取消队列排空之后；不能将它解释为关闭瞬间已经
释放仍在执行的原生计算输入。结果列表、Shell 有界日志和采样本身也占内存，
原始数值不作主观扣除，tracemalloc 留存差异单列观察器开销。
计数和 tracing 会扰动耗时，均不是 DWM FPS 或 P0 流畅度验收。
测试窗口以自有 force_close/Discard 结束；真实 Save/Cancel/关闭决策由持久化
专项分别验证，不把此关闭耗时冒充完整用户交互延迟。

初版 mixed/tasks 只设置图面选择，未确认 Data 页选择，且 Dynamic 默认为空；
这些原始记录只作为窗口/同步生命周期证据，**不算已完成绘图压力验收**。
后续改为先等待数据就绪、显式选择 Data 页 wafer/参数，再绘制实际存在的 tab，
必须检查 Map 场景数、Radius 序列数、Correlation fit、Trend panel 与 Dynamic
pivot 均为正数。2000 行、多 wafer、非空 Dynamic 的公开 CLI 回归先失败，修正
测试入口后通过（15.629 秒），防止再次把“没出错”当成“已绘图”。

## 已确认的问题与风险处置

### 采样工具的 ctypes 类型留存：已作局部修复

tracemalloc 的留存差异中出现原 `memory_info()` 内部反复定义的 Counters。
每次观察都创建新 Structure 和 POINTER 类型；ctypes 全局类型注册表强引用
这些类型。真实采样 25 次，注册表从 21 增至 46，专项实际失败。
这属于观察器自身，不能当成生产窗口泄漏，更不能用它解释全部 Private 增长。

最小修改只在 `benchmarks/benchmark_correlation_restore.py` 缓存一份固定计数
结构体和 Win32 查询签名，字段、Private/Working Set/Peak 定义不变。
同一 warmed 25 次采样回归现在新增类型为 0；新增生命周期 8 项全部通过，
13.071 秒。原始和修正采样器的运行分开保留，不修饰旧数据。
没有修改生产模块。回滚只需 revert 该工具 checkpoint。

另一个假设是 Shell 长期保留关闭的 Settings 对话框。真实模态 Cancel、排空
DeferredDelete 并 GC 的 12 轮回归已通过；该假设未被证实，未改 Shell。

### 子窗口滞留的观察器假象：已否定生产归因

补充“母 Workbook 始终打开”的探针最初发现每轮保留 3 个关闭子窗口；
2000×8 的两轮采样 widgets 3577→5747、Figure 9→18。单独断连
`owner.match_type.currentTextChanged` 不消失；仅 deleteLater 或两者组合
虽删除原生 widget，Python 包装对象和 Figure 仍被保留。故不能由这些曲线
直接修改生产销毁逻辑。

根因是探针使用 `patch.object(..., return_value=...)` 创建的 QMessageBox
MagicMock 记录调用参数，强引用传给弹框的子窗口。只把探针默认应答改为
**不保存参数的普通函数桩**，无需 disconnect/deleteLater，母窗口保持打开
时两轮即为 0 存活子窗口、widgets 固定 1407、Figure 0；Raw 和分析 summary
仍精确相同。当前相同源码的 `--record-dialog-calls` 红灯与非记录桩绿灯
作为单变量对照保留。前述“生产生命周期异常”判断撤回。

这也说明 `run_tests.isolated_suite()` 的默认记录型对话框 Mock 不宜直接
用来测长时间资源趋势。它在常规功能测试中可以保留调用证据，本轮未修改
整个 runner，也未将全量两个耗时失败归因于它。主基准采用 force_close，
记录的本轮窗口弱引用均已归零；真实 Discard 生命周期另用非记录桩补测。
没有据此修改 `configure_workbook_owner()`、`closeEvent()`、浮窗、Qt flags
或父子状态协议。

### Settings 嵌套可变值共享：仅提交证据，等待所有权审核

命令 `python -m benchmarks.probe_settings_ownership` 在独立临时配置下预期退出 1。
`get_settings()` 返回的 `trend_overlay` 与活动配置共享；缺省配置下还与
DEFAULTS 共享。调用方仅修改返回值、未保存，活动值和下一次缺省加载已改变，
磁盘文件此时不存在。该探针确认公开访问器边界的别名，不等于已证明实际 UI
取消会丢数据；正常取消专项仍应保持磁盘和内存不变。

根因为 `dict(DEFAULTS)`、`_current.update(DEFAULTS)` 与返回 `dict(_current)`
只复制外层。只改 getter 不足以切断加载默认值、保存候选和调用方之间全部别名。
此项涉及状态所有权，按用户要求，本阶段不擅自修改。

后续方案：在 `settings.load_settings/get_settings/save_settings` 明确可变值
所有权，审查 DEFAULTS、返回快照、save 输入及 expected 比较四个边界；先增加
嵌套修改、重新加载、两实例、冲突、取消和保存失败回归。不得趁机改 YAML
协议、默认值、字段归一化或文档 overlay 语义。

### 崩溃后的孤立临时 YAML

复用现有故障 seam，在子进程最终 `os.replace` 前 `os._exit(17)`。
原 YAML 字节不变；下次加载/保存可回收死进程锁并成功，但仍留下一个
468 字节 `.settings.yaml.*.tmp`。正常异常路径的临时文件清理已有回归。
这是崩溃后的孤立文件问题，未发现静默覆盖。不要按文件名/年龄直接删除可能
属于活跃实例的候选文件；清理归属与恢复政策交给后续阶段审核。

## Settings / WKB / Recovery 验证

未重复实现原子写入、冲突检测、损坏保护或 overlay 隔离。
现有 Settings、WorkspaceStore、DocumentStorage、StorageV2、Recovery
所有权/帧共享、MatchWorkbook 旧 schema 与往返测试，加新增循环测试，
首轮完整专项 130/130 通过，105.109 秒。
权限上下文更新打断过一次尚未完成的专项进程，该中断日志没有算作通过。

已覆盖旧 WKB schema、原文字串/列序、保存与备份失败、最终 revision 冲突、
损坏/未来版本拒绝、父子草稿、后台恢复与继续编辑、取消另存与关闭、迟到结果
失效、正式文件保持有效。新增 20 次排队 Recovery 取消确认：单写线程仍被阻塞时，
已取消请求的大帧就能释放，不必等队列实际排空。
WKB 格式、数据协议、业务语义和 Recovery 提交顺序均未修改。

## 趋势、最终测试和 checkpoint

原始完整采样保存在会话自有 `p1-memory-storage-20261026` 目录，文件哈希与
逐轮数据将收录到 `docs/validation/p1-memory-storage-baseline.json`。

以下为关闭后数值，MiB = 2^20 bytes。早/晚分别为前/后 1/3 样本中位数，
不足三项时为首/末样本；不是不同进程的相减，也不是性能提升百分比。

| 场景 | 轮数 | Private 早→晚 MiB | Working Set 早→晚 MiB | 最大 Qt gap |
| --- | ---: | ---: | ---: | ---: |
| 10k×30 Workbook | 20 | 1296.78→1398.05 | 423.97→487.75 | 5633.49 ms |
| 10k×30 verified Mixed | 12 | 1364.75→1448.72 | 433.88→467.63 | 5500.86 ms |
| 10k×30 verified Tasks，20 maps/轮 | 12 | 1219.98→1262.67 | 353.12→394.44 | 5863.43 ms |
| 10k×30 Workbook traced，修正采样器 | 8 | 1351.04→1540.87 | 475.87→609.44 | 8113.62 ms |
| 10k×30 Workbook 自然 GC | 8 | 1474.72→1500.51 | 606.91→632.83 | 5179.57 ms |
| 100k×33 Workbook | 3 | 1672.86→1771.09 | 736.91→802.79 | 30508.40 ms |
| 100k×33 verified Mixed | 3 | 1705.38→1820.17 | 708.30→761.80 | 26405.18 ms |
| 100k×33 verified Tasks，24 maps/轮 | 3 | 1523.24→1557.05 | 658.43→650.12 | 25740.15 ms |
| Settings 真实模态 Cancel | 20 | 1108.90→1109.54 | 240.66→240.51 | 92.28 ms |

Workbook 的循环包含保存、恢复、重新打开等多项操作，正式文件路径每轮不同，
recent 列表按原规则增长到上限；Mixed/Tasks 重用同一输入路径。不同场景、
是否 tracing、是否有真实 Dynamic 数据不能混成同一个配对性能结论。

关闭并显式 GC 后，已完成的主要场景保持 Shell 的 82 个 widgets、157 个
可达 Qt 对象（包括基准 heartbeat）、0 活动文档、0 本轮窗口包装对象。
Figure、SurfaceJob、PlotDataItem、ImageItem 均回到 0；固定 1 个 DataFrame
不随轮次增加，其身份尚未单独归因。Recovery 场景留下一个按设计常驻的
单写线程；绘图任务场景的取消队列最终为空、Python 线程为 1。
自然 GC 对照在采样时保留约 2 个本轮窗口包装对象，显式 GC 对照归零。
这支持“部分对象是待循环 GC 的垃圾”，不能推导所有 Private 增长都是垃圾。

修正采样器的 8 轮 Workbook traced 中，存活 traced 内存约 13.57→13.80 MiB，
跟踪器簿记约 15.05→15.15 MiB，Private 约 1320.35→1562.48 MiB。
未发现与之对应的存活窗口/表格数量线性增长；主要 Private 增量未由这些
已测 Python 分配解释。原生缓存、分配器保留或原生泄漏仍不能排除，不能
把它直接命名为“正常缓存”，也不能仅据 RSS/Private 曲线宣布泄漏。

全部矩阵共 143 轮、18 个独立进程场景；初版窗口-only 和修正后 verified
cohort 分开保存，不能把两者混成同一次完整绘图验收。实际验证绘图的循环共
38 轮，其中显式生成 468 个 Map 场景（未把父更新触发的重绘重复算入）。
最终存储专项 **134/134 通过，141.595 秒**。本阶段仅运行一次全量：
**1104 项、1102 通过、2 项失败，1090.725 秒**，不能报告为全绿。

| 未通过的原有耗时断言 | 实测 | 原门槛 |
| --- | ---: | ---: |
| unchanged controls 的 Dirty 检查，三次最小值 | 0.1115765 s | <0.10 s |
| Plain Writer cell encoding | 0.3175300 s | <0.30 s |

两个失败测试及全部 `metrology_app/` 生产源码与入口 `v4.3.2` 相同，未放宽
门槛、删除用例或为 P1 越界优化 P0。失败堆栈均为耗时断言，但不能由此
宣称这些测试中断后的断言已执行；没有再跑全量或挑选绿灯覆盖本次红灯。
全量前后核对 184 个生产/测试/基准 Python 文件，哈希变化为 0。
补充母窗口常驻探针在全量后执行，复用同一份未改动的工具函数；驱动完整
源码和哈希包含在验证 JSON，未改冻结的生产和测试语料。

补充母窗口常驻：10k×30 六轮均为 0 存活子窗口，母窗口自身 widgets 固定
1407、文档数为 1、scope 数为 3；Private 首/末 1447.19→1503.27 MiB。
100k×33 一轮压力样本为 0 存活子窗口、widgets 1407、Private 2933.15 MiB，
仅为一次压力验证，不声称多轮趋势。关闭母窗口后均回到 82 widgets、0 文档。
连同补充验证共 **150 轮、20 个进程场景**，Mock/销毁/断连诊断对照另列，
不混入生产场景验收。窗口/绘图对象未累积的结论仅限这些已测流程与时长。
不得仅凭 RSS/Private Bytes 上升宣布泄漏，也不得把有限循环解释为无泄漏证明。

真实 `config/settings.yaml` 的起始 SHA-256 为
`cb419604ac0620206baa212ac3c527dee022d8d98c1ff1e23dd7db580683014f`。
全部 WKB/Recovery/YAML 测试均写自有临时目录，不读写用户 WKB/Excel。

## 下一阶段 Sol Ultra 的具体入口

1. 优先审查 `metrology_app/settings.py` 的 `load_settings()`、`get_settings()`、
   `save_settings()` 和 DEFAULTS 可变值所有权。以
   `python -m benchmarks.probe_settings_ownership` 的明确红灯为入口，先确定
   返回值、默认模板、保存候选和 expected 是否应独立，再实施完整边界修复。
   不凭正常 Cancel 回归通过就否认访问器别名，也不凭别名推断实际 UI 已丢数据。
2. 审查 `settings.save_settings()` 崩溃临时文件的归属政策，并对照
   `workspace_store.save_workspace()`、`recovery.PreparedRecovery.discard()`。
   当前 WKB 活跃锁保护、revision 复核和候选发布协议保留；不按 glob/年龄
   删除未知归属的文件，不自动移走用户正式文件。
3. 对确认仍增长的 Private Bytes 做原生堆归因。入口为本轮 verified 命令，
   优先采集 `MatchingWindow._refresh_stage_workspace()`、
   `WkbDocument.request_recovery()` / `recovery.freeze_snapshot()`、
   `WaferMapGrid` 和 pyqtgraph/Qt 销毁链的分配栈；检查残留 DataFrame 的
   shape/referrer 及有界缓存身份。没有新证据前，不改缓存策略、所有权或
   发布 generation。Python/Qt 计数稳定不是原生堆已经无泄漏的证明。
4. 已通过的 `_cancel_recovery()`、`_finish_recovery()`、`discard_result()`
   与帧冻结契约作为保护线保留；不另造 Recovery 协议或撤销事务。

可重复 verified 场景（独立进程、自有输出目录）：

```powershell
python -m benchmarks.benchmark_memory_storage --cycles 12 --rows 10000 --columns 30 --scenario mixed --populate-dynamic --plot-wafers 2 --output C:/owned-qa/mixed.json
python -m benchmarks.benchmark_memory_storage --cycles 12 --rows 10000 --columns 30 --scenario tasks --plot-wafers 10 --output C:/owned-qa/tasks.json
python -m benchmarks.benchmark_memory_storage --cycles 3 --rows 100000 --columns 33 --scenario mixed --populate-dynamic --output C:/owned-qa/stress.json
```

`--tracemalloc` 另开进程测分配，`--gc-every 0` 保留自然 GC 对照。
本机为 Python 3.10.20 / Qt 6.11.0；历史 P0 审核为 Python 3.11.16，不能混算提速。
测试所需 lxml/OCR 依赖沿用上轮自有 QA 目录，原生扩展读取受沙盒 ACL 限制，
全量采用相同的授权读取环境；没有全局 pip 更新。

## Git checkpoint 状态

入口与已推送 tag 的代码为 `79b5910550b05f6888053a4bc0408b798b8d8f39`。
本轮新增代码仅为基准、探针和测试，生产 `metrology_app/` 未改；全量期间
冻结语料 184 个 Python 文件的 SHA-256 全部未变。
用户在了解上述两个耗时红灯后明确回复“保存本地记录吧”，授权保存诊断
基线。代码/工具/测试 checkpoint 为
`3cb314277d51db9733fd9f7953a96664fc372f2a`；这两份报告另存本地证据提交，
准确提交见 Git log。全量结果仍为 1102/1104，不改写为通过。
只纳入本轮工具、测试和报告，保留 AGENTS.md、.vscode/settings.json、
docs/todos/ 的用户修改。回滚使用上述代码 checkpoint 的 revert，不 reset
工作目录或恢复旧用户配置。P1 不 push、不移动 v4.3.2 标签、不改 main。

阶段结束后停止，不自动开始 Sol Ultra 的修复工作；P1 提交不推送。
