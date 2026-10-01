# Metrology Workspace 开发交接

更新日期：2026 年 10 月 1 日

## 当前状态

项目实际目录是 `C:\Users\Yuanhao Qin\OneDrive\Desktop\MyCodes\MetrologyWorkspace`。运行环境为 Anaconda 的 `metrology-workspace`，使用 Python 3.11；依赖由根目录的 `environment.yml` 和 `requirements.txt` 管理。

```powershell
conda activate metrology-workspace
python main.py
```

完整测试：

```powershell
conda run -n metrology-workspace python -m unittest discover -s tests -v
```

## v2 Card Matching 当前状态

v2 已回到 `main` 持续开发，本轮交付目标标记为 `v2.0.0-dev.4`，`VERSION` 仍为 `2.0.0-dev`。原独立 `v2` 分支已删除；`v2.0.0-dev.3`、`v2.0.0-dev.2`、`v2.0.0-dev.1`、v1.2.0 及更早的提交、标签和 Release 均不移动。

当前完成的纵向切片：

- Reference-first：先粘贴整理好的 Reference，再粘贴相同行数的 Raw Data；当前按行序对应。
- Reference 与 Raw Data 复用 `SheetModel` / `SheetView` 的可编辑网格；空表也保留行列，支持单元格编辑、区域粘贴及撤销/重做。两个网格直接用 Ctrl+V，不再提供重复的 Paste 按钮。网格改动会同步回 Matching 的 DataFrame 并使旧分析失效。
- 用户在 A1 粘贴整表现在通过 `TableReplace` 写入同一个撤销栈；Reference/Raw Data 的整表替换、Ctrl+A 后 Delete 以及普通编辑都可用 Ctrl+Z 恢复。程序加载文件仍建立干净基线，不把加载动作放进撤销历史。
- 一张 Reference 表支持多参数列；`<name> Reference` 自动对应 Raw Data 的 `<name>`，可在界面取消或改选。
- 无 `Reference` 后缀的数值列也会列为候选参数，但默认不勾选，避免把 `TEM` 与 `PMISH` 之类的业务列擅自配错；Wafer ID、Die Seq 等元数据会排除。
- Parameter mapping 标题行提供 `Select all`。映射快照同时保留参数名、勾选状态和期望的 Raw 列；Raw Data 清空或替换为缺列表时不会删除映射，缺失列保持待选择状态、Run Analysis 禁用，并在顶部状态区提示修改。
- Card 固定按 `Reference = slope × Raw + intercept` 拟合；Preview 应用 Card，Final 直接使用已经加 Card 的 Raw Data。
- Bias 与 Bias % 改为至少选择一个的复选框；两者可同时显示，选择状态写入 WKB，旧文件按原 `bias_mode` 恢复。Reference 为 0 的百分比为 NaN。
- KLA/NOVA 的 Single-wafer metrics 读取 Raw Data，并复用 Wafer Map 的 Wafer ID/Lot ID/PAD Name 默认身份规则；多个身份字段用多行标签显示，Die Seq 不单独拆组。TEM 隐藏单片结果。
- Match Workbook 使用可滚动的单页工作流：输入、Parameter mapping 和结果区位于可拖动的纵向 splitter 中；Slope、Intercept、R² 等结果合并回 mapping 行。页面内不再重复显示 `Match Workbook` 标题或设置卡，Open/Save/Export/Save images、Run analysis、Match Type 和 Bias 选择位于原生菜单栏。
- 结果区不再使用 Parameter 下拉框，并拆为 All parameter plots / Single-wafer metrics 两个 tab。所有映射参数按纵向顺序生成独立卡片；卡片内 Match、Trend 及勾选的 Bias/Bias % 使用单行横向图格。Match 固定为 510 × 330 px，其他主图高 330 px并平分剩余宽度；四图同时显示也不触发外层横向滚动。Match 图标题取 Raw Data column，X/Y 分别标 PMISH/Match Type；参数名与两行拟合公式/R² 使用绘图区上方的独立标题栏，公式位于参数名右侧且不覆盖数据。所有结果图复用 `InteractivePlotWidget` 的完整四边框；普通滚轮传给外层页面，Ctrl+滚轮才缩放当前图，另支持左拖框选放大、右拖平移和双击自动适配。Trend 的 PMISH 是蓝色实线圆点，当前 Match Type 是橙色实线圆点；Trend/Bias 横轴使用 Raw Data 测量身份。Bias 直接显示 nm 和 %，不使用自动 SI 系数。
- 参数卡标题可拖动排序，拖动时显示半透明卡片和 180 ms 淡入插入线；自动重算和 Preview/Final 切换都会保留 splitter、滚动位置和参数顺序。顺序写入 WKB；结果区不再显示 Reset，以减少顶部空白。
- Slope 超出 0.9–1.1 或 R² 低于 0.9 时，Parameter mapping 与 Single-wafer 表格使用主题适配的红色警示和阈值说明。
- Preview/Final 是窗口顶部的模式 tab，替代 Result 下拉框。两种模式各自保留独立 Raw Data；切换模式不会先清空输出。首次 Run analysis 成功后，编辑 Reference、当前模式 Raw Data、映射选择、参数名或 Raw Data column 都会自动重新分析；无效的临时输入只显示警告并保留上一个有效结果。
- `.wkb` 使用 SQLite schema 8，原子保存 Reference、Preview Raw Data、独立 Final 匹配 Raw Data、可选 Preview/Final FullMap 原始来源、Preview/Final Map 与 Dynamic 工作区精确快照、四个工作区独立的 wafer/parameter 勾选、Wafer Map 与 Radius Plot 上次成功绘制的框选、映射、设置、Setup splitter 尺寸与 parameter order。Map 快照可以是显式空表，用于防止重开后错误回填；Dynamic 快照也按 Preview/Final 分开保存。KLA/NOVA 无 Map 快照和独立 FullMap 时从相应 Raw Data 初始化；TEM 无独立 Map 数据时保持空白。用户在 Map 或 Dynamic 工作区编辑后保存 WKB 即可，重开优先恢复快照与仍存在的勾选；Wafer Map 或 Radius Plot 已成功绘制过时会立即按各自保存的框选自动出图。首次保存选择路径，保存或打开后 `Ctrl+S` 直接覆盖当前文件；`Save WKB As…` / `Ctrl+Shift+S` 选择新文件并将其设为后续保存目标。应用设置另存最多 10 个最近成功使用的 WKB，File 菜单可直接重开，并可在系统文件管理器中定位当前文件；该列表不改变 WKB schema。旧 schema 1–7 文件继续读取；旧 Final 工作簿会把原共享 Raw Data 迁移复制到独立 Final 输入。Excel 和逐图 PNG 只作为可选导出。
- Run Analysis 重建参数图前会记住 splitter 尺寸；结果区需要增加高度时只扩展底部内容，不移动用户已拖动的上方两个边界。
- 工具已注册到主窗口，可同时打开多个 Match Workbook 进行对照。
- 独立 FullMap 输入页已从 UI 移除。Preview 将 Card 应用到 Preview Raw Data；Final 直接使用独立且已加 Card 的 Final Raw Data。Trend 右上角 Card 复选框只控制该趋势图显示原始值还是 Card Value，不改动已计算的 Bias/导出语义。旧 WKB 里已有的独立 stage 数据仍保持兼容。
- 当前模式的 Open Preview/Final Wafer Map / Radius、Dynamic 与 Correlation and Trend 按钮位于顶部 tab 右侧。WKB 入口直接复用主窗口注册的 `CorrelationWindow`：Ref Data / Raw Data 是两个独立可编辑页，Raw 保留全部列，Ref 的 Wafer ID、Lot ID、PAD Name、Die Seq 逐行采用 Raw 身份，mapping 名称只用于分析。Correlation 与 Trend 都按 Reference 后 Raw Data 排列；默认来源色为橙/蓝。Trend 可通过面板右键显式叠加两个参数，同单位共轴，异单位或未知单位使用右轴；该偏好写入应用设置而不进入 WKB。
- `MainWindow.selection_state()` / `restore_selection()` 和 `selection_changed` 是 Map、Dynamic 共用的选择状态接口。替换整表时重新识别分组，但按列名和 measurement key 恢复新表中仍存在的选择并自动刷新；如果旧 wafer key 全部不存在，则保留新表默认的全选。Match Workbook 在内存中分别保存 Preview/Final × Map/Dynamic 四份状态，子窗口关闭重开时恢复，互不串选。
- Match Workbook 使用 `MainWindow.set_managed_close_handler()` 接管其 Map/Dynamic 子窗口关闭。关闭时当前表先回写对应 stage；已有 WKB 路径则立即调用原子保存，没有路径则留在父窗口供首次 Save WKB 写入。该路径不显示 Discard/Cancel；独立 Wafer Map/Dynamic 仍保留未保存确认，保存异常则阻止关闭并显示错误。
- Match Workbook 关闭时由父窗口集中管理所有已打开或已隐藏的 Wafer Map、Dynamic 和 Correlation 子窗口：先读取仍存活的 Map/Dynamic model 与选择状态，只保存当前 WKB 一次，再解除 managed-close callback 并关闭/销毁三个类型的子窗口。这个生命周期顺序防止父窗口被 `WA_DeleteOnClose` 销毁后，子窗口回调再读取已经删除的 `QComboBox`。
- `PlotPage` 与 `RadiusPage` 分别保存最后一次成功绘制的 selector cells。之后 `set_input()` 会恢复仍可用的 cells 并以单次 timer 合并快速变化后自动重绘；全部 wafer key 改变时沿用上次参数到新 wafer。只有从未成功绘制或没有可恢复参数时才显示 selector。手动 `Select maps` 会取消待执行的旧刷新，但首次成功绘制后的新方框选择会以 120 ms debounce 自动重绘，不需要再次点击 `Draw selected`。
- 参数图统一为 330 px 高、卡片间距 8 px，并为坐标轴保留内部边距；Match/Trend/Bias 绘图区对齐、四边同粗，Trend/Bias 不显示冗余的 Wafer 轴标题。打开 WKB 后回到页面顶部，同时仍恢复保存的 splitter 与参数顺序。
- 主窗口不再重复显示 Available Tools 卡片；左侧是唯一工具入口，右侧恢复 Activity，底部终端风格 Log 横跨窗口并显示运行环境、错误与 WKB 打开/保存路径。用户实际拖动 Log 分隔栏后，正常关闭保存两个分区尺寸并在下次启动恢复；未打开工具时不显示冗余的 `No tools open`。Shell 也不再显示全局 Close all、Ready 文案、绿色状态点或其占位区域。Log 使用优先 Cascadia Mono、回退 Consolas 的系统等宽字体，背景与现有内容会随 Light/Dark 主题同步切换，INFO/WARNING/ERROR 标签具有高对比语义颜色。
- 新增 Dynamic 工具：复用 Data 编辑器和 measurement identity，自动添加 Cycle。页面删除重复标题并拆成上下两个独立滚动区：上方纵向排列每个勾选参数的 Cycle × Die Seq 表；下方先显示全部已选参数的彩色分组柱图，再显示各参数独立柱图，并以每行三张的 420 × 270 px 网格排列，超出三张自动换行。合并图不显示参数拼接标题，标题行改为带 10 px 小色块的单行横向 legend；独立图仍显示参数标题。柱图不叠加数据点；每张表末行和对应柱图均显示各 Die 跨 Cycle 的样本 3σ。
- Wafer Map 阵列底部不再显示 RBF、边缘扩展和自动尺寸说明文字，释放出的空间归还绘图区；尺寸摘要仍保留在绘制结果和状态信息中。

