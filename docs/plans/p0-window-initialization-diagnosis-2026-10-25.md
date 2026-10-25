# P0 剩余专项第 1 项：多大表后的新窗口初始化

## 结论与本轮边界

入口为 `017c10d48e93bf3d4e94a4ed12c8c485087f584b`，继续使用原工作目录和分支。
工作区另外九个导出相关文件已有未提交修改，本轮完整保留，不将它们归入本轮成果。
入口 diff 和文件哈希在 `.cache/p0-audit/init-special/entry-*`。

**上轮几十秒初始化异常已复现并定位：旧基准将 SheetView 本身作为顶层窗口，
放大了 Qt 6.11 Windows UI Automation 的窗口查找兜底。** 本轮修正基准窗口层级，
保持原数据、模型、投影、选择、辅助功能和完整刷新。真实生产表格本来就嵌在窗口内，
本轮没有修改任何 `metrology_app/` 生产文件，也没有改所有权、Undo、Recovery、WKB
或异步发布协议。

三个真实排序工作簿（10k×30 和 100k×33）的新窗口打开没有复现几十秒等待。
三个完整恢复的 NOVA 工作簿下仍有约半秒开窗成本，已单独量化，不宣称所有新窗
均达到几十毫秒。第一项诊断结束后停止，不进入其余四个热点。

## 真实复现条件及原因

复现环境为 Windows build 26200、Python 3.11.16、Qt 6.11.0，原生 `windows`
后端，`UiaClientsAreListening()` 为 True。明确通过 `WM_GETOBJECT` 请求原生辅助功能，
没有关闭辅助功能、GC 或模型通知。

裸表夹具与上轮被中断的场景一致：一个装载 NOVA 原文的 SheetModel、一个空目标
模型、一个共享来源且反向显示隔行记录的投影模型，三个 SheetView 分别作为顶层窗口。
**这是三个视图，只有一个完整来源单元格 payload，不是三个完整数据副本。**
数据规模分别是实际常用的 10k×30 和压力场景 100k×33。

链路如下：

1. 创建新窗口中的 ComboBox/SpinBox，发出可访问值变化事件，此时新控件及其父链
   可能尚未创建原生 QWindow。
2. Qt 的 `windowForAccessible()` 取不到窗口时，会遍历所有顶层窗口，并逐项查询
   每个 accessible root 的直接子项。这是一段 WebEngine 兼容兜底，不是业务同步。
3. 独立 QTableView 的直接可访问子项包括全部虚拟单元格和表头，数量随行列乘积增长。
   查询这些 child 会创建并缓存单元格接口，因而反复查询旧模型索引并增加内存。
4. 生产的 QMainWindow/QDialog/QWidget 根只含少量直接子控件，表格位于其下层，
   此次兜底不会把整表单元格当作顶层根的直接子项遍历。

官方 Qt 6.11 代码与 profile、独立容器对照共同支持上述归因；本轮没有声称已经捕捉
每一帧 Windows 原生 C++ 调用栈：

