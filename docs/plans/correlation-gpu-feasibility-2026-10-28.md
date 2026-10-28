# Correlation 50 参数：GPU 可行性与条件延迟推算

日期：2026-10-28。源码 HEAD：`71c3105c74c26bfe916cfa5234605bfa68fe8ecb`。

本报告回答 GPU 能加速哪些实际依赖，以及在既有 V/Z/Y 分段下能推算出什么。
没有安装 GPU 包、改生产代码、切换渲染器或运行 GPU 实测。所有倍率是假设，不是 GTX 1650 的实测或保证。
Y 是 Ctrl+Y（重做），V 是粘贴，Z 是撤销。

## 硬件与当前环境

只读核对：Ryzen 7 4800H；NVIDIA GTX 1650，4096 MiB，驱动 527.83，计算能力 7.5；
另有 AMD Radeon 集显。尚未测量 Qt 的实际 GL_RENDERER，不能假设 OpenGL 必然用独显。
当前解释器为 F:/Anaconda3/envs/octs/python.exe，并读取既有 QA 依赖目录。

pandas 2.3.3、NumPy 2.2.6、SciPy 1.15.3、lmfit 1.3.4、PyQtGraph 0.14.0、
PyQt6 6.11.0、Matplotlib 3.10.9、ContourPy 1.3.2、openpyxl 3.1.5、
lxml 6.1.3、Pillow 12.3.0、PyYAML 6.0.3、RapidOCR 3.10.0、
ONNX Runtime 1.23.2、opencv-python-headless 5.0.0.93。
CuPy、cuDF、Numba、Torch 均未安装。

首次受限查询没有读到外部 QA 目录的真实包文件；经过只读提权核实，真实 lxml.etree 扩展及上述 OCR 包存在。
没有因此换 XML 后端，也不把第一次受限结果误记为依赖缺失。

## 各库和实际调用链

| 库/路径 | 当前用途与 GPU 边界 |
| --- | --- |
| pandas | 来源表包装、原始字符串规范化、筛选、分组和对齐目前为 CPU。cuDF 可加速支持的表操作，不能让 Qt 模型提交、Python 对象深复制或 Undo 自动上 GPU。 |
| NumPy | 当前共同有效行批量 OLS 的居中矩阵乘法、归约、预测和残差最适合做 CuPy 对照。必须包含字符串转数值、传输、结果回 CPU 的总成本，并保持 float64 与现有数值定义。 |
| SciPy | 实际用于 Wafer 插值；1.15.3 的 Array API 支持只有部分函数，不能把 RBFInterpolator/griddata 或所有 SciPy 调用视为自动 GPU。替换算法前必须证明数值及边缘处理等价。 |
| lmfit | 小样本、异常/不适合批量拟合时保留原求解器；既有 leastsq 路径包装 SciPy。当前大样本普通线性拟合已走 NumPy 快路，换 lmfit 后端不能消除 Qt 提交成本。 |
| PyQtGraph | 当前默认 useOpenGL=False，Wafer Graphics 还显式设 False。0.14.0 部分曲线支持 OpenGL；散点符号准备、QPainter atlas、坐标轴/文字/布局仍有 CPU 工作，不能把整个绘图段算成 GPU。安装源码还明确说明 OpenGL 曲线传入 float32 顶点，需检验大偏移小变化、NaN、点线样式、截图/导出等价性。 |
| PyQt6 | QWidget、模型通知、控件恢复、布局、启用状态和主线程事件处理仍是 GUI/CPU 工作；OpenGL 不会执行这些业务提交。 |
| Matplotlib / ContourPy / Pillow | 当前 Agg 导出、轮廓生成和图像处理路径为 CPU。改变为 GPU 实现属于具体算法/渲染路径的替换，不是打开一个通用开关。 |
| openpyxl / lxml / YAML / JSON / SQLite / ZIP | 当前文件、XML、配置、序列化与事务路径，没有可直接替换的本流程 GPU 加速步骤；这些也不在本次 Correlation 全链计时的主要数值热点中。 |
| RapidOCR / ONNX Runtime / OpenCV | OCR 可另测 CUDA provider，但不在 Correlation 粘贴/Undo 链中。当前 ORT 只有 Azure/CPU provider；OpenCV CUDA 设备数 0，构建有 OpenCL。OpenCL 构建支持不证明本应用当前调用已走 GPU。 |

