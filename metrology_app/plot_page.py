"""Wafer controls, background interpolation and a static pyqtgraph scene.

Matplotlib figures are materialised only when an export is requested.
"""
from io import BytesIO
from dataclasses import replace
from pathlib import Path
from weakref import WeakSet

import numpy as np
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6 import sip
from PyQt6.QtCore import QEvent, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QPainter, QShortcut
from matplotlib import colormaps

from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGraphicsView, QHBoxLayout, QLabel, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .array_plot import ArrayOptions, draw_array, drawn_axes, prepare_array
from .appearance import (COLOR_MAP_OPTIONS, MAX_COPY_PIXELS, MAX_EXPORT_PIXELS,
                         configure_resolution_combo, export_dpi, resolution_settings,
                         screen_render_scale)
from .color_range_bar import ColorRangeBar
from .map_selector import MapSelector
from .plot import auto_cmap_range
from .settings import get_settings, save_settings
from .plotting.identity_labels import measurement_caption
from .wafer_graphics import PAGE_ZOOM_PERCENTAGES, StaticMapView, WaferMapGrid

_PLOT_PAGES = WeakSet()
_CANCELLED_JOBS = set()


def _finish_cancelled_jobs():
    # A single numerical-library call cannot be forcibly interrupted safely.
    # Only application shutdown joins these data-only jobs, never child close.
    for job in tuple(_CANCELLED_JOBS):
        job.wait()


def _release_cancelled_job(job):
    if job not in _CANCELLED_JOBS:
        return
    _CANCELLED_JOBS.discard(job)
    job.deleteLater()

