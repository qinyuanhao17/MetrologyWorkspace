# Excel 导出方案：数据 + 图片（A）与数据 + Excel 原生图表（B）

Status: both single-file export routes are implemented and verified.
The latest implementation notes at the end supersede conflicting earlier proposals.
本文定义导出形态、数据契约、sheet 映射、图表绑定与验收，不改动拟合、插值、色标、
参与范围或 WKB。

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

## 11. 实施记录

### 2026-10-11：B1 第一段（Workbook 导出，用户已选定 B1）

- 新增 `metrology_app/excel_export.py`：数据表 + 数值绘图区 + 参数信息块 + **原生图表**
  （散点/折线），不启动 Excel；`MatchingWindow.export_excel` 改为调用它。
- 每个参数一块：`序号 / 原始值 / PMISH / REF / Bias / Bias % / Fit X / Fit Y`；
  `PMISH = $K$slope*B+$K$intercept`（软件 Card 系数），`Bias = C-D`，`Bias %` 含除零保护；
  参数信息块写 Parameter、Reference/Raw 列、slope、intercept、R²、有效点数、Bias limit、
  单位、Card 来源、阶段、范围、行数与方程文本；不写 `SLOPE()/LINEST()/RSQ()`，不写趋势线。
- 图表：Match 散点（点=原始值×REF，另加软件系数的 Fit 系列）+ Trend 折线（PMISH/REF）+ Bias 折线，
  系列全部引用单元格；有分类时每个 Group 一张 `Match <Group>` sheet，另保留 `Group Fits` 与 `Order`。
- 数据 sheet 顺序：`Summary`、`Reference`、`Raw Data`、`Preview/Final`、
  `Match`/`Match <Group>`、`Group Fits`、`Order`、`Preview/Final FullMap`。
- 验证：新增 `tests/test_excel_export.py`（原生图表类型与单元格引用、Card 公式与系数、
  原始字符串、每个 Group 一张 sheet）；导出/分组/性能/主窗口四组 **219 项测试通过**。
  真实工作簿 `matching-analysis_nova_testfilter1.wkb`（6,958 行 × 2 参数）导出 3.87 s、2.73 MB、
  6 张原生图表，产物见 `.cache/excel-native-check/nova-testfilter1-native.xlsx`。
- 待继续（下一段）：`RSQ` 与 `All_Trend` sheet；子窗口各自的导出（FM=Correlation/Trend、
  Dynamic、Radius、Map 图片），以及 Excel 端人工拖动/编辑验收。

### 2026-10-11 续：`RSQ` 与 `All Trend`

- `RSQ`（NOVA/KLA）: 每个 Wafer 一行、每个参数一列 R²（来自 `wafer_summary`），
  Wafer 用 `/` 连接多行身份；每参数一张原生折线（类别=Wafer，值=该参数 R² 列）。
- `All Trend`（有分组时）：每个参数一段，按 Group 分列 `原始值 / PMISH / REF / Bias`，
  `PMISH` 用该 Group 的 slope/intercept 单元格（写在同一段的右侧信息区）做公式；
  每参数一张原生折线，每个 Group 两条系列（PMISH 与 REF）。Bias 保留在表内，
  其单独折线仍在每张 `Match <Group>` sheet 上。
- sheet 顺序（NOVA/KLA 有分组时）：
  `Summary`、`Reference`、`Raw Data`、`Preview/Final`、`Match`、`Match <Group>`…、
  `All Trend`、`RSQ`、`Group Fits`、`Order`、`Preview/Final FullMap`。
- `tests/test_excel_export.py` 增加 All Trend 的列头/公式/系列引用与 RSQ 的 R² 与图表断言。
- 全量 `python run_tests.py`（B1 后）：**695 项，2 失败 + 1 错误**。
  错误仍是沙箱内 `os.link`（沙箱外通过）；两个失败是 `test_performance_regressions` 的
  固定耗时阈值（Opening Wafer Map 0.516 s / Correlation check 0.249 s），
  同一台机器上用**发布提交 a26e670 的独立副本**复测同样失败（0.673 s），
  即本轮 B1 未引入新的功能性回归；两次全量运行耗时 564 s 对 291 s，属机器负载差异。

