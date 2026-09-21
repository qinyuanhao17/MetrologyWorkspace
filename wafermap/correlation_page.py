"""Pairwise numeric scatter plots and lmfit linear regression."""

from dataclasses import dataclass
from io import BytesIO
from itertools import combinations
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
from lmfit.models import LinearModel
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .appearance import configure_resolution_combo, resolution_settings, screen_render_scale
from .data import number
from .plot import restyle_panel_title, set_panel_title
from .settings import get_settings


MAX_INPUT_COLUMNS = 40
MAX_VISIBLE_FITS = 12
MAX_SCREEN_PIXELS = 6_000_000


@dataclass(slots=True)
class LinearFit:
    x_name: str
    y_name: str
    x: np.ndarray
    y: np.ndarray
    predicted: np.ndarray
    slope: float
    intercept: float
    rsquared: float


def fit_numeric_pair(frame, x_name, y_name):
    """Fit y = slope*x + intercept with lmfit after paired numeric cleanup."""
    data = pd.DataFrame({"x": number(frame[x_name]), "y": number(frame[y_name])})
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 3:
        raise ValueError("fewer than 3 paired numeric points")
    x, y = data.x.to_numpy(float), data.y.to_numpy(float)
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        raise ValueError("constant data cannot be fitted")
    model = LinearModel()
    result = model.fit(y, model.guess(y, x=x), x=x)
    predicted = np.asarray(result.best_fit, dtype=float)
    residual = float(np.square(y - predicted).sum())
    total = float(np.square(y - y.mean()).sum())
    rsquared = 1 - residual / total if total > 0 else float("nan")
    return LinearFit(x_name, y_name, x, y, predicted,
                     float(result.params["slope"].value),
                     float(result.params["intercept"].value), rsquared)


def pairwise_linear_fits(frame, metrics):
    """Return valid lmfit results ordered from strongest to weakest linear fit."""
    fits, errors = [], []
    for x_name, y_name in combinations(metrics, 2):
        try:
            fits.append(fit_numeric_pair(frame, x_name, y_name))
        except ValueError as error:
            errors.append((x_name, y_name, str(error)))
    fits.sort(key=lambda fit: fit.rsquared if np.isfinite(fit.rsquared) else -np.inf, reverse=True)
    return fits, errors


