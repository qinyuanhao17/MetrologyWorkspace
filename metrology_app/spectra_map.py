"""Paginated point maps for spectrum measurements."""
from __future__ import annotations

from collections import defaultdict
import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QEvent, QTimer, Qt, pyqtSignal
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPalette, QPainter, QPainterPath, QTransform
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .appearance import fit_window_to_screen, style_titlebar
from .settings import apply_theme as apply_window_theme, get_settings, theme_stylesheet
from .sme_spectra import SpectrumFile, natural_key

TILE_WIDTH, TILE_HEIGHT = 420, 496
GRID_MARGIN, GRID_SPACING = 12, 12


class _PointSelectionViewBox(pg.ViewBox):
    rectangleSelected = pyqtSignal(object, object)

    def mouseDragEvent(self, event, axis=None):
        if event.button() != Qt.MouseButton.LeftButton or axis is not None:
            return super().mouseDragEvent(event, axis=axis)
        event.accept()
        if event.isFinish():
            self.rbScaleBox.hide()
            rect = self.childGroup.mapRectFromParent(QRectF(event.buttonDownPos(), event.pos())).normalized()
            self.rectangleSelected.emit(rect, event.modifiers())
        else:
            self.updateScaleBox(event.buttonDownPos(), event.pos())


class _DieLabel(pg.TextItem):
    """Keep the number just below its marker at a fixed screen-space distance."""

    def updateTextPos(self):
        super().updateTextPos()
        self.textItem.moveBy(0, 5)


