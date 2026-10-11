# 第七项：仅 Wafer Map 的 metadata 列使用锁图标

采用用户最新范围：只有 Wafer Map Data 表的 metadata 列名格右侧显示锁。
这份记录覆盖此前右侧 Metadata locks 面板、Correlation 锁和按名称追加锁定列的旧设计。

## 当前行为

- 点击图标切换：红色闭锁、绿色开锁；选中该列后 Ctrl+L 也可切换。
- 复用既有 metadata 名称识别，包括 Wafer ID、Die Seq、FIELD X/Y、X/Y、X(mm)/Y(mm) 等。
  测量参数列没有锁图标，Correlation、Dynamic、Match Workbook 表格也不启用该控件。
- 第四、第五列从 FIELD X/FIELD Y 改名为 X/Y 并锁定后，粘贴新表仍保护第四、第五列：
  保留 X/Y 列名及原始字符串，其他未锁列正常更新，不在右侧追加旧列。
- 范围粘贴、工具栏整表粘贴和 Ctrl+Shift+V 替换都遵守保护规则。
  锁定列不可直接编辑；后续交互修订允许剪切混合选区，复制整个选区而仅清空未锁单元格。
- 保留已有安全边界：锁定时不同数据行数、缺少锁定位置、重复列名会拒绝粘贴；先解锁再更改布局。
  不猜测 Die/Wafer join；明确打开文件仍是数据替换。后续交互修订将 Copy from WKB 也纳入锁保护。
- 锁状态随 Wafer Map 工作区保存、重开；旧 Correlation/Dynamic 的锁忽略，旧 Wafer Map 的非metadata锁忽略，
  避免移除控件后留下无法解除的只读列。锁变化仍参与未保存状态判断。
- Undo/Redo 恢复之前的 metadata 列名时，锁跟随该列位置；恢复为空或非metadata名称时释放锁，
  避免锁住预留空白格或出现没有图标的锁。新建空表清除不再存在的锁。

## 最小验证

按 tdd 先复现位置合并失败、锁点击缺失、旧保存状态中的不可见锁和列名撤销时锁丢失，再逐项修改。
沿用已有 SheetModel 粘贴/Undo、SheetView 交互和工作区 Save/Open 接口，不引入新的持久化格式或依赖。
bdd 的范围与边界示例落实为以下执行检查，不把文字说明当作通过证据：

- `tests.test_metadata_locks`：12 项，覆盖红/绿实际像素、点击/快捷键、测量列无图标、窗口范围、
  原位置列名/数值保护、撤销重做、精确字符串、拒绝形状变化、工具栏来源与分析一致、
  `.wmap` 实际保存重开、脏状态，以及旧文件锁的处理。
- `tests.test_table_clipboard`：3 个已有例子，复制动画、单步剪切撤销、粘贴原生选区。
- `tests.test_workbook_copy_data`：2 个已有例子，保存后手动模式保持、关闭 Copy 后 Workbook selection 的状态。

最终 **17 项全部通过，1.869 秒**。执行输出在 `.cache/header-metadata-locks/focused-tests.txt`。
实际 Qt 表格截图在 `.cache/header-metadata-locks/wafer-map-header-locks.png`：合成数据中 CD 更新为 9.100–9.400，
第四、第五列保留锁住的 X/Y 及 -6.000 等源字符串；截图不是绘图完成时间证明。
UI 使用原生 Qt delegate 绘制矢量锁，不给每个表格单元格创建按钮控件。

设置、recovery、临时工作区和 Matplotlib 缓存均显式使用 `.cache/header-metadata-locks` scratch。
用户配置本轮早先检测到既有变化，保留当前内容，未尝试覆盖回旧哈希；收窄范围期间和最终验证的哈希一致。
未写原始桌面 WKB；未运行全量测试、性能基准、打包或 GitHub 推送。
本项为本地实现和最小验证完成，不代表其余待确认任务或全项目验收已完成。

## UI 尺寸修订

按用户后续要求，锁的可见宽高各缩为原来 50%，绘制不透明度设为 50%。
保留原 20×20 的点击区域、红/绿状态、tooltip 和 Ctrl+L；不改变表格背景、文字或锁定合同。
按 tdd/ponytail 只修改已有 Qt delegate 的绘制变换，没有新增按钮或 UI 依赖。
实际像素检查先在原图标宽度 12 上失败，再通过半尺寸与半透明检查。
交互/绘制、实际保存重开、X/Y 原位置保护、窗口范围共 **4 项通过，0.419 秒**；未做全量或性能测试。
验证输出及实际 Qt 截图位于 `.cache/compact-metadata-locks`，只使用 scratch 配置。

锁与 Ctrl+X、Copy 开关及 selection 的最新合同和验证见
[锁定后的交互修复](locked-workbook-actions-2026-10-09.md)，覆盖本记录早先的混合剪切拒绝和 Copy 替换规则。
