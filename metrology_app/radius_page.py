"""Signed-radius scatter plots using the selections from the Data tab."""
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QPainter, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .appearance import configure_resolution_combo, resolution_settings, screen_render_scale
from .array_plot import drawn_axes
from .data import number
from .map_selector import MapSelector
from .plot import infer_wafer_geometry, restyle_panel_title, set_panel_title
from .settings import get_settings


def signed_radius(x, y):
    """R = sqrt(X² + Y²), mirrored to the negative side when X < 0."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    return np.hypot(x, y) * np.sign(x)


class RadiusPage(QWidget):
    draw_state_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__(objectName="radiusPage")
        settings = get_settings()
        self.frame = None
        self.selection = {}
        self.signature = None
        self.ready = False
        self.has_drawn_once = False
        self.pending_input_refresh = False
        self.drawn_cells = set()
        self.base_size = (800, 600)
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
            "Drag to select plots · Ctrl to add / remove · Shift to extend"
        )
        self.select_button.clicked.connect(self.show_selector)
        toolbar.addWidget(self.select_button)
        self.draw_button = QPushButton("Draw selected", objectName="primary")
        self.draw_button.clicked.connect(self.draw_plot)
        self.export_button = QPushButton("Export PNG")
        self.export_button.clicked.connect(self.export_png)
        self.copy_button = QPushButton("Copy PNG")
        self.copy_button.clicked.connect(self.copy_png)
        for control in (self.draw_button, self.export_button, self.copy_button):
            toolbar.addWidget(control)
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        toolbar.addStretch()
        header.addLayout(toolbar)
        appearance = QHBoxLayout()
        appearance.setSpacing(8)
        appearance.addWidget(QLabel("View", objectName="muted"))
        self.zoom = QComboBox()
        self.zoom.addItems(["Fit width", "50%", "75%", "100%", "125%", "150%", "200%", "250%", "300%"])
        self.zoom.currentTextChanged.connect(self.resize_canvas)
        appearance.addWidget(self.zoom)
        self.x_column, self.y_column = QComboBox(), QComboBox()
        for title, combo in (("X", self.x_column), ("Y", self.y_column)):
            appearance.addWidget(QLabel(title, objectName="muted"))
            combo.setMinimumContentsLength(8)
            appearance.addWidget(combo)
        appearance.addWidget(QLabel("Font", objectName="muted"))
        self.font_size = QComboBox()
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16"])
        self.font_size.setCurrentText(str(settings.get("font_size", 10)))
        self.font_size.setFixedWidth(58)
        self.font_size.currentTextChanged.connect(self.redraw)
        appearance.addWidget(self.font_size)
        appearance.addWidget(QLabel("Resolution", objectName="muted"))
        self.resolution = QComboBox()
        configure_resolution_combo(self.resolution)
        self.resolution.setCurrentIndex(max(0, self.resolution.findText(settings.get("resolution", "High"))))
        self.resolution.currentIndexChanged.connect(self.change_resolution)
        appearance.addWidget(self.resolution)
        appearance.addWidget(QLabel("Wafers / page", objectName="muted"))
        self.page_size = QSpinBox()
        self.page_size.setRange(1, 99)
        self.page_size.setValue(int(settings.get("map_page_size", 12)))
        self.page_size.setFixedWidth(58)
        self.page_size.setKeyboardTracking(False)
        self.page_size.setToolTip(
            "Draw one page at a time; every metric of a wafer stays on its page.")
        self.page_size.valueChanged.connect(self._page_size_changed)
        appearance.addWidget(self.page_size)
        self.page_back = QPushButton("◀", objectName="subtle")
        self.page_back.setFixedWidth(34)
        self.page_back.clicked.connect(lambda: self.change_page(-1))
        appearance.addWidget(self.page_back)
        self.page_label = QLabel("Page 1 / 1", objectName="hint")
        appearance.addWidget(self.page_label)
        self.page_next = QPushButton("▶", objectName="subtle")
        self.page_next.setFixedWidth(34)
        self.page_next.clicked.connect(lambda: self.change_page(1))
        appearance.addWidget(self.page_next)
        self.page_index = 0
        appearance.addStretch()
        header.addLayout(appearance)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.empty = QLabel(objectName="subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack.addWidget(self.empty)
        self.figure = Figure(figsize=(8, 6), dpi=100, facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
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
        self.copy_button.setToolTip("Copy the full plot grid as a PNG. Ctrl+C works while this tab is active.")
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
        self.status = QLabel(objectName="hint")
        layout.addWidget(self.status)
        self.x_column.currentIndexChanged.connect(self.invalidate)
        self.y_column.currentIndexChanged.connect(self.invalidate)
        self.selector.changed.connect(self.selector_changed)

    def draw_state(self):
        """Return the successful radius selection that can be restored later."""
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
    def populate(combo, entries, selected):
        combo.blockSignals(True)
        combo.clear()
        for text, value in entries:
            combo.addItem(text, value)
        combo.setCurrentIndex(max(0, combo.findData(selected)))
        combo.blockSignals(False)

    def set_input(self, frame, selection):
        signature = (id(frame), tuple(selection["wafers"]), tuple(selection["metrics"]), selection["wafer_column"])
        if signature == self.signature:
            return
        # Only a data change may redraw by itself. Adding or removing wafers or
        # parameters rebuilds the box grid, so the engineer picks the boxes again
        # and presses Draw selected.
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
                selected = next((names[a] for a in aliases if a in names), None)
                self.populate(combo, entries, selected)
        self.selector.set_array(selection["wafers"], selection["metrics"], selection.get("labels"))
        self.invalidate()
        if (self.has_drawn_once and not grid_changed
                and not self.selector.pending_draw
                and set(self.selector.selected_cells()) == set(self.drawn_cells)):
            # Auto redraw only replays the last successful draw; a pending box
            # selection waits for the engineer to press Draw selected.
            self.queue_input_refresh()

    def invalidate(self, *_):
        self.ready = False
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.figure.clear()
        self.canvas.draw_idle()
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)
        rows, columns = len(self.selection.get("wafers", [])), len(self.selection.get("metrics", []))
        count = len(self.selector.selected_cells())
        self.status.setText(
            f"{count} / {rows * columns} selected  ·  {rows} × {columns}"
        )

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
        self.page_index = max(0, self.page_index + delta)
        if self.selector.selected_cells():
            self.draw_plot()

    def _page_size_changed(self, *_args):
        self.page_index = 0
        if self.has_drawn_once and self.selector.selected_cells():
            self.draw_plot()

    def _update_page_controls(self, index, pages):
        self.page_label.setText(f"Page {index + 1} / {pages}")
        self.page_back.setEnabled(index > 0)
        self.page_next.setEnabled(index < pages - 1)

    def queue_input_refresh(self):
        if not self.selector.selected_cells():
            self.pending_input_refresh = False
            self.input_refresh_timer.stop()
            return
        self.pending_input_refresh = True
        self.input_refresh_timer.start()

    def show_selector(self):
        self.pending_input_refresh = False
        self.input_refresh_timer.stop()
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        if not available:
            self.empty.clear()
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)

    def _parts(self):
        wafers = self.selection.get("wafers", [])
        if "groups" in self.selection:
            return {key: self.frame.iloc[list(self.selection["groups"][key])] for key in wafers}
        ids = self.frame[self.selection["wafer_column"]].astype(str).str.strip()
        return {key: self.frame[ids == key] for key in wafers}

    def draw_plot(self):
        self.pending_input_refresh = False
        self.input_refresh_timer.stop()
        try:
            if self.frame is None or self.frame.empty:
                raise ValueError("Load or paste a table in Data first.")
            wafers, metrics = self.selection.get("wafers", []), self.selection.get("metrics", [])
            if not wafers or not metrics:
                raise ValueError("Select at least one measurement set and one parameter in Data.")
            x_name, y_name = self.x_column.currentData(), self.y_column.currentData()
            if x_name == y_name:
                raise ValueError("Choose different X and Y coordinate columns.")
            cells = self.selector.selected_cells()
            if not cells:
                raise ValueError("Select at least one plot box before drawing.")
            parts, labels = self._parts(), self.selection.get("labels", {})
            # Only the rows and columns that hold a drawn box end up on the
            # canvas, so its size follows the number of drawn plots.
            wafers, metrics = drawn_axes(wafers, metrics, cells)
            wafers, page_index, pages = self.paginate_wafers(wafers)
            self._update_page_controls(page_index, pages)
            if len(wafers) * len(metrics) > 120:
                raise ValueError("Select up to 120 radius plots per page.")
            columns, rows = len(metrics), len(wafers)
            self.figure.clear()
            axes = self.figure.subplots(rows, columns, squeeze=False)
            base = int(self.font_size.currentText())
            colors = [f"C{index % 10}" for index in range(len(wafers))]
            unit = "mm" if all("mm" in name.lower() for name in (x_name, y_name)) else "coordinate units"
            drawn = 0
            for row, (color, wafer) in enumerate(zip(colors, wafers)):
                name = labels.get(wafer, wafer).replace("\n", " · ")
                for column, metric in enumerate(metrics):
                    ax = axes[row, column]
                    if (wafer, metric) not in cells:
                        ax.set_axis_off()
                        continue
                    drawn += 1
                    part = parts[wafer]
                    data = pd.DataFrame({"x": number(part[x_name]), "y": number(part[y_name]),
                                         "value": number(part[metric])}).dropna()
                    if data.empty:
                        ax.text(.5, .5, "No valid samples", ha="center", va="center", transform=ax.transAxes)
                        ax.set(xticks=[], yticks=[])
                        continue
                    radius = signed_radius(data.x.to_numpy(), data.y.to_numpy())
                    ax.scatter(radius, data.value, s=16, alpha=.78, color=color,
                               edgecolors="white", linewidths=.25)
                    _, standard = infer_wafer_geometry(data[["x", "y"]].to_numpy(), (x_name, y_name))
                    limit = standard / 2 if standard else max(float(np.abs(radius).max()) * 1.05, 1)
                    stats = f"Min {data.value.min():.5g}   Max {data.value.max():.5g}   Mean {data.value.mean():.5g}"
                    ax.axvline(0, color="#707070", linewidth=.7, zorder=0)
                    ax.set_xlim(-limit, limit)
                    set_panel_title(ax, metric, name, stats, base)
                    ax.set_xlabel(f"Signed radius ({unit})", fontsize=max(6, base - 1))
                    ax.set_ylabel(metric, fontsize=max(6, base - 1))
                    ax.tick_params(direction="out", top=True, right=True, labelsize=max(5, base - 2))
                    for spine in ax.spines.values():
                        spine.set_color("#303030")
            width, height = columns * 460, rows * 370 + 30
            grow = max(0, base - 10)
            self.figure.subplots_adjust(left=(60 + 7 * grow) / width, right=1 - (30 + 4 * grow) / width,
                                        top=1 - (75 + 8 * grow) / height, bottom=(55 + 6 * grow) / height,
                                        # Row titles need more room as the font grows.
                                        wspace=.32 + .02 * grow, hspace=.48 + .055 * grow)
            self.base_size = width, height
            self.ready = True
            self.has_drawn_once = True
            self.drawn_cells = set(cells)
            self.selector.pending_draw = False
            self.draw_state_changed.emit(self.draw_state())
            self.refresh_canvas()
            self.export_button.setEnabled(True)
            self.copy_button.setEnabled(True)
            self.stack.setCurrentWidget(self.scroll)
            self.status.setText(f"{drawn} / {rows * columns} radius plots drawn · "
                                f"Page {page_index + 1} / {pages} · "
                                f"{rows} measurement rows × {columns} parameters.")
        except (ValueError, KeyError) as error:
            self.ready = False
            self.export_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.status.setText(str(error))

    def refresh_previous_selection(self):
        if not self.pending_input_refresh:
            return
        # A data refresh redraws the radius plots in place: keep the zoom and
        # the scroll offset the engineer was reading.
        zoom = self.zoom.currentText()
        horizontal = self.scroll.horizontalScrollBar().value()
        vertical = self.scroll.verticalScrollBar().value()
        self.draw_plot()
        self.restore_canvas_view(zoom, horizontal, vertical)

    def restore_canvas_view(self, zoom, horizontal, vertical):
        def settle():
            try:
                if self.zoom.currentText() != zoom:
                    self.zoom.setCurrentText(zoom)
                self.scroll.horizontalScrollBar().setValue(
                    min(horizontal, self.scroll.horizontalScrollBar().maximum())
                )
                self.scroll.verticalScrollBar().setValue(
                    min(vertical, self.scroll.verticalScrollBar().maximum())
                )
            except RuntimeError:
                # The page was closed before the deferred pass ran.
                return

        QTimer.singleShot(0, settle)

    def stop(self):
        self.pending_input_refresh = False
        self.input_refresh_timer.stop()

    def redraw(self, *_):
        if self.ready:
            base = int(self.font_size.currentText())
            for ax in self.figure.axes:
                restyle_panel_title(ax, base)
                ax.xaxis.label.set_fontsize(max(6, base - 1))
                ax.yaxis.label.set_fontsize(max(6, base - 1))
                ax.tick_params(labelsize=max(5, base - 2))
            self.canvas.draw_idle()
            QTimer.singleShot(0, self.center_canvas)

    def refresh_canvas(self):
        if not self.ready:
            return
        width, height = self.base_size
        requested_scale, _dpi = resolution_settings(self.resolution)
        render_scale = screen_render_scale(width, height, requested_scale)
        self.figure.set_dpi(100 * render_scale)
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        size = (round(width * render_scale), round(height * render_scale))
        self._canvas_resized = size != (self.canvas.width(), self.canvas.height())
        self.canvas.setFixedSize(*size)
        self.canvas.draw()
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        self.resize_canvas()
        # Settle once Qt has processed the canvas resize, so the first frame
        # never shows the squeezed stale transform until a zoom fixes it.
        QTimer.singleShot(0, self.settle_canvas)

    def settle_canvas(self):
        if not self.ready:
            return
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        if getattr(self, "_canvas_resized", False):
            self._canvas_resized = False
            self.resize_canvas()
        self.scroll.viewport().update()

    def resize_canvas(self, *_):
        if not self.ready:
            return
        width, _height = self.base_size
        text = self.zoom.currentText()
        display_scale = min(1, max(280, self.scroll.viewport().width() - 20) / width) if text == "Fit width" else int(text[:-1]) / 100
        display_scale = max(.65, display_scale)
        render_scale = self.figure.dpi / 100
        self.scroll.resetTransform()
        self.scroll.scale(display_scale / render_scale, display_scale / render_scale)
        QTimer.singleShot(0, self.center_canvas)

    def center_canvas(self):
        """Center the plot array horizontally without changing the visible row."""
        if not self.ready:
            return
        viewport_center = self.scroll.mapToScene(self.scroll.viewport().rect().center())
        canvas_center = self.canvas_proxy.sceneBoundingRect().center()
        self.scroll.centerOn(canvas_center.x(), viewport_center.y())

    def change_resolution(self, *_):
        if not self.ready:
            return
        render_scale, dpi = resolution_settings(self.resolution)
        self.status.setText(f"Rendering at {render_scale:.0%} · PNG output {dpi} dpi…")
        self.refresh_canvas()
        self.status.setText(f"Resolution: {self.resolution.currentText()} · PNG output {dpi} dpi.")

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and self.ready:
            delta = event.angleDelta()
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                amount = delta.y() or event.pixelDelta().y()
                self.zoom_by_wheel(amount, watched, event.position().toPoint())
            else:
                horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or abs(delta.x()) > abs(delta.y())
                bar = self.scroll.horizontalScrollBar() if horizontal else self.scroll.verticalScrollBar()
                amount = delta.x() if abs(delta.x()) > abs(delta.y()) else delta.y()
                if not amount:
                    pixels = event.pixelDelta()
                    amount = pixels.x() if horizontal else pixels.y()
                bar.setValue(bar.value() - round(np.sign(amount) * max(bar.singleStep() * 3, 36)))
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def zoom_by_wheel(self, delta, watched=None, position=None):
        if not delta or not self.ready:
            return
        render_scale = self.figure.dpi / 100
        current = round(100 * self.scroll.transform().m11() * render_scale)
        steps = [50, 75, 100, 125, 150, 200, 250, 300]
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

    def export_png(self):
        if not self.ready:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export radius plot", "radius_plot.png", "PNG (*.png)")
        if path:
            path = str(Path(path).with_suffix(".png"))
            _render_scale, dpi = resolution_settings(self.resolution)
            self.figure.savefig(path, dpi=dpi, facecolor="white")
            self.status.setText(f"Exported ({dpi} dpi): {path}")

    def copy_png(self):
        if not self.ready:
            return
        buffer = BytesIO()
        _render_scale, dpi = resolution_settings(self.resolution)
        self.figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        image = QImage.fromData(buffer.getvalue(), "PNG")
        QApplication.clipboard().setImage(image)
        self.status.setText(f"Copied radius plot ({dpi} dpi) · {image.width()} × {image.height()} px")