class WaferPointPlot(QWidget):
    pointSelected = pyqtSignal(object, object)
    checkRequested = pyqtSignal(object, bool)
    selectionMenuRequested = pyqtSignal(object)

    def __init__(self, wafer: str, parent=None):
        super().__init__(parent)
        self.wafer = wafer
        self.setObjectName("dieMapCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(0, 0)
        self.setFixedSize(TILE_WIDTH, TILE_HEIGHT)
        self.setStyleSheet("QWidget#dieMapCard { background: #ffffff; border: 1px solid #d9d9de; border-radius: 10px; }")
        self.setAutoFillBackground(True)
        background = self.palette()
        background.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        self.setPalette(background)
        self._foreground = QColor("#d8d3df")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        # A long graphics-scene title imposes a minimum scene width and clips
        # the right half of small maps. Keep the complete title in the tile.
        self.title_label = QLabel(wafer)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setStyleSheet("color: #2b2730; background: transparent; font-size: 16px; font-weight: 600;")
        self.title_label.setToolTip(wafer)
        self.title_label.setFixedHeight(48)
        layout.addWidget(self.title_label)
        view = _PointSelectionViewBox()
        view.rectangleSelected.connect(self._rectangle_selected)
        self.plot = pg.PlotWidget(viewBox=view)
        self.plot.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.plot.setFixedSize(400, 400)
        self.plot.setToolTip("Left-drag to select points. Ctrl/Shift-drag adds points; click blank space to clear selection.")
        self.plot.scene().sigMouseClicked.connect(self._scene_clicked)
        self.plot.getPlotItem().hideButtons()
        self.plot.setMenuEnabled(False)
        self.plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(
            lambda position: self.selectionMenuRequested.emit(self.plot.mapToGlobal(position))
        )
        self.plot.setAspectLocked(True)
        self.plot.showGrid(x=True, y=True, alpha=0.14)
        self.plot.showAxis("top")
        self.plot.showAxis("right")
        self.plot.getAxis("top").setStyle(showValues=False)
        self.plot.getAxis("right").setStyle(showValues=False)
        self.plot.getAxis("left").setWidth(60)
        self.plot.getAxis("right").setWidth(8)
        self.plot.setLabel("bottom", "X (mm)")
        self.plot.setLabel("left", "Y (mm)")
        self.plot.setMouseEnabled(x=False, y=False)
        self.outline = pg.PlotDataItem(pen=pg.mkPen(self._foreground, width=1.5), antialias=True)
        self.plot.addItem(self.outline)
        layout.addWidget(
            self.plot,
            0,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        )
        self.summary_label = QLabel()
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_label.setStyleSheet("color: #6b6b70; background: transparent; font-size: 11px;")
        self.summary_label.setFixedHeight(18)
        layout.addWidget(self.summary_label)
        layout.addStretch(1)
        self.scatter = pg.ScatterPlotItem(
            antialias=True,
            size=12,
            symbol="o",
            pen=pg.mkPen("#202020", width=0.8),
            brush=pg.mkBrush("#3E8BD8"),
            hoverable=True,
            tip=self._point_tip,
        )
        self.scatter.sigClicked.connect(self._point_clicked)
        self.plot.addItem(self.scatter)
        self.selection = pg.ScatterPlotItem(
            antialias=True,
            size=20,
            symbol="o",
            pen=pg.mkPen("#E69F00", width=2.4),
            brush=pg.mkBrush(None),
        )
        self.selection.setEnabled(False)
        self.plot.addItem(self.selection)
        flag = QPainterPath()
        flag.moveTo(5, -3)
        flag.lineTo(5, -12)
        flag.moveTo(5, -12)
        flag.lineTo(12, -9.5)
        flag.lineTo(5, -7)
        flag.closeSubpath()
        # The cache tile must contain the offset glyph (and a second mixed
        # flag). The painted flag itself is only 7 × 9 screen pixels.
        self._flag_symbol = QTransform.fromScale(1 / 48, 1 / 48).map(flag)
        self._flag_symbols = {0: self._flag_symbol}
        self.flag_markers = pg.ScatterPlotItem(size=48, symbol=self._flag_symbol, pxMode=True, antialias=True)
        self.flag_markers.setEnabled(False)
        self.flag_markers.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.plot.addItem(self.flag_markers, ignoreBounds=True)
        self._test_flags = {}
        self.labels: list[pg.TextItem] = []
        self._label_records: list[tuple[pg.TextItem, float, float, tuple[str, ...], str]] = []
        self.wafer_diameter = 300
        self._selected_keys: set[str] = set()
        self._spot_keys: list[tuple[str, ...]] = []
        self._checked_keys = set()
        self._plot_positions: list[tuple[float, float]] = []

    def apply_theme(self, palette):
        self._foreground = QColor("#2b2730")
        self.plot.setBackground("#ffffff")
        for axis_name in ("left", "bottom", "top", "right"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(self._foreground)
            axis.setTextPen(self._foreground)
        self.plot.setTitle(None)
        self.outline.setPen(pg.mkPen(self._foreground, width=1.5))

    def set_data(self, spectra, selected_keys, *, scale_spectra=None, checked_keys=None):
        spectra = tuple(spectra)
        for label in self.labels:
            if label.scene() is not None:
                label.scene().removeItem(label)
        self.labels = []
        self._label_records = []
        self._spot_keys = []
        self._plot_positions = []
        clusters: dict[tuple[float, float], list[SpectrumFile]] = defaultdict(list)
        for spectrum in spectra:
            if spectrum.has_map_point:
                clusters[(round(spectrum.x_mm, 6), round(spectrum.y_mm, 6))].append(
                    spectrum
                )
        coordinates = sorted(clusters)
        self._plot_positions = coordinates
        spots = []
        selected = set(selected_keys)
        for x, y in coordinates:
            members = sorted(
                clusters[(x, y)],
                key=lambda spectrum: spectrum.sort_key,
            )
            keys = tuple(spectrum.key for spectrum in members)
            self._spot_keys.append(keys)
            dies = [
                str(spectrum.identity.die_seq)
                for spectrum in members
                if spectrum.identity.die_seq is not None
            ]
            label = f"Die {', '.join(dies)}" if dies else "Die ?"
            if len(members) > 1:
                label += f" ({len(members)})"
            spots.append({
                "pos": (x, y),
                "data": {"keys": keys, "label": label},
                "brush": pg.mkBrush("#3E8BD8"),
            })
            text = _DieLabel(
                text=", ".join(dict.fromkeys(dies)) if dies else "?",
                color=self._foreground,
                anchor=(0.5, 0.0),
            )
            text.textItem.document().setDocumentMargin(0)
            text.updateTextPos()
            text.setPos(x, y)
            self.plot.addItem(text)
            self.labels.append(text)
            self._label_records.append((text, x, y, keys, label))
        self.scatter.setData(spots)
        self.set_checked({s.key for s in spectra} if checked_keys is None else checked_keys)
        self._update_selection(selected)

        radius = max(
            (
                math.hypot(spectrum.x_mm, spectrum.y_mm)
                for spectrum in (scale_spectra or spectra)
                if spectrum.has_map_point
            ),
            default=0.0,
        )
        diameter = next(
            (
                candidate
                for candidate in (100, 200, 300)
                if radius <= candidate * 0.51
            ),
            300,
        )
        self.wafer_diameter = diameter
        half = diameter / 2
        angle = np.linspace(0, 2 * math.pi, 361)
        self.outline.setData(half * np.cos(angle), half * np.sin(angle))
        self.plot.setRange(
            xRange=(-half, half),
            yRange=(-half, half),
            padding=0.03,
        )
        self._avoid_label_collisions(selected)

    def set_selected(self, selected_keys):
        if set(selected_keys) == self._selected_keys:
            return
        self._update_selection(set(selected_keys))

    def set_checked(self, checked_keys):
        self._checked_keys = set(checked_keys)
        for point, keys in zip(self.scatter.points(), self._spot_keys):
            count = sum(key in self._checked_keys for key in keys)
            state = "Checked" if count == len(keys) else ("Mixed" if count else "Unchecked")
            data = point.data()
            if data.get("state") == state:
                continue
            data = {**data, "state": state}
            point.setData(data)
            point.setBrush(pg.mkBrush("#3E8BD8" if count else "#D6D9DE"))
            point.setPen(pg.mkPen("#202020" if count else "#A8ADB5", width=.8))
        self._update_summary()

    def _update_summary(self):
        states = [point.data().get("state") for point in self.scatter.points()]
        selected = sum(bool(self._selected_keys.intersection(keys)) for keys in self._spot_keys)
        mixed = states.count("Mixed")
        text = f"{len(states)} points · {states.count('Checked')} checked"
        if mixed:
            text += f" · {mixed} mixed"
        self.summary_label.setText(f"{text} · {selected} selected")

    def set_test_flags(self, flags):
        current = {key: flags.get(key, 0) for keys in self._spot_keys for key in keys}
        if current == self._test_flags:
            return
        self._test_flags = current
        points = []
        for position, keys in zip(self._plot_positions, self._spot_keys):
            # Multiple files at one physical point retain all nonzero flags;
            # a mixed point shows both small flags rather than hiding a conflict.
            values = {current[key] for key in keys} - {0}
            for offset, value in enumerate(sorted(values)):
                color = "#15803d" if value == 1 else "#dc2626" if value == -1 else "#6b7280"
                if offset not in self._flag_symbols:
                    self._flag_symbols[offset] = self._flag_symbol.translated(offset * 8 / 48, 0)
                points.append({"pos": position, "brush": pg.mkBrush(color),
                               "pen": pg.mkPen(color, width=1), "data": value,
                               "symbol": self._flag_symbols[offset]})
        self.flag_markers.setData(points)
        for point, keys in zip(self.scatter.points(), self._spot_keys):
            point.setData({**point.data(), "test_flags": sorted({current[key] for key in keys})})

    def _update_selection(self, selected_keys):
        self._selected_keys = set(selected_keys)
        points = [
            {"pos": position}
            for position, keys in zip(self._plot_positions, self._spot_keys)
            if self._selected_keys.intersection(keys)
        ]
        self.selection.setData(points)
        self._avoid_label_collisions(self._selected_keys)
        self._update_summary()

    @staticmethod
    def _point_tip(x, y, data):
        details = data if isinstance(data, dict) else {}
        keys = tuple(details.get("keys", ()))
        label = details.get("label", "Die ?")
        return (f"{label}\nX: {x:g} mm\nY: {y:g} mm\nSpectra: {len(keys)}\n{details.get('state', '')}"
                + f"\nTest Flag: {', '.join(str(value) for value in details.get('test_flags', [0]))}")

    def _scene_clicked(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and not event.double()
                and not event.isAccepted()):
            self.pointSelected.emit(set(), Qt.KeyboardModifier.NoModifier)

    def _point_clicked(self, _item, points, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        keys = {
            key
            for point in points
            for key in tuple(
                (point.data() or {}).get("keys", ())
                if isinstance(point.data(), dict)
                else ()
            )
        }
        if keys:
            self.pointSelected.emit(keys, event.modifiers())
            if event.double():
                self.checkRequested.emit(keys, not keys.issubset(self._checked_keys))

    def _rectangle_selected(self, rect, modifiers):
        keys = {key for (x, y), members in zip(self._plot_positions, self._spot_keys)
                if rect.left() <= x <= rect.right() and rect.top() <= y <= rect.bottom()
                for key in members}
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            modifiers = Qt.KeyboardModifier.ShiftModifier
        self.pointSelected.emit(keys, modifiers)

    def _avoid_label_collisions(self, selected_keys):
        records = sorted(
            self._label_records,
            key=lambda record: not bool(set(record[3]).intersection(selected_keys)),
        )
        placed: list[QRectF] = []
        for label, x, y, keys, text in records:
            selected = bool(set(keys).intersection(selected_keys))
            rect = label.sceneBoundingRect().adjusted(-2, -2, 2, 2)
            overlap = any(rect.intersects(other) for other in placed)
            label.setVisible(selected or not overlap)
            if selected or not overlap:
                placed.append(rect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._avoid_label_collisions(self._selected_keys)


class SpectraMapWindow(QMainWindow):
    spectra_selected = pyqtSignal(object)
    check_selected_requested = pyqtSignal()
    uncheck_selected_requested = pyqtSignal()
    test_flags_changed = pyqtSignal(object)
    checks_changed = pyqtSignal(object)

    def __init__(self, parent=None, *, pin_owner=None):
        owner_flags = parent.windowFlags() if parent is not None else Qt.WindowType.Window
        super().__init__(parent, owner_flags | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle("Spectrum Die Map")
        fit_window_to_screen(self, (1360, 900), minimum=(900, 620))
        self._spectra: tuple[SpectrumFile, ...] = ()
        self._checked_keys: set[str] = set()
        self._test_flags = {}
        self._flag_values = [0, 1, -1]
        self._selected_keys: set[str] = set()
        self._source_signature = None
        self._context_wafer = None
        self._wafers: list[tuple[str, str, str]] = []
        self.page_index = 0
        self.page_size = 12
        self.wafer_plots: dict[tuple[str, str, str], WaferPointPlot] = {}
        self._pending_page_wafers: list[tuple[str, str, str]] = []
        self._page_build_timer = QTimer(self, singleShot=True, interval=0)
        self._page_build_timer.timeout.connect(self._build_next_page_batch)
        self._columns = 3
        apply_window_theme(self)
        self._build_ui()
        self.apply_theme(self.palette())
        from .floating_editor import WindowPin
        self.window_pin = WindowPin(self, pin_owner or parent)

    def nativeEvent(self, event_type, message):
        result = self.window_pin.native_event(event_type, message) if hasattr(self, "window_pin") else None
        return result if result is not None else (False, 0)

    def _build_ui(self):
        root = QWidget()
        root.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        root.customContextMenuRequested.connect(
            lambda position: self._selection_menu_requested(root.mapToGlobal(position))
        )
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Die Map", objectName="panelTitle"))
        self.summary_label = QLabel("0 wafers · 0 points", objectName="muted")
        controls.addWidget(self.summary_label)
        controls.addStretch(1)
        controls.addWidget(QLabel("Wafers / page", objectName="muted"))
        self.page_size_spin = QSpinBox()
        self.page_size_spin.setRange(1, 12)
        self.page_size_spin.setValue(12)
        self.page_size_spin.setFixedSize(76, 32)
        self.page_size_spin.setKeyboardTracking(False)
        self.page_size_spin.setAccessibleName("Wafers per page")
        self.page_size_spin.valueChanged.connect(self._change_page_size)
        controls.addWidget(self.page_size_spin)
        self.previous = QPushButton(objectName="subtle")
        self.previous.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
        self.previous.setToolTip("Previous page")
        self.previous.setFixedSize(32, 32)
        self.previous.setAccessibleName("Previous page")
        self.previous.clicked.connect(lambda: self.change_page(-1))
        controls.addWidget(self.previous)
        self.page_label = QLabel("Page 1 / 1", objectName="hint")
        controls.addWidget(self.page_label)
        self.next = QPushButton(objectName="subtle")
        self.next.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.next.setToolTip("Next page")
        self.next.setFixedSize(32, 32)
        self.next.setAccessibleName("Next page")
        self.next.clicked.connect(lambda: self.change_page(1))
        controls.addWidget(self.next)
        layout.addLayout(controls)
        frame = QFrame(objectName="dieMapGrid")
        frame.setStyleSheet("QFrame#dieMapGrid { background: transparent; border: none; }")
        self.grid = QGridLayout(frame)
        self.grid.setContentsMargins(GRID_MARGIN, GRID_MARGIN, GRID_MARGIN, GRID_MARGIN)
        self.grid.setSpacing(GRID_SPACING)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setWidget(frame)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.scroll_area.viewport().installEventFilter(self)
        frame.installEventFilter(self)
        layout.addWidget(self.scroll_area, 1)
        self.empty = QLabel("Load spectrum measurements to display Die Maps.", objectName="subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)
        self.setCentralWidget(root)

    def apply_theme(self, palette):
        for plot in self.wafer_plots.values():
            plot.apply_theme(palette)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "grid"):
            style = theme_stylesheet()
            if self.styleSheet() != style:
                self.setStyleSheet(style)
            style_titlebar(self, get_settings()["theme"])
            self.apply_theme(self.palette())

    def showEvent(self, event):
        super().showEvent(event)
        style_titlebar(self, get_settings()["theme"])

    def _reflow_grid(self):
        count = min(self.page_size, max(0, len(self._wafers) - self.page_index * self.page_size))
        columns = min(3, max(1, count))
        rows = max(1, math.ceil(count / columns))
        # QGridLayout retains old row/column indices after a page is cleared.
        for column in range(max(self.grid.columnCount(), columns)):
            self.grid.setColumnStretch(column, 0)
            self.grid.setColumnMinimumWidth(column, TILE_WIDTH if column < columns else 0)
        for row in range(max(self.grid.rowCount(), rows)):
            self.grid.setRowStretch(row, 0)
            self.grid.setRowMinimumHeight(row, TILE_HEIGHT if row < rows else 0)
        self.grid.parentWidget().setFixedSize(
            2 * GRID_MARGIN + columns * TILE_WIDTH + (columns - 1) * GRID_SPACING,
            2 * GRID_MARGIN + rows * TILE_HEIGHT + (rows - 1) * GRID_SPACING,
        )
        if columns != self._columns:
            self._columns = columns
            for index, plot in enumerate(self.wafer_plots.values()):
                self.grid.removeWidget(plot)
                self.grid.addWidget(plot, index // columns, index % columns)

    @property
    def wafer_count(self) -> int:
        return len(self._wafers)

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(len(self._wafers) / self.page_size))

    @property
    def point_count(self) -> int:
        points = set()
        for spectrum in self._spectra:
            if (
                spectrum.has_map_point
            ):
                points.add((
                    (spectrum.identity.wafer, spectrum.identity.lot, spectrum.identity.pad),
                    round(spectrum.x_mm, 6),
                    round(spectrum.y_mm, 6),
                ))
        return len(points)

    def set_data(self, spectra, *, checked_keys, selected_keys=()):
        spectra = tuple(spectra)
        signature = tuple((s.key, id(s)) for s in spectra)
        if signature == self._source_signature:
            self.update_checks(checked_keys, selected_keys=selected_keys)
            return
        self._source_signature = signature
        self._spectra = spectra
        self._checked_keys = set(checked_keys)
        self._selected_keys = set(selected_keys)
        self._wafers = sorted(
            {
                (spectrum.identity.wafer, spectrum.identity.lot, spectrum.identity.pad)
                for spectrum in self._spectra
                if spectrum.has_map_point
            },
            key=lambda identity: tuple(natural_key(part) for part in identity),
        )
        self.page_index = min(self.page_index, self.page_count - 1)
        self._rebuild_page()

    def update_checks(self, checked_keys, *, selected_keys=None):
        checked = set(checked_keys)
        changed = checked ^ self._checked_keys
        self._checked_keys = checked
        for plot in self.wafer_plots.values():
            if any(changed.intersection(keys) for keys in plot._spot_keys):
                plot.set_checked(checked)
        if selected_keys is not None:
            self.select_spectrum_keys(selected_keys)

    def _point_check_requested(self, keys, checked):
        self.checks_changed.emit({key: checked for key in keys})

    def update_test_flags(self, flags, *, flag_values=None):
        if flag_values is not None:
            self._flag_values = list(flag_values)
        if self._test_flags == flags:
            return
        self._test_flags = dict(flags)
        for plot in self.wafer_plots.values():
            plot.set_test_flags(flags)

    def select_spectrum_keys(self, keys):
        self._selected_keys = {str(key) for key in keys}
        for plot in self.wafer_plots.values():
            plot.set_selected(self._selected_keys)

    def _points_selected(self, keys, modifiers):
        keys = set(keys)
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            keys = self._selected_keys ^ keys
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            keys |= self._selected_keys
        self.select_spectrum_keys(keys)
        self.spectra_selected.emit(keys)

    def mousePressEvent(self, event):
        child = self.childAt(event.position().toPoint())
        while child is not None and child is not self:
            if isinstance(child, QAbstractScrollArea):
                return super().mousePressEvent(event)
            child = child.parentWidget()
        if event.button() == Qt.MouseButton.LeftButton:
            self._points_selected(set(), Qt.KeyboardModifier.NoModifier)
        super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and watched.childAt(event.position().toPoint()) is None):
            self._points_selected(set(), Qt.KeyboardModifier.NoModifier)
        return super().eventFilter(watched, event)

    def build_selection_menu(self, wafer=None):
        menu = QMenu(self)
        menu.addAction("Check Selected", self.check_selected_requested.emit).setEnabled(bool(self._selected_keys))
        menu.addAction("Uncheck Selected", self.uncheck_selected_requested.emit).setEnabled(bool(self._selected_keys))
        flags = menu.addMenu("Set Test Flag")
        flags.setEnabled(bool(self._selected_keys))
        for value in self._flag_values:
            flags.addAction("0 (Fallback)" if value == 0 else str(value),
                            lambda _checked=False, value=value:
                            self.test_flags_changed.emit({key: value for key in self._selected_keys}))
        identity = wafer if wafer is not None else self._context_wafer
        for label, checked in (("Check Unselected", True), ("Uncheck Unselected", False)):
            if not checked:
                menu.addSeparator()
            action = menu.addAction(label, lambda _=False, value=checked, source=identity:
                                    self.set_unselected_checked(source, value))
            action.setEnabled(bool(self._unselected_keys(identity)))
            action.setToolTip("Applies only to unselected points in the wafer you right-clicked.")
        menu.addSeparator()
        menu.addAction("Apply Check To Similar Wafer", lambda: self.apply_to_similar_wafer(identity)).setEnabled(identity is not None)
        menu.addAction("Apply Flag to Similar Wafer", lambda: self.apply_flags_to_similar_wafer(identity)).setEnabled(identity is not None)
        return menu

    def _unselected_keys(self, wafer):
        return {s.key for s in self._spectra if s.has_map_point
                and (s.identity.wafer, s.identity.lot, s.identity.pad) == wafer
                and s.key not in self._selected_keys}

    def set_unselected_checked(self, wafer, checked):
        keys = self._unselected_keys(wafer)
        if keys:
            self.checks_changed.emit({key: bool(checked) for key in keys})

    def apply_to_similar_wafer(self, wafer):
        from .die_selection import similar_wafer_selection
        try:
            updates, matched, skipped = similar_wafer_selection(self._spectra, wafer, self._checked_keys)
        except ValueError as error:
            self.statusBar().showMessage(str(error))
            return
        if updates:
            self.checks_changed.emit(updates)
        self.statusBar().showMessage(f"Applied to {len(matched)} similar wafers; skipped {len(skipped)}. X/Y tolerance: < 0.4 mm.")
        self.statusBar().setToolTip("\n".join(f"{' / '.join(identity)}: {reason}" for identity, reason in skipped))

    def apply_flags_to_similar_wafer(self, wafer):
        from .die_selection import similar_wafer_flags
        try:
            updates, matched, skipped = similar_wafer_flags(self._spectra, wafer, self._test_flags)
        except ValueError as error:
            self.statusBar().showMessage(str(error))
            return
        if updates:
            self.test_flags_changed.emit(updates)
        self.statusBar().showMessage(f"Applied flags to {len(matched)} similar wafers; skipped {len(skipped)}. X/Y tolerance: < 0.4 mm.")
        self.statusBar().setToolTip("\n".join(f"{' / '.join(identity)}: {reason}" for identity, reason in skipped))

    def _selection_menu_requested(self, position, wafer=None):
        self._context_wafer = wafer
        self.build_selection_menu().exec(position)

    def _change_page_size(self, value):
        self.page_size = int(value)
        self.page_index = 0
        self._rebuild_page()

    def change_page(self, delta):
        target = min(max(0, self.page_index + int(delta)), self.page_count - 1)
        if target != self.page_index:
            self.page_index = target
            self._rebuild_page()

    def _clear_grid(self):
        self._page_build_timer.stop()
        self._pending_page_wafers = []
        for plot in self.wafer_plots.values():
            self.grid.removeWidget(plot)
            plot.setParent(None)
            plot.deleteLater()
        self.wafer_plots = {}

    def _rebuild_page(self):
        self._clear_grid()
        start = self.page_index * self.page_size
        page_wafers = self._wafers[start:start + self.page_size]
        self._pending_page_wafers = list(page_wafers)
        self._reflow_grid()
        self.page_label.setText(
            f"Page {self.page_index + 1} / {self.page_count}"
        )
        self.summary_label.setText(f"{self.wafer_count} {'wafer' if self.wafer_count == 1 else 'wafers'} · {self.point_count} points")
        self.previous.setEnabled(self.page_index > 0)
        self.next.setEnabled(self.page_index < self.page_count - 1)
        has_page = bool(page_wafers)
        self.empty.setVisible(not has_page)
        self.grid.parentWidget().setVisible(has_page)
        self.scroll_area.setVisible(has_page)
        if has_page:
            self._page_build_timer.start()

    def _build_next_page_batch(self):
        for _ in range(1):
            if not self._pending_page_wafers:
                return
            wafer = self._pending_page_wafers.pop(0)
            spectra = tuple(
                spectrum
                for spectrum in self._spectra
                if (spectrum.identity.wafer, spectrum.identity.lot, spectrum.identity.pad) == wafer
            )
            title = " · ".join(part for part in wafer if part)
            plot = WaferPointPlot(title)
            plot.apply_theme(self.palette())
            plot.pointSelected.connect(self._points_selected)
            plot.checkRequested.connect(self._point_check_requested)
            plot.selectionMenuRequested.connect(lambda position, identity=wafer: self._selection_menu_requested(position, identity))
            plot.set_data(
                spectra,
                self._selected_keys,
                scale_spectra=spectra,
                checked_keys=self._checked_keys,
            )
            plot.set_test_flags(self._test_flags)
            index = len(self.wafer_plots)
            row, column = divmod(index, self._columns)
            self.grid.addWidget(plot, row, column)
            self.wafer_plots[wafer] = plot
        if self._pending_page_wafers:
            self._page_build_timer.start()

