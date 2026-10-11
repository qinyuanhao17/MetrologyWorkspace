# Excel 导出方案：数据 + 图片（A）与数据 + Excel 原生图表（B）

状态：**方案，未实施**。本文只定义导出形态、数据契约、sheet 映射、图表绑定与验收，
不改动拟合、插值、色标、参与范围或 WKB。

## 1. 现状与样例核实

现有 `Export Excel`（`metrology_app/matching_window.py::export_excel`）只写数据表：
`Summary`、`Reference`、`Raw Data`、`Preview/Final`、`Order`、`Group Fits`、
`AllTrend`/各 Group trend、`Preview/Final FullMap`，没有任何图。

两个样例工作簿的形态已逐 sheet 核实（openpyxl 读取图表绑定与公式）：

| 样例 | sheets | 图与数据形态 |
| --- | --- | --- |
| 样例一（TEM 形态） | `FM`、`Match`、`Dynamic`、`Dynamic RM4`、`Radius Plot`、`Map`（+空 `Sheet1`/`Sheet2`） | `FM`：源表 A:AL + 公式镜像的数值区 AS:AZ + 7 张折线 + 11 张嵌入 PNG；`Match`：源表 + 每个参数一块 14 行区块（表1/表2/参数/PMISH/REF/Bias），每块配 Match 散点 + Trend 折线 + Bias 折线；`Dynamic`：源表 + 透视块 AR:BB，配折线（MSE、标准差）与 `3-SIGMA` 柱状；`Radius Plot`：`Die Seq/X/Y/R` + 公式引用 `FM!` 的参数列，配散点；`Map`：只有 5 张图片 |
| 样例二（NOVA/KLA 形态） | `RSQ`、`Match_All`、`Match_MM1`、`Match_MM2`、`Match_Unkown`、`NEW_Match_all`、`New_Match_MM1`、`New_Match_MM2`、`Order`、`All_Trend`（+空 `Sheet1`） | `Match_All`：A:H 为 Reference 列、K `CINDEX`、M `TestFlag`、O:U 为身份列、AA:AU 为计算结果列；散点 `yVal=AC`（REF）、`xVal=AD`（PMISH/测量）；**每个 Group 一张 sheet**（`Match_MM1/MM2/Unkown`、`New_*`）各自散点；`RSQ`：wafer × 参数的 R² 网格 + 跨 wafer 折线；`Order`：`Wafer ID…Type/参数` 的 Order 表；`All_Trend`：按 Group 的 `PMISH/NOVA/Bias` 列 + 折线 |

样例里用 Excel 自带算法算 Card（`Match!D20 =SLOPE($E$20:$E$32,$C$20:$C$32)*表2`）
——**这条不沿用**，见第 3 节第 3 条。

## 2. 两种方案

| 项目 | A：Excel 数据＋Matplotlib 图 | B：Excel 数据＋Excel 原生图 |
| --- | --- | --- |
| 数据 | 原始表、参与绘图的数据、计算结果（两方案完全同一套） | 同 A |
| Match／Trend／Bias／Radius | Matplotlib 生成图片并嵌入（按报告尺寸重画，不截软件窗口） | 原生图表，系列引用单元格，可在 Excel 改系列/颜色/坐标轴/尺寸 |
| Correlation/Trend（FM） | Matplotlib 图片 | 原生图表（当前窗口的图型，散点或折线） |
| Dynamic | Matplotlib 图片（含 3-SIGMA） | 折线 + `3-SIGMA` 柱状原生图表 |
| Wafer Map | Matplotlib 图片 | 同样嵌入 Matplotlib 图片（与样例一致） |
| 后续编辑 | 可改表格；图片需重新导出 | 表格与图表都能改；Card/R² 为导出时软件值（见 3.3） |
| 运行条件 | 不需要 Excel，纯 Python 绘制 | 见 7.4：B1 直接写 xlsx 图表（不需要 Excel）；B2 调用 Windows 桌面 Excel 渲染/套模板 |
| 额外产物 | 可另存 PNG/PDF/SVG（同一次绘制 `savefig`） | 只有 xlsx |
| 适用 | 固定报告、截图、分享 | 需要下游在 Excel 里继续调图 |

两种方案共用同一份"导出数据模型"，B 只是换渲染器；A 与 B 的单元格数值必须逐值一致。

## 3. 共同规则（可执行约束）

1. **Reference 列名与身份列**：Reference 一律保留原始列名；身份信息（`Cur SME File Path`、
   `Wafer ID`、`Lot ID`、`Tool SN`、`PAD Name`、`Die Seq`、`FIELD X/Y`…）读取同一源行的
   **Raw Data**，不借用 Parameter mapping 名称；`Parameter` 名只出现在参数信息块与图标题。
