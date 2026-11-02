"""Pairwise numeric scatter plots and unweighted linear regression.

The visible grid is PyQtGraph so every variable pair zooms and pans on its own;
Matplotlib stays behind the Export / Copy PNG buttons as the print backend.
"""

from dataclasses import dataclass
from copy import deepcopy
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
from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .appearance import (CORRELATION_FIT_COLOR, CORRELATION_POINT_COLOR,
                         MAX_COPY_PIXELS, MAX_EXPORT_PIXELS, configure_resolution_combo,
                         export_dpi, panel_title_label, resolution_settings)
from .appearance import widget_to_qimage
from .array_plot import drawn_axes
from .data import number
from .map_selector import MapSelector
from .plot import set_panel_title
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel
from .plotting.curve import ResponsivePlotDataItem
from .plotting.annotations import plain_matplotlib_y, plain_y_axes
from .plotting.parameter_filter import ParameterFilterBar
from .settings import get_settings


DEFAULT_PAGE_SIZE = 12
HOME_PADDING = 0.08
RENDER_BATCH_SIZE = 2


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
    parameter_keys: tuple[tuple[str, str], ...] = ()

    @property
    def rsquared(self):
        return max(source.fit.rsquared for source in self.sources)


def correlation_colors(fit):
    """Stable source-pair colours, independent of parameter names or X/Y order."""
    if isinstance(fit, SourcePairFit):
        sources = frozenset(name for name, _metric in fit.parameter_keys)
        if not sources:
            sources = frozenset(source.name for source in fit.sources)
        if sources == {"Reference"}:
            return "#ed7d31", "#b95616"
        if sources == {"Raw Data"}:
            return CORRELATION_POINT_COLOR, "#285f9f"
        if sources == {"Reference", "Raw Data"}:
            return "#009e73", "#006b4f"
    # Unqualified standalone data retains its established observation/fit style.
    return CORRELATION_POINT_COLOR, CORRELATION_FIT_COLOR


def fit_numeric_pair(frame, x_name, y_name):
    """Fit y = slope*x + intercept with lmfit after paired numeric cleanup."""
    x = number(frame[x_name]).to_numpy(float)
    y = number(frame[y_name]).to_numpy(float)
    return _fit_numeric_values(x, y, x_name, y_name)


