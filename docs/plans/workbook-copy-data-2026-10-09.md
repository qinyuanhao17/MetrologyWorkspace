# 第一个任务：来源清空与 Copy from WKB

按 2026-10-09 的用户要求，本轮不做性能优化、不跑全量测试。后续全量及延迟检查等待另行指示。

## 行为与范围

- 删除全部 Ref 时，不再要求空 Ref 与 Raw 等长；当前 Select maps 移除 Reference，Raw 仍能绘制。
- Correlation and Trend / Wafer Map 的 Data 菜单新增一个原生勾选项 `Copy from WKB`。
  Correlation 的这一个选择同时控制 Ref / Raw，不分别控制两个来源。
- 有可用的父 WKB 来源时初始勾选；取消只清空子窗口，不改变父表，也不接受/保存草稿。
  手动 Ctrl+V 之后仍可绘制，父刷新不会自行把已关闭的复制模式填回。
- 重新勾选复制当前 WKB 来源；对刚重建的来源恢复默认参数选择，不沿用删除后的空选择。
  替换已有手动数据仍需确认，取消则保留数据和未勾选状态；空输入无需覆盖确认。
- 选择随分析 UI 状态保存恢复。复用已有父子草稿、来源复制和绘图计划机制，未改变拟合/插值。
- 无关联 WKB 时复制项禁用；既有 TEM 独立 Map / Dynamic 的禁止自动覆盖规则保留。

## 最小验证

先复现 Ctrl+A / Delete 删除 Ref 后的 `Reference and Raw Data must have the same row count`。
用失败用例驱动来源过滤及勾选项实现；另一个失败用例验证重复制不能留下空 Reference 选择。
新增四个工作流测试覆盖删除、真实 Ctrl+V 后绘图、取消覆盖、保存/父刷新/重开及复制最新值。
额外只运行六个直接相关的来源绘图/复制确认/TEM 安全回归。

结果：**10 项通过，3.741 秒**，记录 `.cache/workbook-copy-data/focused-tests.txt`。
使用 workspace scratch 设置与恢复目录，不写用户设置或原桌面 WKB。没有运行全量、性能基准或发布流程。

## 用户补充：范围菜单可见性与 Copy 联动

- 关联 Wafer Map / Correlation 的 Data 菜单保留 Match Workbook selection 和 Full data，不因 TEM 的独立来源规则隐藏。
- 未 Copy 时两项均未勾选、禁用，仍可用本窗口 Data selection；手动来源不再套用父 Workbook 的排除行。
- 从未 Copy 状态重新复制时，先按 Workbook selection 取得来源行，再启用并勾选该范围。
  保存重开保持手动模式的取消/禁用状态。TEM 独立 Map 的禁止覆盖合同未改变。
- 固定菜单状态的失败用例后修正；另一次相关回归发现屏蔽 QAction 状态信号会让互斥组失步，
  改为让互斥组正常接收状态变化，程序化设置不会触发用户的范围重载。
- 最小复测：**11 项通过，9.533 秒**，记录 `.cache/workbook-copy-data/menu-scope-tests.txt`。
  包含复制/手动行范围、取消、保存重开、TEM 保护和 Full/selected 切换；未跑全量或性能基准。
