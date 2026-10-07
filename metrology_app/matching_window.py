"""Qt workspace for multi-parameter Reference/Raw card matching."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import json
from io import StringIO
from pathlib import Path
from uuid import uuid4
import subprocess
import sys

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyqtgraph.exporters
from .plotting.parameter_layout import ParameterPlotArea, normalize_plot_layouts
from PyQt6.QtCore import (
    QAbstractTableModel, QEasingCurve, QEvent, QMimeData, QModelIndex, QPoint, QRect, QRectF,
    QPropertyAnimation, QSignalBlocker, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QActionGroup, QBrush, QColor, QDrag, QKeySequence, QPainter,
    QFontMetrics, QPalette, QPixmap, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
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
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .appearance import fit_window_to_screen, help_title_label
from .data import inspect_table
from .trend import parse_unit
from .diagnostics import get_logger
from .matching import MAX_ROWS, MatchWorkbook, ParameterMapping, extrema_sample_indices
from .match_groups import group_state, row_ids
from .match_group_ui import CombinedGroupDialog, GroupControls, GroupPlotPage, ProjectedSheetModel, draw_group_trend, set_group_axes
from .data_selection import DataSelectionDialog
from .plotting import InteractivePlotWidget, place_legend_above_frame
from .plotting.sequence_axis import SpanLabelAxis
from .settings import (
    apply_theme, forget_recent_wkb, recent_wkb_paths, remember_recent_wkb,
)
from .sheet import DuplicateHeaderBanner, SheetModel, SheetView
from .widgets import ScrollSafeComboBox
from .workspace_store import WorkspaceSnapshot, file_revision, load_workspace, save_workspace, workspace_path
from .workspace_document import WkbDocument, commit_editors, local_snapshot, local_ui, recovery_decision, recovery_directory, writable_path
from .workbook_startup import AXIS_MODE_LABELS, analysis_settings as normalized_analysis_settings


PLOT_LIMIT = 20_000
_PARAMETER_MIME = "application/x-metrology-match-parameter"
LOGGER = get_logger()
DEFAULT_METRIC_HIGHLIGHTING = {"slope_min": .9, "slope_max": 1.1, "rsq_min": .9}


def _metric_highlighting_limits(state=None):
    if state is not None and not isinstance(state, dict):
        raise ValueError("Invalid metric highlighting settings.")
    try:
        limits = {key: float((state or {}).get(key, default))
                  for key, default in DEFAULT_METRIC_HIGHLIGHTING.items()}
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Invalid metric highlighting settings.") from error
    if (not all(np.isfinite(value) for value in limits.values())
            or not -1_000_000 <= limits["slope_min"] <= limits["slope_max"] <= 1_000_000
            or not 0 <= limits["rsq_min"] <= 1):
        raise ValueError("Slope minimum must not exceed maximum; R² minimum must be between 0 and 1.")
    return limits


def _metric_warning(field, value, limits):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(number):
        return ""
    if field == "Slope" and not limits["slope_min"] <= number <= limits["slope_max"]:
        return f"Slope is outside the accepted {limits['slope_min']:g}–{limits['slope_max']:g} range."
    if field == "R²" and number < limits["rsq_min"]:
        return f"R² is below {limits['rsq_min']:g}."
    return ""


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

    def __init__(self, frame=None, parent=None, *, quality_limits=None):
        super().__init__(parent)
        self.frame = frame if frame is not None else pd.DataFrame()
        self.quality_limits = _metric_highlighting_limits(quality_limits)

    def set_quality_limits(self, limits):
        self.quality_limits = dict(limits)
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1),
                                  [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.ToolTipRole])

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
        return _metric_warning(str(self.frame.columns[column]), value, self.quality_limits)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self.frame.columns[section])
        return str(section + 1)


class _WaferMetricsModel(DataFrameModel):
    checkedChanged = pyqtSignal(int, bool)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and self.frame.columns[index.column()] == "Draw":
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if self.frame.iat[index.row(), index.column()] else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.ToolTipRole:
                if pd.isna(self.frame.iloc[index.row()]["Slope"]):
                    return "Match unavailable: need at least two finite pairs with distinct Raw values."
                return "Click anywhere in this cell, or press Space, to toggle this measurement set's Match, Trend and Bias plots."
            return None
        return super().data(index, role)

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and self.frame.columns[index.column()] == "Draw" and pd.notna(self.frame.iloc[index.row()]["Slope"]):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (role != Qt.ItemDataRole.CheckStateRole or not index.isValid()
                or self.frame.columns[index.column()] != "Draw"
                or not self.flags(index) & Qt.ItemFlag.ItemIsUserCheckable):
            return False
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        self.frame.iat[index.row(), index.column()] = checked
        self.dataChanged.emit(index, index, [role])
        self.checkedChanged.emit(index.row(), checked)
        return True


class _DrawCellDelegate(QStyledItemDelegate):
    """One centred indicator, with the whole cell as its mouse hit target."""

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        side = 18
        rect = QRect(0, 0, side, side)
        rect.moveCenter(option.rect.center())
        dark = option.palette.color(QPalette.ColorRole.Base).lightness() < 128
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        border = "#9b8ea8" if dark else "#94a3b8"
        fill = "#1b1425" if dark else "#ffffff"
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not enabled:
            painter.setOpacity(.45)
        painter.setPen(pg.mkPen("#2563eb" if checked else border, width=1))
        painter.setBrush(QColor("#2563eb" if checked else fill))
        painter.drawRoundedRect(QRectF(rect).adjusted(.5, .5, -.5, -.5), 3, 3)
        if checked:
            painter.setPen(pg.mkPen("#ffffff", width=2))
            painter.drawLine(rect.left() + 4, rect.top() + 9, rect.left() + 7, rect.top() + 12)
            painter.drawLine(rect.left() + 7, rect.top() + 12, rect.left() + 13, rect.top() + 5)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if not index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() != Qt.MouseButton.LeftButton or not option.rect.contains(event.position().toPoint()):
                return False
        elif event.type() == QEvent.Type.KeyPress:
            if event.key() not in (Qt.Key.Key_Space, Qt.Key.Key_Select):
                return False
        else:
            return event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        return model.setData(index, Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
                             Qt.ItemDataRole.CheckStateRole)


class _WaferMetricsView(QTableView):
    clearRequested = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        header = self.horizontalHeader()
        self.uncheck_all = QToolButton(header.viewport(), objectName="waferUncheckAll")
        self.uncheck_all.setText("×")
        self.uncheck_all.setFixedSize(20, 20)
        self.uncheck_all.setAutoRaise(True)
        self.uncheck_all.setAccessibleName("Uncheck all")
        self.uncheck_all.setToolTip("Uncheck all\nRemove all Draw plots for this parameter. Data and point selection are unchanged.")
        self.uncheck_all.setEnabled(False)
        self.uncheck_all.hide()
        header.geometriesChanged.connect(self._position_uncheck_all)
        header.sectionResized.connect(self._position_uncheck_all)
        header.sectionMoved.connect(self._position_uncheck_all)

    def _position_uncheck_all(self, *_):
        header = self.horizontalHeader()
        column = next((i for i in range(header.count())
                       if self.model().headerData(i, Qt.Orientation.Horizontal) == "Draw"), -1)
        if column < 0 or header.isSectionHidden(column):
            self.uncheck_all.hide()
            return
        self.uncheck_all.move(header.sectionViewportPosition(column) + header.sectionSize(column) - 24,
                              (header.viewport().height() - self.uncheck_all.height()) // 2)
        self.uncheck_all.setVisible(header.viewport().rect().contains(self.uncheck_all.geometry()))

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._position_uncheck_all()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.indexAt(event.position().toPoint()).isValid():
            self.clearRequested.emit()
        super().mousePressEvent(event)


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
            target = self._parameter_drop_target(event)
            position = target.mapFromGlobal(self.mapToGlobal(event.position().toPoint()))
            target._show_drop_position(position.y() < target.height() / 2)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_PARAMETER_MIME):
            target = self._parameter_drop_target(event)
            position = target.mapFromGlobal(self.mapToGlobal(event.position().toPoint()))
            target._show_drop_position(position.y() < target.height() / 2)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(_PARAMETER_MIME):
            event.ignore()
            return
        parameter = bytes(event.mimeData().data(_PARAMETER_MIME)).decode("utf-8")
        target = self._parameter_drop_target(event)
        position = target.mapFromGlobal(self.mapToGlobal(event.position().toPoint()))
        before = position.y() < target.height() / 2
        target.workspace.clear_parameter_drop_previews()
        target.workspace.move_parameter(parameter, target.parameter, before=before)
        event.acceptProposedAction()

    def _parameter_drop_target(self, event):
        owner = getattr(self.workspace, "workbook_window", self.workspace)
        source = bytes(event.mimeData().data(_PARAMETER_MIME)).decode("utf-8")
        if source in owner.plot_groups:
            card = self
            while card is not None:
                if isinstance(card, _ParameterCard) and card.parameter in owner.plot_groups:
                    return card
                card = card.parentWidget()
        return self

    def dragLeaveEvent(self, event):
        self.workspace.clear_parameter_drop_previews()
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
    """Trend plot with its legend in the header row and a Card toggle above it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        item = self.getPlotItem()
        # The legend is the only layout item in the header row; the title moves
        # into an overlay label (same pattern as the Match plot heading) because
        # sharing one layout cell makes Qt warn on every redraw.
        item.setTitle(None)
        item.layout.removeItem(item.titleLabel)
        item.layout.setRowFixedHeight(0, _MatchPlotWidget.HEADER_HEIGHT)
        self.title_label = QLabel(objectName="trendPlotTitle", parent=self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_font = self.title_label.font()
        title_font.setPointSizeF(11.0)
        self.title_label.setFont(title_font)
        self.card_checkbox = QCheckBox("Card", self)
        self.card_checkbox.setObjectName("trendCardToggle")
        self.card_checkbox.setToolTip(
            "Show PMISH after applying the fitted Card; clear to show Raw Data."
        )
        self.card_checkbox.adjustSize()

    def set_scope_title(self, title):
        self._scope_title = title
        self._refresh_scope_title()

    def _refresh_scope_title(self):
        if not hasattr(self, "_scope_title"):
            return
        # Caption and Card occupy the first header row; the legend has its own
        # row underneath. Reserve horizontal room for the Card, not the legend.
        reserve = self.card_checkbox.width() + 20
        available = int(max(40, self.width() - 2 * reserve - 40))
        self.title_label.setGeometry(0, 0, self.width(), self.title_label.fontMetrics().height() + 4)
        self.title_label.setText(QFontMetrics(self.title_label.font()).elidedText(
            self._scope_title, Qt.TextElideMode.ElideMiddle, available
        ))
        self.title_label.setToolTip(self._scope_title)

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
        self.title_label.raise_()
        self._refresh_scope_title()


class MatchingWindow(QMainWindow):
    """Build Preview or Final results from one row-aligned matching workbook."""
    workspace_type = "match_workbook"

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
        self._analysis_current = False
        self._group_only_pending = False
        self._primary_bias_mode = "absolute"
        self._auto_run_enabled = False
        self._auto_run_pending = False
        self._pending_auto_view_state = None
        self._loading_input_sheets = False
        self._input_sheet_errors = {"reference": "", "raw": "", "final_raw": ""}
        self._selection_columns_missing = set()
        self._parameter_order = []
        self._displayed_raw_mode = "preview"
        self._raw_sources = {"preview": "No data", "final": "No data"}
        self._trend_card_state = {}
        self._plot_layout_states = {}
        self._single_wafer_checks = {"preview": {}, "final": {}}
        self._plot_layout_identity_timer = QTimer(self)
        self._plot_layout_identity_timer.setSingleShot(True)
        self._plot_layout_identity_timer.setInterval(150)
        self._plot_layout_identity_timer.timeout.connect(lambda: self.document.refresh_identity())
        self._wafer_window_factory = wafer_window_factory or self._default_wafer_window_factory
        self._dynamic_window_factory = (
            dynamic_window_factory or self._default_dynamic_window_factory
        )
        self._correlation_window_factory = (
            correlation_window_factory or self._default_correlation_window_factory
        )
        self._map_selection_states = {"preview": None, "final": None}
        self._dynamic_selection_states = {"preview": None, "final": None}
        self._correlation_selection_states = {
            "preview": None, "final": None
        }
        self._stage_windows = []
        self._syncing_stage_windows = False
        self._stage_sync_inputs = None
        self._stage_window_context = {}
        self._workspace_states = {}
        self._workspace_frames = {}
        self._recovered_children = {}
        self.second_axis_ratio = 10.0
        self.metric_highlighting = _metric_highlighting_limits()
        self.trend_axis_mode = "auto"
        self._recent_wkb_paths = list(recent_wkb_paths())
        self.reference_model = SheetModel()
        self.raw_model = SheetModel()
        self.final_raw_model = SheetModel()
        self.group_controls = GroupControls(self)
        self._group_proxies = {"reference": ProjectedSheetModel(self.reference_model, self),
                               "preview": ProjectedSheetModel(self.raw_model, self),
                               "final": ProjectedSheetModel(self.final_raw_model, self),
                               "order": ProjectedSheetModel(self.group_controls.order_model, self)}
        self.preview_model = DataFrameModel(parent=self)
        self.final_model = DataFrameModel(parent=self)
        self.summary_model = DataFrameModel(parent=self)
        self._build_ui()
        self.group_controls.changed.connect(self._group_controls_changed)
        self.group_controls.apply_requested.connect(self._apply_group_clicked)
        self.group_controls.combined_imported.connect(self._import_group_frames)
        self.reference_model.changed.connect(
            lambda: self._input_sheet_changed("reference")
        )
        self.raw_model.changed.connect(lambda: self._input_sheet_changed("raw"))
        self.final_raw_model.changed.connect(
            lambda: self._input_sheet_changed("final_raw")
        )
        self.raw_view.table_pasted.connect(self._raw_table_pasted)
        self._update_state()
        self.document = WkbDocument(self)
        self.document.mark_clean()
        self._initial_layout_pending = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._initial_layout_pending:
            self._initial_layout_pending = False
            document = self.document
            if document.path is None and not document.forced_dirty and not document.untrusted_recovery:
                # Qt resolves the initial splitter geometry only on first show.
                # Accept that geometry alone, never pre-show data/settings edits.
                document.baseline.states["match"]["setup_splitter_sizes"] = self.setup_splitter.sizes()
                document.refresh_identity()

    def workspace_snapshot(self, *, include_drafts=False, readonly=False, validate=True):
        """Capture document state; read-only views are for immediate GUI-thread comparison only."""
        capture = (lambda value: value) if readonly else deepcopy
        frames = {"reference": self.reference_model.document_frame(),
                  "raw": self.raw_model.document_frame(),
                  "test_flags": self.group_controls.flags_frame(),
                  "final_match_raw": self.final_raw_model.document_frame()}
        if not len(frames["final_match_raw"].columns):
            del frames["final_match_raw"]
        for name, frame in (("preview_raw", self.preview_frame), ("final_raw", self.final_frame),
                            ("preview_map", self.preview_map_frame), ("final_map", self.final_map_frame),
                            ("preview_dynamic", self.preview_dynamic_frame), ("final_dynamic", self.final_dynamic_frame)):
            if frame is not None and (not frame.empty or name.endswith(("map", "dynamic"))):
                frames[name] = frame
        frames.update(self._workspace_frames)
        try:
            mappings = [asdict(m)
                        for m in self.selected_mappings()]
        except ValueError:
            mappings = []  # Incomplete mapping choices are retained in match_ui.
        state = {"match_type": self.match_type.currentText(), "result_mode": self.result_mode.currentText().lower(),
                 "bias_mode": self._primary_bias_mode, "bias_views": self._selected_bias_views(),
                 "bias_limit": self._default_bias_limit,
                 "setup_splitter_sizes": self.setup_splitter.sizes(), "parameter_order": list(self.parameter_order()),
                 "mappings": mappings, "workspace_selections": {"map": self._map_selection_states,
                                                                   "dynamic": self._dynamic_selection_states},
                 "correlation_selections": self._correlation_selection_states,
                 "trend_axis_settings": {"ratio": self.second_axis_ratio, "mode": self.trend_axis_mode},
                 "grouping_state": capture(self.group_controls.state),
                 "draft": not (self._analysis_current or self._group_only_pending) or self.result is None or not mappings or bool(any(self._input_sheet_errors.values()))}
        ui = {"mapping_choices": self._mapping_state(),
              "metric_highlighting": dict(self.metric_highlighting),
              "single_wafer_checks": capture(self._single_wafer_checks),
              "group_plots": self.group_plot_page.selection_state(),
              "plot_layouts": capture(self._plot_layout_states),
              "trend_cards": [[list(key), value] for key, value in self._trend_card_state.items()]}
        snapshot = WorkspaceSnapshot("match_workbook", frames,
                                     {"match": state, "match_ui": ui, **capture(self._workspace_states)})
        if validate and not state["draft"]:
            try:
                MatchWorkbook.from_snapshot(snapshot)
            except (ValueError, TypeError):
                state["draft"] = True  # Row counts/mappings may be mid-edit after a previous run.
        if include_drafts:
            for child in self._stage_windows:
                context = self._stage_window_context.get(child)
                if context and hasattr(child, "workspace_snapshot"):
                    scope = ".".join(context)
                    draft = child.workspace_snapshot()
                    snapshot.states[scope] = {"ui": draft.states["ui"], "workspace_type": draft.workspace_type,
                                              "data_override": True,
                                              "analysis_states": {key: deepcopy(value) for key, value in draft.states.items() if key != "ui"}}
                    for name, frame in draft.frames.items():
                        snapshot.frames[f"{scope}.{name}"] = frame
        return snapshot

    def _accepted_workspace_state(self):
        return {name: deepcopy(getattr(self, name)) for name in (
            "preview_map_frame", "final_map_frame", "preview_dynamic_frame", "final_dynamic_frame",
            "_map_selection_states", "_dynamic_selection_states", "_correlation_selection_states",
            "_workspace_states", "_workspace_frames")}

    def _restore_accepted_workspace_state(self, state):
        for name, value in state.items():
            setattr(self, name, value)

    def restore_workspace(self, snapshot, *, analysis_settings=None):
        if snapshot.workspace_type != self.workspace_type:
            raise ValueError("This WKB is not a Match Workbook.")
        group_state(snapshot.states["match"].get("grouping_state"))
        metric_limits = _metric_highlighting_limits(snapshot.states.get("match_ui", {}).get("metric_highlighting"))
        plot_layouts = normalize_plot_layouts(snapshot.states.get("match_ui", {}).get("plot_layouts"))
        checks = snapshot.states.get("match_ui", {}).get("single_wafer_checks", {})
        if not isinstance(checks, dict) or set(checks) - {"preview", "final"}:
            raise ValueError("Invalid single-wafer plot selection.")
        for selections in checks.values():
            if not isinstance(selections, dict) or any(
                not isinstance(name, str) or not isinstance(labels, list)
                or any(not isinstance(label, str) for label in labels)
                for name, labels in selections.items()
            ):
                raise ValueError("Invalid single-wafer plot selection.")
        self._close_stage_workspaces(tuple(self._stage_windows))
        self._clear_plot_groups()
        self.set_metric_highlighting(metric_limits, refresh=False)
        self._recovered_children = {}
        state = snapshot.states["match"]
        self.group_controls.restore(state.get("grouping_state"), snapshot.frames.get("test_flags"))
        self.group_plot_page.restore_state(snapshot.states.get("match_ui", {}).get("group_plots"))
        self._workspace_states = {name: deepcopy(value) for name, value in snapshot.states.items()
                                  if name not in ("match", "match_ui", "recovery")}
        self._workspace_frames = {name: frame.copy() for name, frame in snapshot.frames.items() if "." in name}
        self._trend_card_state = {tuple(key): value for key, value in snapshot.states.get("match_ui", {}).get("trend_cards", [])}
        self._plot_layout_states = plot_layouts
        self._single_wafer_checks = {stage: deepcopy(checks.get(stage, {})) for stage in ("preview", "final")}
        if not state.get("draft"):
            workbook = MatchWorkbook.from_snapshot(snapshot)
            return self._restore_analyzed_workbook(
                workbook, self.workbook_path or "Workspace.wkb", analysis_settings=analysis_settings)
        else:
            self._restore_draft(snapshot)
            baseline = self.workspace_snapshot()
            if analysis_settings is not None:
                self.apply_analysis_settings(analysis_settings, refresh=False)
            return baseline

    def apply_analysis_settings(self, settings, *, refresh=True):
        """Apply one Workbook-wide policy without intermediate recalculations."""
        settings = normalized_analysis_settings(settings)
        mapping_state = self._mapping_state()
        changed_stage = self.result_mode.currentText().lower() != settings["result_mode"]
        with QSignalBlocker(self.match_type), QSignalBlocker(self.result_mode), \
                QSignalBlocker(self.absolute_bias), QSignalBlocker(self.percent_bias):
            self.match_type.setCurrentText(settings["match_type"])
            self.result_mode.setCurrentText(settings["result_mode"].title())
            self.absolute_bias.setChecked("absolute" in settings["bias_views"])
            self.percent_bias.setChecked("percent" in settings["bias_views"])
        self._primary_bias_mode = settings["bias_mode"]
        self.match_type_actions[settings["match_type"]].setChecked(True)
        self.absolute_bias_action.setChecked(self.absolute_bias.isChecked())
        self.percent_bias_action.setChecked(self.percent_bias.isChecked())
        with QSignalBlocker(self.mode_tabs):
            self.mode_tabs.setCurrentIndex(self.result_mode.currentIndex())
        self._show_raw_mode(settings["result_mode"])
        if changed_stage:
            self._populate_mappings(mapping_state)
        self.set_second_axis_ratio(settings["trend_axis_settings"]["ratio"])
        self.set_trend_axis_mode(settings["trend_axis_settings"]["mode"])
        for child in self._stage_windows:
            update = getattr(child, "_update_workbook_data_action", None)
            if callable(update):
                update()
        self._update_state()
        if refresh and self.analyze_button.isEnabled() and not any(self._input_sheet_errors.values()):
            self.run_analysis()
        elif refresh:
            self._analysis_current = False
            self._invalidate_analysis()
        self.document.refresh_identity()

    def _restore_draft(self, snapshot):
        state = snapshot.states["match"]
        self._auto_run_enabled = False
        self._auto_run_pending = False
        self.result = None
        self._analysis_current = False
        self.workbook = None
        self._clear_plot_groups()
        self._loading_input_sheets = True
        try:
            for name, model in (("reference", self.reference_model), ("raw", self.raw_model),
                                ("final_match_raw", self.final_raw_model)):
                frame = snapshot.frames.get(name, pd.DataFrame()).copy()
                model.load(frame)
                try:
                    analysis_frame = model.frame().reset_index(drop=True)
                except ValueError:
                    analysis_frame = pd.DataFrame()
                setattr(self, {"reference": "reference_frame", "raw": "raw_frame",
                               "final_match_raw": "final_match_frame"}[name], analysis_frame)
            for name, attribute in (("preview_raw", "preview_frame"), ("final_raw", "final_frame"),
                                     ("preview_map", "preview_map_frame"), ("final_map", "final_map_frame"),
                                     ("preview_dynamic", "preview_dynamic_frame"), ("final_dynamic", "final_dynamic_frame")):
                setattr(self, attribute, snapshot.frames.get(name, pd.DataFrame() if name.endswith("raw") else None))
            self.match_type.setCurrentText(state.get("match_type", "KLA"))
            self.result_mode.setCurrentText(state.get("result_mode", "preview").title())
            self._show_raw_mode(self.result_mode.currentText().lower())
            self._primary_bias_mode = state.get("bias_mode", "absolute")
            self._default_bias_limit = state.get("bias_limit", .5)
            self.absolute_bias.setChecked("absolute" in state.get("bias_views", ["absolute"]))
            self.percent_bias.setChecked("percent" in state.get("bias_views", []))
            self._map_selection_states = state.get("workspace_selections", {}).get("map", {"preview": None, "final": None})
            self._dynamic_selection_states = state.get("workspace_selections", {}).get("dynamic", {"preview": None, "final": None})
            self._correlation_selection_states = state.get("correlation_selections", {"preview": None, "final": None})
            self.set_second_axis_ratio(state.get("trend_axis_settings", {}).get("ratio", 10.0))
            self.set_trend_axis_mode(state.get("trend_axis_settings", {}).get("mode", "auto"))
            if self.reference_frame.columns.is_unique:
                self._populate_mappings(snapshot.states.get("match_ui", {}).get("mapping_choices", {}))
            else:
                self.mapping_table.setRowCount(0)
            self._parameter_order = list(state.get("parameter_order", []))
            self._input_sheet_errors = {name: "" for name in ("reference", "raw", "final_raw")}
            for name, model in (("reference", self.reference_model), ("raw", self.raw_model), ("final_raw", self.final_raw_model)):
                if model.duplicate_header_count():
                    self._input_sheet_errors[name] = "Duplicate column names in row 1. Rename them to continue."
            self.preview_model.set_frame(self.preview_frame)
            self.final_model.set_frame(self.final_frame)
            self.summary_model.set_frame(pd.DataFrame())
            self.result_status.setText("Draft restored · Run analysis when the inputs are ready")
            self.reference_source.setText(self._source_text("WKB draft", self.reference_model.document_frame()))
            self._raw_sources = {"preview": self._source_text("WKB draft", self.raw_model.document_frame()),
                                 "final": self._source_text("WKB draft", self.final_raw_model.document_frame())}
            self.raw_source.setText(self._raw_sources[self.result_mode.currentText().lower()])
        finally:
            self._loading_input_sheets = False
        self._update_state()
        sizes = state.get("setup_splitter_sizes")
        self._refresh_group_projection()
        if sizes:
            self._restore_setup_splitter_layout(sizes)

    def recover_draft(self):
        path, _ = QFileDialog.getOpenFileName(self, "Recover Match draft", str(recovery_directory()), "WKB draft (*.wkb)")
        if path and self.document.confirm_close():
            try:
                self.document.recover(path)
            except Exception as error:
                QMessageBox.warning(self, "Cannot recover draft", str(error))

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
        self.new_action = QAction("New Workbook…", self)
        self.new_action.setShortcut(QKeySequence("Ctrl+N"))
        self.new_action.triggered.connect(lambda: self.start_workbook(new=True))
        self.open_action = QAction("Open Workbook…", self)
        self.open_action.setShortcut(QKeySequence("Ctrl+O"))
        self.open_action.triggered.connect(self.open_wkb_dialog)
        self.open_recent_menu = QMenu("Open Recent WKB", self.file_menu)
        self.reveal_wkb_action = QAction("Reveal Workbook in Folder", self)
        self.reveal_wkb_action.setEnabled(False)
        self.reveal_wkb_action.triggered.connect(self.reveal_wkb_in_folder)
        self.save_action = QAction("Save Workbook", self)
        self.save_action.setToolTip("Save Workbook data, shared settings and all open analysis drafts.")
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_action.triggered.connect(self.save_wkb)
        self.save_as_action = QAction("Save Workbook As…", self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.triggered.connect(self.save_wkb_dialog)
        for action in (self.new_action, self.open_action, self.save_action, self.save_as_action):
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.export_action = QAction("Export Excel", self)
        self.export_action.triggered.connect(self.export_excel_dialog)
        self.images_action = QAction("Save images", self)
        self.images_action.triggered.connect(self.save_images_dialog)
        for action in (
            self.new_action,
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
        recover_action = self.file_menu.addAction("Recover Workbook Draft…")
        recover_action.triggered.connect(self.recover_draft)

        self.analysis_menu = self.menuBar().addMenu("Analysis")
        self.run_action = QAction("Run analysis", self)
        self.run_action.setShortcut(QKeySequence("Ctrl+Return"))
        self.run_action.triggered.connect(self._run_analysis_clicked)
        self.analysis_menu.addAction(self.run_action)
        self.metric_highlighting_action = self.analysis_menu.addAction("Metric highlighting…")
        self.metric_highlighting_action.triggered.connect(self.edit_metric_highlighting)
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

        # One explicit mode choice plus a decimal auto threshold. Plain menu
        # actions use a radio-style text marker instead of misleading boxes.
        self.second_axis_menu = self.analysis_menu.addMenu("Trend Y axes")
        self.second_axis_actions = {}
        for mode, label in AXIS_MODE_LABELS.items():
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, value=mode:
                self.set_trend_axis_mode(value)
            )
            self.second_axis_actions[mode] = action
        self.second_axis_menu.addAction(self.second_axis_actions["auto"])
        ratio_row = QWidget(self.second_axis_menu)
        ratio_layout = QHBoxLayout(ratio_row)
        ratio_layout.setContentsMargins(16, 2, 12, 4)
        ratio_layout.addWidget(QLabel("Median ratio >", ratio_row))
        self.second_axis_spin = QDoubleSpinBox(ratio_row)
        self.second_axis_spin.setDecimals(3)
        self.second_axis_spin.setRange(1.0, 1_000_000.0)
        self.second_axis_spin.setSingleStep(0.1)
        self.second_axis_spin.setSuffix("×")
        self.second_axis_spin.setValue(self.second_axis_ratio)
        self.second_axis_spin.setToolTip(
            "Auto: split same-unit curves when their median absolute values "
            "differ by more than this ratio. Different units always split."
        )
        self.second_axis_spin.valueChanged.connect(self.set_second_axis_ratio)
        ratio_layout.addWidget(self.second_axis_spin)
        ratio_action = QWidgetAction(self.second_axis_menu)
        ratio_action.setDefaultWidget(ratio_row)
        self.second_axis_menu.addAction(ratio_action)
        self.second_axis_menu.addSeparator()
        self.second_axis_menu.addAction(self.second_axis_actions["dual"])
        self.second_axis_menu.addAction(self.second_axis_actions["single"])
        self._refresh_axis_mode_menu()

        self.groups_menu = self.menuBar().addMenu("Groups")
        self.group_settings_action = self.groups_menu.addAction("Group settings…")
        self.group_settings_action.triggered.connect(self.open_group_settings)
        self.manage_groups_action = self.groups_menu.addAction("Manage groups…")
        self.manage_groups_action.triggered.connect(self.manage_groups)
        self.data_selection_action = self.groups_menu.addAction("Data selection…")
        self.data_selection_action.triggered.connect(self.select_analysis_data)
        self.group_settings_dialog = QDialog(self, objectName="groupSettingsDialog")
        self.group_settings_dialog.setWindowTitle("Group settings — Match Workbook")
        self.group_settings_dialog.setSizeGripEnabled(True)
        group_layout = QVBoxLayout(self.group_settings_dialog)
        group_layout.setContentsMargins(20, 18, 20, 12)
        group_layout.setSpacing(10)
        group_scroll = QScrollArea()
        group_scroll.setFrameShape(QFrame.Shape.NoFrame)
        group_scroll.setWidgetResizable(True)
        group_scroll.setWidget(self.group_controls)
        self.group_controls.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
        group_layout.addWidget(group_scroll, 1)
        group_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        group_close.addButton(self.group_controls.apply_button, QDialogButtonBox.ButtonRole.ApplyRole)
        group_close.rejected.connect(self.group_settings_dialog.reject)
        group_layout.addWidget(group_close)
        fit_window_to_screen(self.group_settings_dialog, (520, 360), minimum=(440, 320))

        # Compatibility aliases for callers that previously enabled toolbar buttons.
        self.open_button = self.open_action
        self.save_button = self.save_action
        self.save_as_button = self.save_as_action
        self.export_button = self.export_action
        self.images_button = self.images_action

    def open_group_settings(self):
        """One modeless settings window edits this Workbook's shared group state."""
        if not self.group_settings_action.isEnabled():
            return
        dialog = self.group_settings_dialog
        dialog.setWindowTitle(f"Group settings — {self.windowTitle()}")
        dialog.showNormal()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def manage_groups(self):
        plan = self.result.group_plan if self.result is not None else None
        if plan is None or not plan.enabled:
            QMessageBox.warning(self, "Groups unavailable", "Enable Head groups or Mark and enter the paired data first.")
            return
        dialog = CombinedGroupDialog(plan, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        groups = deepcopy(dialog.groups)
        show_wafer_groups = sorted(dialog.show_wafer_groups)
        dialog.deleteLater()
        if accepted:
            for state in (self.group_controls.state, self.group_controls.state["applied"]):
                state["combined_groups"] = deepcopy(groups)
                state["show_wafer_groups"] = show_wafer_groups.copy()
            self.group_controls.refresh()
            self._stage_sync_inputs = None
            try:
                self.run_analysis(apply_groups=False)
            except ValueError as error:
                QMessageBox.warning(self, "Cannot plot Groups", str(error))

    def select_analysis_data(self):
        from .match_groups import GroupPlan
        try:
            raw = self._active_raw_frame()
            if raw.empty or len(raw) != len(self.reference_frame):
                raise ValueError("Enter row-aligned Reference and Raw Data first.")
            plan = GroupPlan(raw, self.group_controls.flags_frame(), self.group_controls.state, self.reference_frame)
            dialog = DataSelectionDialog(plan, self)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            selection = deepcopy(dialog.selection)
            dialog.deleteLater()
            if not accepted:
                return
            for state in (self.group_controls.state, self.group_controls.state["applied"]):
                state["data_selection"] = deepcopy(selection)
            self._selection_columns_missing = set()
            self.group_controls.refresh()
            self._stage_sync_inputs = None
            self.run_analysis(apply_groups=False)
        except ValueError as error:
            QMessageBox.warning(self, "Cannot select analysis data", str(error))

    def _install_shortcuts(self):
        for title, shortcut, handler in (
            ("Open WKB", "Ctrl+O", self.open_wkb_dialog),
            ("Save WKB", "Ctrl+S", self.save_wkb),
            ("Save WKB As…", "Ctrl+Shift+S", self.save_wkb_dialog),
            ("Run analysis", "Ctrl+Return", self._run_analysis_clicked),
        ):
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
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
        if hasattr(self, "order_view"):
            self._refresh_group_projection()

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
        (self.order_card, self.order_view, self.order_source,
         self.order_duplicate_banner) = self._table_card(
            "Order", "-1 = Unknown; 0 and 1 use your head names. Blank = not provided.",
            self.group_controls.order_model)
        (self.reference_card, self.reference_view, self.reference_source,
         self.reference_duplicate_banner) = self._table_card(
            "Reference", "Paste the prepared table first.", self.reference_model
        )
        (self.raw_card, self.raw_view, self.raw_source,
         self.raw_duplicate_banner) = self._table_card(
            "Raw Data", "Rows are matched to Reference from top to bottom.", self.raw_model
        )
        inputs.addWidget(self.order_card)
        inputs.addWidget(self.reference_card)
        inputs.addWidget(self.raw_card)
        inputs.setSizes([280, 570, 650])
        inputs.setChildrenCollapsible(False)
        inputs.setMinimumHeight(280)
        for card in (self.order_card, self.reference_card, self.raw_card):
            card.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
            )
        inputs.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding
        )
        self.mapping_card = QFrame(objectName="panel")
        self.mapping_card.setMinimumHeight(170)
        mapping_layout = QVBoxLayout(self.mapping_card)
        mapping_layout.setContentsMargins(16, 14, 16, 12)
        heading = QHBoxLayout()
        heading.addWidget(help_title_label(
            "Parameter mapping",
            "Numeric Reference columns are listed; “Reference” suffix columns pair by name.",
        ))
        heading.addStretch()
        self._default_bias_limit = .5  # Legacy WKB fallback; new limits live in mapping rows.
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
        self.mapping_table = QTableWidget(0, 12)
        self.mapping_table.setHorizontalHeaderLabels([
            "Use", "Parameter", "Reference column", "Raw Data column",
            "Slope", "Intercept", "R²", "Valid pairs", "Match type", "Result mode",
            "Bias limit ±", "Bias out of range",
        ])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setItemDelegateForColumn(0, _DrawCellDelegate(self.mapping_table))
        header = self.mapping_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((52, 150, 180, 210, 100, 100, 90, 95, 100, 105, 185, 150)):
            self.mapping_table.setColumnWidth(column, width)
        self.mapping_table.itemChanged.connect(self._mapping_item_changed)
        mapping_layout.addWidget(self.mapping_table, 1)
        mapping_footer = QHBoxLayout()
        self.mapping_size = _label("0 rows × 12 columns", "hint")
        mapping_footer.addWidget(self.mapping_size)
        mapping_footer.addStretch()
        mapping_layout.addLayout(mapping_footer)
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
        for view, table in ((self.order_view, "order"), (self.reference_view, "reference"), (self.raw_view, "raw")):
            self.group_controls.attach_header(view, table)
        return page

    def _table_card(self, title, subtitle, model):
        card = QFrame(objectName="sheetCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 12)
        heading = QHBoxLayout()
        guidance = subtitle
        if isinstance(model, SheetModel):
            guidance += ("\nRow 1 = headers · Ctrl+V paste · Ctrl+Shift+V replace table"
                         " · Ctrl+Z undo.")
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
        self.empty_plots_hint = _label("", "hint")
        self.plot_groups_layout.addWidget(self.empty_plots_hint)
        self.results_tabs.addTab(self.plot_groups_widget, "All parameter plots")

        self.wafer_groups_widget = QWidget()
        self.wafer_groups_layout = QVBoxLayout(self.wafer_groups_widget)
        self.wafer_groups_layout.setContentsMargins(0, 0, 0, 0)
        self.wafer_groups_layout.setSpacing(16)
        self.wafer_groups_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.empty_wafer_hint = _label("", "hint")
        self.wafer_groups_layout.addWidget(self.empty_wafer_hint)
        self.results_tabs.addTab(self.wafer_groups_widget, "Single-wafer metrics")
        self.group_plot_page = GroupPlotPage(self)
        # Until its tab is added the page has no layout slot; an unparented
        # child would otherwise float at the window's top-left over the menu bar.
        self.group_plot_page.hide()
        self.results_tabs.currentChanged.connect(self._refresh_visible_wafer_metrics)
        layout.addWidget(self.results_tabs, 1)
        panel.setMinimumHeight(520)
        return panel

    def _refresh_visible_wafer_metrics(self, _index):
        if self.results_tabs.currentWidget() is not self.wafer_groups_widget or self.result is None:
            return
        for parameter, group in self.plot_groups.items():
            if group.get("wafer_metrics_pending"):
                self._draw_wafer_metrics(parameter, group)
        self._resize_results_for_plot_groups()

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
        for name, group in self.plot_groups.items():
            details = group.get("wafer_details", {})
            source = next((label for label, detail in details.items() if detail["storage_key"] == parameter), None)
            destination = next((label for label, detail in details.items() if detail["storage_key"] == target), None)
            if source is not None and destination is not None and source != destination:
                order = self._single_wafer_checks[self.workbook.result_mode][name]
                order.remove(source)
                index = order.index(destination)
                order.insert(index if before else index + 1, source)
                for label in order:
                    if label in details:
                        group["wafer_detail_layout"].removeWidget(details[label]["card"])
                        group["wafer_detail_layout"].addWidget(details[label]["card"])
                self.document.refresh_identity()
                return
        order = list(self._reconciled_parameter_order(self.plot_groups))
        if parameter not in order or target not in order or parameter == target:
            return
        order.remove(parameter)
        target_index = order.index(target)
        order.insert(target_index if before else target_index + 1, parameter)
        self._parameter_order = order
        self._apply_parameter_order()
        self.document.refresh_identity()

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
        self.group_plot_page.apply_parameter_order()

    def clear_parameter_drop_previews(self):
        for group in self.plot_groups.values():
            group["card"]._show_drop_position(None)
            group["wafer_card"]._show_drop_position(None)
            for detail in group.get("wafer_details", {}).values():
                detail["card"]._show_drop_position(None)
        self.group_plot_page.clear_parameter_drop_previews()

    def _create_parameter_section(self, parameter):
        """A draggable outer section; its existing children move without redraw."""
        card = _ParameterCard(parameter, self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        heading = QHBoxLayout()
        handle = _ParameterDragHandle(parameter, card)
        font = handle.font()
        font.setBold(True)
        handle.setFont(font)
        heading.addWidget(handle)
        heading.addStretch()
        layout.addLayout(heading)
        return card

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
        self._refresh_selection_columns_warning()
        self._populate_mappings(mapping_state)
        self._analysis_input_changed(view_state=view_state)

    def set_raw_frame(self, frame, source="Raw Data"):
        if self.reference_frame.empty:
            raise ValueError("Paste the Reference table before Raw Data.")
        previous_raw = self._active_raw_frame()
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
        flag_column = next((column for column in stored if "".join(c.lower() for c in column if c.isalnum()) == "testflag"), None)
        if mode == "preview" and flag_column is not None:
            self.group_controls.restore(
                self.group_controls.state,
                stored[[flag_column]].rename(columns={flag_column: "TestFlag"}))
        self._input_sheet_errors[error_key] = ""
        self._raw_sources[mode] = self._source_text(source, stored)
        self.raw_source.setText(self._raw_sources[mode])
        self._sync_selection_to_raw(previous_raw)
        self._refresh_selection_columns_warning()
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
        previous_raw = self._active_raw_frame()
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
            states = (self.group_controls.state, self.group_controls.state.get("applied", {}))
            preserve_rows = any(state.get("enabled") or state.get("mark_enabled")
                                or state.get("data_selection") is not None for state in states)
            if preserve_rows:
                # Participation needs row alignment even without classification.
                # Validate normalized headers without materializing the table
                # twice; document_frame keeps blank source rows and raw headers.
                headers = model.headers()
                if len(set(headers)) != len(headers):
                    raise ValueError("Duplicate column names in row 1. Rename them to continue.")
                frame = model.document_frame().reset_index(drop=True)
            else:
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
        if name != "reference":
            self._sync_selection_to_raw(previous_raw, preserve_positions=model.preserves_record_positions)
        self._refresh_selection_columns_warning()
        self._populate_mappings(mapping_state)
        controls = self.group_controls
        # With unchanged dimensions and no row projection/pending settings,
        # the queued post-run analysis can prepare the Group plan once.
        defer_groups = (self._auto_run_enabled and not error and not controls.pending
                        and not controls.state["filters"] and not controls.state["sort"]
                        and self.reference_frame.shape == controls.reference.shape
                        and self._active_raw_frame().shape == controls.raw.shape
                        and self.reference_frame.columns.equals(controls.reference.columns)
                        and self._active_raw_frame().columns.equals(controls.raw.columns))
        self._analysis_input_changed(view_state=view_state, prepare_groups=not defer_groups)

    def _active_raw_frame(self):
        return (
            self.final_match_frame
            if self.result_mode.currentText().lower() == "final"
            else self.raw_frame
        )

    def _sync_selection_to_raw(self, previous_raw, *, preserve_positions=False):
        """Keep the applied Data selection when the Raw Data table is replaced.

        Rows keep their record identity when it survives; rows that no longer
        match one fall back to the previous participation at the same position,
        so pasting a corrected table does not silently select everything again.
        """
        from .match_groups import participation_ids, row_ids
        current = self._active_raw_frame()
        old_keys, new_keys = row_ids(previous_raw), row_ids(current)
        records = None
        for config in (self.group_controls.state, self.group_controls.state.get("applied", {})):
            selection = config.get("data_selection")
            if selection is not None:
                if records is None:
                    # Both the draft and applied states must receive the same
                    # mapping, or the settings would look pending forever.
                    old_ids = participation_ids(previous_raw, selection)
                    by_key = {key: identifier for key, identifier in zip(old_keys, old_ids)}
                    # A cell clear/edit cannot move another record to this row,
                    # even if two records now have identical blank identities.
                    positional = preserve_positions
                    reserved = {by_key[key] for key in new_keys if key in by_key}
                    used = set()
                    records = []
                    for position, key in enumerate(new_keys):
                        identifier = (old_ids[position] if position < len(old_ids) else None) if positional else by_key.get(key)
                        if identifier in used:
                            identifier = None
                        if identifier is None and position < len(old_ids):
                            candidate = old_ids[position]
                            if candidate not in used and candidate not in reserved:
                                identifier = candidate
                        identifier = identifier or uuid4().hex
                        used.add(identifier)
                        records.append({"key": key, "id": identifier})
                selection["records"] = [dict(record) for record in records]
                known = {record["id"] for record in records}
                selection["excluded"] = [identifier for identifier in selection["excluded"]
                                         if identifier in known]
            if len(current) == len(previous_raw):
                marks = config.get("mark_rows")
                if marks is None:  # A state built before Marks were free-form.
                    legacy = set(config.get("new_rows", []))
                    marks = ({"New": [new for old, new in zip(old_keys, new_keys) if old in legacy]}
                             if legacy else {})
                else:
                    remapped = {}
                    for key, assigned in marks.items():
                        assigned_ids = set(assigned)
                        remapped[key] = [new for old, new in zip(old_keys, new_keys)
                                         if old in assigned_ids]
                    marks = remapped
                config["mark_rows"] = {key: assigned for key, assigned in marks.items() if assigned}
                config.pop("new_rows", None)

    def _refresh_selection_columns_warning(self):
        """Flag an applied selection whose filter columns no longer exist."""
        selection = self.group_controls.state.get("applied", {}).get("data_selection")
        if selection is None:
            selection = self.group_controls.state.get("data_selection")
        used = set()
        for row in (selection or {}).get("view_filter_groups", []) or []:
            for spec in row:
                if isinstance(spec, dict) and spec.get("column"):
                    used.add(str(spec["column"]))
        for spec in (selection or {}).get("view_filters", []) or []:
            if isinstance(spec, dict) and spec.get("column"):
                used.add(str(spec["column"]))
        available = {"Order / TestFlag", "Order / Head", "Order / Mark", "Order / Group"}
        available |= {f"Reference / {column}" for column in self.reference_frame.columns}
        available |= {f"Raw Data / {column}" for column in self._active_raw_frame().columns}
        self._selection_columns_missing = used - available

    def _refresh_group_projection(self):
        controls = self.group_controls
        controls.set_sources(self.reference_frame, self._active_raw_frame())
        plan = controls.plan
        projected = plan is not None and bool(controls.state["filters"] or controls.state["sort"])
        rows = plan.display_rows if projected else None
        mode = self.result_mode.currentText().lower()
        for name, view, source in (("reference", self.reference_view, self.reference_model),
                                   (mode, self.raw_view, self.final_raw_model if mode == "final" else self.raw_model),
                                   ("order", self.order_view, controls.order_model)):
            proxy = self._group_proxies[name]
            proxy.set_rows(rows)
            model = proxy if projected else source
            if view.model() is not model:
                view.setModel(model)
        # The Order grid always has TestFlag / Head / Mark / Group, so its size
        # stays readable even before any paired rows exist.
        order_frame = (plan.order_frame if plan is not None
                       else pd.DataFrame(columns=["TestFlag", "Head", "Mark", "Group"]))
        self.order_source.setText(self._source_text("Order", order_frame))
        self.group_settings_action.setEnabled(True)
        self.manage_groups_action.setEnabled(True)
        self.order_card.setVisible(True)
        index = self.results_tabs.indexOf(self.group_plot_page)
        # Mark alone groups a workbook without TestFlags, so the tab follows the
        # resolved plan instead of the Head-groups switch.
        tem = self.match_type.currentText() == "TEM"
        grouped = bool(plan is not None and plan.enabled)
        if grouped and not tem and index < 0:
            self.results_tabs.addTab(self.group_plot_page, "Group plots")
        elif (not grouped or tem) and index >= 0:
            self.results_tabs.removeTab(index)
            self.group_plot_page.hide()
        # TEM keeps the classification for ordering and selection, but neither
        # the grouped plots nor the single-wafer metrics tab belongs to it.
        wafer_index = self.results_tabs.indexOf(self.wafer_groups_widget)
        if tem and wafer_index >= 0:
            self.results_tabs.removeTab(wafer_index)
        elif not tem and wafer_index < 0:
            self.results_tabs.insertTab(1, self.wafer_groups_widget, "Single-wafer metrics")

    def _group_controls_changed(self):
        if self._loading_input_sheets:
            return
        self._refresh_group_projection()
        self._analysis_current = False
        self._group_only_pending = self.result is not None
        if hasattr(self, "document"):
            self.document.refresh_identity()

    def _apply_group_clicked(self):
        try:
            self.run_analysis()
        except ValueError as error:
            QMessageBox.warning(self, "Cannot apply group settings", str(error))
        else:
            self.group_settings_dialog.accept()

    def _import_group_frames(self, reference, raw, flags):
        # One explicit column-assignment import; never infer duplicate Ref/Raw columns.
        self._auto_run_pending = False
        self.set_reference_frame(reference, "Combined clipboard")
        self.set_raw_frame(raw, "Combined clipboard")
        explicit = [ParameterMapping(str(column), str(column), str(column)) for column in reference
                    if column in raw and pd.to_numeric(reference[column], errors="coerce").notna().any()]
        if explicit:
            self._populate_mappings(explicit)
        state = deepcopy(self.group_controls.state)
        self.group_controls.restore(state, flags)
        self.group_controls.flags_changed()

    def _capture_setup_view_state(self):
        if not hasattr(self, "setup_splitter"):
            return None
        return (
            tuple(self.setup_splitter.sizes()),
            self.setup_scroll.verticalScrollBar().value(),
        )

    def _analysis_input_changed(self, *_, view_state=None, prepare_groups=True):
        """Refresh valid post-run edits without blanking plots or layout first."""
        self._analysis_current = False
        self._group_only_pending = False
        if prepare_groups:
            self._refresh_group_projection()
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
        if not self._auto_run_enabled or self._auto_run_pending or self.group_controls.pending:
            return
        self._auto_run_pending = True
        QTimer.singleShot(0, self._run_paste_analysis)

    def _run_paste_analysis(self):
        if not self._auto_run_pending:
            return  # An explicit analysis/export already covered this request.
        self._auto_run_pending = False
        view_state = self._pending_auto_view_state
        self._pending_auto_view_state = None
        if not self._auto_run_enabled or not self.analyze_button.isEnabled() or self.group_controls.pending:
            if view_state is not None:
                sizes, scroll_value = view_state
                self._restore_setup_view_state(sizes, scroll_value)
            return
        try:
            self.run_analysis(apply_groups=False)
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
                "bias_limit": self.mapping_table.cellWidget(row, 10).findChild(QDoubleSpinBox).value(),
                "show_bias_limit": self.mapping_table.cellWidget(row, 10).findChild(QCheckBox).isChecked(),
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
    def _source_text(_source, frame):
        # The paired tables only report their size; the file name and origin are
        # already visible in the window title and File menu.
        return f"{len(frame):,} rows × {len(frame.columns)} columns"

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
                    "bias_limit": mapping.bias_limit,
                    "show_bias_limit": mapping.show_bias_limit,
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
                    **(mapping_state or {}),
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
            use.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            use.setToolTip("Click anywhere in this cell, or press Space, to toggle this parameter's use in analysis.")
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
            raw_picker = ScrollSafeComboBox()
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
            limit_cell = QWidget()
            limit_layout = QHBoxLayout(limit_cell)
            limit_layout.setContentsMargins(4, 0, 4, 0)
            limit_layout.setSpacing(4)
            show_limit = QCheckBox(objectName="showBiasLimit")
            show_limit.setToolTip("Show red dashed ±limit lines on this parameter's absolute Bias plot.")
            show_limit.setAccessibleName(f"Show Bias limit for {reference_column}")
            show_limit.setChecked(mapping_state.get("show_bias_limit", False))
            limit_spin = QDoubleSpinBox(objectName="biasLimit")
            limit_spin.setDecimals(6)
            limit_spin.setRange(0, float(np.finfo(float).max))
            limit_spin.setSingleStep(.1)
            limit_spin.setKeyboardTracking(False)
            limit_spin.setValue(mapping_state.get("bias_limit") if mapping_state.get("bias_limit") is not None else self._default_bias_limit)
            unit = parse_unit(reference_column)
            limit_spin.setSuffix(" " + unit)
            limit_spin.setToolTip("Count |Bias| > limit in this parameter's unit. Equal-to-limit and non-finite values are not counted.\n"
                                  "The checkbox controls only the red limit lines, not the count. Bias % is not used.")
            limit_spin.setAccessibleName(f"Bias limit for {reference_column}")
            limit_layout.addWidget(show_limit)
            limit_layout.addWidget(limit_spin, 1)
            self.mapping_table.setCellWidget(row, 10, limit_cell)
            limit_spin.valueChanged.connect(lambda _value, cell=limit_cell: self._bias_limit_changed(cell))
            show_limit.toggled.connect(lambda _checked, cell=limit_cell: self._bias_limit_changed(cell))
            for column in range(4, self.mapping_table.columnCount()):
                if column == 10:
                    continue
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
            cell = self.mapping_table.cellWidget(row, 10)
            mappings.append(ParameterMapping(name, reference_column, raw_column,
                                             cell.findChild(QDoubleSpinBox).value(),
                                             cell.findChild(QCheckBox).isChecked()))
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
        """Bias plots are optional: unchecking one removes its plot."""
        views = self._selected_bias_views()
        if views and self._primary_bias_mode not in views:
            self._primary_bias_mode = views[0]
        if self.result is not None:
            self._draw_all_parameters()
            self.group_plot_page.render()

    def _bias_limit_changed(self, cell):
        row = next((r for r in range(self.mapping_table.rowCount()) if self.mapping_table.cellWidget(r, 10) is cell), None)
        if row is None:
            return
        parameter = self.mapping_table.item(row, 1).text().strip()
        value = cell.findChild(QDoubleSpinBox).value()
        show = cell.findChild(QCheckBox).isChecked()
        if self.result is not None and parameter in self.result.parameter_names:
            if self.result.bias_limits[parameter] != value:
                self.result.set_bias_limit(value, parameter)
            self.summary_model.set_frame(self.result.summary)
            self._show_mapping_results()
            self.workbook.mappings = tuple(replace(m, bias_limit=value, show_bias_limit=show) if m.name == parameter else m
                                           for m in self.workbook.mappings)
            self._draw_bias_limit(parameter)
            for detail in self.plot_groups.get(parameter, {}).get("wafer_details", {}).values():
                detail["workbook"].mappings = tuple(replace(m, bias_limit=value, show_bias_limit=show) for m in detail["workbook"].mappings)
                if detail["result"].bias_limits[parameter] != value:
                    detail["result"].set_bias_limit(value, parameter)
                detail["signature"] = (detail["workbook"].mappings[0], self.workbook.result_mode, self._selected_bias_views())
                self._draw_bias_limit(parameter, detail)
            for (key, name), block in self.group_plot_page.plot_groups.items():
                if name == parameter:
                    block["result"].set_bias_limit(value, parameter)
                    self._draw_bias_limit(parameter, block)
        if hasattr(self, "document"):
            self.document.refresh_identity()

    def _clear_mapping_results(self):
        self.mapping_table.blockSignals(True)
        for row in range(self.mapping_table.rowCount()):
            for column in range(4, self.mapping_table.columnCount()):
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
            "Slope", "Intercept", "R²", "Valid pairs", "Match type", "Result mode", "Bias limit", "Bias out of range"
        )
        self.mapping_table.blockSignals(True)
        for row in range(self.mapping_table.rowCount()):
            reference_item = self.mapping_table.item(row, 2)
            summary = summaries.get(reference_item.text()) if reference_item else None
            for column, field in enumerate(fields, start=4):
                if field == "Bias limit":
                    continue
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
                if field == "Bias out of range" and summary is not None:
                    unit = "dimensionless" if summary["Bias unit"] == "1" else summary["Bias unit"]
                    item.setToolTip(f"|Bias| > {summary['Bias limit']:g} {unit}; includes all finite analysis rows.\n"
                                    "Equal-to-limit and missing/non-finite values are not counted.")
        self.mapping_table.blockSignals(False)

    def _style_mapping_metric(self, item, field, value):
        """Apply accessible threshold styling without changing numeric text."""
        item.setBackground(QBrush())
        item.setForeground(QBrush())
        item.setToolTip("")
        font = item.font()
        font.setBold(False)
        item.setFont(font)
        message = _metric_warning(field, value, self.metric_highlighting)
        if not message:
            return
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        item.setBackground(QColor("#4a1822" if dark else "#fff0f1"))
        item.setForeground(QColor("#ffb4bd" if dark else "#a3132b"))
        item.setToolTip(message)
        font.setBold(True)
        item.setFont(font)

    def set_metric_highlighting(self, limits, *, refresh=True):
        self.metric_highlighting = _metric_highlighting_limits(limits)
        for model in self.findChildren(DataFrameModel):
            model.set_quality_limits(self.metric_highlighting)
        if refresh:
            self._show_mapping_results()
            self.document.refresh_identity()

    def edit_metric_highlighting(self):
        dialog = QDialog(self, objectName="metricHighlightingDialog")
        dialog.setWindowTitle("Metric highlighting")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 12)
        layout.setSpacing(12)
        form = QGridLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        fields = {}
        for row, (key, label, name) in enumerate((
                ("slope_min", "Slope minimum", "slopeHighlightMinimum"),
                ("slope_max", "Slope maximum", "slopeHighlightMaximum"),
                ("rsq_min", "R² minimum", "rsqHighlightMinimum"))):
            spin = QDoubleSpinBox(dialog, objectName=name)
            spin.setDecimals(6)
            spin.setRange(*((0, 1) if key == "rsq_min" else (-1_000_000, 1_000_000)))
            spin.setSingleStep(.01)
            spin.setValue(self.metric_highlighting[key])
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(spin, row, 1)
            fields[key] = spin
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        error = _label("", "hint")
        error.setWordWrap(True)
        layout.addWidget(error)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        apply = QPushButton("Apply", objectName="primary")
        buttons.addButton(apply, QDialogButtonBox.ButtonRole.ApplyRole)
        apply.clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        def validate():
            valid = fields["slope_min"].value() <= fields["slope_max"].value()
            apply.setEnabled(valid)
            error.setText("" if valid else "Slope minimum must not exceed maximum.")
        for spin in fields.values():
            spin.valueChanged.connect(validate)
        fit_window_to_screen(dialog, (480, 300), minimum=(420, 280))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_metric_highlighting({key: spin.value() for key, spin in fields.items()})
        dialog.deleteLater()

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
        self.empty_wafer_hint = _label("", "hint")
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
        if hasattr(self, "mapping_size"):
            self.mapping_size.setText(
                f"{self.mapping_table.rowCount():,} rows × {self.mapping_table.columnCount()} columns")
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
        self.save_button.setEnabled(True)  # Incomplete tables can be saved as drafts.
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
        self.run_action.setEnabled(bool(valid_rows and has_mapping and not input_error))
        missing_selection_columns = sorted(getattr(self, "_selection_columns_missing", set()))
        warning = False
        if missing_selection_columns:
            message = ("Data selection columns changed: "
                       + ", ".join(missing_selection_columns)
                       + " — run Groups → Data selection… to re-select.")
            warning = True
        elif input_error:
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
        if self.group_controls.state["enabled"] and self.result_mode.currentText().lower() == "final" and not self.raw_frame.empty:
            if row_ids(self.raw_frame) != row_ids(active_raw):
                raise ValueError("Preview/Final record identities or order differ. Align Wafer/Lot/PAD/Die records before sharing TestFlag/Mark classifications.")
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
            bias_limit=self._default_bias_limit,
            # The checkboxes only decide which Bias plots are shown; the
            # workbook itself always keeps a primary Bias mode.
            bias_views=self._selected_bias_views()
            or (self._primary_bias_mode,),
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
            correlation_selections=self._correlation_selection_states,
            trend_axis_settings={
                "ratio": self.second_axis_ratio,
                "mode": self.trend_axis_mode,
            },
            setup_splitter_sizes=tuple(self.setup_splitter.sizes()),
            parameter_order=parameter_order,
            test_flags=self.group_controls.flags_frame(),
            grouping_state=self.group_controls.state,
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
        stage = mode.lower()
        existing = self._prepare_stage_window("correlation", stage)
        if existing is not None:
            return existing
        workspace = self._correlation_window_factory()
        reference, scoped_raw = self._child_correlation_frames(workspace)
        workspace.set_sources(reference, scoped_raw, mappings, mode)
        book = None
        if hasattr(workspace, "set_workbook_groups"):
            book = self.current_workbook()
            workspace.set_workbook_groups(book)
        self._bind_workspace_selection(workspace, "correlation", stage)
        self._offer_second_axis_settings(workspace)
        self._configure_managed_close(workspace, "correlation", stage)
        if hasattr(workspace, "setWindowTitle"):
            workspace.setWindowTitle(f"{mode} Correlation and Trend")
        self._register_stage_workspace(workspace, "correlation", stage, book=book)
        workspace.show()
        self.remember_stage_inputs()
        return workspace

    def _open_correlation_clicked(self):
        try:
            self.open_correlation_workspace()
        except Exception as error:
            QMessageBox.warning(
                self, "Cannot open Correlation and Trend", str(error)
            )

    def open_stage_workspace(self, stage):
        existing = self._prepare_stage_window("map", stage)
        if existing is not None:
            return existing
        if self.result is None:
            self.run_analysis()
        self.workbook = self.current_workbook()
        book = self.workbook
        # The workspace owns the Card choice, so hand over untouched values.
        frame = self.workbook.stage_frame(stage, apply_card=False)
        workspace = self._wafer_window_factory()
        title = f"{str(stage).title()} · Match Workbook"
        self._offer_parameter_cards(workspace)
        workspace.set_table(frame, title)
        self._bind_workspace_selection(workspace, "map", stage)
        if not self._workspace_data_follows_workbook():
            # TEM owns this table; KLA/NOVA keep deriving it from Raw Data until
            # the engineer edits the child window.
            self._capture_stage_map(stage, frame)
        # Child edits remain a draft until its Save, or the parent's Save.
        self._configure_managed_close(workspace, "map", stage)
        if hasattr(workspace, "setWindowTitle"):
            workspace.setWindowTitle(f"{str(stage).title()} Wafer Map / Radius")
        self._register_stage_workspace(workspace, "map", stage, book=book)
        workspace.show()
        self.remember_stage_inputs()
        return workspace

    def _capture_stage_map(self, stage, frame):
        if self._syncing_stage_windows:
            # A refresh we pushed ourselves must not turn derived data into a
            # saved snapshot.
            return
        snapshot = frame.reset_index(drop=True).copy()
        if str(stage).lower() == "preview":
            self.preview_map_frame = snapshot
        else:
            self.final_map_frame = snapshot

    def _capture_stage_model(self, stage, model):
        if self._syncing_stage_windows:
            return
        try:
            frame = model.frame()
        except ValueError:
            return
        self._capture_stage_map(stage, frame)

    def _register_stage_workspace(self, workspace, kind=None, stage=None, *, book=None):
        """Track a child window and the WKB snapshot it owns, when applicable."""
        if hasattr(workspace, "set_workbook_participation"):
            workspace.set_workbook_participation(book if book is not None else self.current_workbook())
        self._stage_windows.append(workspace)
        if kind is not None:
            self._stage_window_context[workspace] = (
                str(kind).lower(), str(stage).lower()
            )
            scope = f"{kind}.{stage}"
            saved = self._workspace_states.get(scope)
            if saved and hasattr(workspace, "workspace_snapshot"):
                workspace._independent_data = bool(saved.get("data_override"))
                snapshot = workspace.workspace_snapshot()
                snapshot.states["ui"] = deepcopy(saved["ui"])
                snapshot.states.update(deepcopy(saved.get("analysis_states", {})))
                for name in snapshot.frames:
                    frame = self._workspace_frames.get(f"{scope}.{name}")
                    if frame is not None:
                        snapshot.frames[name] = frame.copy()
                workspace.restore_workspace(snapshot)
            if kind == "correlation":
                self._offer_second_axis_settings(workspace)
            if hasattr(workspace, "document"):
                workspace.document.mark_clean()
                if self.document.untrusted_recovery:
                    workspace.document.forced_dirty = True
                recovered = self._recovered_children.pop(scope, None)
                if recovered:
                    workspace.restore_workspace(recovered["draft"])
                    workspace._use_workbook_data = bool(recovered.get("follow_source"))
                    workspace.document.baseline = deepcopy(recovered["baseline"])
                    if kind == "correlation":
                        self._offer_second_axis_settings(workspace)
                workspace.document.refresh_identity()
                workspace._managed_after_close_handler = lambda child=workspace: self._forget_stage_workspace(child)
        if hasattr(workspace, "destroyed"):
            workspace.destroyed.connect(
                lambda *_args, window=workspace:
                self._forget_stage_workspace(window)
            )

    def _forget_stage_workspace(self, workspace):
        if workspace in self._stage_windows:
            self._stage_windows.remove(workspace)
        self._stage_window_context.pop(workspace, None)
        if hasattr(self, "document"):
            try:
                self.document.refresh_identity()
            except RuntimeError as error:
                if not self._deleted_qt_object(error):
                    raise

    def _capture_workspace_selection(self, kind, stage, state):
        if not isinstance(state, dict):
            return
        if kind == "correlation":
            saved = deepcopy(state)
            saved.pop("trend_axis_ratio", None)
            saved.pop("trend_axis_mode", None)
            self._correlation_selection_states[str(stage).lower()] = saved
            return
        states = (
            self._map_selection_states
            if kind == "map"
            else self._dynamic_selection_states
        )
        saved = {
            "wafers": tuple(state.get("wafers", ())),
            "metrics": tuple(state.get("metrics", ())),
            "min_records": int(state.get("min_records", 0) or 0),
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
        if (kind == "correlation" and self._workspace_states.get(f"{kind}.{stage}")
                and hasattr(workspace, "workspace_snapshot")):
            # Registration restores the complete accepted child document below.
            # Do not draw the same saved selection first on provisional tables,
            # or replace the accepted selection with an intermediate snapshot.
            return
        if kind == "map":
            states = self._map_selection_states
        elif kind == "dynamic":
            states = self._dynamic_selection_states
        else:
            states = self._correlation_selection_states
        # Accepted choices are captured only by Save, not by each checkbox.
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
            lambda frame, workspace_kind=kind, stage_name=stage,
            child=workspace:
            self._save_managed_workspace_on_close(
                workspace_kind, stage_name, frame, child
            )
        )
        configure = getattr(workspace, "configure_workbook_owner", None)
        if callable(configure):
            configure(self, f"{kind}.{stage}")

    def _single_stage_window(self):
        """TEM keeps one analysis window at a time; KLA and NOVA allow all."""
        return str(self.match_type.currentText()).strip().upper() == "TEM"

    def _workspace_data_follows_workbook(self):
        """KLA and NOVA derive Map/Dynamic from the workbook's Raw Data.

        TEM keeps independent Map/Radius and Dynamic tables, so those windows
        must never be overwritten from the workbook.
        """
        return not self._single_stage_window()

    def _prepare_stage_window(self, kind, stage):
        """TEM keeps one window per analysis button.

        Opening a button whose window is already open brings that window
        forward and refreshes it instead of stacking a second copy; the other
        two kinds stay open. KLA and NOVA may open each window separately.
        """
        if not self._stage_windows:
            return None
        wanted = (str(kind).lower(), str(stage).lower())
        for workspace in tuple(self._stage_windows):
            if self._stage_window_context.get(workspace) != wanted:
                continue
            # Reopening is activation, never a destructive data refresh.
            workspace.show()
            raise_window = getattr(workspace, "raise_", None)
            if callable(raise_window):
                raise_window()
            activate = getattr(workspace, "activateWindow", None)
            if callable(activate):
                activate()
            return workspace
        return None

    def _close_stage_windows(self):
        """Persist and close every open analysis window."""
        workspaces = tuple(self._stage_windows)
        if not workspaces:
            return
        self._save_stage_workspaces_before_close(workspaces)
        self._close_stage_workspaces(workspaces)

    def _stage_window_inputs(self):
        """Workbook tables the open analysis windows mirror."""
        return (
            self.reference_frame.copy(),
            self._active_raw_frame().copy(),
            tuple(self.selected_mappings()),
            str(self.match_type.currentText()),
        )

    @staticmethod
    def _same_stage_inputs(left, right):
        if left is None or right is None:
            return False
        return (
            left[0].equals(right[0])
            and left[1].equals(right[1])
            and left[2] == right[2]
            and left[3] == right[3]
        )

    def remember_stage_inputs(self):
        """Mark the workbook tables the open windows were built from."""
        self._stage_sync_inputs = self._stage_window_inputs()

    def sync_stage_windows(self):
        """Refresh open analysis windows from the Match Workbook tables.

        KLA and NOVA keep all three windows on the workbook's Reference/Raw
        data. In TEM only Correlation and Trend follows, because its Map/Radius
        and Dynamic tables are independent inputs.
        """
        if not self._stage_windows or self._syncing_stage_windows:
            return
        inputs = self._stage_window_inputs()
        if self._same_stage_inputs(inputs, self._stage_sync_inputs):
            return
        self._syncing_stage_windows = True
        try:
            for workspace in tuple(self._stage_windows):
                context = self._stage_window_context.get(workspace)
                if context is None:
                    continue
                kind, stage = context
                if hasattr(workspace, "set_workbook_participation"):
                    workspace.set_workbook_participation(self.current_workbook())
                # Dynamic keeps its own table in every match type; the Map data
                # is only derived from Raw Data for KLA and NOVA.
                follows = kind == "correlation" or (
                    kind == "map" and self._workspace_data_follows_workbook()
                )
                if not follows:
                    continue
                try:
                    self._refresh_stage_workspace(workspace, kind, stage)
                except Exception as error:
                    LOGGER.warning(
                        "Could not refresh the %s %s window: %s",
                        stage, kind, error,
                    )
            self._stage_sync_inputs = inputs
        finally:
            self._syncing_stage_windows = False

    def _refresh_stage_workspace(self, workspace, kind, stage, *, reset_data=False):
        """Push the current workbook tables into one open analysis window."""
        if hasattr(workspace, "document") and not reset_data:
            baseline = workspace.document.baseline
            if baseline is not None:
                current_frames = workspace.workspace_snapshot().frames
                if any(not frame.equals(baseline.frames.get(name, pd.DataFrame()))
                       for name, frame in current_frames.items()):
                    workspace._independent_data = True
                    workspace.document.refresh_identity()
                    return  # Never overwrite the child's unsaved measurement draft.
            if self._workspace_states.get(f"{kind}.{stage}", {}).get("data_override"):
                if hasattr(workspace, "ownership_label"):
                    workspace.ownership_label.setToolTip("Using independently edited data; not overwritten by Workbook source changes.")
                return
        state = getattr(workspace, "selection_state", None)
        saved = state() if callable(state) else None
        tabs = getattr(workspace, "tabs", None)
        tab_index = (
            tabs.currentIndex() if hasattr(tabs, "currentIndex") else None
        )
        views = self._workspace_views(workspace)
        pages = self._workspace_pages(workspace)
        if kind == "correlation":
            reference, scoped_raw = self._child_correlation_frames(workspace)
            workspace.set_sources(
                reference,
                scoped_raw,
                self.selected_mappings(),
                str(stage).title(),
            )
            if hasattr(workspace, "set_workbook_groups"):
                workspace.set_workbook_groups(self.current_workbook())
        else:
            self.workbook = self.current_workbook()
            applies = getattr(workspace, "_workbook_selection_applies", True)
            frame = (
                self.workbook.stage_frame(stage, apply_card=False, apply_selection=applies)
                if kind == "map"
                else self.workbook.dynamic_frame(stage, apply_card=False, apply_selection=applies)
            )
            label = "Wafer Map / Radius" if kind == "map" else "Dynamic"
            self._offer_parameter_cards(workspace)
            workspace.set_table(
                frame, f"{str(stage).title()} {label} · Match Workbook",
                keep_local_selection=True,
            )
        if tabs is not None and tab_index is not None and tab_index >= 0:
            # Refreshing data must not move the engineer off the tab they are
            # reading; loading a fresh window still starts at its first tab.
            tabs.setCurrentIndex(tab_index)
        self._restore_workspace_views(views)
        restore = getattr(workspace, "restore_selection", None)
        if saved is not None and callable(restore):
            restore(saved)
        if kind == "correlation":
            self._offer_second_axis_settings(workspace)
        self._restore_workspace_pages(pages)
        if hasattr(workspace, "document") and workspace.document.baseline is not None and not reset_data:
            # Parent-driven table refreshes are not child edits. Keep draft
            # configuration intact while advancing the table-only baseline.
            workspace.document.baseline.frames = deepcopy(workspace.workspace_snapshot().frames)

    def _child_correlation_frames(self, workspace):
        """Reference/Raw pair for one child; honours its selection scope."""
        raw = self._active_raw_frame()
        if (getattr(workspace, "_workbook_selection_applies", True)
                and len(raw) == len(self.reference_frame) and not raw.empty):
            from .match_groups import applied_state, participation_rows
            selection = applied_state(self.current_workbook().grouping_state)["data_selection"]
            if selection is not None:
                allowed = list(participation_rows(raw, selection))
                return (self.reference_frame.iloc[allowed].reset_index(drop=True),
                        raw.iloc[allowed].reset_index(drop=True))
        return self.reference_frame, raw

    def child_selection_context(self, workspace):
        """Order / Reference frames shown in a child's own Data selection."""
        context = self._stage_window_context.get(workspace)
        if context is None:
            return []
        kind, stage = context
        if kind in ("map", "dynamic") and not self._workspace_data_follows_workbook():
            return []
        try:
            current_rows = len(workspace.model.frame())
        except ValueError:
            return []
        if not current_rows:
            return []
        from .match_groups import applied_state, participation_rows
        book = self.current_workbook()
        raw = (book.final_match_raw
               if str(stage).lower() == "final" and book.final_match_raw is not None
               else book.raw)
        if kind == "correlation":
            raw = self._active_raw_frame()
        selection = applied_state(book.grouping_state)["data_selection"]
        if getattr(workspace, "_workbook_selection_applies", True) and selection is not None:
            allowed = list(participation_rows(raw, selection))
        else:
            allowed = list(range(len(raw)))
        if len(allowed) != current_rows or len(raw) != len(self.reference_frame):
            return []
        frames = []
        plan = getattr(self.result, "group_plan", None)
        if plan is not None and len(plan.order_frame) == len(raw):
            frames.append(("Order", plan.order_frame.iloc[allowed].reset_index(drop=True)))
        frames.append(("Reference", self.reference_frame.iloc[allowed].reset_index(drop=True)))
        return frames

    def apply_child_selection_scope(self, workspace):
        """Reload a child's table as the post-selection or the full copy."""
        context = self._stage_window_context.get(workspace)
        if context is None:
            return False
        kind, stage = context
        if kind in ("map", "dynamic") and not self._workspace_data_follows_workbook():
            return False
        if getattr(workspace, "_independent_data", False) and QMessageBox.question(
                workspace, "Use Workbook Data",
                "Discard this analysis's independent measurements and use current Workbook data?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Discard:
            return False
        previous = self._accepted_workspace_state()
        try:
            if kind in ("map", "dynamic"):
                setattr(self, f"{stage}_{kind}_frame", None)
            self._refresh_stage_workspace(workspace, kind, stage, reset_data=True)
        except Exception as error:
            QMessageBox.warning(workspace, "Cannot change selection scope", str(error))
            return False
        finally:
            self._restore_accepted_workspace_state(previous)
        workspace._use_workbook_data = True
        workspace._independent_data = False
        workspace.document.forced_dirty = True
        workspace.document.refresh_identity()
        return True

    def reset_child_to_workbook(self, workspace):
        """Explicitly replace an independent table; acceptance still requires Save."""
        context = self._stage_window_context.get(workspace)
        if context is None:
            return False
        kind, stage = context
        if kind in ("map", "dynamic") and not self._workspace_data_follows_workbook():
            return False
        if self.document.untrusted_recovery:
            QMessageBox.warning(self, "Cannot replace recovered analysis", "Save the entire recovered Workbook As first.")
            return False
        choice = QMessageBox.question(workspace, "Use Workbook Data",
                                      "Discard this analysis's independent measurements and use current Workbook data?\n"
                                      "Other analysis drafts and the saved file are unchanged until you save.",
                                      QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if choice != QMessageBox.StandardButton.Discard:
            return False
        previous = self._accepted_workspace_state()
        try:
            if kind in ("map", "dynamic"):
                setattr(self, f"{stage}_{kind}_frame", None)
            self._refresh_stage_workspace(workspace, kind, stage, reset_data=True)
        except Exception as error:
            QMessageBox.warning(workspace, "Cannot use Workbook data", str(error))
            return False
        finally:
            self._restore_accepted_workspace_state(previous)
        workspace._use_workbook_data = True
        workspace._independent_data = False
        workspace.document.forced_dirty = True
        workspace.document.refresh_identity()
        return True

    @staticmethod
    def _workspace_pages(workspace):
        """Stacked sub-pages (curve boxes versus drawn plots) to keep visible."""
        pages = []
        for name in ("plot_page", "radius_page", "correlation_page",
                     "sequence_page"):
            page = getattr(workspace, name, None)
            stack = getattr(page, "stack", None)
            if stack is None or not hasattr(stack, "setCurrentWidget"):
                continue
            current = stack.currentWidget()
            if current is not None:
                pages.append((stack, current))
        return pages

    @staticmethod
    def _restore_workspace_pages(pages):
        """Leave the engineer on the sub-page they were reading."""
        for stack, current in pages:
            try:
                stack.setCurrentWidget(current)
            except RuntimeError:
                # The page was destroyed before the refresh finished.
                return

    def _offer_parameter_cards(self, workspace):
        """Hand this workbook's Cards to a workspace that offers the option."""
        setter = getattr(workspace, "set_parameter_cards", None)
        if not callable(setter):
            return
        try:
            if self._analysis_current and self.result is not None:
                cards = {name: (self.result.card(name).slope, self.result.card(name).intercept)
                         for name in self.result.parameter_names}
            else:
                # An edit can precede the queued analysis. Never give a newly
                # opened child the Card of the earlier source values.
                cards = self.workbook.parameter_cards()
        except Exception as error:
            LOGGER.warning("Could not compute the parameter Cards: %s", error)
            return
        setter(cards)

    def set_second_axis_ratio(self, ratio):
        """Keep every open Trend window on the decimal auto threshold."""
        self.second_axis_ratio = float(ratio)
        if self.second_axis_spin.value() != self.second_axis_ratio:
            self.second_axis_spin.setValue(self.second_axis_ratio)
        for workspace in tuple(self._stage_windows):
            context = self._stage_window_context.get(workspace)
            if context is None or context[0] != "correlation":
                continue
            setter = getattr(workspace, "set_second_axis_ratio", None)
            if not callable(setter):
                continue
            setter(self.second_axis_ratio)

    def set_trend_axis_mode(self, mode):
        """Use automatic, forced dual-axis, or forced single-axis plotting."""
        if mode not in AXIS_MODE_LABELS:
            return
        self.trend_axis_mode = mode
        self._refresh_axis_mode_menu()
        for workspace in tuple(self._stage_windows):
            context = self._stage_window_context.get(workspace)
            if context is None or context[0] != "correlation":
                continue
            setter = getattr(workspace, "set_trend_axis_mode", None)
            if not callable(setter):
                continue
            setter(mode)

    def _refresh_axis_mode_menu(self):
        for mode, action in self.second_axis_actions.items():
            marker = "●" if mode == self.trend_axis_mode else "○"
            action.setText(f"{marker} {AXIS_MODE_LABELS[mode]}")
        self.second_axis_spin.setEnabled(self.trend_axis_mode == "auto")

    def _offer_second_axis_settings(self, workspace):
        """Both stages always use the workbook menu's shared axis policy."""
        ratio_setter = getattr(workspace, "set_second_axis_ratio", None)
        mode_setter = getattr(workspace, "set_trend_axis_mode", None)
        if callable(ratio_setter):
            ratio_setter(self.second_axis_ratio)
        if callable(mode_setter):
            mode_setter(self.trend_axis_mode)

    @staticmethod
    def _workspace_views(workspace):
        """Editable grids whose position must survive a data refresh."""
        views = []
        for name in ("sheet", "reference_sheet"):
            view = getattr(workspace, name, None)
            if view is None or not hasattr(view, "verticalScrollBar"):
                continue
            index = view.currentIndex()
            views.append((
                view,
                index.row(),
                index.column(),
                view.horizontalScrollBar().value(),
                view.verticalScrollBar().value(),
            ))
        return views

    @staticmethod
    def _restore_workspace_views(views):
        """Put each grid back on the cell and offset it was showing."""
        if not views:
            return
        for view, row, column, horizontal, vertical in views:
            model = view.model()
            if model is not None and row >= 0 and column >= 0:
                index = model.index(row, column)
                if index.isValid():
                    view.setCurrentIndex(index)
            view.horizontalScrollBar().setValue(horizontal)
            view.verticalScrollBar().setValue(vertical)

        def settle():
            for view, _row, _column, horizontal, vertical in views:
                try:
                    view.horizontalScrollBar().setValue(
                        min(horizontal, view.horizontalScrollBar().maximum())
                    )
                    view.verticalScrollBar().setValue(
                        min(vertical, view.verticalScrollBar().maximum())
                    )
                except RuntimeError:
                    # The window was closed before the deferred pass ran.
                    return

        QTimer.singleShot(0, settle)

    def _save_managed_workspace_on_close(
        self, kind, stage, frame, workspace=None
    ):
        if self.workbook_path is None or not writable_path(self.workbook_path) or self.workbook_path.suffix.lower() != ".wkb":
            return self.save_wkb_dialog(capture_children=False, child=workspace) or False
        return self.save_workbook(self.workbook_path, capture_children=False, child=workspace)

    def _capture_managed_stage_workspace(self, workspace):
        """Copy a managed child's live state before either window is destroyed."""
        context = self._stage_window_context.get(workspace)
        if context is None:
            return
        kind, stage = context
        if hasattr(workspace, "workspace_snapshot"):
            draft = local_snapshot(workspace)
            scope = f"{kind}.{stage}"
            prior = self._workspace_states.get(scope, {})
            baseline = workspace.document.baseline
            edited = baseline is None or any(
                not frame.equals(baseline.frames.get(name, pd.DataFrame()))
                for name, frame in draft.frames.items())
            reset_data = bool(getattr(workspace, "_use_workbook_data", False))
            override = not reset_data and bool(prior.get("data_override") or edited)
            if reset_data:
                if kind in ("map", "dynamic"):
                    setattr(self, f"{stage}_{kind}_frame", None)
                for name in tuple(self._workspace_frames):
                    if name.startswith(scope + "."):
                        del self._workspace_frames[name]
            self._workspace_states[scope] = {"ui": draft.states["ui"], "workspace_type": draft.workspace_type,
                                              "data_override": override,
                                              "analysis_states": {key: deepcopy(value) for key, value in draft.states.items() if key != "ui"}}
            if kind == "correlation" and override:
                for name, frame in draft.frames.items():
                    self._workspace_frames[f"{scope}.{name}"] = frame.copy()
            if kind in ("map", "dynamic"):
                frame = draft.frames["input_data"]
                try:
                    MatchWorkbook._validate_workspace_snapshot(frame, "Child draft")
                except ValueError:
                    # An invalid child sheet must not prevent the parent from
                    # opening its otherwise valid analysis or the sheet editor.
                    self._workspace_frames[f"{scope}.input_data"] = frame.copy()
                else:
                    if kind == "map" and (override or not self._workspace_data_follows_workbook()):
                        self._capture_stage_map(stage, frame)
                    elif kind == "dynamic":
                        self._capture_stage_dynamic(stage, frame)
                    self._workspace_frames.pop(f"{scope}.input_data", None)
        if kind == "correlation":
            selection_getter = getattr(workspace, "selection_state", None)
            if callable(selection_getter):
                self._capture_workspace_selection(
                    kind, stage, selection_getter()
                )
            return
        model = getattr(workspace, "model", None)
        frame_getter = getattr(model, "frame", None)
        if callable(frame_getter) and not hasattr(workspace, "workspace_snapshot"):
            frame = frame_getter()
            if kind == "dynamic":
                # Dynamic owns its table in every match type.
                self._capture_stage_dynamic(stage, frame)
            elif kind == "map":
                # Legacy adapters have no document baseline; accept their table
                # only at the explicit save boundary.
                self._capture_stage_map(stage, frame)
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
            if hasattr(workspace, "document"):
                workspace.document.force_close = True
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
        """One parent decision covers its open child drafts; no silent write."""
        if not self.document.confirm_close():
            event.ignore()
            return
        self.group_settings_dialog.hide()
        workspaces = tuple(self._stage_windows)
        if not workspaces:
            self._auto_run_pending = False
            self._plot_layout_identity_timer.stop()
            self.document.closed()
            event.accept()
            return
        try:
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
        self._auto_run_pending = False
        self._plot_layout_identity_timer.stop()
        self.document.closed()

    def _open_stage_clicked(self, stage):
        try:
            self.open_stage_workspace(stage)
        except Exception as error:
            QMessageBox.warning(self, f"Cannot open {stage.title()}", str(error))

    def open_dynamic_workspace(self, stage):
        existing = self._prepare_stage_window("dynamic", stage)
        if existing is not None:
            return existing
        if self.result is None:
            self.run_analysis()
        self.workbook = self.current_workbook()
        # Dynamic measures its own table: restore the saved Dynamic table when
        # the workbook has one, otherwise start from an empty grid instead of
        # copying the Raw/Map data (Preview and Final behave the same way).
        saved_dynamic = (
            self.workbook.preview_dynamic
            if str(stage).lower() == "preview"
            else self.workbook.final_dynamic
        )
        frame = (
            pd.DataFrame()
            if saved_dynamic is None
            else saved_dynamic.reset_index(drop=True).copy()
        )
        workspace = self._dynamic_window_factory()
        title = f"{str(stage).title()} Dynamic · Match Workbook"
        self._offer_parameter_cards(workspace)
        workspace.set_table(frame, title)
        self._bind_workspace_selection(workspace, "dynamic", stage)
        model = getattr(workspace, "model", None)
        if model is not None:
            # Dynamic holds its own table in every match type, so opening the
            # window freezes the table it starts from.
            self._capture_dynamic_model(stage, model)
        else:
            self._capture_stage_dynamic(stage, frame)
        self._configure_managed_close(workspace, "dynamic", stage)
        if hasattr(workspace, "setWindowTitle"):
            workspace.setWindowTitle(f"{str(stage).title()} Dynamic")
        self._register_stage_workspace(workspace, "dynamic", stage)
        workspace.show()
        self.remember_stage_inputs()
        return workspace

    def _capture_stage_dynamic(self, stage, frame):
        if self._syncing_stage_windows:
            return
        snapshot = frame.reset_index(drop=True).copy()
        if str(stage).lower() == "preview":
            self.preview_dynamic_frame = snapshot
        else:
            self.final_dynamic_frame = snapshot

    def _capture_dynamic_model(self, stage, model):
        if self._syncing_stage_windows:
            return
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

    def run_analysis(self, *, apply_groups=True):
        self._auto_run_pending = False
        self._pending_auto_view_state = None
        scroll_value = self.setup_scroll.verticalScrollBar().value()
        self._refresh_group_projection()
        if apply_groups:
            if self.group_controls.plan is None:
                raise ValueError(self.group_controls.status.text())
            self.group_controls.accept_changes()
            self._stage_sync_inputs = None
        self.workbook = self.current_workbook()
        self.result = self.workbook.analyze()
        self._analysis_current = True
        self._group_only_pending = False
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
        self.group_plot_page.set_result(self.result)
        self._update_state()
        # Open analysis windows mirror the workbook tables they were built from.
        try:
            self.sync_stage_windows()
        except Exception as error:
            LOGGER.warning("Could not refresh the analysis windows: %s", error)
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
        if self.result is None:
            self._clear_plot_groups()
            self._show_empty_plot_hint("")
            return
        self._parameter_order = list(
            self._reconciled_parameter_order(self.result.parameter_names)
        )
        layout_key = (tuple(self._parameter_order), self.workbook.result_mode, self.workbook.match_type,
                      tuple(self._selected_bias_views()), self.result.group_plan.enabled)
        previous_key = getattr(self, "_plot_layout_key", None)
        reuse = previous_key is not None and previous_key[1:] == layout_key[1:] and bool(self.plot_groups)
        if not reuse:
            self._clear_plot_groups()
        else:
            for parameter in set(self.plot_groups) - set(self._parameter_order):
                group = self.plot_groups.pop(parameter)
                for layout, key in ((self.plot_groups_layout, "card"), (self.wafer_groups_layout, "wafer_card")):
                    layout.removeWidget(group[key])
                    group[key].deleteLater()
        self._plot_layout_key = layout_key
        identity = (self.result.group_plan.ids, deepcopy(self.result.group_plan.state))
        for parameter in self._parameter_order:
            data = self.result.series(parameter)
            mapping = next(m for m in self.workbook.mappings if m.name == parameter)
            source_mapping = (mapping.reference_column, mapping.raw_column)
            group = self.plot_groups.get(parameter)
            if (group is not None and group.get("source_identity") == identity
                    and group.get("source_mapping") == source_mapping and data.equals(group.get("source_data"))):
                self._draw_bias_limit(parameter)
                continue
            if group is None:
                group = self._create_plot_group(parameter)
                self.plot_groups[parameter] = group
                self.plot_groups_layout.addWidget(group["card"])
                self.wafer_groups_layout.addWidget(group["wafer_card"])
            else:
                for plot in group["plots"].values():
                    plot.clear()
                    if plot.getPlotItem().legend is not None:
                        plot.getPlotItem().legend.clear()
            self._draw_parameter_group(parameter, group)
            group["source_identity"] = identity
            group["source_mapping"] = source_mapping
            group["source_data"] = data.copy()
        if reuse and previous_key[0] != layout_key[0]:
            self._apply_parameter_order()
        if not any(
            not group["wafer_card"].isHidden()
            for group in self.plot_groups.values()
        ):
            self.empty_wafer_hint = _label(
                "",
                "hint",
            )
            self.wafer_groups_layout.addWidget(self.empty_wafer_hint)
        self._resize_results_for_plot_groups()
        self._restore_setup_splitter_layout(splitter_sizes)
        self.result_status.setText(self._result_descriptor)

    def _create_plot_group(self, parameter, detail_key=None):
        storage_key = detail_key or parameter
        card = _ParameterCard(storage_key, self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(12)

        heading = QHBoxLayout()
        heading.addWidget(_ParameterDragHandle(storage_key, card))
        heading.addStretch()
        note = _label("", "hint")
        heading.addWidget(note)
        card_layout.addLayout(heading)

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
        for name, bottom, left in specs:
            if name == "match":
                plot_class = _MatchPlotWidget
            elif name == "trend":
                plot_class = _TrendPlotWidget
            else:
                plot_class = InteractivePlotWidget
            plot = self._plot_widget(bottom, left, plot_class=plot_class)
            plot.getPlotItem().setContentsMargins(6, 4, 8, 8)
            if name in {"bias", "bias-percent"}:
                plot.getAxis("left").enableAutoSIPrefix(False)
            plots[name] = plot
        primary_width = 340
        plot_container = ParameterPlotArea(plots, plot_height=primary_height)
        match_title = plots["match"].title_label
        match_formula = plots["match"].formula_label
        mode = self.result_mode.currentText().lower()
        trend_card_key = (mode, storage_key)
        trend_card_enabled = self._trend_card_state.get(
            trend_card_key, mode == "preview"
        )
        self._trend_card_state[trend_card_key] = trend_card_enabled
        trend_checkbox = plots["trend"].card_checkbox
        trend_checkbox.setToolTip(
            "Use this parameter's overall Match Card; Group plots selects its own Card source."
        )
        trend_checkbox.setChecked(trend_card_enabled)
        trend_checkbox.toggled.connect(
            lambda checked, name=parameter:
            self._trend_card_toggled(name, checked, detail_key)
        )
        card_layout.addWidget(plot_container)
        variant = "|".join(plots)
        saved_layout = self._plot_layout_states.get(mode, {}).get(storage_key, {}).get(variant)
        if saved_layout is not None:
            plot_container.restoreState(saved_layout)
        plot_container.layoutChanged.connect(
            lambda: self._parameter_plot_layout_changed(storage_key, mode, variant, plot_container)
        )

        if detail_key is not None:
            return {"card": card, "note": note, "plots": plots, "plot_area": plot_container,
                    "trend_card_key": trend_card_key, "storage_key": storage_key}

        wafer_card = self._create_parameter_section(parameter)
        wafer_layout = wafer_card.layout()
        wafer_header = wafer_layout.itemAt(0).layout()
        wafer_model = _WaferMetricsModel(parent=wafer_card, quality_limits=self.metric_highlighting)
        wafer_view = _WaferMetricsView(objectName="waferMetricsTable")
        wafer_view.setModel(wafer_model)
        uncheck_all = wafer_view.uncheck_all
        uncheck_all.clicked.connect(lambda: self._uncheck_all_wafers(parameter))
        wafer_model.modelReset.connect(wafer_view._position_uncheck_all)
        draw_delegate = _DrawCellDelegate(wafer_view)
        wafer_view.setAlternatingRowColors(True)
        wafer_view.setFixedHeight(280)
        wafer_view.setMinimumWidth(180)
        wafer_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        wafer_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        wafer_view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        wafer_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        wafer_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        wafer_model.checkedChanged.connect(lambda row, checked: self._wafer_checked(parameter, row, checked))
        wafer_view.selectionModel().selectionChanged.connect(lambda *_: self._wafer_selection_changed(parameter))
        wafer_view.clearRequested.connect(lambda: self._clear_wafer_selection(parameter))
        wafer_metrics_layout = QHBoxLayout()
        wafer_metrics_layout.setSpacing(14)
        wafer_metrics_layout.addWidget(wafer_view, 1)
        wafer_plots = QWidget()
        wafer_plot_layout = QGridLayout(wafer_plots)
        wafer_plot_layout.setContentsMargins(0, 0, 0, 0)
        wafer_plot_layout.setHorizontalSpacing(14)
        wafer_r2 = self._plot_widget("Wafer", "R²")
        wafer_slope = self._plot_widget("Wafer", "Slope")
        for column, plot in enumerate((wafer_r2, wafer_slope)):
            plot.setFixedSize(420, 280)
            plot.getAxis("left").enableAutoSIPrefix(False)
            wafer_plot_layout.addWidget(plot, 0, column)
        for plot in (wafer_r2, wafer_slope):
            plot.setToolTip("Click a point to find its row. Click the same point again, or press Esc, to clear the highlight.")
            # Dense single-wafer plots thin the row-number ticks out so the
            # labels never overlap, however narrow the card becomes.
            plot.getPlotItem().getViewBox().sigResized.connect(
                lambda *_args, name=parameter: self._refresh_wafer_ticks(name)
            )
        for widget in (wafer_view, wafer_r2, wafer_slope):
            shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), widget)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda: self._clear_wafer_selection(parameter))
        wafer_plots.setFixedSize(854, 280)
        wafer_metrics_layout.addWidget(wafer_plots)
        wafer_layout.addLayout(wafer_metrics_layout)
        wafer_detail_layout = QVBoxLayout()
        wafer_detail_layout.setSpacing(12)
        wafer_layout.addLayout(wafer_detail_layout)
        wafer_card.hide()

        card.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        group = {
            "card": card,
            "note": note,
            "plots": plots,
            "plot_area": plot_container,
            "match_title": match_title,
            "match_formula": match_formula,
            "primary_height": primary_height,
            "primary_width": primary_width,
            "wafer_card": wafer_card,
            "wafer_model": wafer_model,
            "wafer_view": wafer_view,
            "wafer_draw_delegate": draw_delegate,
            "wafer_header": wafer_header,
            "wafer_metrics_layout": wafer_metrics_layout,
            "wafer_uncheck_all": uncheck_all,
            "wafer_r2": wafer_r2,
            "wafer_slope": wafer_slope,
            "wafer_detail_layout": wafer_detail_layout,
            "wafer_details": {},
            "trend_card_key": trend_card_key,
        }
        return group

    def _parameter_plot_layout_changed(self, parameter, stage, variant, area):
        layouts = normalize_plot_layouts({stage: {parameter: {variant: area.saveState()}}})
        self._plot_layout_states.setdefault(stage, {}).setdefault(parameter, {})[variant] = layouts[stage][parameter][variant]
        sizes = self.setup_splitter.sizes()
        self._resize_results_for_plot_groups()
        self._restore_setup_splitter_layout(sizes)
        if hasattr(self, "document"):
            self._plot_layout_identity_timer.start()

    def _draw_parameter_group(self, parameter, group):
        result = group.get("result", self.result)
        workbook = group.get("workbook", self.workbook)
        grouped = result.group_plan.enabled
        data = (result.group_series(parameter, trend=True) if grouped
                else result.series(parameter))
        card = result.card(parameter)
        fit_card = group.get("fit_card", card)
        mapping = next(
            (
                candidate
                for candidate in workbook.mappings
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
            measurement_spans = [] if grouped else result.measurement_spans()
        except ValueError:
            measurement_spans = []
        if measurement_spans:
            # Reserve the same footer in every primary panel. Zooming restores
            # Lot/PAD without shifting the frames or exposing an axis title.
            lines = max(2, max(label.count("\n") + 1 for _, _, label in measurement_spans))
            plots["match"].getAxis("bottom").setHeight(lines * QFontMetrics(plots["match"].font()).height() + 12)
            for name in ("trend", "bias", "bias-percent"):
                plot = plots.get(name)
                if plot is None:
                    continue
                previous = plot.getAxis("bottom")
                axis = SpanLabelAxis(measurement_spans, font=plot.font(), reserve_lines=lines)
                axis.setPen(previous.pen())
                axis.setTextPen(previous.textPen())
                axis.enableAutoSIPrefix(False)
                plot.setAxisItems({"bottom": axis})
                plot.setLabel("bottom", "")
                axis.refresh()

        match_plot = plots["match"]
        valid = np.isfinite(raw) & np.isfinite(reference)
        fit_text = ""
        match_plot.plot(raw[valid], reference[valid], pen=None, symbol="o", symbolSize=5,
                        symbolBrush="#4f8bd6", symbolPen=None)
        if valid.any() and np.isfinite(fit_card.slope) and np.isfinite(fit_card.intercept):
            low, high = float(np.min(raw[valid])), float(np.max(raw[valid]))
            x_line = np.array([low, high])
            y_line = fit_card.slope * x_line + fit_card.intercept
            match_plot.plot(
                x_line,
                y_line,
                pen=pg.mkPen("#e09f3e", width=2),
            )
            intercept_sign = "+" if fit_card.intercept >= 0 else "-"
            fit_text = (
                f"y = {fit_card.slope:.6g}x {intercept_sign} "
                f"{abs(fit_card.intercept):.6g}\nR² = {fit_card.r_squared:.6g}"
            )
        match_plot.set_match_heading(raw_column, fit_text)

        group["trend_data"] = (row, reference, raw, card_value)
        self._draw_trend_plot(parameter, group)

        bias_plot = plots.get("bias")
        if bias_plot is not None:
            unit = parse_unit(mapping.reference_column if mapping is not None else parameter)
            bias_plot.setLabel("left", "Bias" if unit == "1" else f"Bias ({unit})")
            bias_plot.plot(
                row,
                bias,
                connect="finite",
                pen=pg.mkPen("#4f8bd6", width=1.3),
                symbol="o",
                symbolSize=5,
                symbolBrush="#4f8bd6",
                symbolPen=None,
            )
            # Zero is a reference, not an observation to include in auto-range.
            bias_plot.addItem(pg.InfiniteLine(
                pos=0, angle=0,
                pen=pg.mkPen("#8a8f98", width=1, style=Qt.PenStyle.DashLine),
            ), ignoreBounds=True)
            bias_plot.setTitle("Bias")
            self._draw_bias_limit(parameter, group)

        bias_percent_plot = plots.get("bias-percent")
        if bias_percent_plot is not None:
            bias_percent_plot.plot(
                row,
                bias_percent,
                connect="finite",
                pen=pg.mkPen("#4f8bd6", width=1.3),
                symbol="o",
                symbolSize=5,
                symbolBrush="#4f8bd6",
                symbolPen=None,
            )
            bias_percent_plot.addItem(pg.InfiniteLine(
                pos=0, angle=0,
                pen=pg.mkPen("#8a8f98", width=1, style=Qt.PenStyle.DashLine),
            ), ignoreBounds=True)
            bias_percent_plot.setTitle("Bias %")
        header_height = max(_MatchPlotWidget.HEADER_HEIGHT,
                            *(getattr(plot, "_caption_header_height", 0) for plot in plots.values()))
        for primary_plot in plots.values():
            primary_plot.getPlotItem().layout.setRowFixedHeight(
                0, header_height
            )
            primary_plot.getViewBox().updateAutoRange()
        for name in ("trend", "bias", "bias-percent"):
            plot = plots.get(name)
            if plot is not None and len(data):
                plot.set_auto_x_range((.5, len(data) + .5))
                plot.setXRange(.5, len(data) + .5, padding=0)
        if grouped:
            for name in ("bias", "bias-percent"):
                plot = plots.get(name)
                if plot is not None:
                    plot.setXRange(.5, len(data) + .5, padding=0)
                    set_group_axes(plot, result, data, show_wafers=group.get("show_wafers", False))
        if "wafer_card" in group:
            if self.isVisible() and not self.wafer_groups_widget.isVisible() and "wafer_summary" in group:
                group["wafer_metrics_pending"] = True
            else:
                self._draw_wafer_metrics(parameter, group)

    def _draw_bias_limit(self, parameter, group=None):
        group = group if group is not None else self.plot_groups.get(parameter)
        plot = None if group is None else group["plots"].get("bias")
        if plot is None:
            return
        for line in getattr(plot, "_bias_limit_lines", []):
            plot.removeItem(line)
        plot._bias_limit_lines = []
        workbook = group.get("workbook", self.workbook)
        result = group.get("result", self.result)
        mapping = next((m for m in workbook.mappings if m.name == parameter), None)
        if mapping is None or not mapping.show_bias_limit:
            return
        limit = result.bias_limits[parameter]
        for value in (-limit, limit):
            line = pg.InfiniteLine(value, angle=0,
                                   pen=pg.mkPen("#dc2626", width=2, style=Qt.PenStyle.DashLine))
            line.setZValue(8)
            line.setToolTip(f"Bias limit: {value:+g} {parse_unit(mapping.reference_column)}")
            plot.addItem(line)
            plot._bias_limit_lines.append(line)

    def _trend_card_toggled(self, parameter, checked, detail_key=None):
        group = self.plot_groups.get(parameter)
        if group is not None and detail_key is not None:
            group = next((detail for detail in group["wafer_details"].values() if detail["storage_key"] == detail_key), None)
        if group is None:
            return
        self._trend_card_state[group["trend_card_key"]] = bool(checked)
        self._draw_trend_plot(parameter, group)

    def _draw_trend_plot(self, parameter, group):
        """Redraw only Trend so its Card control feels immediate and stable."""
        if "trend_data" not in group:
            return
        trend_plot = group["plots"]["trend"]
        result = group.get("result", self.result)
        workbook = group.get("workbook", self.workbook)
        # Trend plots carry the Raw Data column as their title and never a
        # Y-axis label: the block heading already names the parameter.
        trend_plot.setLabel("left", "")
        if result.group_plan.enabled:
            mode = "global" if trend_plot.card_checkbox.isChecked() else "raw"
            draw_group_trend(trend_plot, result, parameter, card_mode=mode,
                             group_only=not group.get("show_wafers", False))
            return
        for item in tuple(trend_plot.listDataItems()):
            trend_plot.removeItem(item)
        place_legend_above_frame(trend_plot)
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
            name=workbook.match_type,
        )
        place_legend_above_frame(trend_plot)
        title = result.raw_column(parameter)
        if hasattr(trend_plot, "set_scope_title"):
            trend_plot.set_scope_title(title)
        else:
            trend_plot.setTitle(title)
        trend_plot.getPlotItem().layout.setRowFixedHeight(
            0, getattr(trend_plot, "_caption_header_height", _MatchPlotWidget.HEADER_HEIGHT)
        )

    def _draw_wafer_metrics(self, parameter, group):
        group["wafer_metrics_pending"] = False
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
        # One line per wafer: the identity's newline-separated fields (wafer,
        # PAD, Lot, ...) are joined with "/" in classification order so the
        # cell shows the whole label instead of eliding after the first line.
        display = summary.copy()
        group["wafer_summary"] = summary
        selected = self._single_wafer_checks.setdefault(self.workbook.result_mode, {}).setdefault(parameter, [])
        display["Draw"] = [label in selected for label in summary.get("Wafer", [])]
        if "Wafer" in display.columns:
            display["Wafer"] = [
                str(value).replace("\n", "/") for value in display["Wafer"]
            ]
        group["wafer_model"].set_frame(display)
        group["wafer_uncheck_all"].setEnabled(bool(display["Draw"].any()))
        wafer_view = group.get("wafer_view")
        if wafer_view is not None:
            # Configure the header only once it owns sections: the per-section
            # resize mode dereferences an empty section list (index -1) and
            # crashes inside Qt while the table has no columns yet.
            header = wafer_view.horizontalHeader()
            columns = header.count()
            if columns:
                header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
                wafer_view.setColumnWidth(0, 320)
            # Only in-range sections: the wafer column keeps the free width.
            for column in range(1, columns):
                wafer_view.setColumnWidth(column, 164 if column == 1 else 104)
            if "Draw" in display:
                wafer_view.setItemDelegateForColumn(display.columns.get_loc("Draw"), group["wafer_draw_delegate"])
        # Row numbers, not wafer names: the single-wafer table alongside shows the
        # same index. Dense rows thin the labels out to every nth row number.
        group["wafer_tick_count"] = len(summary)
        group["wafer_tick_levels"] = None
        for key in ("wafer_r2", "wafer_slope"):
            group[key].clear()
        group["wafer_highlights"] = {}
        group["wafer_selected_row"] = None
        if summary.empty:
            self._draw_single_wafer_plots(parameter)
            return
        x = np.arange(len(summary), dtype=float)
        self._refresh_wafer_ticks(parameter)
        wafer_r2 = group["wafer_r2"]
        wafer_slope = group["wafer_slope"]
        r_squared = summary["R²"].to_numpy(float)
        slope = summary["Slope"].to_numpy(float)
        valid_r2 = np.isfinite(r_squared)
        valid_slope = np.isfinite(slope)
        if valid_r2.any():
            curve = wafer_r2.plot(x[valid_r2], r_squared[valid_r2], pen=None,
                                 symbol="o", symbolSize=8, symbolBrush="#4f8bd6", data=np.flatnonzero(valid_r2))
            curve.sigPointsClicked.connect(lambda _curve, points, _event: self._select_wafer(parameter, int(points[0].data()), toggle=True))
        if valid_slope.any():
            curve = wafer_slope.plot(x[valid_slope], slope[valid_slope], pen=None,
                                    symbol="o", symbolSize=8, symbolBrush="#e09f3e", data=np.flatnonzero(valid_slope))
            curve.sigPointsClicked.connect(lambda _curve, points, _event: self._select_wafer(parameter, int(points[0].data()), toggle=True))
        wafer_r2.setTitle("Single-wafer R²")
        wafer_slope.setTitle("Single-wafer slope")
        for key in ("wafer_r2", "wafer_slope"):
            highlight = pg.ScatterPlotItem(size=14, pen=pg.mkPen("#dc2626", width=2), brush=pg.mkBrush(None))
            highlight.setZValue(10)
            # pyqtgraph dispatches clicks to the ring above the data point;
            # clicking that ring is the same as clicking the selected point.
            highlight.sigClicked.connect(lambda *_: self._clear_wafer_selection(parameter))
            group[key].addItem(highlight, ignoreBounds=True)
            group["wafer_highlights"][key] = highlight
        self._draw_single_wafer_plots(parameter)

    def _wafer_selection_changed(self, parameter):
        group = self.plot_groups.get(parameter)
        if group is None:
            return
        rows = group["wafer_view"].selectionModel().selectedRows()
        if rows:
            self._select_wafer(parameter, rows[0].row(), scroll=False)
        else:
            self._clear_wafer_selection(parameter)

    def _clear_wafer_selection(self, parameter):
        group = self.plot_groups.get(parameter)
        if group is None:
            return
        group["wafer_selected_row"] = None
        view = group["wafer_view"]
        with QSignalBlocker(view.selectionModel()):
            view.clearSelection()
            view.setCurrentIndex(QModelIndex())
        for highlight in group.get("wafer_highlights", {}).values():
            highlight.setData([], [])

    def _select_wafer(self, parameter, row, *, toggle=False, scroll=True):
        group = self.plot_groups.get(parameter)
        if group is None or not 0 <= row < len(group.get("wafer_summary", [])):
            return
        if toggle and group.get("wafer_selected_row") == row:
            self._clear_wafer_selection(parameter)
            return
        group["wafer_selected_row"] = row
        view = group["wafer_view"]
        index = group["wafer_model"].index(row, 0)
        if not any(index.row() == row for index in view.selectionModel().selectedRows()):
            view.setCurrentIndex(index)
            view.selectRow(row)
        if scroll:
            # Do not reset horizontal scroll to the Wafer column, hiding Draw.
            view.verticalScrollBar().setValue(view.verticalHeader().sectionPosition(row)
                                              - view.viewport().height() // 2 + view.rowHeight(row) // 2)
        for key, column in (("wafer_r2", "R²"), ("wafer_slope", "Slope")):
            value = group["wafer_summary"].iloc[row][column]
            highlight = group.get("wafer_highlights", {}).get(key)
            if highlight is not None:
                highlight.setData([float(row)] if np.isfinite(value) else [], [value] if np.isfinite(value) else [])

    def _wafer_checked(self, parameter, row, checked):
        group = self.plot_groups[parameter]
        label = group["wafer_summary"].iloc[row]["Wafer"]
        selected = self._single_wafer_checks.setdefault(self.workbook.result_mode, {}).setdefault(parameter, [])
        if checked and label not in selected:
            selected.append(label)
        elif not checked and label in selected:
            selected.remove(label)
        group["wafer_uncheck_all"].setEnabled(bool(selected))
        self._draw_single_wafer_plots(parameter)
        self._resize_results_for_plot_groups()
        self.document.refresh_identity()

    def _uncheck_all_wafers(self, parameter):
        group = self.plot_groups[parameter]
        self._single_wafer_checks[self.workbook.result_mode][parameter] = []
        model = group["wafer_model"]
        column = model.frame.columns.get_loc("Draw")
        model.frame["Draw"] = False
        if model.rowCount():
            model.dataChanged.emit(model.index(0, column), model.index(model.rowCount() - 1, column),
                                   [Qt.ItemDataRole.CheckStateRole])
        group["wafer_uncheck_all"].setEnabled(False)
        self._draw_single_wafer_plots(parameter)
        self._resize_results_for_plot_groups()
        self.document.refresh_identity()

    def _draw_single_wafer_plots(self, parameter):
        group = self.plot_groups[parameter]
        details = group["wafer_details"]
        summary = group["wafer_summary"]
        selected = self._single_wafer_checks[self.workbook.result_mode][parameter]
        labels = list(summary.get("Wafer", []))
        for label in tuple(details):
            if label not in selected or label not in labels or pd.isna(summary.iloc[labels.index(label)]["Slope"]):
                group["wafer_detail_layout"].removeWidget(details[label]["card"])
                removed = details.pop(label)["card"]
                removed.hide()
                removed.deleteLater()
        mapping = next(m for m in self.workbook.mappings if m.name == parameter)
        signature = (mapping, self.workbook.result_mode, self._selected_bias_views())
        for label in selected:
            if label not in labels:
                continue
            row = labels.index(label)
            if pd.isna(summary.iloc[row]["Slope"]):
                continue
            reference, raw = self.result.wafer_frames(row)
            detail = details.get(label)
            if (detail is not None and detail["source_reference"].equals(reference)
                    and detail["source_raw"].equals(raw) and detail["signature"] == signature):
                continue
            if detail is not None:
                group["wafer_detail_layout"].removeWidget(detail["card"])
                detail["card"].hide()
                detail["card"].deleteLater()
            storage_key = "single-wafer:" + json.dumps([parameter, label], ensure_ascii=False)
            detail = self._create_plot_group(parameter, storage_key)
            detail["card"].findChild(_ParameterDragHandle).setText("⋮⋮  " + parameter + " · " + label.replace("\n", " / "))
            detail["workbook"] = MatchWorkbook(reference, raw, [mapping], match_type=self.workbook.match_type,
                                              result_mode=self.workbook.result_mode, bias_views=self.workbook.bias_views,
                                              bias_mode=self.workbook.bias_mode, bias_limit=self.workbook.bias_limit)
            detail["result"] = detail["workbook"].analyze()
            detail.update(source_reference=reference, source_raw=raw, signature=signature)
            details[label] = detail
            self._draw_parameter_group(parameter, detail)
            self._single_wafer_tick_labels(detail)
            detail["card"].setFixedHeight(54 + detail["plot_area"].height())
        for label in selected:
            if label in details:
                group["wafer_detail_layout"].removeWidget(details[label]["card"])
                group["wafer_detail_layout"].addWidget(details[label]["card"])
                details[label]["card"].show()

    def _single_wafer_tick_labels(self, detail):
        raw = detail["source_raw"]
        column = next((c for c in raw if str(c).casefold().replace(" ", "") == "dieseq"), None)
        labels = [str(v) for v in raw[column]] if column is not None else [str(i + 1) for i in range(len(raw))]
        for name in ("trend", "bias", "bias-percent"):
            plot = detail["plots"].get(name)
            if plot is None:
                continue
            def refresh(*_, target=plot):
                low, high = target.getViewBox().viewRange()[0]
                width = max(1., target.getViewBox().sceneBoundingRect().width())
                metrics = QFontMetrics(target.font())
                start, end = max(0, int(np.ceil(low)) - 1), min(len(labels) - 1, int(high) - 1)
                count = min(max(0, end - start + 1), max(1, int(width / 55)))
                indices = np.unique(np.linspace(start, end, count, dtype=int)) if count else []
                ticks, previous_edge = [], -float("inf")
                for i in indices:
                    x = (int(i) + 1 - low) * width / max(1e-9, high - low)
                    half = metrics.horizontalAdvance(labels[i]) / 2
                    if x - half >= max(0, previous_edge + 8) and x + half <= width:
                        ticks.append((int(i) + 1, labels[i]))
                        previous_edge = x + half
                target.getAxis("bottom").setTicks([ticks])
            plot.setLabel("bottom", "Die Seq" if column is not None else "Measurement order")
            plot.getAxis("bottom").setHeight(40)
            plot.getViewBox().sigResized.connect(refresh)
            plot.getViewBox().sigRangeChanged.connect(refresh)
            refresh()

    def _refresh_wafer_ticks(self, parameter, _view_box=None):
        """Redraw the row-number ticks of one single-wafer card, if it has data."""
        group = self.plot_groups.get(parameter)
        if group is None:
            return
        count = int(group.get("wafer_tick_count") or 0)
        if count <= 0:
            return
        levels = self._wafer_row_tick_levels(group, count)
        if levels == group.get("wafer_tick_levels"):
            return
        group["wafer_tick_levels"] = levels
        for key in ("wafer_r2", "wafer_slope"):
            group[key].getAxis("bottom").setTicks([levels])

    @staticmethod
    def _wafer_row_tick_levels(group, count):
        """Show every nth row number so neighbouring labels cannot overlap."""
        plot = group["wafer_r2"]
        metrics = QFontMetrics(plot.font())
        widest = max(
            metrics.horizontalAdvance("1"),
            metrics.horizontalAdvance(str(count)),
        )
        spacing = max(28.0, float(widest) + 12.0)
        width = float(plot.getPlotItem().getViewBox().width())
        if width < 120.0:  # Not laid out yet; refine once the card is shown.
            width = 480.0
        room = max(1, int(width // spacing))
        step = max(1, (count + room - 1) // room)
        return [(float(index), str(index + 1)) for index in range(0, count, step)]

    def _resize_results_for_plot_groups(self):
        total = 64
        wafer_total = 64
        # Older fixed-width layouts could leave this splitter wider than its
        # viewport after a re-run. Clear that constraint every time results
        # are rebuilt so four plots fit the visible workbook.
        self.setup_splitter.setMinimumWidth(0)
        for group in self.plot_groups.values():
            card_height = 54 + group["plot_area"].height()
            group["card"].setFixedHeight(card_height)
            total += card_height + self.plot_groups_layout.spacing()
            if not group["wafer_card"].isHidden():
                for detail in group["wafer_details"].values():
                    detail["card"].setFixedHeight(54 + detail["plot_area"].height())
                # Derive height from the live sections, not a cached hint for
                # the formerly expanded card while deleted docks await Qt.
                layout = group["wafer_card"].layout()
                margins = layout.contentsMargins()
                wafer_height = (margins.top() + margins.bottom()
                                + group["wafer_header"].sizeHint().height() + layout.spacing()
                                + group["wafer_metrics_layout"].sizeHint().height())
                details = group["wafer_details"]
                if details:
                    wafer_height += (layout.spacing() + sum(d["card"].height() for d in details.values())
                                     + group["wafer_detail_layout"].spacing() * (len(details) - 1))
                layout.invalidate()
                group["wafer_card"].setFixedHeight(wafer_height)
                wafer_total += wafer_height + self.wafer_groups_layout.spacing()
        result_height = max(total, wafer_total)
        self.results_panel.setMinimumHeight(max(520, result_height))
        upper_height = sum(self.setup_splitter.sizes()[:2])
        self.setup_splitter.setMinimumHeight(max(
            1120, max(650, upper_height + 2 * self.setup_splitter.handleWidth())
            + self.results_panel.minimumHeight()
        ))

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
        elif not self._analysis_current:
            self.run_analysis(apply_groups=False)
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
            if self.result.group_plan.enabled:
                plan = self.result.group_plan
                plan.order_frame.to_excel(writer, sheet_name="Order", index=False)
                pd.concat([self.result.group_summary(parameter).assign(Parameter=parameter)
                           for parameter in self.result.parameter_names], ignore_index=True).to_excel(
                               writer, sheet_name="Group Fits", index=False)
                for group in ("all", *plan.group_keys):
                    frames = []
                    for parameter in self.result.parameter_names:
                        trend = self.result.group_series(parameter, group, trend=True, card_mode="group")
                        trend = trend.rename(columns={"Trend value": "Group Card Value"})
                        trend["Parameter"] = parameter
                        trend["Mark"] = [plan.order_frame.iloc[row]["Mark"] for row in trend["Source row"]]
                        trend["Head"] = [plan.head(plan.flags[row]) for row in trend["Source row"]]
                        for column in plan.identity_columns:
                            trend[column] = [plan.raw.iloc[row][column] for row in trend["Source row"]]
                        frames.append(trend)
                    # Stable flag-based sheet names avoid user-name collisions and Excel limits.
                    sheet = "AllTrend" if group == "all" else group.replace(":", " Flag ") or "Not provided"
                    pd.concat(frames, ignore_index=True).to_excel(writer, sheet_name=sheet, index=False)
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
        elif not self._analysis_current:
            self.run_analysis(apply_groups=False)
        else:
            self.workbook = self.current_workbook()
            if set(self.plot_groups) != set(self.result.parameter_names):
                self._draw_all_parameters()
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        saved = []
        for parameter, group in self.plot_groups.items():
            if group.get("wafer_metrics_pending"):
                self._draw_wafer_metrics(parameter, group)
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
    @recovery_decision
    def save_workbook(self, path, *, capture_children=True, child=None):
        commit_editors(self)
        previous = self._accepted_workspace_state()
        children = tuple(self._stage_windows) if capture_children else (() if child is None else (child,))
        baselines = {}
        try:
            if capture_children:
                for scope, recovered in self._recovered_children.items():
                    draft = recovered["draft"]
                    follow_source = bool(recovered.get("follow_source"))
                    if follow_source:
                        kind, stage = scope.split(".")
                        if kind in ("map", "dynamic"):
                            setattr(self, f"{stage}_{kind}_frame", None)
                        for name in tuple(self._workspace_frames):
                            if name.startswith(scope + "."):
                                del self._workspace_frames[name]
                    ui = local_ui(draft.states["ui"]) if draft.workspace_type == "correlation_trend" else deepcopy(draft.states["ui"])
                    self._workspace_states[scope] = {"ui": ui,
                                                     "workspace_type": draft.workspace_type, "data_override": not follow_source}
                    for name, frame in draft.frames.items():
                        if not follow_source or draft.workspace_type == "dynamic":
                            self._workspace_frames[f"{scope}.{name}"] = frame.copy(deep=True)
            for workspace in children:
                if hasattr(workspace, "document"):
                    commit_editors(workspace)
                    baselines[workspace] = workspace.workspace_snapshot()
                try:
                    self._capture_managed_stage_workspace(workspace)
                except RuntimeError as error:
                    if not self._deleted_qt_object(error):
                        raise
                    self._forget_stage_workspace(workspace)
            target = self.document.choose_target(path)
            if target is None:
                return None
            snapshot = self.workspace_snapshot()
            candidate = self._accepted_workspace_state()
        finally:
            # Candidate construction must not accept anything before durable IO.
            self._restore_accepted_workspace_state(previous)
        expected = self.document.revision if target == self.document.path else self.document.selected_target_revision
        saved = save_workspace(target, snapshot, expected_revision=expected)
        self.document.last_warning = "; ".join(snapshot.warnings)
        self._restore_accepted_workspace_state(candidate)
        self.workbook_path = Path(saved).resolve()
        self.document.path = self.workbook_path
        self.document.revision = snapshot.revision
        self.document.untrusted_recovery = False
        if capture_children:
            self._recovered_children.clear()
        self.document.mark_clean(snapshot)
        for workspace, baseline in baselines.items():
            workspace.document.mark_clean(baseline)
            workspace._use_workbook_data = False
            scope = getattr(workspace, "_managed_scope", "")
            workspace._independent_data = bool(self._workspace_states.get(scope, {}).get("data_override"))
        # Everything below is auxiliary to an already committed file.
        try:
            self.workbook = None if snapshot.states["match"]["draft"] else MatchWorkbook.from_snapshot(snapshot)
            self.reveal_wkb_action.setEnabled(True)
            for workspace in children:
                model = getattr(workspace, "model", None)
                if model is not None and hasattr(model, "undo"):
                    model.undo.setClean()
            for workspace in self._stage_windows:
                if hasattr(workspace, "document"):
                    workspace.document.refresh_identity()
            if self.document.has_changes():
                self.document.write_recovery()
            else:
                self.document.remove_recovery()
            warning = f" · Warning: {self.document.last_warning}" if self.document.last_warning else ""
            self._set_status(f"Saved {saved.name}{warning}")
            LOGGER.info("WKB saved: %s", saved)
        except Exception as error:
            self.document.last_warning = str(error)
            LOGGER.warning("Workbook saved; auxiliary update failed: %s", error)
            self.statusBar().showMessage(f"Workbook saved; auxiliary update failed: {error}", 8000)
        return saved

    def _refresh_recent_wkb_menu(self):
        self.open_recent_menu.clear()
        if not self._recent_wkb_paths:
            empty_action = self.open_recent_menu.addAction("No Recent WKB")
            empty_action.setEnabled(False)
            return
        for index, path in enumerate(self._recent_wkb_paths, start=1):
            if Path(path).is_file():
                try:
                    if load_workspace(path).workspace_type != "match_workbook":
                        continue
                except (OSError, ValueError):
                    continue
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
        except Exception as error:
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
            workbook = self.start_workbook(path=path)
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
        if (self.workbook_path is None or self.workbook_path.suffix.lower() != ".wkb"
                or self.document.untrusted_recovery or not writable_path(self.workbook_path)):
            return self.save_wkb_dialog()
        try:
            saved = self.save_workbook(self.workbook_path)
            self._remember_recent_wkb(saved)
            return saved
        except Exception as error:
            LOGGER.exception("Cannot save WKB")
            QMessageBox.warning(self, "Cannot save WKB", str(error))

    def save_wkb_dialog(self, *, capture_children=True, child=None):
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
                saved = self.save_workbook(path, capture_children=capture_children, child=child)
                self._remember_recent_wkb(saved)
                return saved
        except Exception as error:
            LOGGER.exception("Cannot save WKB")
            QMessageBox.warning(self, "Cannot save WKB", str(error))

    @recovery_decision
    def load_workbook(self, path, *, analysis_settings=None):
        snapshot = load_workspace(path, expected_type=self.workspace_type)
        group_state(snapshot.states["match"].get("grouping_state"))
        normalize_plot_layouts(snapshot.states.get("match_ui", {}).get("plot_layouts"))
        _metric_highlighting_limits(snapshot.states.get("match_ui", {}).get("metric_highlighting"))
        if analysis_settings is not None:
            analysis_settings = normalized_analysis_settings(analysis_settings)
        if not snapshot.states.get("match", {}).get("draft"):
            MatchWorkbook.from_snapshot(snapshot)
        if not self.document.confirm_close():
            return None
        if snapshot.revision != file_revision(path):
            snapshot = load_workspace(path, expected_type=self.workspace_type)
            group_state(snapshot.states["match"].get("grouping_state"))
            normalize_plot_layouts(snapshot.states.get("match_ui", {}).get("plot_layouts"))
            _metric_highlighting_limits(snapshot.states.get("match_ui", {}).get("metric_highlighting"))
            if not snapshot.states.get("match", {}).get("draft"):
                MatchWorkbook.from_snapshot(snapshot)
        self._close_stage_workspaces(tuple(self._stage_windows))
        if "recovery" in snapshot.states:
            self.document.recover(path, snapshot)
            return self.workbook or snapshot
        self.workbook_path = Path(path).resolve()
        self._auto_run_enabled = False
        self._auto_run_pending = False
        self.result = None
        self.workbook = None
        # Use the file's original choices as the accepted basis, even when
        # launch choices differ. Only the effective choices are drawn.
        changed_settings = (analysis_settings is not None and analysis_settings !=
                            normalized_analysis_settings(snapshot.states["match"], allow_empty_bias=True))
        baseline = self.restore_workspace(snapshot, analysis_settings=analysis_settings if changed_settings else None)
        self.document.path = self.workbook_path
        self.document.revision = snapshot.revision
        self.document.untrusted_recovery = False
        self.document.mark_clean(baseline if changed_settings else None)
        self._remember_recent_wkb(path)
        return self.workbook or snapshot

    def _restore_analyzed_workbook(self, workbook, path, *, analysis_settings=None):
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
        self._correlation_selection_states = {
            stage: workbook.correlation_selections[stage]
            for stage in ("preview", "final")
        }
        self.second_axis_ratio = workbook.trend_axis_settings["ratio"]
        self._default_bias_limit = workbook.bias_limit
        self.trend_axis_mode = workbook.trend_axis_settings["mode"]
        self.second_axis_spin.blockSignals(True)
        self.second_axis_spin.setValue(self.second_axis_ratio)
        self.second_axis_spin.blockSignals(False)
        self._refresh_axis_mode_menu()
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
        self.group_controls.restore(workbook.grouping_state, workbook.test_flags)
        self._refresh_group_projection()
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
        self.absolute_bias_action.setChecked(self.absolute_bias.isChecked())
        self.percent_bias_action.setChecked(self.percent_bias.isChecked())
        self._populate_mappings(workbook.mappings)
        self._parameter_order = list(workbook.parameter_order)
        self._update_state()
        baseline = None
        if analysis_settings is not None:
            baseline = self.workspace_snapshot()
            baseline.states["match"]["draft"] = False
            self.apply_analysis_settings(analysis_settings, refresh=False)
        if analysis_settings is not None and not self.analyze_button.isEnabled():
            self._analysis_current = False
            self._clear_plot_groups()
            self.summary_model.set_frame(pd.DataFrame())
            self.result_status.setText("Workbook opened · Complete the selected stage's inputs, then Run analysis")
            if workbook.setup_splitter_sizes is not None:
                self._restore_setup_splitter_layout(workbook.setup_splitter_sizes)
            return baseline
        self.workbook = self.current_workbook()
        self.result = self.workbook.analyze()
        self._analysis_current = True
        self._auto_run_enabled = True
        self._result_descriptor = (
            f"{self.workbook.match_type} · {self.workbook.result_mode.title()} · "
            f"{len(self.result.parameter_names)} parameters"
        )
        self.result_status.setText(self._result_descriptor)
        self.summary_model.set_frame(self.result.summary)
        self._show_mapping_results()
        self._draw_all_parameters()
        self.group_plot_page.set_result(self.result)
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
        return baseline

    def open_wkb_dialog(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, "Open Matching Workbook", "",
                                                  "Matching Workbook (*.wkb)")
            if path:
                self.start_workbook(path=path)
        except Exception as error:
            LOGGER.exception("Cannot open WKB")
            QMessageBox.warning(self, "Cannot open WKB", str(error))

    def start_workbook(self, *, path=None, new=False):
        """Open a workbook as saved; only a new workbook asks for its settings."""
        if path is not None:
            return self.load_workbook(path)
        from .workbook_startup import WorkbookStartupDialog
        dialog = WorkbookStartupDialog(self, new=new)
        try:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return None
            if dialog.path is not None:
                return self.load_workbook(dialog.path)
            settings = dialog.settings()
            if not self.document.confirm_close():
                return None
            self._auto_run_enabled = False
            self._auto_run_pending = False
            self.workbook_path = None
            self.document.path = None
            self.document.revision = None
            self.document.untrusted_recovery = False
            self.reveal_wkb_action.setEnabled(False)
            snapshot = WorkspaceSnapshot("match_workbook", {
                "reference": pd.DataFrame(), "raw": pd.DataFrame(),
            }, {"match": {**settings, "draft": True}, "match_ui": {}})
            self.restore_workspace(snapshot)
            self.document.mark_clean()
            return snapshot
        finally:
            dialog.deleteLater()


def _safe_filename(value):
    safe = "".join(character if character.isalnum() or character in "-_" else "-"
                   for character in str(value).strip())
    return safe.strip("-") or "parameter"



__all__ = ["DataFrameModel", "MatchingWindow", "clipboard_frame"]
