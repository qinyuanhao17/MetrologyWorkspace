"""Qt workspace for multi-parameter Reference/Raw card matching."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyqtgraph.exporters
from PyQt6.QtCore import (
    QAbstractTableModel, QEasingCurve, QMimeData, QModelIndex, QPoint,
    QPropertyAnimation, Qt, QTimer,
)
from PyQt6.QtGui import (
    QAction, QActionGroup, QBrush, QColor, QDrag, QKeySequence, QPainter,
    QPalette, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .appearance import fit_window_to_screen, help_title_label
from .data import inspect_table
from .diagnostics import get_logger
from .matching import MAX_ROWS, MatchWorkbook, ParameterMapping, extrema_sample_indices
from .plotting import InteractivePlotWidget
from .settings import (
    apply_theme, forget_recent_wkb, recent_wkb_paths, remember_recent_wkb,
)
from .sheet import DuplicateHeaderBanner, SheetModel, SheetView


PLOT_LIMIT = 20_000
_PARAMETER_MIME = "application/x-metrology-match-parameter"
LOGGER = get_logger()


def reveal_path_in_folder(path):
    """Open the platform file manager and reveal one existing file."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer.exe", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
    return path


def _label(text, role="muted"):
    widget = QLabel(text)
    widget.setObjectName(role)
    return widget


def clipboard_frame(text):
    """Parse an Excel/CSV clipboard block while preserving identifiers as text."""
    if not text or not text.strip():
        raise ValueError("The clipboard does not contain a table.")
    delimiter = "\t" if "\t" in text.partition("\n")[0] else ","
    frame = pd.read_csv(StringIO(text), sep=delimiter, dtype=str, keep_default_na=False)
    if frame.empty or not len(frame.columns):
        raise ValueError("The clipboard table has headers but no data rows.")
    return frame


class DataFrameModel(QAbstractTableModel):
    """Read-only, lazy Qt view over a DataFrame; no per-cell object cache."""

    def __init__(self, frame=None, parent=None):
        super().__init__(parent)
        self.frame = frame if frame is not None else pd.DataFrame()

    def set_frame(self, frame):
        self.beginResetModel()
        self.frame = frame
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.frame.iat[index.row(), index.column()]
        warning = self._quality_warning(index.column(), value)
        if role == Qt.ItemDataRole.BackgroundRole and warning:
            dark = QApplication.palette().color(
                QPalette.ColorRole.Base
            ).lightness() < 128
            return QBrush(QColor("#4a1822" if dark else "#fff0f1"))
        if role == Qt.ItemDataRole.ForegroundRole and warning:
            dark = QApplication.palette().color(
                QPalette.ColorRole.Base
            ).lightness() < 128
            return QBrush(QColor("#ffb4bd" if dark else "#a3132b"))
        if role == Qt.ItemDataRole.ToolTipRole and warning:
            return warning
        if role not in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
        ):
            return None
        if pd.isna(value):
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{value:.8g}"
        return str(value)

    def _quality_warning(self, column, value):
        name = str(self.frame.columns[column])
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ""
        if not np.isfinite(number):
            return ""
        if name == "Slope" and (number < 0.9 or number > 1.1):
            return "Slope is outside the accepted 0.9–1.1 range."
        if name == "R²" and number < 0.9:
            return "R² is below 0.9."
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self.frame.columns[section])
        return str(section + 1)


