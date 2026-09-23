"""Signed-radius scatter plots using the selections from the Data tab."""
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt6.QtGui import QImage, QKeySequence, QPainter, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
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
    def __init__(self):
        super().__init__(objectName="radiusPage")
        settings = get_settings()
        self.frame = None
        self.selection = {}
        self.signature = None
        self.ready = False
        self.base_size = (800, 600)
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
        self.summary = QLabel("R = sign(X) · √(X² + Y²)", objectName="accent")
        toolbar.addWidget(self.summary)
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
        appearance.addStretch()
        header.addLayout(appearance)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.empty = QLabel("Select measurement sets and parameters in the Data tab.", objectName="subtitle")
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
        self.copy_button.setToolTip("Copy the complete plot as PNG (Ctrl+C while this tab is active).")
        self.stack.addWidget(self.scroll)
        self.selector_panel = QWidget()
        box_layout = QVBoxLayout(self.selector_panel)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_bar = QHBoxLayout()
        box_bar.addWidget(QLabel("Drag to select plots · Ctrl to add / remove · Shift to extend", objectName="hint"))
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
        self.status = QLabel("Select measurement sets and parameters in Data, then draw.", objectName="hint")
        layout.addWidget(self.status)
        self.x_column.currentIndexChanged.connect(self.invalidate)
        self.y_column.currentIndexChanged.connect(self.invalidate)
        self.selector.changed.connect(self.invalidate)

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

    def invalidate(self, *_):
        self.ready = False
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.figure.clear()
        self.figure.text(.5, .5, "Select boxes, then click Draw selected",
                         ha="center", va="center", color="#746b7e")
        self.canvas.draw_idle()
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)
        rows, columns = len(self.selection.get("wafers", [])), len(self.selection.get("metrics", []))
        count = len(self.selector.selected_cells())
        self.status.setText(f"{count} / {rows * columns} selected  ·  {rows} × {columns}")

    def show_selector(self):
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        if not available:
            self.empty.setText("Select measurement sets and parameters in the Data tab.")
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)
        self.status.setText("Drag to select plots, then click Draw selected; unselected cells stay blank.")

    def _parts(self):
        wafers = self.selection.get("wafers", [])
        if "groups" in self.selection:
            return {key: self.frame.iloc[list(self.selection["groups"][key])] for key in wafers}
        ids = self.frame[self.selection["wafer_column"]].astype(str).str.strip()
        return {key: self.frame[ids == key] for key in wafers}

    def draw_plot(self):
        try:
            if self.frame is None or self.frame.empty:
                raise ValueError("Load or paste a table in Data first.")
            wafers, metrics = self.selection.get("wafers", []), self.selection.get("metrics", [])
            if not wafers or not metrics:
                raise ValueError("Select at least one measurement set and one parameter in Data.")
            x_name, y_name = self.x_column.currentData(), self.y_column.currentData()
            if x_name == y_name:
                raise ValueError("Choose different X and Y coordinate columns.")
            if len(wafers) * len(metrics) > 120:
                raise ValueError("Select up to 120 radius plots per array.")
            cells = self.selector.selected_cells()
            if not cells:
                raise ValueError("Select at least one plot box before drawing.")
            parts, labels = self._parts(), self.selection.get("labels", {})
            # Only the rows and columns that hold a drawn box end up on the
            # canvas, so its size follows the number of drawn plots.
            wafers, metrics = drawn_axes(wafers, metrics, cells)
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
            self.refresh_canvas()
            self.export_button.setEnabled(True)
            self.copy_button.setEnabled(True)
            self.stack.setCurrentWidget(self.scroll)
            self.status.setText(f"{drawn} / {rows * columns} radius plots drawn  ·  "
                                f"{rows} measurement rows × {columns} parameters.")
        except (ValueError, KeyError) as error:
            self.ready = False
            self.export_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.status.setText(str(error))

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
        self.canvas.setFixedSize(round(width * render_scale), round(height * render_scale))
        self.canvas.draw()
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        self.resize_canvas()

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
