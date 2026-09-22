"""Plot-tab controls, background interpolation and a scrollable Matplotlib canvas."""
from io import BytesIO
from pathlib import Path

import numpy as np
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QPainter, QShortcut
from matplotlib import colormaps

from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .array_plot import ArrayOptions, draw_array, prepare_array
from .appearance import configure_resolution_combo, resolution_settings, screen_render_scale
from .color_range_bar import ColorRangeBar
from .map_selector import MapSelector
from .plot import auto_cmap_range, display_colormap, restyle_panel_title
from .settings import get_settings

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
    def __init__(self):
        super().__init__(objectName="plotPage")
        prefs = get_settings()
        self.frame = None
        self.selection = {}
        self.signature = None
        self.dirty = True
        self.revision = 0
        self.worker = None
        self.result = None
        self.artists = []
        self.font_timer = QTimer(self, interval=120, singleShot=True)
        self.font_timer.timeout.connect(self.apply_font_style)
        self.style_timer = QTimer(self, interval=120, singleShot=True)
        self.style_timer.timeout.connect(self.apply_plot_style)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)
        header = QVBoxLayout()
        header.setSpacing(8)
        toolbar = QHBoxLayout()
        self.select_button = QPushButton("Select maps")
        self.select_button.clicked.connect(self.show_selector)
        toolbar.addWidget(self.select_button)
        self.draw_button = QPushButton("Draw selected", objectName="primary")
        self.draw_button.clicked.connect(self.draw_maps)
        self.export_button = QPushButton("Export PNG")
        self.export_button.clicked.connect(self.export_png)
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
        for title, name in (("Viridis", "viridis"), ("Turbo", "turbo"), ("Plasma", "plasma"),
                            ("Jet", "jet"), ("Coolwarm", "coolwarm"), ("Spectral", "Spectral_r")):
            self.color_map.addItem(title, name)
        self.color_map.setCurrentIndex(max(0, self.color_map.findData(prefs.get("color_map", "turbo"))))
        self.color_map.setFixedWidth(104)
        self.color_map.currentIndexChanged.connect(self.change_colormap)
        appearance.addWidget(self.color_map)
        appearance.addWidget(QLabel("Colors", objectName="muted"))
        self.color_range = ColorRangeBar()
        self.color_range.set_colormap(colormaps[self.color_map.currentData()])
        self.color_range.set_range(*auto_cmap_range(self.color_map.currentData()))
        self.color_range.changed.connect(self.queue_plot_style)
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
        self.fill_edge.setToolTip("Harmonic continuation from the measured hull to the wafer edge; this area is estimated.")
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
        self.labels.toggled.connect(self.apply_overlay_visibility)
        self.points.toggled.connect(self.apply_overlay_visibility)
        self.contour.toggled.connect(self.queue_plot_style)
        self.point_outline.toggled.connect(self.queue_plot_style)
        for control in (self.fill_edge, self.shared):
            control.toggled.connect(self.invalidate)
        for control in (self.labels, self.points, self.contour, self.point_outline, self.fill_edge, self.shared):
            options.addWidget(control)
        self.scale_bar.setToolTip("Show the color scale beside every wafer map.")
        self.scale_bar.toggled.connect(self.queue_plot_style)
        options.addWidget(self.scale_bar)
        options.addStretch()
        controls.addLayout(options)
        layout.addWidget(settings)
        self.stack = QStackedWidget()
        self.empty = QLabel("Select wafers and parameters in the Data tab.", objectName="subtitle")
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
        self.copy_button.setToolTip("Copy the complete plot as PNG (Ctrl+C while this tab is active).")
        self.stack.addWidget(self.scroll)
        self.selector_panel = QWidget()
        box_layout = QVBoxLayout(self.selector_panel)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_bar = QHBoxLayout()
        box_bar.addWidget(QLabel("Drag to select maps · Ctrl to add / remove · Shift to extend", objectName="hint"))
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
        self.selector.changed.connect(self.invalidate)
        self.diameter.currentTextChanged.connect(self.invalidate)
        self.invalidate()

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

    def show_selector(self):
        if self.worker is not None:
            self.invalidate()
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        self.empty.setText("Select wafers and parameters in the Data tab to create map boxes.")
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)
        self.status.setText("Select boxes, then click Draw selected. Unselected positions stay blank.")

    def change_colormap(self, *_):
        """Follow the palette box: show the new palette and reset to its default slice."""
        name = self.color_map.currentData()
        self.color_range.set_colormap(colormaps[name])
        self.color_range.set_range(*auto_cmap_range(name))
        self.queue_plot_style()

    def invalidate(self, *_):
        self.revision += 1
        self.dirty = True
        self.result = None
        self.artists = []
        if self.worker:
            self.worker.requestInterruption()
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.stack.setCurrentWidget(self.selector_panel)
        nr, nc = len(self.selection.get("wafers", [])), len(self.selection.get("metrics", []))
        if not nr or not nc:
            self.empty.setText("Select wafers and parameters in the Data tab to create map boxes.")
            self.stack.setCurrentWidget(self.empty)
        count = len(self.selector.selected_cells())
        self.summary.setText(f"{count} / {nr * nc} selected  ·  {nr} × {nc}")
        self.status.setText("Drag to select boxes, then click Draw selected; old results are hidden.")

    def draw_maps(self):
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
            self.invalidate()
            revision = self.revision
            self.worker = SurfaceJob(self.frame, dict(self.selection, cells=list(cells)), options, self)
            self.worker.ready.connect(lambda result: self.render_result(result) if revision == self.revision else None)
            self.worker.failed.connect(lambda message: self.show_error(message) if revision == self.revision else None)
            self.worker.progress.connect(lambda done, total: self.status.setText(f"Interpolating {done} / {total} maps…")
                                         if revision == self.revision else None)
            self.worker.finished.connect(self.finished)
            self.draw_button.setText("Cancel")
            self.stack.setCurrentIndex(0)
            self.empty.setText("Preparing wafer maps…")
            self.worker.start()
        except (ValueError, KeyError) as error:
            self.show_error(str(error))

    def show_error(self, message):
        self.result = None
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.stack.setCurrentIndex(0)
        self.empty.setText(message)
        self.status.setText("Check the data and plot settings, then draw again.")

    def finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.draw_button.setText("Draw selected")
        if self.result is None and self.empty.text() == "Preparing wafer maps…":
            self.show_selector()

    def render_result(self, result):
        try:
            self.result = result
            self.artists = draw_array(self.figure, result, int(self.font_size.currentText()))
            self.dirty = False
            self.stack.setCurrentIndex(1)
            self.refresh_canvas()
            self.export_button.setEnabled(bool(self.artists))
            self.copy_button.setEnabled(bool(self.artists))
            self.status.setText(f"{len(self.artists)} / {result['selected_count']} maps · "
                                f"{result['size_summary']} · Hover a point for its value.")
        except Exception as error:
            self.show_error(str(error))

    def refresh_canvas(self):
        """Render once at 100%; zoom later uses only the Qt view transform."""
        if self.result is None:
            return
        rows, columns = self.result["shape"]
        base_width, base_height = columns * 460, rows * 420 + 30
        requested_scale, _dpi = resolution_settings(self.resolution)
        render_scale = screen_render_scale(base_width, base_height, requested_scale)
        self.figure.set_dpi(100 * render_scale)
        self.figure.set_size_inches(base_width / 100, base_height / 100, forward=False)
        self.canvas.setFixedSize(round(base_width * render_scale), round(base_height * render_scale))
        self.canvas.draw()
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        self.resize_canvas()

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
        self.status.setText("Updating plot typography…")
        self.font_timer.start()

    def queue_plot_style(self, *_):
        """Color changes reuse prepared surfaces instead of repeating interpolation."""
        if self.result is not None and self.stack.currentWidget() is self.scroll:
            self.status.setText("Updating color style…")
            self.style_timer.start()

    def apply_plot_style(self):
        if self.result is None or self.stack.currentWidget() is not self.scroll:
            return
        cmap, show_colorbar = self.color_map.currentData(), self.scale_bar.isChecked()
        contour, point_outline = self.contour.isChecked(), self.point_outline.isChecked()
        opacity = self.opacity.currentData() / 100
        cmap_range = self.color_range.range()
        previous = self.result["settings"]
        structural_change = (show_colorbar != previous.show_colorbar or contour != previous.contour)
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
            self.canvas.draw_idle()
        name = self.color_map.currentText()
        self.status.setText(f"Color: {name} · Palette {cmap_range[0]:.0%}–{cmap_range[1]:.0%} · "
                            f"Opacity {opacity:.0%} · Contours: {'on' if contour else 'off'} · "
                            f"Scale bar: {'shown' if show_colorbar else 'hidden'}.")

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
        self.canvas.draw_idle()
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
        self.canvas.draw_idle()
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
        QTimer.singleShot(0, self.resize_canvas)

    def hover_point(self, event):
        if event.x is None or event.inaxes is None:
            return
        for plot, scene in self.artists:
            if event.inaxes is plot.axes:
                distance = np.linalg.norm(plot.axes.transData.transform(plot.positions) - [event.x, event.y], axis=1)
                index = int(distance.argmin())
                if distance[index] < 12:
                    point = scene["layer"].iloc[index]
                    name = scene.get('label', scene['wafer']).replace('\n', ' · ')
                    self.status.setText(f"{name} · {scene['metric']} = {point.value:.8g} · "
                                        f"X = {point.x:.6g}, Y = {point.y:.6g}")
                break

    def export_png(self):
        if self.result is None or not self.artists:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export wafer map array", "wafer_maps.png", "PNG (*.png)")
        if path:
            try:
                path = str(Path(path).with_suffix(".png"))
                _render_scale, dpi = resolution_settings(self.resolution)
                self.figure.savefig(path, dpi=dpi, facecolor="white")
                self.status.setText(f"Exported complete array ({dpi} dpi): {path}")
            except Exception as error:
                self.status.setText(f"Export failed: {error}")

    def copy_png(self):
        if self.result is None or not self.artists:
            return
        try:
            buffer = BytesIO()
            _render_scale, dpi = resolution_settings(self.resolution)
            self.figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
            image = QImage.fromData(buffer.getvalue(), "PNG")
            if image.isNull():
                raise ValueError("Unable to create the PNG image.")
            QApplication.clipboard().setImage(image)
            self.status.setText(f"Copied complete array as PNG ({dpi} dpi) · {image.width()} × {image.height()} px")
        except Exception as error:
            self.status.setText(f"Copy failed: {error}")

    def stop(self):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.worker.wait()
