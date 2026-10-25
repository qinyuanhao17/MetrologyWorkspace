# P0 剩余性能专项：Match Workbook Undo（2026-10-25）

## 范围与结论

接续 `b3fe61b0031e3f69c5da71e72bbf1809c8eb6b2d` 的新窗口初始化诊断。
用户明确排除主窗口 Tools 中尚未完成的 AutoWeighting Writer；本轮未修改其业务、
历史、OCR 或测试。只处理完整 Match Workbook Undo 的一个已复现热点，未开始
五窗口同步、宽表粘贴/删除或 P1/P2 重构。沿用同一本地分支，没有新 worktree。

唯一生产修改：`MatchingWindow._analysis_input_frame()` 用
`pd.api.types.infer_dtype(..., skipna=False) == "string"` 识别字符串输入，替换逐格
Python `type(value) is str` 扫描。仍逐列/逐行判断实际非空内容；混合类型和日期等
输入保留原 `fillna("").astype(str)` fallback。没有新增缓存、改变数据所有权、
Undo 事务、事件发布、Recovery/WKB 格式，也未跳过分析、通知或绘图。

**本轮有局部收益，完整 Workbook Undo 仍不满足整体流畅要求，Task 06 保持部分完成。**
100k×33 Raw 首次 Undo 的 P50 从 1471.42 降到 1281.14ms（约 12.9%），
同步按键处理从 234.30 降到 112.25ms（约 52.1%）。Final 完整 Undo
1292.97→1190.62ms（约 7.9%）。不能把 112ms 的 dispatch 当成完整撤销耗时。

## 诊断与最小修复依据

使用现有 `benchmark_sheet_workflows`，未重新搭建基准。先冻结当前生产包到
`.cache/p0-audit/workbook-undo/baseline/`，包含已有但未提交的导出现场；这不是
Git checkout/worktree。前后都使用上轮已修正的真实嵌入式表格/Workbook 夹具。

100k Raw 首次 Undo 的 cProfile 对照：

| 函数/调用 | 前 | 后 | 解释 |
| --- | ---: | ---: | --- |
| `_analysis_input_frame` inclusive | 0.624s | 0.105s | 330 万次 Python 类型判断被移除 |
| 全动作 Python 函数调用数 | 7,089,197 | 3,789,106 | 不是跳过模型/分析通知 |
| `measurement_spans` inclusive | 0.588s | 0.597s | 本轮未改，仍是热点 |
| `_draw_all_parameters` inclusive | 0.865s | 0.883s | 本轮未改，仍是热点 |
| 数值分析 inclusive | 0.210s | 0.214s | 本轮未改 |

profile 有显著插桩开销且 inclusive 时段互相重叠；上表只用于定位，不作未插桩
性能承诺。当前 profile 未再出现历史日志中的 100k UUID 生成热点，未重复优化
Group 身份路径。不能把旧日志的 UUID 耗时算成本轮收益。

未采用“所有 object dtype 都是字符串”的假设。bytes 空白解码和 datetime NaT
转换可能与逐标量判断不同，因此加入与原完整 mask 的直接对照；`skipna=False`
确保含缺失值不会被误当作全字符串。numpy 字符串及自定义 strip 的字符串子类也
有对照。原始字符串、行列顺序和源 frame 未被写回。

## Windows 原生配对性能

只读 NOVA Raw 原表为 7731×33，按原顺序重复/截取到目标行数。10k×30 仅在内存
副本显式去掉未映射的 MSE、GOF、NGOF 三列，保留所有映射和 Wafer/Lot/PAD/Die
及文件身份列；Reference 保留真实列和对应顺序。三个参数均参与原有分析。

每个尺寸/阶段/版本在一个独立进程创建三组新窗口，每组测其首次 Ctrl+A、Undo、
Redo；不是三个全新应用进程。修改前和修改后使用同一增强后的基准。计时包含
QTest 键盘派发、queued analysis、Qt 事件处理及同步 paint，未统计 DWM FPS。
小样本 P95 是三次中的最大值，不表示尾部置信界。UI Automation 保持启用。

| 场景 | Undo P50 前→后 ms | Undo P95 前→后 ms | dispatch P50 前→后 ms | Qt gap P95 前→后 ms |
| --- | ---: | ---: | ---: | ---: |
| 10k×30 Preview Raw | 392.08→383.77 | 401.28→393.14 | 26.31→16.69 | 146.88→148.51 |
| 10k×30 Reference | 258.39→240.25 | 343.85→241.29 | 2.64→2.63 | 199.95→148.82 |
| 10k×30 Order | 40.45→39.32 | 49.40→41.64 | 33.72→31.34 | 43.99→32.51 |
| 10k×30 Final | 371.52→352.06 | 384.83→357.64 | 27.67→16.98 | 153.71→151.81 |
| 100k×33 Preview Raw | 1471.42→1281.14 | 1473.75→1291.42 | 234.30→112.25 | 825.09→775.51 |
| 100k×33 Reference | 1093.04→1037.42 | 1111.76→1040.64 | 9.18→8.99 | 783.85→752.56 |
| 100k×33 Order | 288.79→272.69 | 291.39→284.69 | 286.63→269.70 | 289.27→282.46 |
| 100k×33 Final | 1292.97→1190.62 | 1313.41→1197.90 | 218.98→125.12 | 816.22→806.74 |

