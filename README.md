# Metrology Workspace

Metrology Workspace 是一套 Python 3.10+ / PyQt6 桌面工具，用于整理量测数据、完成 Card 匹配，并绘制 Wafer Map、径向图、相关性图和 Die Seq 趋势图。主窗口提供 **Wafer Map**、**Correlation and Trend** 和 **Card Matching Workbook** 三个工具。每次打开都会创建一个独立窗口，同一工具可以同时开多个实例。当前 `v2` 分支为 `2.0.0-dev`；已发布且保留的稳定版本是 `v1.2.0`。

## 运行

项目已经提供 Anaconda 环境文件。首次使用时，在项目目录执行：

```powershell
conda env create -f environment.yml
conda activate metrology-workspace
python main.py
```

本机环境位于 `C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace`。在 VS Code 中选择该目录下的 `python.exe` 即可运行和调试。环境会独立安装 `requirements.txt` 中的依赖，不使用系统 Python 包。

主窗口通常以约 1180 × 820 的尺寸居中打开；在小屏幕或高缩放比例下，会按任务栏以上的可用空间自动缩小。分析窗口依次错开，窗口变小时仍可通过滚动条查看内容。

程序启动后不会自动打开分析工具。点击左侧的 **Wafer Map**、**Correlation and Trend**、**Card Matching Workbook**，或工具卡片上的 **Open**，即可新建一个窗口。卡片上的 **Close all** 关闭该工具的全部窗口；顶部的 **Close all windows** 关闭所有分析窗口。

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

## Card Matching Workbook（v2 开发中）

该工具把日常的 Reference/Raw Data 匹配流程从手工 Excel 中独立出来。当前实现按以下顺序工作：

1. 先粘贴已经整理好的 Reference 表。一个表可以同时包含多列参数，例如 `CD_Bot Reference`、`SPA Reference`。
2. 再粘贴 Raw Data。当前版本按从上到下的行顺序对应，两张表必须具有相同的行数。
3. 软件会把 `<参数名> Reference` 自动匹配到 Raw Data 中同名参数。像 `TEM`、`PMISH` 这样没有 `Reference` 后缀的数值列也会出现在映射表中，但不会擅自自动选择；勾选需要的 Reference 列，再选择对应的 Raw Data 参数。Wafer ID、Die Seq 等元数据不会列为参数。一次最多选择 50 个参数，最多处理 100,000 行。
4. 选择 KLA、NOVA 或 TEM，并运行 Preview 或 Final。
5. 在 **3. FullMap** 中可粘贴 Preview FullMap 或 Final Raw Data，并直接打开现有的 Wafer Maps / Radius Plot 工作区。

Card 的定义为：

`Reference = slope × Raw + intercept`

- **Preview** 会把新生成的 slope/intercept 应用到 Raw Data，得到 Card Value，再用它绘制 Trend 和 Bias。TEM 可在 Card 确认后另行粘贴点数更多的 FullMap；KLA/NOVA 未提供单独 FullMap 时可直接使用匹配 Raw Data。
- **Final** 假定 Raw Data 已经由 OCD 软件应用 Card，不会重复加 Card；Trend 和 Bias 直接使用输入值。Final FullMap 作为独立输入，软件不会再次套用 slope/intercept。
- Bias 默认是 `Evaluated Value - Reference`，也可以切换成百分比 `(Evaluated Value - Reference) / Reference × 100%`。Reference 为 0 时百分比留空，不猜测替代值。
- KLA/NOVA 会额外按 Wafer ID 显示单片 SLOPE、INTERCEPT 和 R²；TEM 不显示该组单片结果。
- Match、Trend、Bias 和单片指标按参数惰性生成，不会同时展开 50 个参数的全部派生表。

**Save WKB** 保存 Reference、匹配 Raw Data、可选的 Preview/Final FullMap、参数映射和分析设置。WKB 是 SQLite-backed 的主工作文件，可以在多个独立窗口中重新打开比较；它不依赖 Excel，也不会执行不安全的 pickle。**Export Excel** 是确认结果后的可选输出，包含 Summary、Reference、Raw Data、Preview/Final 结果，以及存在时的 FullMap 工作表。**Save images** 会把每个参数的图分别保存为 PNG。

10 万行、50 参数的随机浮点基准中，50 个 Card 的计算约 0.16 秒，单个参数结果展开约 0.004 秒；WKB 保存约 1.05 秒、载入约 2.43 秒，文件约 97.9 MB。结果取自当前开发机的一次可重复测量，不代表所有磁盘和数据分布。 可用 python benchmarks/benchmark_matching.py 复测。

当前 v2 已支持 TEM 匹配后单独粘贴 Preview FullMap，并将 Preview/Final 数据交给现有 Wafer Map 和 Radius Plot。尚未实现的是按 Wafer ID、Slot ID、PAD Name 和坐标自动整理尚未对齐的 Reference；当前匹配数据仍按行序对应。
## Wafer Map

基本流程如下：

1. 在 Data 中勾选测量条目和参数。
2. 切换到 **Wafer Maps**，确认 X、Y 坐标列。
3. 在方框阵列中拖动选择要绘制的组合。Ctrl 用于增减选择，Shift 用于扩选，**All** 和 **None** 可以全选或清空。
4. 点击 **Draw selected**。只有选中的组合会参与计算，画布也只保留实际用到的行和列。

坐标列优先匹配 `X(mm) / Y(mm)`，其次是 FIELD X/Y 和 X/Y，也可以手动指定。阵列中的行对应测量条目，列对应参数。同一个 Wafer ID 下，不同 PAD Name 会作为不同条目。