def _fit_numeric_values(x, y, x_name, y_name, model=None, *, moments=None):
    """Fit already-converted arrays while preserving the public frame seam."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    paired = np.isfinite(x) & np.isfinite(y)
    if not (type(model) is LinearModel and not x.flags.writeable
            and not y.flags.writeable and paired.all()):
        x, y = x[paired], y[paired]
    if len(x) < 3:
        raise ValueError("fewer than 3 paired numeric points")
    # Batch callers already supplied the ordinary, unweighted LinearModel.
    # Its two coefficients have a closed OLS solution; starting a generic
    # iterative fit for every pair repeats that work quadratically. Keep the
    # public single-pair/lmfit path and conservative numerical fallback intact.
    coefficients = None
    # Retain the established solver's bit-for-bit output for small selections;
    # the batch shortcut is useful for long measurement vectors.
    if type(model) is LinearModel and len(x) >= 128:
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            mean_x, centered_x, denominator, spread_x = _numeric_moments(x, moments)
            mean_y, centered_y, _energy_y, spread_y = _numeric_moments(y, moments)
            if spread_x == 0 or spread_y == 0:
                raise ValueError("constant data cannot be fitted")
            if (abs(mean_x) <= 1e4 * spread_x
                    and abs(mean_y) <= 1e4 * spread_y):
                if np.isfinite(denominator) and denominator > 0:
                    slope = float(np.dot(centered_x, centered_y) / denominator)
                    intercept = float(mean_y - slope * mean_x)
                    if np.isfinite([slope, intercept]).all():
                        coefficients = slope, intercept
    if coefficients is None:
        if np.ptp(x) == 0 or np.ptp(y) == 0:
            raise ValueError("constant data cannot be fitted")
        model = model or LinearModel()
        result = model.fit(y, model.guess(y, x=x), x=x)
        predicted = np.asarray(result.best_fit, dtype=float)
        slope = float(result.params["slope"].value)
        intercept = float(result.params["intercept"].value)
    else:
        slope, intercept = coefficients
        predicted = slope * x + intercept
    residual = float(np.square(y - predicted).sum())
    total = float(np.square(y - y.mean()).sum())
    rsquared = 1 - residual / total if total > 0 else float("nan")
    return LinearFit(x_name, y_name, x, y, predicted, slope, intercept, rsquared)


def _numeric_moments(values, cache):
    # Only call-local, detached read-only vectors are reused. Pairwise NaN
    # filtering produces new writable arrays and must compute its own moments.
    key = id(values)
    reusable = cache is not None and not values.flags.writeable
    if reusable and key in cache:
        return cache[key]
    mean = float(values.mean())
    centered = values - mean
    result = mean, centered, float(np.dot(centered, centered)), float(np.ptp(values))
    if reusable:
        cache[key] = result
    return result


def swap_fit_axes(fit):
    """Refit the same paired observations in the opposite OLS direction.

    Reversing the old equation is not regression of X on Y for noisy data.
    Source populations remain separate, with their original order and colours.
    """
    if isinstance(fit, SourcePairFit):
        return SourcePairFit(fit.y_name, fit.x_name, tuple(
            SourceFit(source.name, source.color, swap_fit_axes(source.fit)) for source in fit.sources),
            tuple(reversed(fit.parameter_keys)))
    return _fit_numeric_values(fit.y, fit.x, fit.y_name, fit.x_name)


def _owned_numeric_columns(frame, metrics):
    """Detached read-only vectors may safely serve many result pairs."""
    numeric = {}
    for name in metrics:
        values = number(frame[name]).to_numpy(dtype=float, copy=True)
        values.flags.writeable = False
        numeric[name] = values
    return numeric


def _selected_numeric(numeric, name, positions, selection, cache):
    if positions is None:
        return numeric[name]
    key = (selection, name)
    if key not in cache:
        values = numeric[name][positions]
        values.flags.writeable = False
        cache[key] = values
    return cache[key]


class _CommonPopulationFits:
    """Call-local OLS coefficients for one proven finite observation population."""

    def __init__(self, names, vectors, stats, covariance):
        self.positions = {name: position for position, name in enumerate(names)}
        self.vectors, self.stats, self.covariance = vectors, stats, covariance
        # Keep the existing residual definition, including its centered total,
        # rather than deriving R² by subtracting nearly equal matrix energies.
        self.totals = [float(np.square(stat[1]).sum()) for stat in stats]

    def fit(self, x_name, y_name):
        i, j = self.positions[x_name], self.positions[y_name]
        x, y = self.vectors[i], self.vectors[j]
        slope = float(self.covariance[i, j] / self.stats[i][2])
        intercept = float(self.stats[j][0] - slope * self.stats[i][0])
        predicted = slope * x + intercept
        residual = float(np.square(y - predicted).sum())
        total = self.totals[j]
        return LinearFit(x_name, y_name, x, y, predicted, slope, intercept,
                         1 - residual / total if total > 0 else float('nan'))


def _common_population_fits(numeric, metrics, groups, cells, source_rows=None):
    # Small inputs retain exact legacy results. Different selections and NaN
    # masks must keep their per-pair cleanup; equal lengths alone prove nothing.
    if len(metrics) < 8 or len(set(metrics)) != len(metrics):
        return None
    positions = None
    if groups is not None and cells is not None:
        keys = tuple(key for key in groups if (key, metrics[0]) in cells)
        if any(tuple(key for key in groups if (key, name) in cells) != keys for name in metrics[1:]):
            return None
        if source_rows is None:
            rows = [row for key in keys for row in groups[key]]
        else:
            allowed = {row for key in keys for row in groups[key]}
            rows = [row for row in source_rows if row in allowed]
        positions = np.asarray(rows, dtype=int)
    elif source_rows is not None:
        positions = np.asarray(source_rows, dtype=int)
    vectors = [numeric[name] if positions is None else numeric[name][positions] for name in metrics]
    if any(len(values) < 128 or not np.isfinite(values).all() for values in vectors):
        return None
    for values in vectors:
        values.flags.writeable = False
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        stats = [_numeric_moments(values, None) for values in vectors]
        if any(not np.isfinite(stat[2]) or stat[2] <= 0 or stat[3] <= 0
               or not np.isfinite(stat[3]) or abs(stat[0]) > 1e4 * stat[3] for stat in stats):
            return None
        centered = np.stack([stat[1] for stat in stats])
        covariance = centered @ centered.T
        denominators = np.asarray([stat[2] for stat in stats])
        slopes = covariance / denominators[:, None]
        means = np.asarray([stat[0] for stat in stats])
        if not (np.isfinite(slopes).all()
                and np.isfinite(means[None, :] - slopes * means[:, None]).all()):
            return None
    return _CommonPopulationFits(metrics, vectors, stats, covariance)


def pairwise_linear_fits(frame, metrics, groups=None, cells=None, *, cancelled=None):
    """Return valid OLS results ordered from strongest to weakest linear fit.

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
    numeric = _owned_numeric_columns(frame, metrics)
    common = _common_population_fits(numeric, metrics, groups, cells)
    model = LinearModel()
    row_cache, vector_cache, moments = {}, {}, {}
    for x_name, y_name in combinations(metrics, 2):
        if cancelled is not None and cancelled():
            raise InterruptedError("Correlation update cancelled")
        if common is not None:
            fits.append(common.fit(x_name, y_name))
            continue
        positions, selected_keys = None, None
        if groups is not None and cells is not None:
            selected_keys = tuple(key for key in groups
                                  if (key, x_name) in cells and (key, y_name) in cells)
            if selected_keys not in row_cache:
                row_cache[selected_keys] = np.asarray(
                    [index for key in selected_keys for index in groups[key]], dtype=int)
            positions = row_cache[selected_keys]
        x = _selected_numeric(numeric, x_name, positions, selected_keys, vector_cache)
        y = _selected_numeric(numeric, y_name, positions, selected_keys, vector_cache)
        try:
            fits.append(_fit_numeric_values(x, y, x_name, y_name, model, moments=moments))
        except ValueError as error:
            errors.append((x_name, y_name, str(error)))
    fits.sort(key=lambda fit: fit.rsquared if np.isfinite(fit.rsquared) else -np.inf, reverse=True)
    return fits, errors


