# Metrology Workspace

编辑量测数据、按 Reference 拟合 PMISH，并在可保存的工作文档中呈现量测结果。
源记录和参与分析的记录是不同概念，未参与的记录仍属于文档。

## Language

**Match Workbook**:
含 Reference、Raw Data、参数映射、分组设置及关联分析草稿的文档。
_Avoid_: Excel workbook（除非确实指 Excel 文件）

**Reference**:
用于拟合和比较的基准量测表；Match type 表示 KLA、NOVA 或 TEM。

**Raw Data**:
保留原始字符串和行序的 PMISH 量测表；Preview 和 Final 可以使用各自的源表。
_Avoid_: 已校准数据

**Parameter mapping**:
一个分析参数与一个 Reference 列和一个 Raw Data 列之间的显式对应。

**Card**:
从参与分析的配对量测拟合得到的斜率、截距及拟合质量。
Group Card 使用该 Group 的记录拟合；整体 Card 使用全部参与记录拟合。

**Measurement set**:
由选定的 Wafer、Lot、PAD 身份区分的一组源记录；不等同于仅按 Wafer ID 合并。

**Head**:
启用 Head groups 时由保留的 TestFlag 映射得到的分类名称。

**Mark**:
用户定义的量测分类；可独立于 Head 启用。
_Avoid_: Age、New/Old（除非确实指这两个自定义名称）

**Group**:
由当前启用的 Head 和 Mark 分类得到的分析范围。
Combined Group 是多个基础 Group 的记录并集，同一记录只参与一次。

**Data selection**:
源记录参与分析的选择；取消参与不删除源数据，也不同于只改变可见行的筛选。

**Participation identity**:
参与选择中保存的一条记录的身份，与可编辑的 Wafer/Lot/PAD 值和显示顺序分开。
原位置的单元格编辑不转移其他记录的参与状态；整表替换则需要明确的身份对应。

**Draft**:
尚未接受为正式保存基准的数据或设置；关联分析的草稿有明确的父文档归属。
