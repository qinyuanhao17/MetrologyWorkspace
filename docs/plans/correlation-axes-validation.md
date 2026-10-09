# Correlation：单图 X/Y 切换验收

2026-10-09。按用户确认，每张图独立切换；完成本地验证后，用户另行授权按 v3.0.2 推送源码与新标签，不移动已发布标签。

## 行为

- 每张 Correlation 图标题右侧有 `Swap X/Y`，再次点击恢复原方向。
- 复用同一图的 Qt widget 与曲线对象，只重新拟合该图的同一批配对观测；其他图的控件、曲线和缩放不变。
- 交换后重新做“新 Y 对新 X”的带截距普通最小二乘拟合，不把原斜率取倒数；保留现有 lmfit 算法、有限值规则和所有选中行。
- Reference / Raw Data 分别记住方向；参数筛选、页切换、更新数据和参数顺序变化不丢用户指定的轴名。
- 坐标标签、标题、拟合线、PNG 导出及 Copy PNG 使用同一方向。复制 PNG 不带 `Swap X/Y` 控件，复制后恢复控件。
- 方向作为文档 UI 状态随 WKB / WCT 保存与恢复，改变方向会标记未保存；旧文件缺字段时维持默认方向。
- Pending Draw 的保存状态仍不自动绘制；用户再点击 Draw selected 时使用已存方向。

## 可执行例子

`tests/test_correlation_axes.py` 的六项工作流验证通过；已有 Correlation 与 parameter filter 的组合验证 66 项通过。

| 给定 / 操作 | 用户可见结果 |
| --- | --- |
| X=1,2,3,4，Y=1,2,2,5，并混入两条非配对数值记录 | 正向斜率 1.2；交换后斜率 2/3、截距 5/6、R²=0.8，仍只有同四对观测 |
| 三张图只切换 CD/Depth | 目标图轴与拟合线改变，其他图的 widget/zoom 保留，源 dataframe 不变；再切换恢复 |
| Reference / Raw 轴名相同，仅切换 Reference，正式保存与重开 | Raw 方向不变；Reference 方向恢复；源字符串、Die 与完整表不变 |
| 已切换的参数隐藏再恢复；更新量测并重排参数 | 用指定的新 X 轴和最新数值拟合，无旧数组缓存 |
| Copy PNG | 真实图像中没有按钮颜色像素，界面控件随后恢复 |
| 存着方向但选择尚未 Draw | 重开仍 Pending Draw，明确绘制后才显示已存方向 |

## 实际 NOVA 图与响应

只读 `matching-analysis_nova_multi_param.wkb`：7,731 原始行，六张实际 Correlation 图，窗口 1740×1040。
为完整展示六组配对，在本次演示子稿中将 Min R² 设为 0；不保存回原 WKB，也不把低 R² 关系当成显著结果。
第 1 张 Reference 图从 X=`AACut_TCDoff_Reference` / Y=`CutDeponFin_Reference` 换为反方向，另外五张图不变。

`benchmarks/verify_correlation_axes_ui.py` 读取固定夹具，检查完整源 frame、其他 widget / view、导出标签与原文件哈希。
21 次切换分别记录首次和其后 20 次热态；不是与不存在的旧功能做速度对照，也不是冷启动/原生 Windows 帧率保证。

| Qt 缩放 | 首次回调 / 完整 viewport 绘制 ms | 热态回调 / 绘制 P50 ms |
| --- | ---: | ---: |
| 100% | 15.34 / 33.94 | 14.19 / 29.28 |
| 150% | 15.64 / 39.68 | 14.21 / 35.14 |

真实 Qt 窗口与单图截图：`.cache/correlation-axes/ui-final-1x/`、`ui-final-150/` 中的
`correlation-before.png`、`correlation-after.png`、`panel-before.png`、`panel-after.png`。
Source 保真、其余视图和导出方向检查均通过；未覆盖帧率长期运行、所有硬件或每种极端数值尺度。

## 完整回归

首次完整 `python run_tests.py`：587 项，586 通过，1 项错误，253.427 秒。
错误出在新增测试的窗口清理：直接 `deleteLater()` 绕过正常关闭，让四个已删除 Qt timer 的测试文档仍留在 registry，
后续设置测试更新 recovery 周期时访问失效 timer。单独运行六项新测试后显式处理 DeferredDelete，
可重复复现同一错误；改为按正常关闭流程清理后 registry 为 0，六项通过（1.027 秒），设置更新正常。
仅修正测试夹具，不用生产代码的异常捕获掩盖问题，也不改变 recovery 行为。

修正后完整 `python run_tests.py`：**587 项全部通过，252.610 秒**。
运行记录：`.cache/correlation-axes/full-tests-final.txt`。覆盖原有保存/恢复、数据编辑/撤销、绘图/导出及性能门槛；
不是仅跑新增功能。最终 `git diff --check` 无空白错误。
不写用户 `config/settings.yaml` 或桌面 WKB，不放宽已有性能预算、存储 revision/锁/原子替换保护。

## 方法

tdd/bdd 把用户确认的逐图切换、反向拟合、文档恢复和 Pending Draw 写成可执行例子，先留下失败再最小实现。
codebase-design/ponytail 复用原拟合模块、页面缓存与文档 UI 状态，不新增依赖或改保存格式。
statistical-analysis/scientific-visualization/matplotlib 要求配对观测不变、反向拟合而非倒数、静态与交互图一致。
软件方法参考：Kassis, T., Agarwal, V., He, Y., Patel, D., Brueckner, A. M. (2026),
[*Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*](https://arxiv.org/abs/2609.00065),
[doi:10.48550/arXiv.2609.00065](https://doi.org/10.48550/arXiv.2609.00065)。数值和时间依据本地执行记录，非该论文。