规模目标是 100,000 行、50 参数。当前开发机随机浮点基准：全部 Card 0.16 秒，单参数派生结果 0.004 秒，WKB 保存 1.05 秒、载入 2.43 秒，文件 97.9 MB。分析结果仍按参数惰性展开；UI 为所有参数建立图卡，但每张图只保留极值采样后的绘图数组，不常驻 50 份完整派生表。

后续明确保留的故事：按 Wafer ID、Slot ID、PAD Name 和坐标自动对齐尚未整理的 Reference，以及直接读取文件而不只依赖复制粘贴。当前不要把这些未完成故事混入行序匹配的 interface。
## 最近完成的修改

### Correlation 和 Trend 布局

- Correlation 默认三列、Trend 默认两列时会按窗口宽度伸缩，不再依靠固定宽度画布。
- `metrology_app/plotting/grid.py` 统一管理标题、浅色绘图面板、可拖动分隔线和列宽同步。
- 深色主题下，绘图标题仍使用清晰的浅色面板背景。

### Trend Auto Scale

- `metrology_app/plotting/interactive.py` 是所有 PyQtGraph 交互的共用 module，Dynamic 也必须使用它，不能直接实例化 `pg.PlotWidget`。
- 该 module 管理四边外框、普通滚轮向外层滚动区转发、Ctrl+滚轮缩放，并允许 Trend 固定 Auto Scale 使用的 X domain。
- 点击 PyQtGraph 的 Auto Scale 后，Y 轴仍按数据适配，X 轴保持紧凑范围，不会恢复左右空白。
- 右侧边框不再因隐藏刻度文字而收缩为 0 像素。
- 回归测试直接触发 PyQtGraph 的 Auto Scale 路径，不只测试页面自己的 Reset views。

