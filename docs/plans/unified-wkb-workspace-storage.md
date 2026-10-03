# 方案：统一 WKB / SQLite 工作区存储

> 状态：已按用户授权在本地实现，代码验证见文末。新存储实现尚未上传 GitHub。
>
> 本文记录 Match Workbook、Wafer Map / Radius、Dynamic、Correlation and Trend
> 的统一存储模式。改动前的代码已冻结为 GitHub `dev5` 标签（`8370067`）。

> 后续设计：[文档归属、分类后缀与独立分析副本完整方案](workspace-storage-v2-design.md)。
> 后续方案已按用户授权在本地实施；本文保留第一阶段基线的历史记录，尤其是统一 `.wkb`
> 和子窗口整本 Save As 的旧行为。当前分类后缀、独立副本与分层恢复以新方案及 ADR 0003 为准。

## 1. 目标

1. Match Workbook 中打开的 Wafer Map / Radius、Dynamic、Correlation and Trend
   都保存到所属 `.wkb` 文件，不再把文档级状态只写入全局应用设置。
2. 主窗口独立打开的 Wafer Map、Dynamic、Correlation and Trend 使用 SQLite
   工作区文件保存；`Ctrl+S` 是保存当前工作区的快捷键。
3. CSV、XLSX、PNG、SVG、PDF 继续作为导入或导出格式，不承担工作区恢复职责。
4. 保留源测量字符串、列顺序、行顺序和现有参数映射语义。
5. 继续兼容现有 WKB schema 1–10；新容器的 `format_version=1` 与旧 schema 独立编号。

## 2. 推荐决策

所有可恢复工作区统一使用 `.wkb` 扩展名和 SQLite 容器，通过
`workspace_type` 区分文件内容：

- `match_workbook`
- `wafer_map`
- `dynamic`
- `correlation_trend`

使用同一个扩展名可以复用原子保存、最近文件、文件定位、错误处理和兼容逻辑。
打开文件时必须校验 `workspace_type`，不得把一种工作区静默当成另一种工作区载入。

不采用以下方案：

- 不为三个独立工具分别实现三套 SQLite 读写逻辑。
- 不把多个彼此独立的窗口强制放入一个全局会话数据库。
- 不序列化 Qt、Matplotlib、PyQtGraph 对象或 Python pickle。
- 不保存 PNG 作为可编辑工作区的真实来源。

## 3. 存储模块与 interface

新增一个深模块，例如 `metrology_app/workspace_store.py`。窗口只负责构建和恢复
`WorkspaceSnapshot`，不直接执行 SQL。

建议的小 interface：

```python
save_workspace(path, snapshot) -> Path
load_workspace(path, expected_type=None) -> WorkspaceSnapshot
```

`WorkspaceSnapshot` 至少包含：

```python
WorkspaceSnapshot(
    workspace_type: str,
    frames: dict[str, pandas.DataFrame],
    states: dict[str, dict],
)
```

模块内部负责：

- SQLite 表名映射与校验；
- DataFrame 精确写入和读取；
- JSON 状态版本化；
- 临时文件写入、提交、关闭连接后原子替换；
- 文件类型校验；
- 旧 WKB 迁移；
- 无效或损坏文件的统一错误信息。

窗口和测试通过同一个 interface 使用该模块，不在各窗口复制 SQLite 细节。

## 4. SQLite 结构

建议的公共表：

### `workspace_manifest`

| 字段 | 含义 |
| --- | --- |
| `format_version` | 通用容器格式版本 |
| `workspace_type` | 工作区类型 |
| `saved_utc` | 保存时间 |
| `application_version` | 可选的应用版本 |

### `workspace_state`

| 字段 | 含义 |
| --- | --- |
| `scope` | 状态作用域，主键 |
| `state_version` | 该作用域状态版本 |
| `payload_json` | UTF-8 JSON 状态 |

### `frame_catalog`

记录逻辑 DataFrame 名称、实际 SQLite 表名和稳定顺序。实际数据放入内部生成的
`frame_*` 表，避免直接把外部文本作为 SQL 标识符。

Match Workbook 原有的参数映射保持关系表形式，不必塞入 JSON。

## 5. Match Workbook 的作用域

一个 Match WKB 保存父工作簿及其全部子工作区：

```text
match
map.preview
map.final
dynamic.preview
dynamic.final
correlation.preview
correlation.final
```

### `match`

- Reference、Preview Raw Data、Final Raw Data 和现有阶段数据；
- 参数映射；
- Match Type、Preview / Final 模式；
- Bias 选择；
- 参数顺序和 Setup 布局。

### `map.preview` / `map.final`

