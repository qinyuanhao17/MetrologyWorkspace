# Raw Data 粘贴、撤销与范围反馈

日期：2026-10-08；2026-10-09 按最新截图修订。保留所有既有未提交修改；没有提交、推送或重打 v3.0.0 tag。

## 用户可观察行为

- 删除 `Show changes` 和额外变化格着色，保留精确的粘贴摘要与 Before / After tooltip。
- Ctrl+C：复制当前范围的精确 TSV 字符串，外围显示绿色流动虚线。Esc 取消边框，不清空剪贴板或数据。
- Ctrl+X：按用户单独确认的方式，**复制成功后立即清空**来源格，作为一次可撤销的普通编辑。
  Ctrl+Z 在来源表恢复原值；不是“下一次粘贴成功后再移动”的待定剪切，不联动两个表的独立撤销历史。
- Ctrl+V / Ctrl+Shift+V：成功后使用表格原生选区显示完整粘贴矩形，**不再显示实线框或额外颜色**。
  相同值也选择范围并显示 No changes，不增加 Undo / revision；选区不限于实际变化的格。
- Ctrl+A：共享数据表只选择从列名行到最后一个非空值的矩形，不包含预留的空白行、列或空白尾行标记。
  矩形内部的空格保留；源文件中的空白记录仍照常保存，选择行为不删改它们。
- Raw Data、Reference、Order 的可编辑来源格、主窗口数据表和 Dynamic 实测格支持剪切。
  过滤 / 排序后的剪切按源行映射清空，隐藏行不受影响。
  混入只读格的剪切整体拒绝，避免只剪掉部分数据却让用户以为全部已移动。
- Summary、single-wafer metrics、participation、mapping 与 plot selector 的表格支持复制虚线，
  不允许整格剪切删除计算结果或配置控件；普通文本编辑器的原生剪切不受影响。
- 切换表模型、重新加载、修改值 / Undo 或替换剪贴板会清除相应复制框。
  隐藏视图时停止动画，重新显示再继续。选区反馈和 receipt 不进入 WKB、recovery 或导出数据。
- `Paste complete` 只表示源表已更新，**不表示数值结果或绘图已经完成**。

## 定位到的开销与最小修改

本轮先在冻结来源与只读 NOVA 夹具上复现 Ctrl+V / Ctrl+Z，然后做定向修改：

1. 连续键盘编辑原来每次同步做完整输入、分组、子窗口和分析更新。
   现在源格与 Undo 立即更新，昂贵的派生分析用 120 ms GUI-thread idle 合并；
   明确 Run / 导出仍读取最新数据，不复用过期计算结果。
2. 相同表结构的普通数值编辑无需重建名称相同的映射控件或重新解析不变的来源身份。
   身份复用仅在行数、列结构与全部身份输入精确一致时成立；有参与选择或旧状态迁移时保留原完整路径。
3. 模块私有的字符串 dataframe 缓存仅对已存在、非空的数据格做精确局部更新。
   header、空值 / whitespace、增长、替换、未知修改仍完整失效；对外 dataframe 始终是分离副本，
   pandas Copy-on-Write 开 / 关均验证。
4. Measurement 缓存仅保存有界的元数据解析结果，最多四份；不缓存测量值。
   Wafer ID / Lot ID / PAD Name / Die Seq 等所有相关输入变化均使解析结果失效。
5. Match 的 dirty 比较不重复构造一个完整验证后的 workbook；正式 Save / recovery 校验合同未放宽。
6. Group Trend 原来先创建大量 wafer 边界，再由 group axis 在首次绘制前全部删除。
   现在在确定 group axis 路径时跳过这些无效中间对象，最终原生边界和数据曲线保持不变。
7. 新范围边框只绘制最多四条**可见**边线，120 ms 动画只重绘 overlay，不遍历格、不发出模型 changed。
   粘贴范围从已知剪贴板矩形直接传递，避免为计算外框再次扫描 25 万个输入格。
   Ctrl+A 缓存 occupied extent，均匀可选模型的复制不展开 selectedIndexes。