### 相关性计算性能

`pairwise_linear_fits` 会预先转换选中的 numeric 列，并缓存测量条目对应的行位置。40 列、480 行、780 次拟合的基准中，中位耗时从 1.412 秒降到 0.902 秒，约快 36%。不要在没有新的前后对照测量时继续声称性能提升。

### 文案

- README 已改成面向使用者的说明，保留 RBF、R²、DPI 等必要术语。
- Activity、工具卡片、绘图区提示和导出状态改为直接说明动作与结果。
- 文案修改没有改变计算、筛选或导出规则。

### 目录

- 三个示例 CSV 位于 `sample_data/`。
- 开发交接文档位于 `docs/`。
- 应用源码包已从职责过窄的 `wafermap/` 改名为 `metrology_app/`；Wafer Map 仍是包内的一个功能模块，包名也不会重复产品名。
- `main.py`、README、依赖文件、环境文件、VERSION 和 PyInstaller spec 留在根目录。这些都是常规项目入口或构建文件，不需要为了目录对称而移动。
- 源码版的运行设置位于 `config/settings.yaml`，该文件忽略提交。便携版仍把设置放在 EXE 旁边。

## Skill 使用约定

`AGENTS.md` 是项目内的个人 Skill 白名单。系统 Skill 和插件 Skill 保持 Codex 默认行为。

