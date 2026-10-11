# Data 菜单控件与 WKB selection 恢复

本轮只修改用户指定的菜单 UI、重复命令及打开已有 WKB 时的数据范围，不做全量测试、性能优化或推送。

## 修改

- 菜单使用现有 Qt 原生 QAction / QActionGroup，不另建控件或依赖。
  浅色及深色主题均将选择标识放到文字右侧：复选项为方框带勾，互斥单选项为圆形。
  保留整行点击、Enter 激活与互斥语义。
- Correlation and Trend、Wafer Map 的 File 菜单移除 `Use Workbook Data…`；
  统一使用 Data 中的 `Copy from WKB`。Dynamic 没有此复选项，保留其唯一的显式恢复命令。
- 新建关联子窗口时，先读取该范围保存的 `follow_workbook`，再决定是否按 WKB selection 取来源行。
  原来先截取来源、后恢复 Full data 状态，造成菜单与实际表格不一致。
- 恢复单选项时不阻断 QActionGroup 的状态同步，避免老 WKB 重开后的互斥选择失配。
  不触发用户复制/清除处理，不覆盖已保存的独立来源、锁定元数据或本地 Data selection。

## 真实文件验证

只读打开桌面 `matching-analysis_nova_testfilter1.wkb`：

- 原始 Raw / Reference 均为 7,731 行。
- 修改前：菜单 Full data，但 Map 表格只有 6,958 行。
- 修改后：Map 表格恢复 7,731 行；本地保存的 773 条排除仍生效，参与记录为 6,958 行。
  Full data 只取消父 WKB 的参与范围限制，不取消子窗口自己的 Data selection。
- 原始 WKB 和 `config/settings.yaml` 的 SHA256 在验证前后均不变。

## 限定验证

沿用 tdd 失败用例先行和 ponytail 原生样式/现有数据路径复用原则。
`tests.test_menu_controls`、`tests.test_workbook_copy_data` 及两个现有 selection 集成用例，
合计 **15 项通过，9.762 秒**。覆盖浅/深色实际像素、鼠标和键盘操作、重复菜单移除、
新旧 WKB 的 Full data 重开与往返切换、保留源字符串、本地排除、手动输入及锁定复制行为。

日志：`.cache/data-menu-controls/focused-tests.txt`。
原生截图：`.cache/data-menu-controls/data-menu-light.png`、`data-menu-dark.png`、`file-menu-light.png`。

## 再次核验与范围切换修正（2026-10-10）

用户再次报告 `nova_testfilter` 保存为 Full data 后仍使用 WKB selection 的问题。
两个桌面文件的初次 Map 打开均已正确加载 7,731 行，原加载次序修正仍有效。
但本轮往返切换发现：刷新截取后的来源表时，本地排除记录被按行位置重映射，
返回 Full data 会误排除其他记录；`testfilter1` 的参与行数从 6,958 错减到 6,345。

- 加强现有保存/重开集成测试，验证 Full data → WKB selection → Full data 后，
  仍只有原来的 die `002` 被排除；新旧 WKB 用例均先失败，再修复通过。
- 显式更换来源范围或 Copy 时保留已有参与身份，不对截取后的行位置做迁移；
  锁定元数据混合表仍走原有位置保护逻辑，普通父数据编辑的迁移行为不变。
- 桌面隔离副本验证通过：两个 Map 均打开/保存重开为 7,731 行；
  `testfilter` 本地 383 条排除仍对应 7,348 个参与行，`testfilter1` 本地 773 条排除
  仍对应 6,958 个参与行。Correlation 改为 Full data 后保存重开均为 7,731 行。
- 桌面原 WKB 与正式 `config/settings.yaml` 的 SHA256 均未变化。

本轮日志：`.cache/testfilter-scope-20261010/desktop-fixed.txt`、`scope-red.txt`。
初次较大范围测试有一项临时原子保存权限错误，非 OneDrive 隔离目录中单独复验通过；
没有修改原子保存保护。最终全量结果见同目录 `full-tests.txt`。
非 OneDrive 隔离环境最终 `python run_tests.py`：**645 项通过，264.200 秒**，
未出现已销毁 Qt 控件的异步异常。