def source_pairwise_linear_fits(frame, metrics, sources, groups, cells, *, cancelled=None):
    """Fit within-source and row-aligned cross-source parameter pairs.

    Within-source panels remain Reference-first/Raw-second. Cross-source
    panels follow and fit aligned observations, never pooled populations.
    """
    numeric = _owned_numeric_columns(frame, metrics)
    model = LinearModel()
    panels, errors = [], []
    for source in sources:
        source_panels = []
        row_cache, vector_cache, moments = {}, {}, {}
        common = _common_population_fits(numeric, metrics, groups, cells, source['rows'])
        for x_name, y_name in combinations(metrics, 2):
            if cancelled is not None and cancelled():
                raise InterruptedError("Correlation update cancelled")
            try:
                if common is not None:
                    fit = common.fit(x_name, y_name)
                else:
                    selected_keys = tuple(key for key in groups
                                          if (key, x_name) in cells and (key, y_name) in cells)
                    if selected_keys not in row_cache:
                        selected_rows = {row for key in selected_keys for row in groups[key]}
                        # Retain source order/repeated positions for each distinct selection.
                        row_cache[selected_keys] = np.asarray(
                            [row for row in source["rows"] if row in selected_rows], dtype=int)
                    positions = row_cache[selected_keys]
                    fit = _fit_numeric_values(
                        _selected_numeric(numeric, x_name, positions, selected_keys, vector_cache),
                        _selected_numeric(numeric, y_name, positions, selected_keys, vector_cache),
                        x_name, y_name, model, moments=moments,
                    )
            except ValueError as error:
                errors.append((source["name"], x_name, y_name, str(error)))
                continue
            source_panels.append(SourcePairFit(
                x_name, y_name,
                (SourceFit(source["name"], source["color"], fit),),
                ((source["name"], x_name), (source["name"], y_name)),
            ))
        source_panels.sort(key=lambda panel: panel.rsquared, reverse=True)
        panels.extend(source_panels)
    # Different source tables share original row ordinals, not concatenated
    # population positions. Intersect selections before paired NaN cleanup.
    source_labels = {"Reference": "REF", "Raw Data": "RAW"}
    for left, right in combinations(sources, 2):
        if len(left["rows"]) != len(right["rows"]):
            raise ValueError("Cross-source correlation requires row-aligned source tables.")
        selected = {}
        for source in (left, right):
            for name in metrics:
                allowed = {row for key, rows in groups.items() if (key, name) in cells for row in rows}
                selected[(source["name"], name)] = {
                    index: row for index, row in enumerate(source["rows"]) if row in allowed}
        cross = []
        for x_name in metrics:
            x_rows = selected[(left["name"], x_name)]
            if not x_rows:
                continue
            for y_name in metrics:
                if cancelled is not None and cancelled():
                    raise InterruptedError("Correlation update cancelled")
                y_rows = selected[(right["name"], y_name)]
                if not y_rows:
                    continue
                indices = sorted(x_rows.keys() & y_rows.keys())
                labels = tuple(f"{source_labels.get(source['name'], source['name'])} · {name}"
                               for source, name in ((left, x_name), (right, y_name)))
                try:
                    fit = _fit_numeric_values(numeric[x_name][[x_rows[i] for i in indices]],
                                              numeric[y_name][[y_rows[i] for i in indices]], *labels, model)
                except ValueError as error:
                    errors.append((left["name"], x_name, right["name"], y_name, str(error)))
                    continue
                cross.append(SourcePairFit(*labels,
                    (SourceFit(f"{left['name']} ↔ {right['name']}", left["color"], fit),),
                    ((left["name"], x_name), (right["name"], y_name))))
        cross.sort(key=lambda panel: panel.rsquared, reverse=True)
        panels.extend(cross)
    return panels, errors


