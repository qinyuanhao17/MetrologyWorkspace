# Metrology Workspace

Python 3.10+ / PyQt6 桌面软件。启动后进入主窗口，**Wafer Map** 与 **Correlation Analysis** 作为两个可加载组件独立打开。Wafer Map 包含 Data、Wafer Maps、Radius Plot；Correlation Analysis 复用相同的 Data 工作区，并提供 Pairwise Fit 与 Die Seq Plot。

## 运行

本机已准备项目环境：

```powershell
cd D:\WaferMap
.\.venv\Scripts\python.exe main.py
```

VS Code 选择 `D:\WaferMap\.venv\Scripts\python.exe`，直接运行 `main.py`。
主窗口默认不加载任何组件；即使工作目录或命令行中存在数据文件，也保持 **UNLOADED**。点击 **Wafer Map**、**Correlation Analysis** 或组件卡片中的 **Load** 会**新开一个组件实例**，同一模块可重复点击实现多开；每个实例窗口右上角有编号，导航按钮徽标显示当前打开数（如 `2 OPEN`）。组件卡片中的 **Close all** 关闭该模块全部实例，顶部 **Unload all** 关闭所有模块。
该环境复用本机已有的 PyQt6，其余依赖装在本项目。
换电脑时使用 Python 3.10+ 执行：

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Windows 便携版

解压 `MetrologyWorkspace-Windows-x64.zip` 后，双击目录中的 `MetrologyWorkspace.exe` 即可运行，不需要另装 Python。请保留 `_internal` 文件夹与 EXE 在同一目录；`settings.yaml` 位于 EXE 旁边，保存设置后下次启动会自动读取。

