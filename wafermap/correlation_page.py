"""Pairwise numeric scatter plots and lmfit linear regression.

The visible grid is PyQtGraph so every variable pair zooms and pans on its own;
Matplotlib stays behind the Export / Copy PNG buttons as the print backend.
"""

from dataclasses import dataclass
from html import escape
from itertools import combinations
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from lmfit.models import LinearModel
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .appearance import (MAX_COPY_PIXELS, MAX_EXPORT_PIXELS, configure_resolution_combo,
                         export_dpi, frame_plot_axes,
                         panel_title_label, resolution_settings)
from .appearance import widget_to_qimage
from .array_plot import drawn_axes
from .data import number
from .map_selector import MapSelector
from .panel_grid import PanelGrid
from .plot import set_panel_title
from .settings import get_settings


MAX_INPUT_COLUMNS = 40
MAX_VISIBLE_FITS = 12
HOME_PADDING = 0.08


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


def pairwise_linear_fits(frame, metrics, groups=None, cells=None):
    """Return valid lmfit results ordered from strongest to weakest linear fit.

    ``groups`` maps a measurement set to its row indices and ``cells`` holds the
    selected (measurement set, column) boxes. A pair is then fitted only on the
    measurement sets where **both** columns were selected, so the box grid can
    narrow a fit without mixing in rows the user did not pick.
    """
    fits, errors = [], []
    for x_name, y_name in combinations(metrics, 2):
        rows = frame
        if groups is not None and cells is not None:
            chosen = [index for key, indices in groups.items()
                      if (key, x_name) in cells and (key, y_name) in cells
                      for index in indices]
            rows = frame.iloc[chosen] if chosen else frame.iloc[0:0]
        try:
            fits.append(fit_numeric_pair(rows, x_name, y_name))
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
        self.plot_widgets = []
        self.panel_hosts = []
        self.skipped_count = 0
        self.base_size = (900, 650)
        self._pending_updates = set()
        self.home_views = []
        self.update_timer = QTimer(self, interval=180, singleShot=True)
        self.update_timer.timeout.connect(self.flush_updates)
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
        self.summary = QLabel("0 × 0", objectName="accent")
        toolbar.addWidget(self.summary)
        header.addLayout(toolbar)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("Min R²", objectName="muted"))
        self.min_rsq = QDoubleSpinBox()
        self.min_rsq.setRange(0, 1)
        self.min_rsq.setDecimals(2)
        self.min_rsq.setSingleStep(.05)
        self.min_rsq.setValue(float(settings.get("min_rsq", 0.50)))
        self.min_rsq.setFixedWidth(72)
        self.min_rsq.setToolTip("Only draw pairwise fits with R² strictly greater than this value.")
        self.min_rsq.valueChanged.connect(lambda: self.queue_update("filter"))
        options.addWidget(self.min_rsq)
        options.addWidget(QLabel("Columns", objectName="muted"))
        self.columns = QComboBox()
        self.columns.addItems(["2", "3", "4"])
        self.columns.setCurrentText("3")
        self.columns.setFixedWidth(54)
        self.columns.currentIndexChanged.connect(lambda: self.queue_update("layout"))
        options.addWidget(self.columns)
        options.addWidget(QLabel("Wheel: zoom · drag: box zoom · right-drag: pan", objectName="muted"))
        self.reset_button = QPushButton("Reset views")
        self.reset_button.setToolTip("Restore every plot to the view it had after drawing.")
        self.reset_button.clicked.connect(self.reset_views)
        options.addWidget(self.reset_button)
        options.addWidget(QLabel("Font", objectName="muted"))
        self.font_size = QComboBox()
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16"])
        self.font_size.setCurrentText(str(settings.get("font_size", 10)))
        self.font_size.setFixedWidth(58)
        self.font_size.currentIndexChanged.connect(lambda: self.queue_update("style"))
        options.addWidget(self.font_size)
        options.addWidget(QLabel("Resolution", objectName="muted"))
        self.resolution = QComboBox()
        configure_resolution_combo(self.resolution)
        self.resolution.setCurrentIndex(max(0, self.resolution.findText(settings.get("resolution", "High"))))
        self.resolution.currentIndexChanged.connect(lambda: self.queue_update("resolution"))
        options.addWidget(self.resolution)
        options.addStretch()
        header.addLayout(options)
        layout.addLayout(header)

        self.figure = Figure(figsize=(9, 6.5), dpi=100, facecolor="white")
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        FigureCanvasAgg(self.figure)
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_png)
        self.copy_button.setToolTip("Copy the complete plot as PNG (Ctrl+C while this tab is active).")
        self.plot_host = None
        self.interactive_scroll = QScrollArea()
        self.interactive_scroll.setWidgetResizable(True)
        self.interactive_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.stack = QStackedWidget()
        self.empty = QLabel("Select at least 2 numeric columns in the Data tab.", objectName="subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.interactive_scroll)
        self.selector_panel = QWidget()
        box_layout = QVBoxLayout(self.selector_panel)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_bar = QHBoxLayout()
        box_bar.addWidget(QLabel("Drag to select fits · Ctrl to add / remove · Shift to extend",
                                 objectName="hint"))
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
        self.status = QLabel("Choose numeric columns in Data, then draw.", objectName="hint")
        layout.addWidget(self.status)
        self.selector.changed.connect(self.invalidate)
        self.invalidate()

    def set_input(self, frame, selection):
        self.frame = frame
        self.selection = selection.copy()
        self.selector.set_array(selection.get("wafers", []), selection.get("metrics", []),
                                selection.get("labels"))
        self.invalidate()

    def show_selector(self):
        """Return to the box grid so another set of fits can be chosen."""
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        self.empty.setText("Select at least 2 numeric columns in the Data tab.")
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)

    def invalidate(self):
        self.update_timer.stop()
        self._pending_updates.clear()
        self.ready = False
        self.all_fits = []
        self.fits = []
        self.skipped_count = 0
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        self.figure.clear()
        self.draw_canvas_message("Choose boxes, then click Draw selected")
        self.clear_interactive("Choose boxes, then click Draw selected")
        wafers = self.selection.get("wafers", [])
        metrics = self.selection.get("metrics", [])
        rows, columns = len(wafers), len(metrics)
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        if not available:
            self.empty.setText("Select at least 2 numeric columns in the Data tab.")
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.selector_panel)
        count = len(self.selector.selected_cells())
        self.summary.setText(f"{count} / {rows * columns} selected  ·  {rows} × {columns}")
        self.status.setText("Drag to select fits, then click Draw selected.")

    def draw_canvas_message(self, message):
        """Draw a readable centered message that follows the plot font setting."""
        size = max(15, int(self.font_size.currentText()) + 3)
        return self.figure.text(.5, .5, message, ha="center", va="center",
                                color="#746b7e", fontsize=size)

    def row_groups(self):
        """Row indices of every selected measurement set, keyed by its identity."""
        wafers = self.selection.get("wafers", [])
        groups = self.selection.get("groups")
        if groups:
            return {key: list(groups.get(key, ())) for key in wafers}
        column = self.selection.get("wafer_column")
        if not column or column not in self.frame:
            return {}
        ids = self.frame[column].astype(str).str.strip()
        return {key: list(np.flatnonzero(ids == key)) for key in wafers}

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
            cells = self.selector.selected_cells()
            if not cells:
                raise ValueError("Select at least one fit box before drawing.")
            wafers = self.selection.get("wafers", [])
            drawn_wafers, drawn_metrics = drawn_axes(wafers, metrics, cells)
            if len(drawn_metrics) < 2:
                raise ValueError("Select boxes for at least 2 numeric columns.")
            groups = {key: rows for key, rows in self.row_groups().items() if key in set(drawn_wafers)}
            if not any(groups.values()):
                raise ValueError("Select at least one measurement set in Data.")
            self.cells = set(cells)
            pair_count = len(drawn_metrics) * (len(drawn_metrics) - 1) // 2
            self.status.setText(f"Fitting {pair_count} parameter pairs…")
            QApplication.processEvents()
            self.all_fits, errors = pairwise_linear_fits(self.frame, drawn_metrics, groups, cells)
            self.skipped_count = len(errors)
            if not self.all_fits:
                raise ValueError("No selected pair has enough varying numeric data for a linear fit.")
            self.drawn_metrics = list(drawn_metrics)
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
            self.draw_canvas_message(f"No pairwise fit has R² > {threshold:.2f}")
            self.clear_interactive(f"No pairwise fit has R² > {threshold:.2f}")
            self.stack.setCurrentWidget(self.interactive_scroll)
            self.status.setText(f"0 / {len(self.all_fits)} fits pass R² > {threshold:.2f}.")
            return
        self.render_fits()
        self.ready = True
        self.stack.setCurrentWidget(self.interactive_scroll)
        self.export_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        skipped = f" · {self.skipped_count} invalid pairs skipped" if self.skipped_count else ""
        limited = (f" · showing top {MAX_VISIBLE_FITS}" if len(self.fits) > MAX_VISIBLE_FITS else "")
        self.status.setText(
            f"{len(self.fits)} / {len(self.all_fits)} fits pass R² > {threshold:.2f}"
            f" · sorted high → low{limited}{skipped}"
        )

    def render_fits(self):
        """Refresh the interactive grid; the export mirror is built on demand."""
        visible_fits = self.fits[:MAX_VISIBLE_FITS]
        columns = min(int(self.columns.currentText()), len(visible_fits))
        rows = ceil(len(visible_fits) / columns)
        self.base_size = (columns * 520, rows * 390 + 30)
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        self.render_interactive(visible_fits, columns, rows)

    def build_export_figure(self):
        """Matplotlib mirror of the visible fits, used by Export / Copy PNG."""
        self._export_dirty = False
        visible_fits = self.fits[:MAX_VISIBLE_FITS]
        columns = min(int(self.columns.currentText()), len(visible_fits))
        rows = ceil(len(visible_fits) / columns)
        width, height = self.base_size
        self.figure.clear()
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
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
        grow = max(0, base - 10)
        self.figure.subplots_adjust(left=(68 + 8 * grow) / width, right=1 - (28 + 4 * grow) / width,
                                    top=1 - (72 + 8 * grow) / height, bottom=(58 + 6 * grow) / height,
                                    # Row titles need more room as the font grows.
                                    wspace=.32 + .02 * grow, hspace=.43 + .04 * grow)

    def ensure_export_figure(self):
        """Build the export mirror only when Export / Copy actually needs it."""
        if self._export_dirty or not self.figure.axes:
            self.build_export_figure()
            self.refresh_canvas()

    def clear_interactive(self, message=None):
        if self.plot_host is not None:
            self.plot_host.setParent(None)
            self.plot_host.deleteLater()
            self.plot_host = None
        self.plot_widgets = []
        self.panel_hosts = []
        self.home_views = []
        if message:
            label = QLabel(message, objectName="subtitle")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"font-size: {max(15, int(self.font_size.currentText()) + 3)}pt;")
            label.setMinimumSize(600, 360)
            self.plot_host = label
            self.interactive_scroll.setWidget(label)

    def render_interactive(self, visible_fits, columns, rows):
        """Build a resizable grid of independently zoomable PyQtGraph plots."""
        self.clear_interactive()
        base = int(self.font_size.currentText())
        panel_width, panel_height = 470, 350
        grid = PanelGrid(columns)
        grid.setMinimumSize(columns * panel_width, rows * panel_height)
        for rank, fit in enumerate(visible_fits, start=1):
            widget = pg.PlotWidget(background="w")
            widget.setMinimumSize(420, 310)
            widget.setToolTip("Mouse wheel: zoom · Left drag: box zoom · Right drag: pan · "
                              "Double-click: fit · Reset views: restore all")
            plot = widget.getPlotItem()
            plot.setTitle(None)   # the QLabel above the plot owns the heading
            plot.showGrid(x=True, y=True, alpha=.18)
            plot.setLabel("bottom", fit.x_name, color="#30343b", size=f"{max(7, base - 1)}pt")
            plot.setLabel("left", fit.y_name, color="#30343b", size=f"{max(7, base - 1)}pt")
            equation = f"y = {fit.slope:.5g}x {fit.intercept:+.5g}"
            details = f"{equation}   R² {fit.rsquared:.5f}   n {len(fit.x)}   rank {rank}"
            heading = panel_title_label(
                f"<b>{escape(fit.y_name)} vs {escape(fit.x_name)}</b><br>"
                f"<span style='font-size:{max(7, base - 1)}pt'>{escape(details)}</span>",
                base + 1)
            # A QLabel keeps every title line in its own space; pyqtgraph's own
            # title reserves one line and printed the second over the plot.
            container = QWidget()
            box = QVBoxLayout(container)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            box.addWidget(heading)
            box.addWidget(widget, 1)
            plot.addItem(pg.ScatterPlotItem(fit.x, fit.y, size=6.5,
                                            pen=pg.mkPen("#ffffff", width=.5),
                                            brush=pg.mkBrush(53, 109, 145, 165)))
            order = np.argsort(fit.x)
            plot.addItem(pg.PlotDataItem(fit.x[order], fit.predicted[order],
                                         pen=pg.mkPen("#d1495b", width=2)))
            view = plot.getViewBox()
            # Left drag selects a region to zoom into; right drag pans.
            view.setMouseMode(pg.ViewBox.RectMode)
            view.setDefaultPadding(HOME_PADDING)
            view.autoRange(padding=HOME_PADDING)
            for axis_name in ("bottom", "left"):
                axis = plot.getAxis(axis_name)
                axis.setPen(pg.mkPen("#30343b"))
                axis.setTextPen(pg.mkPen("#30343b"))
                axis.setStyle(tickFont=widget.font())
            # The export keeps ticks on all four sides; mirror that frame here.
            frame_plot_axes(plot, tick_length=3)
            grid.add_panel(container)
            self.plot_widgets.append(widget)
            self.panel_hosts.append(container)
        self.plot_host = grid
        self.interactive_scroll.setWidget(grid)
        QTimer.singleShot(0, self.remember_home_views)

    def remember_home_views(self):
        """Store the view each plot was drawn with, so Reset views can restore it exactly."""
        self.home_views = [widget.getPlotItem().getViewBox().viewRange()
                           for widget in self.plot_widgets]

    def reset_views(self):
        """Restore every plot to the exact range it was drawn with."""
        if not self.plot_widgets:
            return
        if len(self.home_views) != len(self.plot_widgets):
            for widget in self.plot_widgets:
                widget.getPlotItem().getViewBox().autoRange(padding=HOME_PADDING)
            self.remember_home_views()
        else:
            for widget, home in zip(self.plot_widgets, self.home_views):
                widget.getPlotItem().getViewBox().setRange(xRange=home[0], yRange=home[1],
                                                           padding=0)
        self.status.setText(f"Reset {len(self.plot_widgets)} interactive plot views.")

    def relayout(self, *_):
        if not self.ready:
            return
        self.render_fits()

    def restyle(self, *_):
        if not self.ready:
            for text in self.figure.texts:
                text.set_fontsize(max(15, int(self.font_size.currentText()) + 3))
            if self.all_fits:
                self.clear_interactive(f"No pairwise fit has R² > {self.min_rsq.value():.2f}")
            return
        self.render_fits()

    def refresh_canvas(self):
        if not self.ready:
            return
        width, height = self.base_size
        # The visible plots are PyQtGraph widgets. Keep only a lightweight
        # Matplotlib export model here; savefig applies the requested DPI later.
        self.figure.set_dpi(100)
        self.figure.set_size_inches(width / 100, height / 100, forward=False)

    def change_resolution(self, *_):
        if self.ready:
            _scale, dpi = resolution_settings(self.resolution)
            self.status.setText(f"PNG output resolution: {dpi} dpi. Interactive plots stay vector-sharp.")

    def export_png(self):
        if not self.ready:
            return
        self.ensure_export_figure()
        path, _ = QFileDialog.getSaveFileName(self, "Export pairwise fits", "pairwise_fits.png", "PNG (*.png)")
        if not path:
            return
        path = str(Path(path).with_suffix(".png"))
        _scale, requested = resolution_settings(self.resolution)
        dpi = export_dpi(self.figure, requested, MAX_EXPORT_PIXELS)
        note = f" · capped from {requested} dpi" if dpi < requested else ""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status.setText("Exporting…")
        QApplication.processEvents()
        try:
            self.figure.savefig(path, dpi=dpi, facecolor="white")
            shown = min(len(self.fits), MAX_VISIBLE_FITS)
            self.status.setText(f"Exported top {shown} / {len(self.fits)} ranked fits "
                                f"({dpi} dpi{note}): {path}")
        except Exception as error:
            self.status.setText(f"Export failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()

    def copy_png(self):
        if not self.ready:
            return
        _scale, requested = resolution_settings(self.resolution)
        cache_key = (requested, self.plot_host.width(), self.plot_host.height())
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status.setText("Copying…")
        QApplication.processEvents()
        try:
            if self._copy_image is None or self._copy_dpi != cache_key:
                self._copy_image, scale = widget_to_qimage(
                    self.plot_host, requested / 100, MAX_COPY_PIXELS)
                self._copy_dpi = (requested, self.plot_host.width(), self.plot_host.height())
            else:
                scale = self._copy_image.width() / max(1, self.plot_host.width())
            image = self._copy_image
            dpi = round(scale * 100)
            note = f" · capped from {requested} dpi" if dpi < requested else ""
            QApplication.clipboard().setImage(image)
            shown = min(len(self.fits), MAX_VISIBLE_FITS)
            self.status.setText(f"Copied top {shown} / {len(self.fits)} ranked fits "
                                f"({dpi} dpi{note}) · {image.width()} × {image.height()} px")
        except Exception as error:
            self.status.setText(f"Copy failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()