`table_clipboard.py` 仅负责共享 TSV 与范围呈现；源字符串、编辑、Undo 仍归 `SheetModel`；
proxy 只翻译来源坐标，Dynamic 仍使用主数据表的既有 Undo。无新依赖、GPU、全局剪切事务或持久化状态。

## 可执行行为例子

BDD 例子落实在 `tests/test_table_clipboard.py` 和 `tests/test_paste_feedback.py`，不是仅写场景说明：

| 给定与操作 | 结果 |
| --- | --- |
| 两行来源值 `1.000`、`2.100`，复制 | TSV 保留字符串；外围虚线实际逐帧改变，数据 / Undo / revision 不变 |
| 同范围剪切并 Ctrl+Z | 复制先成功，两个值清空作为一次编辑；Undo 恢复完整 snapshot |
| 复制失败 / 混入只读 Order 格 | 不清空来源；不新增编辑 |
| 过滤行按 3、1 排序再剪切 | 只清空源行 3、1；源行 2 和行映射保持，Undo 全量还原 |
| 粘贴与原值完全相同 | 原生选择完整矩形、No changes；不新增编辑或外框 |
| 一个内侧格变化，已知整表粘贴矩形 | 摘要仅计变化格，选区覆盖整个已粘贴矩形，无额外着色 |
| 含内部空格、尾部全空行列，Ctrl+A | 选择真实 occupied 矩形，内部空格保留，尾部及预留格不选 |
| Dynamic 剪切实测格 / 选择 3 Sigma | 剪切使用完整源字符串而非 .8g 显示值；走来源 Undo，3 Sigma 不被删除 |
| 8,000 × 33 整表复制与动画 | 均匀模型不构造逐格 selectedIndexes，动画不更改数据 |
| stage / model / 过滤变化与重载 | 不把旧坐标框贴到新来源；receipt 的源行字符串仍对应原记录 |

## 固定 NOVA 的重复测量