class CorrelationPage(QWidget):
    axes_changed = pyqtSignal()

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
        self._panel_cache = {}
        self._visible_panel_keys = []
        self._retained_grid = None
        self._axis_directions = {}
        self._reversed_fits = {}
        self.skipped_count = 0
        self.base_size = (900, 650)
        self._pending_updates = set()
        self.home_views = []
        self._render_generation = 0
        self._batch_state = None
        self._render_timer = QTimer(self, interval=5, singleShot=True)
        self._render_timer.timeout.connect(self._render_next_panels)
        self._home_timer = QTimer(self, interval=0, singleShot=True)
        self._home_timer.timeout.connect(self._remember_current_home_views)
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
        self.parameter_filter = ParameterFilterBar(pair_selection=True)
        self.parameter_filter.changed.connect(self.set_parameter_filter)
        header.addWidget(self.parameter_filter)
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

    def restore_draw_state(self, state, *, background=False):
        """Restore surviving fit boxes and redraw without another click."""
        if not isinstance(state, dict) or state.get("enabled") is not True:
            if isinstance(state, dict) and state.get("enabled") is False:
                self.has_drawn_once = False
                self.invalidate()
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
        if background:
            self.request_background_draw(deferred=True)
        else:
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
        self._updating_input = True
        try:
            self.selector.set_array(
                selection.get("wafers", []), selection.get("metrics", []),
                selection.get("labels"), selection.get("available_cells"),
            )
        finally:
            self._updating_input = False
        self.invalidate(preserve_panels=True)
        if (self.has_drawn_once and not self.selector.pending_draw
                and self.selector.selected_cells()):
            self.input_refresh_timer.start()

    def selector_changed(self):
        """Changed fit boxes wait for the explicit Draw selected click."""
        self.invalidate(preserve_panels=getattr(self, "_updating_input", False))

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

    def invalidate(self, *, preserve_panels=False):
        self._cancel_background_draw()
        self.input_refresh_timer.stop()
        self.update_timer.stop()
        self.parameter_filter.set_parameters(
            [name for name in self.parameter_filter.names if name in self.frame.columns]
            if not self.frame.empty and self.selector.rowCount() and self.selector.columnCount() else (),
            sources=self.parameter_filter.source_groups)
        self._pending_updates.clear()
        self.ready = False
        self.all_fits = []
        self._reversed_fits.clear()
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
        self.clear_interactive(preserve_panels=preserve_panels and not self.frame.empty
                               and bool(self.selector.rowCount() and self.selector.columnCount()),
                               retain_layout=True)
        wafers = self.selection.get("wafers", [])
        metrics = self.selection.get("metrics", [])
        rows, columns = len(wafers), len(metrics)
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        if not available:
            self.empty.clear()
            self.stack.setCurrentWidget(self.empty)
        elif (preserve_panels and self.page_intent == "plots" and not self.selector.pending_draw
              and isinstance(self.plot_host, PanelGrid)):
            self.stack.setCurrentWidget(self.interactive_scroll)
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

    @property
    def background_render_pending(self):
        task = getattr(self, "_draw_task", None)
        return bool(getattr(self, "_background_requested", False) or (task is not None and task.busy)
                    or self._batch_state is not None)

    def _cancel_background_draw(self):
        timer = getattr(self, "_draw_request_timer", None)
        if timer is not None:
            timer.stop()
        self._cancel_interactive_render()
        task = getattr(self, "_draw_task", None)
        if task is not None:
            task.cancel()
        self._background_requested = False

    def request_background_draw(self, *, deferred=False):
        if deferred:
            self._cancel_background_draw()
            self.input_refresh_timer.stop()
            self.ready = False
            self._background_requested = True
            for button in (self.export_button, self.export_all_button, self.copy_button):
                button.setEnabled(False)
            if not hasattr(self, "_draw_request_timer"):
                self._draw_request_timer = QTimer(self, interval=0, singleShot=True)
                self._draw_request_timer.timeout.connect(self.request_background_draw)
            self._draw_request_timer.start()
            return
        timer = getattr(self, "_draw_request_timer", None)
        owner = getattr(self.window(), "_managed_owner", None)
        if (timer is not None and getattr(self, "_background_requested", False)
                and owner is not None and owner.linked_updates_pending):
            timer.start(1)
            return
        if timer is not None:
            timer.stop()
        self._cancel_interactive_render()
        from .background_task import LatestTask
        from .correlation_data import prepare_correlations
        metrics = self.selection.get("metrics", ())
        cells = self.selector.selected_cells()
        wafers, metrics = drawn_axes(self.selection.get("wafers", ()), metrics, cells)
        groups = {key: rows for key, rows in self.row_groups().items() if key in set(wafers)}
        if not cells or not metrics or not any(groups.values()):
            self.draw_plot()
            return
        if not hasattr(self, "_draw_task"):
            self._draw_task = LatestTask(prepare_correlations, self._accept_background_draw,
                                         self._background_draw_error, self)
        self.input_refresh_timer.stop()
        self.update_timer.stop()
        self._background_requested = True
        self.ready = False
        self.cells = set(cells)
        for button in (self.export_button, self.export_all_button, self.copy_button):
            button.setEnabled(False)
        self.status.setText("Updating Correlation…")
        self._draw_task.submit({"frame": self.frame.copy(deep=True), "metrics": tuple(metrics),
            "cells": frozenset(cells), "groups": deepcopy(groups),
            "sources": deepcopy(self.selection.get("sources"))})

    def _accept_background_draw(self, prepared):
        if prepared is None:
            return
        self._background_requested = False
        self.all_fits, errors, metrics, cells = prepared
        self._reversed_fits.clear()
        self.skipped_count = len(errors)
        if not self.all_fits:
            self._background_draw_error("No selected pair has enough varying numeric data for a linear fit.")
            return
        self.drawn_metrics, self.drawn_cells = list(metrics), set(cells)
        self.has_drawn_once = True
        self.selector.pending_draw = False
        self.apply_rsq_filter()
        if self.ready:
            self.set_page(self.user_page)
            self.apply_page_intent()

    def _background_draw_error(self, message):
        self.invalidate()
        self.status.setText(f"Correlation update failed: {message}")

    def finish_background_draw(self):
        if getattr(self, "_background_requested", False):
            self.redraw_keeping_page()
        self._finish_interactive_render()

    def stop_background_draw(self):
        self._cancel_background_draw()
        task = getattr(self, "_draw_task", None)
        if task is not None:
            task.close()

    def closeEvent(self, event):
        self.stop_background_draw()
        super().closeEvent(event)

    def draw_plot(self):
        self._cancel_background_draw()
        self.input_refresh_timer.stop()
        self.update_timer.stop()
        self._pending_updates.clear()
        self.draw_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            metrics = self.selection.get("metrics", [])
            if len(metrics) < (1 if self.selection.get("sources") else 2):
                raise ValueError("Select at least 2 numeric columns in Data.")
            cells = self.selector.selected_cells()
            if not cells:
                raise ValueError("Select at least one fit box before drawing.")
            wafers = self.selection.get("wafers", [])
            drawn_wafers, drawn_metrics = drawn_axes(wafers, metrics, cells)
            if len(drawn_metrics) < (1 if self.selection.get("sources") else 2):
                raise ValueError("Select boxes for at least 2 numeric columns.")
            groups = {key: rows for key, rows in self.row_groups().items() if key in set(drawn_wafers)}
            if not any(groups.values()):
                raise ValueError("Select at least one measurement set in Data.")
            self.cells = set(cells)
            pair_count = len(drawn_metrics) * (len(drawn_metrics) - 1) // 2
            self.status.setText("Fitting within- and cross-table parameter pairs…" if self.selection.get("sources")
                                else f"Fitting {pair_count} parameter pairs…")
            QApplication.processEvents()
            try:
                self.draw_button.isEnabled()
            except RuntimeError:
                # A deferred automatic refresh can overlap deleteLater().
                # Once Qt has disposed the page controls there is nothing left
                # to render, so leave without touching another wrapped object.
                return
            sources = self.selection.get("sources")
            self._reversed_fits.clear()
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
        if kind in ("filter", "layout", "style") and self._batch_state is not None:
            self._cancel_interactive_render()
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
        return ceil(len(self.display_fits()) / size)

    def display_fits(self):
        parameter = self.parameter_filter.parameter
        return self.fits if parameter is None else [fit for fit in self.fits
                                                   if self.parameter_filter.matches(
                                                       fit.parameter_keys if isinstance(fit, SourcePairFit)
                                                       else (fit.x_name, fit.y_name))]

    @staticmethod
    def axis_key(fit):
        sources = tuple(source.name for source in fit.sources) if isinstance(fit, SourcePairFit) else ()
        return (sources, *sorted((fit.x_name, fit.y_name)))

    def axis_state(self):
        return [{"sources": list(sources), "x": x_name, "y": second if x_name == first else first}
                for (sources, first, second), x_name in sorted(self._axis_directions.items())]

    def restore_axis_state(self, state):
        """Restore explicit predictor choices before the saved fit boxes draw."""
        if not isinstance(state, list):
            raise ValueError("Invalid correlation axis directions.")
        directions = {}
        for choice in state:
            if not isinstance(choice, dict):
                raise ValueError("Invalid correlation axis direction.")
            sources, x_name, y_name = choice.get("sources"), choice.get("x"), choice.get("y")
            if (not isinstance(sources, list) or not all(isinstance(name, str) for name in sources)
                    or not isinstance(x_name, str) or not isinstance(y_name, str) or x_name == y_name):
                raise ValueError("Invalid correlation axis direction.")
            directions[(tuple(sources), *sorted((x_name, y_name)))] = x_name
        if directions != self._axis_directions:
            self._axis_directions = directions
            if self.ready:
                self.render_fits()
            self.axes_changed.emit()

    def oriented_fit(self, fit):
        if self._axis_directions.get(self.axis_key(fit), fit.x_name) == fit.x_name:
            return fit
        if id(fit) not in self._reversed_fits:
            self._reversed_fits[id(fit)] = swap_fit_axes(fit)
        return self._reversed_fits[id(fit)]

    def swap_axes(self, fit):
        """Change one panel in place; unrelated fits/widgets/views stay intact."""
        rebuilding = self._batch_state is not None
        if rebuilding:
            fit = next((candidate for candidate in self.all_fits
                        if self.axis_key(candidate) == self.axis_key(fit)), fit)
        if not self.ready or not any(candidate is fit for candidate in self.all_fits):
            return
        key = self.axis_key(fit)
        current = self.oriented_fit(fit)
        if current.x_name == fit.x_name:
            # Prepare before accepting state; a failed fit must not change axes.
            try:
                if id(fit) not in self._reversed_fits:
                    self._reversed_fits[id(fit)] = swap_fit_axes(fit)
            except ValueError as error:
                self.status.setText(f"Unable to swap axes: {error}")
                return
            self._axis_directions[key] = fit.y_name
        else:
            self._axis_directions.pop(key, None)
        updated = self.oriented_fit(fit)
        base = int(self.font_size.currentText())
        cache_key = self._panel_key(fit, base)
        if rebuilding:
            self.render_fits()
        elif cache_key in self._visible_panel_keys:
            index = self._visible_panel_keys.index(cache_key)
            rank = self.page_index * int(self.page_size.currentText()) + index + 1
            self.update_panel_direction(self._panel_cache[cache_key], updated, rank, base)
            self.home_views[index:index + 1] = [self._panel_cache[cache_key]["home"]]
        self._export_dirty = True
        self._copy_image = self._copy_dpi = None
        self.axes_changed.emit()

    @classmethod
    def _panel_key(cls, fit, base):
        return (cls.axis_key(fit), tuple(getattr(fit, "parameter_keys", ())), base)

    def update_panel_direction(self, cached, fit, rank, base, *, swap_view=True):
        widget = cached["widget"]
        plot, view = widget.getPlotItem(), widget.getViewBox()
        previous = view.viewRange()
        at_home = cached["home"] is None or np.allclose(previous, cached["home"])
        plot.setLabel("bottom", fit.x_name, color="#30343b", size=f"{max(7, base - 1)}pt")
        plot.setLabel("left", fit.y_name, color="#30343b", size=f"{max(7, base - 1)}pt")
        values = [source.fit for source in fit.sources] if isinstance(fit, SourcePairFit) else [fit]
        previous_values = ([source.fit for source in cached["fit"].sources]
                           if isinstance(cached["fit"], SourcePairFit) else [cached["fit"]])
        for (points, line), source, previous_source in zip(cached["items"], values, previous_values):
            if not (np.array_equal(previous_source.x, source.x) and np.array_equal(previous_source.y, source.y)):
                points.setData(source.x, source.y)
            order = np.argsort(source.x)
            x, y = source.x[order], source.predicted[order]
            if not (np.array_equal(line.xData, x) and np.array_equal(line.yData, y)):
                line.setData(x, y)
        cached["heading"].setText(self.panel_heading(fit, rank, base))
        cached["fit"] = fit
        view.autoRange(padding=HOME_PADDING)
        cached["home"] = view.viewRange()
        if not at_home and swap_view:
            view.setRange(xRange=previous[1], yRange=previous[0], padding=0)

    def set_parameter_filter(self, _parameter):
        if self.ready:
            self.page_index = self.user_page = 0
            self.render_fits()
            self.update_fit_status()

    def page_fits(self, index=None):
        size = int(self.page_size.currentText())
        index = self.page_index if index is None else index
        start = index * size
        return self.display_fits()[start:start + size]

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
        fits = self.display_fits()
        if not fits:
            self.status.setText(
                f"No correlation for the selected parameters passes R² > {self.min_rsq.value():.2f} "
                "with the current drawn measurements."
            )
            return
        size = int(self.page_size.currentText())
        start = self.page_index * size + 1
        end = min(start + size - 1, len(fits))
        skipped = (
            f" · skipped {self.skipped_count} invalid pairs"
            if self.skipped_count else ""
        )
        pairs = len({frozenset(fit.parameter_keys if isinstance(fit, SourcePairFit) else (fit.x_name, fit.y_name))
                     for fit in fits})
        pair_summary = f"{pairs} parameter pair{'s' if pairs != 1 else ''}"
        if any(isinstance(fit, SourcePairFit) for fit in fits):
            pair_summary += f" · {len(fits)} source fits"
        self.status.setText(
            f"{pair_summary} · {len(fits)} / {len(self.all_fits)} fits pass "
            f"R² > {self.min_rsq.value():.2f} · highest R² first · "
            f"showing {start}–{end} of {len(fits)}{skipped}"
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
        if self.selection.get("sources"):
            keys = {key for fit in self.fits for key in fit.parameter_keys}
            names = {name for _, name in keys}
            self.parameter_filter.set_parameters([name for name in self.drawn_metrics if name in names], sources=[
                (source["name"], [name for name in self.drawn_metrics if (source["name"], name) in keys])
                for source in self.selection["sources"]])
        else:
            self.parameter_filter.set_parameters([name for name in self.drawn_metrics
                                                  if any(name in (fit.x_name, fit.y_name) for fit in self.fits)])
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
        visible = bool(self.display_fits())
        self.export_button.setEnabled(visible and self._batch_state is None)
        self.export_all_button.setEnabled(visible and self._batch_state is None)
        self.copy_button.setEnabled(visible and self._batch_state is None)
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
        for control in (self.export_button, self.export_all_button, self.copy_button):
            control.setEnabled(bool(visible_fits))
        if not visible_fits:
            self.base_size = (900, 400)
            self.update_fit_status()
            self.figure.clear()
            self.draw_canvas_message(self.status.text())
            self.clear_interactive(self.status.text(), preserve_panels=True)
            return
        start_rank = self.page_index * int(self.page_size.currentText()) + 1
        self.render_interactive(visible_fits, columns, rows, start_rank)

    def build_export_figure(self, page_index=None):
        """Matplotlib mirror of the visible fits, used by Export / Copy PNG."""
        self._export_dirty = False
        index = self.page_index if page_index is None else page_index
        visible_fits = self.page_fits(index)
        if not visible_fits:
            self.figure.clear()
            self.figure.set_size_inches(9, 4, forward=False)
            self.update_fit_status()
            self.draw_canvas_message(self.status.text())
            return
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
            fit = self.oriented_fit(fit)
            point_color, fit_color = correlation_colors(fit)
            if isinstance(fit, SourcePairFit):
                details = []
                for source in fit.sources:
                    values = source.fit
                    ax.scatter(
                        values.x, values.y, s=15, alpha=1,
                        color=point_color, edgecolors="none",
                        rasterized=True,
                    )
                    order = np.argsort(values.x)
                    ax.plot(
                        values.x[order], values.predicted[order],
                        color=fit_color, linewidth=1.5, label=source.name,
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
                ax.scatter(fit.x, fit.y, s=15, alpha=1, color=point_color,
                           edgecolors="none", rasterized=True)
                order = np.argsort(fit.x)
                ax.plot(fit.x[order], fit.predicted[order], color=fit_color, linewidth=1.5)
                equation = f"y = {fit.slope:.5g}x {fit.intercept:+.5g}"
                stats = f"R² {fit.rsquared:.5f}   n {len(fit.x)}   rank {rank}"
                set_panel_title(ax, f"{fit.y_name} vs {fit.x_name}", equation, stats, base)
            ax.set_xlabel(fit.x_name, fontsize=label_size)
            ax.set_ylabel(fit.y_name, fontsize=label_size)
            plain_matplotlib_y(ax)
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
        self._finish_interactive_render()
        if self._export_dirty or not self.figure.axes:
            self.build_export_figure()
            self.refresh_canvas()

    def clear_interactive(self, message=None, *, preserve_panels=False, retain_layout=False):
        self._cancel_interactive_render()
        if preserve_panels and retain_layout and isinstance(self.plot_host, PanelGrid):
            keys = tuple(self._visible_panel_keys)
            if keys:
                self._retained_grid = self.plot_host, keys
            if self._retained_grid is not None:
                # Keep the complete old canvas while its replacement is prepared.
                # Copy/export remain disabled until current data is published.
                return
        self._retained_grid = None
        for cached in self._panel_cache.values():
            cached["panel"].setParent(self)
            cached["panel"].hide()
            if not preserve_panels:
                cached["panel"].deleteLater()
        if not preserve_panels:
            self._panel_cache.clear()
        if self.plot_host is not None:
            self.plot_host.setParent(None)
            self.plot_host.deleteLater()
            self.plot_host = None
        self.plot_widgets = []
        self.panel_hosts = []
        self.home_views = []
        self._visible_panel_keys = []
        if message:
            label = QLabel(message, objectName="subtitle")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"font-size: {max(15, int(self.font_size.currentText()) + 3)}pt;")
            label.setMinimumSize(600, 360)
            self.plot_host = label
            self.interactive_scroll.setWidget(label)

    @staticmethod
    def panel_heading(fit, rank, base):
        if isinstance(fit, SourcePairFit):
            lines = []
            for source in fit.sources:
                values = source.fit
                lines.append(f"{source.name}: y = {values.slope:.5g}x "
                             f"{values.intercept:+.5g}   R² {values.rsquared:.5f}   n {len(values.x)}")
            details = "<br>".join(escape(line) for line in lines)
        else:
            details = escape(f"y = {fit.slope:.5g}x {fit.intercept:+.5g}   "
                             f"R² {fit.rsquared:.5f}   n {len(fit.x)}   rank {rank}")
        return (f"<b>{escape(fit.y_name)} vs {escape(fit.x_name)}</b><br>"
                f"<span style='font-size:{max(7, base - 1)}pt'>{details}</span>")

    def _cancel_interactive_render(self):
        self._render_generation += 1
        self._render_timer.stop()
        self._home_timer.stop()
        state, self._batch_state = self._batch_state, None
        if state is not None:
            state["grid"].deleteLater()

    def _current_render(self, state):
        return (not sip.isdeleted(self) and state is self._batch_state
                and state["generation"] == self._render_generation)

    def _schedule_home_views(self):
        self._home_generation = self._render_generation
        self._home_timer.start()

    def _remember_current_home_views(self):
        if self._home_generation == self._render_generation and self._batch_state is None:
            self.remember_home_views()

    def _finish_interactive_render(self):
        """Explicit Copy/export/save completion; normal rendering stays event driven."""
        while self._batch_state is not None:
            self._render_timer.stop()
            self._render_next_panels()

    def _update_render_panel(self, cached, fit, rank, base):
        previous = cached["widget"].getViewBox().viewRange()
        custom = cached["home"] is not None and not np.allclose(previous, cached["home"])
        changed = (cached["fit"].x_name, cached["fit"].y_name) != (fit.x_name, fit.y_name)
        self.update_panel_direction(cached, fit, rank, base, swap_view=changed)
        if custom and not changed:
            cached["widget"].getViewBox().setRange(xRange=previous[0], yRange=previous[1], padding=0)

    def render_interactive(self, visible_fits, columns, rows, start_rank=1):
        """Reuse retained grids, otherwise stage complete pages in small GUI batches."""
        self._cancel_interactive_render()
        base = int(self.font_size.currentText())
        keys = tuple(self._panel_key(fit, base) for fit in visible_fits)
        retained = self._retained_grid
        if (retained is not None and retained[0] is self.plot_host
                and retained[1] == keys and self.plot_host.columns == columns
                and len(self.plot_host.row_splitters) == rows
                and all(key in self._panel_cache for key in keys)):
            widgets, hosts = [], []
            for rank, original in enumerate(visible_fits, start=start_rank):
                cached = self._panel_cache[self._panel_key(original, base)]
                fit = self.oriented_fit(original)
                if cached["fit"] is not fit:
                    self._update_render_panel(cached, fit, rank, base)
                cached["original"] = original
                cached["heading"].setText(self.panel_heading(fit, rank, base))
                widgets.append(cached["widget"])
                hosts.append(cached["panel"])
            self.plot_widgets, self.panel_hosts = widgets, hosts
            self._visible_panel_keys = list(keys)
            self._retained_grid = None
            self.plot_host.show()
            self._schedule_home_views()
            return
        grid = PanelGrid(columns, parent=self)
        grid.hide()
        grid.set_fixed_row_height(rows, 350)
        self._batch_state = {"generation": self._render_generation, "grid": grid,
            "fits": tuple(visible_fits), "position": 0, "base": base,
            "rank": start_rank, "entries": [], "replacements": {},
            "scroll": self.interactive_scroll.verticalScrollBar().value()}
        for control in (self.export_button, self.export_all_button, self.copy_button):
            control.setEnabled(False)
        if len(visible_fits) <= 3:
            self._render_next_panels()
        else:
            self.status.setText(f"Drawing 0 / {len(visible_fits)} plots…")
            self._render_timer.start()

    def _prepare_render_panel(self, original, rank, state):
        base = state["base"]
        key = self._panel_key(original, base)
        fit = self.oriented_fit(original)
        cached = self._panel_cache.get(key)
        if cached is not None:
            if key not in self._visible_panel_keys and cached["fit"] is not fit:
                self._update_render_panel(cached, fit, rank, base)
            return key, cached, original, fit, rank
        entry = self._create_interactive_panel(original, fit, rank, base, state["grid"])
        previous = next((self._panel_cache[visible] for visible in self._visible_panel_keys
                         if visible[:2] == key[:2]), None)
        if previous is not None:
            state["replacements"][key] = previous
        return key, entry, original, fit, rank

    def _render_next_panels(self):
        state = self._batch_state
        if state is None or not self._current_render(state):
            return
        try:
            count = len(state["fits"]) if len(state["fits"]) <= 3 else RENDER_BATCH_SIZE
            for _ in range(count):
                if state["position"] == len(state["fits"]):
                    break
                index = state["position"]
                prepared = self._prepare_render_panel(state["fits"][index], state["rank"] + index, state)
                if not self._current_render(state):
                    return
                state["entries"].append(prepared)
                state["position"] += 1
            if state["position"] == len(state["fits"]):
                self._publish_render(state)
            else:
                self.status.setText(f"Drawing {state['position']} / {len(state['fits'])} plots…")
                self._render_timer.start()
        except Exception as error:
            if self._current_render(state):
                self._background_draw_error(str(error))

    def _publish_render(self, state):
        if not self._current_render(state):
            return
        grid = state["grid"]
        entries = {key: entry for key, entry, _original, _fit, _rank in state["entries"]}
        # Retain zoom/pan/reset performed on the old canvas between batches.
        previous_views = {key: (cached["widget"].getViewBox().viewRange(), cached["home"], cached["fit"])
                          for key, cached in state["replacements"].items()}
        updates = self.interactive_scroll.updatesEnabled()
        self.interactive_scroll.setUpdatesEnabled(False)
        try:
            old = self.interactive_scroll.takeWidget()
            for key, cached in self._panel_cache.items():
                if entries.get(key) is cached:
                    continue
                cached["panel"].setParent(self)
                cached["panel"].hide()
                if key in entries:
                    cached["panel"].deleteLater()
            for key, entry, original, fit, rank in state["entries"]:
                if entry["fit"] is not fit:
                    self._update_render_panel(entry, fit, rank, state["base"])
                entry["original"] = original
                entry["heading"].setText(self.panel_heading(fit, rank, state["base"]))
                grid.add_panel(entry["panel"])
                entry["panel"].show()
            grid.complete_last_row(minimum_width=180)
            self._panel_cache.update(entries)
            self.plot_widgets = [entry["widget"] for entry in entries.values()]
            self.panel_hosts = [entry["panel"] for entry in entries.values()]
            self._visible_panel_keys = list(entries)
            self._retained_grid = None
            self.plot_host = grid
            self.interactive_scroll.setWidget(grid)
            grid.show()
            for key, (previous, home, old_fit) in previous_views.items():
                entry = entries[key]
                view = entry["widget"].getViewBox()
                if home is not None and not np.allclose(previous, home):
                    view.autoRange(padding=HOME_PADDING)
                    entry["home"] = view.viewRange()
                    fit = entry["fit"]
                    changed = (old_fit.x_name, old_fit.y_name) != (fit.x_name, fit.y_name)
                    view.setRange(xRange=previous[1] if changed else previous[0],
                                  yRange=previous[0] if changed else previous[1], padding=0)
            self.interactive_scroll.verticalScrollBar().setValue(state["scroll"])
            if old is not None and old is not grid:
                old.deleteLater()
            self._batch_state = None
            # Keep the existing bounded cache for parameter/ALL toggles.
            limit = max(24, 2 * int(self.page_size.currentText()))
            for key in list(self._panel_cache):
                if len(self._panel_cache) <= limit:
                    break
                if key not in entries:
                    self._panel_cache.pop(key)["panel"].deleteLater()
        finally:
            self.interactive_scroll.setUpdatesEnabled(updates)
        self._schedule_home_views()
        visible = bool(self.display_fits())
        for control in (self.export_button, self.export_all_button, self.copy_button):
            control.setEnabled(visible)
        self.update_fit_status()

    def _create_interactive_panel(self, original, fit, rank, base, owner):
        key = self._panel_key(original, base)
        widget = InteractivePlotWidget(background="w", frame_tick_length=3)
        if sip.isdeleted(self) or sip.isdeleted(owner):
            widget.deleteLater()
            raise RuntimeError('Correlation rendering cancelled')
        widget.setMinimumSize(180, 310)
        widget.setToolTip("Ctrl+scroll to zoom · Drag a box to zoom · Right-drag to pan · "
                          "Ordinary scrolling moves the page · "
                          "Double-click to fit this plot · Reset views restores all plots")
        plot = widget.getPlotItem()
        plot.setTitle(None)   # the QLabel above the plot owns the heading
        plot.showGrid(x=True, y=True, alpha=.18)
        plot.setLabel("bottom", fit.x_name, color="#30343b", size=f"{max(7, base - 1)}pt")
        plot.setLabel("left", fit.y_name, color="#30343b", size=f"{max(7, base - 1)}pt")
        plain_y_axes(widget)
        point_color, fit_color = correlation_colors(fit)
        heading = panel_title_label(self.panel_heading(fit, rank, base), base + 1)
        title_row = QWidget()
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 4, 0)
        title_layout.addWidget(heading, 1)
        swap_button = QToolButton()
        swap_button.setText("Swap X/Y")
        swap_button.setStyleSheet(
            "QToolButton { color: #30343b; background: #f3f4f6; border: 1px solid #cbd5e1; "
            "border-radius: 4px; padding: 3px 7px; } "
            "QToolButton:hover { background: #e2e8f0; } "
            "QToolButton:pressed { background: #cbd5e1; } "
            "QToolButton:focus { border-color: #356d91; }")
        swap_button.setAccessibleName(f"Swap X and Y for {fit.y_name} versus {fit.x_name}")
        swap_button.setToolTip("Swap this plot's axes and refit the same observations in the new direction.")
        policy = swap_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        swap_button.setSizePolicy(policy)
        swap_button.clicked.connect(lambda _checked=False, target=key:
            self.swap_axes(self._panel_cache[target]["original"]) if target in self._panel_cache else None)
        title_layout.addWidget(swap_button)
        # A QLabel keeps every title line in its own space; pyqtgraph's own
        # title reserves one line and printed the second over the plot.
        container = PlotPanel(title_row, widget, parent=owner)
        items = []
        if isinstance(fit, SourcePairFit):
            plot.addLegend(offset=(10, 8))
            for source in fit.sources:
                values = source.fit
                # Reuse the unchanged full scatter arrays during layout,
                # pan and zoom, as the Trend renderer already does.
                points = ResponsivePlotDataItem(
                    values.x, values.y, pen=None, symbol="o", symbolSize=5,
                    broadcast_uniform_symbols=True,
                    symbolPen=None,
                    symbolBrush=pg.mkBrush(point_color),
                    name=f"{source.name} points",
                )
                plot.addItem(points)
                order = np.argsort(values.x)
                line = plot.plot(
                    values.x[order], values.predicted[order],
                    pen=pg.mkPen(fit_color, width=2),
                    name=f"{source.name} fit",
                )
                items.append((points, line))
        else:
            points = pg.ScatterPlotItem(fit.x, fit.y, size=5, symbol="o", pen=None,
                                       brush=pg.mkBrush(point_color))
            plot.addItem(points)
            order = np.argsort(fit.x)
            line = pg.PlotDataItem(fit.x[order], fit.predicted[order],
                                   pen=pg.mkPen(fit_color, width=2))
            plot.addItem(line)
            items.append((points, line))
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
        return {"widget": widget, "panel": container, "heading": heading,
                                  "fit": fit, "original": original, "items": items, "home": None, "swap_button": swap_button}

    def remember_home_views(self):
        """Store the view each plot was drawn with, so Reset views can restore it exactly."""
        self.home_views = []
        for key in self._visible_panel_keys:
            cached = self._panel_cache[key]
            if cached["home"] is None:
                cached["home"] = cached["widget"].getViewBox().viewRange()
            self.home_views.append(cached["home"])

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
        if not self.ready or not self.display_fits():
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
        if not self.ready or not self.display_fits():
            return
        self._finish_interactive_render()
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
                f"Exported all {len(self.display_fits())} fits across {pages} pages: "
                f"{base_path.parent}"
            )
        except Exception as error:
            self.status.setText(f"Export failed: {error}")
        finally:
            self._export_dirty = True
            QApplication.restoreOverrideCursor()

    def copy_png(self):
        if not self.ready or not self.display_fits():
            return
        self._finish_interactive_render()
        _scale, requested = resolution_settings(self.resolution)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status.setText("Copying…")
        controls = []
        try:
            QApplication.processEvents()
            if not self.ready or self.plot_host is None:
                return
            cache_key = (requested, self.plot_host.width(), self.plot_host.height())
            if self._copy_image is None or self._copy_dpi != cache_key:
                controls = [(self._panel_cache[key]["swap_button"],
                             self._panel_cache[key]["swap_button"].isHidden()) for key in self._visible_panel_keys]
                for control, _hidden in controls:
                    control.hide()
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
            for control, hidden in controls:
                control.setHidden(hidden)
            QApplication.restoreOverrideCursor()
