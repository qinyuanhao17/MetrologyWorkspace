# 参数按钮换行与清空同步

按用户要求，只处理 Correlation / Trend 的参数导航栏，并做最小相关测试。
不运行全量测试、性能基准或发布流程。

## 修改范围

- 按钮根据窗口可用宽度自动换行，允许第二、第三行及更多行；放宽窗口后重新合并。
  复用原有按钮和参数筛选接口，不因窗口宽度变化重新拟合或重建曲线。
- 清空来源或没有可绘制选择时，立即隐藏并移除旧参数按钮及 ALL。
  旧按钮的延迟点击不会重新启用已清除的参数。
- 只删除部分参数时移除失效名称，保留仍有效的筛选；清空后重新绘制从 ALL 开始。
- 未修改源字符串、行映射、拟合、坐标缩放及导出语义。

使用 Qt 的 height-for-width 布局协商实现换行，参考
[Qt 官方 Flow Layout 示例](https://doc.qt.io/qt-6/qtwidgets-layouts-flowlayout-example.html)。
未增加依赖或固定行数限制。

## 验证

先增加失败测试：旧实现只能单行滚动；清空来源后 Correlation 和 Trend 均残留参数名称。
修改后新增用例验证窄窗口至少三行、宽窗口收为一行、筛选保留、全部清空及部分删除。

最小回归：

```text
python run_tests.py tests.test_parameter_filter tests.test_workbook_copy_data -v
Ran 13 tests in 3.530s
OK
```

包括原有图形复用、缩放、完整曲线值、筛选导出及 Copy from WKB 清空/重复制工作流。
另以 `QT_SCALE_FACTOR=1.5` 运行换行用例，1 项通过。耗时仅为测试记录，不是性能改善证据。

记录位于 `.cache/parameter-filter-wrap/focused-tests.txt`。
截图 `.cache/parameter-filter-wrap/wrapping-after.png` 来自实际 Qt 控件示例，
使用截图中的参数名称，不是完整 NOVA 数据窗口。截图与测试使用 scratch 设置和恢复路径。
检查发现用户设置文件时间戳及哈希与先前记录不同；未回退或覆盖该文件，也不据此断言变化来源。
原始桌面 NOVA WKB 未改写。

## 状态

本地源码已完成本项修改与最小验证；未运行全量或延迟检查，未提交或推送。
