# Metrology Workspace

Metrology Workspace 是一套 Python 3.10+ / PyQt6 桌面工具，用于整理量测数据、完成 Card 匹配、Dynamic 重复性分析，并绘制 Wafer Map、径向图、相关性图和 Die Seq 趋势图。主窗口依次提供 **Match Workbook**、**Wafer Map**、**Correlation and Trend** 和 **Dynamic** 四个工具。每次打开都会创建一个独立窗口，同一工具可以同时开多个实例。当前正式源码版本为 **v3.0.2**，在 `main` 分支维护；功能、验证及已知限制见 [v3.0.2 发布说明](docs/releases/v3.0.2.md)。历史版本与开发版标签保持不变。

## 运行

项目已经提供 Anaconda 环境文件。首次使用时，在项目目录执行：

```powershell
conda env create -f environment.yml
conda activate metrology-workspace
python main.py
```

本机环境位于 `C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace`。在 VS Code 中选择该目录下的 `python.exe` 即可运行和调试。环境会独立安装 `requirements.txt` 中的依赖，不使用系统 Python 包。

主窗口通常以约 1180 × 820 的尺寸居中打开；在小屏幕或高缩放比例下，会按任务栏以上的可用空间自动缩小。分析窗口依次错开，窗口变小时仍可通过滚动条查看内容。

程序启动后不会自动打开分析工具。点击左侧的 **Match Workbook**、**Wafer Map**、**Correlation and Trend** 或 **Dynamic** 即可新建窗口。右侧 Activity 保留本次会话的窗口与文件事件，横跨主窗口底部的 Log 会记录 Python 运行环境、错误，以及 WKB 打开和保存位置，便于调试；上下区域可拖动调整，实际拖动后的 Log 高度会在正常关闭时保存并在下次启动恢复。Shell 不显示重复的全局 Close all、Ready、绿色状态点或空闲 `No tools open` 文本。Log 使用 Cascadia Mono、Consolas 等系统等宽字体，随 Light/Dark 主题切换背景，并以蓝色、琥珀色和红色区分 INFO、WARNING、ERROR 标签。

如果不使用 Conda，也可以在 Python 3.10+ 环境中安装依赖：

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Windows 便携版

历史便携版 `MetrologyWorkspace-Windows-x64-v1.2.0.zip` 解压后双击 `MetrologyWorkspace.exe` 即可运行，无需另装 Python；它不包含 v3.0.2 的功能和优化。本次 v3.0.2 发布为源码及 Git 标签，未生成新的 Windows 便携包。`_internal` 文件夹必须和 EXE 放在同一目录。设置保存在 EXE 旁边的 `settings.yaml` 中，下次启动时会自动读取。