以下为 2026-10-08 的测量记录，不用旧数字替代当前验证。2026-10-09 最新简化 UI 的串行重复测量见
[续作验收](resumed-ui-2026-10-09.md#性能边界)，其中单步 Undo 的完整可见 P50 本次慢 64.55 ms，已如实记录。

只读夹具 `matching-analysis_nova_multi_param.wkb`：7,731 × 33，三组映射。
SHA256：`2e5c35c62af4b8b7ab917b1f46444db0538c87430cca43942805e3e89af7be18`。
整表从 A1 粘贴，仅 `AACut_TCDoff` 全列加 0.25，其他所有源字符串保留。
主窗口 All parameter plots 有九张实际可见图，不用隐藏图或占位框冒充绘制完成。

每份来源在独立进程运行，固定 1500 × 950、configure_fonts、独立 settings / recovery / MPL / temp；
测量区间不并发运行 full suite / 其他图形测试。每次 30 个 paste + 30 个 Undo，另做五次连续撤销。
“回调返回”“数值当前”“实际可见完整绘图完成”分开等候；10 ms heartbeat 记录最大事件循环间隔。
P95 使用 nearest-rank；单位 ms。

| 操作 | 回调 P50 前 → 后 | 数值当前 P50 前 → 后 | 可见图 P50 前 → 后 | 可见图 P95 前 → 后 |
| --- | ---: | ---: | ---: | ---: |
| 整表粘贴、一列改变 | 471.00 → 262.10 | 1017.35 → 694.25 | 1128.93 → 804.97 | 1184.01 → 861.44 |
| Ctrl+Z | 202.86 → 43.22 | 913.94 → 683.42 | 1016.17 → 792.35 | 1107.46 → 865.36 |
| 连续五次 Ctrl+Z（单次 burst） | 4007.73 → 201.86 | 4007.73 → 494.52 | 4146.63 → 699.97 | 单次，不估计 P95 |

本进程中第一次粘贴的回调 / 数值 / 可见完成：444.81 / 1006.65 / 1112.46 → 264.82 / 672.31 / 787.40。
第一次 Undo：200.20 / 984.03 / 1098.48 → 40.53 / 678.58 / 801.42。
**这是 WKB 已打开并完整显示后的首次操作，不是首次 WKB 读取或冷启动指标。**
本轮没有重新宣称 WKB 启动、全部子窗口首次打开或长期原生 Windows 帧率已达标。

最早两次冻结来源测量的连续五次 Undo 可见完成是 4025 / 4019 ms；
不同时间的当前来源曾测得 618～909 ms，存在机器负载波动。上表使用本轮新 sandbox 中重新测量的
冻结来源 `nova-baseline.txt` 和加入新范围反馈并去掉重复矩形扫描的 `nova-final.txt`，
不选用最小耗时记录来宣称提速。
每次 Undo 逐格比较整个来源 dataframe，全部 summary 拟合结果还原；夹具 hash 不变。
回调返回后仍有数百 ms 派生更新，不能称所有控件已经“零延迟”。

复现入口：`benchmarks/benchmark_raw_paste_undo.py --code-root <current-or-frozen> --scratch <scratch> --wkb <readonly-fixture> --kind column --count 30 --burst`。
当前日志在 `.cache/raw-clipboard-audit/`；早期冻结来源与日志位于只读 `raw-undo-audit` scratch。
正式设置 `config/settings.yaml` 的本轮原始 hash 为
`56932a7d139e1d4a792ae973e11b96ca58c6011872a72edbc88735cd6de8ed37`，与上轮文档旧 hash 不同，不覆盖用户的新设置。

## 绘图保真与验证状态

曾尝试把普通 wafer 边界合成一个渲染 item；1x 看似相同，但实际 Group Trend 的 150% 像素比较不一致，
该实验已撤回。保留的改动只跳过首次 paint 前必然删除的对象，不改普通 wafer 的原生边界渲染。
冻结来源 / 当前 Group Trend 在 1x、1.5x，group-only 开 / 关、全视图 / 缩放视图比较一致；
完整曲线数组、边界、zoom 和 source 等价。
此前 light / dark 截图验证属于旧反馈 UI；2026-10-09 的当前 UI 已取消琥珀色与实线框，不能沿用旧截图作新 UI 证据。

技能影响：tdd 先留下失败的剪切、范围与 Ctrl+A 例子；bdd 将用户确认的剪切时机和只读边界转为可执行例子；
codebase-design / ponytail 复用既有 Qt history，仅提取共享呈现。scientific-visualization 的保真要求
导致撤回不等价的边界合并实验，而不是降低像素 / 数值验证要求。
方法参考：Timothy Kassis、Vinayak Agarwal、Yuhuan He、Darshil Patel、Aubrey M. Brueckner，
2026，[*Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*](https://arxiv.org/abs/2609.00065)，
[DOI 10.48550/arXiv.2609.00065](https://doi.org/10.48550/arXiv.2609.00065)。

2026-10-09 定向验证：clipboard / paste feedback / Dynamic 55 项通过；包含新 metadata / parameter filter / Correlation / hover 的 95 项通过。
2026-10-08 最新全量为 568 项、565 通过、2 失败、1 错误（284.027 s），不是全通过。
2026-10-09 续作的最终全量与最新 UI 复测见 [续作验收](resumed-ui-2026-10-09.md)。
最终隔离到本机非同步临时目录后的完整 `python run_tests.py`：**581 项全通过，246.807 s**。
之前 OneDrive scratch 的一次原子替换 WinError 5 与动画固定睡眠问题均保留日志、分别记录，不抹去失败历史。
此前本轮 555 项全量是 550 通过、5 失败（459.011 s），不是全通过：KLA view scroll 的上下文问题，
wide Trend 首绘、recovery check、dirty check、Wafer Map 打开耗时超预算。
后三个重负载目标中的 wide Trend、recovery 和 Map 也在冻结来源独立复测中超预算；
KLA view 与 dirty 独立复测通过，不能因此声称全量上下文问题已经消失。
新连续 Undo 的 650 ms 门槛曾在一次针对性运行测得 661 ms；预算未放宽，最新针对性通过但仍应视为边缘风险。