每张图显示插值曲面、原始测点、点值、坐标轴和 Min/Max/Mean。默认色阶为 Turbo，也可以选择 Viridis、Plasma、Jet、Coolwarm 或 Spectral。**Colors** 两端的手柄用于裁剪调色板范围；拖动时只更新颜色，不重新计算 RBF。**Opacity** 只改变填色透明度，等值线和测点保持实心。

**Point values**、**Measurement points**、**Contour lines**、**Point outline** 和 **Scale bar** 可以单独开关。程序会复用已有插值结果，因此切换这些显示项不会改变当前缩放或滚动位置。在 18 张图的测试数据上，叠加层更新约为 0.05 秒；原来的完整重绘约为 1.2 秒。

每张图默认使用独立色阶。需要比较不同测量条目的绝对数值时，打开 **Shared scale / parameter**，让同一参数共用色阶。

**Diameter** 设为 Auto 时，X(mm)/Y(mm) 坐标会识别 100、200 或 300 mm 标准晶圆。300 mm 晶圆的坐标范围固定为 -150 到 150 mm。其他坐标类型按数据范围估算，也可以手动输入直径。

**Fill edge** 用外侧测点的径向镜像样本估计凸包之外的区域。该区域不是实测数据。关闭后，凸包外保持空白；开启后，结果仍限制在实测 Min/Max 范围内。

**View** 支持适宽和 50% 到 300% 缩放。普通滚轮纵向滚动，Shift+滚轮横向滚动，Ctrl+滚轮按指针位置缩放。**Resolution** 提供 Standard、High 和 Ultra，分别对应 200、300 和 400 dpi 的 PNG 输出。图像过大时，复制和导出会自动降低 DPI，避免耗尽剪贴板或内存。

**Export…** 支持 PNG、SVG 和 PDF。SVG/PDF 中的坐标轴、标题、等值线、测点和 colorbar 刻度保持矢量；插值色面作为图像层嵌入。**Copy PNG** 会复制整个阵列，包括当前滚动区域之外的内容。

同一测量条目中，只要坐标一致，多个参数会共用一次 RBF 矩阵求解。显示网格按图数自动调整：不超过 12 张时使用 400 × 400，不超过 48 张时使用 300 × 300，更大的阵列使用 200 × 200。插值平滑可以在 Settings 中选择 Off、Light、Medium 或 Strong。

## Radius Plot

Radius Plot 使用 Data 中当前勾选的测量条目和参数，但保留自己独立的方框选择。横轴按下式计算：

`signed R = sign(X) × sqrt(X² + Y²)`

X < 0 位于负半轴，X > 0 位于正半轴，X = 0 时半径为 0。每个“测量条目 × 参数”单独绘制，不会把多组数据叠在一张图上。标准毫米坐标沿用 100/200/300 mm 晶圆识别，缩放、字体、分辨率和 PNG 输出规则与 Wafer Maps 一致。

## Correlation and Trend

该工具的 Data 页支持同样的导入、粘贴和编辑操作。新表格会默认选中所有测量条目，并勾选可用的 numeric 列；MSE、GOF、NGOF、LBH、regIter（包括 `reglter` 拼写）和 CINDEX 默认排除。名称匹配忽略大小写、空格、下划线和连字符。

### Correlation

Correlation 使用 `lmfit.models.LinearModel` 对所选 numeric 列做两两线性拟合：

`y = slope × x + intercept`

无法成对转换为数值的行会被忽略；有效点少于 3 个或存在常数列时，该组合会跳过。方框阵列同时限定参数和测量条目。例如选择 3 个测量条目和 2 个参数，只会得到 1 个基于这 3 组数据的拟合。

结果按 R² 从高到低排列。Min R² 默认是 0.50，只有严格满足 `R² > 0.50` 的结果会显示。修改阈值只过滤现有结果，不会重新拟合。一次最多选择 40 列，屏幕最多显示排名最高的 12 张图，状态栏会给出完整的通过数量。

屏幕图由 PyQtGraph 绘制。滚轮缩放，左键拖动框选区域，右键拖动平移，双击恢复单张图；**Reset views** 恢复全部图。面板边界也可以拖动，双击边界恢复等分布局。默认三列布局会根据窗口宽度伸缩，不会横向裁掉最后一列。

**Export PNG** 使用 Matplotlib 输出完整图，**Copy PNG** 直接复制当前 PyQtGraph 阵列。复制包含滚动区域外的图，并缓存相同设置下的结果。

### Trend

Trend 按 Data 页顺序把每个 numeric 参数画成连续的 Die Seq 曲线。横轴保留真实 Die Seq，允许缺号；下方的第二条轴标出各段对应的 Wafer ID，测量条目之间用浅色虚线分隔。

方框选择决定要画的参数和测量条目。未选条目会跳过，横轴只覆盖实际有曲线的区段。默认双列布局会随窗口宽度伸缩。滚轮缩放，左键拖动框选区域，右键拖动平移；Auto Scale 会重新适配 Y 轴，但保留紧凑的 X 范围。右侧边框会一直显示。该页也支持 Reset views、Export PNG、Copy PNG 和 Ctrl+C。

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
  shell.py                 主窗口、分析窗口和 Activity
  module_registry.py       工具注册信息和延迟创建工厂
  matching/                Card 拟合、按参数惰性结果和 WKB 存储
  matching_window.py       Reference-first 工作流、结果图和导出
  correlation_window.py    Correlation and Trend 窗口
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