rcParams["font.family"] = ["Segoe UI", "Microsoft YaHei", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


class SurfaceJob(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, frame, selection, options, parent):
        super().__init__(parent)
        self.inputs = frame.copy(), selection.copy(), options

    def run(self):
        try:
            result = prepare_array(*self.inputs, progress=self.progress.emit, cancelled=self.isInterruptionRequested)
            if result is not None and not self.isInterruptionRequested():
                self.ready.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


class PlotPage(QWidget):
    draw_state_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__(objectName="plotPage")
        prefs = get_settings()
        self.frame = None
        self.selection = {}
        self.identity_labels = {"pad": True, "lot": True}
        self.signature = None
        self.dirty = True
        self.revision = 0
        self._pending_render = None
        self._style_source = None
        self._presentation_fields = set()
        self._render_serial = 0
        self._settle_timer = QTimer(self, interval=0, singleShot=True)
        self._settle_timer.timeout.connect(self.settle_canvas)
        self._restore_scroll_timer = QTimer(self, interval=0, singleShot=True)
        self._restore_scroll_timer.timeout.connect(self._restore_scroll)
        self._page_refresh_timer = QTimer(self, interval=0, singleShot=True)
        self._page_refresh_timer.timeout.connect(self.draw_maps)
        self._saved_scroll = None
        self._center_timer = QTimer(self, singleShot=True)
        self._center_timer.timeout.connect(self.center_canvas)
        self._fit_width_timer = QTimer(self, singleShot=True)
        self._fit_width_timer.timeout.connect(self._resize_fit_width)
        self.worker = None
        self.pending_fill_refresh = False
        self.pending_input_refresh = False
        self.page_intent = "canvas"
        self.has_drawn_once = False
        self.drawn_cells = set()
        self.pending_cells = set()
        self.result = None
        self.artists = []
        self.font_timer = QTimer(self, interval=120, singleShot=True)
        self.font_timer.timeout.connect(self.apply_font_style)
        self.style_timer = QTimer(self, interval=120, singleShot=True)
        self.style_timer.timeout.connect(self.apply_plot_style)
        self.overlay_timer = QTimer(self, interval=120, singleShot=True)
        self.overlay_timer.timeout.connect(self.apply_overlay_visibility)
        self.settings_timer = QTimer(self, interval=350, singleShot=True)
        self.settings_timer.timeout.connect(self.persist_color_preferences)
        self.input_refresh_timer = QTimer(self, interval=120, singleShot=True)
        self.input_refresh_timer.timeout.connect(self.refresh_previous_selection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)
        header = QVBoxLayout()
        header.setSpacing(8)
        toolbar = QHBoxLayout()
        self.select_button = QPushButton("Select maps")
        self.select_button.setToolTip(
            "Drag to select maps · Ctrl to add / remove · Shift to extend"
        )
        self.select_button.clicked.connect(self.show_selector)
        toolbar.addWidget(self.select_button)
        self.draw_button = QPushButton("Draw selected", objectName="primary")
        self.draw_button.clicked.connect(self.draw_maps)
        self.export_button = QPushButton("Export…")
        self.export_button.setToolTip("Export a PNG at the selected resolution, or save an SVG or PDF.\n"
                                      "Axes, text, contours, and points remain vector graphics; the "
                                      "interpolated color field is embedded as an image.")
        self.export_button.clicked.connect(self.export_image)
        self.export_button.setEnabled(False)
        self.copy_button = QPushButton("Copy PNG")
        self.copy_button.clicked.connect(self.copy_png)
        self.copy_button.setEnabled(False)
        toolbar.addWidget(self.draw_button)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.copy_button)
        toolbar.addStretch()
        self.summary = QLabel("0 × 0", objectName="accent")
        toolbar.addWidget(self.summary)
        header.addLayout(toolbar)
        appearance = QHBoxLayout()
        self.zoom = QComboBox()
        self.zoom.addItems(["Fit width", *(f"{value}%" for value in PAGE_ZOOM_PERCENTAGES)])
        self.zoom.currentTextChanged.connect(self.resize_canvas)
        self.zoom.setToolTip("Ctrl+wheel scales the entire grid, not the coordinates inside an individual map.")
        toolbar.insertWidget(toolbar.indexOf(self.copy_button) + 1, QLabel("View", objectName="muted"))
        toolbar.insertWidget(toolbar.indexOf(self.copy_button) + 2, self.zoom)
        appearance.addWidget(QLabel("Font", objectName="muted"))
        self.font_size = QComboBox()
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16"])
        self.font_size.setCurrentText(str(prefs.get("font_size", 10)))
        self.font_size.setFixedWidth(58)
        self.font_size.setToolTip("Base plot font size; tick labels stay two points smaller.")
        self.font_size.currentTextChanged.connect(self.redraw_style)
        appearance.addWidget(self.font_size)
        appearance.addWidget(QLabel("Resolution", objectName="muted"))
        self.resolution = QComboBox()
        configure_resolution_combo(self.resolution)
        self.resolution.setCurrentIndex(max(0, self.resolution.findText(prefs.get("resolution", "High"))))
        self.resolution.currentIndexChanged.connect(self.change_resolution)
        appearance.addWidget(self.resolution)
        appearance.addWidget(QLabel("Color", objectName="muted"))
        self.color_map = QComboBox()
        for title, name in COLOR_MAP_OPTIONS:
            self.color_map.addItem(title, name)
        self.color_map.setCurrentIndex(max(0, self.color_map.findData(prefs.get("color_map", "turbo"))))
        self.color_map.setFixedWidth(142)
        self.color_map.currentIndexChanged.connect(self.change_colormap)
        self.color_map.activated.connect(lambda *_: self.settings_timer.start())
        appearance.addWidget(self.color_map)
        appearance.addWidget(QLabel("Colors", objectName="muted"))
        self.color_range = ColorRangeBar()
        self.color_range.set_colormap(colormaps[self.color_map.currentData()])
        saved_range = (float(prefs.get("color_range_low", 0.0)),
                       float(prefs.get("color_range_high", 1.0)))
        if saved_range[1] - saved_range[0] < self.color_range.GAP:
            saved_range = auto_cmap_range(self.color_map.currentData())
        self.color_range.set_range(*saved_range)
        self.color_range.changed.connect(self.color_range_changed)
        self.color_range.setFixedWidth(130)
        appearance.addWidget(self.color_range)
        appearance.addWidget(QLabel("Opacity", objectName="muted"))
        self.opacity = QComboBox()
        for percent in (100, 90, 80, 70, 60, 50):
            self.opacity.addItem(f"{percent}%", percent)
        self.opacity.setCurrentIndex(
            max(0, self.opacity.findData(int(round(float(prefs.get("opacity", 100)))))))
        self.opacity.setFixedWidth(74)
        self.opacity.setToolTip("Fill opacity of every wafer map.\n"
                                "Contour lines and measured points stay solid; the colour bar shows "
                                "the same blended colours as the maps.")
        self.opacity.currentIndexChanged.connect(self.queue_plot_style)
        appearance.addWidget(self.opacity)
        appearance.addWidget(QLabel("Decimals", objectName="muted"))
        self.point_decimals = QSpinBox(objectName="pointValueDecimals")
        self.point_decimals.setRange(0, 10)
        self.point_decimals.setValue(prefs.get("point_value_decimals", 2))
        self.point_decimals.setFixedWidth(60)
        self.point_decimals.setToolTip("Decimal places for Point values (0–10). Does not change source values.")
        self.point_decimals.setKeyboardTracking(False)
        self.point_decimals.valueChanged.connect(self.change_point_precision)
        _PLOT_PAGES.add(self)
        appearance.addWidget(self.point_decimals)
        appearance.addStretch()
        header.addLayout(appearance)
        layout.addLayout(header)
        settings = QFrame(objectName="panel")
        controls = QVBoxLayout(settings)
        controls.setContentsMargins(12, 10, 12, 10)
        controls.setSpacing(8)
        coordinates = QHBoxLayout()
        self.x_column, self.y_column = QComboBox(), QComboBox()
        for title, widget in (("X", self.x_column), ("Y", self.y_column)):
            coordinates.addWidget(QLabel(title, objectName="muted"))
            coordinates.addWidget(widget, 1)
            widget.setMinimumContentsLength(8)
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        options = coordinates
        self.diameter = QComboBox()
        self.diameter.addItems(["Auto", "100", "200", "300"])
        self.diameter.setEditable(True)
        self.diameter.setFixedWidth(88)
        self.diameter.setToolTip("Auto recognizes 100 / 200 / 300 mm wafers from X(mm) and Y(mm).")
        options.addWidget(QLabel("Diameter", objectName="muted"))
        options.addWidget(self.diameter)
        options.addSpacing(10)
        self.labels = QCheckBox("Point values")
        self.points = QCheckBox("Measurement points")
        self.contour = QCheckBox("Contour lines")
        self.point_outline = QCheckBox("Point outline")
        self.fill_edge = QCheckBox("Fill edge")
        self.shared = QCheckBox("Shared scale / parameter")
        self.scale_bar = QCheckBox("Scale bar")
        self.fill_edge.setToolTip("Estimate the unmeasured edge by mirroring outer samples before interpolation.")
        self.labels.setChecked(bool(prefs.get("point_values", True)))
        self.points.setChecked(bool(prefs.get("measurement_points", True)))
        self.contour.setChecked(bool(prefs.get("contour", False)))
        self.point_outline.setChecked(bool(prefs.get("point_outline", False)))
        self.fill_edge.setChecked(bool(prefs.get("fill_edge", True)))
        self.shared.setChecked(bool(prefs.get("shared_scale", False)))
        self.scale_bar.setChecked(bool(prefs.get("scale_bar", True)))
        self.labels.setToolTip("Show or hide the numeric value beside every measured position.")
        self.points.setToolTip("Show or hide the measured-position dots.")
        self.contour.setToolTip("Overlay iso-lines of the interpolated surface (topographic look).")
        self.point_outline.setToolTip("Draw a light ring around every measured point so it stays visible on dark areas.")
        self.labels.toggled.connect(self.queue_overlay_visibility)
        self.points.toggled.connect(self.queue_overlay_visibility)
        self.contour.toggled.connect(self.queue_plot_style)
        self.point_outline.toggled.connect(self.queue_plot_style)
        self.fill_edge.toggled.connect(self.refresh_fill_edge)
        self.shared.toggled.connect(self.invalidate)
        for control in (self.labels, self.points, self.contour, self.point_outline, self.fill_edge, self.shared):
            options.addWidget(control)
        self.scale_bar.setToolTip("Show the color scale beside every wafer map.")
        self.scale_bar.toggled.connect(self.queue_plot_style)
        options.addWidget(self.scale_bar)
        options.addSpacing(12)
        options.addWidget(QLabel("Wafers / page", objectName="muted"))
        self.page_size = QSpinBox()
        self.page_size.setRange(1, 99)
        self.page_size.setValue(int(prefs.get("map_page_size", 12)))
        self.page_size.setFixedWidth(58)
        self.page_size.setKeyboardTracking(False)
        self.page_size.setToolTip(
            "Draw one page at a time; every metric of a wafer stays on its page.")
        self.page_size.valueChanged.connect(self._page_size_changed)
        options.addWidget(self.page_size)
        self.page_back = QPushButton("◀", objectName="subtle")
        self.page_back.setFixedWidth(34)
        self.page_back.clicked.connect(lambda: self.change_page(-1))
        options.addWidget(self.page_back)
        self.page_label = QLabel("Page 1 / 1", objectName="hint")
        options.addWidget(self.page_label)
        self.page_next = QPushButton("▶", objectName="subtle")
        self.page_next.setFixedWidth(34)
        self.page_next.clicked.connect(lambda: self.change_page(1))
        options.addWidget(self.page_next)
        self.page_index = 0
        options.addStretch()
        controls.addLayout(options)
        layout.addWidget(settings)
        self.stack = QStackedWidget()
        self.empty = QLabel(objectName="subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack.addWidget(self.empty)
        self._figure = Figure(figsize=(8, 6), dpi=100, facecolor="white")
        self._canvas = None
        self._export_dirty = True
        self.scroll = StaticMapView()
        self.scene = self.scroll.scene()
        self.map_grid = WaferMapGrid()
        self.scene.addItem(self.map_grid)
        self.canvas_proxy = self.map_grid
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.scroll.setBackgroundBrush(Qt.GlobalColor.white)
        self.scroll.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.scroll.viewport().installEventFilter(self)
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_png)
        self.copy_button.setToolTip("Copy the full map grid as a PNG. Ctrl+C works while this tab is active.")
        self.stack.addWidget(self.scroll)
        self.selector_panel = QWidget()
        box_layout = QVBoxLayout(self.selector_panel)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_bar = QHBoxLayout()
        box_bar.addStretch()
        self.selector = MapSelector()
        for title, handler in (("All", self.selector.selectAll), ("None", self.selector.clearSelection)):
            control = QPushButton(title, objectName="subtle")
            control.clicked.connect(handler)
            box_bar.addWidget(control)
        box_layout.addLayout(box_bar)
        box_layout.addWidget(self.selector, 1)
        self.stack.addWidget(self.selector_panel)
        layout.addWidget(self.stack, 1)
        self.status = QLabel("", objectName="hint")
        self.map_grid.status_callback = self.status.setText
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.map_grid.rendered.connect(self._publish_map_result)
        self.map_grid.render_failed.connect(self._map_render_failed)
        self.map_grid.render_progress.connect(self._map_render_progress)
        self.x_column.currentIndexChanged.connect(self.invalidate)
        self.y_column.currentIndexChanged.connect(self.invalidate)
        self.selector.changed.connect(self.selector_changed)
        self.diameter.currentTextChanged.connect(self.invalidate)
        self.invalidate()

    @property
    def figure(self):
        """The export figure, built lazily, never used by screen presentation."""
        self._ensure_export()
        return self._figure

    @property
    def canvas(self):
        self._ensure_export()
        if self._canvas is None:
            self._canvas = FigureCanvasQTAgg(self._figure)
            self._canvas.setParent(self)
            self._canvas.hide()
        return self._canvas

    @property
    def artists(self):
        """Matplotlib export artists (not pyqtgraph scene items)."""
        self._ensure_export()
        return self._artists

    @artists.setter
    def artists(self, value):
        self._artists = value
        self._export_dirty = True

    def _ensure_export(self):
        self._flush_export_overlay()
        if (getattr(self.window(), '_source_refresh_pending', False)
                or self.background_render_pending or (self.result is not None and self.dirty)):
            raise ValueError("Wait for current Wafer Map data and graphics to finish before exporting.")
        if self.result is None or not self._export_dirty:
            return
        rows, columns = self.result["shape"]
        width, height = columns*460, rows*420+30
        scale = screen_render_scale(width, height, resolution_settings(self.resolution)[0])
        self._figure.set_dpi(100*scale)
        self._figure.set_size_inches(width/100, height/100, forward=False)
        if self._canvas is None:
            self._canvas = FigureCanvasQTAgg(self._figure)
            self._canvas.setParent(self)
            self._canvas.hide()
        self._canvas.setFixedSize(round(width*scale), round(height*scale))
        self._artists = draw_array(self._figure, self.result, int(self.font_size.currentText()))
        for ax, scene in zip(self._figure.axes[:len(self.result["scenes"])], self.result["scenes"]):
            if scene.get("skip"):
                continue
            caption = measurement_caption(scene["label"], self.identity_labels)
            if scene["error"]:
                ax.set_title(f'{scene["metric"]}\n{caption}')
            else:
                ax._wafer_title_details[0].set_text(caption.replace("\n", " · "))
        self._export_dirty = False

    def draw_state(self):
        """Return the successful map selection that can be restored later."""
        return {
            "enabled": self.has_drawn_once,
            "cells": tuple(sorted(self.drawn_cells)),
        }

    def restore_draw_state(self, state):
        """Resume automatic drawing from a previously successful selection."""
        if not isinstance(state, dict) or state.get("enabled") is not True:
            return
        try:
            cells = {
                (str(wafer), str(metric))
                for wafer, metric in state.get("cells", ())
            }
        except (TypeError, ValueError):
            return
        cells = self.selector.reconciled_cells(cells)
        if not cells:
            return
        preserve = self.result is not None and cells == self.drawn_cells
        self.has_drawn_once = True
        self.drawn_cells = set(cells)
        self.selector.set_selected_cells(cells, notify=False)
        self.selector.pending_draw = False
        self.invalidate(preserve_canvas=preserve)
        self.draw_state_changed.emit(self.draw_state())
        self.queue_input_refresh()

    @staticmethod
    def populate(combo, entries, previous=None):
        combo.blockSignals(True)
        combo.clear()
        for text, value in entries:
            combo.addItem(text, value)
        combo.setCurrentIndex(max(0, combo.findData(previous)))
        combo.blockSignals(False)

    def set_input(self, frame, selection):
        signature = (id(frame), tuple(selection["wafers"]), tuple(selection["metrics"]), selection["wafer_column"],
                     tuple((key, tuple(selection["groups"].get(key, ()))) for key in selection["wafers"])
                     if "groups" in selection else None)
        if signature == self.signature:
            return
        # Only a data change may redraw by itself. Adding or removing wafers or
        # parameters rebuilds the box grid, so the engineer picks the maps again
        # and presses Draw selected; that is also what keeps the previous box
        # selection from being redrawn behind their back.
        grid_changed = (
            tuple(selection["wafers"]) != tuple(self.selection.get("wafers", ()))
            or tuple(selection["metrics"]) != tuple(self.selection.get("metrics", ()))
            or selection["wafer_column"] != self.selection.get("wafer_column")
        )
        changed_table = self.frame is not frame
        self.signature, self.frame, self.selection = signature, frame, selection.copy()
        if changed_table:
            names = {"".join(c.lower() for c in name if c.isalnum()): name for name in frame}
            entries = [(name, name) for name in frame]
            for combo, aliases in ((self.x_column, ("xmm", "fieldx", "x", "diex")),
                                   (self.y_column, ("ymm", "fieldy", "y", "diey"))):
                previous = combo.currentData()
                default = previous if previous in frame else next((names[a] for a in aliases if a in names), None)
                self.populate(combo, entries, default)
        self.selector.set_array(selection["wafers"], selection["metrics"], selection.get("labels"))
        replay = (self.has_drawn_once and not grid_changed
                and not self.selector.pending_draw
                and set(self.selector.selected_cells()) == set(self.drawn_cells))
        self.invalidate(preserve_canvas=replay and self.result is not None)
        if replay:
            # Auto redraw only replays the last successful draw; a pending box
            # selection waits for the engineer to press Draw selected.
            self.queue_input_refresh()

    def show_selector(self):
        self.page_intent = "selector"
        self._center_timer.stop()
        self._fit_width_timer.stop()
        self.pending_input_refresh = False
        self.input_refresh_timer.stop()
        if self.worker is not None:
            self.invalidate()
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        self.empty.clear()
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)

    def change_colormap(self, *_):
        """Follow the palette box: show the new palette and reset to its default slice."""
        name = self.color_map.currentData()
        self.color_range.set_colormap(colormaps[name])
        self.color_range.set_range(*auto_cmap_range(name))
        self.queue_plot_style()

    def color_range_changed(self, *_):
        """Apply immediately, then persist once the user pauses dragging."""
        self.queue_plot_style()
        self.settings_timer.start()

    def persist_color_preferences(self):
        if getattr(self, "document_scoped", False):
            return  # Saved with the owning WKB; Discard must not leak preferences.
        low, high = self.color_range.range()
        try:
            save_settings({
                "color_map": self.color_map.currentData(),
                "color_range_low": round(low, 4),
                "color_range_high": round(high, 4),
            })
        except OSError as error:
            self.status.setText(f"Could not save color preferences: {error}")

    def invalidate(self, *_, preserve_canvas=False):
        self._cancel_background_draw()
        self.pending_fill_refresh = False
        self.revision += 1
        self.dirty = True
        if not preserve_canvas:
            self.result = None
            self.artists = []
        if self.worker:
            self.worker.requestInterruption()
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.stack.setCurrentWidget(self.scroll if preserve_canvas and self.page_intent == "canvas"
                                   else self.selector_panel)
        nr, nc = len(self.selection.get("wafers", [])), len(self.selection.get("metrics", []))
        if not nr or not nc:
            self.empty.clear()
            self.stack.setCurrentWidget(self.empty)
        count = len(self.selector.selected_cells())
        self.summary.setText(f"{count} / {nr * nc} selected  ·  {nr} × {nc}")

    def selector_changed(self):
        """A changed box selection waits for the explicit Draw selected click."""
        self.pending_input_refresh = False
        self.input_refresh_timer.stop()
        self.page_index = 0
        self.invalidate()

    def paginate_wafers(self, wafers):
        """One page at a time; a wafer always brings all its metrics along."""
        wafers = list(wafers)
        size = max(1, self.page_size.value())
        pages = max(1, (len(wafers) + size - 1) // size)
        self.page_index = min(max(0, self.page_index), pages - 1)
        start = self.page_index * size
        return wafers[start:start + size], self.page_index, pages

    def change_page(self, delta):
        if self.worker is not None:
            return
        self.page_index = max(0, self.page_index + delta)
        if self.selector.selected_cells():
            self.draw_maps()

    def _page_size_changed(self, *_args):
        self.page_index = 0
        if not self.has_drawn_once or not self.selector.selected_cells():
            return
        if self.worker is not None:
            self._pending_page_refresh = True
            return
        self.draw_maps()

    def _update_page_controls(self, index, pages):
        self.page_label.setText(f"Page {index + 1} / {pages}")
        self.page_back.setEnabled(index > 0)
        self.page_next.setEnabled(index < pages - 1)

    def refresh_fill_edge(self, *_):
        """Recompute edge continuation while leaving the current plot visible."""
        if self.worker is not None:
            # Coalesce rapid checkbox changes and redraw once with the latest
            # state after the current interpolation has stopped.
            self.pending_fill_refresh = True
            self.revision += 1
            self.worker.requestInterruption()
            self.status.setText("Restarting the edge-fill update…")
            return
        if self.map_grid.render_pending:
            self._cancel_background_draw()
            self._start_surface_job(preserve_canvas=self.result is not None)
            return
        if self.result is None or self.stack.currentWidget() is not self.scroll:
            self.invalidate()
            return
        self._start_surface_job(preserve_canvas=True)

    def draw_maps(self, *_):
        self.page_intent = "canvas"
        self.pending_input_refresh = False
        self.input_refresh_timer.stop()
        if _ and self.map_grid.render_pending:
            self.revision += 1
            self._cancel_background_draw()
            self.status.setText('Wafer drawing cancelled; click Draw selected to refresh current data.')
            return
        self._start_surface_job(preserve_canvas=False)

    def queue_input_refresh(self):
        """Redraw a previously drawn array after Data changes, without prompting."""
        if not self.selector.selected_cells():
            self.pending_input_refresh = False
            self.input_refresh_timer.stop()
            return
        self.pending_input_refresh = True
        if self.worker is not None:
            self.worker.requestInterruption()
            return
        self.input_refresh_timer.start()

    def refresh_previous_selection(self):
        if not self.pending_input_refresh:
            return
        if self.worker is not None:
            self.worker.requestInterruption()
            return
        self.pending_input_refresh = False
        # A data refresh repaints the maps in place: same zoom, same scroll
        # offset and the same selector-or-canvas page the engineer chose.
        self._refresh_keeps_page = True
        self._start_surface_job(preserve_canvas=True)
        self.apply_page_intent()

    def apply_page_intent(self):
        """Show the sub-page the engineer last chose: map boxes or the maps."""
        if getattr(self, "page_intent", "canvas") == "selector":
            self.stack.setCurrentWidget(self.selector_panel)
        elif self.result is not None:
            self.stack.setCurrentWidget(self.scroll)

    def _start_surface_job(self, preserve_canvas=False):
        if self.worker is not None:
            self.revision += 1
            self._cancel_background_draw()
            self.worker.requestInterruption()
            self.status.setText("Cancelling…")
            return
        try:
            if self.frame is None or self.frame.empty:
                raise ValueError("Load or paste a table in the Data tab first.")
            diameter = self.diameter.currentText().strip()
            try:
                diameter = None if diameter.lower() == "auto" else float(diameter)
            except ValueError:
                raise ValueError("Enter a positive diameter in coordinate units, or Auto.") from None
            options = ArrayOptions(self.x_column.currentData(), self.y_column.currentData(),
                                   diameter=diameter, labels=self.labels.isChecked(), points=self.points.isChecked(),
                                   fill_edge=self.fill_edge.isChecked(), shared_scale=self.shared.isChecked(),
                                   contour=self.contour.isChecked(), point_outline=self.point_outline.isChecked(),
                                   smoothing=float(get_settings().get("smoothing", 0.0)),
                                   cmap_range=self.color_range.range(),
                                   opacity=self.opacity.currentData() / 100,
                                   point_decimals=self.point_decimals.value(),
                                   cmap=self.color_map.currentData(), show_colorbar=self.scale_bar.isChecked())
            cells = self.selector.selected_cells()
            if not cells:
                raise ValueError("Select at least one map box before drawing.")
            self.pending_cells = set(cells)
            # Lay out only the rows and columns that actually contain a drawn
            # box: the canvas then scales with the number of maps instead of
            # reserving blank space for every combination of the Data selection.
            wafers, metrics = drawn_axes(self.selection.get("wafers", []),
                                         self.selection.get("metrics", []), cells)
            wafers, page_index, pages = self.paginate_wafers(wafers)
            self._update_page_controls(page_index, pages)
            self._page_total = pages
            selection = dict(self.selection, cells=list(cells),
                             wafers=wafers, metrics=metrics)
            if preserve_canvas:
                self._cancel_background_draw()
                self.revision += 1
                self.dirty = True
                self.export_button.setEnabled(False)
                self.copy_button.setEnabled(False)
            else:
                self.invalidate()
            revision = self.revision
            # Option-driven re-renders keep the current zoom and scroll offset;
            # only a fresh "Draw selected" recentres the canvas.
            self._preserve_view = preserve_canvas
            self.pending_fill_refresh = False
            self.worker = SurfaceJob(self.frame, selection, options, self)
            self.worker.ready.connect(lambda result: self._accept_surface_result(result, revision))
            if preserve_canvas:
                self.worker.failed.connect(
                    lambda message: self.show_refresh_error(message) if revision == self.revision else None)
            else:
                self.worker.failed.connect(lambda message: self.show_error(message) if revision == self.revision else None)
            self.worker.progress.connect(lambda done, total: self.status.setText(f"Interpolating {done} / {total} maps…")
                                         if revision == self.revision else None)
            self.worker.finished.connect(self.finished)
            self.draw_button.setText("Cancel")
            if preserve_canvas:
                self.stack.setCurrentWidget(self.scroll)
                self.status.setText("Updating the estimated edge…")
            else:
                self.stack.setCurrentIndex(0)
                self.empty.setText("Preparing wafer maps…")
            self.worker.start()
        except (ValueError, KeyError) as error:
            if preserve_canvas and self.result is not None:
                self.show_refresh_error(str(error))
            else:
                self.show_error(str(error))

    def show_refresh_error(self, message):
        """Report an option-refresh failure without discarding the last plot."""
        self._cancel_background_draw()
        self.dirty = True
        self.stack.setCurrentWidget(self.scroll)
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.status.setText(f"Could not update wafer maps; previous image retained: {message}")

    def show_error(self, message):
        self._cancel_background_draw()
        self.result = None
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.stack.setCurrentIndex(0)
        self.empty.setText(message)
        self.status.setText("Check the data and settings, then try again.")

    def finished(self):
        if self.worker is None or self.sender() is not self.worker:
            return  # A completion event queued before close must not refresh the page.
        self.worker.deleteLater()
        self.worker = None
        self.draw_button.setText("Cancel" if self.map_grid.render_pending else "Draw selected")
        if getattr(self, "_pending_page_refresh", False):
            self._pending_page_refresh = False
            self._page_refresh_timer.start()
            return
        if self.pending_input_refresh:
            self.input_refresh_timer.start()
            return
        if self.pending_fill_refresh:
            self.pending_fill_refresh = False
            self._start_surface_job(preserve_canvas=self.result is not None)
            return
        if (self.result is None and self._pending_render is None
                and self.empty.text() == "Preparing wafer maps…"):
            self.show_selector()

    @property
    def background_render_pending(self):
        return self._graphics_work_pending() or self.overlay_timer.isActive()

    def _graphics_work_pending(self):
        return (self.worker is not None or self.pending_input_refresh
                or self._pending_render is not None or self.map_grid.render_pending
                or any(timer.isActive() for timer in (self.input_refresh_timer, self.font_timer,
                                                       self.style_timer, self._page_refresh_timer)))

    def _cancel_background_draw(self):
        """Use the parent's existing cancellation hook for unpublished graphics."""
        self._render_serial += 1
        self._pending_render = None
        self._style_source = None
        self._presentation_fields.clear()
        self.map_grid.cancel_render()
        for timer in (self.font_timer, self.style_timer, self.overlay_timer,
                      self._settle_timer, self._restore_scroll_timer):
            timer.stop()
        self._saved_scroll = None
        if self.worker is None:
            self.draw_button.setText("Draw selected")

    def _style_values(self):
        return dict(cmap=self.color_map.currentData(), cmap_range=self.color_range.range(),
                    opacity=self.opacity.currentData()/100, show_colorbar=self.scale_bar.isChecked(),
                    contour=self.contour.isChecked(), point_outline=self.point_outline.isChecked(),
                    labels=self.labels.isChecked(), points=self.points.isChecked(),
                    point_decimals=self.point_decimals.value())

    def _styled_result(self, result, fields):
        """Clone presentation options only; numerical surfaces/layers stay intact."""
        changes = {name:value for name,value in self._style_values().items() if name in fields}
        if all(getattr(result['settings'], name) == value for name,value in changes.items()):
            return result
        current = dict(result, settings=replace(result['settings'], **changes), scenes=[])
        for scene in result['scenes']:
            copied = dict(scene)
            if 'options' in scene:
                copied['options'] = replace(scene['options'], **changes)
            current['scenes'].append(copied)
        return current

    def _accept_surface_result(self, result, revision):
        if revision == self.revision:
            self.render_result(self._styled_result(result, self._style_values()))

    def _map_render_progress(self, done, total):
        if self._pending_render is not None:
            self.status.setText(f"Preparing wafer graphics {done} / {total}…")

    def _map_render_failed(self, message):
        if self._pending_render is None:
            return
        self._cancel_background_draw()
        self.dirty = True
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        if self.result is None:
            self.stack.setCurrentWidget(self.empty)
            self.empty.setText(f"Could not prepare wafer graphics: {message}")
        self.status.setText(f"Could not update wafer graphics; current data is not drawn: {message}")

    def render_result(self, result):
        try:
            self._cancel_background_draw()
            # A worker may finish after this presentation-only control changed.
            result["settings"].point_decimals = self.point_decimals.value()
            for scene in result["scenes"]:
                if "options" in scene:
                    scene["options"].point_decimals = self.point_decimals.value()
            state = {"result":result, "revision":self.revision, "serial":self._render_serial,
                     "preserve_view":getattr(self, '_preserve_view', False),
                     "keep_page":getattr(self, '_refresh_keeps_page', False),
                     "cells":set(self.pending_cells)}
            self._pending_render = state
            self.dirty = True
            self.export_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.draw_button.setText("Cancel")
            self.status.setText(f"Preparing wafer graphics 0 / {len(result['scenes'])}…")
            def current():
                if sip.isdeleted(self) or self._pending_render is not state:
                    return False
                if state['revision'] != self.revision or state['serial'] != self._render_serial:
                    self._pending_render = None
                    self.dirty = True
                    if self.worker is None:
                        self.draw_button.setText('Draw selected')
                    return False
                return True
            self.map_grid.set_result(result, int(self.font_size.currentText()), self.identity_labels,
                                     deferred=True, valid=current)
        except Exception as error:
            self._map_render_failed(str(error))

    def _publish_map_result(self, result):
        state = self._pending_render
        if (state is None or state['result'] is not result or state['revision'] != self.revision
                or state['serial'] != self._render_serial):
            return
        try:
            saved_view = self.capture_view() if state['preserve_view'] else None
            self.result = result
            self._pending_render = None
            self._export_dirty = True
            self.dirty = False
            self.has_drawn_once = True
            self.drawn_cells = state['cells']
            self.selector.pending_draw = False
            self.draw_state_changed.emit(self.draw_state())
            self._refresh_keeps_page = False
            # A page choice made during preparation wins over the old request.
            self.apply_page_intent()
            self.refresh_canvas()
            if saved_view is not None:
                self.restore_view(saved_view)
            count = self.map_grid.valid_count
            self.export_button.setEnabled(bool(count))
            self.copy_button.setEnabled(bool(count))
            rows, columns = result["shape"]
            self.status.setText(f"{count} / {result['selected_count']} maps · "
                                f"Page {self.page_index + 1} / {getattr(self, '_page_total', 1)} · "
                                f"{rows} × {columns} grid · {result['size_summary']}.")
            self.draw_button.setText("Cancel" if self.worker is not None else "Draw selected")
        except Exception as error:
            self.show_error(str(error))

    def _apply_identity_labels(self):
        if self.result is None:
            return
        self._export_dirty = True
        for panel in self.map_grid.panels:
            panel.identity_labels = self.identity_labels
            panel.update()

    def set_identity_labels(self, options):
        """Only repaint caption text, even if interpolation is still running."""
        if self.identity_labels == options:
            return
        self.identity_labels = dict(options)
        if self.background_render_pending:
            self._queue_presentation(self.font_timer, set())
            return
        self._apply_identity_labels()

    def refresh_canvas(self):
        """Present the prepared ImageItems, without constructing export artists."""
        if self.result is None:
            return
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        self.scroll.setSceneRect(self.scene.sceneRect())
        self.resize_canvas()
        self._settle_timer.start()

    def settle_canvas(self):
        if self.result is None:
            return
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        self.scroll.setSceneRect(self.scene.sceneRect())
        if getattr(self, "_canvas_resized", False):
            # A new grid (for example after the records filter) changed the
            # canvas size; re-fit the view instead of reusing a stale transform.
            self._canvas_resized = False
            self.resize_canvas()
        self.scroll.viewport().update()

    def resize_canvas(self, *_):
        if self.result is None:
            return
        rows, columns = self.result["shape"]
        base_width = columns * 460
        text = self.zoom.currentText()
        display_scale = min(1, max(280, self.scroll.viewport().width() - 20) / base_width) if text == "Fit width" else int(text[:-1]) / 100
        display_scale = max(.01, display_scale)
        self.scroll.resetTransform()
        self.scroll.scale(display_scale, display_scale)
        # The transformed scene's scrollbar range is finalized on the next
        # event-loop pass. Centering before then can use the previous range.
        self._center_timer.start(0)

    def center_canvas(self):
        """Center the plot array horizontally without losing its vertical row."""
        if self.result is None or self.stack.currentWidget() is not self.scroll:
            return
        viewport_center = self.scroll.mapToScene(self.scroll.viewport().rect().center())
        canvas_center = self.canvas_proxy.sceneBoundingRect().center()
        self.scroll.centerOn(canvas_center.x(), viewport_center.y())

    def capture_view(self):
        """Remember zoom and scroll offset so a re-render can keep the same view."""
        return {"zoom": self.zoom.currentText(),
                "scale": self.scroll.transform().m11(),
                "h": self.scroll.horizontalScrollBar().value(),
                "v": self.scroll.verticalScrollBar().value()}

    def restore_view(self, saved):
        """Re-apply a captured view after the canvas has been re-rendered."""
        if self.zoom.currentText() != saved["zoom"]:
            self.zoom.setCurrentText(saved["zoom"])
        # An explicit restore supersedes the fit/centering queued by rendering.
        # Also prevent settle_canvas from scheduling a second late recenter.
        self._center_timer.stop()
        self._fit_width_timer.stop()
        self._canvas_resized = False
        self.scroll.resetTransform()
        self.scroll.scale(saved["scale"], saved["scale"])
        horizontal = self.scroll.horizontalScrollBar()
        vertical = self.scroll.verticalScrollBar()
        horizontal.setValue(saved["h"])
        vertical.setValue(saved["v"])

        self._saved_scroll = dict(saved, serial=self._render_serial)
        self._restore_scroll_timer.start()

    def _restore_scroll(self):
        saved = self._saved_scroll
        if saved is None or saved['serial'] != self._render_serial:
            return
        horizontal, vertical = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        horizontal.setValue(min(saved['h'], horizontal.maximum()))
        vertical.setValue(min(saved['v'], vertical.maximum()))
        self._saved_scroll = None

    def change_resolution(self, *_):
        if self.result is None:
            return
        _render_scale, dpi = resolution_settings(self.resolution)
        self._export_dirty = True
        self.status.setText(f"Resolution: {self.resolution.currentText()} · PNG output {dpi} dpi.")

    def redraw_style(self, *_):
        """Merge rapid font changes before updating the static scene."""
        self._queue_presentation(self.font_timer, set())

    def queue_plot_style(self, *_):
        """Color changes reuse prepared surfaces instead of repeating interpolation."""
        self._queue_presentation(self.style_timer,
            {'cmap', 'cmap_range', 'opacity', 'show_colorbar', 'contour', 'point_outline'})

    def _queue_presentation(self, timer, fields):
        base = self._pending_render['result'] if self._pending_render is not None else self._style_source
        merged = self._presentation_fields | set(fields)
        if base is None and (self.worker is not None or self.pending_input_refresh):
            self._presentation_fields = merged
            self.status.setText('Current plot options will apply when the data is ready…')
            return
        if base is None:
            if self.result is None or self.dirty:
                return
            base = self.result
        self._cancel_background_draw()
        self._style_source = base
        self._presentation_fields = merged
        self.dirty = True
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.status.setText('Updating wafer graphics…')
        timer.start()

    def _submit_presentation(self, fields):
        base = (self._pending_render['result'] if self._pending_render is not None
                else self._style_source)
        if base is None and (self.worker is not None or self.pending_input_refresh):
            self._presentation_fields |= set(fields)
            return
        if base is None:
            if self.result is None or self.dirty:
                return
            base = self.result
        current = self._styled_result(base, self._presentation_fields | set(fields))
        self._preserve_view = True
        self.render_result(current)

    def apply_plot_style(self):
        self._submit_presentation({'cmap', 'cmap_range', 'opacity', 'show_colorbar', 'contour', 'point_outline'})

    def queue_overlay_visibility(self, *_):
        """Merge rapid value/point toggles into a single repaint."""
        if (self._pending_render is not None or self._style_source is not None
                or self.worker is not None or self.pending_input_refresh):
            self._queue_presentation(self.overlay_timer, {'labels', 'points', 'point_decimals'})
            return
        if self.result is None or not self.map_grid.valid_count or self.dirty:
            return
        self.status.setText("Updating points and contours…")
        self.overlay_timer.start()

    def change_point_precision(self, decimals):
        """One application preference, independent of document Save/Discard."""
        try:
            save_settings({"point_value_decimals": decimals})
        except OSError as error:
            self.status.setText(f"Could not save point decimals: {error}")
            self.sync_point_precision(get_settings()["point_value_decimals"])
            return
        self.sync_point_precision(decimals)

    @staticmethod
    def sync_point_precision(decimals):
        for page in tuple(_PLOT_PAGES):
            try:
                page.point_decimals.blockSignals(True)
                page.point_decimals.setValue(decimals)
                page.point_decimals.blockSignals(False)
                page.queue_overlay_visibility()
            except RuntimeError:
                _PLOT_PAGES.discard(page)  # Deleted Qt widget still awaiting Python GC.

    def apply_overlay_visibility(self, *_):
        """Toggle values and measured points without recalculating map surfaces."""
        if (self._pending_render is not None or self._style_source is not None
                or self.worker is not None or self.pending_input_refresh):
            self._submit_presentation({'labels', 'points', 'point_decimals'})
            return
        if self.result is None:
            return
        show_labels, show_points = self.labels.isChecked(), self.points.isChecked()
        self.result["settings"].labels = show_labels
        self.result["settings"].points = show_points
        decimals = self.point_decimals.value()
        self.result["settings"].point_decimals = decimals
        changed = False
        for panel in self.map_grid.panels:
            if panel.image is None:
                continue
            options = panel.source["options"]
            changed |= (options.labels != show_labels or options.points != show_points
                        or options.point_decimals != decimals)
            options.labels, options.points = show_labels, show_points
            if options.point_decimals != decimals:
                options.point_decimals = decimals
                panel._prepare_labels()
            panel.update()
        if changed and not self._export_dirty:
            # A previously requested export may be reused too: these are
            # presentation-only overlays, not a new surface or axes layout.
            for plot, _scene in self._artists:
                plot.value_labels.set_decimals(decimals)
                plot.value_labels.set_visible(show_labels)
                plot.point_markers.set_visible(show_points)
        values = "shown" if show_labels else "hidden"
        points = "shown" if show_points else "hidden"
        self.status.setText(f"Point values: {values} · Measurement points: {points}.")
        if (not self.dirty and not getattr(self.window(), '_source_refresh_pending', False)
                and not self.background_render_pending):
            available = bool(self.map_grid.valid_count)
            self.export_button.setEnabled(available)
            self.copy_button.setEnabled(available)

    def apply_font_style(self):
        """Resize Qt annotations; the colour fields and interpolations are reused."""
        self._submit_presentation(set())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and self.result is not None:
            delta = event.angleDelta()
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.scroll.zoom_page(event, self.zoom)
                self._center_timer.stop()
                self._fit_width_timer.stop()
                self._canvas_resized = False
                event.accept()
                return True
            else:
                horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or abs(delta.x()) > abs(delta.y())
                bar = self.scroll.horizontalScrollBar() if horizontal else self.scroll.verticalScrollBar()
                amount = (delta.x() if abs(delta.x()) > abs(delta.y()) else delta.y())
                if not amount:
                    pixels = event.pixelDelta()
                    amount = pixels.x() if horizontal else pixels.y()
                step = max(bar.singleStep() * 3, 36)
                bar.setValue(bar.value() - round(np.sign(amount) * step))
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Percentage zoom does not depend on viewport width. A late layout
        # resize must not recenter a previously restored/user-scrolled view.
        if self.zoom.currentText() == "Fit width":
            self._fit_width_timer.start(0)

    def _resize_fit_width(self):
        # A resize requested while fitting must not later re-centre an explicit
        # percentage zoom or restored viewport. The owned timer also coalesces
        # layout cascades and is cancelled when this page is destroyed.
        if self.zoom.currentText() == "Fit width":
            self.resize_canvas()

    def export_image(self):
        """Write the complete array as PNG (chosen quality) or as SVG / PDF vector."""
        if not self._export_ready():
            return
        if self.result is None or not self.artists:
            return
        self.apply_overlay_visibility()
        path, chosen = QFileDialog.getSaveFileName(
            self, "Export wafer map array", "wafer_maps.png",
            "PNG image (*.png);;SVG vector (*.svg);;PDF vector (*.pdf)")
        if not path:
            return
        try:
            suffix = Path(path).suffix.lower()
            if suffix not in (".png", ".svg", ".pdf"):
                suffix = ".svg" if "SVG" in chosen else ".pdf" if "PDF" in chosen else ".png"
            path = str(Path(path).with_suffix(suffix))
            _render_scale, requested = resolution_settings(self.resolution)
            dpi = export_dpi(self.figure, requested, MAX_EXPORT_PIXELS)
            if suffix == ".png":
                self.figure.savefig(path, dpi=dpi, facecolor="white")
                note = f" · capped from {requested} dpi" if dpi < requested else ""
                self.status.setText(f"Exported the map grid at {dpi} dpi{note}: {path}")
            else:
                # Vector output keeps axes, text, iso-lines and measured points
                # sharp; dpi only sets how finely the colour field is rasterised
                # inside the file.
                self.figure.savefig(path, dpi=dpi, facecolor="white")
                self.status.setText(f"Exported {suffix[1:].upper()} with a {dpi} dpi color layer: {path}")
        except Exception as error:
            self.status.setText(f"Export failed: {error}")

    def copy_png(self):
        if not self._export_ready():
            return
        if self.result is None or not self.artists:
            return
        self.apply_overlay_visibility()
        _render_scale, requested = resolution_settings(self.resolution)
        dpi = export_dpi(self.figure, requested, MAX_COPY_PIXELS)
        note = f" · capped from {requested} dpi" if dpi < requested else ""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status.setText("Copying…")
        QApplication.processEvents()
        try:
            image = QImage.fromData(self.png_bytes(), "PNG")
            if image.isNull():
                raise ValueError("Unable to create the PNG image.")
            QApplication.clipboard().setImage(image)
            self.status.setText(f"Copied the map grid at {dpi} dpi{note} · "
                                f"{image.width()} × {image.height()} px")
        except Exception as error:
            self.status.setText(f"Copy failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()

    def png_bytes(self):
        """Current Copy PNG grid, without touching the system clipboard."""
        if not self._export_ready():
            raise ValueError(self.status.text())
        self.apply_overlay_visibility()
        requested = resolution_settings(self.resolution)[1]
        dpi = export_dpi(self.figure, requested, MAX_COPY_PIXELS)
        buffer = BytesIO()
        self.figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        return buffer.getvalue()

    def _flush_export_overlay(self):
        # A current map can apply precision/point overlays immediately, as
        # before. Never flush a stale source or an unfinished graphics request.
        if (self.overlay_timer.isActive() and self.result is not None and not self.dirty
                and not getattr(self.window(), '_source_refresh_pending', False)
                and not self._graphics_work_pending()):
            self.overlay_timer.stop()
            self.apply_overlay_visibility()

    def _export_ready(self):
        self._flush_export_overlay()
        if (getattr(self.window(), '_source_refresh_pending', False)
                or self.background_render_pending or (self.result is not None and self.dirty)):
            self.status.setText('Wait for current Wafer Map data and graphics to finish before exporting.')
            return False
        return self.result is not None

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    def stop(self):
        self.revision += 1  # Invalidate results already queued on the GUI thread.
        self._cancel_background_draw()
        self.pending_input_refresh = False
        self.pending_fill_refresh = False
        self._pending_page_refresh = False
        self.input_refresh_timer.stop()
        for timer in (self.font_timer, self.style_timer, self.overlay_timer,
                      self._center_timer, self._fit_width_timer, self._page_refresh_timer):
            timer.stop()
        if self.settings_timer.isActive():
            self.settings_timer.stop()
            self.persist_color_preferences()
        if self.worker is not None:
            job, self.worker = self.worker, None
            job.requestInterruption()
            for signal in (job.ready, job.failed, job.progress, job.finished):
                signal.disconnect()
            job.setParent(None)
            if not _CANCELLED_JOBS:
                app = QApplication.instance()
                try:
                    app.aboutToQuit.disconnect(_finish_cancelled_jobs)
                except TypeError:
                    pass
                app.aboutToQuit.connect(_finish_cancelled_jobs)
            _CANCELLED_JOBS.add(job)
            job.finished.connect(lambda: _release_cancelled_job(job))
            if not job.isRunning():
                _release_cancelled_job(job)
            self.draw_button.setText("Draw selected")
        self.map_grid.clear()
        self.result = None
        self._artists = []
        self._export_dirty = True
        self._figure.clear()
