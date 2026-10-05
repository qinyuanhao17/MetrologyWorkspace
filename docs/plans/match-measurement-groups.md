# KLA / NOVA 的 TestFlag、测头和可选 Mark 分组

已实现于本地，未同步 GitHub。TEM 使用与 KLA/NOVA 相同的可选 Head/Mark 分组：`Group settings`、Order 表和 `Data selection` 都可用，但结果区在 TEM 下不显示 `Group plots` 与 `Single-wafer metrics` 两个 tab；TEM 的 Map/Radius、Dynamic 仍保持独立数据工作流。

## 操作

1. 在 Reference 左侧的 `Order / TestFlag` 表粘贴或编辑 TestFlag。允许任意整数，包括正整数、0 和负整数，不限定为 `0`、`1`、`-1`；从 Excel 导入的 `2.0` 按整数 2 处理，但 `2.5` 这类小数不接受。表格按配对数据行数显示，不预填分类；未输入 Flag 的行保持空白。在分组分析中，缺失 Flag 单独归为 `Not provided`，不会冒充 Unknown。小数、非数字及无穷大标红并禁止绘制。
2. 从顶部 `Groups → Group settings…` 打开独立分组设置窗口。Preview / Final 共用同一个设置窗口，表格上方不再放置分组工具栏。启用 `Head groups`，在 `Head names…` 为实际输入的 TestFlag 命名：只有 1 就只显示 1，有 0、1 才显示这两项。全部为空时按钮不可用；已有名称保留供对应 Flag 再次出现时使用。默认名称不假定仪器一定叫 MM1/MM2。`Head groups` 与 `Mark` 在所有 Match Type（KLA／NOVA／TEM）下默认都不勾选：加载已有分析设置、粘贴带 TestFlag 的 Raw Data、编辑 Order 里的 Flag 都不会自动打开，需用户显式勾选。设置窗口非模态，可同时编辑主窗口表格；关闭只隐藏窗口，不丢弃待应用设置，设置随 Workbook 一起保存。TEM 也启用此入口（结果区不显示 Group plots 与 Single-wafer metrics）。
3. 原 `Age` 改为可选的 `Mark` 列：新建 Workbook 默认不开启，关闭时只按测头分组。勾选设置窗口中的 `Mark` 后打开 `Marks…`：每个量测组最多一个 Mark，名称自由命名（不限于 POR 等固定取值），双击改名，`Add Mark` / `Delete Mark` 随时增删。第一个 Mark 是兜底组（列表中以 ✓ 标出），未显式分配的量测组自动归入它；保留两个 Mark 即可当二元分类（默认 Old / New），需要多元时继续添加。删除某个 Mark 后，原属它的量测组回到第一个 Mark。列表搜索框只筛选展示，`Assign Visible` 批量分配给搜索后可见的量测组；先点击首行，再按住 Shift 点击末行，将首行的 Mark 应用到整个可见区间。改名会同步更新 Order 表的 Mark / Group 筛选值。改变身份字段仅改变展示颗粒度，合并组不自动改写原记录。关闭 Mark 保留定义和分配，忽略 Mark 列筛选/排序，Mark × 测头组筛选合并到对应测头；重新开启恢复。旧 WKB 自动开启 Mark、保留原 Old/New 名称及标记，旧 Age 列筛选迁移为 Mark。
4. 三个表的列标题可右键筛选、升序或降序排序。它们共享同一行投影：Reference、Raw、TestFlag 永远同行移动，编辑、粘贴和撤销仍映射到源记录。向筛选视图追加记录前需清除筛选/排序。
5. 修改筛选、排序、测头名、Mark 名称/记录标记、分组顺序后，在设置窗口点击 `Apply` 应用。它只提交设置，不替代 `Group plots` 页自己的 `Draw selected`，也不会自动提交该页待绘制的框选；已绘制图仍立即排除不参与的记录。Match 始终使用配对原始数值拟合；显示排序不改变拟合顺序。数据值编辑在没有待应用设置时自动更新，未变化参数的图不会重建。
6. `Group plots`（原 `Group Match / Trend`）只选实际 Group、自定义合并 Group 及可选 Group × Wafer，不默认增加 All / Mark All。每个范围使用与 `All parameter plots` 相同的 Match / Trend / Bias / 可选 Bias % 图块，支持模块排序、内部图拖动和分隔条调整。标题标明 Group；晶圆范围标明完整 Wafer 身份，轴标签按宽度稀疏显示。分页选择绘制，可以导出当前页 PNG 或复制整页图。
7. `Groups → Manage groups…` 选择至少两个基础 Group，为合并范围命名。按原始记录身份去重取并集，独立拟合新 Card，不平均旧组系数；不改变原始 Group 和原表。合并定义不能嵌套，源组暂时无数据时保留定义且显示 inactive。
8. `Groups → Data selection…` 汇集 Order / Reference / Raw Data 全部列。搜索、数值/文本/取值筛选和排序只改变可见行；过滤是两级布尔矩阵：`Add row` 新建布尔组，条件在行内用 `AND / OR` 连接并先计算，行与行之间再用 `AND / OR` 连接，可表达 `(A OR B) AND C` 这类组合（同层内 AND 先于 OR）；行末 `+` 给该行加条件，`Edit` / `×` 修改或删除，编辑弹窗里的 `Remove filter` 也可单删，`Clear filters` 清空全部，矩阵随选择保存。`Use` 决定参与状态，点击整行切换，Shift 设置可见区间，支持 `Check Visible / Uncheck Visible`。`Apply` 提交、`Cancel` 丢弃本窗口草稿。已提交的 selection 在 Raw Data 整表替换或行数变化后保持：行身份仍匹配的按身份延续，其余按原行位置延续；仅当 selection 使用的列（过滤列或行身份列）不存在时，才在提示栏要求重新 selection。未勾选记录不参与拟合、统计及同源绘图，但完整源表保留，全部取消得到有效的空分析，不回退 All。新 Workbook 的表头筛选也只影响展示；旧 WKB 的已有筛选保持原分析范围，首次应用本窗口时转换为显式参与状态。

