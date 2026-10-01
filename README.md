# Metrology Workspace

Metrology Workspace 是一套 Python 3.10+ / PyQt6 桌面工具，用于整理量测数据、完成 Card 匹配、Dynamic 重复性分析，并绘制 Wafer Map、径向图、相关性图和 Die Seq 趋势图。主窗口依次提供 **Match Workbook**、**Wafer Map**、**Correlation and Trend** 和 **Dynamic** 四个工具。每次打开都会创建一个独立窗口，同一工具可以同时开多个实例。v2 在 `main` 分支持续开发，本轮开发快照为 `v2.0.0-dev.4`；已发布且保留的稳定版本是 `v1.2.0`。

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

解压 `MetrologyWorkspace-Windows-x64-v1.2.0.zip`，双击 `MetrologyWorkspace.exe` 即可运行，无需另装 Python。`_internal` 文件夹必须和 EXE 放在同一目录。设置保存在 EXE 旁边的 `settings.yaml` 中，下次启动时会自动读取。

重新构建便携版：

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean MetrologyWorkspace.spec
```

## 设置

从主窗口左上角菜单打开 **Settings…**。这里可以设置主题、分辨率、默认色阶、字体、插值平滑、Min R²、边缘填充、共享色阶、点值、色条、等值线和测点样式。

点击 **Save** 后，源码版会把配置写入 `config/settings.yaml` 并立即生效。便携版仍保存到 EXE 旁边。**Load from YAML** 用于重新读取磁盘上的设置。浅色和深色主题都会同步应用到原生窗口标题栏。

## Data 工作区

- 左侧表格支持单元格编辑、区域复制和粘贴、清空、撤销及重做。第一行始终作为字段名。
- 可以导入 CSV 和 XLSX。Excel 文件包含多个工作表时，可选择要读取的工作表。`001` 这类文本 ID 和原始数值字符串会保留。
- 在 A1 使用 **Ctrl+V** 粘贴带表头的整张表时，程序会替换当前工作区并重新识别字段；在其他位置粘贴时，只覆盖选中的区域。**Paste table**（Ctrl+Shift+V）始终替换整张表。
- 如果第一行有重复列名，**Auto rename** 会按列顺序添加 `_2`、`_3` 等后缀。该操作只修改表头，也可以用 Ctrl+Z 撤销。
- Wafers 列表上方显示当前身份字段，例如 `Wafer ID / Lot ID / PAD Name`。身份字段可以多选。
- Parameters 默认只显示可绘图的 numeric 列。取消 **Numeric** 后，可以查看和选择元数据列。
- X/Y、FIELD X/Y、X(mm)/Y(mm) 和 Die Seq 默认按元数据处理，不会自动作为测量参数。
- 只有手动保存才会写回 CSV。关闭窗口或替换表格前，程序会提示尚未保存的修改。

这个表格用于整理绘图数据，不支持 Excel 公式、合并单元格或完整的 Excel 格式。

## Match Workbook（v2 开发中）

该工具把日常的 Reference/Raw Data 匹配流程从手工 Excel 中独立出来。当前实现按以下顺序工作：

1. 先在 Reference 网格粘贴已经整理好的表。一个表可以同时包含多列参数，例如 `CD_Bot Reference`、`SPA Reference`。
2. 再在 Raw Data 网格粘贴原始数据。两个输入区与 Wafer Map / Correlation 的数据表操作一致：第 1 行是表头，可直接改单元格、区域粘贴，并用 `Ctrl+Z` 撤销。当前版本按从上到下的行顺序对应，两张表必须具有相同的行数。
3. 软件会把 `<参数名> Reference` 自动匹配到 Raw Data 中同名参数。像 `TEM`、`PMISH` 这样没有 `Reference` 后缀的数值列也会出现在映射表中，但不会擅自自动选择；可用 **Select all** 勾选全部候选项，再为它们选择对应的 Raw Data 参数。Wafer ID、Die Seq 等元数据不会列为参数。一次最多选择 50 个参数，最多处理 100,000 行。
4. 在顶部选择 **Preview** 或 **Final**。文件操作、KLA/NOVA/TEM Match Type、`Bias` / `Bias %` 和 Run analysis 都位于原生菜单栏；页面不再重复显示 Workbook 标题和设置面板。`Bias` 与 `Bias %` 至少选择一个，也可以同时选择。
5. 首次执行 **Run analysis** 后，Slope、Intercept、R²、Valid pairs 等结果直接显示在 Parameter mapping 的同一行。以后在 Raw Data 的 A1 粘贴新表或更改 Raw Data column 都会自动重新分析，不需要重复点击；Reference 与 Raw Data 都直接在网格中按 `Ctrl+V` 粘贴，整表替换、单元格编辑和 Delete 清空均可用 `Ctrl+Z` 撤销。Raw Data 暂时清空或缺少原参数列时，Reference 建立的映射仍会保留，界面会提示重新选择缺失的 Raw Data column。Slope 小于 0.9 或大于 1.1、R² 小于 0.9 时，值会以红色警示并说明阈值。
6. 结果区分为 **All parameter plots** 和 **Single-wafer metrics** 两个 tab。全部参数按纵向卡片显示，只有一个参数时也从结果区顶部开始；Match、Trend、Bias、Bias % 按当前选择排在同一横行。Match 固定为 510 × 330 px，Trend、Bias 和 Bias % 统一为 330 px 高并平分剩余宽度；四图同时显示时也会收进可见工作区，不需要横向滚动且不会互相重叠。绘图区上下对齐、四边同粗，Trend/Bias 不再重复显示 Wafer 轴标题。Trend 右上角的 **Card** 可在原始 PMISH 与加 Card 后的 PMISH 间切换。拖动参数卡标题时会显示半透明预览和淡入的插入位置；当前顺序会直接保留，不再占用空间显示 Reset。输入、映射和结果区之间的分隔线可以拖动；首次运行成功后，修改 Reference、当前模式的 Raw Data 或 Parameter mapping 会自动原位刷新，并保持分隔栏、滚动位置和参数顺序。Preview 与 Final 各自保留独立 Raw Data，切换模式不会清空另一侧数据或已有结果。当前模式对应的 **Open Preview/Final Wafer Map / Radius** 与 **Open Preview/Final Dynamic** 位于顶部右侧。

顶部右侧还提供 **Open Correlation and Trend**：它直接读取当前模式的 Reference 与 Raw Data，分别显示在两个数据页。Raw Data 保留全部原始列；Ref Data 用 parameter mapping 的参数名显示量测值，并把 Wafer ID、Lot ID、PAD Name 与 Die Seq 按行对齐 Raw Data。Correlation 只在 Reference 内部或 Raw Data 内部拟合，不做跨来源 correlation；所有 Reference 图先显示并使用橙色，随后是蓝色 Raw Data 图。Trend 使用相同的来源顺序与配色。

Card 的定义为：

`Reference = slope × Raw + intercept`

- **Preview** 会把新生成的 slope/intercept 应用到当前 Raw Data，得到 Card Value，再用它绘制 Trend、Bias、Wafer Map 和 Radius Plot。
- **Final** 使用自己的 Raw Data，假定这些值已经由 OCD 软件应用 Card，不会复用 Preview Raw Data，也不会重复加 Card；Trend、Bias、Wafer Map 和 Radius Plot 都直接使用 Final 输入值。
- `Bias` 是 `Evaluated Value - Reference`；`Bias %` 是 `(Evaluated Value - Reference) / Reference × 100%`。两者可以同时显示，Reference 为 0 时百分比留空，不猜测替代值。
- KLA/NOVA 的 Single-wafer tab 使用 Raw Data 的 Wafer ID、Lot ID 和 PAD Name，并沿用 Wafer Map 的默认身份规则；只有真正变化的 Lot/PAD 才参与分组，Die Seq 不单独拆组。多个身份字段分行显示，避免横轴文字重叠。TEM 不显示该组单片结果。
- Match 始终显示线性拟合，不再提供重复的开关；图名使用映射的 Raw Data column，横轴是 PMISH、纵轴是当前 Match Type。参数名与两行拟合公式/R² 使用绘图区上方的独立标题栏，公式位于参数名右侧且不会覆盖曲线或数据点。Match、Trend、Bias 和单片指标图统一显示完整四边坐标轴，并与 Correlation and Trend 一样支持 Ctrl+滚轮缩放、左键拖框放大、右键平移和双击自动适配；不按 Ctrl 的滚轮会继续滚动外层页面。Trend 中 PMISH 使用蓝色实线圆点，当前 Match Type 使用橙色实线圆点，且不重复显示无意义的纵轴名。Bias 使用蓝色点线并按原始数值显示 `Bias (nm)` 和 `Bias (%)`，禁用自动 SI 缩放，不再出现 ×0.001 或百分比系数。分析层仍按需生成每个参数的派生数据，界面只保留经过极值采样的绘图数组，不复制 50 份完整结果表。

**Save WKB** 保存 Reference、Preview/Final 独立 Raw Data、参数映射、Bias 显示选择、分析设置、分隔栏布局、参数顺序，以及 Preview/Final 的 Map 与 Dynamic 工作区中实际显示和编辑的表；这些数据不需要再单独保存。四个工作区各自右侧勾选的 wafer 与 parameter 也写入 WKB，关闭整个软件并重新打开文件后仍会恢复。KLA/NOVA 在尚无 Map 快照或独立 FullMap 时由相应 Raw Data 初始化；TEM 不会把匹配 Raw Data 自动填进 Map，需输入独立 Map 数据。Map 或 Dynamic 一旦在工作区中打开或修改，保存 WKB 后会按对应 Preview/Final 原表恢复，不会在重开时互相覆盖。同一次 Match Workbook 会话中关闭再打开 Map 或 Dynamic 时，也会恢复该模式上次勾选且仍存在的 wafer 与参数，并立即刷新分析。从 Match Workbook 打开的 Map/Dynamic 由父工作簿托管，关闭时不弹出丢弃编辑确认；当前已有 WKB 路径时会立即覆盖保存，没有路径时先保留在父窗口中并在首次 Save WKB 时写入。独立打开的工具仍保留未保存确认。第一次保存会选择路径，保存或打开以后按 `Ctrl+S` 会直接覆盖当前 WKB。**Save WKB As…**（`Ctrl+Shift+S`）用于另存为，新路径会成为后续保存目标。File 菜单的 **Open Recent WKB** 按最新优先保存最多 10 个成功打开或保存的工作簿，可在软件重启后直接重开；**Reveal WKB in Folder** 会在系统文件管理器中定位当前 WKB，没有当前文件时保持禁用。旧 WKB 没有独立 Final 匹配表、Map、Dynamic 快照或工作区选择状态时继续兼容。WKB 是 SQLite-backed 的主工作文件，可以在多个独立窗口中重新打开比较；它不依赖 Excel，也不会执行不安全的 pickle。**Export Excel** 是确认结果后的可选输出，包含 Summary、Reference、Raw Data、Preview/Final 结果，以及存在时的 Map/FullMap 工作表。**Save images** 会把当前选择显示的每个参数图分别保存为 PNG。

10 万行、50 参数的随机浮点基准中，50 个 Card 的计算约 0.16 秒，单个参数结果展开约 0.004 秒；WKB 保存约 1.05 秒、载入约 2.43 秒，文件约 97.9 MB。结果取自当前开发机的一次可重复测量，不代表所有磁盘和数据分布。 可用 python benchmarks/benchmark_matching.py 复测。

Wafer Map 或 Radius Plot 成功绘制过后，WKB schema 8 会分别保存“自动绘制已启用”和实际框选组合。关闭子窗口再打开、或彻底关闭并重新加载 WKB，都会恢复仍存在的组合并直接出图，不必再次点击 **Draw selected**；旧 schema 1–7 仍可读取，并保留缺少相应状态时首次手动绘制的兼容行为。

当前 v2 已把 Preview/Final 作为顶部模式页，并将各自的 Raw Data 交给现有 Wafer Map 和 Radius Plot；独立 FullMap 输入页已移除。尚未实现的是按 Wafer ID、Slot ID、PAD Name 和坐标自动整理尚未对齐的 Reference；当前匹配数据仍按行序对应。

## Dynamic

Dynamic 用于同一 wafer 上若干 Die 的重复测试。导入数据后，软件优先从 `Cur SME File Path` 中的 `DYNAMIC/<run>` 识别每轮测试；如果路径没有该结构，则在有序 Die Seq 首次重复时开始下一 Cycle。Die 数量和 Cycle 数量均不固定。旧 Excel 透视表若位于第一个空白列之后，会在导入时排除，避免把报表列误当成新参数。

第一个 tab 复用 Data 编辑器与 Wafer Map 的 Wafer ID / Lot ID / PAD Name measurement identity，可勾选 DP、EW、TG 等数值参数。粘贴或打开替换表格时，会按列名保留新表中仍存在的参数选择并直接重算，无需重新勾选；Wafer Map 使用相同规则。第二个 tab 要求选择一个 measurement set，并分成上下两个独立滚动区域：上方按勾选顺序纵向显示每个参数自己的 Cycle × Die Seq 透视表；下方先用不同颜色在一张图中比较全部已选参数，再分别显示每个参数的 3σ 图。合并图不重复显示参数拼接标题，原标题行改为带小色块的横向 legend。每张表底部的 `3 Sigma` 使用跨 Cycle 的样本标准差 `3 × std(ddof=1)`；柱图以 Die Seq 为横轴、3 Sigma 为纵轴并固定为 420 × 270 px，只显示柱形、不叠加数据点，每行最多三张，超过三张自动换到下一行。页面不再提供参数下拉框或重复的 Dynamic 标题。相同 Cycle/Die Seq 出现多行时会直接报告歧义，不会静默取平均。

## Wafer Map

基本流程如下：

1. 在 Data 中勾选测量条目和参数。
2. 切换到 **Wafer Maps**，确认 X、Y 坐标列。
3. 在方框阵列中拖动选择要绘制的组合。Ctrl 用于增减选择，Shift 用于扩选，**All** 和 **None** 可以全选或清空。
4. 点击 **Draw selected**。只有选中的组合会参与计算，画布也只保留实际用到的行和列。

Wafer Maps 成功绘制一次后会记住实际绘制的方框。此后直接粘贴、打开或编辑 Data 时，只要对应参数仍存在，就会用新数据自动重绘并继续显示图，不再跳回方框选择页；如果 wafer 身份全部变化，则把上次绘制的参数应用到新的 wafer。需要修改组合时仍可点击 **Select maps**，但改选方框后会自动重绘，不必再次点击 **Draw selected**。Radius Plot 独立记忆自己的上次方框，并采用同样的自动刷新规则。

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

该工具用 **Ref Data** 与 **Raw Data** 两个独立页保留来源表；Raw Data 始终显示全部原始列，Reference 的 Wafer ID、Lot ID、PAD Name 与 Die Seq 按行取自 Raw Data。两个页面支持同样的导入、粘贴和编辑操作。新表格会默认选中所有测量条目，并勾选可用的 numeric 列；MSE、GOF、NGOF、LBH、regIter（包括 `reglter` 拼写）和 CINDEX 默认排除。名称匹配忽略大小写、空格、下划线和连字符。双来源模式下，Correlation 先列完 Reference 的来源内拟合，再列 Raw Data；Trend 也按 Reference 后 Raw Data 排列，并以橙色/蓝色区分来源。

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

默认仍是一个参数一张图。偶尔需要比较两个趋势时，可在面板上右键选择 **叠加对比…**；同单位共用左轴，不同或无法识别的单位自动增加着色右轴，Reference/Raw Data 分别使用实线/虚线。标题区的 **解除对比** 可恢复分面板。对比关系写入应用设置并在下次 Draw selected 时按仍存在的勾选恢复，不写入 WKB，也不改变 schema 8。

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

在项目目录运行：

```powershell
conda run -n metrology-workspace python -m unittest discover -s tests -v
```

测试覆盖数据识别、编辑操作、插值、绘图、导出、窗口行为、Correlation/Trend 交互以及 Card Matching/WKB 工作流。开发过程中生成的截图和临时视觉检查文件不纳入项目。

当前开发状态和 Skill 使用约定见 [docs/HANDOFF.md](docs/HANDOFF.md)。