cuDF 对支持的操作使用 GPU，不支持的操作会回退 CPU。[官方用法](https://docs.nvidia.com/cudf/latest/cudf_pandas/usage/)
Windows 官方安装路线为 WSL2；当前原生 Windows PyQt 进程不能直接原位换成 WSL2 的 pandas，
若拆出 WSL 服务会新增进程通信和数据传输，这是本报告的架构推断，不是已实施方案。
[官方平台要求](https://docs.nvidia.com/datascience/install/)

SciPy 的限制按本机版本核对：[SciPy 1.15.3 Array API](https://docs.scipy.org/doc/scipy-1.15.3/dev/api-dev/array_api.html)。
lmfit 的优化器包装关系见[官方 fitting 文档](https://lmfit.github.io/lmfit-py/fitting.html)。
Qt GUI 主线程约束见[官方线程说明](https://doc.qt.io/qt-6/threads-qobject.html)。
PyQtGraph 同时核对了本地 0.14.0 的 PlotCurveItem/ScatterPlotItem 源码和
[0.14.0 发布说明](https://github.com/pyqtgraph/pyqtgraph/releases/tag/pyqtgraph-0.14.0)。

CuPy 首次 CUDA 上下文建立可能有秒级开销，正确计时还需同步 GPU 完成。
本推算故意没有加入这些额外成本，不是冷启动预测。
[CuPy 性能说明](https://docs.cupy.dev/en/stable/user_guide/performance.html)
OCR GPU 路径须匹配实际 CUDA/cuDNN 和 provider：[ONNX Runtime CUDA](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)。

## 按用户截图那组测量推算

输入：10k 行、50 个选中 Raw 参数、1225 对、100 wafers、一个分析子窗口。
原测量文件为 QA data-version/native-readers-before.json，
V=3108.40ms，Z=2215.12ms，Y=2554.99ms。它是已有分段测量，不冒充最新稳定分布。

为了给 GPU 最大的有利假设，把以下三个**含有 CPU 工作的整段**都列入加速：
主 WKB 分析/主图、后台子数据/分组准备、尾段拟合/绘制/强制验收。
可加速预算分别为 V=1252ms、Z=1209ms、Y=1298ms。
其余流程及未分配/四舍五入差额保留不变，分别为 1856.40/1006.12/1256.99ms。

公式：新总耗时 = 保留部分 + 三段预算 / 假设倍率。

| 假设 | V 粘贴 | Z 撤销 | Y 重做 |
| --- | ---: | ---: | ---: |
| 原截图测量 | 3.11s | 2.22s | 2.55s |
| 三个整段均加速 2 倍 | 2.48s | 1.61s | 1.91s |
| 三个整段均加速 5 倍 | 2.11s | 1.25s | 1.52s |
| 三个整段完全不花时间 | 1.86s | 1.01s | 1.26s |

这些数字是条件敏感性计算，不是显卡速度预测或置信区间。
GPU 只覆盖其中部分操作，加入传输/回退/上下文成本后可能收益更小，甚至变慢。
若改造数据流并同时削减 CPU/Qt 提交，上述保留部分会变，必须重建基准；
不能把此条件模型解释为该软件永远不能达到 300ms。

当前证据支持：**保持现有表格和界面提交路径时，单靠 GPU 不足以达成 300ms。**
下一步更有价值的是继续压缩子窗口数据/控件提交、字符串和数值准备、粘贴事务；
GPU 应在明确的独立数值热点上小范围验证。

## 独立的测试器边界核查

QA-only 修改防止 check_ready 在强制 repaint 验收后再次结束计时。
native-ready-single.json 中五项操作均只执行一次完成验收；
所有原有数据/拟合/当前图验收保留。
A=88.01ms，取消全选点击=81.44ms，V=2824.39ms，Z=1996.10ms，Y=2246.90ms。
300ms 断言仍对 V/Z/Y 失败。未修改生产代码，不能将这组单次变化归因为 GPU 或应用提速，
也不替换前面截图分段模型，未形成新的稳定 P50/P95。

真实 settings 与自有 WKB 哈希保持既有值；没有写用户文件、安装依赖、push、改 tag 或发布。
本次只有诊断文档/算术核验，不重复跑全量；既有全量红灯状态不变。

