# 暂停与续作清单：2026-10-09 00:45

> 2026-10-09 已按用户“继续未完成的”手动恢复。以下保留暂停现场，不是当前实施状态。
> 截图六项与续作测试/性能的当前状态见 [续作验收](resumed-ui-2026-10-09.md)。

用户在 2026-10-08 晚明确要求暂停所有当前与排队工作，并于 **2026-10-09 00:45 Asia/Shanghai**
在当前对话恢复未完成任务。恢复时不要重新从零开始，也不要漏掉截图里的排队项。
00:45 前只保存暂停记录和安排续作，不继续实现、修复或启动新测试。期间收到旧排队需求也先暂存。

## 暂停现场

- 没有活跃子代理；应用列出的其他会话是 idle / notLoaded，没有其他活跃会话。
- 当前全量进程在停止请求到达时已经完成，session 52924 已收取最终结果；不再启动测试或 benchmark。
- 最新 `python run_tests.py`：**568 项，565 通过、2 失败、1 错误，284.027 秒**。
  日志 `.cache/raw-clipboard-audit/full-tests.txt`。不是全通过。
- 剪贴板 / paste feedback / Dynamic 针对性 54 项通过，性能针对性 6 项通过。
- 当前修改未提交。保留所有既有工作，不 reset / checkout，不覆盖用户设置与原桌面 WKB。
- `raw-data-paste-undo-responsiveness.md` 写于最新全量结束前，末尾仍标“正在运行”；
  以本清单和实际 full-tests.txt 为最新状态，恢复时更新报告，不能沿用旧成功结论。

## 建议恢复顺序（可由用户调整）

### 1. 数据安全及本轮回归收尾（先做）

- 调查 `test_match_recovery_saves_to_original_not_the_previously_open_file`：预期保存原来源，实际返回 None。
  尚未隔离复现或确定根因；不要擅自归为环境问题。保留 Save / Discard / Cancel、锁、backup、revision、原子替换合同。
- 调查新 `test_copy_animates_the_range_without_editing_and_escape_cancels_only_feedback`：
  针对性通过，但全量上下文中两帧相等；区分真实动画故障与测试时机 / 全局 Qt 状态，不放宽验证冒充修复。
- `test_copy_cannot_overwrite_owner_or_samefile_alias` 在 `os.link` 出现 WinError 5。
  先判断环境权限与代码回归，不移除 samefile / alias 保护或跳过安全测试作全绿结论。
- **Dynamic 剪切精度风险待验证**：当前 Dynamic copy 读取 `.8g` 的显示值，剪切后再粘贴可能截断来源字符串。
  尚未新增精度回归或实现修复。测试带高精度、尾零的实测字符串；剪切必须保留精确来源值，3 Sigma 不可删。

### 2. 剪贴板与选择 UI 按最新要求定稿

已实现但未最终交付：

- 去掉 Show changes。
- Ctrl+C / Ctrl+X 显示绿色流动虚线；Esc 取消边框。
- 用户已选定 **Ctrl+X 复制成功后立即清空，可在来源表 Ctrl+Z 撤销**，不是待粘贴后移动。
- Raw Data、Reference、Order 可编辑来源格、主窗口数据表与 Dynamic 实测格接入剪切。
  结果和配置表可以复制，但不得用整格 Ctrl+X 删除计算结果或 checkbox / combobox 设置。
- Ctrl+V / Ctrl+Shift+V 选择完整已粘贴矩形并显示实线外框；完全相同的值也标范围，无新增编辑。
- Ctrl+A 仅已有数据矩形（含列名行），不选预留 / 尾部空白；保留内部空格和文件中的空白记录。
- 当前还有粘贴摘要、琥珀色差异格和 Before / After。

截图第二项队列的原文可见部分是：
“control V后类似这种control A显示即可这样我就能判断是否有粘贴成功不用加颜…”
因此 **用户追加的简化要求尚未落实**：恢复时读完整排队原文 / 图片，核对是否去掉额外着色与提示。
不能把当前琥珀高亮和摘要继续保留当成最终确认；若无法获取截断部分，问具体缺失细节，不自行补写。