重新构建便携版：

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean MetrologyWorkspace.spec
```

## 设置与主题

主窗口左上角的菜单按钮里选择 **Settings…** 打开设置弹窗，可配置浅色/深色主题，以及分辨率、默认色阶、字号、插值平滑、Min R²、边缘填充、共享色阶、点值、色条、等值线和测点着色等默认项。**Save** 会把配置写入项目根目录的 `settings.yaml` 并立即应用主题；下次启动会自动读取，无需重复设置。弹窗里的 **Load from YAML** 可重新读回已保存的配置。浅色主题采用 Codex 风格的中性灰白配色，原生标题栏会随主题一起切换，不再是黑条。

## 当前功能

- 左侧 Excel 式表格：字母列号、数字行号、可编辑单元格、完整值编辑栏、区域复制/粘贴、清空单元格、撤销/重做。
- 第一行为字段标题；编辑标题或数据后，右侧自动重新识别。
- CSV/XLSX 导入；多个 Excel 工作表可选择；保留 `001` 等文本 ID 和原始数值字符串。
- **Paste table**（Ctrl+Shift+V）用完整表格替换工作区；表格里的 **Ctrl+V** 在 A1 粘贴带表头的整表时同样按“替换工作区”处理，并清除上一张表留下的多余行列、重新自动识别 wafer/参数；在其他单元格粘贴则只覆盖该区域，保留已有分组。
- **Ctrl+C** 复制区域，**Delete** 清空区域，**Ctrl+Z / Ctrl+Y** 撤销/重做，**Ctrl+S** 保存 CSV。
- 右上 Wafers：顶部直接显示当前分组条件（如 `Wafer ID / Lot ID / PAD Name`），点击可多选表格中的身份字段；默认选中 Wafer ID、Lot ID、PAD Name。下方列表点击整行任意位置即可勾选/取消，悬停可查看完整身份信息。
- 右下 Parameters：识别所有标题，默认只显示可绘制的数值列；在 Wafer Map 中新导入或粘贴数据后不默认勾选参数。取消 Numeric 可看元数据标题，支持搜索、多选/全选，点击整行即可切换选择。
- X/Y、FIELD X/Y、X(mm)/Y(mm)、Die Seq 等作为元数据，不默认作为测量项目。
- 阵列规则固定为：**行 = 已选测量条目数；列 = 已选项目数**。同一 Wafer ID 的不同 PAD Name 是不同条目；当前 CSV 为 6 个条目 × 3 项 = 18 张 Map。
- 未保存编辑在关闭或替换表格前提示；输入不修改原文件，只有手动保存才写入所选 CSV。
- 表格是数据编辑器，暂不支持 Excel 公式计算、合并单元格或完整 Excel 格式。
- 页签采用相连矩形样式；新建、打开、粘贴、保存放在表格标题栏，不再占用独立的大标题区。
- 四个数据按钮统一为 104 × 34；去掉品牌栏和 LOCAL 标识。Data 页不再重复显示 MAP ARRAY 卡片，切换到 Wafer Maps 后直接选择方框。

## 绘图区

1. 在 Data 勾选晶圆和参数，切换到 Tab 2 进入方框阵列，不自动绘图。
2. 优先识别 `X(mm) / Y(mm)`，没有时使用 FIELD X/Y 或 X/Y；也可手动选择坐标列。
3. 鼠标拖动选择矩形区域；Ctrl 增减格子，Shift 扩选；All / None 全选或清空。点击 **Draw selected** 只计算选中的 Map，其他位置留白，仍保持原来的行列布局。**Select maps** 可返回方框模式。
4. 每张图包含圆形裁切、连续彩色插值、原始测量点及数值和四边坐标轴框。默认 Color 为 Turbo，也可选择 Viridis、Plasma、Jet、Coolwarm 或 Spectral；色阶会自动裁掉过暗的色段并整体提亮（亮度低于 0.38 的色段不进入映射，再向白色混入 16%），所以晶圆外圈不会被画成一条近黑的边，colorbar 两端是可读的浅蓝和亮红。色阶实际用到的**颜色范围**可以拖动调整：工具栏 **Colors** 是一条可拖动的色带，两个手柄决定使用调色板的哪一段（默认已自动跳过近黑的两端）。把左手柄向右拖，底图最深的那一档就会变浅；把右手柄向左拖则去掉最红的一端。拖动时立即复用已有插值结果重绘，状态栏会显示当前使用的百分比区间。**Opacity** 控制每张 Map 填色的不透明度（100%–50%），等值线和测点始终保持实心，colorbar 显示的是同样的混色结果；调低后整个图会变淡，适合叠加或弱化底图。Point values 和 Measurement points 可分别即时显示或隐藏，Scale bar 可控制每张图的 colorbar 是否显示，这些显示切换均复用已有插值结果。**Contour lines** 在填色面上叠加等值线，呈现参考图那种地形图观感；每条等值线按底下填色的亮度自动取深色或浅色，所以色阶最暗的一端也看得见。**Point outline** 给每个测点加一圈浅色描边（点本身仍是深色），在色阶最暗的边缘区域也能看清测点；关闭时是普通深色小圆点。两者都只重绘已有插值结果，不重新做 RBF。悬停测量点可查看更完整的数值。标题依次为参数名、测量分类、实测 Min / Max / Mean。
5. 行对应测量条目（晶圆 + Lot + PAD / Run）、列对应参数；图标题和方框标签带 PAD Name。默认每张图使用独立色阶；勾选 Shared scale 才让同一参数的已选 Map 共享色阶。跨图比较绝对大小时应开启共享色阶。
6. Diameter 默认 **Auto**：当坐标列是 X(mm) / Y(mm) 时，根据 XY 覆盖范围识别 100、200 或 300 mm 标准晶圆；小幅采样偏心会吸附到圆心 (0, 0)。坐标轴边框严格使用识别直径，例如 300 mm 显示为 -150…150 mm，不再额外扩成约 320 mm。其他坐标类型使用数据范围估计圆，也可手动输入直径；边界过小会提示而非截掉测量点。标准换算为 100 mm≈4 英寸、200 mm≈8 英寸、300 mm≈12 英寸。
7. Fill edge 控制是否填充采样点凸包之外；该区域不是实测数据。开启时把外侧采样点沿晶圆半径镜像成虚拟样本，再用同一个全局薄板样条覆盖整个圆面：全圆是一张连续曲面，没有凸包接缝，也不会像无通量调和延拓那样在边缘压出一圈均匀色带，边缘会延续实测的径向趋势。镜像只取外侧样本（r ≥ 0.5R），避免把内部离群点投射到边缘；结果再按实测 Min/Max 截断。关闭后凸包外留白，只显示实测覆盖范围。
8. 默认使用 Turbo 连续色阶；标注加浅色描边以保证在底图上的可读性。View 支持适宽和 50–300% 缩放：普通滚轮纵向滚动，Shift+滚轮横向滚动，Ctrl+滚轮逐级缩放并尽量保持鼠标指向的位置。Resolution 可选 Standard（100% 屏幕渲染 / 200 dpi PNG）、High（150% / 300 dpi，默认）或 Ultra（200% / 400 dpi）；滚轮仍然只更新 Qt 视图矩阵，不重新插值或重画整套图元。Matplotlib 光栅按高于屏幕的分辨率超采样后再由 Qt 视图缩放，因此 QGraphicsView 打开了平滑重采样，并关闭了缩放时会失真的字形 hinting，避免字体边缘发虚。
9. Font 可在 8–16 pt 间调整基础绘图字号，坐标轴标签小 1 pt、坐标刻度和 colorbar 刻度小 2 pt；连续选择会延迟合并，直接更新现有文字对象，不重新创建图或重新插值。阵列的四周边距随字号一起放大，字体调大后最左列的 Y 轴标签和标题不会被裁掉、整组图仍居中。Export PNG 与 Copy PNG 都使用当前 Resolution，并输出**整个阵列**。
10. 同一测量条目中坐标完全相同的多个参数共享一次 RBF 矩阵求解；点值合并为每张 Map 一个矢量文字图层。插值显示网格按阵列规模自适应（≤12 张用 400 × 400，≤48 张用 300 × 300，更大用 200 × 200），小阵列因此接近屏幕像素密度，显示不再发虚。薄板样条支持平滑项（Settings → Interpolation smoothing：Off / Light / Medium / Strong）：Off 精确穿过每个测点，Medium（默认）会让曲面残差约为「该参数自身量程」的 9%，用来压掉螺旋采样点之间产生的放射状等值线抖动。求解前每个参数列都按自身均值和量程标准化，因此量程差别很大的参数共用一次求解时，不会互相把对方抹平；数值结果由逐参数对照测试保证一致。

## Radius Plot

- Tab 3 使用 Data 页当前勾选的测量条目和参数，无需再次配置分组。进入后先在 **Select maps** 面板框选要画的格子（**与 Wafer Maps 的框选是两套独立状态，互不影响**），再点 **Draw selected**；未选中的格子留白并保留原行列位置。
- 横轴按 `signed R = sign(X) × sqrt(X² + Y²)` 计算：X < 0 显示在负半轴，X > 0 显示在正半轴；X = 0 时为 0。纵轴为所选参数值。
- 阵列规则与 Wafer Maps 一致：行＝已选测量条目，列＝已选参数；每个“晶圆/PAD × 参数”单独一张散点图，不再将多个测量条目叠在同一张图。标题依次显示参数、测量分类和 Min/Max/Mean。
- 标准毫米坐标沿用 100/200/300 mm 自动识别，因此 300 mm 晶圆的 signed radius 横轴固定为 -150…150 mm。支持 8–16 pt 字体、适宽及 50–300% 缩放、普通/Shift/Ctrl 滚轮操作，并与 Wafer Maps 共用 Standard / High / Ultra 分辨率和 PNG 输出规则。

## Correlation Analysis

- 主窗口中手动加载 **Correlation Analysis**；Tab 1 与 Wafer Map 的 Data 页一致，可导入、粘贴和编辑表格。
- Wafers 的勾选范围决定参与拟合的数据行，Parameters 中选中的 numeric 列决定两两组合；选择 n 列会生成 n(n-1)/2 个组合。新导入或粘贴数据时默认全选所有测量条目，并自动勾选可用 numeric 列，但排除 MSE、GOF、NGOF、LBH、regIter（也兼容 reglter 拼写）和 CINDEX；名称匹配忽略大小写、空格、下划线和连字符。
- Tab 2 对每一对列使用 `lmfit.models.LinearModel` 拟合 `y = slope × x + intercept`，忽略未能成对转为数值的行；有效配对少于 3 点或常数列会跳过。
- 所有散点图按照 R² 从高到低排列，标题显示变量对、拟合方程、R²、有效点数和排名。Min R² 默认 0.50，仅绘制严格满足 R² > 0.50 的结果；修改阈值只筛选已有 lmfit 结果，不重新拟合。一次最多选择 40 列；为避免低阈值生成超大画布，界面按排名显示最强的 12 张图并在状态栏报告完整通过数量。
- Min R²、列数、字号和分辨率的连续修改会合并为一次刷新；大阵列的屏幕渲染自动限制像素量，PNG 导出仍使用所选 Standard / High / Ultra 的完整 DPI。
- 支持每行 2/3/4 图、字体大小、Standard/High/Ultra 分辨率、快速缩放、完整阵列 Export PNG 和 Copy PNG。
- Tab 3 **Die Seq Plot** 按已选 Numeric 参数分别绘制折线与测点，标题为参数名；横轴内层显示真实 Die Seq（允许缺号，不自动补齐），外层显示 Wafer ID，各测量条目之间用留白和分隔线区分。支持单列/双列布局、字号、缩放、分辨率、Export PNG、Copy PNG 和 Ctrl+C。

绘图区不再提供独立分组下拉框；测量分组在 Data 页自动完成。当前 CSV 的 480 行会完整拆为 **3 个 Wafer ID × 2 个 PAD Name = 6 个测量条目，每条 80 点**，可直接绘制，无需删除其中一组。原始文件未被改动。

### 自动识别规则

- 菜单中勾选的普通字段共同组成测量身份；任何一项不同都单独列出。首次导入或粘贴表格时自动勾选身份列：`Wafer ID` 一定参与；`PAD Name` / `Lot ID` 只有在确实有多个不同取值时才加入。PAD 恒为 `CELL` 的文件按 Wafer ID 分组，同一 Wafer ID 有多个 PAD（如两次时间戳测量）的文件拆成 `Wafer ID × PAD`。也可手动改选其他元数据字段。空值不猜测或向下填充；列名识别忽略大小写、空格和下划线。
- Die Seq 是每个测点的元数据，允许跳号和缺号（例如范围 1–100 只测到 92 个 die），**不作为分图或筛选条件**，也不出现在身份字段菜单中；缺失的编号不会被当成新 wafer。
- 同一个最终测量条目内仍不允许重复 X/Y；遇到无法拆分的重复点会报错，**不会平均、选择第一组或覆盖原行**。所有绘图使用对应条目的原始行索引。

无有效数据的组合保留原阵列位置并显示原因。修改数据、勾选、方框选择或设置会隐藏旧结果；后台插值可以取消。为控制内存，每批最多 120 个阵列位置。

本软件使用 SciPy 薄板样条 RBF 插值；外观参考用户提供的 Wafer Map，**不是 KLA 专有算法的复现**。不同测量可并排查看；当前不实现 A/B 差值 UI 或测量单位自动换算。

## 架构

```text
main.py                    仅启动、配置字体和自动载入
wafermap/
  shell.py                 主窗口、组件多开/卸载、设置弹窗和活动记录
  module_registry.py       可加载组件元数据和延迟创建工厂
  module_button.py         带实例数徽标（N OPEN / UNLOADED）的导航按钮
  correlation_window.py    复用 Data 页的相关性分析组件窗口
  correlation_page.py      lmfit 两两线性拟合、R² 排序与散点图阵列
  sequence_page.py         Numeric 参数按 Die Seq / Wafer ID 分组的折线图
  data.py                  表格导入、字段识别、数据筛选
  measurements.py          Wafer/Lot/PAD 等复合测量身份识别
  sheet.py                 表格模型、单元格编辑、复制粘贴和撤销
  window.py                三个 Tab、面板布局与选择联动
  appearance.py            字体、Qt 配色与原生 Windows 标题栏
  theme.qss                深色控件样式
  theme_light.qss          浅色控件样式
  settings.py              YAML 配置读写与主题应用
  settings_dialog.py       设置弹窗，主窗口左上角菜单入口
  assets/atmosphere.png     深色背景素材
  assets/arrow_*_*.png      两套主题的下拉/微调箭头
  assets/check_white.png    勾选框对勾图标
  plot.py                  单张 Wafer Map 插值、坐标轴与 colorbar
  array_plot.py            选中格子的数据准备、重复检查与统一色阶
  map_selector.py          方框阵列、鼠标拖选及选择保留
  plot_page.py             绘图区控件、后台插值、缩放和导出
  radius_page.py           带 X 正负号的径向散点图、导出和复制
tests/
  test_core.py             数据及绘图回归
  test_workspace.py        表格编辑与第一个 Tab 的交互回归
  test_array.py            阵列顺序、拖选、重复检查、取消与导出回归
  test_measurements.py     自动身份、字段别名、序列重启及原始行映射
  test_radius.py           Signed radius 计算与真实数据绘制回归
```

保持按职责拆分；主窗口只依赖组件注册信息，Wafer Map 在首次加载时才导入和创建。组件内部第二个 Tab 直接消费当前选择：
`window.selection = {wafers, metrics, wafer_column, groups, labels}`。
其中 wafers 保存稳定的测量身份键，groups 映射到原始行位置，labels 提供人类可读标签；不向用户表格插入辅助列。

## UI 来源

外观采用 Segoe UI Variable 字体、紫黑背景、细边框卡片与紫色交互色，另提供浅色主题；中文内容使用微软雅黑回退。
当前数据页布局按用户要求重新组织，非仪器控制主页的逐像素复制。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

运行完整回归测试即可验证数据识别、绘图和模块窗口行为；开发时生成的截图与视觉检查临时文件不纳入项目。