class _ParameterDragHandle(QLabel):
    """Small keyboard-neutral pointer handle for reordering parameter cards."""

    def __init__(self, parameter, parent=None):
        super().__init__(f"⋮⋮  {parameter}", parent)
        self.parameter = parameter
        self._press_position = None
        self.setObjectName("parameterDragHandle")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to reorder this parameter.")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._press_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press_position).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            mime = QMimeData()
            mime.setData(_PARAMETER_MIME, self.parameter.encode("utf-8"))
            drag = QDrag(self)
            drag.setMimeData(mime)
            card = self.parentWidget()
            if card is not None:
                preview = card.grab()
                if preview.width() > 520:
                    preview = preview.scaledToWidth(
                        520, Qt.TransformationMode.SmoothTransformation
                    )
                ghost = QPixmap(preview.size())
                ghost.fill(Qt.GlobalColor.transparent)
                painter = QPainter(ghost)
                painter.setOpacity(0.72)
                painter.drawPixmap(0, 0, preview)
                painter.end()
                drag.setPixmap(ghost)
                drag.setHotSpot(QPoint(28, 22))
            drag.exec(Qt.DropAction.MoveAction)
            if hasattr(self.window(), "clear_parameter_drop_previews"):
                self.window().clear_parameter_drop_previews()
            self._press_position = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_position = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class _ParameterCard(QFrame):
    """Drop target that delegates order changes to the matching workspace."""

    def __init__(self, parameter, workspace):
        super().__init__(objectName="sheetCard")
        self.parameter = parameter
        self.workspace = workspace
        self.setAcceptDrops(True)
        self.setProperty("parameter", parameter)
        self._drop_indicator = QFrame(self)
        self._drop_indicator.setObjectName("parameterDropIndicator")
        self._drop_indicator.setFixedHeight(4)
        self._drop_indicator.hide()
        self._drop_effect = QGraphicsOpacityEffect(self._drop_indicator)
        self._drop_indicator.setGraphicsEffect(self._drop_effect)
        self._drop_animation = QPropertyAnimation(
            self._drop_effect, b"opacity", self
        )
        self._drop_animation.setDuration(180)
        self._drop_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_PARAMETER_MIME):
            self._show_drop_position(event.position().y() < self.height() / 2)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_PARAMETER_MIME):
            self._show_drop_position(event.position().y() < self.height() / 2)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(_PARAMETER_MIME):
            event.ignore()
            return
        parameter = bytes(event.mimeData().data(_PARAMETER_MIME)).decode("utf-8")
        before = event.position().y() < self.height() / 2
        self.workspace.clear_parameter_drop_previews()
        self.workspace.move_parameter(parameter, self.parameter, before=before)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._show_drop_position(None)
        super().dragLeaveEvent(event)

    def _show_drop_position(self, before):
        value = "" if before is None else ("before" if before else "after")
        if self.property("dropPosition") == value:
            return
        self.setProperty("dropPosition", value)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        self._drop_animation.stop()
        if before is None:
            self._drop_indicator.hide()
            return
        self._place_drop_indicator(before)
        self._drop_effect.setOpacity(0.2)
        self._drop_indicator.show()
        self._drop_indicator.raise_()
        self._drop_animation.setStartValue(0.2)
        self._drop_animation.setEndValue(1.0)
        self._drop_animation.start()

    def _place_drop_indicator(self, before):
        margin = 12
        y = 0 if before else max(0, self.height() - 4)
        self._drop_indicator.setGeometry(
            margin, y, max(0, self.width() - 2 * margin), 4
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        position = self.property("dropPosition")
        if position in {"before", "after"}:
            self._place_drop_indicator(position == "before")


class _MatchPlotWidget(InteractivePlotWidget):
    """Match plot with a reserved title-and-fit row above the data area."""

    HEADER_HEIGHT = 46

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        plot = self.getPlotItem()
        plot.setTitle(None)
        plot.layout.setRowFixedHeight(0, self.HEADER_HEIGHT)

        self.heading = QWidget(self)
        self.heading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        heading_layout = QHBoxLayout(self.heading)
        heading_layout.setContentsMargins(42, 0, 8, 0)
        heading_layout.setSpacing(8)
        self.title_label = QLabel(objectName="matchPlotTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.formula_label = QLabel(objectName="matchPlotFormula")
        self.formula_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        heading_layout.addWidget(self.title_label, 3)
        heading_layout.addWidget(self.formula_label, 2)

    def set_match_heading(self, title, formula):
        self.title_label.setText(str(title))
        self.formula_label.setText(str(formula))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "heading"):
            return
        self.heading.setGeometry(0, 0, self.width(), self.HEADER_HEIGHT)
        self.heading.raise_()


class _TrendPlotWidget(InteractivePlotWidget):
    """Trend plot with a compact Card toggle overlaid at the top-right."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.card_checkbox = QCheckBox("Card", self)
        self.card_checkbox.setObjectName("trendCardToggle")
        self.card_checkbox.setToolTip(
            "Show PMISH after applying the fitted Card; clear to show Raw Data."
        )
        self.card_checkbox.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "card_checkbox"):
            return
        self.card_checkbox.adjustSize()
        self.card_checkbox.move(
            max(8, self.width() - self.card_checkbox.width() - 12),
            8,
        )
        self.card_checkbox.raise_()


class MatchingWindow(QMainWindow):
    """Build Preview or Final results from one row-aligned matching workbook."""

    def __init__(self, wafer_window_factory=None, dynamic_window_factory=None,
                 correlation_window_factory=None):
        super().__init__()
        self.setWindowTitle("Match Workbook")
        fit_window_to_screen(self, (1520, 930), minimum=(1050, 700))
        apply_theme(self)
        self.reference_frame = pd.DataFrame()
        self.raw_frame = pd.DataFrame()
        self.final_match_frame = pd.DataFrame()
        self.preview_frame = pd.DataFrame()
        self.final_frame = pd.DataFrame()
        self.preview_map_frame = None
        self.final_map_frame = None
        self.preview_dynamic_frame = None
        self.final_dynamic_frame = None
        self.workbook = None
        self.workbook_path = None
        self.result = None
        self._primary_bias_mode = "absolute"
        self._auto_run_enabled = False
        self._auto_run_pending = False
        self._pending_auto_view_state = None
        self._loading_input_sheets = False
        self._input_sheet_errors = {"reference": "", "raw": "", "final_raw": ""}
        self._parameter_order = []
        self._displayed_raw_mode = "preview"
        self._raw_sources = {"preview": "No data", "final": "No data"}
        self._trend_card_state = {}
        self._wafer_window_factory = wafer_window_factory or self._default_wafer_window_factory
        self._dynamic_window_factory = (
            dynamic_window_factory or self._default_dynamic_window_factory
        )
        self._correlation_window_factory = (
            correlation_window_factory or self._default_correlation_window_factory
        )
        self._map_selection_states = {"preview": None, "final": None}
        self._dynamic_selection_states = {"preview": None, "final": None}
        self._stage_windows = []
        self._stage_window_context = {}
        self._recent_wkb_paths = list(recent_wkb_paths())
        self.reference_model = SheetModel()
        self.raw_model = SheetModel()
        self.final_raw_model = SheetModel()
        self.preview_model = DataFrameModel(parent=self)
        self.final_model = DataFrameModel(parent=self)
        self.summary_model = DataFrameModel(parent=self)
        self._build_ui()
        self.reference_model.changed.connect(
            lambda: self._input_sheet_changed("reference")
        )
        self.raw_model.changed.connect(lambda: self._input_sheet_changed("raw"))
        self.final_raw_model.changed.connect(
            lambda: self._input_sheet_changed("final_raw")
        )
        self.raw_view.table_pasted.connect(self._raw_table_pasted)
        self._update_state()

    def _build_ui(self):
        self.result_mode = QComboBox(self)
        self.result_mode.addItems(["Preview", "Final"])
        self.result_mode.hide()
        self.match_type = QComboBox(self)
        self.match_type.addItems(["KLA", "NOVA", "TEM"])
        self.match_type.hide()
        self.absolute_bias = QCheckBox("Bias", self)
        self.absolute_bias.setChecked(True)
        self.absolute_bias.hide()
        self.percent_bias = QCheckBox("Bias %", self)
        self.percent_bias.hide()
        self._build_menu_bar()

        root = QWidget(objectName="appRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.mode_tabs = QTabBar()
        self.mode_tabs.setObjectName("workspaceModeTabs")
        self.mode_tabs.setExpanding(False)
        self.mode_tabs.addTab("Preview")
        self.mode_tabs.addTab("Final")
        mode_row.addWidget(self.mode_tabs)
        mode_row.addStretch()
        self.correlation_button = QPushButton(
            "Open Correlation and Trend", objectName="primary"
        )
        self.correlation_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.correlation_button.clicked.connect(
            self._open_correlation_clicked
        )
        self.preview_open_button = QPushButton(
            "Open Preview Wafer Map / Radius", objectName="primary"
        )
        self.preview_open_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.preview_open_button.clicked.connect(
            lambda: self._open_stage_clicked("preview")
        )
        self.final_open_button = QPushButton(
            "Open Final Wafer Map / Radius", objectName="primary"
        )
        self.final_open_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.final_open_button.clicked.connect(
            lambda: self._open_stage_clicked("final")
        )
        self.preview_dynamic_button = QPushButton(
            "Open Preview Dynamic", objectName="primary"
        )
        self.preview_dynamic_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.preview_dynamic_button.clicked.connect(
            lambda: self._open_dynamic_clicked("preview")
        )
        self.final_dynamic_button = QPushButton(
            "Open Final Dynamic", objectName="primary"
        )
        self.final_dynamic_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.final_dynamic_button.clicked.connect(
            lambda: self._open_dynamic_clicked("final")
        )
        mode_row.addWidget(self.correlation_button)
        mode_row.addWidget(self.preview_dynamic_button)
        mode_row.addWidget(self.final_dynamic_button)
        mode_row.addWidget(self.preview_open_button)
        mode_row.addWidget(self.final_open_button)
        layout.addLayout(mode_row)

        self.setup_page = self._build_setup_page()
        layout.addWidget(self.setup_page, 1)
        self.setCentralWidget(root)
        self.mode_tabs.currentChanged.connect(self._mode_tab_changed)
        self.result_mode.currentIndexChanged.connect(self._result_mode_changed)
        self._update_mode_actions()

    def _build_menu_bar(self):
        self.file_menu = self.menuBar().addMenu("File")
        self.open_action = QAction("Open WKB", self)
        self.open_action.setShortcut(QKeySequence("Ctrl+O"))
        self.open_action.triggered.connect(self.open_wkb_dialog)
        self.open_recent_menu = QMenu("Open Recent WKB", self.file_menu)
        self.reveal_wkb_action = QAction("Reveal WKB in Folder", self)
        self.reveal_wkb_action.setEnabled(False)
        self.reveal_wkb_action.triggered.connect(self.reveal_wkb_in_folder)
        self.save_action = QAction("Save WKB", self)
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_action.triggered.connect(self.save_wkb)
        self.save_as_action = QAction("Save WKB As…", self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.triggered.connect(self.save_wkb_dialog)
        self.export_action = QAction("Export Excel", self)
        self.export_action.triggered.connect(self.export_excel_dialog)
        self.images_action = QAction("Save images", self)
        self.images_action.triggered.connect(self.save_images_dialog)
        for action in (
            self.open_action,
            self.open_recent_menu.menuAction(),
            self.reveal_wkb_action,
            self.save_action,
            self.save_as_action,
            self.export_action,
            self.images_action,
        ):
            self.file_menu.addAction(action)
        self._refresh_recent_wkb_menu()

        self.analysis_menu = self.menuBar().addMenu("Analysis")
        self.run_action = QAction("Run analysis", self)
        self.run_action.setShortcut(QKeySequence("Ctrl+Return"))
        self.run_action.triggered.connect(self._run_analysis_clicked)
        self.analysis_menu.addAction(self.run_action)
        self.match_type_menu = self.analysis_menu.addMenu("Match Type")
        self.match_type_group = QActionGroup(self)
        self.match_type_group.setExclusive(True)
        self.match_type_actions = {}
        for match_type in ("KLA", "NOVA", "TEM"):
            action = QAction(match_type, self, checkable=True)
            action.setChecked(match_type == self.match_type.currentText())
            action.triggered.connect(
                lambda _checked=False, value=match_type:
                self.match_type.setCurrentText(value)
            )
            self.match_type_group.addAction(action)
            self.match_type_menu.addAction(action)
            self.match_type_actions[match_type] = action
        self.match_type.currentTextChanged.connect(
            lambda value: self.match_type_actions[value].setChecked(True)
        )

        self.bias_menu = self.analysis_menu.addMenu("Bias")
        self.absolute_bias_action = QAction("Bias", self, checkable=True)
        self.percent_bias_action = QAction("Bias %", self, checkable=True)
        self.absolute_bias_action.setChecked(True)
        self.absolute_bias_action.toggled.connect(self.absolute_bias.setChecked)
        self.percent_bias_action.toggled.connect(self.percent_bias.setChecked)
        self.absolute_bias.toggled.connect(self.absolute_bias_action.setChecked)
        self.percent_bias.toggled.connect(self.percent_bias_action.setChecked)
        self.bias_menu.addAction(self.absolute_bias_action)
        self.bias_menu.addAction(self.percent_bias_action)

        # Compatibility aliases for callers that previously enabled toolbar buttons.
        self.open_button = self.open_action
        self.save_button = self.save_action
        self.save_as_button = self.save_as_action
        self.export_button = self.export_action
        self.images_button = self.images_action

    def _install_shortcuts(self):
        for title, shortcut, handler in (
            ("Open WKB", "Ctrl+O", self.open_wkb_dialog),
            ("Save WKB", "Ctrl+S", self.save_wkb),
            ("Save WKB As…", "Ctrl+Shift+S", self.save_wkb_dialog),
            ("Run analysis", "Ctrl+Return", self._run_analysis_clicked),
        ):
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(handler)
            self.addAction(action)

    def _mode_tab_changed(self, index):
        if index >= 0 and self.result_mode.currentIndex() != index:
            self.result_mode.setCurrentIndex(index)
        self._update_mode_actions()

    def _result_mode_changed(self, index):
        had_result = self.result is not None
        mapping_state = self._mapping_state()
        splitter_sizes = (
            tuple(self.setup_splitter.sizes())
            if hasattr(self, "setup_splitter")
            else ()
        )
        scroll_value = (
            self.setup_scroll.verticalScrollBar().value()
            if hasattr(self, "setup_scroll")
            else 0
        )
        if index >= 0 and self.mode_tabs.currentIndex() != index:
            self.mode_tabs.setCurrentIndex(index)
        self._show_raw_mode(self.result_mode.currentText().lower())
        self._populate_mappings(mapping_state)
        if had_result:
            self._show_mapping_results()
        self._update_mode_actions()
        self._update_state()
        if had_result and self.analyze_button.isEnabled():
            try:
                self.run_analysis()
                if splitter_sizes:
                    self._restore_setup_splitter_layout(splitter_sizes)
                QTimer.singleShot(
                    0,
                    lambda value=scroll_value:
                    self.setup_scroll.verticalScrollBar().setValue(value),
                )
            except Exception as error:
                self._set_status(
                    f"Could not update {self.result_mode.currentText()}: {error}",
                    warning=True,
                )

    def _update_mode_actions(self):
        preview = self.result_mode.currentText().lower() == "preview"
        self.preview_open_button.setVisible(preview)
        self.final_open_button.setVisible(not preview)
        self.preview_dynamic_button.setVisible(preview)
        self.final_dynamic_button.setVisible(not preview)
        if hasattr(self, "raw_card"):
            self.raw_card.show()

    def _show_raw_mode(self, mode):
        """Put the mode's independent editable Raw Data model in the shared view."""
        mode = "final" if str(mode).lower() == "final" else "preview"
        model = self.final_raw_model if mode == "final" else self.raw_model
        if hasattr(self, "raw_view") and self.raw_view.model() is not model:
            self.raw_view.setModel(model)
        if hasattr(self, "raw_duplicate_banner"):
            self.raw_duplicate_banner.set_model(model)
        self._displayed_raw_mode = mode
        if hasattr(self, "raw_source"):
            self.raw_source.setText(self._raw_sources[mode])

    def _build_setup_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        self.match_type.currentTextChanged.connect(self._analysis_input_changed)
        self.status = _label("", "hint")
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)

        inputs = QSplitter(Qt.Orientation.Horizontal)
        self.inputs_splitter = inputs
        (self.reference_card, self.reference_view, self.reference_source,
         self.reference_duplicate_banner) = self._table_card(
            "Reference", "Paste the prepared table first.", self.reference_model
        )
        (self.raw_card, self.raw_view, self.raw_source,
         self.raw_duplicate_banner) = self._table_card(
            "Raw Data", "Rows are matched to Reference from top to bottom.", self.raw_model
        )
        inputs.addWidget(self.reference_card)
        inputs.addWidget(self.raw_card)
        inputs.setSizes([720, 720])
        inputs.setChildrenCollapsible(False)
        for card in (self.reference_card, self.raw_card):
            card.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
            )
        inputs.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
        self.mapping_card = QFrame(objectName="panel")
        mapping_layout = QVBoxLayout(self.mapping_card)
        mapping_layout.setContentsMargins(16, 14, 16, 12)
        heading = QHBoxLayout()
        heading.addWidget(help_title_label(
            "Parameter mapping",
            "Numeric Reference columns are listed; “Reference” suffix columns pair by name.",
        ))
        heading.addStretch()
        self.select_all_mappings = QCheckBox("Select all")
        self.select_all_mappings.setEnabled(False)
        self.select_all_mappings.toggled.connect(
            self._set_all_mappings_checked
        )
        heading.addWidget(self.select_all_mappings)
        self.analyze_button = QPushButton("Run analysis", objectName="primary")
        self.analyze_button.clicked.connect(self._run_analysis_clicked)
        heading.addWidget(self.analyze_button)
        mapping_layout.addLayout(heading)
        self.mapping_table = QTableWidget(0, 10)
        self.mapping_table.setHorizontalHeaderLabels([
            "Use", "Parameter", "Reference column", "Raw Data column",
            "Slope", "Intercept", "R²", "Valid pairs", "Match type", "Result mode",
        ])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setAlternatingRowColors(True)
        header = self.mapping_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((52, 150, 180, 210, 100, 100, 90, 95, 100, 105)):
            self.mapping_table.setColumnWidth(column, width)
        self.mapping_table.itemChanged.connect(self._mapping_item_changed)
        mapping_layout.addWidget(self.mapping_table, 1)
        self.mapping_card.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )

        self.results_panel = self._build_results_panel()
        self.results_panel.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
        self.setup_splitter = QSplitter(Qt.Orientation.Vertical)
        self.setup_splitter.setChildrenCollapsible(False)
        self.setup_splitter.setHandleWidth(10)
        self.setup_splitter.addWidget(inputs)
        self.setup_splitter.addWidget(self.mapping_card)
        self.setup_splitter.addWidget(self.results_panel)
        self.setup_splitter.setSizes([430, 190, 520])
        self.setup_splitter.setMinimumHeight(1120)

        self.setup_scroll = QScrollArea()
        self.setup_scroll.setObjectName("matchingSetupScroll")
        self.setup_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setup_scroll.setWidgetResizable(True)
        self.setup_scroll.setWidget(self.setup_splitter)
        layout.addWidget(self.setup_scroll, 1)
        self.absolute_bias.toggled.connect(self._bias_view_changed)
        self.percent_bias.toggled.connect(self._bias_view_changed)
        return page

    def _table_card(self, title, subtitle, model):
        card = QFrame(objectName="sheetCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 12)
        heading = QHBoxLayout()
        guidance = subtitle
        if isinstance(model, SheetModel):
            guidance += "\nRow 1 = headers · Ctrl+V paste · Ctrl+Z undo."
        heading.addWidget(help_title_label(title, guidance))
        heading.addStretch()
        layout.addLayout(heading)
        if isinstance(model, SheetModel):
            view = SheetView(model)
            duplicate_banner = DuplicateHeaderBanner(model)
            layout.addWidget(duplicate_banner)
        else:
            view = QTableView()
            duplicate_banner = None
            view.setModel(model)
            view.setAlternatingRowColors(True)
            view.setWordWrap(False)
            view.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
            view.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
            view.horizontalHeader().setDefaultSectionSize(140)
        layout.addWidget(view, 1)
        footer = QHBoxLayout()
        source = _label("No data", "hint")
        footer.addWidget(source)
        footer.addStretch()
        layout.addLayout(footer)
        return card, view, source, duplicate_banner

    def _build_results_panel(self):
        panel = QFrame(objectName="panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(14)
        self.result_status = _label("", "hint")
        self.result_status.hide()

        self.results_tabs = QTabWidget()
        self.plot_groups_widget = QWidget()
        self.plot_groups_layout = QVBoxLayout(self.plot_groups_widget)
        self.plot_groups_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_groups_layout.setSpacing(8)
        self.plot_groups_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.plot_groups = {}
        self.empty_plots_hint = _label(
            "Run an analysis to show every mapped parameter below.", "hint"
        )
        self.plot_groups_layout.addWidget(self.empty_plots_hint)
        self.results_tabs.addTab(self.plot_groups_widget, "All parameter plots")

        self.wafer_groups_widget = QWidget()
        self.wafer_groups_layout = QVBoxLayout(self.wafer_groups_widget)
        self.wafer_groups_layout.setContentsMargins(0, 0, 0, 0)
        self.wafer_groups_layout.setSpacing(16)
        self.wafer_groups_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.empty_wafer_hint = _label(
            "Run a KLA or NOVA analysis to show single-wafer metrics.", "hint"
        )
        self.wafer_groups_layout.addWidget(self.empty_wafer_hint)
        self.results_tabs.addTab(self.wafer_groups_widget, "Single-wafer metrics")
        layout.addWidget(self.results_tabs, 1)
        panel.setMinimumHeight(520)
        return panel

    def parameter_order(self):
        """Return the user-visible parameter card order."""
        return tuple(self._parameter_order)

    def _reconciled_parameter_order(self, names):
        names = tuple(names)
        retained = [name for name in self._parameter_order if name in names]
        retained.extend(name for name in names if name not in retained)
        return tuple(retained)

    def move_parameter(self, parameter, target, before=True):
        """Move one parameter card relative to another, as a drag/drop operation."""
        order = list(self._reconciled_parameter_order(self.plot_groups))
        if parameter not in order or target not in order or parameter == target:
            return
        order.remove(parameter)
        target_index = order.index(target)
        order.insert(target_index if before else target_index + 1, parameter)
        self._parameter_order = order
        self._apply_parameter_order()

    def _apply_parameter_order(self):
        for layout, key in (
            (self.plot_groups_layout, "card"),
            (self.wafer_groups_layout, "wafer_card"),
        ):
            for parameter in self._parameter_order:
                group = self.plot_groups.get(parameter)
                if group is None:
                    continue
                widget = group[key]
                layout.removeWidget(widget)
                layout.addWidget(widget)

    def clear_parameter_drop_previews(self):
        for group in self.plot_groups.values():
            group["card"]._show_drop_position(None)

    @staticmethod
    def _plot_widget(bottom, left, plot_class=InteractivePlotWidget):
        plot = plot_class(background=None, frame_tick_length=3)
        plot.showGrid(x=True, y=True, alpha=0.18)
        plot.setLabel("bottom", bottom)
        plot.setLabel("left", left)
        plot.setToolTip(
            "Ctrl+scroll to zoom · Drag a box to zoom · Right-drag to pan · "
            "Ordinary scrolling moves the page · "
            "Double-click to fit this plot"
        )
        plot_item = plot.getPlotItem()
        plot_item.layout.setRowFixedHeight(0, _MatchPlotWidget.HEADER_HEIGHT)
        view = plot_item.getViewBox()
        view.setMouseMode(pg.ViewBox.RectMode)
        frame_pen = pg.mkPen(plot.palette().color(plot.foregroundRole()))
        view.setBorder(None)
        for axis_name in ("top", "right", "bottom", "left"):
            axis = plot_item.getAxis(axis_name)
            axis.setPen(frame_pen)
            axis.setTextPen(frame_pen)
        return plot

    def paste_reference(self):
        try:
            self.set_reference_frame(clipboard_frame(QApplication.clipboard().text()), "Clipboard")
        except Exception as error:
            QMessageBox.warning(self, "Reference", str(error))

    def paste_raw(self):
        try:
            self.set_raw_frame(clipboard_frame(QApplication.clipboard().text()), "Clipboard")
        except Exception as error:
            QMessageBox.warning(self, "Raw Data", str(error))

    def set_reference_frame(self, frame, source="Reference"):
        self._validate_input_frame(frame, "Reference")
        view_state = self._capture_setup_view_state()
        mapping_state = self._mapping_state()
        self.reference_frame = frame.reset_index(drop=True)
        self._load_input_sheet(self.reference_model, self.reference_frame)
        self._input_sheet_errors["reference"] = ""
        self.reference_source.setText(self._source_text(source, self.reference_frame))
        self._populate_mappings(mapping_state)
        self._analysis_input_changed(view_state=view_state)

    def set_raw_frame(self, frame, source="Raw Data"):
        if self.reference_frame.empty:
            raise ValueError("Paste the Reference table before Raw Data.")
        mode = self.result_mode.currentText().lower()
        title = "Final Raw Data" if mode == "final" else "Raw Data"
        self._validate_input_frame(frame, title)
        view_state = self._capture_setup_view_state()
        mapping_state = self._mapping_state()
        stored = frame.reset_index(drop=True)
        if mode == "final":
            self.final_match_frame = stored
            model = self.final_raw_model
            error_key = "final_raw"
        else:
            self.raw_frame = stored
            model = self.raw_model
            error_key = "raw"
        self._load_input_sheet(model, stored)
        self._input_sheet_errors[error_key] = ""
        self._raw_sources[mode] = self._source_text(source, stored)
        self.raw_source.setText(self._raw_sources[mode])
        self._populate_mappings(mapping_state)
        self._analysis_input_changed(view_state=view_state)

    def _load_input_sheet(self, model, frame):
        self._loading_input_sheets = True
        try:
            model.load(frame)
        finally:
            self._loading_input_sheets = False

    def _input_sheet_changed(self, name):
        """Synchronize an editable grid with the matching domain frames."""
        if self._loading_input_sheets:
            return
        view_state = self._capture_setup_view_state()
        mapping_state = self._mapping_state()
        if name == "reference":
            model = self.reference_model
            title = "Reference"
        elif name == "final_raw":
            model = self.final_raw_model
            title = "Final Raw Data"
        else:
            model = self.raw_model
            title = "Raw Data"
        try:
            frame = model.frame().reset_index(drop=True)
            if not frame.empty:
                self._validate_input_frame(frame, title)
            error = ""
        except ValueError as exc:
            frame = pd.DataFrame()
            error = str(exc)
        self._input_sheet_errors[name] = error
        if name == "reference":
            self.reference_frame = frame
            source = self.reference_source
        elif name == "final_raw":
            self.final_match_frame = frame
            source = self.raw_source
            self._raw_sources["final"] = (
                "No data" if frame.empty else self._source_text("Edited", frame)
            )
        else:
            self.raw_frame = frame
            source = self.raw_source
            self._raw_sources["preview"] = (
                "No data" if frame.empty else self._source_text("Edited", frame)
            )
        source.setText(
            f"Fix table · {error}" if error
            else ("No data" if frame.empty else self._source_text("Edited", frame))
        )
        self._populate_mappings(mapping_state)
        self._analysis_input_changed(view_state=view_state)

    def _active_raw_frame(self):
        return (
            self.final_match_frame
            if self.result_mode.currentText().lower() == "final"
            else self.raw_frame
        )

    def _capture_setup_view_state(self):
        if not hasattr(self, "setup_splitter"):
            return None
        return (
            tuple(self.setup_splitter.sizes()),
            self.setup_scroll.verticalScrollBar().value(),
        )

    def _analysis_input_changed(self, *_, view_state=None):
        """Refresh valid post-run edits without blanking plots or layout first."""
        if self._auto_run_enabled:
            if self._pending_auto_view_state is None:
                self._pending_auto_view_state = (
                    view_state or self._capture_setup_view_state()
                )
            self._update_state()
            self._queue_auto_analysis()
        else:
            self._invalidate_analysis()

    def _raw_table_pasted(self):
        """Re-run a valid workbook after the user has opted in by running once."""
        self._queue_auto_analysis()

    def _queue_auto_analysis(self):
        """Coalesce valid post-run edits into one layout-preserving analysis."""
        if not self._auto_run_enabled or self._auto_run_pending:
            return
        self._auto_run_pending = True
        QTimer.singleShot(0, self._run_paste_analysis)

    def _run_paste_analysis(self):
        self._auto_run_pending = False
        view_state = self._pending_auto_view_state
        self._pending_auto_view_state = None
        if not self._auto_run_enabled or not self.analyze_button.isEnabled():
            if view_state is not None:
                sizes, scroll_value = view_state
                self._restore_setup_view_state(sizes, scroll_value)
            return
        try:
            self.run_analysis()
            if view_state is not None:
                sizes, scroll_value = view_state
                self._restore_setup_splitter_layout(sizes)
                QTimer.singleShot(
                    0,
                    lambda saved_sizes=sizes, saved_scroll=scroll_value:
                    self._restore_setup_view_state(saved_sizes, saved_scroll),
                )
        except Exception as error:
            self._set_status(
                f"Automatic analysis could not run: {error}", warning=True
            )

    def _mapping_state(self):
        """Capture complete and incomplete mapping edits across input-table changes."""
        state = {}
        for row in range(self.mapping_table.rowCount()):
            use = self.mapping_table.item(row, 0)
            name = self.mapping_table.item(row, 1)
            reference = self.mapping_table.item(row, 2)
            picker = self.mapping_table.cellWidget(row, 3)
            if reference is None:
                continue
            requested_raw = ""
            if picker is not None:
                requested_raw = picker.property("requestedRawColumn")
                if requested_raw is None:
                    requested_raw = picker.currentText()
            state[reference.text()] = {
                "checked": bool(
                    use is not None
                    and use.checkState() == Qt.CheckState.Checked
                ),
                "name": name.text().strip() if name is not None else "",
                "raw_column": str(requested_raw or ""),
            }
        return state

    def _clear_stage_frames(self):
        self.preview_frame = pd.DataFrame()
        self.final_frame = pd.DataFrame()
        self.preview_model.set_frame(self.preview_frame)
        self.final_model.set_frame(self.final_frame)

    def set_preview_frame(self, frame, source="Preview FullMap"):
        if self.raw_frame.empty:
            raise ValueError("Paste the matching Raw Data before Preview FullMap.")
        self._validate_input_frame(frame, "Preview FullMap")
        self.preview_frame = frame.reset_index(drop=True)
        self.preview_map_frame = None
        self.preview_model.set_frame(self.preview_frame)
        self._update_state()

    def set_final_frame(self, frame, source="Final Raw Data"):
        if self.raw_frame.empty:
            raise ValueError("Paste the matching Raw Data before Final Raw Data.")
        self._validate_input_frame(frame, "Final Raw Data")
        self.final_frame = frame.reset_index(drop=True)
        self.final_map_frame = None
        self.final_model.set_frame(self.final_frame)
        self._update_state()

    @staticmethod
    def _validate_input_frame(frame, name):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"{name} must contain headers and at least one data row.")
        if len(frame) > MAX_ROWS:
            raise ValueError(f"{name} supports at most {MAX_ROWS:,} rows.")
        if not frame.columns.is_unique:
            raise ValueError(f"{name} column names must be unique.")

    @staticmethod
    def _source_text(source, frame):
        return f"{source} · {len(frame):,} rows × {len(frame.columns)} columns"

    def _populate_mappings(self, selected=None):
        selected = selected or ()
        if isinstance(selected, dict):
            selected_by_reference = dict(selected)
        else:
            selected_by_reference = {
                mapping.reference_column: {
                    "checked": True,
                    "name": mapping.name,
                    "raw_column": mapping.raw_column,
                }
                for mapping in selected
            }
        raw_frame = self._active_raw_frame()
        suggestions = MatchWorkbook.suggest_mappings(self.reference_frame, raw_frame)
        suggestion_by_reference = {mapping.reference_column: mapping for mapping in suggestions}
        numeric_columns = set(inspect_table(self.reference_frame)[2])
        reference_columns = [
            str(column)
            for column in self.reference_frame.columns
            if column in numeric_columns
            or str(column).strip().lower().endswith(" reference")
        ]
        self.mapping_table.blockSignals(True)
        self.mapping_table.setRowCount(len(reference_columns))
        for row, reference_column in enumerate(reference_columns):
            default_name = (
                reference_column[:-len(" Reference")].strip()
                if reference_column.strip().lower().endswith(" reference")
                else reference_column.strip()
            )
            mapping_state = selected_by_reference.get(reference_column)
            suggestion = suggestion_by_reference.get(reference_column)
            configured = bool(
                mapping_state
                and (
                    mapping_state.get("checked")
                    or mapping_state.get("raw_column")
                    or mapping_state.get("name", default_name) != default_name
                )
            )
            if not configured and suggestion is not None:
                mapping_state = {
                    "checked": True,
                    "name": suggestion.name,
                    "raw_column": suggestion.raw_column,
                }
            mapping_state = mapping_state or {
                "checked": False,
                "name": default_name,
                "raw_column": "",
            }
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            use.setCheckState(
                Qt.CheckState.Checked
                if mapping_state["checked"]
                else Qt.CheckState.Unchecked
            )
            self.mapping_table.setItem(row, 0, use)
            self.mapping_table.setItem(
                row,
                1,
                QTableWidgetItem(mapping_state["name"] or default_name),
            )
            reference_item = QTableWidgetItem(reference_column)
            reference_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.mapping_table.setItem(row, 2, reference_item)
            raw_picker = QComboBox()
            raw_picker.addItem("")
            raw_picker.addItems([str(column) for column in raw_frame.columns])
            requested_raw = mapping_state["raw_column"]
            raw_picker.setProperty("requestedRawColumn", requested_raw)
            if requested_raw in raw_frame.columns:
                raw_picker.setCurrentText(requested_raw)
            raw_picker.setToolTip(
                "Choose a Raw Data column for this Reference parameter."
            )
            raw_picker.currentTextChanged.connect(
                lambda text, picker=raw_picker: self._raw_mapping_changed(
                    picker, text
                )
            )
            self.mapping_table.setCellWidget(row, 3, raw_picker)
            for column in range(4, 10):
                result_item = QTableWidgetItem("")
                result_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                self.mapping_table.setItem(row, column, result_item)
        self.mapping_table.blockSignals(False)
        self._sync_select_all_mappings()

    def _raw_mapping_changed(self, picker, text):
        picker.setProperty("requestedRawColumn", text)
        self._analysis_input_changed()

    def _mapping_item_changed(self, item):
        if item is not None and item.column() == 0:
            self._sync_select_all_mappings()
        self._analysis_input_changed()

    def _set_all_mappings_checked(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.mapping_table.blockSignals(True)
        try:
            for row in range(self.mapping_table.rowCount()):
                item = self.mapping_table.item(row, 0)
                if item is not None:
                    item.setCheckState(state)
        finally:
            self.mapping_table.blockSignals(False)
        self._sync_select_all_mappings()
        self._analysis_input_changed()

    def _sync_select_all_mappings(self):
        row_count = self.mapping_table.rowCount()
        all_checked = row_count > 0 and all(
            self.mapping_table.item(row, 0) is not None
            and self.mapping_table.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(row_count)
        )
        self.select_all_mappings.blockSignals(True)
        self.select_all_mappings.setEnabled(row_count > 0)
        self.select_all_mappings.setChecked(all_checked)
        self.select_all_mappings.blockSignals(False)

    def selected_mappings(self):
        raw_frame = self._active_raw_frame()
        mappings = []
        for row in range(self.mapping_table.rowCount()):
            use = self.mapping_table.item(row, 0)
            if use is None or use.checkState() != Qt.CheckState.Checked:
                continue
            name = self.mapping_table.item(row, 1).text().strip()
            reference_column = self.mapping_table.item(row, 2).text()
            raw_column = self.mapping_table.cellWidget(row, 3).currentText()
            if not raw_column or raw_column not in raw_frame.columns:
                raise ValueError(f"Choose a Raw Data column for {reference_column}.")
            mappings.append(ParameterMapping(name, reference_column, raw_column))
        if not mappings:
            raise ValueError("Select at least one parameter mapping.")
        return tuple(mappings)

    def _selected_bias_views(self):
        views = []
        if self.absolute_bias.isChecked():
            views.append("absolute")
        if self.percent_bias.isChecked():
            views.append("percent")
        return tuple(views)

    def _bias_view_changed(self, _checked):
        if not self._selected_bias_views():
            checkbox = self.sender()
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)
        views = self._selected_bias_views()
        if self._primary_bias_mode not in views:
            self._primary_bias_mode = views[0]
        if self.result is not None:
            self._draw_all_parameters()

    def _clear_mapping_results(self):
        self.mapping_table.blockSignals(True)
        for row in range(self.mapping_table.rowCount()):
            for column in range(4, 10):
                item = self.mapping_table.item(row, column)
                if item is not None:
                    item.setText("")
                    self._style_mapping_metric(item, "", None)
        self.mapping_table.blockSignals(False)

    def _show_mapping_results(self):
        if self.result is None:
            self._clear_mapping_results()
            return
        summaries = {
            str(row["Reference column"]): row
            for _, row in self.result.summary.iterrows()
        }
        fields = (
            "Slope", "Intercept", "R²", "Valid pairs", "Match type", "Result mode"
        )
        self.mapping_table.blockSignals(True)
        for row in range(self.mapping_table.rowCount()):
            reference_item = self.mapping_table.item(row, 2)
            summary = summaries.get(reference_item.text()) if reference_item else None
            for column, field in enumerate(fields, start=4):
                item = self.mapping_table.item(row, column)
                value = None if summary is None else summary[field]
                if value is None or pd.isna(value):
                    text = ""
                elif isinstance(value, (float, np.floating)):
                    text = f"{float(value):.8g}"
                else:
                    text = str(value)
                item.setText(text)
                self._style_mapping_metric(item, field, value)
        self.mapping_table.blockSignals(False)

    def _style_mapping_metric(self, item, field, value):
        """Apply accessible threshold styling without changing numeric text."""
        item.setBackground(QBrush())
        item.setForeground(QBrush())
        item.setToolTip("")
        font = item.font()
        font.setBold(False)
        item.setFont(font)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if not np.isfinite(number):
            return
        message = ""
        if field == "Slope" and (number < 0.9 or number > 1.1):
            message = "Slope is outside the accepted 0.9–1.1 range."
        elif field == "R²" and number < 0.9:
            message = "R² is below 0.9."
        if not message:
            return
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        item.setBackground(QColor("#4a1822" if dark else "#fff0f1"))
        item.setForeground(QColor("#ffb4bd" if dark else "#a3132b"))
        item.setToolTip(message)
        font.setBold(True)
        item.setFont(font)

    def _clear_plot_groups(self):
        for layout in (self.plot_groups_layout, self.wafer_groups_layout):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self.plot_groups.clear()
        self.results_panel.setMinimumHeight(520)
        self.setup_splitter.setMinimumHeight(1120)

    def _show_empty_plot_hint(self, text):
        self._clear_plot_groups()
        self.empty_plots_hint = _label(text, "hint")
        self.plot_groups_layout.addWidget(self.empty_plots_hint)
        self.empty_wafer_hint = _label(
            "Run a KLA or NOVA analysis to show single-wafer metrics.", "hint"
        )
        self.wafer_groups_layout.addWidget(self.empty_wafer_hint)

    def _invalidate_analysis(self, *_):
        if self.result is None and self.workbook is None:
            self._update_state()
            return
        self.result = None
        self.workbook = None
        self.summary_model.set_frame(pd.DataFrame())
        self._show_empty_plot_hint("Settings changed. Run the analysis again.")
        self._clear_mapping_results()
        self.result_status.setText("Settings changed. Run the analysis again.")
        self._update_state()

    def _update_state(self, *_):
        has_reference = not self.reference_frame.empty
        raw_frame = self._active_raw_frame()
        has_raw = not raw_frame.empty
        self.raw_view.setEnabled(has_reference)
        valid_rows = has_reference and has_raw and len(self.reference_frame) == len(raw_frame)
        has_mapping = False
        missing_mapping_columns = []
        if valid_rows:
            for row in range(self.mapping_table.rowCount()):
                item = self.mapping_table.item(row, 0)
                picker = self.mapping_table.cellWidget(row, 3)
                if item and item.checkState() == Qt.CheckState.Checked:
                    if picker and picker.currentText() in raw_frame.columns:
                        has_mapping = True
                    else:
                        reference = self.mapping_table.item(row, 2)
                        if reference is not None:
                            missing_mapping_columns.append(reference.text())
        has_mapping = has_mapping and not missing_mapping_columns
        self.analyze_button.setEnabled(bool(valid_rows and has_mapping))
        self.save_button.setEnabled(bool(valid_rows and has_mapping))
        self.export_button.setEnabled(self.result is not None)
        self.images_button.setEnabled(self.result is not None)
        self.preview_open_button.setEnabled(self.result is not None)
        self.final_open_button.setEnabled(self.result is not None)
        self.preview_dynamic_button.setEnabled(self.result is not None)
        self.final_dynamic_button.setEnabled(self.result is not None)
        self.correlation_button.setEnabled(bool(valid_rows and has_mapping))
        self._update_mode_actions()
        raw_error_key = (
            "final_raw"
            if self.result_mode.currentText().lower() == "final"
            else "raw"
        )
        input_error = (
            self._input_sheet_errors["reference"]
            or self._input_sheet_errors[raw_error_key]
        )
        warning = False
        if input_error:
            message = input_error
            warning = True
        elif not has_reference:
            message = "Paste a Reference table to begin."
        elif not has_raw:
            prefix = "Final Raw Data" if raw_error_key == "final_raw" else "Raw Data"
            message = (
                f"{prefix} is empty. Parameter mappings were kept. "
                f"Paste the row-aligned {prefix}, then choose a Raw Data column "
                "for each selected parameter."
            )
            warning = True
        elif len(self.reference_frame) != len(raw_frame):
            message = (f"Row count differs: Reference {len(self.reference_frame):,}; "
                       f"Raw Data {len(raw_frame):,}.")
            warning = True
        elif missing_mapping_columns:
            message = (
                "Choose a Raw Data column for: "
                + ", ".join(missing_mapping_columns)
                + "."
            )
            warning = True
        elif not has_mapping:
            message = "Select at least one valid parameter mapping."
            warning = True
        else:
            message = "Ready to run. Rows will be matched from top to bottom."
        self._set_status(message, warning=warning)

    def _set_status(self, message, warning=False):
        """Show blocking guidance as a visible warning bar, not muted helper text."""
        role = "warning" if warning else "hint"
        if self.status.objectName() != role:
            self.status.setObjectName(role)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        self.status.setText(message if warning else "")
        self.status.setVisible(bool(warning and message))

    def current_workbook(self):
        mappings = self.selected_mappings()
        active_raw = self._active_raw_frame()
        if self.result_mode.currentText().lower() == "final" and active_raw.empty:
            raise ValueError("Paste Final Raw Data before running Final analysis.")
        preview_raw = self.raw_frame if not self.raw_frame.empty else active_raw
        parameter_order = self._reconciled_parameter_order(
            mapping.name for mapping in mappings
        )
        return MatchWorkbook(
            reference=self.reference_frame,
            raw=preview_raw,
            mappings=mappings,
            match_type=self.match_type.currentText(),
            result_mode=self.result_mode.currentText().lower(),
            bias_mode=self._primary_bias_mode,
            bias_views=self._selected_bias_views(),
            preview_raw=None if self.preview_frame.empty else self.preview_frame,
            final_raw=None if self.final_frame.empty else self.final_frame,
            final_match_raw=(
                None if self.final_match_frame.empty else self.final_match_frame
            ),
            preview_map=self.preview_map_frame,
            final_map=self.final_map_frame,
            preview_dynamic=self.preview_dynamic_frame,
            final_dynamic=self.final_dynamic_frame,
            workspace_selections={
                "map": self._map_selection_states,
                "dynamic": self._dynamic_selection_states,
            },
            setup_splitter_sizes=tuple(self.setup_splitter.sizes()),
            parameter_order=parameter_order,
        )

    @staticmethod
    def _default_wafer_window_factory():
        from .window import MainWindow
        return MainWindow()

    @staticmethod
    def _default_dynamic_window_factory():
        from .dynamic_window import DynamicWindow
        return DynamicWindow()

    @staticmethod
    def _default_correlation_window_factory():
        from .correlation_window import CorrelationWindow
        return CorrelationWindow()

    def open_correlation_workspace(self):
        """Open the active WKB sources without combining or renaming tables."""
        mappings = self.selected_mappings()
        raw = self._active_raw_frame()
        if self.reference_frame.empty or raw.empty:
            raise ValueError("Paste Reference and Raw Data before opening Correlation and Trend.")
        if not mappings:
            raise ValueError("Select at least one valid parameter mapping first.")
        mode = self.result_mode.currentText()
        workspace = self._correlation_window_factory()
        workspace.set_sources(self.reference_frame, raw, mappings, mode)
        if hasattr(workspace, "setWindowTitle"):
            workspace.setWindowTitle(f"{mode} Correlation and Trend")
        self._register_stage_workspace(workspace)
        workspace.show()
        return workspace

    def _open_correlation_clicked(self):
        try:
            self.open_correlation_workspace()
        except Exception as error:
            QMessageBox.warning(
                self, "Cannot open Correlation and Trend", str(error)
            )

    def open_stage_workspace(self, stage):
        if self.result is None:
            self.run_analysis()
        self.workbook = self.current_workbook()
        frame = self.workbook.stage_frame(stage)
        workspace = self._wafer_window_factory()
        title = f"{str(stage).title()} · Match Workbook"
        workspace.set_table(frame, title)
        self._bind_workspace_selection(workspace, "map", stage)
        self._capture_stage_map(stage, frame)
        model = getattr(workspace, "model", None)
        if model is not None and hasattr(model, "changed"):
            model.changed.connect(
                lambda stage_name=stage, stage_model=model:
                self._capture_stage_model(stage_name, stage_model)
            )
        self._configure_managed_close(workspace, "map", stage)
        if hasattr(workspace, "setWindowTitle"):
            workspace.setWindowTitle(f"{str(stage).title()} Wafer Map / Radius")
        self._register_stage_workspace(workspace, "map", stage)
        workspace.show()
        return workspace

    def _capture_stage_map(self, stage, frame):
        snapshot = frame.reset_index(drop=True).copy()
        if str(stage).lower() == "preview":
            self.preview_map_frame = snapshot
        else:
            self.final_map_frame = snapshot

    def _capture_stage_model(self, stage, model):
        try:
            frame = model.frame()
        except ValueError:
            return
        self._capture_stage_map(stage, frame)

    def _register_stage_workspace(self, workspace, kind=None, stage=None):
        """Track a child window and the WKB snapshot it owns, when applicable."""
        self._stage_windows.append(workspace)
        if kind is not None:
            self._stage_window_context[workspace] = (
                str(kind).lower(), str(stage).lower()
            )
        if hasattr(workspace, "destroyed"):
            workspace.destroyed.connect(
                lambda *_args, window=workspace:
                self._forget_stage_workspace(window)
            )

    def _forget_stage_workspace(self, workspace):
        if workspace in self._stage_windows:
            self._stage_windows.remove(workspace)
        self._stage_window_context.pop(workspace, None)

    def _capture_workspace_selection(self, kind, stage, state):
        if not isinstance(state, dict):
            return
        states = (
            self._map_selection_states
            if kind == "map"
            else self._dynamic_selection_states
        )
        saved = {
            "wafers": tuple(state.get("wafers", ())),
            "metrics": tuple(state.get("metrics", ())),
        }
        if kind == "map":
            for field in ("map_draw", "radius_draw"):
                if not isinstance(state.get(field), dict):
                    continue
                draw_state = state[field]
                saved[field] = {
                    "enabled": draw_state.get("enabled") is True,
                    "cells": tuple(
                        tuple(cell) for cell in draw_state.get("cells", ())
                    ),
                }
        states[str(stage).lower()] = saved

    def _bind_workspace_selection(self, workspace, kind, stage):
        """Keep a stage workspace's surviving choices across close/reopen."""
        stage = str(stage).lower()
        states = (
            self._map_selection_states
            if kind == "map"
            else self._dynamic_selection_states
        )
        signal = getattr(workspace, "selection_changed", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(
                lambda state, workspace_kind=kind, stage_name=stage:
                self._capture_workspace_selection(
                    workspace_kind, stage_name, state
                )
            )
        saved = states.get(stage)
        restore = getattr(workspace, "restore_selection", None)
        if saved is not None and callable(restore):
            restore(saved)
        current = getattr(workspace, "selection_state", None)
        if callable(current):
            self._capture_workspace_selection(kind, stage, current())

    def _configure_managed_close(self, workspace, kind, stage):
        setter = getattr(workspace, "set_managed_close_handler", None)
        if not callable(setter):
            return
        setter(
            lambda frame, workspace_kind=kind, stage_name=stage:
            self._save_managed_workspace_on_close(
                workspace_kind, stage_name, frame
            )
        )

    def _save_managed_workspace_on_close(self, kind, stage, frame):
        if kind == "map":
            self._capture_stage_map(stage, frame)
        else:
            self._capture_stage_dynamic(stage, frame)
        self.workbook = self.current_workbook()
        if self.workbook_path is not None:
            self.save_workbook(self.workbook_path)

    def _capture_managed_stage_workspace(self, workspace):
        """Copy a managed child's live state before either window is destroyed."""
        context = self._stage_window_context.get(workspace)
        if context is None:
            return
        kind, stage = context
        model = getattr(workspace, "model", None)
        frame_getter = getattr(model, "frame", None)
        if callable(frame_getter):
            frame = frame_getter()
            if kind == "map":
                self._capture_stage_map(stage, frame)
            else:
                self._capture_stage_dynamic(stage, frame)
        selection_getter = getattr(workspace, "selection_state", None)
        if callable(selection_getter):
            self._capture_workspace_selection(
                kind, stage, selection_getter()
            )

    @staticmethod
    def _deleted_qt_object(error):
        return (
            isinstance(error, RuntimeError)
            and "has been deleted" in str(error)
        )

    def _save_stage_workspaces_before_close(self, workspaces):
        for workspace in workspaces:
            try:
                self._capture_managed_stage_workspace(workspace)
            except RuntimeError as error:
                if not self._deleted_qt_object(error):
                    raise
                self._forget_stage_workspace(workspace)
        if self.workbook_path is not None:
            self.save_workbook(self.workbook_path)
            return
        # An unsaved Match window has no WKB target. Keep the in-memory
        # workbook coherent and allow its owned children to close with it.
        self.workbook = self.current_workbook()
        for workspace in workspaces:
            model = getattr(workspace, "model", None)
            undo = getattr(model, "undo", None)
            if undo is not None:
                undo.setClean()

    def _close_stage_workspaces(self, workspaces):
        for workspace in workspaces:
            context = self._stage_window_context.get(workspace)
            if context is not None:
                setter = getattr(workspace, "set_managed_close_handler", None)
                if callable(setter):
                    setter(None)
            close = getattr(workspace, "close", None)
            if not callable(close):
                self._forget_stage_workspace(workspace)
                continue
            try:
                closed = close()
            except RuntimeError as error:
                if not self._deleted_qt_object(error):
                    raise
                self._forget_stage_workspace(workspace)
                continue
            if closed is False:
                if context is not None:
                    self._configure_managed_close(
                        workspace, context[0], context[1]
                    )
                raise RuntimeError("An analysis workspace refused to close.")
            delete_later = getattr(workspace, "deleteLater", None)
            if callable(delete_later):
                delete_later()
            self._forget_stage_workspace(workspace)

    def closeEvent(self, event):
        """Persist and close every analysis child before Qt deletes this WKB."""
        workspaces = tuple(self._stage_windows)
        if not workspaces:
            event.accept()
            return
        try:
            self._save_stage_workspaces_before_close(workspaces)
            self._close_stage_workspaces(workspaces)
        except Exception as error:
            LOGGER.exception("Cannot close Match Workbook and its workspaces")
            QMessageBox.warning(
                self,
                "Cannot close Match Workbook",
                "The open analysis workspaces could not be saved and closed "
                f"with this Match Workbook.\n\n{error}",
            )
            event.ignore()
            return
        event.accept()

    def _open_stage_clicked(self, stage):
        try:
            self.open_stage_workspace(stage)
        except Exception as error:
            QMessageBox.warning(self, f"Cannot open {stage.title()}", str(error))

    def open_dynamic_workspace(self, stage):
        if self.result is None:
            self.run_analysis()
        self.workbook = self.current_workbook()
        frame = self.workbook.dynamic_frame(stage)
        workspace = self._dynamic_window_factory()
        title = f"{str(stage).title()} Dynamic · Match Workbook"
        workspace.set_table(frame, title)
        self._bind_workspace_selection(workspace, "dynamic", stage)
        model = getattr(workspace, "model", None)
        if model is not None:
            self._capture_dynamic_model(stage, model)
            if hasattr(model, "changed"):
                model.changed.connect(
                    lambda stage_name=stage, stage_model=model:
                    self._capture_dynamic_model(stage_name, stage_model)
                )
        else:
            self._capture_stage_dynamic(stage, frame)
        self._configure_managed_close(workspace, "dynamic", stage)
        if hasattr(workspace, "setWindowTitle"):
            workspace.setWindowTitle(f"{str(stage).title()} Dynamic")
        self._register_stage_workspace(workspace, "dynamic", stage)
        workspace.show()
        return workspace

    def _capture_stage_dynamic(self, stage, frame):
        snapshot = frame.reset_index(drop=True).copy()
        if str(stage).lower() == "preview":
            self.preview_dynamic_frame = snapshot
        else:
            self.final_dynamic_frame = snapshot

    def _capture_dynamic_model(self, stage, model):
        try:
            frame = model.frame()
        except ValueError:
            return
        self._capture_stage_dynamic(stage, frame)

    def _open_dynamic_clicked(self, stage):
        try:
            self.open_dynamic_workspace(stage)
        except Exception as error:
            QMessageBox.warning(
                self, f"Cannot open {stage.title()} Dynamic", str(error)
            )

    def run_analysis(self):
        scroll_value = self.setup_scroll.verticalScrollBar().value()
        self.workbook = self.current_workbook()
        self.result = self.workbook.analyze()
        self._auto_run_enabled = True
        self._parameter_order = list(self.workbook.parameter_order)
        self.summary_model.set_frame(self.result.summary)
        self._show_mapping_results()
        self._result_descriptor = (
            f"{self.workbook.match_type} · {self.workbook.result_mode.title()} · "
            f"{len(self.result.parameter_names)} parameters"
        )
        self.result_status.setText(self._result_descriptor)
        self._draw_all_parameters()
        self._update_state()
        QTimer.singleShot(
            0,
            lambda value=scroll_value:
            self.setup_scroll.verticalScrollBar().setValue(value),
        )
        return self.result

    def _run_analysis_clicked(self):
        try:
            self.run_analysis()
            self._auto_run_enabled = True
        except Exception as error:
            QMessageBox.warning(self, "Cannot run analysis", str(error))

    def _draw_all_parameters(self):
        splitter_sizes = tuple(self.setup_splitter.sizes())
        self._clear_plot_groups()
        if self.result is None:
            self._show_empty_plot_hint("Run an analysis to see results.")
            return
        self._parameter_order = list(
            self._reconciled_parameter_order(self.result.parameter_names)
        )
        for parameter in self._parameter_order:
            group = self._create_plot_group(parameter)
            self.plot_groups[parameter] = group
            self.plot_groups_layout.addWidget(group["card"])
            self._draw_parameter_group(parameter, group)
            self.wafer_groups_layout.addWidget(group["wafer_card"])
        if not any(
            not group["wafer_card"].isHidden()
            for group in self.plot_groups.values()
        ):
            self.empty_wafer_hint = _label(
                "Single-wafer metrics are available for KLA and NOVA analyses.",
                "hint",
            )
            self.wafer_groups_layout.addWidget(self.empty_wafer_hint)
        self._resize_results_for_plot_groups()
        self._restore_setup_splitter_layout(splitter_sizes)
        self.result_status.setText(self._result_descriptor)

    def _create_plot_group(self, parameter):
        card = _ParameterCard(parameter, self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(12)

        heading = QHBoxLayout()
        heading.addWidget(_ParameterDragHandle(parameter, card))
        heading.addStretch()
        note = _label("", "hint")
        heading.addWidget(note)
        card_layout.addLayout(heading)

        plot_container = QWidget()
        plot_grid = QGridLayout(plot_container)
        plot_grid.setContentsMargins(0, 0, 0, 0)
        plot_grid.setHorizontalSpacing(14)
        plot_grid.setVerticalSpacing(16)
        primary_height = 330
        specs = [
            ("match", "PMISH", self.match_type.currentText()),
            ("trend", " ", ""),
        ]
        if self.absolute_bias.isChecked():
            specs.append(("bias", " ", "Bias (nm)"))
        if self.percent_bias.isChecked():
            specs.append(("bias-percent", " ", "Bias (%)"))
        plots = {}
        for index, (name, bottom, left) in enumerate(specs):
            if name == "match":
                plot_class = _MatchPlotWidget
            elif name == "trend":
                plot_class = _TrendPlotWidget
            else:
                plot_class = InteractivePlotWidget
            plot = self._plot_widget(bottom, left, plot_class=plot_class)
            plot.getPlotItem().setContentsMargins(6, 4, 8, 8)
            if name == "match":
                plot.setFixedWidth(510)
                horizontal_policy = QSizePolicy.Policy.Fixed
                plot_grid.setColumnMinimumWidth(index, 510)
            else:
                # Trend and bias plots share the space left after the fixed
                # Match plot. Their graphics remain interactive at narrower
                # widths, so do not force the workbook to scroll sideways.
                plot.setMinimumWidth(0)
                horizontal_policy = QSizePolicy.Policy.Ignored
                plot_grid.setColumnMinimumWidth(index, 0)
            plot.setFixedHeight(primary_height)
            plot.setSizePolicy(
                horizontal_policy, QSizePolicy.Policy.Fixed
            )
            plot_grid.addWidget(plot, 0, index)
            plot_grid.setColumnStretch(index, 0 if name == "match" else 5)
            if name in {"bias", "bias-percent"}:
                plot.getAxis("left").enableAutoSIPrefix(False)
            plots[name] = plot
        primary_width = 510
        plot_container.setMinimumWidth(0)
        match_title = plots["match"].title_label
        match_formula = plots["match"].formula_label
        mode = self.result_mode.currentText().lower()
        trend_card_key = (mode, parameter)
        trend_card_enabled = self._trend_card_state.get(
            trend_card_key, mode == "preview"
        )
        self._trend_card_state[trend_card_key] = trend_card_enabled
        trend_checkbox = plots["trend"].card_checkbox
        trend_checkbox.setChecked(trend_card_enabled)
        trend_checkbox.toggled.connect(
            lambda checked, name=parameter:
            self._trend_card_toggled(name, checked)
        )
        plot_container.setFixedHeight(primary_height)
        card_layout.addWidget(plot_container)

        wafer_card = QFrame(objectName="sheetCard")
        wafer_layout = QVBoxLayout(wafer_card)
        wafer_layout.setContentsMargins(12, 10, 12, 12)
        wafer_layout.setSpacing(10)
        wafer_layout.addWidget(_label(parameter, "panelTitle"))
        wafer_model = DataFrameModel(parent=wafer_card)
        wafer_view = QTableView()
        wafer_view.setModel(wafer_model)
        wafer_view.setAlternatingRowColors(True)
        wafer_view.setMaximumHeight(180)
        wafer_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        wafer_layout.addWidget(wafer_view)
        wafer_plots = QWidget()
        wafer_plot_layout = QGridLayout(wafer_plots)
        wafer_plot_layout.setContentsMargins(0, 0, 0, 0)
        wafer_plot_layout.setHorizontalSpacing(14)
        wafer_r2 = self._plot_widget("Wafer", "R²")
        wafer_slope = self._plot_widget("Wafer", "Slope")
        for column, plot in enumerate((wafer_r2, wafer_slope)):
            plot.setMinimumSize(360, 280)
            plot.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
            )
            wafer_plot_layout.addWidget(plot, 0, column)
        wafer_plots.setMinimumHeight(280)
        wafer_layout.addWidget(wafer_plots)
        wafer_card.hide()

        card.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        group = {
            "card": card,
            "note": note,
            "plots": plots,
            "match_title": match_title,
            "match_formula": match_formula,
            "primary_height": primary_height,
            "primary_width": primary_width,
            "wafer_card": wafer_card,
            "wafer_model": wafer_model,
            "wafer_r2": wafer_r2,
            "wafer_slope": wafer_slope,
            "trend_card_key": trend_card_key,
        }
        return group

    def _draw_parameter_group(self, parameter, group):
        data = self.result.series(parameter)
        card = self.result.card(parameter)
        mapping = next(
            (
                candidate
                for candidate in self.workbook.mappings
                if candidate.name == parameter
            ),
            None,
        )
        raw_column = mapping.raw_column if mapping is not None else parameter
        reference_all = data["Reference"].to_numpy(float)
        raw_all = data["Raw"].to_numpy(float)
        evaluated_all = data["Evaluated Value"].to_numpy(float)
        card_value_all = data["Card Value"].to_numpy(float)
        bias_all = data["Bias"].to_numpy(float)
        bias_percent_all = data["Bias %"].to_numpy(float)
        indices = extrema_sample_indices(
            reference_all, raw_all, evaluated_all, card_value_all,
            bias_all, bias_percent_all,
            limit=PLOT_LIMIT,
        )
        row = np.arange(1, len(data) + 1, dtype=float)[indices]
        reference = reference_all[indices]
        raw = raw_all[indices]
        evaluated = evaluated_all[indices]
        card_value = card_value_all[indices]
        bias = bias_all[indices]
        bias_percent = bias_percent_all[indices]
        display_note = ""
        if len(indices) < len(data):
            display_note = f" · display {len(indices):,}/{len(data):,}; calculations use all rows"
        group["note"].setText(
            f"{len(data):,} rows" if not display_note else display_note.removeprefix(" · ")
        )
        plots = group["plots"]
        try:
            measurement_ticks = list(self.result.measurement_ticks())
        except ValueError:
            measurement_ticks = []
        if measurement_ticks:
            tick_levels = [measurement_ticks]
            max_lines = max(label.count("\n") + 1 for _, label in measurement_ticks)
            axis_height = 42 + 16 * max_lines
            for plot in plots.values():
                plot.getAxis("bottom").setHeight(axis_height)
            for name in ("trend", "bias", "bias-percent"):
                plot = plots.get(name)
                if plot is None:
                    continue
                axis = plot.getAxis("bottom")
                axis.setTicks(tick_levels)

        match_plot = plots["match"]
        match_plot.addLegend(offset=(12, 12))
        valid = np.isfinite(raw) & np.isfinite(reference)
        fit_text = ""
        match_plot.plot(raw[valid], reference[valid], pen=None, symbol="o", symbolSize=5,
                        symbolBrush="#4f8bd6", symbolPen=None, name="Rows")
        if valid.any():
            low, high = float(np.min(raw[valid])), float(np.max(raw[valid]))
            x_line = np.array([low, high])
            y_line = card.slope * x_line + card.intercept
            match_plot.plot(
                x_line,
                y_line,
                pen=pg.mkPen("#e09f3e", width=2),
                name="Linear fit",
            )
            intercept_sign = "+" if card.intercept >= 0 else "-"
            fit_text = (
                f"y = {card.slope:.6g}x {intercept_sign} "
                f"{abs(card.intercept):.6g}\nR² = {card.r_squared:.6g}"
            )
        match_plot.set_match_heading(raw_column, fit_text)

        group["trend_data"] = (row, reference, raw, card_value)
        self._draw_trend_plot(parameter, group)

        bias_plot = plots.get("bias")
        if bias_plot is not None:
            bias_plot.plot(
                row,
                bias,
                pen=pg.mkPen("#4f8bd6", width=1.3),
                symbol="o",
                symbolSize=5,
                symbolBrush="#4f8bd6",
                symbolPen=None,
            )
            bias_plot.addLine(y=0, pen=pg.mkPen("#8a8f98", width=1, style=Qt.PenStyle.DashLine))
            bias_plot.setTitle("Bias")

        bias_percent_plot = plots.get("bias-percent")
        if bias_percent_plot is not None:
            bias_percent_plot.plot(
                row,
                bias_percent,
                pen=pg.mkPen("#4f8bd6", width=1.3),
                symbol="o",
                symbolSize=5,
                symbolBrush="#4f8bd6",
                symbolPen=None,
            )
            bias_percent_plot.addLine(
                y=0, pen=pg.mkPen("#8a8f98", width=1, style=Qt.PenStyle.DashLine)
            )
            bias_percent_plot.setTitle("Bias %")
        for primary_plot in plots.values():
            primary_plot.getPlotItem().layout.setRowFixedHeight(
                0, _MatchPlotWidget.HEADER_HEIGHT
            )
        self._draw_wafer_metrics(parameter, group)

    def _trend_card_toggled(self, parameter, checked):
        group = self.plot_groups.get(parameter)
        if group is None:
            return
        self._trend_card_state[group["trend_card_key"]] = bool(checked)
        self._draw_trend_plot(parameter, group)

    def _draw_trend_plot(self, parameter, group):
        """Redraw only Trend so its Card control feels immediate and stable."""
        if "trend_data" not in group:
            return
        trend_plot = group["plots"]["trend"]
        for item in tuple(trend_plot.listDataItems()):
            trend_plot.removeItem(item)
        if trend_plot.getPlotItem().legend is None:
            trend_plot.addLegend(offset=(12, 12))
        row, reference, raw, card_value = group["trend_data"]
        pmish = card_value if trend_plot.card_checkbox.isChecked() else raw
        trend_plot.plot(
            row,
            pmish,
            pen=pg.mkPen("#5b9bd5", width=2.2),
            symbol="o",
            symbolSize=5,
            symbolBrush="#5b9bd5",
            symbolPen=None,
            name="PMISH",
        )
        trend_plot.plot(
            row,
            reference,
            pen=pg.mkPen("#ed7d31", width=2.2),
            symbol="o",
            symbolSize=5,
            symbolBrush="#ed7d31",
            symbolPen=None,
            name=self.workbook.match_type,
        )
        trend_plot.setTitle("Trend")
        trend_plot.getPlotItem().layout.setRowFixedHeight(
            0, _MatchPlotWidget.HEADER_HEIGHT
        )

    def _draw_wafer_metrics(self, parameter, group):
        enabled = self.workbook.match_type in {"NOVA", "KLA"}
        if not enabled:
            group["wafer_card"].hide()
            return
        try:
            summary = self.result.wafer_summary(parameter)
        except ValueError:
            summary = pd.DataFrame()
            enabled = False
        group["wafer_card"].setVisible(enabled)
        group["wafer_model"].set_frame(summary)
        if summary.empty:
            return
        x = np.arange(len(summary), dtype=float)
        labels = [(int(index), str(wafer)) for index, wafer in enumerate(summary["Wafer"])]
        wafer_r2 = group["wafer_r2"]
        wafer_slope = group["wafer_slope"]
        wafer_r2.getAxis("bottom").setTicks([labels])
        wafer_slope.getAxis("bottom").setTicks([labels])
        r_squared = summary["R²"].to_numpy(float)
        slope = summary["Slope"].to_numpy(float)
        valid_r2 = np.isfinite(r_squared)
        valid_slope = np.isfinite(slope)
        if valid_r2.any():
            wafer_r2.plot(x[valid_r2], r_squared[valid_r2], pen=None,
                          symbol="o", symbolSize=8, symbolBrush="#4f8bd6")
        if valid_slope.any():
            wafer_slope.plot(x[valid_slope], slope[valid_slope], pen=None,
                             symbol="o", symbolSize=8, symbolBrush="#e09f3e")
        wafer_r2.setTitle("Single-wafer R²")
        wafer_slope.setTitle("Single-wafer slope")

    def _resize_results_for_plot_groups(self):
        total = 64
        wafer_total = 64
        # Older fixed-width layouts could leave this splitter wider than its
        # viewport after a re-run. Clear that constraint every time results
        # are rebuilt so four plots fit the visible workbook.
        self.setup_splitter.setMinimumWidth(0)
        for group in self.plot_groups.values():
            card_height = 54 + group["primary_height"]
            group["card"].setFixedHeight(card_height)
            total += card_height + self.plot_groups_layout.spacing()
            if not group["wafer_card"].isHidden():
                wafer_height = 520
                group["wafer_card"].setMinimumHeight(wafer_height)
                wafer_total += wafer_height + self.wafer_groups_layout.spacing()
        result_height = max(total, wafer_total)
        self.results_panel.setMinimumHeight(max(520, result_height))
        self.setup_splitter.setMinimumHeight(max(1120, 650 + result_height))

    def _restore_setup_splitter_layout(self, sizes):
        """Keep the two user-positioned upper boundaries while results expand."""
        if len(sizes) != self.setup_splitter.count() or len(sizes) != 3:
            return
        current_total = sum(self.setup_splitter.sizes())
        if current_total <= 0:
            return
        first, second, third = (max(0, int(size)) for size in sizes)
        available_for_results = current_total - first - second
        third = max(third, self.results_panel.minimumHeight(), available_for_results)
        self.setup_splitter.setSizes([first, second, third])
        self.setup_splitter.moveSplitter(first, 1)
        second_handle = first + self.setup_splitter.handleWidth() + second
        self.setup_splitter.moveSplitter(second_handle, 2)

    def _restore_setup_view_state(self, sizes, scroll_value):
        self._restore_setup_splitter_layout(sizes)
        self.setup_scroll.verticalScrollBar().setValue(scroll_value)

    def export_excel(self, path):
        """Export an optional human-readable workbook; WKB remains the primary store."""
        if self.result is None:
            self.run_analysis()
        else:
            self.workbook = self.current_workbook()
        target = Path(path)
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        derived = {}
        for parameter in self.result.parameter_names:
            series = self.result.series(parameter)
            for column in ("Card Value", "Evaluated Value", "Bias", "Bias %"):
                derived[f"{parameter} | {column}"] = series[column].to_numpy()
        result_frame = pd.DataFrame(derived)
        with pd.ExcelWriter(target, engine="openpyxl") as writer:
            self.result.summary.to_excel(writer, sheet_name="Summary", index=False)
            self.reference_frame.to_excel(writer, sheet_name="Reference", index=False)
            self.raw_frame.to_excel(writer, sheet_name="Raw Data", index=False)
            result_frame.to_excel(writer, sheet_name=self.workbook.result_mode.title(), index=False)
            if (
                self.workbook.preview_map is not None
                or self.workbook.preview_raw is not None
            ):
                self.workbook.stage_frame("preview").to_excel(
                    writer, sheet_name="Preview FullMap", index=False
                )
            if (
                self.workbook.final_map is not None
                or self.workbook.final_raw is not None
            ):
                self.workbook.stage_frame("final").to_excel(
                    writer, sheet_name="Final FullMap", index=False
                )
        self.result_status.setText(f"Exported {target.name}")
        return target

    def export_excel_dialog(self):
        try:
            default = str(Path.home() / f"matching-{self.workbook.result_mode if self.workbook else 'result'}.xlsx")
            path, _ = QFileDialog.getSaveFileName(self, "Export Excel", default, "Excel Workbook (*.xlsx)")
            if path:
                self.export_excel(path)
        except Exception as error:
            QMessageBox.warning(self, "Cannot export Excel", str(error))

    def save_plot_images(self, folder):
        """Save separate PNG files for every selected parameter and plot type."""
        if self.result is None:
            self.run_analysis()
        else:
            self.workbook = self.current_workbook()
            if set(self.plot_groups) != set(self.result.parameter_names):
                self._draw_all_parameters()
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        saved = []
        for parameter, group in self.plot_groups.items():
            plot_specs = list(group["plots"].items())
            if not group["wafer_card"].isHidden():
                plot_specs.extend([
                    ("single-wafer-r2", group["wafer_r2"]),
                    ("single-wafer-slope", group["wafer_slope"]),
                ])
            safe_parameter = _safe_filename(parameter)
            for suffix, widget in plot_specs:
                output = target / f"{safe_parameter}-{suffix}.png"
                if isinstance(widget, _MatchPlotWidget):
                    # The fit equation lives in the reserved QWidget heading,
                    # outside pyqtgraph's GraphicsScene. Capture the complete
                    # widget so the saved Match image matches the screen.
                    if not widget.grab().save(str(output), "PNG"):
                        raise OSError(f"Could not save {output}")
                else:
                    exporter = pg.exporters.ImageExporter(widget.getPlotItem())
                    exporter.parameters()["width"] = 1600
                    exporter.export(str(output))
                saved.append(output)
        self.result_status.setText(f"Saved {len(saved)} plot images")
        return tuple(saved)

    def save_images_dialog(self):
        try:
            folder = QFileDialog.getExistingDirectory(self, "Save plot images")
            if folder:
                self.save_plot_images(folder)
        except Exception as error:
            QMessageBox.warning(self, "Cannot save images", str(error))
    def save_workbook(self, path):
        workbook = self.current_workbook()
        saved = workbook.save(path)
        self.workbook = workbook
        self.workbook_path = Path(saved).resolve()
        self.reveal_wkb_action.setEnabled(True)
        for workspace in self._stage_windows:
            model = getattr(workspace, "model", None)
            if model is not None and hasattr(model, "undo"):
                model.undo.setClean()
        self._set_status(f"Saved {saved.name}")
        LOGGER.info("WKB saved: %s", Path(saved).resolve())
        return saved

    def _refresh_recent_wkb_menu(self):
        self.open_recent_menu.clear()
        if not self._recent_wkb_paths:
            empty_action = self.open_recent_menu.addAction("No Recent WKB")
            empty_action.setEnabled(False)
            return
        for index, path in enumerate(self._recent_wkb_paths, start=1):
            action = self.open_recent_menu.addAction(f"{index}. {Path(path).name}")
            action.setToolTip(str(path))
            action.triggered.connect(
                lambda _checked=False, recent_path=Path(path):
                self._open_recent_wkb(recent_path)
            )

    def _remember_recent_wkb(self, path):
        path = Path(path).resolve()
        fallback = [path] + [
            Path(item).resolve()
            for item in self._recent_wkb_paths
            if Path(item).resolve() != path
        ]
        try:
            self._recent_wkb_paths = list(remember_recent_wkb(path))
        except OSError as error:
            self._recent_wkb_paths = fallback[:10]
            LOGGER.warning("Recent WKB list could not be saved: %s", error)
        self._refresh_recent_wkb_menu()

    def _forget_recent_wkb(self, path):
        path = Path(path).resolve()
        fallback = [
            Path(item).resolve()
            for item in self._recent_wkb_paths
            if Path(item).resolve() != path
        ]
        try:
            self._recent_wkb_paths = list(forget_recent_wkb(path))
        except OSError as error:
            self._recent_wkb_paths = fallback
            LOGGER.warning("Recent WKB list could not be updated: %s", error)
        self._refresh_recent_wkb_menu()

    def _open_recent_wkb(self, path):
        path = Path(path).resolve()
        if not path.is_file():
            self._forget_recent_wkb(path)
            QMessageBox.warning(
                self,
                "Recent WKB not found",
                f"This workbook is no longer available:\n\n{path}",
            )
            return
        try:
            workbook = self.load_workbook(path)
            self._remember_recent_wkb(path)
            return workbook
        except Exception as error:
            LOGGER.exception("Cannot open recent WKB")
            QMessageBox.warning(self, "Cannot open WKB", str(error))

    def reveal_wkb_in_folder(self):
        path = self.workbook_path
        if path is None:
            return
        try:
            reveal_path_in_folder(path)
        except FileNotFoundError:
            self.reveal_wkb_action.setEnabled(False)
            self._forget_recent_wkb(path)
            QMessageBox.warning(
                self,
                "WKB not found",
                f"This workbook is no longer available:\n\n{path}",
            )
        except OSError as error:
            LOGGER.exception("Cannot reveal WKB")
            QMessageBox.warning(self, "Cannot reveal WKB", str(error))

    def save_wkb(self):
        if self.workbook_path is None:
            return self.save_wkb_dialog()
        try:
            saved = self.save_workbook(self.workbook_path)
            self._remember_recent_wkb(saved)
            return saved
        except Exception as error:
            LOGGER.exception("Cannot save WKB")
            QMessageBox.warning(self, "Cannot save WKB", str(error))

    def save_wkb_dialog(self):
        try:
            default = str(
                self.workbook_path
                if self.workbook_path is not None
                else Path.home() / "matching-analysis.wkb"
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Matching Workbook As",
                default,
                "Matching Workbook (*.wkb)",
            )
            if path:
                saved = self.save_workbook(path)
                self._remember_recent_wkb(saved)
                return saved
        except Exception as error:
            LOGGER.exception("Cannot save WKB")
            QMessageBox.warning(self, "Cannot save WKB", str(error))

    def load_workbook(self, path):
        workbook = MatchWorkbook.load(path)
        self.workbook_path = Path(path).resolve()
        self.reveal_wkb_action.setEnabled(True)
        self._map_selection_states = {
            stage: workbook.workspace_selections["map"][stage]
            for stage in ("preview", "final")
        }
        self._dynamic_selection_states = {
            stage: workbook.workspace_selections["dynamic"][stage]
            for stage in ("preview", "final")
        }
        self.reference_frame = workbook.reference
        self.raw_frame = workbook.raw
        self.final_match_frame = (
            pd.DataFrame()
            if workbook.final_match_raw is None
            else workbook.final_match_raw
        )
        if (
            self.final_match_frame.empty
            and workbook.result_mode == "final"
        ):
            # Schema 1/2 workbooks used the same Raw Data for both modes.
            # Copy it once into the new independent Final input on migration.
            self.final_match_frame = workbook.raw.copy()
        self.preview_frame = (
            pd.DataFrame() if workbook.preview_raw is None else workbook.preview_raw
        )
        self.final_frame = (
            pd.DataFrame() if workbook.final_raw is None else workbook.final_raw
        )
        self.preview_map_frame = (
            None if workbook.preview_map is None else workbook.preview_map.copy()
        )
        self.final_map_frame = (
            None if workbook.final_map is None else workbook.final_map.copy()
        )
        self.preview_dynamic_frame = (
            None
            if workbook.preview_dynamic is None
            else workbook.preview_dynamic.copy()
        )
        self.final_dynamic_frame = (
            None
            if workbook.final_dynamic is None
            else workbook.final_dynamic.copy()
        )
        self._load_input_sheet(self.reference_model, self.reference_frame)
        self._load_input_sheet(self.raw_model, self.raw_frame)
        self._load_input_sheet(self.final_raw_model, self.final_match_frame)
        self._input_sheet_errors = {
            "reference": "", "raw": "", "final_raw": "",
        }
        self.preview_model.set_frame(self.preview_frame)
        self.final_model.set_frame(self.final_frame)
        self.reference_source.setText(self._source_text(Path(path).name, self.reference_frame))
        self._raw_sources = {
            "preview": self._source_text(Path(path).name, self.raw_frame),
            "final": (
                "No data"
                if self.final_match_frame.empty
                else self._source_text(Path(path).name, self.final_match_frame)
            ),
        }
        self.match_type.setCurrentText(workbook.match_type)
        self.result_mode.setCurrentText(workbook.result_mode.title())
        self._show_raw_mode(workbook.result_mode)
        self.absolute_bias.blockSignals(True)
        self.percent_bias.blockSignals(True)
        self._primary_bias_mode = workbook.bias_mode
        self.absolute_bias.setChecked("absolute" in workbook.bias_views)
        self.percent_bias.setChecked("percent" in workbook.bias_views)
        self.absolute_bias.blockSignals(False)
        self.percent_bias.blockSignals(False)
        self._populate_mappings(workbook.mappings)
        self._parameter_order = list(workbook.parameter_order)
        self._update_state()
        self.workbook = self.current_workbook()
        self.result = self.workbook.analyze()
        self._auto_run_enabled = True
        self._result_descriptor = (
            f"{self.workbook.match_type} · {self.workbook.result_mode.title()} · "
            f"{len(self.result.parameter_names)} parameters"
        )
        self.result_status.setText(self._result_descriptor)
        self.summary_model.set_frame(self.result.summary)
        self._show_mapping_results()
        self._draw_all_parameters()
        if workbook.setup_splitter_sizes is not None:
            self._restore_setup_splitter_layout(workbook.setup_splitter_sizes)
            QTimer.singleShot(
                0,
                lambda sizes=workbook.setup_splitter_sizes:
                    self._restore_setup_splitter_layout(sizes),
            )
        QTimer.singleShot(0, lambda: self.setup_scroll.verticalScrollBar().setValue(0))
        LOGGER.info("WKB opened: %s", Path(path).resolve())
        self._update_state()
        return workbook

    def open_wkb_dialog(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, "Open Matching Workbook", "",
                                                  "Matching Workbook (*.wkb)")
            if path:
                self.load_workbook(path)
                self._remember_recent_wkb(path)
        except Exception as error:
            LOGGER.exception("Cannot open WKB")
            QMessageBox.warning(self, "Cannot open WKB", str(error))


def _safe_filename(value):
    safe = "".join(character if character.isalnum() or character in "-_" else "-"
                   for character in str(value).strip())
    return safe.strip("-") or "parameter"



__all__ = ["DataFrameModel", "MatchingWindow", "clipboard_frame"]