如果从提供的整张混合表导入，先复制含表头的数据，再用 `Import combined…` 明确指定每一列是 TestFlag、Reference、Raw Data 或 Ignore。同名参数的两个列必须分别指定；不通过数值猜测哪列是 Reference。整个导入完成前不改变原来的源表。

## 分类约束

- 默认包含 Wafer ID；Lot ID / PAD Name 只有在整表包含多个非空值时默认加入。用户可以单独勾选/取消这些字段，也可以选择其他可用身份字段。
- 按所选字段的完整元组合并，去除首尾空格，大小写不自动合并，非连续出现的同一元组仍是一组。
- GUI **不启用 Die Seq 重复/重启拆组**。重复的 Die Seq 不构成另一片晶圆的自动证据。
- 缺失主身份字段的记录以 `Identity pending` 单独展示，不静默丢弃。
- 勾选标记绑定源记录身份及重复记录序号，不绑定列表位置、显示名称或当前分组方式。
- Preview/Final 只有逐条身份及顺序一致时共享 TestFlag/Mark；仅行数一样不够。独立修改的子窗口不依 Wafer ID 猜测继承分类。

## 绘图与 Card

开启 Mark 时，Trend 按 Mark 的排列顺序再按测头分类（兜底 Mark 在最前，名称可编辑，旧文件为 Old/New）；关闭时只按测头分类。各类别内优先沿用 0、1、-1 的已有顺序，其余实际 Flag 按首次出现顺序排列，空白最后。空组不占 X 空间；可拖动修改组顺序，也可选择当前表顺序或原始行顺序。

多片晶圆按测量位置沿连续序号 X 轴拼接，刻度仍标实际 Die Seq，组/晶圆标签独立占一行，边界明确标出。不同 Mark/head 类别不连接成一条不加区分的曲线；同组相邻晶圆仍衔接。缺失数值形成断点，不补零、不插值。

`All parameter plots` 分组模式中，Trend、Bias、Bias % 按同一分组顺序显示配对记录，横坐标只显示 Group 和稀疏的实际 Die Seq，不堆叠 Wafer ID / PAD / Lot 标签。刻度随窗口宽度和缩放自动调整，组名占独立的两行，空间不足时减少显示数量；完整组名保留在轴提示中。仅绘制组边界，不绘制每片 wafer 的密集边界线。Reference 曲线置于 Raw/Card 曲线上层，避免被覆盖。`Group plots` 显示稀疏 Group / Wafer 标签，细灰色 Wafer 分界与粗黑色 Group 分界；Trend / Bias 不连接相邻不同 Wafer。两页保留原有横轴紧贴全数据范围的 Auto 规则。

