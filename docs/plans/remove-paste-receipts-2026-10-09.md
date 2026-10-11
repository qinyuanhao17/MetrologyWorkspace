# 第五项：移除表格粘贴提示条

按用户截图及请求，删除窗口中粘贴后的确认提示条，包括 `No changes` 和 `Paste complete`。

## 范围

- 从 Match Workbook Raw Data 卡片和通用 Data 页布局删除提示条创建及引用。
- Correlation and Trend、Wafer Map、Dynamic 复用通用 Data 页，均不再出现这些提示条。
- Reference、Order、参数映射及只读结果表没有单独创建这类提示条，未添加新的提示。
- 不改内部临时粘贴差异记录或单元格 tooltip，不改保存数据、撤销历史和粘贴后的原生选区。
  复制/剪切虚线以及重复列名、越界等必要验证提示保留。
- 未删除可单独测试的旧提示组件定义；软件窗口已无实例化调用。
  本轮按 ponytail 只移除用户可见提示层，不扩大到数据记录或接口清理。

## 最小验证

按 tdd 先将两项窗口粘贴用例改为断言不存在确认提示：旧实现均失败，移除布局创建后通过。
另验证 Correlation 的 Ref / Raw 及 Dynamic 的实际表格粘贴、相同值重复粘贴、选区和撤销。

合计 **8 项通过，0.657 秒**，包括：

- Match Workbook Preview / Final，通用 Wafer Map Data 页、Correlation、Dynamic；
- 工具栏整表粘贴和单元格粘贴，无变化粘贴静默；
- 精确字符串、撤销及保存重开；
- 复制虚线、单步剪切撤销、原生粘贴选区；
- 重复列名验证和自动重命名提示仍可使用。

命令及输出：`.cache/remove-paste-receipts/focused-tests.txt`。
设置、recovery、Matplotlib 缓存和临时文档均使用 scratch；用户设置哈希本轮前后相同。
未运行全量测试、性能基准或发布流程。本项本地修改及最小验证完成。
