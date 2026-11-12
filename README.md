# Metrology Workspace

Metrology Workspace 是一套 Python 3.10+ / PyQt6 桌面工具，用于整理量测数据、完成 Card 匹配、Dynamic 重复性分析，并绘制 Wafer Map、光谱、径向图、相关性图和趋势图。主窗口提供 **Match Workbook**、**Wafer Map**、**Spectra Viewer**、**Correlation and Trend**、**Dynamic**、**AutoWeighting Writer** 和 **Reference Summary** 七个工具。每次打开都会创建一个独立窗口，同一工具可以同时开多个实例；窗口可命名、勾选随 WKB 保存。当前版本为 **v5.2.0**，提供 Windows x64 Setup，见 [发布说明](docs/releases/v5.2.0.md)。历史版本标签保持不变。

v4.3.1 修复 Match Group / Wafer 导出中曲线、Wafer 标签和分界线不一致的问题：原生 Trend、Bias 与 Bias % 改为绑定单元格的 XY series，Show Wafer Group 的真实宽度会同步作用于数据；Wafer 标签保持各自 span 中心。单独 Group 页始终展示全部 Wafer，Match Wafer 改为不分页的一张完整图，数值轴只保留一个 Die Seq 标题，并在每个 Wafer 内按可用宽度生成密集刻度。完整 Undo、宽表粘贴/删除和多窗口阶段切换仍可能等待，不能把局部提速理解为整体流畅度全部达标。

v4.0.0 在 v4-dev3 基础上整理 Excel/Matplotlib 导出：Match Original 合并原始数据与参数图，增加 Match Group，Match Wafer 提供独立 Wafer 视图；Bias 纵轴正负对称。Dynamic 的原始数据、逐参数 Cycle×Die 表和 3 Sigma 图集中到同一工作表；FullMap 同时放置已绘制的 Wafer Map、Radius 图片，TEM 额外保留 Trend。提醒事项继续使用独立用户目录存储。

v4.0.1 增加独立工具 **AutoWeighting Writer**（v4.0.0 安装包不含此功能）：在软件内粘贴/打开截图，由本地 CPU 自动识别为基础四列和 Multiple Step 两张可编辑表，合并滚动截图，保留原图复核及冲突候选，支持 `.waw` 保存、恢复和 Excel 导出。无需聊天助手或联网识别服务，模型随完整软件包提供。用法、方案取舍和限制见 [AutoWeighting Writer V1](docs/auto_weighting_writer.md)。此版本还修复 REF/RAW 独立筛选及 WKB 同步；Trend 缺少 Die Seq 时按原始表格行号绘图。全量 854 项测试中 847 项通过、7 项耗时门槛未通过，具体限制在发布说明中列出。

## 运行

项目已经提供 Anaconda 环境文件。首次使用时，在项目目录执行：

```powershell
conda env create -f environment.yml
conda activate metrology-workspace
python main.py
```

本机环境位于 `C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace`。在 VS Code 中选择该目录下的 `python.exe` 即可运行和调试。环境会独立安装 `requirements.txt` 中的依赖，不使用系统 Python 包。

主窗口通常以约 1180 × 820 的尺寸居中打开；在小屏幕或高缩放比例下，会按任务栏以上的可用空间自动缩小。分析窗口依次错开，窗口变小时仍可通过滚动条查看内容。

程序启动后不会自动打开分析工具。点击左侧的 **Match Workbook**、**Wafer Map**、**Spectra Viewer**、**Correlation and Trend**、**Dynamic**、**AutoWeighting Writer** 或 **Reference Summary** 即可新建窗口。**Reference Summary** 支持 NOVA、PMISH、KLA 和 CDSEM1 文件批量汇总，Summary 页只显示文件数、保留行数、通道或 MP 数、问题摘要及输出文件，不展示 100 行数据预览。右侧 Activity 保留本次会话的窗口与文件事件，横跨主窗口底部的 Log 会记录 Python 运行环境、错误，以及 WKB 打开和保存位置，便于调试；上下区域可拖动调整，实际拖动后的 Log 高度会在正常关闭时保存并在下次启动恢复。Shell 不显示重复的全局 Close all、Ready、绿色状态点或空闲 `No tools open` 文本。Log 使用 Cascadia Mono、Consolas 等系统等宽字体，随 Light/Dark 主题切换背景，并以蓝色、琥珀色和红色区分 INFO、WARNING、ERROR 标签。

Reference Summary 现有三页：**Summary** 汇总源文件；**Wafer Alignment** 自动载入 Ref，并可在 Raw Data 表内 Ctrl+V 粘贴、整片拖动、一对一链接及按 Field 或绝对 XY 稳定排序；**XY Bias Trends** 仅绘已链接的晶圆。Ref 坐标先换算到 Raw 所选单位，再计算 Raw − Ref。点数不同、缺失 XY 或未指定单位会提示，不截断或虚构坐标。Trend 默认两列，普通滚轮滚页，Ctrl＋滚轮缩放；Choose folders 支持多选并去重扫描路径。

四种 Vendor 均支持 `.csv`、`.xlsx`、`.xlsm`，Excel 只读取第一张 Sheet。CDSEM1 每个源文件独立处理，只保留 `ACD_No=CD`；缺少 `Wafer_ID` 或 `Lot_ID` 时输出空白，不生成身份。无 Wafer ID 的源文件须确认只有一片晶圆。MP 名称、大小写及首次出现顺序保持原样；缺失 MP/Chip 坐标或同 Chip＋MP 测量冲突会报错，完全重复行忽略 SourceRow 后去重。CD Pivot 保留 Common 11 列和每个 MP 的 34 列，另输出 CD Results、Checks 和 Results CSV。命令行可用 `python main.py --vendor CDSEM1 --files "C:\Data\cd_sem_ref.xlsx"`，可加 `--output-parent` 指定输出位置。见 [定向验收记录](docs/validation/reference-input-formats-2026-11-12.md)；本轮按要求未跑全量测试。

如果不使用 Conda，也可以在 Python 3.10+ 环境中安装依赖：

```powershell
python -m pip install -r requirements.txt
python main.py
```

### Home reminders (v4)

The home screen replaces Current Session with an independent Reminders list.
Use **+** to add a title, notes, optional date/time and flag. Click the circle to
complete a task; **Completed** lets you restore it. Double-click or F2 edits a
task. Right-click provides Edit, Complete, Flag and confirmed Delete; Delete
also works from the focused list. Today includes overdue tasks; Scheduled,
All, Flagged and search provide other views.
Only the reminder body scrolls: the title, filters, search and footer actions
stay fixed above the Log. The redundant Workspace heading is omitted.