Reference 和 Order 不经过本次字符串分类快路径，其小幅变化只记为此次观测，
不宣称由本次修改带来。10k Raw 总耗时和 gap 没有显著改善。100k Order Redo
P50 284.39→292.07ms，P95 284.72→304.95ms，也保留原记录，没有筛掉慢样本。
Redo、CPU 和 RSS/private/累计 peak 的全部统计见配套 JSON。

首次 Ctrl+A 的按键 dispatch 都小于 2ms，但计入窗口后续 paint 后，100k Raw/Final
P50 仍约 163/170ms；Reference/Order 约 4–5ms。该较长 paint 成本没有因本轮变更
而消失，不能用裸按键数值宣称“所有表格首次都已流畅”。

## 验证与现场保护

- 开发专项：10/10，通过，2.603s。原 100k presence `<0.35s` 断言原样保留。
- 原生前后基准：各 72 个动作样本均通过，共 144 个；每次 Undo/Redo 核对源 frame、
  analysis current 与对应分析 summary；Final 同时核对 Preview 源表不变。
- Windows 原生单元专项：104 项中 102 项通过。修改前冻结基线和修改后重复运行
  都在相同两项剪贴板动画断言失败（`test_table_clipboard.py` 的 timeout 和 reshow）。
  首次/基线/重测为 15.386/15.338/15.195s；不能写作 104/104。这些用例不调用本次
  修改的 Workbook 输入路径；生产 Clipboard 实现也未改变。
- 两项原生失败尚未定性为真实应用缺陷或 fixture 时序。已有代码收到任意剪贴板
  dataChanged 都会清除 outline，延迟自有通知是候选原因，现有日志尚不能证明。
  本轮保留失败、未放宽 160ms 阈值、未删除/跳过测试，也未改剪贴板行为。
- 隔离全量 `python run_tests.py`：**1,087/1,087 通过，386.218s**，0 failures、
  0 errors。第一次全量仅在沙箱内触发 `os.link` 拒绝；沙箱外使用独立 TEMP 和
  隔离 OCR 依赖重跑完整套件通过，没有删除或跳过测试。
- 真实 settings、只读 NOVA、用户 Excel、既有未提交导出现场的哈希：最终待核对。

测试均使用独立 settings/recovery/reminders/MPL 路径及隔离 TEMP，未把生产设置
作为测试输出。入口状态和源码 diff 保存在 `.cache/p0-audit/workbook-undo/`。
九个既有导出文件未纳入本轮 checkpoint，用户 Excel 未纳入 Git。

## 剩余方案与风险

1. 100k 完整 Undo 仍约 1.0–1.3s，Qt gap 约 0.75–0.81s；10k 常用规模也有
   0.24–0.38s 等待。后续应优先研究已测到的测量身份/标签准备和边界线绘制，
   用纯业务例程的逐点/NaN/标签等价对照约束修改，不能抽样少画或省去必要刷新。
2. Raw 的原有 120ms keyboard debounce 也适用于当前键盘历史链。区分打字与完成的
   Undo/Redo 事务可能减少等待，但会触及队列合并/最新结果发布契约。应先给出
   连续 Z/Y、typing→paste、模态决策、关闭/切阶段的时序方案并由 Astra High 审核；
   本轮未改调度、revision/generation、事务或所有权。
3. 对跨 analysis 复用 metadata 或共享输入快照，必须定义精确输入边界并保护旧
   accepted result、独立子窗口及原始量测字符串；不能直接按 frame identity 命中。
   这些仍是方案，不是已实现优化。
4. 原生剪贴板动画的既有失败独立记录，后续需采集 dataChanged/Show/Hide 顺序和
   剪贴板所有权，确认根因后再安排单独修复。
5. 五窗口 Group/阶段切换、100k×33 粘贴/删除仍未在本轮优化。AutoWeighting Writer
   按用户要求排除，不再作为本轮待修项目。

Task 02–05 的既有完成结论不变；01 的长时/瞬时峰值/DWM 扩展边界不变；
06/07/08 保持部分完成；09 保留“不额外重构”的评估结论。不能把本次一处加速
写成整体 P0 无保留通过。

## 复现与回滚

在现有 Conda 环境及隔离 TEMP 下串行执行（`--rows 10000` 时另加
`--omit-raw-columns MSE GOF NGOF`；Final 改 `--workbook-stage final`）：

```powershell
python -X utf8 -m benchmarks.benchmark_sheet_workflows --rows 100000 --count 3 --platform windows --accessibility --wkb .cache/p0-audit/input/nova.wkb --workbook-only --workbook-stage preview --code-root .cache/p0-audit/workbook-undo/baseline --output .cache/p0-audit/workbook-undo/before-preview-100000.json
python -X utf8 -m benchmarks.benchmark_sheet_workflows --rows 100000 --count 3 --platform windows --accessibility --wkb .cache/p0-audit/input/nova.wkb --workbook-only --workbook-stage preview --output .cache/p0-audit/workbook-undo/after-preview-100000.json
```

本轮文件：`metrology_app/matching_window.py`、
`benchmarks/benchmark_sheet_workflows.py`、`tests/test_analysis_input_frame_fast.py`、
本报告、进度索引与 `docs/validation/p0-workbook-undo-performance-2026-10-25.json`。
独立 checkpoint 的准确 SHA 见本轮最终交接及 `git log --` 上述文件。
回滚只需 `git revert <本轮 SHA>`；也可仅将 `_analysis_input_frame` 的类型判定恢复为
原 Python `all(type(...) is str)`。没有用户数据迁移；不要 reset 整个工作区。