2. **子窗口各自导出**：`Correlation/Trend`、`Dynamic`、`Wafer Map`、`Radius` 各自按自身数据、
   筛选与参数导出；父窗口的 mapping / 阶段不得覆盖子窗口（与样例二"每个 Group 一张 sheet"
   同理，作用域写进 sheet 名与参数信息块）。
3. **拟合与统计以软件为准**：Card 的 `slope`/`intercept`、R²、有效点数、Bias 超限计数、单位
   全部写软件当前值。数值绘图区的 PMISH 用 `=slope_cell*raw_cell+intercept_cell` 应用软件
   Card（**应用**系数，不是重新拟合）；禁止写 `SLOPE()`/`LINEST()`/`RSQ()`/Excel 趋势线。
   Excel 改动 raw 只更新 PMISH/Bias，Card 与 R² 保持导出时的软件值并在参数块注明。
4. **原始字符串与行身份**：源表保留原始测量字符串（文本，不转数值、不四舍五入）；
   数值绘图区独立另起区块（样例的 `FM!AS:AZ`、`Radius Plot!A:I` 就是这种"另设数值区"）。
   Excel 内的一切编辑不回写 WKB。
5. **显示设置跟随界面**：`PAD:`/`LOT:` 图注开关（`match_ui.plot_labels`）、Show wafer、
   Group 名称与顺序、`Expand Wafers` 状态都按当前工作簿设置导出，导出不改变这些设置。
6. **Wafer 标签与展开**：每个 Wafer/Lot/PAD 身份占一段连续 X；按标签实际所需宽度给空间，
   wafer 多时**分段**（同 sheet 多区块或按 `…_2`/`…_3` 续页），不按总点数把单图无限拉长。
7. **只借样式，不借范围**：样例中个别图表引用范围与数据范围差一行；导出时每个系列都从同一份
   数值绘图区重新生成，并逐一核对起止行、类别列与行数（空值留空，不补 0）。
8. **可回读**：导出文件里同时给出"源表 + 数值绘图区 + 计算结果"，使图表可追溯到单元格
   （样例的可编辑性来自这一点，也是 A 方案图表的"无障碍数据表"）。

## 4. 公共骨架（每张数据 sheet）

| 区块 | 位置 | 内容 |
| --- | --- | --- |
| 源表 | A1 起 | 身份列 + 原始测量列（文本）+ `TestFlag`/`Head`/`Mark`/`Group`（如启用） |
| 数值绘图区 | 源表右侧留一空列后 | `X`（序号或 Die Seq）、`PMISH`、`REF`、`Bias`、`Bias %`、`Card Value`…（公式引用源表） |
| 参数信息块 | 数值区右侧或图上方 | `Parameter` / `Reference column` / `Raw column` / `slope` / `intercept` / `R²` / `Valid pairs` / `Bias limit` / 单位 / Card 来源（Overall 或 Group）/ 阶段（Preview/Final）/ 行数 |
| 图区 | 数据右侧 | A：图片锚定在首列，按行排，每图一行图注（参数、Group、阶段、行数、Card 来源）；B：原生图表锚定在数值区右侧 |

图注与参数块是两种方案的公共部分；Wafer Map/Radius 的图片区沿用样例的"图片右侧一列说明"。

## 5. 各类型 sheet 映射

### 5.1 TEM

| sheet | 内容 | A 方案图 | B 方案图 |
| --- | --- | --- | --- |
| `Match` | 源表 + 每参数一块：`序号 / 原始值 / PMISH / REF / Bias`（样例一 `Match!A19:F32` 形态） | 每块 Match 散点（+拟合线）、Trend 折线（PMISH、REF）、Bias 折线 | `ScatterChart`（x=PMISH/原始值，y=REF）+ `LineChart`×2 |
| `FM` | 源表 + 公式镜像数值区（样例一 `FM!AS1:AZ84` 形态） | 每参数一张 Correlation/Trend 折线（子窗口 Trend） | `LineChart`，每参数一条系列（或一图一参数） |
| `Dynamic` | 源表 + 透视块（样例一 `Dynamic!AR:BB` 形态） | 每参数折线 + `3-SIGMA` 柱状 | `LineChart` + `BarChart` |
| `Map` | 仅图片 + 参数/身份说明 | 各 wafer 的 Matplotlib wafer map | 同 A（嵌入图片） |
| `Radius`（可选，样例一有 `Radius Plot`） | `Die Seq/X/Y/R` + 参数列（公式引用） | 每参数 R-参数散点 | `ScatterChart`（x=R，y=参数） |

### 5.2 NOVA / KLA