class CorrelationPage(QWidget):
    def __init__(self):
        super().__init__(objectName="correlationPage")
        settings = get_settings()
        self.frame = pd.DataFrame()
        self.selection = {}
        self.ready = False
        self.all_fits = []
        self.fits = []
        self.skipped_count = 0
        self.base_size = (900, 650)
        self._pending_updates = set()
        self.update_timer = QTimer(self, interval=180, singleShot=True)
        self.update_timer.timeout.connect(self.flush_updates)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        self.draw_button = QPushButton("Draw pairwise fits", objectName="primary")
        self.draw_button.clicked.connect(self.draw_plot)
        self.export_button = QPushButton("Export PNG")
        self.export_button.clicked.connect(self.export_png)
        self.copy_button = QPushButton("Copy PNG")
        self.copy_button.clicked.connect(self.copy_png)
        for control in (self.draw_button, self.export_button, self.copy_button):
            toolbar.addWidget(control)
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        toolbar.addSpacing(10)
        toolbar.addWidget(QLabel("Min R²", objectName="muted"))
        self.min_rsq = QDoubleSpinBox()
        self.min_rsq.setRange(0, 1)
        self.min_rsq.setDecimals(2)
        self.min_rsq.setSingleStep(.05)
        self.min_rsq.setValue(float(settings.get("min_rsq", 0.50)))
        self.min_rsq.setFixedWidth(72)
        self.min_rsq.setToolTip("Only draw pairwise fits with R² strictly greater than this value.")
        self.min_rsq.valueChanged.connect(lambda: self.queue_update("filter"))
        toolbar.addWidget(self.min_rsq)
        toolbar.addWidget(QLabel("Columns", objectName="muted"))
        self.columns = QComboBox()
        self.columns.addItems(["2", "3", "4"])
        self.columns.setCurrentText("3")
        self.columns.setFixedWidth(54)
        self.columns.currentIndexChanged.connect(lambda: self.queue_update("layout"))
        toolbar.addWidget(self.columns)
        toolbar.addWidget(QLabel("View", objectName="muted"))
        self.zoom = QComboBox()
        self.zoom.addItems(["Fit width", "50%", "75%", "100%", "125%", "150%", "200%", "250%", "300%"])
        self.zoom.currentTextChanged.connect(self.resize_canvas)
        toolbar.addWidget(self.zoom)
        toolbar.addWidget(QLabel("Font", objectName="muted"))
        self.font_size = QComboBox()
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16"])
        self.font_size.setCurrentText(str(settings.get("font_size", 10)))
        self.font_size.setFixedWidth(58)
        self.font_size.currentIndexChanged.connect(lambda: self.queue_update("style"))
        toolbar.addWidget(self.font_size)
        toolbar.addWidget(QLabel("Resolution", objectName="muted"))
        self.resolution = QComboBox()
        configure_resolution_combo(self.resolution)
        self.resolution.setCurrentIndex(max(0, self.resolution.findText(settings.get("resolution", "High"))))
        self.resolution.currentIndexChanged.connect(lambda: self.queue_update("resolution"))
        toolbar.addWidget(self.resolution)
        toolbar.addStretch()
        self.summary = QLabel("Select at least 2 numeric columns", objectName="accent")
        toolbar.addWidget(self.summary)
        layout.addLayout(toolbar)

        self.figure = Figure(figsize=(9, 6.5), dpi=100, facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.scene = QGraphicsScene(self)
        self.canvas_proxy = self.scene.addWidget(self.canvas)
        self.scroll = QGraphicsView(self.scene)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.canvas.installEventFilter(self)
        self.scroll.viewport().installEventFilter(self)
        layout.addWidget(self.scroll, 1)
        self.status = QLabel("Choose numeric columns in Data, then draw.", objectName="hint")
        layout.addWidget(self.status)
        self.invalidate()

    def set_input(self, frame, selection):
        self.frame = frame
        self.selection = selection.copy()
        count = len(selection.get("metrics", []))
        pairs = count * (count - 1) // 2
        self.summary.setText(f"{count} columns · {pairs} pairs")
        self.invalidate()

    def invalidate(self):
        self.update_timer.stop()
        self._pending_updates.clear()
        self.ready = False
        self.all_fits = []
        self.fits = []
        self.skipped_count = 0
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.figure.clear()
        self.figure.text(.5, .5, "Choose at least 2 numeric columns and click Draw pairwise fits",
                         ha="center", va="center", color="#746b7e")
        self.canvas.draw_idle()

    def selected_rows(self):
        wafers = self.selection.get("wafers", [])
        groups = self.selection.get("groups", {})
        rows = sorted({row for key in wafers for row in groups.get(key, ())})
        return self.frame.iloc[rows] if rows else self.frame.iloc[0:0]

    def draw_plot(self):
        self.update_timer.stop()
        self._pending_updates.clear()
        self.draw_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            metrics = self.selection.get("metrics", [])
            if len(metrics) < 2:
                raise ValueError("Select at least 2 numeric columns in Data.")
            if len(metrics) > MAX_INPUT_COLUMNS:
                raise ValueError(
                    f"Select up to {MAX_INPUT_COLUMNS} numeric columns "
                    f"({MAX_INPUT_COLUMNS * (MAX_INPUT_COLUMNS - 1) // 2} pairwise fits)."
                )
            rows = self.selected_rows()
            if rows.empty:
                raise ValueError("Select at least one measurement set in Data.")
            pair_count = len(metrics) * (len(metrics) - 1) // 2
            self.status.setText(f"Fitting {pair_count} parameter pairs…")
            QApplication.processEvents()
            self.all_fits, errors = pairwise_linear_fits(rows, metrics)
            self.skipped_count = len(errors)
            if not self.all_fits:
                raise ValueError("No column pair has enough varying numeric data for a linear fit.")
            self.apply_rsq_filter()
        except (ValueError, KeyError) as error:
            self.invalidate()
            self.status.setText(str(error))
        finally:
            QApplication.restoreOverrideCursor()
            self.draw_button.setEnabled(True)

    def queue_update(self, kind):
        """Merge rapid toolbar edits into one redraw after the user pauses."""
        if not self.all_fits:
            return
        self._pending_updates.add(kind)
        self.update_timer.start()

    def flush_updates(self):
        updates = self._pending_updates
        self._pending_updates = set()
        if not updates or not self.all_fits:
            return
        if "filter" in updates:
            self.apply_rsq_filter()
            return
        if "layout" in updates:
            self.relayout()
            return
        if "style" in updates:
            self.restyle()
        if "resolution" in updates:
            self.change_resolution()

    def apply_rsq_filter(self, *_):
        """Filter already-computed models without running lmfit again."""
        if not self.all_fits:
            return
        threshold = self.min_rsq.value()
        self.fits = [fit for fit in self.all_fits if fit.rsquared > threshold]
        if not self.fits:
            self.ready = False
            self.export_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.figure.clear()
            self.figure.text(.5, .5, f"No pairwise fit has R² > {threshold:.2f}",
                             ha="center", va="center", color="#746b7e")
            self.canvas.draw_idle()
            self.status.setText(f"0 / {len(self.all_fits)} fits pass R² > {threshold:.2f}.")
            return
        self.render_fits()
        self.ready = True
        self.export_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self.refresh_canvas()
        skipped = f" · {self.skipped_count} invalid pairs skipped" if self.skipped_count else ""
        limited = (f" · showing top {MAX_VISIBLE_FITS}" if len(self.fits) > MAX_VISIBLE_FITS else "")
        self.status.setText(
            f"{len(self.fits)} / {len(self.all_fits)} fits pass R² > {threshold:.2f}"
            f" · sorted high → low{limited}{skipped}"
        )

    def render_fits(self):
        self.figure.clear()
        visible_fits = self.fits[:MAX_VISIBLE_FITS]
        columns = min(int(self.columns.currentText()), len(visible_fits))
        rows = ceil(len(visible_fits) / columns)
        axes = self.figure.subplots(rows, columns, squeeze=False)
        base = int(self.font_size.currentText())
        label_size, tick_size = max(6, base - 1), max(5, base - 2)
        for rank, (ax, fit) in enumerate(zip(axes.flat, visible_fits), start=1):
            ax.scatter(fit.x, fit.y, s=15, alpha=.58, color="#356d91",
                       edgecolors="white", linewidths=.25, rasterized=True)
            order = np.argsort(fit.x)
            ax.plot(fit.x[order], fit.predicted[order], color="#d1495b", linewidth=1.5)
            equation = f"y = {fit.slope:.5g}x {fit.intercept:+.5g}"
            stats = f"R² {fit.rsquared:.5f}   n {len(fit.x)}   rank {rank}"
            set_panel_title(ax, f"{fit.y_name} vs {fit.x_name}", equation, stats, base)
            ax.set_xlabel(fit.x_name, fontsize=label_size)
            ax.set_ylabel(fit.y_name, fontsize=label_size)
            ax.tick_params(direction="out", top=True, right=True, labelsize=tick_size, length=3)
            ax.grid(True, color="#d8dde3", linewidth=.45, alpha=.65)
            for spine in ax.spines.values():
                spine.set_color("#303030")
        for ax in axes.flat[len(visible_fits):]:
            ax.set_axis_off()
        width, height = columns * 520, rows * 390 + 30
        grow = max(0, base - 10)
        self.figure.subplots_adjust(left=(68 + 8 * grow) / width, right=1 - (28 + 4 * grow) / width,
                                    top=1 - (72 + 8 * grow) / height, bottom=(58 + 6 * grow) / height,
                                    wspace=.32, hspace=.43)
        self.base_size = (width, height)

    def relayout(self, *_):
        if not self.ready:
            return
        self.render_fits()
        self.refresh_canvas()

    def restyle(self, *_):
        if not self.ready:
            return
        base = int(self.font_size.currentText())
        for ax in self.figure.axes:
            restyle_panel_title(ax, base)
            ax.xaxis.label.set_fontsize(max(6, base - 1))
            ax.yaxis.label.set_fontsize(max(6, base - 1))
            ax.tick_params(labelsize=max(5, base - 2))
        self.canvas.draw_idle()

    def refresh_canvas(self):
        if not self.ready:
            return
        width, height = self.base_size
        render_scale, _dpi = resolution_settings(self.resolution)
        # Large correlation arrays can otherwise allocate hundreds of MB at
        # High/Ultra. Export still uses the selected full PNG resolution.
        safe_scale = screen_render_scale(width, height, render_scale, MAX_SCREEN_PIXELS)
        self.figure.set_dpi(100 * safe_scale)
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        self.canvas.setFixedSize(round(width * safe_scale), round(height * safe_scale))
        self.canvas.draw()
        self.scene.setSceneRect(self.canvas_proxy.boundingRect())
        self.resize_canvas()

    def resize_canvas(self, *_):
        if not self.ready:
            return
        width, _height = self.base_size
        text = self.zoom.currentText()
        display = min(1, max(280, self.scroll.viewport().width() - 20) / width) if text == "Fit width" else int(text[:-1]) / 100
        render_scale = self.figure.dpi / 100
        self.scroll.resetTransform()
        self.scroll.scale(max(.5, display) / render_scale, max(.5, display) / render_scale)

    def change_resolution(self, *_):
        if self.ready:
            self.refresh_canvas()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and self.ready:
            delta = event.angleDelta()
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.zoom_by_wheel(delta.y() or event.pixelDelta().y(), watched, event.position().toPoint())
            else:
                horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or abs(delta.x()) > abs(delta.y())
                bar = self.scroll.horizontalScrollBar() if horizontal else self.scroll.verticalScrollBar()
                amount = delta.x() if abs(delta.x()) > abs(delta.y()) else delta.y()
                if not amount:
                    pixel = event.pixelDelta()
                    amount = pixel.x() if horizontal else pixel.y()
                bar.setValue(bar.value() - round(np.sign(amount) * max(bar.singleStep() * 3, 36)))
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def zoom_by_wheel(self, delta, watched=None, position=None):
        if not delta or not self.ready:
            return
        render_scale, _dpi = resolution_settings(self.resolution)
        current = round(100 * self.scroll.transform().m11() * render_scale)
        steps = [50, 75, 100, 125, 150, 200, 250, 300]
        target = next((v for v in steps if v > current), steps[-1]) if delta > 0 else \
                 next((v for v in reversed(steps) if v < current), steps[0])
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
        path, _ = QFileDialog.getSaveFileName(self, "Export pairwise fits", "pairwise_fits.png", "PNG (*.png)")
        if path:
            path = str(Path(path).with_suffix(".png"))
            _scale, dpi = resolution_settings(self.resolution)
            self.figure.savefig(path, dpi=dpi, facecolor="white")
            shown = min(len(self.fits), MAX_VISIBLE_FITS)
            self.status.setText(f"Exported top {shown} / {len(self.fits)} ranked fits ({dpi} dpi): {path}")

    def copy_png(self):
        if not self.ready:
            return
        buffer = BytesIO()
        _scale, dpi = resolution_settings(self.resolution)
        self.figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        image = QImage.fromData(buffer.getvalue(), "PNG")
        if image.isNull():
            self.status.setText("Unable to create the PNG image.")
            return
        QApplication.clipboard().setImage(image)
        shown = min(len(self.fits), MAX_VISIBLE_FITS)
        self.status.setText(f"Copied top {shown} / {len(self.fits)} ranked fits ({dpi} dpi) · "
                            f"{image.width()} × {image.height()} px")