- 对应阶段的精确表快照；
- wafer、parameter 和 grouping 选择；
- Wafer Map 与 Radius Plot 的实际框选；
- 是否已经成功 Draw；
- X/Y 列、直径、色图、色阶范围、透明度；
- Point values、Measurement points、Contour、Outline、Fill edge、Shared scale、
  Scale bar；
- 字体、分辨率和布局选项。

### `dynamic.preview` / `dynamic.final`

- 对应阶段的精确表快照；
- wafer、parameter 和 grouping 选择；
- 已绘制状态和工作区级显示选项。

### `correlation.preview` / `correlation.final`

- Reference 与当前阶段 Raw Data 的独立 wafer、parameter、grouping 选择；
- Correlation 的 R² 阈值、选中拟合组合、列数、每页数量和当前页；
- Trend 的列数和 Add Compare 参数列表；
- 字体、分辨率和必要布局设置；
- 当前页签。

Correlation/Trend 未编辑数据时复用 Match Workbook 的源表，不重复存储。
如果在子窗口编辑了 Ref/Raw，则保存该窗口的独立双表快照，不能再次从父表生成覆盖。
Preview 与 Final 分别保存配置与数据覆盖状态。

## 6. 独立工具的 WKB 内容

### Wafer Map / Radius

- 一个 `input_data` DataFrame；
- 与 Match 版本相同的 Map/Radius 选择和绘图配置。

### Dynamic

- 一个 `input_data` DataFrame；
- wafer、parameter、grouping、绘制状态和显示配置。

### Correlation and Trend

- `reference_data` 和 `raw_data` 两张独立表；
- 两边独立的 wafer、parameter、grouping 选择；
- Correlation 分页与拟合选择；
- Trend Add Compare 配置和其他绘图设置。

Ref Data 允许为空，以兼容只粘贴一张普通数据表的独立分析流程。

## 7. `Ctrl+S` 语义

主窗口独立打开的三个工具统一采用：

- 第一次 `Ctrl+S`：选择 `.wkb` 路径并保存；
- 后续 `Ctrl+S`：原子覆盖当前 WKB；
- `Ctrl+Shift+S`：Save WKB As；
- CSV 按钮改为 `Export CSV`，不再占用 `Ctrl+S`；
- 打开 CSV/XLSX 是导入数据，不自动把该源文件当成工作区保存目标。

工作区 dirty 状态必须同时覆盖数据修改和可持久化的选择/绘图配置修改。

## 8. 写盘时机

不在每次勾选、滚轮切换或拖动时立即写 SQLite。

- 修改时只更新内存快照并标记 dirty；
- `Ctrl+S` 时一次性原子保存；
- Match 子窗口、Match 父窗口和独立工具关闭且 dirty 时，都显示 Save / Discard / Cancel；
- 子窗口编辑先留在自己的草稿中；选择 Save 才接受该子窗口的数据与配置并写入父 WKB；
- 子窗口 Save 也会保存父工作簿当前源数据与设置，但不接受其他仍打开子窗口的草稿；
- 父窗口 Save 捕获所有存活子窗口并一次保存；父窗口 Discard 一并放弃子窗口草稿；
- 子窗口 Discard 不改变父工作簿接受的数据或磁盘文件；Cancel 保持窗口和修改；
- 尚无 WKB 路径时，Save 必须选择路径；取消路径选择等同取消关闭，不作静默内存保存；
- 干净窗口直接关闭，不重复询问。

托管子窗口的 `Ctrl+S` 写回父 WKB；`Ctrl+Shift+S` 为完整父工作簿另存为，
不会把子窗口切换成一个丢失父关系的独立文件。独立工具的另存为只保存自己的文档。

## 9. 不保存的内容

- Matplotlib、PyQtGraph、Qt 对象；
- PNG 或屏幕截图缓存；
- 可从数据重新计算的拟合结果和绘图数组；
- Undo / Redo 历史；
- 临时鼠标缩放范围、悬停状态和滚动位置；
- 搜索框中的临时过滤文字；
- 全局主题和语言。

全局设置只作为新工作区的默认值。WKB 中存在文档级设置时，WKB 优先。

## 10. 兼容与迁移

- 继续读取 WKB schema 1–10；
- 没有 `workspace_manifest` 的文件按旧 Match Workbook 识别；
- 缺少新状态时使用当前默认值；
- 第一次重新保存时升级到统一容器格式；
- 旧 Map/Dynamic `workspace_selections` 转换为新的作用域状态；
- 旧 `settings.yaml` 中的 `trend_overlay` 只作为没有文档状态时的初始默认；
- 迁移不得修改源表字符串、列顺序、行顺序和参数映射。

## 11. 建议实施顺序

