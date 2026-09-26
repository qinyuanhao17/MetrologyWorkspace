# Metrology Workspace 开发交接

更新日期：2026 年 9 月 26 日

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

v2 在独立的 `v2` 分支开发，`VERSION` 为 `2.0.0-dev`。v1.2.0 的提交、标签和 Release 均不移动。

当前完成的纵向切片：

- Reference-first：先粘贴整理好的 Reference，再粘贴相同行数的 Raw Data；当前按行序对应。
- Reference 与 Raw Data 复用 `SheetModel` / `SheetView` 的可编辑网格；空表也保留行列，支持单元格编辑、区域粘贴及撤销/重做。两个网格直接用 Ctrl+V，不再提供重复的 Paste 按钮。网格改动会同步回 Matching 的 DataFrame 并使旧分析失效。
- 一张 Reference 表支持多参数列；`<name> Reference` 自动对应 Raw Data 的 `<name>`，可在界面取消或改选。
- 无 `Reference` 后缀的数值列也会列为候选参数，但默认不勾选，避免把 `TEM` 与 `PMISH` 之类的业务列擅自配错；Wafer ID、Die Seq 等元数据会排除。
- Card 固定按 `Reference = slope × Raw + intercept` 拟合；Preview 应用 Card，Final 直接使用已经加 Card 的 Raw Data。
- Bias 与 Bias % 改为至少选择一个的复选框；两者可同时显示，选择状态写入 WKB，旧文件按原 `bias_mode` 恢复。Reference 为 0 的百分比为 NaN。
- KLA/NOVA 按 Wafer ID 输出单片 SLOPE、INTERCEPT 和 R²；TEM 隐藏单片视图。
- Match Workbook 使用可滚动的单页工作流：输入、Parameter mapping 和结果区位于可拖动的纵向 splitter 中；Slope、Intercept、R² 等结果合并回 mapping 行。窗口标题与模块入口统一为简洁的 `Match Workbook`。
- 结果区不再使用 Parameter 下拉框。所有映射参数按纵向顺序生成独立卡片；卡片内 Match、Trend、Bias、Bias % 使用 2 × 2 图格，固定最小高度并缩短图标题，避免标题、坐标轴和相邻图互相遮挡。Match 始终绘制线性拟合，KLA/NOVA 的单片 R²/SLOPE 放在同一参数卡片下方。
- Preview/Final 是窗口顶部的模式 tab，替代 Result 下拉框。首次手动 Run analysis 成功后，在 Raw Data 的 A1 粘贴替换表会自动重新分析。
- `.wkb` 使用 SQLite schema 2，原子保存 Reference、匹配 Raw Data、可选 Preview/Final FullMap、映射与设置；schema 1 文件仍可打开。Excel 和逐图 PNG 只作为可选导出。
- 工具已注册到主窗口，可同时打开多个 Match Workbook 进行对照。
- 独立 FullMap 输入页已从 UI 移除。Preview 将 Card 应用到当前 Raw Data；Final 直接使用当前已加 Card 的 Raw Data。旧 WKB 里已有的独立 stage 数据仍保持兼容。
- 当前模式的 Open Preview/Final Wafer Map / Radius 按钮位于顶部 tab 右侧，通过 `MainWindow.set_table` 复用现有绘图工作区，没有复制绘图实现。

规模目标是 100,000 行、50 参数。当前开发机随机浮点基准：全部 Card 0.16 秒，单参数派生结果 0.004 秒，WKB 保存 1.05 秒、载入 2.43 秒，文件 97.9 MB。分析结果仍按参数惰性展开；UI 为所有参数建立图卡，但每张图只保留极值采样后的绘图数组，不常驻 50 份完整派生表。

后续明确保留的故事：按 Wafer ID、Slot ID、PAD Name 和坐标自动对齐尚未整理的 Reference，以及直接读取文件而不只依赖复制粘贴。当前不要把这些未完成故事混入行序匹配的 interface。
## 最近完成的修改

### Correlation 和 Trend 布局

- Correlation 默认三列、Trend 默认两列时会按窗口宽度伸缩，不再依靠固定宽度画布。
- `metrology_app/plotting/grid.py` 统一管理标题、浅色绘图面板、可拖动分隔线和列宽同步。
- 深色主题下，绘图标题仍使用清晰的浅色面板背景。

### Trend Auto Scale

- `metrology_app/plotting/interactive.py` 是 PyQtGraph 交互的共用 module。
- 该 module 管理四边外框，并允许 Trend 固定 Auto Scale 使用的 X domain。
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

`metrology_app` 是应用边界，不再用单一功能 `wafermap` 命名整个 package，也不重复产品名 `MetrologyWorkspace`。暂不继续拆成 UI、domain、renderer 等多层目录；项目规模还不足以证明这种搬迁有 leverage，而且会同时影响导入、测试和 PyInstaller。下一项值得单独评估的工作，是把 Trend 的数据准备结果变成一个稳定 interface，再由 PyQtGraph 和 Matplotlib 两个 adapter 消费；不要把这项重构混入小型 bug 修复。

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