重新构建便携版：

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean MetrologyWorkspace.spec
```

## 设置

从主窗口左上角菜单打开 **Settings…**。这里可以设置主题、分辨率、默认色阶、字体、插值平滑、Min R²、边缘填充、共享色阶、点值、色条、等值线和测点样式。**Recovery interval** 设置恢复草稿检查周期，默认 120 秒，可改为 30–1800 秒；Save 后更新所有已打开的文档，Cancel 不改变原设置。周期越长，异常退出时可能丢失的最近编辑越多。

点击 **Save** 后，源码版会把配置写入 `config/settings.yaml` 并立即生效。便携版仍保存到 EXE 旁边。**Load from YAML** 用于重新读取磁盘上的设置。浅色和深色主题都会同步应用到原生窗口标题栏。

## Data 工作区

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
- **Groups → Data selection…** 可按 Order、Reference、Raw Data 的所有列搜索、筛选和排序，整行点击切换 **Use**，Shift 点击批量设置可见区间。过滤是布尔矩阵：**Add row** 新建一行（每行是一个布尔组），行内条件用各自的 **AND / OR** 下拉连接、先算行内；行与行之间再用 **AND / OR** 连接，因此 `(A OR B) AND C` 这类组合都能表达（同一层内 AND 先于 OR 计算，与 SQL 一致）。每行末尾的 **+** 给该行加条件，条件的 **Edit / ×** 修改或删除，**Clear filters** 清空全部，矩阵随选择一起保存。**Check Visible / Uncheck Visible** 只改变可见记录的参与状态。**Apply** 后 selection 会保持：Raw Data 被整表替换或行数变化时，能对上的行按身份延续、其余按原位置延续，不会因为重新粘贴就把选择清空；只有 selection 用到的列（过滤列/身份列）不存在了，才会在提示栏提醒重新执行 Data selection。未勾选记录不参与 Workbook 分析及可追溯同源子工具绘图，但原始三表和 WKB 仍保留它们。搜索/列筛选本身只改变展示；**Cancel** 不提交勾选。独立导入的其他来源及 TEM 独立工具数据不按位置猜测匹配。旧文件保留已有分析筛选，首次应用 Data selection 时转换成显式参与勾选。
- **子窗口的数据来源**（Wafer Map / Radius、Correlation and Trend、Dynamic）：从 Workbook 打开时，菜单栏 **Data** 里有两个互斥选项——**Match Workbook selection**（默认）表示窗口里的表就是 selection 之后的数据；**Full data (before selection)** 表示重新复制 selection 之前的完整数据。切换会按当前 Workbook 数据重建该窗口的表（窗口已有独立修改时会先确认）。两种模式都可以再用 **Data selection…** 给本窗口追加自己的行选择，只影响本窗口的绘图/统计；右上角显示 `N ROWS / M COLUMNS · X ROWS USED`。
- **Mark** 是可选分类（原 Age）：新建 Workbook 默认不启用，关闭时只按 TestFlag / 测头分组，已有 Mark 名称和分配保留。启用后点 **Marks…** 管理：每个量测组最多一个 Mark，名称完全自由（不限于 POR 等固定值），双击改名、**Add Mark / Delete Mark** 随时增删。第一个 Mark 是兜底组，✓ 标出，未显式分配的量测组自动归入它；只保留两个 Mark 就能当二元分类（默认 Old / New），需要多元时继续添加。删除某个 Mark 后，原属它的量测组回到第一个 Mark。搜索框只筛选列表，**Assign Visible** 批量分配给搜索后可见的量测组；点击首行再按住 Shift 点击末行，可把首行的 Mark 应用到可见区间。改名会同步更新 Order 表的 Mark / Group 筛选值。旧 WKB 自动保留原 Old/New 行为；在 Group settings 点击 Apply 后，表格和图使用自定义名称。关闭 Mark 时忽略 Mark 列的筛选/排序，已选 Mark × 测头组的筛选合并到测头，重新启用后恢复。**Order 表没有任何 TestFlag 时，只要启用 Mark 就按 Mark 分组**（组名就是 Mark 名称，不带 TestFlag 说明）；TestFlag 和 Mark 都没有时不分任何组，Group plots 页也不出现。
- Wafers 列表上方显示当前身份字段，例如 `Wafer ID / Lot ID / PAD Name`。身份字段可以多选。
- Parameters 默认只显示可绘图的 numeric 列。取消 **Numeric** 后，可以查看和选择元数据列。
- X/Y、FIELD X/Y、X(mm)/Y(mm) 和 Die Seq 默认按元数据处理，不会自动作为测量参数。
- Wafer Map（主窗口工具及 Match Workbook 的 Preview、Final）把含数值的 MSE、GOF、NGOF、LBH、CINDEX 识别为 **NUMERIC**，可以手动勾选绘图，默认不勾选。fitTime、regIter 仍是元数据；Correlation/Trend 和 Dynamic 的建模参数排除规则不变。
- 只有手动保存才会写回 CSV。关闭窗口或替换表格前，程序会提示尚未保存的修改。

这个表格用于整理绘图数据，不支持 Excel 公式、合并单元格或完整的 Excel 格式。

## Match Workbook（v2 开发中）

该工具把日常的 Reference/Raw Data 匹配流程从手工 Excel 中独立出来。当前实现按以下顺序工作：

1. 先在 Reference 网格粘贴已经整理好的表。一个表可以同时包含多列参数，例如 `CD_Bot Reference`、`SPA Reference`。
2. 再在 Raw Data 网格粘贴原始数据。两个输入区与 Wafer Map / Correlation 的数据表操作一致：第 1 行是表头，可直接改单元格、区域粘贴，并用 `Ctrl+Z` 撤销。当前版本按从上到下的行顺序对应，两张表必须具有相同的行数。
3. 软件会把 `<参数名> Reference` 自动匹配到 Raw Data 中同名参数。像 `TEM`、`PMISH` 这样没有 `Reference` 后缀的数值列也会出现在映射表中，但不会擅自自动选择；可用 **Select all** 勾选全部候选项，再为它们选择对应的 Raw Data 参数。Wafer ID、Die Seq 等元数据不会列为参数。一次最多选择 50 个参数，最多处理 100,000 行。
4. 在顶部选择 **Preview** 或 **Final**。文件操作、KLA/NOVA/TEM Match Type、`Bias` / `Bias %` 和 Run analysis 都位于原生菜单栏；页面不再重复显示 Workbook 标题和设置面板。`Bias` 与 `Bias %` 各自独立开关：取消勾选会立刻移除对应的图，两个都不选时结果里只留 Match 与 Trend（工作簿内部仍保留主 Bias 模式）。

从主窗口启动 Match Workbook 时，先选择 **New Workbook**、**Open Workbook** 或最近文件。最近列表每行显示“文件名 + 保存时间（文件修改时间）+ 所在目录”，单击即打开。**Open Workbook** 与最近文件都直接按文件里保存的 Match Type、Bias、Trend Y axes、倍率和原来的 tab 打开，不再经过设置页，打开后保持已保存状态；只有 **New Workbook** 需要确认 Analysis 设置：默认 KLA、Bias、Auto 10×、Preview，且至少选择一个 Bias 视图。旧文件两个 Bias 视图都不选时也能直接打开，之后可在 Analysis 菜单补选。取消不会留下空窗口。File 的 **New Workbook…**（Ctrl+N）与 **Open Workbook…**（Ctrl+O）遵循同一规则。Final 缺少输入时进入等待补数据的页面。Analysis 设置在 Preview/Final 间共用。
5. 首次执行 **Run analysis** 后，Slope、Intercept、R²、Valid pairs 等结果直接显示在 Parameter mapping 的同一行。以后在 Raw Data 的 A1 粘贴新表或更改 Raw Data column 都会自动重新分析，不需要重复点击；Reference 与 Raw Data 都直接在网格中按 `Ctrl+V` 粘贴（只覆盖粘贴范围），`Ctrl+Shift+V` 才清空整表再粘贴；单元格编辑和 Delete 清空均可用 `Ctrl+Z` 撤销。Raw Data 暂时清空或缺少原参数列时，Reference 建立的映射仍会保留，界面会提示重新选择缺失的 Raw Data column。Slope 小于 0.9 或大于 1.1、R² 小于 0.9 时，值会以红色警示并说明阈值。Parameter mapping 里的 **Raw Data column** 下拉框不吃鼠标滚轮：滚轮只滚动页面，不会误改映射（其他下拉框仍是标准行为）。
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
- KLA/NOVA 的 Single-wafer tab 使用 Raw Data 的 Wafer ID、Lot ID 和 PAD Name，并沿用 Wafer Map 的默认身份规则；只有真正变化的 Lot/PAD 才参与分组，Die Seq 不单独拆组。多个身份字段分行显示，避免横轴文字重叠。TEM 同样支持 Head/Mark 分组和 Data selection（Group settings、Order 表都可用），但结果区不显示 **Single-wafer metrics** 与 **Group plots** 两个 tab。
- Match 始终显示线性拟合，不再提供重复的开关；图名使用映射的 Raw Data column，横轴是 PMISH、纵轴是当前 Match Type。参数名与两行拟合公式/R² 使用绘图区上方的独立标题栏，公式位于参数名右侧且不会覆盖曲线或数据点。Match、Trend、Bias 和单片指标图统一显示完整四边坐标轴，并与 Correlation and Trend 一样支持 Ctrl+滚轮缩放、左键拖框放大、右键平移和双击自动适配；不按 Ctrl 的滚轮会继续滚动外层页面。Trend 中 PMISH 使用蓝色实线圆点，当前 Match Type 使用橙色实线圆点，且不重复显示无意义的纵轴名。Bias 使用蓝色点线并按原始数值显示 `Bias (nm)` 和 `Bias (%)`，禁用自动 SI 缩放，不再出现 ×0.001 或百分比系数。分析层仍按需生成每个参数的派生数据，界面只保留经过极值采样的绘图数组，不复制 50 份完整结果表。

**Save Workbook** 保存 Reference、Preview/Final 独立 Raw Data、参数映射、Bias 显示选择、分析设置、分隔栏布局、参数顺序，以及三个分析工具中实际显示和编辑的数据及配置。各阶段勾选的 wafer、parameter 和已确认的绘图选择也一起写入 `.wkb`，无需逐个子工具另存。KLA/NOVA 在尚无 Map 快照时由相应 Raw Data 初始化；TEM 需输入独立 Map 数据。已保存的 Preview/Final 分别恢复，不互相覆盖。

父窗口 **Save Workbook As…**（`Ctrl+Shift+S`）另存整本工作簿，新路径成为后续保存目标。子窗口保存、独立副本与关闭提示的范围见下方“统一文档保存与恢复”。**Open Recent WKB** 保留最近成功打开或保存的工作簿，**Reveal Workbook in Folder** 定位当前文件。旧 WKB 缺少独立 Final、Map、Dynamic 或选择状态时仍可读取。文件内含数据，不依赖原 Excel/CSV，也不执行 pickle。

**Export Excel** 是确认结果后的可选输出，包含 Summary、Reference、Raw Data、Preview/Final 结果，以及存在时的 Map/FullMap 工作表。**Save images** 将当前显示的各参数图分别保存为 PNG。

存储模块基准：10 万行 × 50 个四位小数文本参数加两列标识，保存约 0.96 秒、载入约 1.58 秒、文件约 43.54 MiB，逐项往返一致（2026-10-03 当前开发机一次实测，不代表全部硬件，不包含 GUI 出图，也不是旧格式对比结论）。可用 `python -m benchmarks.benchmark_workspace_store` 复测。Card 计算可单独用 `python benchmarks/benchmark_matching.py` 测量。

Wafer Map 或 Radius Plot 成功绘制并保存过后，WKB 会分别保存“自动绘制已启用”和实际框选组合。保存子窗口再打开、或重新加载 WKB，都会恢复仍存在的组合并直接出图，不必再次点击 **Draw selected**；尚未确认 Draw 的新框选仍等待点击，不自动绘制。旧 schema 1–10 仍可读取。

### 统一文档保存与恢复

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

每张图显示插值曲面、原始测点、点值、坐标轴和 Min/Max/Mean，不在阵列底部重复显示 RBF、边缘扩展或晶圆尺寸说明。默认色阶为 Turbo，也可以选择 Viridis、Plasma、Jet、Coolwarm 或 Spectral。**Colors** 两端的手柄用于裁剪调色板范围；拖动时只更新颜色，不重新计算 RBF。**Opacity** 只改变填色透明度，等值线和测点保持实心。

**Point values**、**Measurement points**、**Contour lines**、**Point outline** 和 **Scale bar** 可以单独开关。程序会复用已有插值结果，因此切换这些显示项不会改变当前缩放或滚动位置。在 18 张图的测试数据上，叠加层更新约为 0.05 秒；原来的完整重绘约为 1.2 秒。

每张图默认使用独立色阶。需要比较不同测量条目的绝对数值时，打开 **Shared scale / parameter**，让同一参数共用色阶。

**Diameter** 设为 Auto 时，X(mm)/Y(mm) 坐标会识别 100、200 或 300 mm 标准晶圆。300 mm 晶圆的坐标范围固定为 -150 到 150 mm。其他坐标类型按数据范围估算，也可以手动输入直径。

**Fill edge** 用外侧测点的径向镜像样本估计凸包之外的区域。该区域不是实测数据。关闭后，凸包外保持空白；开启后，结果仍限制在实测 Min/Max 范围内。

**View** 支持适宽和 50% 到 300% 缩放。普通滚轮纵向滚动，Shift+滚轮横向滚动，Ctrl+滚轮按指针位置缩放。**Resolution** 提供 Standard、High 和 Ultra，分别对应 200、300 和 400 dpi 的 PNG 输出。图像过大时，复制和导出会自动降低 DPI，避免耗尽剪贴板或内存。

**Export…** 支持 PNG、SVG 和 PDF。SVG/PDF 中的坐标轴、标题、等值线、测点和 colorbar 刻度保持矢量；插值色面作为图像层嵌入。**Copy PNG** 会复制整个阵列，包括当前滚动区域之外的内容。

同一测量条目中，只要坐标一致，多个参数会共用一次 RBF 矩阵求解。显示网格按图数自动调整：不超过 12 张时使用 400 × 400，不超过 48 张时使用 300 × 300，更大的阵列使用 200 × 200。插值平滑可以在 Settings 中选择 Off、Light、Medium 或 Strong。

## Radius Plot

Radius Plot 使用 Data 中当前勾选的测量条目和参数，但保留自己独立的方框选择；首次绘制后，Data 更新会直接按上次组合刷新，不再要求重复选择。横轴按下式计算：

`signed R = sign(X) × sqrt(X² + Y²)`

X < 0 位于负半轴，X > 0 位于正半轴，X = 0 时半径为 0。每个“测量条目 × 参数”单独绘制，不会把多组数据叠在一张图上。标准毫米坐标沿用 100/200/300 mm 晶圆识别，缩放、字体、分辨率和 PNG 输出规则与 Wafer Maps 一致。

## Correlation and Trend

该工具用 **Ref Data** 与 **Raw Data** 两个独立页保留来源表；Raw Data 始终显示全部原始列，Reference 的 Wafer ID、Lot ID、PAD Name 与 Die Seq 按行取自 Raw Data。两个页面支持同样的导入、粘贴和编辑操作。新表格会默认选中所有测量条目，并勾选可用的建模参数列。MSE、GOF、NGOF、LBH、fitTime、regIter（包括 `reglter` 拼写）、CINDEX、Seq、Logical ID，以及 `Cur SME File Path`、Wafer ID、Lot ID、Tool SN、PAD Name、Die Seq、FIELD X/Y、X(mm)/Y(mm) 都不是建模的物理参数，不会出现在参数列表里。名称匹配忽略大小写、空格、下划线和连字符。双来源模式下，Correlation 先列完 Reference 的来源内拟合，再列 Raw Data；Trend 也按 Reference 后 Raw Data 排列，并以橙色/蓝色区分来源。

### Correlation

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
- 每批最多处理 120 个阵列位置。

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