### 2026-10-11：两种入口与最新用户约束

本节覆盖前文存在冲突的旧建议。

- `Export Excel` 使用 Excel 原生图表，采用 Office 默认图表主题；
  `Save images` 已改名为 `Export Matplotlib`，输出同一份 Excel 数据、嵌入的 Matplotlib 图片及独立 PNG。
- 新生成的标签、提示、列头均为英文。单元格和新绘图默认 Times New Roman。
  原始表的列名与测量字符串保持原样；Wafer Map/Radius 保留当前软件 PNG 的原有外观。
- 主工作簿在一个文件中导出已有配对数据的 Preview/Final 两套 sheet，
  分别使用 `(WO Card)` / `(W Card)` 后缀。尚未提供某阶段配对源表时不构造假的分析结果；
  已有的独立 FullMap 源表仍导出。Reference 为两阶段共用的原始源表。
- Final 原始值已是该阶段的接受值，PMISH 直接引用 Final 值，避免再次应用拟合 Card。
  Preview 的数值绘图区沿用软件的 Card 计算；两阶段的软件拟合系数、R²和源表均保留。
- Correlation/Trend、Dynamic、Wafer Map/Radius 的 File 菜单均提供两条导出入口。
  子窗口使用自己的数据、参数、参与范围、成功 Draw 和轴方向；主工作簿也收录当前打开的命名子窗口。
  未打开的保存草稿不会自动启动绘图。Map/Radius 嵌入当前已绘制页的 PNG，并标注页码，
  两条路线均不重新插值或重算半径图。
- Correlation 散点与软件拟合线、Trend 的来源/对比曲线与第二轴、Dynamic 的 3 Sigma 柱状和
  当前 Die 的 Cycle trend 均使用单元格绑定。主窗口 Match/Trend/Bias/Bias %、Group、All Trend、RSQ 均已覆盖。
- 生成 sheet 名合法化与重名编号时保留阶段后缀；数值绘图区保存源行号、Die Seq和标签。
  Source missing values remain blank. Derived numeric formulas use `NA()` for missing values or zero
  percentage denominators: actual Excel treats formula `""` as zero in some charts. These intentional
  chart gaps are not invalid references. Source text is never interpreted as an Excel formula.
- 菜单写入使用后台任务和取消进度窗口。xlsx 写到同目录临时文件，完整且未取消才替换目标；
  关闭正在导出的窗口会等待写入安全收尾，再走原有关闭/保存恢复逻辑。
- 可执行验收：`docs/features/excel_export.feature` → `tests/test_excel_export.py`；
  最终全量与真实桌面 WKB 副本结果在验证完成后补充。

### 2026-10-12: Final chart and font verification

- Both routes use English generated labels and Times New Roman. Literal source headings and
  measurement strings remain unchanged. Current Wafer Map/Radius PNGs retain their existing appearance.
- Native charts use an Office built-in style, unsmoothed curves, light gridlines and General tick formats.
  Chart titles, axis titles and legends reserve their own space instead of overlaying the plot.
- Compact overview charts label at most five representative contiguous Wafer/Group spans, chosen by
  actual plot positions with a minimum label separation. Wider native Trend/Bias panels keep captions
  readable without automatic rotation or word wrapping. This is
  display-only: every measurement is retained in the bound series and full identity/Die Seq columns.
  Excel and Matplotlib pictures begin after the complete numeric helper area.
- Read-only verification in a separate hidden desktop Excel instance confirms Preview/Final formulas,
  native titles/axes, unsmoothed lines and missing-value gaps. No existing user workbook is opened or saved.
  This check also caught and corrected All Trend's coefficient references (value cells instead of label
  cells). The executable Group test and actual Excel calculations verify the corrected references.