在 TEM 的基础上追加 Group 维度（样例二的形态）：

| sheet | 内容 |
| --- | --- |
| `Match_All` | 全部参与行；Reference 列 + `TestFlag` + 身份列 + 计算结果列；所有参数的 Match 散点与 Trend |
| `Match_<Group>` | **每个 Group 一张**（`Match_MM1`、`Match_MM2`、`Match_Unkown`、`New_*`…）；只含该 Group 的行、该 Group 的 Card、Group 级 R²/Bias |
| `All_Trend` | 按 Group 的 `PMISH/NOVA(REF)/Bias` 列 + 折线（Group 用系列或分段） |
| `RSQ` | wafer × 参数 R² 网格（第一行 wafer、最后一列参数名）+ 跨 wafer 折线 |
| `Order` | 沿用样例的 `Wafer ID/Lot ID/Tool SN/PAD Name/Die Seq/Relative Column/Relative Row/Time/Type/参数列`，另附 `TestFlag/Head/Mark/Group` 对照列，作为 sheet↔Group 的索引 |
| `Dynamic` / `Map` / `Radius` | 同 TEM（各子窗口按自身数据导出） |

sheet 命名规则：`Match_` + 归一化的 Group 名（去掉方括号、冒号、星号、问号、斜杠和反斜杠，
≤31 字符、重名或超长加 `_2`）；
Group 的稳定 id 与显示名同时写入 `Order`，用户改名后导出仍能找到对应关系。

## 6. 方案 A：Matplotlib 导出

- 用与界面同源的绘图函数重画（不是截图窗口），数值/单位/采样/色标与界面一致；
  显示采样（`PLOT_LIMIT` 的 `display n/m`）图注照写，不隐藏。
- 尺寸按最终报告尺寸（默认 6.4×4.8 in，150–200 dpi）；Wafer Map/Radius 用方格布局。
- 嵌入用 `openpyxl.drawing.image.Image`（或 artifact tool 的图片 API），锚定在数据右侧，
  逐个写入图注行；同一批图可选另存 PNG/PDF/SVG。
- 运行条件：不需要 Excel；matplotlib 已在运行依赖内。

## 7. 方案 B：Excel 原生图表

### 7.1 图表类型与绑定

| 图 | 类型 | 绑定 |
| --- | --- | --- |
| Match | `ScatterChart` | `xVal`=数值绘图区 PMISH/原始值列，`yVal`=REF 列，`name`=参数名 |
| Trend | `LineChart` | 系列=PMISH、REF（或按 Group 一系列），类别=序号/身份列 |
| Bias / Bias % | `LineChart` | 系列=Bias、Bias %；0 线用参考线或空白列实现 |
| Correlation/Trend（FM） | `ScatterChart` 或 `LineChart` | 按子窗口当前图型，绑定其自身数值区 |
| Dynamic | `LineChart` + `BarChart` | 折线=各参数；柱状=3-SIGMA 统计块 |
| Radius | `ScatterChart` | `xVal`=R 列，`yVal`=参数列 |
| Wafer Map | 嵌入图片 | 同方案 A |

### 7.2 样式模板

提炼一个统一模板并复用：字体=界面字体、颜色 `#5b9bd5`/`#ed7d31`/`#4f8bd6`/`#e09f3e`、
线宽/标记/网格/图例位置固定；每个图表先套模板再按需要覆盖。轴数字格式显式设置，
单位写进标题或轴标题，不假设源格式自动带过去。空值保持空白。

### 7.3 结构核对（来自 Spreadsheets 技能的原生图表规则）

- 系列直接绑定源单元格；`val`/`xVal`/`cat` 三者行数一致，避免"类别变系列""点消失"。
- 创建后逐图核对：图表数量、系列数、起止行、标题、轴格式、空白处理；导出的颜色与线型
  以导出文件里的图表属性为准，不以作者预览为准。
- R²/Card 为软件静态值；Excel 里继续编辑只影响公式链（PMISH/Bias），参数块注明这一点。

### 7.4 生成方式（二选一，待确认）

- **B1（推荐，默认）**：直接写 xlsx 原生图表（openpyxl/artifact tool），**不需要启动 Excel**；
  覆盖散点/折线/柱状与常用轴格式；`Chart.applyChartTemplate`（.crtx）等 Excel 专属特性不支持。
- **B2（可选）**：软件调用 Windows 桌面 Excel（COM）创建图表并套用 `.crtx` 模板后另存；
  样式最接近 Excel，但要求安装桌面 Excel、需处理弹窗/占用/超时。

两者产出的数据与引用结构相同，B2 只是渲染器；先做 B1，B2 由你确认后再加。

### 7.5 直写 xlsx 的原生图表能力（已实测）

