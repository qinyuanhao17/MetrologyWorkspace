# 2026-10-09 续作验收：截图六项

按用户“继续未完成的”恢复；较新的粘贴说明覆盖早先的实线框设计。不自动提交、推送或发布。

## 实现范围

1. Ctrl+C / Ctrl+X：共享表格使用绿色流动虚线，Esc 取消。Ctrl+X 复制成功后立即清空，一次 Ctrl+Z 在来源表精确恢复。
   可编辑来源表支持剪切；结果/配置表可以复制，不可剪掉计算结果和配置控件。过滤/排序按真实源行映射。
2. Ctrl+A：只选已有值的矩形（含列名行），排除预留与尾部空白；内部空格保留，不删源文件中的空白记录。
3. Ctrl+V：只用原生表格选区标出粘贴矩形，无实线框、无额外颜色、无 Show changes。
   相同内容也有选区，不制造 Undo；仍保留粘贴摘要与 Before/After tooltip，摘要不是绘图完成信号。
4. Wafer Map 与 Correlation/Trend 的数据表右侧增加 Metadata locks；Reference 与 Raw 分别锁定。
   锁定值和列名不会被范围粘贴、整表粘贴、直接编辑或剪切覆盖。混入锁定列的剪切整体拒绝。
   整表粘贴按原行位置保留锁定列；缺失的锁定列追加回表。行数不同或重复列名时先拒绝，再提示 Unlock metadata，
   不猜测 Wafer/Die 自动匹配，不改变源字符串、源列顺序或已有分析上下文。
   **这是未收到行对齐策略答复时采用的安全默认规则**；明确打开文件/Use Workbook Data 属于数据替换，不应用 clipboard 合并合同。
   锁定状态进入 WKB/恢复状态；旧文件缺字段时默认未锁定。
5. Correlation 与 Trend 顶部列出当前参与绘图的 parameter 与 ALL。
   Correlation 匹配任一轴，Trend 包括比较曲线；只筛显示，不改变 draw 选择或拟合输入。
   切换复用已有曲线与 Qt plot widgets，保留缩放；Correlation 缓存有界、未见过的图按需创建，Trend 重排已有 panel。
   筛选后的 rank、页数、PNG 与导出对应当前筛选；ALL 恢复全部。筛选状态随 WKB 保存。
   **数据输入刷新仍沿用现有正确性失效路径**；本次没有声称所有新数据更新都已改成原地 setData 或非阻塞后台分析。
6. Wafer Map 实测黑点悬停增加真实 Die 字符串。缺坐标/非法值的过滤同时携带 Die，不将插值像素或行号当成 Die。
   未提供 Die 时不虚构；测量点隐藏时不显示提示。未新增 Matplotlib artist，不改变插值、色标或导出图。

## 修正的隐性问题

- Dynamic 原先剪切读取 .8g 显示值，可能截断高精度源字符串及尾零；现在读取真实来源文本，Undo 保持精确。
- 筛选复用图时 rank 标题可能保留旧序号；新失败测试复现后，改为更新标题而不重建曲线。
- Correlation 拒绝 metadata 行数不符粘贴之前可能清掉来源上下文；新失败测试复现后，改为先校验再更新。
- Metadata 锁定使用精确源列名，不用分析时去空格的 alias；带空格列名同样保护，原列名不改写。
- New/Open 删除了 metadata 字段时清除不再存在的锁，避免空表首贴被隐藏的旧锁拦住。

## 验证记录

- 开发中 clipboard / feedback / Dynamic 55 项通过；metadata / filter / Correlation / hover / clipboard / feedback 95 项通过。
- Metadata 核心、右侧控件与 WKB snapshot 恢复、拒绝粘贴的完整来源上下文、原始列名、新建后首贴 6 项通过。
- 首次续作全量 579 项中 578 通过，唯一失败是动画的固定睡眠采样。
  存储+clipboard 的 39 项组合复现证明：qWait 结束时 phase 仍 0、timer 活动、边框可见，
  再一次 processEvents 后 phase 1 且像素变化；是待派发事件而非边框消失。
  测试改用 QSignalSpy 等真实 timeout，**仍为原 160 ms**，组合 39 项通过；生产定时器与性能预算未改。
- `benchmarks/verify_clipboard_ui.py` 的 100%/150%、light/dark 实际 Qt 图通过并检查：无额外粘贴颜色/实线框，
  copy 两帧实际改变，右侧锁定与参数筛选可见。日志/PNG 在 `.cache/resume-20261009/visual-1x` 和 `visual-150`。
- **最终全量：`python run_tests.py` 581 项全部通过，246.807 s**。
  日志 `.cache/resume-20261009/full-tests-local-temp.txt`，自检 `main.py --self-test` exit 0，`git diff --check` 通过。
  全量包含原有性能门槛与存储 samefile/硬链接别名保护，未跳过或放宽测试；硬链接测试使用已批准的非沙箱执行。