Edits save immediately, without a separate Save command, to
`%LOCALAPPDATA%\MetrologyWorkspace\reminders.sqlite3`. Updated source and portable
versions share this one file for the same Windows user, regardless of their
installation directory or version. It is independent of settings and every
Tool/WKB/WMAP. Close older instances before the first update: on first use, an
uninitialized user file imports the old `config/reminders.sqlite3` (source) or
`reminders.sqlite3` beside the executable (portable), retaining the old file.
Keep that old file in its original directory until migration has succeeded;
the application cannot discover an old installation that has already been removed.
Once initialized, the user file is authoritative: old copies are not reimported
or merged, so they cannot overwrite edits or restore deleted tasks. Corrupt or
unsupported files report an error rather than silently resetting the list.
Older versions using the installation-local path do not share later updates.
For an intentionally separate reminder list, launch with
`METROLOGY_REMINDERS_PATH` pointing to another SQLite file; explicit paths bypass
automatic migration. Back up the user file (with all instances closed) before
moving computers or reinstalling Windows. No account, cloud synchronization or
closed-application notification service is used.
The original reminder feature is included in `v4-dev1`, not `v3.2.0`.
The blue palette, scrolling/calendar fixes and fixed user-directory storage
are included in `v4-dev3`.
Interaction references: [Planify](https://github.com/alainm23/planify) and
[Reminders](https://github.com/remindersdevs/Reminders); no code was copied.

## Windows 便携版

`v4.3.1` 提供新的 Windows 二进制包：[v4.3.1 Release](https://github.com/qinyuanhao17/MetrologyWorkspace/releases/tag/v4.3.1)。下载 `MetrologyWorkspace-Windows-x64-v4.3.1.zip` 后请完整解压，再双击 `MetrologyWorkspace.exe`，无需另装 Python；也可下载 `MetrologyWorkspace-Windows-x64-v4.3.1-Setup.exe` 安装到当前用户目录。`_internal` 文件夹必须和 EXE 放在同一目录；不要只复制 EXE。设置保存在 EXE 旁边的 `settings.yaml` 中，提醒事项使用上面说明的独立用户目录。更新前关闭旧版并备份自己的设置和数据；包内不附带用户数据。

重新构建便携版：

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean MetrologyWorkspace.spec
```

## 设置

从主窗口左上角菜单打开 **Settings…**。这里可以设置主题、分辨率、默认色阶、字体、插值平滑、Min R²、边缘填充、共享色阶、点值、色条、等值线和测点样式。**Recovery interval** 设置恢复草稿检查周期，默认 120 秒，可改为 30–1800 秒；Save 后更新所有已打开的文档，Cancel 不改变原设置。周期越长，异常退出时可能丢失的最近编辑越多。

点击 **Save** 后，源码版会把配置写入 `config/settings.yaml` 并立即生效。便携版仍保存到 EXE 旁边。**Load from YAML** 用于重新读取磁盘上的设置。浅色和深色主题都会同步应用到原生窗口标题栏。

## Data 工作区

Data selection 列筛选中的 **Find values** 可输入 `W1 W3`、`W1,W3` 或 `W1，W3` 查找多个值，空格和逗号可以混用，任一关键词匹配即可，忽略大小写及空项。查找保留已有勾选；**All / None** 只操作显示中的值。

- **Data → Data selection → Hide excluded rows in tables** 勾选并 Apply 后，Order / Reference / Raw Data 隐藏不参与分析的记录；取消勾选并 Apply 可恢复显示。此操作不删除源数据、不重新编号，也不改变原来的参与选择。子窗口选择 **Match Workbook selection** 时遵从相同显示规则；**Full data** 不沿用父级隐藏规则。
- 隐藏/排序的表格中 **Ctrl+V** 按可见行映射到原始记录：允许只覆盖剩余可见行的一部分，超过范围会提示并阻止。隐藏行不被改动；若要整表替换或增加记录，请先恢复全部行。**Ctrl+Shift+V** 不允许绕过隐藏行保护。
- 双击 Raw Data 卡片的标题或表格外空白处，可将同一编辑器悬浮；再次双击或关闭浮窗即还原。左上角图钉（Alt+P）切换仅在母窗口之上或本软件内部最上层，不置顶到其他软件之上。Raw 归属 Match Workbook，其他面板归属各自分析窗口。原表格、复制粘贴、Undo/Redo 和分析联动保持不变，不产生数据副本。
- Wafer Map 的 **Opacity** 后有 **Decimals**，默认 2 位、范围 0–10，使用十进制四舍五入（负数临界值也远离零舍入）。该项只影响点值文字，不改测量值、插值或统计；与主窗口 **Settings → Point value decimals** 共用设置，不随 WKB 保存，旧 WKB 也不能覆盖主设置。
- Trend/Bias 的 Mean、样本 σ、Min、Max 在鼠标位于非数据点区域时自动显示；数据点处优先显示 Die、X、Y。此规则同样适用于 Correlation and Trend 子窗口及动态 Trend，不再占用图标题或单独的统计复选框。Group plots 的 **All-parameter Card** 与 **Group Card** 互斥选择，分别使用总图或当前组拟合的系数，不叠加校准。

- 左侧表格支持单元格编辑、区域复制和粘贴、清空、撤销及重做。第一行始终作为字段名。
- 可以导入 CSV 和 XLSX。Excel 文件包含多个工作表时，可选择要读取的工作表。`001` 这类文本 ID 和原始数值字符串会保留。
- **Ctrl+V** 只覆盖粘贴到的区域，不会清空表格：在 A1 粘贴较窄的表时，右侧原有列保持不变。在 A1 粘贴多行表格且尺寸比现有表小时会先弹出尺寸提醒，列出粘贴与当前的行列数，可选择“只覆盖粘贴范围”“清空后粘贴”或取消。想直接整表替换用 **Ctrl+Shift+V**，等价于菜单里的 **Paste table**；粘贴的第一张表仍会自动识别字段。
- 如果第一行有重复列名，**Auto rename** 保留第一个原名，后续按列顺序添加 `_1`、`_2` 等后缀，并跳过已占用的名字。该操作只修改表头，也可以用 Ctrl+Z 撤销。
- Parameter mapping 每行的 **Bias limit ±** 位于 **Bias out of range** 前，支持独立小数限值（默认 0.5，单位 nm / degree / 无量纲）。行内勾选框只控制绝对 Bias 图的红色 ±limit 虚线，不影响统计、不套用到 Bias %。超限数统计当前已应用筛选和 Preview/Final 全部有限 Bias 中严格超出限值的点，边界值不计入；修改仅更新该参数的统计和限值线，不重绘数据曲线。逐参数限值及勾选状态随 WKB 保存，旧文件沿用原全局限值；Summary 包含限值、单位和超限点数。Group 分界使用加粗黑色虚线，下方标签区对应位置有同粗黑色实线（包含两端）；Wafer 分界保持较细灰色虚线。Auto Scale 保留完整横轴数据范围，不在 Trend/Bias 两端额外留白。
- All parameter plots 内各图上方的 **:: Match / Trend / Bias / Bias %** 标题条可拖动：拖到另一张图的左右边缘调整顺序，拖到上下边缘放到上/下行；图间分隔条可左右拖动改变宽度。图不能浮出窗口或跨参数移动，会随整个参数模块移动；也可右键标题条（键盘 Tab 后 Shift+F10）选择边缘/行位置。布局按参数、Preview/Final 及三图/四图组合分别保存在 WKB 的 UI 状态，刷新数据不重置，旧文件仍使用默认单行布局；移动/缩放容器不重新拟合或修改原始数据。
- Single-wafer metrics 采用左表右图布局，同高 280 px；表格内部独立横向/纵向滚动，右侧 R²/Slope 图各固定为 420 × 280 px。Wafer 列初始宽度 320 px、可手动调整，后面的 **Group** 列展示已应用设置下的真实分组名称；一个测量组跨多个分组时以 `Mixed:` 列出全部归属，分组未开启时显示 `Not grouped`。点击散点会高亮两张指标图的对应点，并滚动定位/蓝色高亮表格行；再次点击已选点、按 Esc 或点击表格空白处可清除高亮，不影响 Draw。表格最后一列 **Draw** 的勾选框居中，点击整个单元格或按空格均可切换，在这一排下方生成该 Wafer 的 Match/Trend/Bias（可选 Bias %）模块；**Uncheck all** 一次取消该参数全部 Draw，不提供 Check all。取消绘图后布局恢复紧凑。单 Wafer 按现有 Wafer/Lot/PAD 身份分类，不因 Die Seq 重复拆分；只使用当前已应用筛选的数据，独立拟合该 Wafer 的 Card，Preview 默认使用它、Final 默认原始值。图块继承 Parameter mapping 的参数及 Bias limit，支持模块排序、内部图拖动与分隔条调整，选择和布局随 WKB 保存。拟合不足的行不可勾选，不回退整体 Card。Match 图不再显示点/拟合线图例。
- **Analysis → Metric highlighting…** 可自定义 Slope 下限/上限和 R² 下限，默认分别为 0.9、1.1 和 0.9。Slope 严格超出区间、R² 严格低于下限时标红；边界值和缺失/非有限值不标红。**Apply** 立即更新 Parameter mapping、Summary、Single-wafer 表格，不改变拟合结果、参与数据、Draw 或图布局；**Cancel** 不提交。设置随 WKB 保存，旧文件保留默认条件。
- Single-wafer metrics 和 Group plots 的参数大模块也可拖动 **⋮⋮ 参数名** 排序，顺序与 All parameter plots 共用并随 WKB 保存。单 wafer 表格、R²/Slope 图和已勾选的 wafer 子图随整个参数模块移动；Group plots 按参数增加外层大模块，把该参数全部基础/组合 Group 图收在一起。内部 Group 卡片只在同一参数下排序，不会混入另一参数。排序仅移动现有界面，不改变数据或重新拟合。
- **Groups → Group settings…** 使用与主窗口 Settings 一致的紧凑纵向表单：Head groups、Mark、Trend order、Group sequence，右下角为 **Cancel / Apply**。不再显示 Import combined 或 Clear filters / sort。Apply 成功应用分组设置并更新绘图后自动关闭窗口；失败时保留窗口。Cancel/关闭仍隐藏窗口、保留待应用编辑，不自动绘图。**Original row order** 忽略三张配对表的排序、保留原始输入顺序，并按 Wafer 画灰色细虚线边界：同一 Wafer 内 Lot ID／PAD Name 变化不再产生额外虚线，每条线都是可对照的 wafer 分界；Trend、Bias、Bias % 只显示稀疏 Die Seq，不显示 Group/wafer 标签。已删除的 **Current table order** 旧设置在重开时按 Original row order 处理。切回 Group 顺序时恢复 Group 标签及各 Group 的 Show wafer 设置。
- **Group plots** 使用与 All parameter plots 相同的可拖动 Match / Trend / Bias / Bias % 图块；默认绘制全部基础 Group 和组合 Group 对应的已启用参数，不额外绘制 All。**Head groups 与 Mark 两个开关在所有 Match Type（KLA／NOVA／TEM）下默认都不勾选，加载或粘贴带 TestFlag 的表也不会自动打开，需要时显式勾选。** 没有选图入口、绘图、PNG 或分页工具栏，所有图块在一个区域内滚动浏览；旧文件的选图、单 wafer 和分页设置自动忽略，单 wafer 图仍在 Single-wafer metrics 中勾选绘制。仅通过 **Groups → Manage groups…** 管理组合：上方固定基础 Group 复选框，下方为可编辑的组合 Group 行列表；**Add** 增行、双击改名，选择行后勾选上方成员，**Apply** 提交全部编辑，**Cancel** 不提交。Trend / Bias / Bias % 默认只显示稀疏 Die Seq 和 Group 名称；管理窗口每个基础、组合 Group 后的 **Show wafer** 默认不勾选，勾选并 Apply 后上层显示 Wafer ID、Lot ID、PAD Name 的值（不带字段名），下层每个 Group 只显示一次名称。Wafer 标签限制在各自区间内，空间不足时省略 Lot/PAD、优先保留 Wafer ID；标签区 Wafer 分界线为细灰线。Trend / Bias / Bias % 的相邻有效点跨 Wafer/Group 边界连续连接，仅真实缺失值断开。这些显示设置不改变组合成员、数据或 Card。组合 Group 的源记录去重合并，独立拟合新 Card；增删或改名后自动更新绘图。该页的 **Use group Card** 勾选后使用显示范围的独立 Card（合并 Group 使用新 Card），取消后使用对应参数的整体 Card；不会改变数据范围。Trend 的 Card 勾选独立控制是否校准，Final Bias 仍沿用原始值规则。All parameter plots、Single-wafer 与 Group plots 的 Trend 统一不显示 Y 轴标题：标题就是对应的 Raw Data 列名，标题行内的图例把 Reference 曲线标为当前 Match Type（KLA／NOVA／TEM）、把 Raw Data 曲线标为 PMISH，图例与标题同排、不再压在曲线上。
- **Data → Data selection…** 可按 Order、Reference、Raw Data 的所有列搜索、筛选和排序，整行点击切换 **Use**，Shift 点击批量设置可见区间。过滤是布尔矩阵：**Add row** 新建一行（每行是一个布尔组），行内条件用各自的 **AND / OR** 下拉连接、先算行内；行与行之间再用 **AND / OR** 连接，因此 `(A OR B) AND C` 这类组合都能表达（同一层内 AND 先于 OR 计算，与 SQL 一致）。每行末尾的 **+** 给该行加条件，条件的 **Edit / ×** 修改或删除，**Clear filters** 清空全部，矩阵随选择一起保存。**Check Visible / Uncheck Visible** 只改变可见记录的参与状态。**Apply** 后 selection 会保持：Raw Data 被整表替换或行数变化时，能对上的行按身份延续、其余按原位置延续，不会因为重新粘贴就把选择清空；只有 selection 用到的列（过滤列/身份列）不存在了，才会在提示栏提醒重新执行 Data selection。未勾选记录不参与 Workbook 分析及可追溯同源子工具绘图，但原始三表和 WKB 仍保留它们。搜索/列筛选本身只改变展示；**Cancel** 不提交勾选。独立导入的其他来源及 TEM 独立工具数据不按位置猜测匹配。旧文件保留已有分析筛选，首次应用 Data selection 时转换成显式参与勾选。
- **子窗口的数据来源**（Wafer Map / Radius、Correlation and Trend、Dynamic）：从 Workbook 打开时，菜单栏 **Data** 里有两个互斥选项——**Match Workbook selection**（默认）表示窗口里的表就是 selection 之后的数据；**Full data (before selection)** 表示重新复制 selection 之前的完整数据。切换会按当前 Workbook 数据重建该窗口的表（窗口已有独立修改时会先确认）。两种模式都可以再用 **Data selection…** 给本窗口追加自己的行选择，只影响本窗口的绘图/统计；右上角显示 `N ROWS / M COLUMNS · X ROWS USED`。
- **Mark** 是可选分类（原 Age）：新建 Workbook 默认不启用，关闭时只按 TestFlag / 测头分组，已有 Mark 名称和分配保留。启用后点 **Marks…** 管理：每个量测组最多一个 Mark，名称完全自由（不限于 POR 等固定值），双击改名、**Add Mark / Delete Mark** 随时增删。第一个 Mark 是兜底组，✓ 标出，未显式分配的量测组自动归入它；只保留两个 Mark 就能当二元分类（默认 Old / New），需要多元时继续添加。删除某个 Mark 后，原属它的量测组回到第一个 Mark。搜索框只筛选列表，**Assign Visible** 批量分配给搜索后可见的量测组；点击首行再按住 Shift 点击末行，可把首行的 Mark 应用到可见区间。改名会同步更新 Order 表的 Mark / Group 筛选值。旧 WKB 自动保留原 Old/New 行为；在 Group settings 点击 Apply 后，表格和图使用自定义名称。关闭 Mark 时忽略 Mark 列的筛选/排序，已选 Mark × 测头组的筛选合并到测头，重新启用后恢复。**Order 表没有任何 TestFlag 时，只要启用 Mark 就按 Mark 分组**（组名就是 Mark 名称，不带 TestFlag 说明）；TestFlag 和 Mark 都没有时不分任何组，Group plots 页也不出现。
- Wafers 列表上方显示当前身份字段，例如 `Wafer ID / Lot ID / PAD Name`。身份字段可以多选。
- Parameters 默认只显示可绘图的 numeric 列。取消 **Numeric** 后，可以查看和选择元数据列。
- X/Y、FIELD X/Y、X(mm)/Y(mm) 和 Die Seq 默认按元数据处理，不会自动作为测量参数。
- Wafer Map（主窗口工具及 Match Workbook 的 Preview、Final）把含数值的 MSE、GOF、NGOF、LBH、CINDEX 识别为 **NUMERIC**，可以手动勾选绘图，默认不勾选。fitTime、regIter 仍是元数据；Correlation/Trend 和 Dynamic 的建模参数排除规则不变。
- 只有手动保存才会写回 CSV。关闭窗口或替换表格前，程序会提示尚未保存的修改。

这个表格用于整理绘图数据，不支持 Excel 公式、合并单元格或完整的 Excel 格式。

## Spectra Viewer

Windows **v5.1.1** 提供 Setup 安装包和便携 ZIP，见 [发布说明](docs/releases/v5.1.1.md)。

**Data → Data selection** 用一行表示一个 SME 文件，Apply 同步树中勾选和绘图。右上角 **Selection Script** 可复制/粘贴带版本号的 JSON，保留全部筛选行、AND/OR、搜索、查看模式、Hide excluded rows 和参与状态。记录仅按 **Wafer ID＋Lot ID＋PAD Name＋Die** 匹配，不使用 SME 名称或路径；同一身份的多条光谱统一应用勾选，来源状态冲突时提示先统一。旧版路径脚本需从更新后的来源窗口重新复制。**Copy WKB Selection** 一次性复制父工作簿的完整脚本，包括 filter conditions 与查看设置，之后可独立修改。其他分析子窗口也使用相同脚本规则；跟随 Match Workbook selection 时显示父窗口选择，Apply 本地改动后自动切到 Full data，父窗口不变。Checked rows / Unchecked rows 按全部记录的当前勾选状态查看；Filtered rows 才按已保存筛选条件查看。

**Open Die Map** 显示所有量测位点，已勾选为蓝色，未勾选为浅灰色。轮廓、位点、选中圈与 Test Flag 小旗开启抗锯齿。左键在单张 Die Map 内拖动矩形选中框内点，Ctrl/Shift 框选追加，单击空白取消选择；双击位点切换其光谱勾选。勾选仅更新现有位点的颜色，不重建整页或改变图尺寸。右键 **Check Unselected / Uncheck Unselected** 仅作用于右键所在晶圆。**Apply Check To Similar Wafer** 和 **Apply Flag to Similar Wafer** 分别复制勾选及旗标，要求 Die 编号集合相同，且每个对应 Die 的 X、Y 绝对差分别小于 **0.4 mm**；缺失/冲突坐标或来源混合状态会明确提示。图块尺寸固定，窗口缩小时用滚动条浏览；窗口与双击打开的光谱图可置顶悬浮。

树右键 **Export Checked Spectra…** 按原 Folder 层级复制已有 SME 原文件，不生成或改写 SME。导出子窗口遇到不可用原件时支持重试或跳过，最后列出未导出文件；目标重名不覆盖。成功显示绿色加粗 **Export Succeeded√**，失败显示红色加粗 **Export Failed×**。

Match Workbook 顶部提供 **Open Spectra Viewer** 子窗口入口，可在菜单中新建、命名、勾选和删除多个光谱窗口。该入口为工作簿级，Preview/Final 共用入口，Card 不修改光谱数据。**Options → Spec Save Type** 提供互斥的 **Embed Spectra Data**（默认完整嵌入）和 **Spectra Paths Only**（仅原 SME 路径）两种保存模式，子窗口随 `.mwkb` 保存。切换为路径模式再保存，会从新 WKB 中移除嵌入采样并缩小文件；正常 `.bak` 仍保留上一保存版本。路径模式依赖原 SME 位置，文件缺失时明确提示并保留引用及勾选/旗标；完整嵌入模式可在原 SME 移动后继续查看。勾选、多选、Filter By、Color By、BSL、分析模式、隐藏图例、视图开关、手动坐标范围和分隔条都随文件恢复。子窗口中的 **Save Match Workbook / Ctrl+S** 保存所属工作簿；关闭子窗口只保留会话草稿，父窗口统一处理未保存提示。保存后标题显示对应 WKB 或独立 `.spec` 名称。

Spectra Viewer 也支持独立的 **`.spec`** 文件：File → **Save Spectra / Save Spectra As…** 按当前 Spec Save Type 保存光谱或路径及设置，**Open Spectra File…** 重新打开；主界面的 Open Workspace 和拖入文件也能识别 `.spec`。Match WKB 子窗口中，**Ctrl+S / Ctrl+Shift+S 始终保存或另存所属 Match WKB**，`.spec` 通过菜单单独保存；独立 Spectra Viewer 中，这两个快捷键保存或另存 `.spec`。保存 `.spec` 不会同时保存父 WKB。

WKB 子窗口的 **Spectra Info** 按 Raw Data 的 Original row order 输出当前勾选光谱，有带/不带 Test Flag 两个 tab。按 Wafer ID、Lot、PAD、Die 和 FIELD X/Y 匹配，Time 来自 SME，Type 为 Accuracy，Reference 列沿用原列名和顺序；隐藏记录不参与复制或 CSV 导出。**Options** 中的文件名时间戳校验默认开启，与 SME 内时间不符或来源不匹配会提示并阻止导出。**Data → Set Test Flag** 支持按身份字段分组、搜索、添加整数旗标和批量分配，0 为 Fallback。Die Map 也可给选中点设置旗标：1 绿色、−1 红色，0 不显示；点的蓝/灰色仍只表示勾选状态。Test Flag 与 Marks 下拉框都避免滚轮误改。

**Spectra Info → XY** 新增坐标表：Wafer ID、Lot ID、PAD Name、Die Seq、FIELD X/Y、X(mm)、Y(mm)。物理坐标直接来自 SME，缺失留空、保留原精度；支持复制和 CSV 导出。绑定 WKB 且有 Raw Data 时严格沿用原行序；独立 Viewer 或 Raw Data 为空时按 Wafer → Lot → PAD 自然排序、Die Seq 数值升序，再以测量时间和源路径稳定区分重复 Die。Data selection 也提供 X(mm)/Y(mm) 筛选，Apply 后的勾选结果同步到 XY 表。对话框的 Filtered rows/Search 仍只用于查看和编辑，不额外改变已勾选光谱的导出范围。

Spectra Info 三页采用相同的行序。表头或表格右键 **Delete Column(s)** 删除当前页的报告列，右侧列左移，复制/导出同样移除该列，原始数据保留；设置随 `.spec` 或 WKB 子窗口草稿保存。**With Test Flag** 页可直接编辑整数旗标，与 Die Map 双向同步，旗子原位更新。Spectra Info、Viewer 和 Die Map 共用删列及旗标修改历史：`Ctrl+Z` 撤销，`Ctrl+Shift+Z` 重做；新载入文档清空操作历史。

Spectra Viewer 的 **Groups** 菜单提供 Enable Groups、Copy WKB Groups 和 Group settings。复制按 Wafer ID / Lot ID / PAD / Die 一次性获取 WKB 当前已应用的 Head/Mark 分类及共享 Test Flag，之后可独立修改；重复身份分类冲突会拒绝，未匹配项保持未分组。Group settings 使用紧凑设置栏和带 Wafer / Lot / PAD / Die 身份的明细表，Test Flag 与 Spectra Info、Die Map 共用状态，Apply 后同步，支持撤销/重做。新建本地 Mark 默认 **POR（Fallback）、POR+、POR-**；已有文档/WKB 自定义 Mark 保留。树右键 **Set Mark → Add Mark…** 提供 Replace / Append：前者替换，后者把 `Old` 叠加成真正的 `Old/POR` Mark。legend 显示 `Mark | 原图例`，Wafer 节点显示 `Wafer ID | Mark`，同片不同 Mark 用逗号并列；Die Map 标题及点提示同步 Group。Mark 修改保留光谱、勾选、曲线颜色和轴范围；设置随 `.spec`/WKB 子窗口保存。Legend 四区可左右调整，与绘图区之间也可上下拖动，双击分隔栏还原。

树右键 **Highlight** 为选中光谱添加亮洋红粗线前景高亮，点击空白取消选择后仍保留，再次取消 Highlight 可移除；不改变原始数据、通道配色或轴范围，隐藏/未勾选曲线仍隐藏。高亮随 `.spec`/WKB 保存并支持撤销/重做。主图或双击放大的图中选中光谱后，按 **U** 取消勾选；文本编辑框不受该快捷键影响。

顶部 **Color By** 可选 **Wafer** 或 **SME Name**。Wafer 按 Wafer ID、Lot、PAD 的完整组合区分颜色；SME Name 按具体光谱文件区分颜色，重复文件名仍按源路径区分。两种方式都为不同 Channel 分配不同颜色，各图、图例与悬浮图保持一致。勾选、分类、缩放及切回已有模式时保留已分配颜色；双击图例只切换对应着色组的显示。优先使用 Tableau Category10，较多组合扩展色相、饱和度和亮度，避免循环复用相同 RGB。3σ 每条曲线汇总多个文件，因此仍按 Wafer/通道着色；此时 Color By 显示 Wafer 并禁用，离开 3σ 后恢复原选择。物理 Channel 数量统计不受着色分组影响。

勾选只更新受影响的 Wafer/Channel 曲线组；超过 32 个颜色组时，按稳定顺序拆成最多 16 个批次，只更新受影响批次，其他曲线及屏幕缓存保留。legend 整个通道隐藏或恢复保留批次源数组和缓存，避免全量重建。窗口和分隔条调整时保持 viewport 绘制及旧图缓存，后台合并新尺寸工作；大文件读写和解码期间界面持续响应。主图和悬浮图保留手动坐标范围，自动轴随可见数据更新。重复勾选保持原有曲线覆盖顺序。实档数值与性能范围见 [性能和路径存储验证](docs/validation/spectra-performance-storage-2026-11-03.md)。

在 legend 分区右键选择 **Show All** 可恢复本区隐藏的通道，不改变光谱勾选，分区标题栏不放按钮。树中单选一条光谱后右键 **Set as BSL**，顶部显示基准身份，树中基准行加粗，并切换到 Residual；BSL 本身可以不勾选。树右键 **Clear BSL** 可取消基准并清除标记，当前为 Residual 时恢复 Original，保留勾选与选择。**Options → Plot Mode** 可选 Original、Residual、3-Sigma，主图与悬浮图同步标注模式。Residual 为“光谱 − BSL”，仅在波长完全相同且值有效时计算，其他点保留空缺，不插值、不外推、不折返 Delta 相位；优先匹配相同通道，否则只接受 AOI/AZI 完全相同且唯一、具有该指标的 BSL 通道，无法匹配时提示。3-Sigma 按 **Wafer ID / Lot / PAD 与通道** 分别对已勾选的原始光谱计算每个波长的 **3×样本标准差（n−1）**，每个波长至少需要两条有效观测；不同 Wafer、不同通道不混合，也不绘制均值±3σ带。点击 3σ 曲线选中其全部参与光谱。切换模式保留 X 缩放、重新自动调整 Y 范围；删除 BSL 后退出 Residual，替换源文件夹时清除 BSL，磁盘源文件及其数据始终不变。计算规则与真实文件核对见 [BSL 与 3σ 验证](docs/validation/spectra-analysis-2026-11-02.md)。

Legend 区域的右键提供 **Show All / Hide All / Select Channel**，可跨当前着色组快速切换一个物理通道。选中曲线、光谱或 Die Map 点时，相应图例同步突出显示。

顶部 **Filter By** 可选 Wafer ID、Lot、PAD Name、Die，改变树的首层分类，其他身份继续保留在下层。切换分类保留光谱源身份、勾选、多选与当前绘图缩放。树底部的 Channel 数按同一仪器内不同 AOI/AZI 组合去重；缺少角度时使用文件内 Channel ID，相同通道不会按 Die 或文件重复累加。成功加载后不再在窗口底部重复显示 Loaded 统计。

该工具递归读取指定文件夹中的 `.sme` 光谱；**Load Spectra** 与 **Add Spectra** 位于 File 菜单，后者用于合并其他文件夹。树按 `Wafer → Lot → Pad → Spectrum` 展示，并显示 SME 文件名、Lot、Tool SN、PAD、Die、FIELD X/Y、时间、目录以及 Channel 信息。内部文件名优先，外部文件名只补缺失字段；依次识别 Wafer ID、Lot、Tool SN、PAD，旧命名缺 PAD 时使用第四段日期作为 PAD。Spectrum 行名只显示 Die 编号，测量时间保留在 Time 列。Spectrum 可单独勾选，同一 Spectrum 内的多个 Channel 在图中一起显示，图例按仪器、Channel、AOI（angle 1）和 AZI（angle 3）区分；角度标签显示整数，原始角度精度保持不变。树右键支持 Check All / Uncheck All 以及 Fold Tree / Unfold Tree。双击图例隐藏或恢复该 Channel。

绘图块包括完整的 4×4 Mueller 矩阵、N、C、S、Psi/Delta 双轴图和 DTS Reflectance，由 **Options → Views** 的勾选动作控制，菜单保持打开以便连续调整。各块与 Mueller 子图之间使用可拖动分隔条，拖动时预览边界、松手后更新布局；树与绘图区默认按约 1:3 分配宽度；所有分隔条都可收窄或折叠相邻区域，右侧或下方图占用腾出的空间，双击恢复初始比例；图例分区也可拖动调整；左键框选放大，右键拖动平移，滚轮缩放，图内左下角的 A 恢复自动范围。双击单个图会打开独立的悬浮放大窗口。绘图区使用白色背景、加粗曲线和标准 Tableau Category10 配色，X 轴范围紧贴可见数据；只显示图块标题和 X 轴标题，不显示 Y 轴标题。Psi 和 Delta 均用实线；选中光谱的曲线以 5 px 线宽高亮。图例分为 NCS、Psi Delta、Mueller、Reflectance 四区，只列出各类图有数据的通道，过多时在区内滚轮浏览；Options 关闭某类全部图后，对应 legend 区一并隐藏；双击任一区的通道仍会在所有图中同步隐藏或恢复该通道。

点击曲线或晶圆位点联动选择树中的光谱；Ctrl 点击可增减选择，Shift 点击可追加选择，树中的 Shift 点击可连续选择一段。树中选中分类分支代表选中其下全部光谱，包括未勾选项。树菜单按 Check All、Uncheck All、Check Selected、Uncheck Selected、Fold、Unfold、Delete Tree 排列；**Delete Tree** 仅从本次会话移除选中的光谱或分支，保留磁盘上的 SME 文件，没有选中时禁用。树和晶圆窗口的右键菜单均提供 **Check Selected / Uncheck Selected**，只切换当前选中光谱的绘图参与状态，保留其他光谱的勾选状态和当前多选结果。点击主窗口、悬浮光谱图或晶圆图的空白处（包括图块外侧留白），同步清除树中选中、曲线加粗和位点高亮，保留勾选状态与缩放。Open Die Map 使用与 WKB 子窗口入口相同的主按钮样式。

主窗口与悬浮光谱图的右键使用 PyQtGraph 原生 ViewBox 菜单：View All、X axis、Y axis、Mouse Mode，可编辑坐标范围及选择自动范围、轴反转和鼠标模式。View All 恢复完整数据并保持紧凑的波长范围。图块显示开关仍位于 Options → Views。

光谱绘图按每条源光谱裁剪视口外数据，并在边界保留线宽范围与相邻点。曲线开启抗锯齿；多颜色密集全览的屏幕折线使用 0.25 个物理像素的简化容差，放大或调整尺寸时按新像素比例重新生成。NaN 间断、源身份和完整源样本保留，不平滑、不平均或插值；计算、点击选中和原生导出仍使用原始数据。真实数据性能与全点原生绘制对照见 `scripts/benchmark_spectra_load_quality.py --verify-pixels`。

读取在后台进行，进度提示限制刷新频率，长文件名和加载控件不会挤压已有绘图区。TSD 加密封装单独标记为 encrypted，并提示从授权环境导出解密后的 SME 副本；其余可读取文件照常载入。重复 Add 不累积相同错误或重建未变化的曲线，保留现有缩放。密集绘图的数据准备与布局重绘逐图处理，曲线图像由两个后台进程绘制；窗口缩放时保留已有曲线预览，后台完成后换成新尺寸的清晰图像。连续更改只发布最新数据和坐标版本，取消勾选或关闭窗口会取消过期工作；高亮保持原线宽且不改变轴范围。全量图像仍需后台更新时间，具体耗时与输入停顿分别记录在 [读取与画质验证](docs/validation/spectra-load-quality-2026-11-02.md)。

**Open Die Map** 打开独立非模态窗口，每张图对应一个 Wafer ID、Lot、PAD 组合，标题包含这三个字段，默认 12 张图一页；图块保持正方形，并沿用按 X/Y 范围识别常见 100/200/300 mm 晶圆的规则。图内只绘制晶圆轮廓、全部有效坐标位点和 Die 编号，不插值或绘制色阶面。点击点会同步选择树中的 Spectrum、突出对应图例和高亮曲线。

不修改原光谱数据，不做插值或启用 OpenGL。BBSE 仿真样本保留在 `Simulation` 树分组中，不虚构 Die Map 位点；未知结构进入 `Load errors`。Instrument、Mode、SE3/SE3.5 等版本字段仅作信息展示，按实际通道数组结构读取，波长点数由各通道自身数据决定；支持已验证的 UVSE、IRSE 和 LDSR-P 数据，TSD 加密文件仍需授权环境提供可读副本。

Die Map 支持鼠标左键拖动框选，框内重合位点的全部光谱一起选中，树与曲线高亮同步。Ctrl/Shift 拖动追加选择；普通空框或空白单击清空选择。框选不会缩放或移动晶圆视图。

Mueller 横轴只显示自动生成的等间隔主刻度文字，保留次网格线与 tight 数据范围，缩放时重新选择间距。Die 标注使用固定的紧凑像素间距紧靠位点下方，不随晶圆直径向下一行偏移。树菜单在 All、Selected、BSL 三组之后显示分隔线，Unfold Tree 与 Delete Tree 之间不分隔。

## Match Workbook（v2 开发中）

该工具把日常的 Reference/Raw Data 匹配流程从手工 Excel 中独立出来。当前实现按以下顺序工作：

1. 先在 Reference 网格粘贴已经整理好的表。一个表可以同时包含多列参数，例如 `CD_Bot Reference`、`SPA Reference`。
2. 再在 Raw Data 网格粘贴原始数据。两个输入区与 Wafer Map / Correlation 的数据表操作一致：第 1 行是表头，可直接改单元格、区域粘贴，并用 `Ctrl+Z` 撤销。当前版本按从上到下的行顺序对应，两张表必须具有相同的行数。
3. 软件会把 `<参数名> Reference` 自动匹配到 Raw Data 中同名参数。像 `TEM`、`PMISH` 这样没有 `Reference` 后缀的数值列也会出现在映射表中，但不会擅自自动选择；可用 **Select all** 勾选全部候选项，再为它们选择对应的 Raw Data 参数。Wafer ID、Die Seq 等元数据不会列为参数。一次最多选择 50 个参数，最多处理 100,000 行。
4. 在顶部选择 **Preview** 或 **Final**。文件操作、KLA/NOVA/TEM Match Type、`Bias` / `Bias %` 和 Run analysis 都位于原生菜单栏；页面不再重复显示 Workbook 标题和设置面板。`Bias` 与 `Bias %` 各自独立开关：取消勾选会立刻移除对应的图，两个都不选时结果里只留 Match 与 Trend（工作簿内部仍保留主 Bias 模式）。

从主窗口启动 Match Workbook 时，先选择 **New Workbook**、**Open Workbook** 或最近文件。最近列表每行显示“文件名 + 保存时间（文件修改时间）+ 所在目录”，单击即打开。**Open Workbook** 与最近文件都直接按文件里保存的 Match Type、Bias、Trend Y axes、倍率和原来的 tab 打开，不再经过设置页，打开后保持已保存状态；只有 **New Workbook** 需要确认 Analysis 设置：默认 KLA、Bias、Auto 10×、Preview，且至少选择一个 Bias 视图。旧文件两个 Bias 视图都不选时也能直接打开，之后可在 Analysis 菜单补选。取消不会留下空窗口。File 的 **New Workbook…**（Ctrl+N）与 **Open Workbook…**（Ctrl+O）遵循同一规则。Final 缺少输入时进入等待补数据的页面。Analysis 设置在 Preview/Final 间共用。
5. 首次执行 **Run analysis** 后，Slope、Intercept、R²、Valid pairs 等结果直接显示在 Parameter mapping 的同一行。以后在 Raw Data 的 A1 粘贴新表或更改 Raw Data column 都会自动重新分析，不需要重复点击；Reference 与 Raw Data 都直接在网格中按 `Ctrl+V` 粘贴（只覆盖粘贴范围），`Ctrl+Shift+V` 才清空整表再粘贴；单元格编辑和 Delete 清空均可用 `Ctrl+Z` 撤销。Raw Data 暂时清空或缺少原参数列时，Reference 建立的映射仍会保留，界面会提示重新选择缺失的 Raw Data column。Slope 小于 0.9 或大于 1.1、R² 小于 0.9 时，值会以红色警示并说明阈值。Parameter mapping 里的 **Raw Data column** 下拉框不吃鼠标滚轮：滚轮只滚动页面，不会误改映射（其他下拉框仍是标准行为）。

Parameter mapping 的 **Show Die Map** 在有超限点的晶圆中保留全部可定位的 Raw 点：Data selection 未勾选为浅灰，勾选且超限为红色，其余勾选点为蓝色。Hide excluded rows 只隐藏表格行，不移除图上灰点；Apply 后颜色同步更新，坐标未变时保留图对象和缩放。关闭的 Spectra 草稿只读取缓存坐标元信息，不打开 Viewer 或解码光谱采样。
6. 结果区分为 **All parameter plots** 和 **Single-wafer metrics** 两个 tab。全部参数按纵向卡片显示，只有一个参数时也从结果区顶部开始；Match、Trend、Bias、Bias % 按当前选择排在同一横行。Match 固定为 510 × 330 px，Trend、Bias 和 Bias % 统一为 330 px 高并平分剩余宽度；四图同时显示时也会收进可见工作区，不需要横向滚动且不会互相重叠。绘图区上下对齐、四边同粗，Trend/Bias 不再重复显示 Wafer 轴标题。Trend 右上角的 **Card** 可在原始 PMISH 与加 Card 后的 PMISH 间切换。拖动参数卡标题时会显示半透明预览和淡入的插入位置；当前顺序会直接保留，不再占用空间显示 Reset。输入、映射和结果区之间的分隔线可以拖动；首次运行成功后，修改 Reference、当前模式的 Raw Data 或 Parameter mapping 会自动原位刷新，并保持分隔栏、滚动位置和参数顺序。Preview 与 Final 各自保留独立 Raw Data，切换模式不会清空另一侧数据或已有结果。当前模式对应的 **Open Preview/Final Wafer Map / Radius** 与 **Open Preview/Final Dynamic** 位于顶部右侧。

顶部右侧还提供 **Open Correlation and Trend**：它直接读取当前模式的 Reference 与 Raw Data，分别显示在两个数据页。Raw Data 保留全部原始列；Ref Data 用 parameter mapping 的参数名显示量测值，并把 Wafer ID、Lot ID、PAD Name 与 Die Seq 按行对齐 Raw Data。Correlation 只在 Reference 内部或 Raw Data 内部拟合，不做跨来源 correlation；所有 Reference 图先显示并使用橙色，随后是蓝色 Raw Data 图。Trend 使用相同的来源顺序与配色。

三个分析窗口与 Match Workbook 的联动规则：

- **KLA / NOVA**：三个窗口可以同时打开，**Wafer Map / Radius** 与 **Correlation and Trend** 的 Data 会跟着 Match Workbook 的 Reference / Raw Data 同步刷新（Map 由 Raw Data 经 Card 推导，Correlation 直接读取 Ref/Raw）；一旦你在其中某个窗口里改过表格，该阶段就以你的修改为准，不再被覆盖。
- **Dynamic 在任何模式下都是独立数据**：Preview 与 Final 打开时都只恢复它自己保存的 Dynamic 表（工作簿里没有就开空白），不会复制 Match Workbook 的 Raw/Map 数据，也不跟随它刷新；之后完全由你在 Dynamic 窗口里编辑，保存时按自己的表快照写回。
- **TEM**：Map/Radius 也是 TEM 自己的独立表（Raw Data 变化时不会被刷新）；只有 **Correlation and Trend** 会跟随 Match Workbook 的 Ref / Raw 刷新。三个窗口可以同时打开，但**每个按钮最多一个窗口**——重复点同一个按钮不会开出第二个，而是把已有窗口带到前面并刷新它的数据。

这种刷新**只换数据**：无论是改 Raw Data、改 Reference，还是改 Parameter mapping，子窗口都保持原样——

- 停留的 tab、可编辑网格里的当前单元格与滚动位置不变，不会甩回第一页或 A1；
- 页面内“方框选择页 vs 绘图页”的切换保持你选的那一页，绘图在后台完成；
- Wafer Map 的画布缩放/滚动、Radius 的缩放/滚动，以及 Correlation 结果翻到第几页（例如第 2 页）都会保留，新的数据直接画在原来的视图里。

Card 的定义为：

`Reference = slope × Raw + intercept`

- **Preview** 会把新生成的 slope/intercept 应用到当前 Raw Data，得到 Card Value，再用它绘制 Trend、Bias、Wafer Map 和 Radius Plot。
- **Final** 使用自己的 Raw Data，假定这些值已经由 OCD 软件应用 Card，不会复用 Preview Raw Data，也不会重复加 Card；Trend、Bias、Wafer Map 和 Radius Plot 都直接使用 Final 输入值。
- `Bias` 是 `Evaluated Value - Reference`；`Bias %` 是 `(Evaluated Value - Reference) / Reference × 100%`。两者可以同时显示，Reference 为 0 时百分比留空，不猜测替代值。
- KLA/NOVA/TEM 的 Single-wafer tab 使用 Raw Data 的 Wafer ID、Lot ID 和 PAD Name，并沿用 Wafer Map 的默认身份规则；只有真正变化的 Lot/PAD 才参与分组，Die Seq 不单独拆组。多个身份字段分行显示，避免横轴文字重叠。TEM 同样支持 Head/Mark 分组和 Data selection（Group settings、Order 表都可用），结果区显示 **Single-Wafer metrics**，启用分组后也显示 **Group plots**。
- Match 始终显示线性拟合，不再提供重复的开关；图名使用映射的 Raw Data column，横轴是 PMISH、纵轴是当前 Match Type。参数名与两行拟合公式/R² 使用绘图区上方的独立标题栏，公式位于参数名右侧且不会覆盖曲线或数据点。Match、Trend、Bias 和单片指标图统一显示完整四边坐标轴，并与 Correlation and Trend 一样支持 Ctrl+滚轮缩放、左键拖框放大、右键平移和双击自动适配；不按 Ctrl 的滚轮会继续滚动外层页面。Trend 中 PMISH 使用蓝色实线圆点，当前 Match Type 使用橙色实线圆点，且不重复显示无意义的纵轴名。Bias 使用蓝色点线并按原始数值显示 `Bias (nm)` 和 `Bias (%)`，禁用自动 SI 缩放，不再出现 ×0.001 或百分比系数。分析层仍按需生成每个参数的派生数据，界面只保留经过极值采样的绘图数组，不复制 50 份完整结果表。

**Save Workbook** 保存 Reference、Preview/Final 独立 Raw Data、参数映射、Bias 显示选择、分析设置、分隔栏布局、参数顺序，以及三个分析工具中实际显示和编辑的数据及配置。各阶段勾选的 wafer、parameter 和已确认的绘图选择也一起写入 `.wkb`，无需逐个子工具另存。KLA/NOVA 在尚无 Map 快照时由相应 Raw Data 初始化；TEM 需输入独立 Map 数据。已保存的 Preview/Final 分别恢复，不互相覆盖。

父窗口 **Save Workbook As…**（`Ctrl+Shift+S`）另存整本工作簿，新路径成为后续保存目标。子窗口保存、独立副本与关闭提示的范围见下方“统一文档保存与恢复”。**Open Recent WKB** 保留最近成功打开或保存的工作簿，**Reveal Workbook in Folder** 定位当前文件。旧 WKB 缺少独立 Final、Map、Dynamic 或选择状态时仍可读取。文件内含数据，不依赖原 Excel/CSV，也不执行 pickle。

**Export Excel** exports editable native charts; **Export Matplotlib** redraws the plots with Matplotlib and embeds them in one workbook. An export dialog selects the output sheets (all by default); unselected formula/chart dependencies remain hidden and editable. Match parameter tables start horizontally at A1, with plots over the data from A5 and literal Raw Data to the right. Reference inputs live in those parameter tables without a duplicate visible Ref block. Preview sheets end with `(WO Card)` and Final sheets with `(W Card)`. FM starts its prepared Wafer/Die Seq/parameter report at A1 and its visual columns at A5: FM Trend (TEM only), Wafer Map, Radius. The complete Copy PNG grid is retained; each Map grid row is 8 cm high. Dynamic retains editable sources, linked pivots and 3 Sigma charts, with 18 cm-wide charts and a top-aligned summary; per-Die Cycle Trend remains in the application but is not duplicated in Excel.

Each stage includes Original, Group and Wafer views. Group/Wafer formulas refer back to Original by source row without altering literal measurements. Trend/Bias retain every observation and tight X limits; their width grows with visible Die Seq and identity-caption demand, and tick marks match visible tick-label spacing. Wafer and Group footer layers follow the WKB hierarchy. Generated text uses English and Times New Roman.

Native Match charts use a real Excel linear trendline with editable equation/R² labels, not a synthetic Fit series. Select the measurement series to expose its draggable X/Y source-range outlines. Editing worksheet inputs refits the Excel trendline; software Card calculations are not replaced by that independent fit. Titles/equations are centered. Match markers are 5 pt; Trend/Bias use 4 pt markers and 1.8 pt strokes. Matplotlib uses the corresponding thicker styles.

Large menu exports prepare an owned report in a separate process, with up to six bounded Agg rendering workers on machines with at least 12 logical CPUs (up to four on smaller machines). Repeated Wafer layouts are reused within that export, redundant merged-caption work is avoided, and `lxml` accelerates XML writing. Data, panel count, resolution and physical sizes are unchanged. The owner publishes only the complete report; cancellation or a failed publication retains the previous file. Cancellation during final XLSX serialization waits for that write to finish safely. See [NOVA export measurements](docs/plans/nova-export-performance-2026-10-16.md) for machine-specific timings and remaining performance work.

存储模块基准：10 万行 × 50 个四位小数文本参数加两列标识，保存约 0.96 秒、载入约 1.58 秒、文件约 43.54 MiB，逐项往返一致（2026-10-03 当前开发机一次实测，不代表全部硬件，不包含 GUI 出图，也不是旧格式对比结论）。可用 `python -m benchmarks.benchmark_workspace_store` 复测。Card 计算可单独用 `python benchmarks/benchmark_matching.py` 测量。

Wafer Map 或 Radius Plot 成功绘制并保存过后，WKB 会分别保存“自动绘制已启用”和实际框选组合。保存子窗口再打开、或重新加载 WKB，都会恢复仍存在的组合并直接出图，不必再次点击 **Draw selected**；尚未确认 Draw 的新框选仍等待点击，不自动绘制。旧 schema 1–10 仍可读取。

### 统一文档保存与恢复

最近工作簿选择界面和 Shell 最近菜单只读取文件类型元信息。打开 Match Workbook 时，尚未打开的 Spectra 子窗口草稿保留为只读磁盘快照，按需读取；保存、另存和恢复继续携带完整光谱，不会把未加载的数据当成空数据。SQLite 表使用原生 fetch 读取，保留原始字符串、列类型和行序；旧 `.mwkb` 格式保持兼容。

Match Workbook 使用 SQLite `.wkb`；独立 Wafer Map / Radius 使用 `.wmap`，Dynamic `.wdyn`，Correlation and Trend `.wct`。**Ctrl+S** 保存当前文档，独立工具和 Match 父窗口的 **Ctrl+Shift+S** 另存为。主窗口菜单的 Open Workspace、最近文件和拖放按内部类型打开正确工具。旧独立 `.wkb` 仍可读，第一次 Save 会要求另存规范后缀，原文件保留。

三个独立工具自己的 File 菜单也有 **Open…**（Ctrl+O）和 **Open Recent**。最近文件复用持久化记录，只显示本工具兼容的正式工作区，过滤缺失、损坏和恢复草稿；打开前仍确认未保存修改，取消不会替换当前文档。Open 与数据区原有 Ctrl+O 共用一个动作，不重复注册快捷键。

Match 内的子工具显示所属文件，**Save Changes to Workbook**（Ctrl+S）保存当前分析加父当前数据/公共设置，不接受其他子草稿。父 **Save Workbook** 保存全部分析草稿；整本 **Save Workbook As** 只在父窗口，子窗口没有隐藏 Ctrl+Shift+S。需要单独分享时选 **Export Standalone Copy**：复制完整实际数据及当前配置成对应独立文件，不改原路径、角色和未保存状态；副本以后独立编辑，不自动回写 Match。子表独立修改后不会被父源数据覆盖，**Use Workbook Data…** 须明确确认，而且替换后仍需正式保存。TEM 的 Preview/Final Map/Radius 与 Dynamic 使用独立数据，不提供该替换操作；Correlation and Trend 仍保留。已打开窗口的菜单会随 Match Type 切换更新。

CSV 按钮是 **Export CSV**，导出不表示文档已保存。Correlation/Trend 保存 Ref/Raw 双表、选择、分页、共享轴策略和 Add Compare；Dynamic 保存实际数据、显示设置和各参数的 Die 选择。重复打开同一 Match 阶段工具只激活原窗口，不刷新掉草稿。

新容器使用版本化状态与生成的 SQL 标识，能保存重复表头待修复草稿，并保留 `001`、`2.1000`、`NA` 和列/行顺序。载入后重新计算图表，不保存可执行对象或图片缓存。正常覆盖保留完整文件名加 `.bak` 的上一版，例如 `.wmap.bak`；同一文件在其他窗口更新后会拒绝过期覆盖，可重新打开或另存为。保存和副本导出会提交尚未失焦的编辑器，不强制 Draw。

脏文档按 **Settings → Recovery interval** 周期另写恢复草稿，不覆盖正式文件。自动 recovery 使用后台单写入者生成完整 SQLite 候选，保留校验、fsync、锁和最终 revision 检查；重复请求只保留最新待处理标记，Save/Open/Recover/关闭决策期间暂停，过期候选不发布。主线程仍负责安全快照采集与最终替换，不能保证任意数据量零停顿。Match 仅父窗口负责聚合恢复，包含正式基准和各子草稿；保存一个子窗口后，剩余草稿继续保留。父 **Recover Workbook Draft** 或独立工具 **Recover draft** 从 `%LOCALAPPDATA%/MetrologyWorkspace/recovery/` 恢复，恢复后仍需正式保存。新恢复 scope 使用版本 2，旧软件拒绝误读，正式容器仍为版本 1。所有有修改的窗口关闭时提供 Save/Discard/Cancel；应用退出先完成全部保存决策，后续取消/保存失败不会提前放弃其他文档。首次周期内或写盘失败的修改不能保证恢复。完整边界见 [当前存储方案](docs/plans/workspace-storage-v2-design.md) 和 [ADR 0003](docs/adr/0003-typed-workspaces-and-independent-copies.md)。

当前 v2 已把 Preview/Final 作为顶部模式页，并将各自的 Raw Data 交给现有 Wafer Map 和 Radius Plot；独立 FullMap 输入页已移除。尚未实现的是按 Wafer ID、Slot ID、PAD Name 和坐标自动整理尚未对齐的 Reference；当前匹配数据仍按行序对应。

Bias 与 Bias % 的纵轴按实际曲线数据自动适配，Preview/Final 使用相同规则；零参考线不参与范围计算，只有视野包含 0 时显示。原始数据与 Bias 计算不变，缩放后的 Auto Scale 和导出图片也使用这一范围。

## Dynamic

Dynamic 用于同一 wafer 上若干 Die 的重复测试。导入数据后，软件优先从 `Cur SME File Path` 中的 `DYNAMIC/<run>` 识别每轮测试；如果路径没有该结构，则在有序 Die Seq 首次重复时开始下一 Cycle。Die 数量和 Cycle 数量均不固定。旧 Excel 透视表若位于第一个空白列之后，会在导入时排除，避免把报表列误当成新参数。

第一个 tab 复用 Data 编辑器与 Wafer Map 的 Wafer ID / Lot ID / PAD Name measurement identity，可勾选 DP、EW、TG 等数值参数。粘贴或打开替换表格时，会按列名保留新表中仍存在的参数选择并直接重算，无需重新勾选；Wafer Map 使用相同规则。第二个 tab 要求选择一个 measurement set，并分成上下两个独立滚动区域：上方按勾选顺序纵向显示每个参数自己的 Cycle × Die Seq 透视表；下方先用不同颜色在一张图里比较全部已选参数，再分别显示每个参数的 3σ 图。合并图不重复显示参数拼接标题，原标题行改为带小色块的横向 legend。

透视表的数值格可以直接编辑，用的就是 Data 表格那套键位：单击选中后输入新值、`Delete`/`Backspace` 清除格点（常用来删掉离群点）、`Ctrl+C` / `Ctrl+V` 复制粘贴选区、`Ctrl+Z` / `Ctrl+Y` 单步撤销与重做。编辑会写回 Data 表对应行的同一个参数列，所以既是可保存的数据修改，也会立刻重算该列的 `3 Sigma`。Cycle / Die 标签和由数据推导的 `3 Sigma` 行保持只读。每个参数标题右侧有 **Restore**：一键把该参数的格子恢复到打开表格时的值（删除过的格点会回来），本身也是一步可撤销操作；想只撤掉上一步删除就按 `Ctrl+Z`。编辑后表格和图表都保持在原来的滚动位置与当前格子上。

每张表底部的 `3 Sigma` 使用跨 Cycle 的样本标准差 `3 × std(ddof=1)`；柱图以 Die Seq 为横轴、3 Sigma 为纵轴并固定为 420 × 270 px，只显示柱形、不叠加数据点，每行最多三张，超过三张自动换到下一行。页面不再提供参数下拉框或重复的 Dynamic 标题。相同 Cycle/Die Seq 出现多行时会直接报告歧义，不会静默取平均。

数值编辑、Delete、粘贴及 Ctrl+Z/Y 使用局部刷新：只重算改变的参数，并原位更新对应表格、3σ 柱图和 Trend 曲线，不销毁其他参数的控件。缩放、滚动位置、当前格和 Die 选择保持不变；改变参数/wafer 选择、Cycle/Die 结构或列布局时才完整刷新。编辑合并等待为 50 ms，统计公式与撤销粒度不变。可运行 `python benchmarks/benchmark_dynamic_edits.py` 重测：开发机上 10 Cycle × 13 Die × 26 参数的合成数据，9 次编辑/撤销（去掉首次）的中位刷新耗时从约 4.1 秒降至约 0.1 秒；不含等待时间，实际耗时取决于数据和机器，`--profile` 可查看热点。

第三个 tab **Trend** 和 Correlation and Trend 里的 Trend 页用法相近，但横轴换成 **Cycle**：每个勾选参数各占一张交互图，**每张图一次只画一个 Die**，用图右侧的 **Die 下拉框**切换要看哪一个（默认 Die 1，颜色与符号按 Die 序号固定，方便对照）；这样能直接读出某个 Die 在几轮重复测试之间的漂移，而不会十几条线叠在一起。这里没有 Add Compare 控制栏，也不做曲线框选——参数、Die 和 Cycle 全部来自 Data 勾选与当前 measurement set，数据一改就自动重画，并且记住每个参数各自选的 Die。下拉框不吃鼠标滚轮：滚轮只滚动页面，不会误切换 Die。支持 Ctrl+滚轮缩放、左键框选放大、右键平移、双击适配、**Reset views**、Columns 1/2、Font、Resolution，以及 **Export PNG** / **Copy PNG**（Ctrl+C 同样可用）；导出的每张图标题会写成 `参数 · Die n`。

## Wafer Map

基本流程如下：

1. 在 Data 中勾选测量条目和参数。
2. 切换到 **Wafer Maps**，确认 X、Y 坐标列。
3. 在方框阵列中拖动选择要绘制的组合。Ctrl 用于增减选择，Shift 用于扩选，**All** 和 **None** 可以全选或清空。
4. 点击 **Draw selected**。只有选中的组合会参与计算，画布也只保留实际用到的行和列。

Wafer Maps 成功绘制一次后会记住实际绘制的方框。此后**只有数值本身变化**时（粘贴、打开、单元格编辑）才会用新数据自动重绘并继续显示图，不再跳回方框选择页；如果 wafer 身份全部变化，则把上次绘制的参数应用到新的 wafer。只要方框选择或 Data 里的 Wafer/Parameters 勾选发生变化（增加或减少参数、增删测量条目），都不会自动重绘：页面回到方框选择页，需要重新选择组合并点击 **Draw selected** 才会绘制。这样参数一变就不会再拿旧方框直接出图。Radius Plot 独立记忆自己的上次方框，并采用同样的规则。

从 Match Workbook 打开的 Wafer Map / Radius 与 Dynamic，Data 页的 Parameters 卡片里多一个 **Card** 勾选框：**默认不勾**，表格保持你载入/粘贴的原始数值；勾上后，`parameter mapping` 里那些参数会按各自的 Card（`slope × value + intercept`）参与绘图与统计。表格内容不会被改写，取消勾选即回到原始值。没从 Match Workbook 打开的独立窗口没有 Card 可套，该勾选框保持禁用。

坐标列优先匹配 `X(mm) / Y(mm)`，其次是 FIELD X/Y 和 X/Y，也可以手动指定。阵列中的行对应测量条目，列对应参数。同一个 Wafer ID 下，不同 PAD Name 会作为不同条目。

每张图第一行为参数名，第二行为 `Group · Wafer ID · Lot · PAD`（无 Group 时省略该项），第三行为 Min/Max/Mean/Sigma。Sigma 是有效量测点的总体标准差（1σ，ddof=0），不从插值网格统计。默认色阶为 Turbo，也可以选择 Viridis、Plasma、Jet、Coolwarm 或 Spectral。**Colors** 两端的手柄用于裁剪调色板范围；拖动时只更新颜色，不重新计算 RBF。**Opacity** 只改变填色透明度，等值线和测点保持实心。

Wafer Map 的 **Groups** 菜单支持本地 Head/Mark/TestFlag、Enable Groups、Use WKB Group settings 和一次性 **Copy WKB Groups**。只显示分类，不按 Group 拆分晶圆或改变参与行；切换分类和标题时复用已有曲面。Group settings 使用带身份列的紧凑明细表。新独立配置默认 Mark 为 POR（Fallback）、POR+、POR-，保留旧文件及复制的自定义值；Marks 的批量分配提供 Replace / Append，叠加会生成真正的 `Old/POR` Mark。配置随独立文件/WKB 子窗口草稿保存。

**Point values**、**Measurement points**、**Contour lines**、**Point outline** 和 **Scale bar** 可以单独开关。程序会复用已有插值结果，因此切换这些显示项不会改变当前缩放或滚动位置。在 18 张图的测试数据上，叠加层更新约为 0.05 秒；原来的完整重绘约为 1.2 秒。

每张图默认使用独立色阶。需要比较不同测量条目的绝对数值时，打开 **Shared scale / parameter**，让同一参数共用色阶。

**Diameter** 设为 Auto 时，X(mm)/Y(mm) 坐标会识别 100、200 或 300 mm 标准晶圆。300 mm 晶圆的坐标范围固定为 -150 到 150 mm。其他坐标类型按数据范围估算，也可以手动输入直径。

**Fill edge** 用外侧测点的径向镜像样本估计凸包之外的区域。该区域不是实测数据。关闭后，凸包外保持空白；开启后，结果仍限制在实测 Min/Max 范围内。

Wafer Map 和 Radius 的屏幕图使用 PyQtGraph，图内不缩放、平移或点选；窗口仍可调整大小。**View** 支持适宽和 1% 到 300% 整页缩放。普通滚轮纵向滚动，Shift+滚轮横向滚动，Ctrl+滚轮按指针位置缩放整个拼图。**Resolution** 提供 Standard、High 和 Ultra，分别对应 200、300 和 400 dpi 的 Matplotlib PNG 输出。图像过大时，复制和导出会自动降低 DPI，避免耗尽剪贴板或内存。

**Export…** 支持 PNG、SVG 和 PDF。SVG/PDF 中的坐标轴、标题、等值线、测点和 colorbar 刻度保持矢量；插值色面作为图像层嵌入。**Copy PNG** 会复制整个阵列，包括当前滚动区域之外的内容。

同一测量条目中，只要坐标一致，多个参数会共用一次 RBF 矩阵求解。显示网格按图数自动调整：不超过 12 张时使用 400 × 400，不超过 48 张时使用 300 × 300，更大的阵列使用 200 × 200。插值平滑可以在 Settings 中选择 Off、Light、Medium 或 Strong。

## Radius Plot

Radius Plot 使用 Data 中当前勾选的测量条目和参数，但保留自己独立的方框选择；首次绘制后，Data 更新会直接按上次组合刷新，不再要求重复选择。横轴按下式计算：

`signed R = sign(X) × sqrt(X² + Y²)`

X < 0 位于负半轴，X > 0 位于正半轴，X = 0 时半径为 0。每个“测量条目 × 参数”单独绘制，不会把多组数据叠在一张图上。标准毫米坐标沿用 100/200/300 mm 晶圆识别，缩放、字体、分辨率和 PNG 输出规则与 Wafer Maps 一致。

## Correlation and Trend

**Groups** 菜单可开关 Group 显示，使用 **Group settings…** 配置与 Match Workbook 相同的 Head、Mark、TestFlag 和 Trend 分组顺序。**Plot labels** 可独立开关 PAD / Lot 标签。WKB 子窗口默认跟随父窗口的 Group 和 Plot Label 设置；取消对应的 **Use WKB…** 后可在子窗口单独配置，不会修改父工作簿。选项随独立文档或 WKB 子窗口草稿保存；关闭 Group 显示不改变数据参与状态。

Correlation and Trend 同样使用紧凑 Group 身份明细表、新独立配置的 POR/POR+/POR- 默认 Mark、Replace/Append 和一次性 **Copy WKB Groups**。一次性复制后不继续跟随父窗口，原有连续跟随开关仍可使用。Ref Data 和 Raw Data 表现在均可使用 Wafer Map 同款元数据列锁：点击列名格的锁图标或 Ctrl+L 切换；锁保护列名、原始字符串和行位，粘贴/删除只改未锁内容，形状冲突明确提示；锁状态随独立文件和子窗口草稿保存。

该工具用 **Ref Data** 与 **Raw Data** 两个独立页保留来源表；Raw Data 始终显示全部原始列，Reference 的 Wafer ID、Lot ID、PAD Name 与 Die Seq 按行取自 Raw Data。两个页面支持同样的导入、粘贴和编辑操作。新表格会默认选中所有测量条目，并勾选可用的建模参数列。MSE、GOF、NGOF、LBH、fitTime、regIter（包括 `reglter` 拼写）、CINDEX、Seq、Logical ID，以及 `Cur SME File Path`、Wafer ID、Lot ID、Tool SN、PAD Name、Die Seq、FIELD X/Y、X(mm)/Y(mm) 都不是建模的物理参数，不会出现在参数列表里。名称匹配忽略大小写、空格、下划线和连字符。双来源模式下，Correlation 先列完 Reference 的来源内拟合，再列 Raw Data；Trend 也按 Reference 后 Raw Data 排列，并以橙色/蓝色区分来源。

### Correlation

Parameter buttons support single selection, Ctrl+click for multiple parameters, and Ctrl+Alt+click to isolate the correlation between two parameters. A third Ctrl+Alt selection starts another pair; ALL restores all eligible fits. This display choice is saved with the WKB and does not change measurements, fit thresholds, regression results, or X/Y direction. Ctrl+Alt+Space provides the same pair selection from the keyboard.

Correlation 使用 `lmfit.models.LinearModel` 对所选 numeric 列做两两线性拟合：

`y = slope × x + intercept`

无法成对转换为数值的行会被忽略；有效点少于 3 个或存在常数列时，该组合会跳过。方框阵列同时限定参数和测量条目。例如选择 3 个测量条目和 2 个参数，只会得到 1 个基于这 3 组数据的拟合。

结果按 R² 从高到低排列。Min R² 默认是 0.50，只有严格满足 `R² > 0.50` 的结果会显示。修改阈值只过滤现有结果，不会重新拟合。一次最多选择 40 列，屏幕最多显示排名最高的 12 张图，状态栏会给出完整的通过数量。

屏幕图由 PyQtGraph 绘制。普通滚轮滚动外层页面，按住 Ctrl 再滚轮才缩放当前图；左键拖动框选区域，右键拖动平移，双击恢复单张图；**Reset views** 恢复全部图。面板边界也可以拖动，双击边界恢复等分布局。默认三列布局会根据窗口宽度伸缩，不会横向裁掉最后一列。

**Export PNG** 使用 Matplotlib 输出完整图，**Copy PNG** 直接复制当前 PyQtGraph 阵列。复制包含滚动区域外的图，并缓存相同设置下的结果。

### Trend

Trend 按 Data 页顺序把每个 numeric 参数画成连续的 Die Seq 曲线。横轴保留真实 Die Seq，允许缺号；下方的第二条轴标出各段对应的 Wafer ID，测量条目之间用浅色虚线分隔。

方框选择决定要画的参数和测量条目。未选条目会跳过，横轴只覆盖实际有曲线的区段。默认双列布局会随窗口宽度伸缩。普通滚轮滚动外层页面，按住 Ctrl 再滚轮才缩放当前图；左键拖动框选区域，右键拖动平移。Auto Scale 会重新适配 Y 轴，但保留紧凑的 X 范围。右侧边框会一直显示。该页也支持 Reset views、Export PNG、Copy PNG 和 Ctrl+C。

默认仍是一个参数一张图。需要比较趋势时，每张图右侧的 **Add Compare** 可以叠加任意多个已勾选参数：每点一次增加一个下拉框，滚轮即可快速切换，`×` 只移除该行。Reference 固定橙色实线、Raw Data 固定蓝色虚线，新增对比曲线使用橙蓝之外的颜色与不同点形；图例始终显示来源与参数名。

拆轴规则由 **Analysis ▸ Trend Y axes** 控制：`Auto` 默认按单位与中位绝对值比例判断，可在 spinbox 输入小数阈值（默认 10×）；单位不同，或同单位两条曲线的中位量级相差超过阈值时增加着色右轴。也可选择 `Always two Y axes` 或 `Always one Y axis` 强制绘制；强制单轴混用不同单位时，轴标签和状态栏会明确标记。模式与阈值由 Preview 和 Final 共用，立即同步到两边已打开的 Trend，并作为一份工作簿设置保存到 .wkb；切换 tab 或重开窗口不会覆盖设置。旧 WKB 两边值不同则采用文件保存时所在 tab 的值，只有倍率时默认沿用 Auto。独立打开的 Correlation and Trend 在 Trend 选项栏保留相同的模式与 spinbox。对比关系随所属 WKB 保存，不再写入全局应用设置；重新打开时按仍存在的组合恢复。对比控制区宽度固定、**高度与绘图区一致**（`Add Compare` 与各下拉框保持在顶部，边框圆角与卡片一致），增删下拉框不会压缩绘图区；重绘保持面板列表的滚动位置，不会跳回顶部。

Trend 的 Y 轴单位按 OCD 行业规则识别：名称含 `SWA` 视为 degree，含 `ratio` 视为无量纲，其余建模参数视为 nm；列名末尾自带单位（如 `EW (V)`、`Si_SWA [rad]`）时以显式单位为准。

## 数据识别与限制

- 勾选的身份字段共同定义测量条目。`Wafer ID` 一定参与；`PAD Name` 和 `Lot ID` 只有存在多个不同值时才默认加入。
- Die Seq 是测点元数据，可以跳号或缺号，不用于拆分测量条目。
- 空白身份值不会自动向下填充，也不会猜测。
- 同一测量条目内不允许重复 X/Y。程序会报告无法拆分的重复点，不会擅自平均或覆盖原行。
- 无有效数据的组合会留在画布中并显示原因。修改数据、选择或设置后，旧结果会隐藏。
- 每批最多处理 120 个阵列位置。Wafer Map 会结合勾选参数数量自动缩小每页晶圆数，保留全部参数，通过翻页访问全部晶圆；例如 24 个参数时每页最多 5 片，不再因默认每页 12 片超出上限而整批失败。

Wafer Map 使用 SciPy 薄板样条 RBF 插值。它用于展示和比较量测结果，不是 KLA 专有算法的复现。目前不提供 A/B 差值界面，也不会自动换算测量单位。

项目附带的 CSV 放在 `sample_data/`。测试数据不会在运行或测试时被改写。

## 代码结构

```text
main.py                    程序入口
sample_data/               示例量测数据
config/                    源码版运行设置（不提交 settings.yaml）
docs/                      开发交接文档
metrology_app/             应用主包
  shell.py                 主窗口、分析窗口和诊断 Log
  module_registry.py       工具注册信息和延迟创建工厂
  matching/                Card 拟合、按参数惰性结果和 WKB 存储
  matching_window.py       Reference-first 工作流、结果图和导出
  dynamic.py               Dynamic Cycle 推断、透视表和样本 3σ
  dynamic_window.py        Dynamic 的 Data + analysis 窗口
  dynamic_page.py          Dynamic pivot 表和 3σ 柱图
  correlation_window.py    主窗口与 WKB 共用的双数据页 Correlation and Trend 工具
  correlation_page.py      两两线性拟合、R² 排序和相关性图
  sequence_page.py         Die Seq 趋势图
  plotting/                PyQtGraph 交互、外框和可调整面板网格
  data.py                  文件导入、字段识别和数据筛选
  measurements.py          Wafer/Lot/PAD 测量身份识别
  sheet.py                 表格编辑、复制粘贴和撤销
  window.py                Wafer Map 主窗口和页签联动
  sme_spectra.py           SME 解析、身份、坐标和批次合并
  spectra_plots.py         Mueller/NCS/Psi-Delta 的 PyQtGraph 面板
  spectra_viewer.py        Spectra Viewer 树、图例和多面板绘图
  spectra_map.py           按 Wafer 分页的可点击测量点图
  plot.py                  单张 Wafer Map 插值和绘制
  array_plot.py            阵列数据准备、检查和布局
  map_selector.py          方框选择
  plot_page.py             Wafer Map 绘图区、后台插值和导出
  radius_page.py           Signed radius 绘图
  settings.py              YAML 设置读写
  settings_dialog.py       设置窗口
tests/                     单元测试和 Qt 回归测试
```

主窗口只依赖注册信息，分析模块在第一次打开时才导入。绘图页通过 `window.selection = {wafers, metrics, wafer_column, groups, labels}` 接收当前选择；`groups` 始终映射到原始行位置，不会向用户数据中插入辅助列。

## 界面说明

界面使用 Segoe UI Variable，中文回退到微软雅黑。深色主题采用紫黑背景和紫色交互色，浅色主题使用中性灰白配色。当前布局针对量测数据编辑和多图比较设计，并非某款仪器控制界面的逐像素复制。

## 验证

KLA/NOVA 的 TestFlag、可命名测头、可选自定义 Mark 分类、三表筛选及分组 Match/Trend 用法见 [分组分析说明](docs/plans/match-measurement-groups.md)。

在项目目录运行：

```powershell
conda run -n metrology-workspace python run_tests.py
```

测试覆盖数据识别、编辑操作、插值、绘图、导出、窗口行为、Correlation/Trend 交互以及 Card Matching/WKB 工作流。`run_tests.py` 使用 scratch 设置与 recovery，避免覆盖用户的主题和 Open Recent 列表。开发过程中生成的截图和临时视觉检查文件不纳入项目。

当前开发状态和 Skill 使用约定见 [docs/HANDOFF.md](docs/HANDOFF.md)。