`Use group Card` 位于 **`Group plots` 页**，不再位于 Group settings。`All parameter plots` 的 Trend 勾选 Card 后始终使用当前参与记录的整体 Match Card，不使用各组的独立 Card；取消勾选仍显示原始值，Preview 默认勾选、Final 默认不勾选的原有规则不变。

| Group plots 的 Trend Card | Use group Card | 分组 Trend Raw 曲线 |
| --- | --- | --- |
| 关闭 | 任意 | 原始值 |
| 开启 | 关闭 | 对应参数 All parameter plots 的整体 Card |
| 开启 | 开启 | 当前显示范围的独立 Card；合并 Group 为源记录并集的新 Card |

Match 图的点始终是未校准配对，拟合线始终来自当前显示范围，不受 Card 来源开关改变。分组拟合不足两个有效不同 Raw 值时，显示 unavailable；分组 Card 留空，**不回退整体 Card**。Preview Bias 使用所选 Card 来源，Final Bias 仍使用 Raw − Reference，不受 Trend Card 是否开启影响。Final 分组 Trend 默认关闭 Card，用户可以明确开启。各参数的 Bias limit 和红色限值线沿用 Parameter mapping。

## 保存和导出

`.wkb` 保存完整源表、TestFlag、测头名字、Mark 开关及任意数量的自定义 Mark 名称、记录级 Mark 分配、分类字段、筛选/排序、Trend 顺序、Card 策略以及待应用/最后应用设置、已绘制/待绘制框选和分页状态。新增稳定参与记录 ID / 排除列表、合并 Group 定义、Group 图块布局及各块 Trend Card 开关。原表中编辑身份字段及撤销时参与 ID 不变。筛选不是删除记录。已有的保存、关闭提示及恢复草稿机制继续使用，不新增数据库或依赖。

Workbook 打开的 Correlation / Trend 使用同一分类；它的独立副本 `.wct` 带分类配置，重开不依赖原 Workbook 的路径。

关联 Map / Radius、Correlation / Trend 和 Dynamic 在 Data 菜单里选择数据来源：`Match Workbook selection`（默认，窗口表就是 selection 之后的记录）或 `Full data (before selection)`（selection 之前的完整复制）；切换按当前 Workbook 数据重建子表，已有独立修改时先确认。子窗口还能用自己的 `Data selection…` 追加行选择，只影响该窗口的绘图/统计，右上角徽标显示 `N ROWS / M COLUMNS · X ROWS USED`。独立导入不同文件来源的同名 Wafer 不会仅因名称相同被排除；没有足够身份字段时不按行号猜测继承。TEM 独立 Map / Dynamic 保持独立输入，参与选择仅作用于配对分析及同源 Correlation / Trend。

Excel 导出保留原源表，并增加 `Order`、`Group Fits`、`AllTrend` 和各非空组合的 Trend 数据页。数据页同时明确列出 Raw、整体 Card Value、Group Card Value，避免把变换后的数据伪装成原始值。文件中身份键/Flag 不使用用户命名作为唯一标识。

## 验证

`python run_tests.py tests.test_match_groups` 覆盖：三表配对和排序编辑/撤销、非法/空白 Flag、New 合并半选、分组系数与无回退、Preview/Final 身份不一致、待应用设置和完整源表保存恢复、子窗口独立副本、PNG/Excel 导出和未变化图复用。交付还运行全量测试与 `main.py --self-test`。

`benchmarks/benchmark_match_groups.py` 使用隔离的设置目录，可重复测量完整重建与仅受影响图更新，也可输出应用字体及真实浅/深色主题的截图。`--table` 是所提供粘贴表的专用验证入口，明确指定第 17 列为 Reference、第 18 列为 Raw，不是通用的自动列猜测。

`benchmarks/verify_group_plots_ui.py <输出目录>` 在独立临时设置中生成 Group plots、Data selection 的浅/深色和窄窗口截图，验证 Dynamic 同源排除及不同文件来源保护，不修改用户设置和正式数据。
