# 第四项：打开 WKB 后的 Raw Data 与分析入口

本轮只调整输入编辑和入口可用性，沿用用户确认的打开 WKB、粘贴/更新 Raw Data及绘图入口验证范围。
不运行全量或性能测试，不提交或推送。

## 已修改

- 原先 `set_raw_frame` 拒绝先录入 Raw，`_update_state` 又按是否存在 Reference 禁用 Raw 编辑器。
  删除这两个顺序限制，Preview 和 Final 的 Raw 编辑器均可编辑、粘贴及撤销。
- 完整配对数据的 WKB 草稿即使还没有分析结果，Wafer Map / Radius 和 Dynamic 按钮也可使用；
  原有打开动作按需分析，不必先手动 Run analysis。Correlation and Trend 原先的完整输入入口继续可用。
- Run analysis 的完整配对、映射及输入错误检查保留。
  Raw-only 草稿仍不能运行匹配；补上 Reference 后可以正常分析。
- 不修改 Dynamic 的独立输入合同、TEM 的独立来源保护，或保存/取消流程。

## 待用户确认

用户后续已确认：Reference 为空或 Ref/Raw 行数不一致也允许三个入口打开、手动贴数据。
该补充及空列误判、参数映射加/减的实现与最小验证见
[2026-10-10 编辑控件修订](workbook-editing-controls-2026-10-10.md)。下面的 9 项记录是较早阶段的验证，不作为新边界的通过证明。

## 最小验证

按 tdd 先增加失败用例，捕获 Raw-before-Reference 异常及未分析草稿的 Dynamic 按钮禁用。
用 ponytail 保留既有编辑器、撤销历史和子窗口打开流程，只改上述限制。

新增用例验证：

- Raw-only WKB 打开后真实 Ctrl+V / Ctrl+Z，精确字符串恢复，原文件未被隐式写入；
- Raw 后补 Reference，已知数据计算 slope = 2；
- Final Raw-only WKB 打开、单元格编辑和撤销，不改 Preview 表；
- 完整未分析草稿实际打开 Correlation and Trend、Dynamic、Wafer Map 三个子窗口。

另运行六个直接相关的打开、输入可编辑、缺少 Final、Correlation 来源和 Dynamic 独立输入回归。
合计 **9 项通过，3.279 秒**，记录 `.cache/workbook-ready-controls/focused-tests.txt`。
设置、recovery、Matplotlib 缓存及临时 WKB 均在 scratch；用户设置哈希本轮前后相同。