- 第二次全量 580 项：579 通过、1 错误（247.892 s）。动画通过；`test_open_settings_are_unsaved_until_the_workbook_is_saved`
  的 OneDrive scratch WKB 在 os.replace 上 WinError 5。独立启动/保存模块 13 项通过。
  读写 SQLite 均使用 closing、文件流均 with 关闭；没有通过增加重试、删掉锁或放宽校验来掩盖错误。
  最终复跑把 TEMP/设置/recovery/MPL 指向专用 `Local/Temp/metrology-resume-20261009-final`，仍隔离用户配置。
  不能仅凭独立通过认定具体外部占用者或完整根因，保留两次失败日志。
  换用本机非同步临时目录后完整通过，与目录/外部占用影响相容；仍不宣称已确定 OneDrive 或某个进程是唯一原因。
  日志仍有既有 modal timer 的 `NoneType.confirm_button` 告警、pandas FutureWarning 和故意失败写入的诊断输出；不宣称零告警。
- 正式配置 SHA256 `56932a7d139e1d4a792ae973e11b96ca58c6011872a72edbc88735cd6de8ed37`；
  桌面只读 NOVA 夹具 SHA256 `2e5c35c62af4b8b7ab917b1f46444db0538c87430cca43942805e3e89af7be18`。
  最终再次检查均未改变。所有修改保留为未提交状态；没有打包、推送、发布或改 v3.0.0 tag。

## 性能边界

2026-10-09 最新串行独立进程实测：冻结来源与当前来源各 30 次整表粘贴/Undo、五次 Undo burst。
固定桌面 NOVA 7,731×33、三映射、九张可见图，源字符串与完整 summary 在每次 Undo 后对照，夹具 hash 不变。
日志 `nova-before-clean.txt` / `nova-after-clean.txt` 在 `.cache/resume-20261009/`，记录真实 import 路径。
此前 `nova-before.txt` 与开发测试重叠，不采用为本次对照数据；不与旧日期不同负载数字拼接。

| 操作 | 回调 P50 前→后 ms | 数值当前 P50 前→后 ms | 完整可见 P50 前→后 ms | 完整可见 P95 前→后 ms |
| --- | ---: | ---: | ---: | ---: |
| 整表 Ctrl+V、一列改变 | 246.45→137.31 | 502.78→425.95 | 576.88→489.58 | 605.20→503.52 |
| 单次 Ctrl+Z | 105.35→26.43 | 356.44→325.82 | 404.75→469.30 | 509.47→484.40 |
| 五次 Ctrl+Z 连续撤销（单次 burst） | 1865.82→151.93 | 1865.82→529.34 | 2039.19→597.45 | 单次，不估计 P95 |

粘贴/Undo 的最大事件循环间隔 P50 分别从 502.37/355.97 降到 192.80/189.88 ms。
**单步 Undo 的完整可见 P50 本次慢 64.55 ms**，不能宣称每种完成时间都更快；回调与数值当前改善，但
idle 合并/后续绘制的端到端完成仍需继续优化。没有改 120 ms idle 间隔来美化数字。
首次操作（WKB 已完整打开后）粘贴回调/数值/可见：236.20/491.76/568.36→129.40/414.04/479.88 ms；
Undo：104.19/353.89/402.02→24.02/292.37/438.50 ms。**不是 WKB 冷启动**。
这是 offscreen Qt 的真实控件与完整 viewport 绘制测量，不是原生 Windows 长会话帧率保证。

Ctrl+V/Ctrl+Z 的归因、固定 7,731×33 NOVA 夹具与前后独立进程协议见
[Raw Data 响应性](raw-data-paste-undo-responsiveness.md)。回调、数值当前、完整可见绘图分别测量，不把旧图或占位界面当完成。
WKB 冷启动、Preview/Final 首次构建、所有子窗首次恢复、Group Apply 的异步架构阶段仍不能据本轮控件验证声称全部完成。
原有预算、回归/插值、参与行、导出精度与 Save/Discard/recovery 原子替换保护未放宽。

沿用用户指定的 python-performance-optimization、diagnosing-bugs、systematic-debugging：先复现/归因，再做单变量最小修改。
tdd/bdd 将六项工作流和安全边界落实为执行测试；codebase-design/ponytail 复用现有模型、Undo 和 rendering seam。
scientific-visualization/matplotlib 要求悬停只读真实观测、保留导出图，不用新增绘图对象实现 tooltip。
方法参考：Kassis, Agarwal, He, Patel, Brueckner (2026),
[*Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*](https://arxiv.org/abs/2609.00065),
[DOI 10.48550/arXiv.2609.00065](https://doi.org/10.48550/arXiv.2609.00065)；性能数字来自本地测量，非该论文。
