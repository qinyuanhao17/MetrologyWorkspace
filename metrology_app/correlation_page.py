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
                         export_dpi, panel_title_label, resolution_settings)
from .appearance import widget_to_qimage
from .array_plot import drawn_axes
from .data import number
from .map_selector import MapSelector
from .plot import set_panel_title
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel
from .settings import get_settings


MAX_INPUT_COLUMNS = 40
DEFAULT_PAGE_SIZE = 12
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


@dataclass(slots=True)
class SourceFit:
    name: str
    color: str
    fit: LinearFit


@dataclass(slots=True)
class SourcePairFit:
    x_name: str
    y_name: str
    sources: tuple[SourceFit, ...]

    @property
    def rsquared(self):
        return max(source.fit.rsquared for source in self.sources)


def fit_numeric_pair(frame, x_name, y_name):
    """Fit y = slope*x + intercept with lmfit after paired numeric cleanup."""
    x = number(frame[x_name]).to_numpy(float)
    y = number(frame[y_name]).to_numpy(float)
    return _fit_numeric_values(x, y, x_name, y_name)


def _fit_numeric_values(x, y, x_name, y_name, model=None):
    """Fit already-converted arrays while preserving the public frame seam."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    paired = np.isfinite(x) & np.isfinite(y)
    x, y = x[paired], y[paired]
    if len(x) < 3:
        raise ValueError("fewer than 3 paired numeric points")
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        raise ValueError("constant data cannot be fitted")
    model = model or LinearModel()
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
    # Converting a 40-column selection inside every one of its 780 pair loops
    # repeats the same pandas parsing 39 times per column. Convert each column
    # once and keep row selection positional, matching the workspace's stable
    # source-row mapping.
    numeric = {name: number(frame[name]).to_numpy(float) for name in metrics}
    model = LinearModel()
    row_cache = {}
    for x_name, y_name in combinations(metrics, 2):
        positions = None
        if groups is not None and cells is not None:
            selected_keys = tuple(key for key in groups
                                  if (key, x_name) in cells and (key, y_name) in cells)
            if selected_keys not in row_cache:
                row_cache[selected_keys] = np.asarray(
                    [index for key in selected_keys for index in groups[key]], dtype=int)
            positions = row_cache[selected_keys]
        x = numeric[x_name] if positions is None else numeric[x_name][positions]
        y = numeric[y_name] if positions is None else numeric[y_name][positions]
        try:
            fits.append(_fit_numeric_values(x, y, x_name, y_name, model))
        except ValueError as error:
            errors.append((x_name, y_name, str(error)))
    fits.sort(key=lambda fit: fit.rsquared if np.isfinite(fit.rsquared) else -np.inf, reverse=True)
    return fits, errors


def source_pairwise_linear_fits(frame, metrics, sources, groups, cells):
    """Fit parameter pairs as source-ordered panels.

    Keeping one source per panel makes the Reference-first/Raw-second contract
    explicit and avoids visually implying that the two populations share one
    regression model.
    """
    numeric = {name: number(frame[name]).to_numpy(float) for name in metrics}
    model = LinearModel()
    panels, errors = [], []
    for source in sources:
        source_panels = []
        for x_name, y_name in combinations(metrics, 2):
            selected_rows = {
                row
                for key, rows in groups.items()
                if (key, x_name) in cells and (key, y_name) in cells
                for row in rows
            }
            positions = np.asarray(
                [row for row in source["rows"] if row in selected_rows],
                dtype=int,
            )
            try:
                fit = _fit_numeric_values(
                    numeric[x_name][positions], numeric[y_name][positions],
                    x_name, y_name, model,
                )
            except ValueError as error:
                errors.append((source["name"], x_name, y_name, str(error)))
                continue
            source_panels.append(SourcePairFit(
                x_name, y_name,
                (SourceFit(source["name"], source["color"], fit),),
            ))
        source_panels.sort(key=lambda panel: panel.rsquared, reverse=True)
        panels.extend(source_panels)
    return panels, errors


class CorrelationPage(QWidget):
    def __init__(self):
        super().__init__(objectName="correlationPage")
        settings = get_settings()
        self.frame = pd.DataFrame()
        self.selection = {}
        self.ready = False
        self.has_drawn_once = False
        self.drawn_cells = set()
        self.all_fits = []
        self.fits = []
        self.page_index = 0
        self.user_page = 0
        self.page_intent = "selector"
        self.plot_widgets = []
        self.panel_hosts = []
        self.skipped_count = 0
        self.base_size = (900, 650)
        self._pending_updates = set()
        self.home_views = []
        self.update_timer = QTimer(self, interval=180, singleShot=True)
        self.update_timer.timeout.connect(self.flush_updates)
        self.input_refresh_timer = QTimer(self, interval=180, singleShot=True)
        self.input_refresh_timer.timeout.connect(self.refresh_previous_selection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(8)
        toolbar = QHBoxLayout()
        self.select_button = QPushButton("Select maps")
        self.select_button.setToolTip(
            "Drag to select fits · Ctrl to add / remove · Shift to extend"
        )
        self.select_button.clicked.connect(self.show_selector)
        toolbar.addWidget(self.select_button)
        self.draw_button = QPushButton("Draw selected", objectName="primary")
        self.draw_button.clicked.connect(self.start_draw)
        self.export_button = QPushButton("Export page")
        self.export_button.clicked.connect(self.export_png)
        self.export_all_button = QPushButton("Export all")
        self.export_all_button.clicked.connect(self.export_all_pages)
        self.copy_button = QPushButton("Copy PNG")
        self.copy_button.clicked.connect(self.copy_png)
        for control in (
            self.draw_button, self.export_button, self.export_all_button,
            self.copy_button,
        ):
            toolbar.addWidget(control)
        self.export_button.setEnabled(False)
        self.export_all_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.export_button.setToolTip("Export the currently visible correlation page as PNG.")
        self.export_all_button.setToolTip(
            "Export every passing fit as numbered page PNG files."
        )
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
        self.reset_button = QPushButton("Reset views")
        self.reset_button.setToolTip(
            "Ctrl+scroll to zoom · Drag a box to zoom · Right-drag to pan.\n"
            "Ordinary scrolling moves the page.\n"
            "Reset returns every plot to its original range."
        )
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
        self.copy_button.setToolTip(
            "Copy the current page as a PNG. Ctrl+C works while this tab is active."
        )
        self.plot_host = None
        self.interactive_scroll = QScrollArea()
        self.interactive_scroll.setWidgetResizable(True)
        self.interactive_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.stack = QStackedWidget()
        self.empty = QLabel(objectName="subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.interactive_scroll)
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
        footer = QHBoxLayout()
        self.status = QLabel(objectName="hint")
        footer.addWidget(self.status, 1)
        footer.addWidget(QLabel("Per page", objectName="muted"))
        self.page_size = QComboBox()
        self.page_size.addItems(["6", "12", "24"])
        self.page_size.setCurrentText(str(DEFAULT_PAGE_SIZE))
        self.page_size.setFixedWidth(58)
        self.page_size.setToolTip("Number of ranked correlation fits shown on each page.")
        self.page_size.currentIndexChanged.connect(self.change_page_size)
        footer.addWidget(self.page_size)
        self.previous_page = QPushButton("Previous", objectName="subtle")
        self.previous_page.clicked.connect(lambda: self.set_page(self.page_index - 1))
        footer.addWidget(self.previous_page)
        self.page_label = QLabel("Page 0 / 0", objectName="muted")
        self.page_label.setMinimumWidth(76)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.addWidget(self.page_label)
        self.next_page = QPushButton("Next", objectName="subtle")
        self.next_page.clicked.connect(lambda: self.set_page(self.page_index + 1))
        footer.addWidget(self.next_page)
        layout.addLayout(footer)
        self.selector.changed.connect(self.selector_changed)
        self.invalidate()

    def draw_state(self):
        """Return the last successful fit-box selection for WKB persistence."""
        cells = self.selector.selected_cells() if self.has_drawn_once else set()
        return {
            "enabled": self.has_drawn_once,
            "cells": tuple(sorted(cells)),
        }

    def restore_draw_state(self, state):
        """Restore surviving fit boxes and redraw without another click."""
        if not isinstance(state, dict) or state.get("enabled") is not True:
            return
        try:
            cells = {
                (wafer, str(metric))
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
        self.redraw_keeping_page()

    def redraw_keeping_page(self, saved=None):
        """Redraw a refresh in place: same ranked page, same visible sub-page."""
        page_index = self.user_page if saved is None else saved
        self.draw_plot()
        if not self.ready:
            return
        self.set_page(page_index)
        self.apply_page_intent()

    def refresh_previous_selection(self):
        """Automatic redraw after a data change; the view stays where it was."""
        self.redraw_keeping_page()

    def set_input(self, frame, selection):
        self.frame = frame
        self.selection = selection.copy()
        self.selector.set_array(
            selection.get("wafers", []), selection.get("metrics", []),
            selection.get("labels"), selection.get("available_cells"),
        )
        self.invalidate()
        if (self.has_drawn_once and not self.selector.pending_draw
                and self.selector.selected_cells()):
            self.input_refresh_timer.start()

    def selector_changed(self):
        """Changed fit boxes wait for the explicit Draw selected click."""
        self.invalidate()

    def show_selector(self):
        """Return to the box grid so another set of fits can be chosen."""
        self.page_intent = "selector"
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        self.empty.clear()
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)

    def start_draw(self):
        """Explicit Draw selected: the ranked plot grid is what the user wants."""
        self.page_intent = "plots"
        self.user_page = 0
        self.draw_plot()

    def apply_page_intent(self):
        """Show the sub-page the engineer last chose: box grid or ranked plots."""
        if self.page_intent == "selector":
            self.stack.setCurrentWidget(self.selector_panel)
        else:
            self.stack.setCurrentWidget(self.interactive_scroll)

    def invalidate(self):
        self.input_refresh_timer.stop()
        self.update_timer.stop()
        self._pending_updates.clear()
        self.ready = False
        self.all_fits = []
        self.fits = []
        self.page_index = 0
        self.skipped_count = 0
        self.export_button.setEnabled(False)
        self.export_all_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        self.update_pagination()
        self.figure.clear()
        self.clear_interactive()
        wafers = self.selection.get("wafers", [])
        metrics = self.selection.get("metrics", [])
        rows, columns = len(wafers), len(metrics)
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        if not available:
            self.empty.clear()
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.selector_panel)
        count = len(self.selector.selected_cells())
        self.summary.setText(f"{count} / {rows * columns} selected  ·  {rows} × {columns}")

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
        self.input_refresh_timer.stop()
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
            try:
                self.draw_button.isEnabled()
            except RuntimeError:
                # A deferred automatic refresh can overlap deleteLater().
                # Once Qt has disposed the page controls there is nothing left
                # to render, so leave without touching another wrapped object.
                return
            sources = self.selection.get("sources")
            if sources:
                self.all_fits, errors = source_pairwise_linear_fits(
                    self.frame, drawn_metrics, sources, groups, cells
                )
            else:
                self.all_fits, errors = pairwise_linear_fits(
                    self.frame, drawn_metrics, groups, cells
                )
            self.skipped_count = len(errors)
            if not self.all_fits:
                raise ValueError("No selected pair has enough varying numeric data for a linear fit.")
            self.drawn_metrics = list(drawn_metrics)
            self.drawn_cells = set(cells)
            self.has_drawn_once = True
            self.selector.pending_draw = False
            self.apply_rsq_filter()
        except (ValueError, KeyError) as error:
            self.invalidate()
            self.status.setText(str(error))
        finally:
            QApplication.restoreOverrideCursor()
            try:
                self.draw_button.setEnabled(True)
            except RuntimeError:
                pass

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
            self.user_page = 0
            self.apply_rsq_filter()
            return
        if "layout" in updates:
            self.relayout()
            return
        if "style" in updates:
            self.restyle()
        if "resolution" in updates:
            self.change_resolution()

    def page_count(self):
        size = int(self.page_size.currentText())
        return ceil(len(self.fits) / size) if self.fits else 0

    def page_fits(self, index=None):
        size = int(self.page_size.currentText())
        index = self.page_index if index is None else index
        start = index * size
        return self.fits[start:start + size]

    def update_pagination(self):
        pages = self.page_count()
        if pages:
            self.page_index = min(max(0, self.page_index), pages - 1)
            self.page_label.setText(f"Page {self.page_index + 1} / {pages}")
        else:
            self.page_index = 0
            self.page_label.setText("Page 0 / 0")
        self.previous_page.setEnabled(self.page_index > 0)
        self.next_page.setEnabled(bool(pages and self.page_index + 1 < pages))

    def update_fit_status(self):
        if not self.fits:
            return
        size = int(self.page_size.currentText())
        start = self.page_index * size + 1
        end = min(start + size - 1, len(self.fits))
        skipped = (
            f" · skipped {self.skipped_count} invalid pairs"
            if self.skipped_count else ""
        )
        self.status.setText(
            f"{len(self.fits)} / {len(self.all_fits)} fits pass "
            f"R² > {self.min_rsq.value():.2f} · highest R² first · "
            f"showing {start}–{end} of {len(self.fits)}{skipped}"
        )

    def set_page(self, index):
        pages = self.page_count()
        if not self.ready or not pages:
            return
        target = min(max(0, int(index)), pages - 1)
        if target == self.page_index:
            return
        self.page_index = target
        self.user_page = target
        self.render_fits()
        self.update_fit_status()

    def change_page_size(self, *_):
        self.page_index = 0
        self.user_page = 0
        if self.ready:
            self.render_fits()
            self.update_fit_status()
        else:
            self.update_pagination()

    def apply_rsq_filter(self, *_):
        """Filter already-computed models without running lmfit again."""
        if not self.all_fits:
            return
        threshold = self.min_rsq.value()
        self.fits = [fit for fit in self.all_fits if fit.rsquared > threshold]
        self.page_index = 0
        if not self.fits:
            self.ready = False
            self.export_button.setEnabled(False)
            self.export_all_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.figure.clear()
            self.draw_canvas_message(f"No pairwise fit has R² > {threshold:.2f}")
            self.clear_interactive(f"No pairwise fit has R² > {threshold:.2f}")
            self.stack.setCurrentWidget(self.interactive_scroll)
            self.update_pagination()
            self.status.setText(f"0 / {len(self.all_fits)} fits pass R² > {threshold:.2f}.")
            return
        self.render_fits()
        self.ready = True
        self.stack.setCurrentWidget(self.interactive_scroll)
        self.export_button.setEnabled(True)
        self.export_all_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self.update_fit_status()

    def render_fits(self):
        """Refresh the interactive grid; the export mirror is built on demand."""
        self.update_pagination()
        visible_fits = self.page_fits()
        columns = int(self.columns.currentText())
        rows = ceil(len(visible_fits) / columns)
        self.base_size = (columns * 520, rows * 390 + 30)
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        start_rank = self.page_index * int(self.page_size.currentText()) + 1
        self.render_interactive(visible_fits, columns, rows, start_rank)

    def build_export_figure(self, page_index=None):
        """Matplotlib mirror of the visible fits, used by Export / Copy PNG."""
        self._export_dirty = False
        index = self.page_index if page_index is None else page_index
        visible_fits = self.page_fits(index)
        columns = min(int(self.columns.currentText()), len(visible_fits))
        rows = ceil(len(visible_fits) / columns)
        width, height = columns * 520, rows * 390 + 30
        self.figure.clear()
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        axes = self.figure.subplots(rows, columns, squeeze=False)
        base = int(self.font_size.currentText())
        label_size, tick_size = max(6, base - 1), max(5, base - 2)
        start_rank = index * int(self.page_size.currentText()) + 1
        for rank, (ax, fit) in enumerate(
            zip(axes.flat, visible_fits), start=start_rank
        ):
            if isinstance(fit, SourcePairFit):
                details = []
                for source in fit.sources:
                    values = source.fit
                    ax.scatter(
                        values.x, values.y, s=15, alpha=.58,
                        color=source.color, edgecolors="white", linewidths=.25,
                        rasterized=True,
                    )
                    order = np.argsort(values.x)
                    ax.plot(
                        values.x[order], values.predicted[order],
                        color=source.color, linewidth=1.5, label=source.name,
                    )
                    details.append(
                        f"{source.name}: y={values.slope:.4g}x "
                        f"{values.intercept:+.4g}, R² {values.rsquared:.4f}"
                    )
                set_panel_title(
                    ax, f"{fit.y_name} vs {fit.x_name}",
                    "   ".join(details), f"rank {rank}", base,
                )
                ax.legend(fontsize=max(6, base - 2), frameon=False)
            else:
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

    def render_interactive(self, visible_fits, columns, rows, start_rank=1):
        """Build a resizable grid of independently zoomable PyQtGraph plots."""
        self.clear_interactive()
        base = int(self.font_size.currentText())
        panel_height = 350
        grid = PanelGrid(columns)
        grid.set_fixed_row_height(rows, panel_height)
        for rank, fit in enumerate(visible_fits, start=start_rank):
            widget = InteractivePlotWidget(background="w", frame_tick_length=3)
            widget.setMinimumSize(180, 310)
            widget.setToolTip("Ctrl+scroll to zoom · Drag a box to zoom · Right-drag to pan · "
                              "Ordinary scrolling moves the page · "
                              "Double-click to fit this plot · Reset views restores all plots")
            plot = widget.getPlotItem()
            plot.setTitle(None)   # the QLabel above the plot owns the heading
            plot.showGrid(x=True, y=True, alpha=.18)
            plot.setLabel("bottom", fit.x_name, color="#30343b", size=f"{max(7, base - 1)}pt")
            plot.setLabel("left", fit.y_name, color="#30343b", size=f"{max(7, base - 1)}pt")
            if isinstance(fit, SourcePairFit):
                lines = []
                for source in fit.sources:
                    values = source.fit
                    lines.append(
                        f"{source.name}: y = {values.slope:.5g}x "
                        f"{values.intercept:+.5g}   R² {values.rsquared:.5f}   "
                        f"n {len(values.x)}"
                    )
                details = "<br>".join(escape(line) for line in lines)
            else:
                equation = f"y = {fit.slope:.5g}x {fit.intercept:+.5g}"
                details = escape(
                    f"{equation}   R² {fit.rsquared:.5f}   "
                    f"n {len(fit.x)}   rank {rank}"
                )
            heading = panel_title_label(
                f"<b>{escape(fit.y_name)} vs {escape(fit.x_name)}</b><br>"
                f"<span style='font-size:{max(7, base - 1)}pt'>{details}</span>",
                base + 1)
            # A QLabel keeps every title line in its own space; pyqtgraph's own
            # title reserves one line and printed the second over the plot.
            container = PlotPanel(heading, widget)
            if isinstance(fit, SourcePairFit):
                plot.addLegend(offset=(10, 8))
                for source in fit.sources:
                    values = source.fit
                    plot.plot(
                        values.x, values.y, pen=None, symbol="o", symbolSize=6,
                        symbolPen=pg.mkPen("#ffffff", width=.5),
                        symbolBrush=pg.mkBrush(source.color),
                        name=f"{source.name} points",
                    )
                    order = np.argsort(values.x)
                    plot.plot(
                        values.x[order], values.predicted[order],
                        pen=pg.mkPen(source.color, width=2),
                        name=f"{source.name} fit",
                    )
            else:
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
            grid.add_panel(container)
            self.plot_widgets.append(widget)
            self.panel_hosts.append(container)
        grid.complete_last_row(minimum_width=180)
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
        self.status.setText(f"Reset {len(self.plot_widgets)} plot views.")

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
            self.status.setText(f"PNG output: {dpi} dpi. This setting does not change the on-screen plots.")

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
            shown = len(self.page_fits())
            self.status.setText(
                f"Exported {shown} fits from page {self.page_index + 1} "
                f"of {self.page_count()} at {dpi} dpi{note}: {path}"
            )
        except Exception as error:
            self.status.setText(f"Export failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()

    def export_all_pages(self):
        if not self.ready:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export all pairwise fit pages", "pairwise_fits.png",
            "PNG (*.png)",
        )
        if not path:
            return
        base_path = Path(path).with_suffix(".png")
        pages = self.page_count()
        _scale, requested = resolution_settings(self.resolution)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status.setText(f"Exporting {pages} pages…")
        QApplication.processEvents()
        try:
            for index in range(pages):
                self.build_export_figure(index)
                output = (
                    base_path
                    if pages == 1 else
                    base_path.with_name(
                        f"{base_path.stem}_{index + 1:02d}{base_path.suffix}"
                    )
                )
                dpi = export_dpi(self.figure, requested, MAX_EXPORT_PIXELS)
                self.figure.savefig(output, dpi=dpi, facecolor="white")
                QApplication.processEvents()
            self.status.setText(
                f"Exported all {len(self.fits)} fits across {pages} pages: "
                f"{base_path.parent}"
            )
        except Exception as error:
            self.status.setText(f"Export failed: {error}")
        finally:
            self._export_dirty = True
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
            shown = len(self.page_fits())
            self.status.setText(
                f"Copied {shown} fits from page {self.page_index + 1} "
                f"of {self.page_count()} at {dpi} dpi{note} · "
                f"{image.width()} × {image.height()} px"
            )
        except Exception as error:
            self.status.setText(f"Copy failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()