- [windowForAccessible 的顶层根子项遍历，已核对 v6.11.0 固定版本](https://github.com/qt/qtbase/blob/v6.11.0/src/plugins/platforms/windows/uiautomation/qwindowsuiautils.cpp#L19-L45)。
- [新控件查询已有原生窗口](https://github.com/qt/qtbase/blob/6.11/src/widgets/accessible/qaccessiblewidget.cpp#L134-L143)。
- [Table childCount、child 及接口缓存](https://github.com/qt/qtbase/blob/6.11/src/widgets/accessible/itemviews.cpp#L481-L585)。
- [Windows 辅助功能激活及监听条件](https://github.com/qt/qtbase/blob/6.11/src/plugins/platforms/windows/uiautomation/qwindowsuiaaccessibility.cpp#L88-L152)。

## Profiling 和排除实验

100k×33 裸表的独立 profiling 运行中，新窗口构造 44.735s、CPU 44.297s，
GC 仅 0.260ms。约 5,097 万次函数调用，其中旧投影的 `index()` 180 万次、
来源 `columnCount()` 约 1,096 万次。大部分栈顶表现为新控件的 `addItem/setRange/
setValue`，但这些是触发点，不是需要删除或减少校验的业务热点。
索引计数还包含 SheetModel 预留的空白行列，不直接等于来源 DataFrame 的行列乘积。

相同模型、数据和辅助功能下，仅把旧表装入普通 QWidget 容器，profile 的构造
降到 58.2ms，总调用约 10.3 万次。profile 有额外开销，只用于归因；正式对照见下一节。
原生与 offscreen、单独来源视图与来源＋投影组合、纯数据字典和真实工作簿也做了
诊断对照，原始结果都保留，没有用 offscreen 的快速结果冒充 Windows 验收。

GC/SIP 生命周期不是本次长等待的主因，因此不实施 `SheetModel.parent` 变更、
全局禁 GC、提前强制所有窗口 `winId()` 等未获证据支持的生产 workaround。
ProjectedSheetModel 已实现 flat parent/index/map 契约，没有发现遗漏 parent 实现。

## 不带 profiler 的性能对照

每个裸表/容器样本均为新进程，复用同一源 WKB；每个条件三轮，构造时间单位 ms。
表格是**基准夹具修正前后**，不是软件生产开窗速度提升声明。

| 来源规模 | 裸表顶层 P50 | 容器顶层 P50 | 容器 P95 |
| --- | ---: | ---: | ---: |
| 10k×30 | 2089.92 | 44.70 | 47.90 |
| 100k×33 | 38180.98 | 45.57 | 45.94 |

裸表 100k 三轮为 38221.42、38180.98、38031.17ms，主线程 gap 同样约 38s；
包装后为 44.46、45.94、45.57ms。首轮也在 ms 量级，未用第二次预热结果代替第一次。
小样本 P95 是最大值，不是统计置信上界。

### 真实应用路径

使用主界面 `Shell.open_component('card_matching')`，不只调用裸 QWidget 工厂。
先打开三个工作簿，用真实 `GroupControls.change('sort', ...)` 激活生产投影；
验证绑定的是既有 preview 代理，投影行是完整原行排列，抽查首/中/末行的源索引和原文。
最后完整比较所有来源 DataFrame，没有重排或改写底层量测字符串。

| 已打开的三个工作簿 | 新窗口入口调用范围 | 加上首次 Qt 绘制的分段和 |
| --- | ---: | ---: |
| 10k×30，Raw 表已排序/投影 | 85.19–89.27ms | 137.50–165.25ms |
| 100k×33，Raw 表已排序/投影 | 85.16–89.70ms | 147.90–167.09ms |
| 原始 NOVA 7731×33，按保存状态恢复 | 324.81–361.27ms | 501.13–576.20ms |

每项在一个进程的同一组持有窗口下，连续打开三个新窗口，原始 JSON 保留首次与后续
值；这与上表三次独立进程的统计口径不同。造表、装载与排序另列阶段，不计入新窗口
操作耗时，不能据此宣称打开 100k 行数据文件也只需 0.16s。

前两项是装载 Raw 表并激活排序的场景，不冒充三份 100k 全分析绘图；第三项才是
原始 WKB 按保存上下文恢复的场景。计时是构造/入口加同步 Qt repaint，未测 DWM FPS，
分段和不包括记录日志的开销。

### 资源压力区分

复现前系统物理内存约 34.19GB，可用约 16.3–16.4GB。裸表 100k 构造后 working set
约 2.32GB，容器夹具约 0.80GB。差异与虚拟单元格接口物化/缓存相符，不能据此
宣称生产应用节省了 1.5GB。

另在容器夹具中额外分配并触碰 1536MiB 内存，working set 达到约 2.42GB，
新窗口构造仍为 32.01–49.54ms，没有出现几十秒等待。这个独立对照支持“本次异常
不是可用内存耗尽导致”。没有人为制造系统分页/极低可用内存，不外推到这些状态。

## 最小修复及保留项

本轮只修改 `benchmarks/benchmark_sheet_workflows.py` 的通用 Sheet 夹具：

- `sheet_probe_host()` 使用 QWidget＋QVBoxLayout 容器，和生产表格的嵌入结构一致。
- 原视图仍可见，原生窗口曝光断言改为检查真实顶层容器；截图仍取原视图。
- 关闭/删除真正的容器窗口，重复新建视图路径已通过原文、投影与 Undo 校验。
- Qt 标准可访问表格仍在容器内，可访问内容没有被删掉；没有降低数据量、屏蔽
  辅助功能或跳过刷新。结果增加 `generic_sheet_host` 元数据以避免混淆旧基准。

`017c10d` 已完成的 Workbook-only 不创建无关表格分支继续保留，本轮没有重复优化它。
新增 `benchmark_window_initialization.py` 只负责本问题的可复现诊断，复用既有
隔离入口、NOVA 副本和 memory/hash helper；输出构造、显示、GC、CPU、gap 和内存阶段。
后续其它热点的前后对照应同时使用这个容器夹具加载旧/新生产源码，不能直接把新
夹具数字与历史裸表数字作软件性能提升对照。

**当前无需为这次几十秒异常修改生产代码。** 实际 NOVA 场景约半秒开窗的单独
profile 显示，约 284ms 用在 `_refresh_recent_wkb_menu`，其中 `load_workspace`
约 276ms；另有现存图形首次 paint。这不属于裸表 UIA 全表枚举。
现有测试明确要求新窗口立即有正确的 Recent Actions，本轮保留完整文件读取与校验。
不为了减少此成本擅自换成只读 manifest、延迟菜单契约或新增文件类型缓存；这些需要
先定义损坏/被替换文件的行为与 API 边界，再单独实施。

## 验证与复现命令

Windows PowerShell 使用 conda Python 及专用 TEMP/TMP。所有 `-m benchmarks` 入口
在导入应用之前创建独立 settings/recovery/reminders/MPL 路径。数据输入为既有
`.cache/p0-audit/input/nova.wkb`，SHA-256：
`fbe22da2a55571b136a1f3e17db1f69284c391e9a2fac86019c5abb919336b4f`。

```powershell
$initPython = 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe'
& $initPython -m benchmarks.benchmark_window_initialization --kind sheets --rows 100000 --columns 33 --uia --output .cache/p0-audit/init-bare.json
& $initPython -m benchmarks.benchmark_window_initialization --kind sheets --rows 100000 --columns 33 --uia --wrap-sheets --output .cache/p0-audit/init-wrapped.json
& $initPython -m benchmarks.benchmark_window_initialization --kind sorted_workbooks --rows 10000 --columns 30 --holders 3 --count 3 --shell --uia --output .cache/p0-audit/init-real-10k.json
& $initPython -m benchmarks.benchmark_window_initialization --kind sorted_workbooks --rows 100000 --columns 33 --holders 3 --count 3 --shell --uia --output .cache/p0-audit/init-real-100k.json
& $initPython -m benchmarks.benchmark_window_initialization --kind saved_workbooks --rows 7731 --columns 33 --holders 3 --count 3 --shell --uia --output .cache/p0-audit/init-saved.json
```

裸表复现可能需要几十秒并临时增加约 GB 级的可访问缓存；这是刻意保留的诊断模式，
默认 `--kind workbooks` 不创建裸表。加 `--profile` 单独生成 profile，不混入计时对照。

- 两轮新容器的原生 10k×33 表格工作流通过：52 个动作样本，保留全部原文、复制/
  粘贴、Undo/Redo 单步性、投影、排序/筛选/隐藏行、Shift 断言。
- 三轮独立进程裸表/容器对照均完成，异常日志中的 20 秒 traceback 是诊断输出，
  不是被隐藏的测试失败；每个正式样本都完整返回并保留原文校验。
- 当前工作区隔离全量 **1086/1086 通过，739.729 秒**，日志为
  `.cache/p0-audit/init-special/full.log`。现场保留九个已有导出修改，因此不是纯净
  017c10d 的 1083 项快照。本轮没有增加/删除功能测试或放宽原有性能阈值。
- 13 个入口现场文件哈希再次一致，包含九个已有修改文件、真实设置、NOVA 副本和
  两份用户 Excel。原始 logs/profile/JSON
  位于 `.cache/p0-audit/init-special/`；可提交摘要：
  `docs/validation/p0-window-initialization-2026-10-25.json`。

## Git checkpoint、回滚与后续顺序

本项独立 checkpoint 包含两个 benchmark 文件、本报告、性能摘要和 P0 进度索引；
准确 SHA 见 Git log/交接消息。未提交入口现场的导出文件，未 push、合并或创建 worktree。
回滚本项用 `git revert <本项 SHA>`，只还原基准与文档，不修改生产文档/用户文件。

第一项不应继续占用后续热点优化的优先级。按常用编辑动作优先的假设，下一轮可先
分析 Writer 首次 Undo，再处理 Workbook Undo；10k 批量操作和五窗口同步的相对
优先级需结合真实使用频率。用户当前没有提供操作频率统计，不能虚构这些频率。
本轮未重测或实施其余四个热点，旧耗时只作为交接线索，**到此停止**。
