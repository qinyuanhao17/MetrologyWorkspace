# 大表首次按键与 Shift 连选补充验收

## 范围与结论

这是用户在 Task 07 期间新增的要求，起点是 Task 07 checkpoint
`2192a04c72498b0a2d083e763e9f88c75707eef0`。沿用同一工作区、分支和既有
`benchmark_sheet_workflows.py`；没有新建 worktree、回到 tag 或重做已完成优化。
导出相关现场修改及两份用户 Excel 保留，不混入本 checkpoint。

100k×33 的冷 Ctrl+A、Shift 两个方向和纯表格 Undo 已消除原有数秒枚举成本。
**新增要求还不能整体标为完成**：完整 Workbook 撤销仍有约 1.0–1.4s 的分析/绘图，
AutoWeighting 极限表格完整撤销约 4.8s。没有用快速返回或热操作替代这些完整耗时。

## 实测根因及局部修改

### Qt 选区与表头

Qt 6.11 的 `QTableView::selectionChanged` 为取得首个辅助功能事件单元格调用
`selected.indexes().value(0)`，会枚举整个选区。100k×33 的 profile 出现数百万次
model.flags；第二次全选没有新 delta，因而很快，不能拿它充当首次操作。
原生辅助功能请求触发这条分支，参考 Qt 官方源码：
[QTableView](https://github.com/qt/qtbase/blob/6.11/src/widgets/itemviews/qtableview.cpp#L3378-L3402)、
[selection indexes](https://github.com/qt/qtbase/blob/6.11/src/corelib/itemmodels/qitemselectionmodel.cpp#L289-L312)、
[Windows UI Automation activation](https://github.com/qt/qtbase/blob/6.11/src/plugins/platforms/windows/uiautomation/qwindowsuiaaccessibility.cpp#L34-L49)。

`table_selection.py` 提供 `RangeSelectionTableView` 和 `RangeSelectionHeader`：

- 已知所有有效格均 enabled/selectable 的模型，向原生 QTableView 提交原来相同的
  首格辅助功能 Add/Remove 事件，同时用 QAbstractItemView 使完整原选区失效重绘。
  实际 selectionModel、完整 selectionChanged 信号和选区范围不变，没有关辅助功能。
- 将 Sheet 原有按 range 计算表头状态的逻辑复用到 Participation、Dynamic pivot、
  Writer、只读统计表和投影。保留按下状态、活动窗口、排序、隐藏首尾、RTL 和数值 0
  表头。自定义 flags/header 和跨模型选区回退原生路径。
- `uniform_selection_flags` 与原剪贴板 `uniform_selectable` 分开。Order 派生列仍只读，
  不因此放宽 Cut、粘贴或复制权限。带禁用单元格的 QTableWidget 未盲目套用。
- `OrderModel.selection_bounds` 从实际 flags 与派生 order_frame 获取末个可见格，
  不再逐个创建 100k×3 QModelIndex；自定义 data 的子类仍走旧路径。

### Undo 与分析准备

- `sheet.CellEdit` 仅在命令自己的不可变数据上保存 bounds、extent 和值是否全空/全非空。
  全非空还原用 dict.update；确认整个现有字典都在全空命令范围内才 clear。混合值保持
  原逐格逻辑；完整 Qt dataChanged/changed、插行列、原字典身份、Undo/Redo 都保留。
  外部 apply 不接受可信边界提示；自定义 apply 继续被调用。
- 仅在确实修改锁定表头时计算锁名，保留重复锁定表头按输入顺序最后一个生效的规则。
  嵌套通知后恢复外层 changed_cells，外层结束后清空。
- `_analysis_input_frame` 的无保留空行模式只对精确 Python str 使用列/行短路存在性检查；
  保留原始字符串和内部行位置；非字符串、缺测和其他类型继续原完整转换 fallback。
- Reference 纯值变化重新核验 numeric candidates。只有候选及两个 schema 均未变才保留
  原 Mapping 控件；数值资格、表头或 schema 变化仍完整重建并重新分析。
- GroupControls 仅在确有空 selection.records 需要初始化时调用 participation_ids，
  draft/applied 仍使用同一批 ID；既有两项 plan 缓存改为按 Raw/Reference 对保留。
  命中仍须完整 state 和精确 DataFrame 相等，copy shell 后绑定当前源，不修改旧 plan。
- Writer 的热点是每格 dataclasses.asdict/deepcopy。Cell 仅对普通不可变标量和空 review
  列表走等价构造，输出字段/顺序、验证和可变值脱离不变；复杂值、子类及输入共享列表
  回退原逻辑。不改 Writer 全文档撤销结构、Dirty 比较或 WKB 格式。

## 原生冷操作前后对照

Windows、Qt/PyQt 6.11.0、Python 3.11.16、20 逻辑 CPU、2048×1152、DPR 1.25。
每次计时前向本进程窗口发送 WM_GETOBJECT/UiaRootObjectId 请求，主动覆盖辅助功能。
NOVA 原始 7,731×33 Raw 在内存重复/切片到 100k×33，不写源 WKB。

独立 Sheet 的 after 为三个新建 view 的**首次**操作，没有 selection 预热；before
为一个冷样本。两种 Shift 前都先 clearSelection，消除旧 benchmark 的一冷一热偏差。
下表完整 wall 包含同步 viewport repaint；P50 after，单位 ms：

| 100k×33 操作 | 前 | 后 | 后 P95 / Qt gap P95 |
| --- | ---: | ---: | --- |
| 首次 Ctrl+A | 6332.42 | 22.43 | 23.06 / 23.06 |
| 投影首次 Ctrl+A | 8393.92 | 25.19 | 25.71 / 25.71 |
| Shift 取消勾选 | 7360.94 | 15.19 | 15.64 / 15.64 |
| Shift 勾选 | 7212.88 | 17.86 | 18.22 / 18.22 |
| 首次撤销整表粘贴 | 1374.04 | 248.09 | 250.09 / 245.84 |
| 首次重做 | 1541.51 | 50.58 | 50.92 / 40.21 |
| 整表 Delete 后首次撤销 | 1556.42 | 51.08 | 52.85 / 41.28 |

before/after 直接使用同一新 benchmark。旧记录中约 7.24s / 6.41s gap 的 Shift
取消是历史未解决边界，已由本次冷操作证据替代，不能继续视作合格标准。

真实 Workbook 的 fresh analysis 使用 WKB 原映射，Raw/Reference 重复到 100k 行，
没有恢复 WKB 数百个已保存单独绘图 widget。Preview 与 Final 分别独立进程，未提前全选。
每项一个冷样本，完整时间等候排队分析收尾；Reference/Order 各 4 列：

| 位置/操作 | 前完整 ms | 后按键返回 ms | 后完整 ms |
| --- | ---: | ---: | ---: |
| Preview Raw Ctrl+A | 6760.29 | 0.46 | 162.66 |
| Preview Raw Ctrl+Z | 1813.31 | 212.89 | 1383.68 |
| Reference Ctrl+A | 739.14 | 0.19 | 4.35 |
| Reference Ctrl+Z | 43573.02 | 8.47 | 1020.12 |
| Order Ctrl+A | 1001.58 | 1.76 | 4.10 |
| Order Ctrl+Z | 290.25 | 280.51 | 282.73 |
| Final Ctrl+A | 6509.53 | 0.45 | 167.70 |
| Final Ctrl+Z | 1683.16 | 212.10 | 1255.86 |

补充单冷样本：Dynamic pivot 10k×33 Ctrl+A 1290.67→25.85ms；Writer 参数
10k×4 全选 528.34→250.93ms，步骤 10k×41 全选 1830.68→274.75ms（按键返回
0.23/0.18ms，剩余含现有可见格 issues/绘制）。Writer 单格编辑 3886.55→949.46ms，
Undo 12711.69→4781.87ms，Redo 10963.63→2970.89ms。Writer 仅支持既有 10k 行/
20 step 上限，没有扩展其数据协议。这组完整 wall 还等待现有 identity timer/Dirty 比较。

CPU、每项 max_gap、RSS/private/累计 peak、P50/P95/max、计数、环境、源文件 hash 和
所有操作（含未再次优化的 Copy/Paste）见
`docs/validation/p0-table-cold-comparison-2026-10-25.json`。小样本 P95 是最大值，
不代表置信上界；进程峰值包含准备，未宣称内存或 DWM FPS 改善。

## 验证与复现

纯/Qt 专项 48 项通过（8.249s，`table-writer-green2.log`），包括新增精确状态 oracle、
160 个输入 frame 比对、数字表头、完整选区通知、自定义模型 fallback、隐藏边界、
锁定表头顺序、嵌套 changed、空尾行、多次 Undo/Redo、ID 初始化、Reference 数值资格
和 Cell 序列化/校验/可变别名。

首次全量为 1,082/1,083 通过（367.027s），唯一失败是本次新增的纯序列化 wall
断言在全套末尾测得 0.663s，而独立诊断约 0.156s。将该性能保护改为独立冷进程，
与基准一致，隔离全套 Qt fixture 的累计运行状态；没有关闭 GC，没有改生产代码来
特殊对待测试，也没有降低原 0.3s 阈值或删除数据断言。同一个新测试在冻结旧生产包
仍失败（1.053s），当前包三个序列化测试通过（0.346s）。原失败日志
`ultra-table-full.log`、对照 `table-writer-isolated-{red,green}.log` 保留；修改测试入口后
重新执行全部 `python run_tests.py`。

最终完整回归 **1,083/1,083 通过，362.503s**，日志
`.cache/p0-audit/ultra-table-final-full.log`。包括所有既有 Dirty/Clean、Undo/Redo、
嵌套/非法状态、Card/Group、绘图、Save/Discard/Recovery、旧 WKB 和 Excel 回归。
相较 Task 07 的 1,059 项，新增 24 项保护；导出相关现场修改保留在完整测试环境中，
不计为本 checkpoint 的代码成果。本次完整测试前后真实配置、源 WKB 和两份用户 Excel
hash 不变，数值列及业务状态验收没有放宽。

```powershell
$py = 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe'
& $py -X utf8 -m benchmarks.benchmark_sheet_workflows --rows 100000 --count 3 --platform windows --accessibility --wkb .cache/p0-audit/input/nova.wkb --interactions --projected-edits --output .cache/p0-audit/table-uia-final.json
# before: --code-root .cache/p0-audit/table-cold-baseline-source
# Workbook: --workbook-only --workbook-stage preview 或 final，--count 1
# 其他实现：--auxiliary-only --rows 10000 --count 1（不需要 --wkb）
```

benchmarks 包启动即隔离 settings/recovery/reminders/MPL。各探针结束验证真实 settings
和只读 WKB hash 不变。最终 JSON 同时记录两份用户 Excel 的 hash；现场的真实设置在
本轮较早阶段有外部变化，不将跨探针的 hash 差异说成程序写入或全程不变。

Profile 单独运行，不混入配对：`table-uia-profile-before-10000-0-select_all.profile.txt`、
`table-workbook-profile-after-100000-0-workbook_reference_first_undo.profile.txt`、
`table-aux-before-10000-0-writer_steps_first_undo.profile.txt`。后者插桩约 46.3s，
不拿它与未插桩 4.8s 对照；实际未插桩 before 是 12.7s。

## 残留及回滚

1. Workbook Raw/Final/Reference 仍有同步分析、measurement spans、完整绘图及 paint
   成本；不能将按键返回 8ms 当作完整撤销 8ms。
2. Writer 仍做全文档 Undo 和 Dirty 比较。若要单格命令及增量身份，需要先明确完整历史
   与混合导入/Review/Resolve 的行为，并评审 Save/Discard/Recovery；此处不改协议。
3. 100k×33 超大 Copy/Paste、累计内存、五子窗口长同步及大页 paint 仍是独立残留，
   没有省略刷新、减少测量点或以跨结果缓存掩盖它们。

回滚本表格 checkpoint 可恢复原生选区路径、原 Sheet 命令执行和原转换/Mapping/Group
更新，保留 Task 08/07 commits。Writer 还可单独恢复本 commit 的 auto_weighting.py diff，
文件格式兼容，不需迁移数据。不要 hard reset 或覆盖现场其他未提交导出成果。