### 3. 继续 Ctrl+V / Ctrl+Z 刷新延迟与一致性验证

原“Ctrl+A / Ctrl+Z”已被用户纠正为 **Ctrl+V / Ctrl+Z**，不要误读截图旧句。
最新固定 NOVA 7,731 × 33、三参数测量（独立进程、完整九图）：

- Paste 回调 P50 471.00 → 262.10 ms；完整可见 P50 1128.93 → 804.97 ms。
- Undo 回调 P50 202.86 → 43.22 ms；完整可见 P50 1016.17 → 792.35 ms。
- 五次连续 Undo 的完整可见完成 4146.63 → 699.97 ms（单次 burst，不作为 P95）。
- 数值当前与可见完成分别等待；全部源字符串 / Undo 后完整 summary 一致，原文件 hash 不变。
- 回调之后仍有数百 ms 工作，不宣称零延迟。650 ms 合成 Undo 门槛曾在一次针对性运行测得 661 ms；预算未放宽。

日志：`.cache/raw-clipboard-audit/nova-baseline.txt`、`nova-final.txt`；
复现：`benchmarks/benchmark_raw_paste_undo.py`。

### 4. 排队项：Correlation / Trend、Wafer Map 的 metadata

截图队列原文可见部分：
“correlation and trend和wafer map里面的metadata可以上锁放在表格右侧吧，这…”

**未开始实现**。登记目标：metadata 放在表格右侧，并支持固定 / 锁定；
恢复时获取完整原文以确认布局和“锁定”的具体含义，不猜测未显示的后半句。

### 5. 排队项：Wafer Map 测量点悬停

截图队列原文：“wafermap上面的黑点把鼠标放上去的时候能不能显示Die”。
**未开始实现**。测量点 hover 显示对应 Die，保持真实源行 / Die 映射，不把插值像素当作实测点。

### 6. 仍未完成的性能主线

先读 `control-responsiveness-optimization.md`、`control-responsiveness-results.md` 与最新 Raw Data 报告。
不重复交付已经验证过的部分；继续覆盖 WKB 首次读取 / 保存视图恢复、Preview / Final 首次切换、
Correlation / Trend / Wafer Map 首次打开与首次完整绘制、Group setting Apply、相关 checkbox 与滚轮。
冷态使用独立进程，热态单独记录，区分回调返回、当前数值、完整可见图；不拿占位或隐藏图作完成证据。

文档级 latest-only 后台输入 / 分析、非阻塞首开与子窗恢复、首次 stage 构建、Map 渲染隔离、
后台正式 Save 和原生 Windows 长会话验证仍未完成。不能只凭本轮某次全量性能项通过宣称这些架构阶段完成。
recovery 周期设置已有前期实现，应核对现状，不重复另建调度；关注其频繁检查和保存原路径回归。

## 恢复约束

- 遵守 AGENTS.md；明确使用用户已请求的 python-performance-optimization、diagnosing-bugs、systematic-debugging，
  以及在 allowlist 内适用的 tdd / bdd 等技能，先读完整指令再行动。
- 使用 `C:/Users/Yuanhao Qin/.conda/envs/metrology-workspace/python.exe`。
- 新测试设置 / recovery / MPL / tempfile 均指向 scratch，不写 `config/settings.yaml`，不改原桌面 WKB。
- 修改必须有根因证据，保持全部源字符串、行映射、数值、导出、view 与存储安全语义。
- 先相关测试，最终完整 `python run_tests.py`，不放宽预算，如实记录未达标和未完成。
- 本轮不自动提交、打包、推送、发布或再次移动 v3.0.0 tag。
- 仅在实质进展、完成、失败或需要用户决定时通知；无变化保持安静。
- 单次续作安排，用后删除该安排，不再每天重复。