- Font styling updates shared font definitions once instead of materializing and visiting every blank
  worksheet cell. A frozen 7,731-source-row / 6,958-participating-row testfilter1 copy was measured in
  independent processes, with two runs per version: 28.763/28.873 seconds before and 4.989/4.985 seconds
  after. The final wide-chart version measured 5.050/5.177 seconds, with font/chart styling taking
  2.5 milliseconds. No timing threshold changed. Comparison of 460,414 frozen-baseline cells passed;
  only intentional chart-gap formula guards and display label helpers differ.
- All seven copied Desktop WKBs passed both-route cell equivalence, default-font and unchanged-window-state
  checks. Source versus participating rows remain distinct (7,731 versus 6,958 in filtered NOVA workbooks).
- Individual PNG files also use a temporary sibling and atomic replacement; interrupted PNG writing
  preserves the previous complete picture. The workbook and separate PNGs are individual atomic files,
  not one cross-file transaction; cancellation after workbook publication may retain that complete workbook.
- Focused executable export tests: 15 passed. Final `python run_tests.py`: **708 tests passed in 286.870 seconds**.
  The runner used isolated settings/recovery/MPL/TEMP paths and an audit guard rejecting user-config writes.
  One earlier full run encountered Windows access-denied while replacing a scratch WKB in OneDrive;
  that exact save test passed independently, then the entire unchanged suite passed with TEMP outside OneDrive.
- Final seven-copy acceptance passed on the final layout and formulas. Both export routes contain identical
  source strings and numeric/formula cells, and leave each captured window's frames and states unchanged.
  The native dense NOVA chart has all 6,958 points and readable representative Wafer/LOT/PAD captions.
  All seven original Desktop WKB hashes still match the frozen input copies; user configuration was preserved.
- No application packaging, Git commit/tag/push, original WKB write or user settings write was performed.

### 2026-10-12: Single-file Matplotlib output and matched chart styling

This section supersedes the earlier separate-PNG export behavior and default Office-only chart appearance.

- Both menu routes now choose a single `.xlsx` target. `Export Matplotlib` embeds its generated PNG bytes
  inside that file; it creates no sidecar images. Existing folder callers still receive one Excel file.
  Previously exported PNGs are not deleted. Workbook publication remains atomic and cancellable.
- The software and both supplied Excel examples informed the visual design: blue/orange comparisons,
  compact Match panels, wider Trend/Bias panels, a light report frame and regression headings above the data.
  Font defaults remain Times New Roman, with English generated text and unchanged literal source headings.
- Matplotlib and native charts share series colors, labels, marker/line distinctions and data-derived
  outer ticks. Tick scales round the axes only; source measurements, fitted coefficients, row identities,
  participation and WKB state are not rounded, filtered, averaged or rescaled.
- Native Excel charts remain editable and cell-bound. Their automatic typography/layout may differ from
  Matplotlib, but numerical ranges, major steps and series values match. Map/Radius reuse current software PNGs.
- Public export and menu regressions verify single-file output, embedding, data equality and native style.
  Small and 6,958-row NOVA exports pass unchanged-window-state and cell-equality checks. Actual desktop Excel
  confirms all 6,958 points and the intended bounds/ticks.
- Final verification: 18 focused checks passed; `python run_tests.py` passed **709 tests in 287.470 seconds**.
  All seven WKB-copy checks passed with identical native/Matplotlib cell data and unchanged window state.
  The complete fresh export directory contains zero sidecar PNGs. User config writes were blocked by the
  audit guard, and settings/recovery/MPL/TEMP paths were isolated outside OneDrive.

### 2026-10-13: Compact report layout in both modes

- Each stage's Match sheet starts with its exact Raw Data at A1. Separate visible Reference, Summary,
  Raw Data and Preview/Final sheets are removed. The original Reference strings, full-precision software
  Card coefficients, source positions and chart label/fit helpers are retained in a hidden `_Plot data` sheet.
- Parameter tables use optional Group, Wafer captions according to plot-label choices, and Die Seq,
  followed by PMISH, PMISH+Card (Preview only), the actual TEM/NOVA/KLA label, Bias and Bias %.
  Final uses its accepted PMISH values directly. The previous visible parameter metadata block is removed.