默认允许的个人 Skill：

- `tdd`：计算规则、数据转换、状态变化和 bug 修复。
- `bdd`：用户能观察到的工作流和验收条件。
- `codebase-design`：调整 module、interface 和 seam。
- `improve-codebase-architecture`：聚焦 architecture 审查和 deepening，避免没有 leverage 的大范围搬迁。
- `scientific-visualization`：坐标、色阶、比较语义、可读性和导出。
- `matplotlib`：Matplotlib 绘图、布局和导出细节。
- `uncertainty-and-units`：单位、换算、容差和不确定度。
- `statistical-analysis`：相关性、回归、R² 和统计报告。

`improve-codebase-architecture` 已列入项目允许项，Skill 文件中的 `disable-model-invocation` 也已设为 `false`。重新启动 Codex 或打开新任务后，它可以在明确的架构审查任务中自动触发；普通功能修改不会因此强制执行完整架构审查。

本轮按用户要求显式使用了以下非白名单 Skill：

- `python-performance-optimization`
- `qt-ui-design`
- `humanizer-zh`
- `no-ai-slop`

这些 Skill 只对相应任务生效，不会因此变成项目默认项。

## Architecture 决策

当前首选 seam 是 `metrology_app.plotting`。它隐藏 PyQtGraph 的 Auto Scale、外框和面板网格细节，Correlation 与 Trend 只配置各自的数据和坐标语义。删除这个 module 会把相同的交互规则重新散回两个页面，因此它具备足够的 depth。

`metrology_app` 是应用边界，不再用单一功能 `wafermap` 命名整个 package，也不重复产品名 `MetrologyWorkspace`。暂不继续拆成 UI、domain、renderer 等多层目录；项目规模还不足以证明这种搬迁有 leverage，而且会同时影响导入、测试和 PyInstaller。Trend 的单位解析、轴选择、量级告警和不插值序列提取已收口在无 Qt 依赖的 `metrology_app.trend`；PyQtGraph 与 Matplotlib 仍由 `SequencePage` 作为两个渲染 adapter 编排，不要把匹配计算或 WKB schema 混入该 seam。

v2 新增 ADR 0001：WKB 采用 SQLite，并让 `MatchWorkbook` 成为分析与持久化的稳定 interface；Qt 窗口只负责编排和展示。

## 方法来源

v2 结果图的极值保留降采样与“显示抽样、统计全量”披露规则参考：Timothy Kassis, Vinayak Agarwal, Yuhuan He, Darshil Patel, and Aubrey M. Brueckner (2026), *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*, arXiv:2609.00065, https://doi.org/10.48550/arXiv.2609.00065。
## 维护要求

- 保留原始量测字符串和行映射，除非需求明确要求改变。
- Trend 的紧凑 X domain 是绘图语义，不是装饰性设置。
- Correlation 仍允许 X/Y 自由 Auto Scale，不要把 Trend 的限制套到所有图。
- 改动回归、插值、色阶或导出时，先检查数值和视觉等价性。
- 开发时先跑最小测试，交付前跑完整测试和 `python main.py --self-test`。
- 当前 v1 系列基线发布为 v1.2.0；后续 Card/Reference 匹配模块从 v2 开始开发，不覆盖 v1 发布。