1. 建立 `WorkspaceSnapshot` 与 SQLite 存储模块。
2. 为原子保存、精确 DataFrame round-trip、类型校验和损坏文件补测试。
3. 让 Match Workbook 通过新 interface 保存，并保留 schema 1–10 读取测试。
4. 把 Match 内 Correlation/Trend 状态加入 WKB。
5. 接入独立 Wafer Map 的 `Ctrl+S`。
6. 接入独立 Dynamic 的 `Ctrl+S`。
7. 接入独立 Correlation/Trend 的 Ref/Raw 双表保存。
8. 运行完整测试，并用 100,000 行 × 50 参数数据验证保存时间、载入时间和文件大小。

## 12. 验收条件

- Match Workbook 重开后，三个子工作区恢复到保存时的参数选择和绘图配置；
- Preview 与 Final 状态互不串用；
- 独立工具第一次 `Ctrl+S` 选择路径，之后直接覆盖；
- CSV 导出不改变当前 WKB 路径；
- 保存失败时旧 WKB 保持完整；
- 错误类型的 WKB 给出明确提示，不部分载入；
- 旧 schema 1–10 文件仍可打开；
- 重开后所有图均由保存的数据和状态重新生成，而不是读取缓存图片。

## 13. 文件安全、备份与恢复

- 保存使用同目录临时 SQLite 文件，提交、关闭句柄、校验并 `fsync` 后原子替换。
- 成功覆盖前保留上一版为 `文件名.wkb.bak`；需要回退时先复制为新 `.wkb` 再打开，
  不直接覆盖当前文件。备份不包含本次尚未接受的草稿。
- `.wkb.lock` 排除同时写入；SHA-256 revision 检测其他窗口或应用保存后的过期覆盖。
  检测到冲突时保留现有文件与当前编辑，要求重新打开或另存为，不自动合并测量数据。
- 崩溃留下的 `.lock` 不自动删除；确认所有实例已关闭后才手动移除，避免误抢活跃写入。
- 脏文档每 30 秒保存恢复草稿到 `%LOCALAPPDATA%/MetrologyWorkspace/recovery/`；
  父恢复草稿包含仍打开子窗口的修改，不写回正式 WKB。
- 用对应工具的 **File → Recover draft…** 手动恢复；恢复后仍标记未保存。
  Save 或 Discard 会清理该文档的恢复草稿，Cancel 保留；清理被系统拒绝时保留草稿并提示，
  不把已经成功的保存误报为失败。直接 Open 恢复文件也会识别为草稿，不标记正式保存，
  恢复 Match 后保存目标是原文档而非此前打开的另一个文件。首次 30 秒内或系统写盘失败
  尚未产生的修改无法保证恢复；草稿不是正式保存的替代。
- 载入只读校验版本、类型、必需表、列模式、行顺序和状态版本；不会创建缺失文件，
  不执行 pickle，也不把错误类型的文件部分装入另一个工具。
- 支持重复表头、空白内行、`001`、`2.1000`、`NA` 等编辑草稿；用于分析的表仍按既有
  规则校验。Match 子表无效时保留在独立作用域，不阻塞父分析及子表编辑器重开修复。

## 14. 实现与验证入口

- `metrology_app/workspace_store.py`：纯 SQLite / JSON 存储和旧格式读取适配。
- `metrology_app/workspace_document.py`：文档状态、关闭决策、草稿与恢复；窗口不直接写 SQL。
- `tests/test_workspace_store.py`：精确往返、备份、过期覆盖、写入失败、版本与类型拒绝。
- `tests/test_document_storage.py`：真实窗口的独立文档、父子草稿、取消、恢复、Ref/Raw 对比、
  Dynamic Die 选择、错误分析草稿和 Shell 路由。
- `tests/legacy_wkb.py`：只用于构造旧格式测试夹具；生产代码只写新容器。
- `docs/features/workspace_storage.feature`：BDD 行为场景，落到以上 unittest 的公开 interface。
- `python run_tests.py`：全量回归；测试隔离应用设置和恢复目录，并对普通夹具清理默认 Discard。
  Save/Cancel 行为测试分别显式覆盖和断言，不依赖清理默认值。

基准命令：`python -m benchmarks.benchmark_workspace_store`。
2026-10-03 在当前开发机一次测得：100,000 行 × 50 个四位小数文本参数，加 Wafer ID、Die Seq
两列，保存 0.963 秒、载入 1.576 秒、文件 43.54 MiB，逐项与原表一致。这是存储模块基准，
不是 GUI 出图时间，也不是相对旧格式的性能提升结论。备份、草稿、父子多表的总成本需按实际文档计算。

最终验证：2026-10-03 执行 `python -W ignore::DeprecationWarning run_tests.py`，
全量 320 项测试通过（136.760 秒）；`git diff --check` 无空白错误。
远端 main 和 dev5 仍为 `837006709016bf0ed30604396674e31cbee2adf4`，本次存储改动仅留在本地工作区。