- Both renderers place wider charts to the right of their data and align their tops. Times New Roman
  titles and axis labels are larger; regression annotations remain smaller than the parameter title.
  Native Trend and Bias retain identical categories and cell-bound values rather than refitting in Excel.
- FullMap uses its own data and plots only mapped parameters. Already drawn software Map/Radius panels
  are cropped without interpolation or changing the live figure, then placed beside the data in
  Wafer Map / Trend / Radius sections. Per the user's confirmation, undrawn Map/Radius plots are omitted.
- Public executable checks are in `tests/test_excel_report_layout.py` and `tests/test_excel_export.py`;
  acceptance wording is in `docs/features/excel_export.feature`. No original WKB/settings writes,
  packaging, commit, tag or push are part of this change.
- Final verification: 20 focused export checks and all 719 tests passed. Small and 7,731-source-row /
  6,958-participating-row WKB-copy exports have identical native/Matplotlib cells and unchanged source
  frames/window state. A private read-only Excel instance verified chart alignment, no horizontal
  overlap, full point counts and the larger titles. The default FullMap fallback also retains its
  child's value of 1 rather than substituting the parent Card value of 3, and both modes reuse identical
  filtered software PNGs. User settings and all seven original Desktop WKB hashes were preserved.

### 2026-10-15: Separate physical panels, editable Excel categories and source projections

This section supersedes the shared Matplotlib/native visual styling and representative-only captions above.

- Original contains literal stage-specific Raw Data in original order, without charts or merged source
  cells; matched Reference values occupy a separate area on its right. Match retains Raw Data at A1.
  PMISH and Reference measurements in Match, Group and Wafer parameter tables refer to exact
  Original source rows; Preview/Final keep their respective (WO Card)/(W Card) suffixes.
- Group projections collect Group then Wafer/Lot/PAD identities; the separate Wafer sheet instead
  follows each identity's first appearance in Original and preserves original row order within it,
  independently of Group order. The live WKB's plotting order and source data are not changed.
- Matplotlib embeds separate physical-size panels rather than a stretched mosaic: Match is 15 by 11 cm;
  Trend/Bias are at least 25 by 11 cm. Compact local caption spacing reuses Expand Wafers' measured
  layout, with every Wafer caption retained. Ordinal X limits hug the first/last observations.
- Native Excel output uses ordinary category LineCharts and visible local series/category ranges,
  Excel's built-in chart theme, square corners and an explicitly orange Reference series. It does not
  imitate Matplotlib's custom frame. Derived contiguous Wafer captions are vertically merged by actual
  Wafer/Lot/PAD identity, never by a potentially incomplete visible caption alone.
- Group Match reports retain both the Group overview and separate Wafer-detail panels to its right;
  the dedicated Wafer sheet has only Wafer sequencing. Each drawing aligns with its parameter heading.
- Named-window entries offer a confirmed right-click deletion. Deletion removes only that window's
  independent data/state and persists after WKB save/reopen, including deletion of the final/default entry.
- Executable acceptance is in excel_export.feature/named_analysis_windows.feature and the corresponding
  public-export/menu tests. Final verification: 38 focused export/window checks passed, and
  `python run_tests.py` passed all **730 tests in 310.183 seconds** with isolated settings/recovery/MPL/TEMP
  and a guard rejecting user-config writes. The updated MatchingWindow export integration also passed.
- A frozen 7,731-source-row NOVA copy with three enabled Groups passed both-stage native and Matplotlib
  exports. All **2,556,776** exported cell contents (including formulas) match across both modes;
  source WKB hash, input frames and window state remain unchanged. Saved PNG inspection confirms
  separate physical-size Match/Group panels and readable first/last Wafer captions in the long detail plot.
- Actual desktop Excel inspection of the generated small sample verified local multi-level categories,
  an orange Reference series and draggable value-range handles: shrinking F3:F28 to F3:F27 worked,
  and Undo restored F3:F28. Only the sample was closed without saving; existing user workbooks were not edited.
- Final artifacts and audit evidence are under `.cache/export-redesign-20261015/`. No original WKB write,
  user-settings write, packaging, commit, tag or push was performed.