不启动 Excel、纯 Python 直写已经验证可以产出"Excel 里可拖动"的原生图表：

- 实测产物（毫秒级生成、7.9 KB）：`.cache/excel-native-check/openpyxl-native-charts.xlsx`。
- 包内是 `xl/charts/chart1.xml`（原生 `scatterChart`，`xVal`/`yVal` 直接引用
  `'Match'!$B$2:$B$14`、`$D$2:$D$14`）与 `chart2.xml`（原生 `lineChart`，PMISH/REF 两条系列）；
  文件里没有 `media/` 目录，说明图不是图片，而是可选中、可拖动、可缩放、可"选择数据/更改图表类型"
  的普通图表对象。
- 两种锚点都能写出：`oneCellAnchor`（固定尺寸、左上角锚定单元格）与
  `twoCellAnchor`（`editAs="twoCell"`，随单元格移动/缩放）；导出时按版面需要二选一。
- 可写设置：图表标题、轴标题、轴数字格式、网格线、标记形状/大小、线色线宽、图例位置、
  系列名称与引用范围、图表尺寸与锚点；Excel 打开后可继续改系列、颜色、坐标轴、尺寸。
- 直写做不到/较弱的：套用 `.crtx` 图表模板、部分高级格式（渐变、误差线细节）、图上自由文本框
  （样例里 `y = 1.0839x - 3.0875 / R² = 0.9691` 那种文本框）。因此方程与 R² 写进标题或参数块，
  或只在 B2 模式下由 Excel 补文本框。
- 运行条件：不需要安装 Excel；只有 B2 才调用 Excel。

### 7.6 B2（调用 Excel）的卡顿风险与约束

调用桌面 Excel 是"跨进程自动化"，卡不卡取决于 Excel 实例的状态，而不是我们的代码：

1. 每次调用都要等 Excel 进程响应；打开 7,731 行、多 sheet、多图的工作簿通常是**秒级到十几秒**。
2. 受保护视图、链接更新、宏/加载项、"文件已被占用"等任一弹窗都会让调用一直等待；
   放在界面线程同步调用就会直接卡死界面。
3. 不能复用或干扰用户已经打开的 Excel 实例与其文档。

因此 B2 若启用，必须：后台独立进程 + 隐藏的新 Excel 实例 + 每一步超时与强制回收 +
只操作刚导出的新文件 + 失败时回退到 B1 产物，并明确告知"需要本机安装桌面 Excel"。

## 8. 分阶段实施（按你给的顺序）

1. **统一导出数据**：抽出 `ExportModel`（源表 / 参与行 / 数值绘图区 / 参数信息），
   现有纯数据导出改由它生成，行为与 sheet 名保持向后兼容。
2. **完成 A**：TEM 四张图 sheet（Match/FM/Dynamic/Map）→ 图片与图注；
   再补 Radius、NOVA/KLA 的 Per-Group sheet 与 RSQ/All_Trend/Order。
3. **B 单参数验证**：先用 DP（或多参数样例里的一个参数）验证原生散点+折线的绑定、
   样式模板与空值处理；逐值与 A 对比。
4. **扩展到多参数、Group 与独立子窗口**：多参数分块、Group 分 sheet、子窗口各自导出。

## 9. 验收清单

1. 数据：数值绘图区与界面计算结果逐值一致（Card、R²、Bias、Bias %、有效点数、超限计数）；
   原始字符串逐格一致；行身份列齐全。
2. 引用：每个系列的起止行、类别列与数值绘图区完全一致，无"少一行/多一行"；空值留空。
3. A：嵌入图与界面同数值、同单位、同色标；图注含参数/Group/阶段/行数/Card 来源。
4. B：在 Excel 打开后每个系列可编辑（改颜色/坐标轴/尺寸），无 `#REF!`、无空白图；
   导出的颜色与线型经文件属性核对。
5. 兼容：sheet 名合法（≤31 字符、无 `[ ] : * ? / \`）、重名自动编号；导出不修改 WKB、
   不修改原桌面 WKB 与 `config/settings.yaml`。
6. 性能：7,731 行多参数工作簿记录 A/B 各自耗时，导出期间界面可响应（后台线程 + 进度）。

## 10. 非目标与待确认

- 不做 Excel → WKB 回写；不用 Excel 拟合替代软件算法；不改插值、色标、采样与参与范围。
- 待确认：B 采用 B1 还是 B2；TEM 是否要 `Radius` sheet；`Match_<Group>` 用显示名还是稳定 id
  作 sheet 名（重命名后的可追溯策略）；每个图 sheet 是自带源表（与样例一致）还是只放数值区
  并引用一张公共 `Source` sheet（更省体积）。
