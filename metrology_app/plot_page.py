"""Plot-tab controls, background interpolation and a scrollable Matplotlib canvas."""
from io import BytesIO
from html import escape
from pathlib import Path

import numpy as np
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QImage, QKeySequence, QPainter, QShortcut
from matplotlib import colormaps

from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout,
    QToolTip, QWidget,
)

from .array_plot import ArrayOptions, draw_array, drawn_axes, prepare_array
from .appearance import (COLOR_MAP_OPTIONS, MAX_COPY_PIXELS, MAX_EXPORT_PIXELS,
                         configure_resolution_combo, export_dpi, resolution_settings,
                         screen_render_scale)
from .color_range_bar import ColorRangeBar
from .map_selector import MapSelector
from .plot import auto_cmap_range, display_colormap, restyle_panel_title
from .settings import get_settings, save_settings

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
        self.signature = None
        self.dirty = True
        self.revision = 0
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
        self._background = None
        self._empty = None
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
        appearance.addWidget(QLabel("View", objectName="muted"))
        self.zoom = QComboBox()
        self.zoom.addItems(["Fit width", "50%", "75%", "100%", "125%", "150%", "175%", "200%", "250%", "300%"])
        self.zoom.currentTextChanged.connect(self.resize_canvas)
        appearance.addWidget(self.zoom)
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
        self.figure = Figure(figsize=(8, 6), dpi=100, facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.mpl_connect("motion_notify_event", self.hover_point)
        self.scene = QGraphicsScene(self)
        self.canvas_proxy = self.scene.addWidget(self.canvas)
        self.scroll = QGraphicsView(self.scene)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.canvas.installEventFilter(self)
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
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.x_column.currentIndexChanged.connect(self.invalidate)
        self.y_column.currentIndexChanged.connect(self.invalidate)
        self.selector.changed.connect(self.selector_changed)
        self.diameter.currentTextChanged.connect(self.invalidate)
        self.invalidate()

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
        self.has_drawn_once = True
        self.drawn_cells = set(cells)
        self.selector.set_selected_cells(cells, notify=False)
        self.selector.pending_draw = False
        self.invalidate()
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
        signature = (id(frame), tuple(selection["wafers"]), tuple(selection["metrics"]), selection["wafer_column"])
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
        self.invalidate()
        if (self.has_drawn_once and not grid_changed
                and not self.selector.pending_draw
                and set(self.selector.selected_cells()) == set(self.drawn_cells)):
            # Auto redraw only replays the last successful draw; a pending box
            # selection waits for the engineer to press Draw selected.
            self.queue_input_refresh()

    def show_selector(self):
        self.page_intent = "selector"
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

    def invalidate(self, *_):
        self.pending_fill_refresh = False
        self.revision += 1
        self.dirty = True
        self.result = None
        self.artists = []
        self._background = None
        self._empty = None
        if self.worker:
            self.worker.requestInterruption()
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.stack.setCurrentWidget(self.selector_panel)
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
        if self.result is None or self.stack.currentWidget() is not self.scroll:
            self.invalidate()
            return
        if self.worker is not None:
            # Coalesce rapid checkbox changes and redraw once with the latest
            # state after the current interpolation has stopped.
            self.pending_fill_refresh = True
            self.revision += 1
            self.worker.requestInterruption()
            self.status.setText("Restarting the edge-fill update…")
            return
        self._start_surface_job(preserve_canvas=True)

    def draw_maps(self, *_):
        self.page_intent = "canvas"
        self.pending_input_refresh = False
        self.input_refresh_timer.stop()
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
            self.worker = SurfaceJob(self.frame, selection, options, self)
            self.worker.ready.connect(lambda result: self.render_result(result) if revision == self.revision else None)
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
        self.dirty = False
        self.stack.setCurrentWidget(self.scroll)
        self.export_button.setEnabled(bool(self.artists))
        self.copy_button.setEnabled(bool(self.artists))
        self.status.setText(f"Could not update the estimated edge: {message}")

    def show_error(self, message):
        self.result = None
        self._background = None
        self._empty = None
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.stack.setCurrentIndex(0)
        self.empty.setText(message)
        self.status.setText("Check the data and settings, then try again.")

    def finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.draw_button.setText("Draw selected")
        if getattr(self, "_pending_page_refresh", False):
            self._pending_page_refresh = False
            QTimer.singleShot(0, self.draw_maps)
            return
        if self.pending_input_refresh:
            self.input_refresh_timer.start()
            return
        if (self.pending_fill_refresh and self.result is not None
                and self.stack.currentWidget() is self.scroll):
            self.pending_fill_refresh = False
            QTimer.singleShot(0, self.refresh_fill_edge)
            return
        if self.result is None and self.empty.text() == "Preparing wafer maps…":
            self.show_selector()

    def render_result(self, result):
        try:
            saved_view = self.capture_view() if getattr(self, "_preserve_view", False) else None
            self.result = result
            self.artists = draw_array(self.figure, result, int(self.font_size.currentText()))
            self.dirty = False
            self.has_drawn_once = True
            self.drawn_cells = set(self.pending_cells)
            self.selector.pending_draw = False
            self.draw_state_changed.emit(self.draw_state())
            if getattr(self, "_refresh_keeps_page", False):
                # The engineer may be re-picking maps: refresh without moving.
                self._refresh_keeps_page = False
            else:
                self.stack.setCurrentIndex(1)
            self.refresh_canvas()
            if saved_view is not None:
                self.restore_view(saved_view)
            self.export_button.setEnabled(bool(self.artists))
            self.copy_button.setEnabled(bool(self.artists))
            rows, columns = result["shape"]
            self.status.setText(f"{len(self.artists)} / {result['selected_count']} maps · "
                                f"Page {self.page_index + 1} / {getattr(self, '_page_total', 1)} · "
                                f"{rows} × {columns} grid · {result['size_summary']} · "
                                f"Hover a point for its value.")
        except Exception as error:
            self.show_error(str(error))

    def refresh_canvas(self):
        """Render once at the current screen scale; zoom reuses the Qt view only."""
        if self.result is None:
            return
        rows, columns = self.result["shape"]
        base_width, base_height = columns * 460, rows * 420 + 30
        requested_scale, _dpi = resolution_settings(self.resolution)
        render_scale = screen_render_scale(base_width, base_height, requested_scale)
        self.figure.set_dpi(100 * render_scale)
        self.figure.set_size_inches(base_width / 100, base_height / 100, forward=False)
        size = (round(base_width * render_scale), round(base_height * render_scale))
        self._canvas_resized = size != (self.canvas.width(), self.canvas.height())
        self.canvas.setFixedSize(*size)
        if self.artists:
            # One draw doubles as the clean background cache, so point-value and
            # measurement-point toggles only redraw two artists per panel.
            self.capture_overlay_background()
        else:
            self.canvas.draw()
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        self.resize_canvas()
        # The canvas resize event is delivered after this pass; settle the
        # scene rect and transform once Qt has processed it so the view never
        # shows a squeezed preview frame in the meantime.
        QTimer.singleShot(0, self.settle_canvas)

    def settle_canvas(self):
        if self.result is None:
            return
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        if getattr(self, "_canvas_resized", False):
            # A new grid (for example after the records filter) changed the
            # canvas size; re-fit the view instead of reusing a stale transform.
            self._canvas_resized = False
            self.resize_canvas()
        self.scroll.viewport().update()

    def overlay_artists(self):
        """Value labels, markers and iso-lines: the artists toggled by checkboxes."""
        return [artist for plot, _scene in self.artists
                for artist in (plot.contours, plot.value_labels, plot.point_markers)
                if artist is not None]

    def capture_overlay_background(self):
        """Rebuild the cached backdrops the fast repaint paths compose from.

        ``_empty`` holds the axes, ticks and titles only; ``_background`` adds
        the colour fields, wafer outlines and colour bars. Overlay toggles then
        only redraw a few artists, and colour changes redraw the fields onto the
        empty backdrop so semi-transparent fills blend correctly.
        """
        fields = [(plot.image, plot.image.get_visible()) for plot, _scene in self.artists
                  if plot.image is not None]
        state = [(artist, artist.get_visible()) for artist in self.overlay_artists()]
        state += fields
        for artist, _visible in state:
            artist.set_visible(False)
        self.canvas.draw()
        self._empty = self.canvas.copy_from_bbox(self.figure.bbox)
        for artist, visible in state:
            artist.set_visible(visible)
        self.draw_fields()
        self._background = self.canvas.copy_from_bbox(self.figure.bbox)
        self.blit_overlays()

    def draw_fields(self):
        """Draw colour fields, wafer outlines and colour bars onto the buffer."""
        canvas = self.canvas
        canvas.restore_region(self._empty)
        renderer = canvas.get_renderer()
        for plot, _scene in self.artists:
            if plot.image is not None:
                plot.image.draw(renderer)
            if plot.circle is not None:
                plot.circle.draw(renderer)
            canvas.blit(plot.axes.bbox)
            if plot.colorbar is not None:
                for image in plot.colorbar.ax.images:
                    image.draw(renderer)
                canvas.blit(plot.colorbar.ax.bbox)

    def blit_overlays(self):
        """Repaint just the value/point overlays over the cached background."""
        if self._background is None:
            self.canvas.draw_idle()
            return
        canvas = self.canvas
        renderer = canvas.get_renderer()
        canvas.restore_region(self._background)
        for plot, _scene in self.artists:
            artists = [artist for artist in (plot.contours, plot.value_labels, plot.point_markers)
                       if artist is not None]
            for artist in artists:
                if artist.get_visible():
                    artist.draw(renderer)
            if artists:
                canvas.blit(plot.axes.bbox)
        canvas.update()

    def repaint_fields(self):
        """Repaint the colour fields, wafer outlines and colour bars in place."""
        if self._empty is None:
            self.capture_overlay_background()
            return
        self.draw_fields()
        # The new colours belong to the background now, so refresh the cache and
        # lay the overlays back on top of it.
        self._background = self.canvas.copy_from_bbox(self.figure.bbox)
        self.blit_overlays()

    def resize_canvas(self, *_):
        if self.result is None:
            return
        rows, columns = self.result["shape"]
        base_width = columns * 460
        text = self.zoom.currentText()
        display_scale = min(1, max(280, self.scroll.viewport().width() - 20) / base_width) if text == "Fit width" else int(text[:-1]) / 100
        display_scale = max(.65, display_scale)
        render_scale = self.figure.dpi / 100
        self.scroll.resetTransform()
        self.scroll.scale(display_scale / render_scale, display_scale / render_scale)
        # The transformed scene's scrollbar range is finalized on the next
        # event-loop pass. Centering before then can use the previous range.
        self._center_timer.start(0)

    def center_canvas(self):
        """Center the plot array horizontally without losing its vertical row."""
        if self.result is None:
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

        def settle():
            # Ranges are finalised on the next event-loop pass; setting the
            # offsets again keeps the exact row and column the user was on.
            horizontal.setValue(min(saved["h"], horizontal.maximum()))
            vertical.setValue(min(saved["v"], vertical.maximum()))

        QTimer.singleShot(0, settle)

    def change_resolution(self, *_):
        if self.result is None:
            return
        render_scale, dpi = resolution_settings(self.resolution)
        self.status.setText(f"Rendering at {render_scale:.0%} · PNG output {dpi} dpi…")
        self.refresh_canvas()
        self.status.setText(f"Resolution: {self.resolution.currentText()} · PNG output {dpi} dpi.")

    def redraw_style(self, *_):
        """Merge rapid combo changes before touching the large Matplotlib tree."""
        if self.result is None:
            return
        self.status.setText("Updating plot labels…")
        self.font_timer.start()

    def queue_plot_style(self, *_):
        """Color changes reuse prepared surfaces instead of repeating interpolation."""
        if self.result is not None and self.stack.currentWidget() is self.scroll:
            self.status.setText("Updating colors…")
            self.style_timer.start()

    def apply_plot_style(self):
        if self.result is None or self.stack.currentWidget() is not self.scroll:
            return
        cmap, show_colorbar = self.color_map.currentData(), self.scale_bar.isChecked()
        contour, point_outline = self.contour.isChecked(), self.point_outline.isChecked()
        opacity = self.opacity.currentData() / 100
        cmap_range = self.color_range.range()
        previous = self.result["settings"]
        # Only the colour bar changes the figure layout; contours, outlines and
        # overlays are toggled in place on the fast blit path.
        structural_change = (show_colorbar != previous.show_colorbar)
        palette_change = (cmap != previous.cmap
                          or tuple(cmap_range) != tuple(previous.cmap_range or ())
                          or opacity != previous.opacity)
        self.result["settings"].cmap = cmap
        self.result["settings"].show_colorbar = show_colorbar
        self.result["settings"].contour = contour
        self.result["settings"].point_outline = point_outline
        self.result["settings"].opacity = opacity
        self.result["settings"].cmap_range = cmap_range
        for scene in self.result["scenes"]:
            if "options" in scene:
                scene["options"].cmap = cmap
                scene["options"].show_colorbar = show_colorbar
                scene["options"].contour = contour
                scene["options"].point_outline = point_outline
                scene["options"].opacity = opacity
                scene["options"].cmap_range = cmap_range
        if structural_change:
            self.artists = draw_array(self.figure, self.result, int(self.font_size.currentText()))
            self.refresh_canvas()
        else:
            palette = display_colormap(cmap, *cmap_range)
            for plot, _scene in self.artists:
                if plot.image is not None:
                    plot.image.set_cmap(palette)
                    plot.image.set_alpha(opacity)
                if plot.colorbar is not None and plot.image is not None:
                    plot.colorbar.update_normal(plot.image)
                if plot.point_markers is not None:
                    plot.point_markers.set_sizes(np.full(len(plot.positions), 13 if point_outline else 5))
                    plot.point_markers.set_linewidths(.9 if point_outline else 0)
                    plot.point_markers.set_edgecolors("#f5f5f5" if point_outline else "none")
                if plot.contours is not None:
                    plot.contours.set_visible(contour)
            if palette_change:
                # Only the colour fields change; repaint those instead of the
                # whole array and refresh the cached background afterwards.
                self.repaint_fields()
            else:
                self.blit_overlays()
        name = self.color_map.currentText()
        self.status.setText(f"Color: {name} · Palette {cmap_range[0]:.0%}–{cmap_range[1]:.0%} · "
                            f"Opacity {opacity:.0%} · Contours: {'on' if contour else 'off'} · "
                            f"Scale bar: {'shown' if show_colorbar else 'hidden'}.")
        QTimer.singleShot(0, self.center_canvas)

    def queue_overlay_visibility(self, *_):
        """Merge rapid value/point toggles into a single repaint."""
        if self.result is None or not self.artists:
            return
        self.status.setText("Updating points and contours…")
        self.overlay_timer.start()

    def apply_overlay_visibility(self, *_):
        """Toggle values and measured points without recalculating map surfaces."""
        if self.result is None or self.stack.currentWidget() is not self.scroll:
            return
        show_labels, show_points = self.labels.isChecked(), self.points.isChecked()
        self.result["settings"].labels = show_labels
        self.result["settings"].points = show_points
        for plot, scene in self.artists:
            if plot.value_labels is not None:
                plot.value_labels.set_visible(show_labels)
            if plot.point_markers is not None:
                plot.point_markers.set_visible(show_points)
            scene["options"].labels = show_labels
            scene["options"].points = show_points
        self.blit_overlays()
        values = "shown" if show_labels else "hidden"
        points = "shown" if show_points else "hidden"
        self.status.setText(f"Point values: {values} · Measurement points: {points}.")

    def apply_font_style(self):
        """Update existing text artists instead of rebuilding every map/colorbar."""
        if self.result is None:
            return
        base = int(self.font_size.currentText())
        label_size, tick_size = max(6, base - 1), max(5, base - 2)
        for plot, _scene in self.artists:
            restyle_panel_title(plot.axes, base)
            plot.axes.xaxis.label.set_fontsize(label_size)
            plot.axes.yaxis.label.set_fontsize(label_size)
            plot.axes.tick_params(labelsize=tick_size)
            if plot.colorbar is not None:
                plot.colorbar.ax.tick_params(labelsize=tick_size)
                if plot.colorbar.ax.title:
                    plot.colorbar.ax.title.set_fontsize(tick_size)
            if plot.value_labels is not None:
                size = max(4.5, base * .55)
                if len(plot.positions) > 100:
                    size = max(4.5, size - 1)
                plot.value_labels.set_fontsize(size)
        if self.figure._supxlabel is not None:
            self.figure._supxlabel.set_fontsize(tick_size)
        self.capture_overlay_background()
        self.status.setText(f"Plot font {base} pt · axis labels {label_size} pt · ticks {tick_size} pt.")

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and self.result is not None:
            delta = event.angleDelta()
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                amount = delta.y() or event.pixelDelta().y()
                self.zoom_by_wheel(amount, watched, event.position().toPoint())
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

    def zoom_by_wheel(self, delta, watched=None, position=None):
        if not delta or self.result is None:
            return
        render_scale = self.figure.dpi / 100
        current = round(100 * self.scroll.transform().m11() * render_scale)
        steps = [50, 75, 100, 125, 150, 175, 200, 250, 300]
        target = next((value for value in steps if value > current), steps[-1]) if delta > 0 else \
                 next((value for value in reversed(steps) if value < current), steps[0])
        viewport = self.scroll.viewport()
        if position is None:
            viewport_pos = viewport.rect().center()
            scene_pos = self.scroll.mapToScene(viewport_pos)
        elif watched is self.canvas:
            scene_pos = QPointF(position)
            viewport_pos = self.scroll.mapFromScene(scene_pos)
        else:
            viewport_pos = position
            scene_pos = self.scroll.mapToScene(viewport_pos)
        hbar, vbar = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        self.zoom.setCurrentText(f"{target}%")
        def restore_anchor():
            moved = self.scroll.mapFromScene(scene_pos)
            hbar.setValue(hbar.value() + moved.x() - viewport_pos.x())
            vbar.setValue(vbar.value() + moved.y() - viewport_pos.y())
        QTimer.singleShot(0, restore_anchor)

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

    def hover_point(self, event):
        if event.x is None or event.inaxes is None:
            QToolTip.hideText()
            return
        for plot, scene in self.artists:
            if (event.inaxes is plot.axes and len(plot.positions)
                    and plot.point_markers.get_visible()):
                distance = np.linalg.norm(plot.axes.transData.transform(plot.positions) - [event.x, event.y], axis=1)
                index = int(distance.argmin())
                if distance[index] < 12:
                    point = scene["layer"].iloc[index]
                    name = scene.get('label', scene['wafer']).replace('\n', ' · ')
                    die = str(point.get("die", "")).strip()
                    identity = f" · Die {die}" if die else ""
                    text = (f"{name}{identity} · {scene['metric']} = {point.value:.8g} · "
                            f"X = {point.x:.6g}, Y = {point.y:.6g}")
                    self.status.setText(text)
                    QToolTip.showText(QCursor.pos(), f"<span>{escape(text)}</span>", self.canvas)
                    return
                break
        QToolTip.hideText()

    def export_image(self):
        """Write the complete array as PNG (chosen quality) or as SVG / PDF vector."""
        if self.result is None or not self.artists:
            return
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
        if self.result is None or not self.artists:
            return
        _render_scale, requested = resolution_settings(self.resolution)
        dpi = export_dpi(self.figure, requested, MAX_COPY_PIXELS)
        note = f" · capped from {requested} dpi" if dpi < requested else ""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status.setText("Copying…")
        QApplication.processEvents()
        try:
            buffer = BytesIO()
            self.figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
            image = QImage.fromData(buffer.getvalue(), "PNG")
            if image.isNull():
                raise ValueError("Unable to create the PNG image.")
            QApplication.clipboard().setImage(image)
            self.status.setText(f"Copied the map grid at {dpi} dpi{note} · "
                                f"{image.width()} × {image.height()} px")
        except Exception as error:
            self.status.setText(f"Copy failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()

    def stop(self):
        self.pending_input_refresh = False
        self.input_refresh_timer.stop()
        if self.settings_timer.isActive():
            self.settings_timer.stop()
            self.persist_color_preferences()
        if self.worker is not None:
            self.worker.requestInterruption()
            self.worker.wait()
