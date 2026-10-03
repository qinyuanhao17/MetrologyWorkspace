"""Numeric trends over Die Seq: one continuous curve per parameter.

Every selected measurement set is appended to the same curve, so a column of
data reads as a single line. The wafer is written below the axis instead of
splitting the line into separate panels; the screen grid uses PyQtGraph so the
curve can be zoomed and panned smoothly, while Matplotlib stays the print
backend for Export / Copy PNG.
"""

from html import escape
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .appearance import (MAX_COPY_PIXELS, MAX_EXPORT_PIXELS, configure_resolution_combo,
                         export_dpi, panel_title_label, resolution_settings)
from .appearance import widget_to_qimage
from .array_plot import drawn_axes
from .data import number
from .map_selector import MapSelector
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel
from .settings import get_settings, save_settings
from .trend import MAGNITUDE_RATIO_LIMIT, overlay_spec, parse_unit


MAX_SEQUENCE_PLOTS = 30
HOME_PADDING = 0.06
LINE_COLOR = "#4472c4"
BOUNDARY_COLOR = "#d4d7dc"
MIN_LABEL_GAP_PIXELS = 30
COMPARE_COLOURS = (
    "#009E73",  # bluish green
    "#AA3377",  # reddish purple
    "#332288",  # indigo
    "#117733",  # green
    "#882255",  # wine
    "#999933",  # olive
    "#666666",  # neutral grey
)
COMPARE_SYMBOLS = ("s", "t", "d", "+", "x", "star", "p")
MATPLOTLIB_MARKERS = ("s", "^", "D", "P", "X", "*", "v")
COMPARE_CONTROL_WIDTH = 180


class CompareComboBox(QComboBox):
    """A compact comparison selector whose wheel changes choices directly."""

    def wheelEvent(self, event):
        if self.count() < 2 or not event.angleDelta().y():
            event.ignore()
            return
        step = -1 if event.angleDelta().y() > 0 else 1
        self.setCurrentIndex((self.currentIndex() + step) % self.count())
        event.accept()


def normalized_name(value):
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def find_column(frame, aliases):
    names = {normalized_name(column): column for column in frame.columns}
    return next((names[alias] for alias in aliases if alias in names), None)


def format_die(value):
    return f"{value:g}" if np.isfinite(value) else ""


def tick_spacing(extent, panel_pixels):
    """Sample step that leaves room for two-digit Die Seq labels side by side."""
    units_per_pixel = max(1.0, float(extent)) / max(1.0, float(panel_pixels))
    return max(1, ceil(MIN_LABEL_GAP_PIXELS * units_per_pixel))


def sampled_ticks(groups, tick_step, extent, panel_pixels):
    """Die Seq tick positions and labels that never sit on top of each other.

    The measurement sets are concatenated without a gap, so sampling every span
    end-to-end would place one wafer's last label directly beside the next
    wafer's first label. Spans therefore stop before their final sample (except
    the last span), and any label that would still land closer than a two-digit
    number's width is dropped.
    """
    positions, labels = [], []
    for index, group in enumerate(groups):
        die_values = group["frame"]["__die"].to_numpy(float)
        local = set(range(0, len(die_values), tick_step))
        if index == len(groups) - 1:
            local.add(len(die_values) - 1)
        for step in sorted(local):
            positions.append(float(group["positions"][step]))
            labels.append(format_die(die_values[step]))
    gap = MIN_LABEL_GAP_PIXELS * max(1.0, float(extent)) / max(1.0, float(panel_pixels))
    kept_positions, kept_labels = [], []
    for position, label in zip(positions, labels):
        if kept_positions and position - kept_positions[-1] < gap:
            continue
        kept_positions.append(position)
        kept_labels.append(label)
    return kept_positions, kept_labels


class SequencePage(QWidget):
    """One line-and-marker curve per selected numeric parameter."""

    def __init__(self):
        super().__init__(objectName="sequencePage")
        settings = get_settings()
        self.frame = pd.DataFrame()
        self.selection = {}
        self.ready = False
        self.has_drawn_once = False
        self.groups = []
        self.metrics = []
        self.panel_specs = []
        stored_overlay = settings.get("trend_overlay", {})
        self.overlay = self._normalise_overlay(stored_overlay)
        stored_source_overlay = settings.get("trend_source_overlay", ())
        self.source_overlay = self._normalise_source_overlay(stored_source_overlay)
        self._source_overlay_initialised = bool(stored_source_overlay)
        self.wafer_ticks = []
        self.home_views = []
        self.cells = set()
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        self.base_size = (1100, 650)
        self.wafer_column = None
        self.die_column = None
        self.compare_timer = QTimer(self)
        self.compare_timer.setSingleShot(True)
        self.compare_timer.setInterval(140)
        self.compare_timer.timeout.connect(self._apply_compare_changes)
        self.input_refresh_timer = QTimer(self, interval=180, singleShot=True)
        self.input_refresh_timer.timeout.connect(self.draw_plot)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.select_button = QPushButton("Select maps")
        self.select_button.setToolTip(
            "Drag to select curves · Ctrl to add / remove · Shift to extend"
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
        self.summary = QLabel("0 × 0", objectName="accent")
        toolbar.addWidget(self.summary)
        header.addLayout(toolbar)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("Columns", objectName="muted"))
        self.columns = QComboBox()
        self.columns.addItems(["1", "2"])
        self.columns.setFixedWidth(54)
        self.columns.currentIndexChanged.connect(self.relayout)
        options.addWidget(self.columns)
        self.reset_button = QPushButton("Reset views")
        self.reset_button.setToolTip(
            "Ctrl+scroll to zoom · Drag a box to zoom · Right-drag to pan.\n"
            "Ordinary scrolling moves the page.\n"
            "Reset returns every curve to its original range."
        )
        self.reset_button.clicked.connect(self.reset_views)
        options.addWidget(self.reset_button)
        options.addWidget(QLabel("Font", objectName="muted"))
        self.font_size = QComboBox()
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16"])
        self.font_size.setCurrentText(str(settings.get("font_size", 10)))
        self.font_size.setFixedWidth(58)
        self.font_size.currentTextChanged.connect(self.restyle)
        options.addWidget(self.font_size)
        options.addWidget(QLabel("Resolution", objectName="muted"))
        self.resolution = QComboBox()
        configure_resolution_combo(self.resolution)
        self.resolution.setCurrentIndex(max(0, self.resolution.findText(settings.get("resolution", "High"))))
        self.resolution.currentIndexChanged.connect(self.change_resolution)
        options.addWidget(self.resolution)
        self.axis_ratio_label = QLabel("Y axes", objectName="muted")
        options.addWidget(self.axis_ratio_label)
        self.axis_mode = QComboBox()
        for label, mode in (("Auto", "auto"), ("Always 2", "dual"),
                            ("Always 1", "single")):
            self.axis_mode.addItem(label, mode)
        self.axis_mode.setToolTip(
            "Auto: split different units or curves exceeding the median-value "
            "ratio. Always 2/1 overrides that decision for comparisons."
        )
        self.axis_mode.currentIndexChanged.connect(self.refresh_axis_split)
        options.addWidget(self.axis_mode)
        self.axis_ratio = QDoubleSpinBox()
        self.axis_ratio.setDecimals(3)
        self.axis_ratio.setRange(1.0, 1_000_000.0)
        self.axis_ratio.setSingleStep(0.1)
        self.axis_ratio.setValue(MAGNITUDE_RATIO_LIMIT)
        self.axis_ratio.setSuffix("×")
        self.axis_ratio.setFixedWidth(85)
        self.axis_ratio.setToolTip(
            "Auto mode: put a comparison on a second Y axis when the ratio "
            "of median absolute values exceeds this threshold. Decimal "
            "values are allowed. Saved with the Matching Workbook (.wkb)."
        )
        self.axis_ratio.valueChanged.connect(self.refresh_axis_split)
        options.addWidget(self.axis_ratio)
        options.addStretch()
        header.addLayout(options)
        layout.addLayout(header)

        self.figure = Figure(figsize=(11, 6.5), dpi=100, facecolor="white")
        FigureCanvasAgg(self.figure)
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_png)
        self.copy_button.setToolTip("Copy the full plot grid as a PNG. Ctrl+C works while this tab is active.")

        self.plot_host = None
        self.interactive_scroll = QScrollArea()
        self.interactive_scroll.setWidgetResizable(True)
        self.interactive_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.stack = QStackedWidget()
        self.empty = QLabel("Select measurement sets and numeric parameters in the Data tab.",
                            objectName="subtitle")
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
        self.status = QLabel("Choose measurement sets and numeric parameters in Data, then select the curves to draw.",
                             objectName="hint")
        layout.addWidget(self.status)
        self.selector.changed.connect(self.selector_changed)
        self.invalidate()

    def draw_state(self):
        """Return the last successful curve-box selection for WKB persistence."""
        cells = self.selector.selected_cells() if self.has_drawn_once else set()
        return {
            "enabled": self.has_drawn_once,
            "cells": tuple(sorted(cells)),
        }

    def restore_draw_state(self, state):
        """Restore surviving curve boxes and redraw without another click."""
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
        self.cells = set(cells)
        self.selector.set_selected_cells(cells, notify=False)
        self.invalidate()
        self.draw_plot()

    def axis_ratio_limit(self):
        """Return the automatic second-axis threshold as a decimal number."""
        return float(self.axis_ratio.value())

    def axis_mode_value(self):
        """Return auto, dual, or single for compared Trend curves."""
        return self.axis_mode.currentData() or "auto"

    def restore_axis_mode(self, mode):
        """Restore a persisted axis mode without accepting unknown values."""
        index = self.axis_mode.findData(mode)
        if index >= 0:
            self.axis_mode.setCurrentIndex(index)
        self.axis_ratio.setEnabled(self.axis_mode_value() == "auto")

    def restore_axis_ratio(self, value):
        """Restore the second-axis threshold stored in a Matching Workbook."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if not 1.0 <= value <= self.axis_ratio.maximum():
            return
        self.axis_ratio.setValue(value)

    def refresh_axis_split(self, *_args):
        """Re-split the axes after the engineer changes the threshold."""
        self.axis_ratio.setEnabled(self.axis_mode_value() == "auto")
        if self.ready:
            self.draw_plot()

    def set_axis_ratio_control_visible(self, visible):
        """Hide the in-page control when the Match Workbook menu owns it."""
        self.axis_ratio_label.setVisible(visible)
        self.axis_mode.setVisible(visible)
        self.axis_ratio.setVisible(visible)

    def set_input(self, frame, selection):
        self.frame = frame
        self.selection = selection.copy()
        self.wafer_column = find_column(frame, ("waferid", "wafer", "waferno"))
        self.die_column = find_column(frame, ("dieseq", "diesequence", "diesequenceno", "dieid"))
        self.selector.set_array(
            selection.get("wafers", []), selection.get("metrics", []),
            selection.get("labels"), selection.get("available_cells"),
        )
        self.invalidate()
        if (self.has_drawn_once and not self.selector.pending_draw
                and self.selector.selected_cells()):
            self.input_refresh_timer.start()

    def selector_changed(self):
        """Changed curve boxes wait for the explicit Draw selected click."""
        self.invalidate()

    def show_selector(self):
        """Return to the box grid so another set of curves can be chosen."""
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        self.empty.setText("Select measurement sets and numeric parameters in the Data tab "
                           "to create boxes.")
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)

    def invalidate(self):
        self.input_refresh_timer.stop()
        self.ready = False
        self.groups = []
        self.metrics = []
        self.panel_specs = []
        self.wafer_ticks = []
        self.export_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.figure.clear()
        self.draw_canvas_message("Select one or more boxes, then click Draw selected")
        self.clear_interactive("Select one or more boxes, then click Draw selected")
        wafers = self.selection.get("wafers", [])
        metrics = self.selection.get("metrics", [])
        rows, columns = len(wafers), len(metrics)
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        if not available:
            self.empty.setText("Select measurement sets and numeric parameters in the Data tab "
                               "to create boxes.")
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.selector_panel)
        count = len(self.selector.selected_cells())
        self.summary.setText(f"{count} / {rows * columns} selected  ·  {rows} × {columns}")
        self.status.setText("Drag across the curves you want, then click Draw selected.")

    def draw_canvas_message(self, message):
        """Keep the export figure readable when there is nothing to plot yet."""
        size = max(15, int(self.font_size.currentText()) + 3)
        self.figure.text(.5, .5, message, ha="center", va="center", color="#746b7e", fontsize=size)

    def _parts(self):
        wafers = self.selection.get("wafers", [])
        if "groups" in self.selection:
            return [(key, self.frame.iloc[list(self.selection["groups"].get(key, ()))]) for key in wafers]
        ids = self.frame[self.selection["wafer_column"]].astype(str).str.strip()
        return [(key, self.frame[ids == key]) for key in wafers]

    def _sequence_groups(self, cells):
        """Append every measurement set to one axis; nothing is split off."""
        groups, cursor = [], 0
        spans = {}
        labels = self.selection.get("labels", {})
        sources = self.selection.get("sources", ())
        source_by_key = {key: source for source in sources for key in source.get("keys", ())}
        drawn_keys = {key for key, _metric in cells}
        parts = [(key, part) for key, part in self._parts()
                 if key in drawn_keys and not part.empty]
        if sources:
            # Keep table order even when the two tabs select different wafers.
            parts.sort(key=lambda pair: pair[1].index.min() - min(
                source_by_key.get(pair[0], {}).get("rows") or (0,)
            ))
        for key, part in parts:
            ordered = part.assign(__die=number(part[self.die_column])).dropna(subset=["__die"])
            ordered = ordered.sort_values("__die", kind="stable")
            if ordered.empty:
                continue
            source = source_by_key.get(key)
            # Ref and Raw are row-aligned tables. The same measurement must
            # occupy the same span in both sources, not overlap other wafers.
            span_key = key[1] if source is not None else key
            if span_key not in spans:
                spans[span_key] = cursor
                cursor += len(ordered)
            start = spans[span_key]
            positions = np.arange(start, start + len(ordered), dtype=float)
            wafer_values = ordered[self.wafer_column].fillna("").astype(str).str.strip()
            wafer_id = next((value for value in wafer_values if value), "")
            if not wafer_id:
                wafer_id = str(labels.get(key, key)).splitlines()[0]
            groups.append({"key": key, "wafer": wafer_id, "frame": ordered,
                           "positions": positions, "center": float(positions.mean()),
                           "start": float(np.min(positions)),
                           "stop": float(np.max(positions)),
                           "source": source})
        return groups, cursor

    @staticmethod
    def _format_die(value):
        return f"{value:g}" if np.isfinite(value) else ""

    def _panel_specs(self, metrics, groups):
        """Return panels in the user's requested source-major order."""
        sources = self.selection.get("sources", ())
        if not sources:
            base = [{"metric": metric, "source": None} for metric in metrics]
        else:
            base = []
            for source in sources:
                for metric in metrics:
                    if any(
                        group.get("source", {}).get("name") == source["name"]
                        and (group["key"], metric) in self.cells
                        for group in groups
                    ):
                        base.append({"metric": metric, "source": source})
        return [
            {
                **panel,
                "comparisons": tuple(
                    self.source_overlay.get(
                        (panel["source"]["name"], panel["metric"]), ()
                    ) if panel["source"] is not None
                    else self.overlay.get(panel["metric"], ())
                ),
            }
            for panel in base
        ]

    @staticmethod
    def _normalise_overlay(stored):
        """Accept legacy ``{primary: secondary}`` and the new list format."""
        if not isinstance(stored, dict):
            return {}
        normalised = {}
        for primary, value in stored.items():
            values = value if isinstance(value, (list, tuple)) else (value,)
            unique = []
            for secondary in values:
                secondary = str(secondary)
                if secondary != str(primary) and secondary not in unique:
                    unique.append(secondary)
            if unique:
                normalised[str(primary)] = unique
        return normalised

    @staticmethod
    def _normalise_source_overlay(stored):
        """Read source-aware comparisons from plain YAML-safe records."""
        if isinstance(stored, dict):
            stored = stored.get("panels", ())
        if not isinstance(stored, (list, tuple)):
            return {}
        normalised = {}
        for record in stored:
            if not isinstance(record, dict):
                continue
            source = str(record.get("source", "")).strip()
            metric = str(record.get("metric", "")).strip()
            if not source or not metric:
                continue
            comparisons = []
            for comparison in record.get("comparisons", ()):
                if not isinstance(comparison, dict):
                    continue
                compare_source = str(comparison.get("source", "")).strip()
                compare_metric = str(comparison.get("metric", "")).strip()
                series = (compare_source, compare_metric)
                if (compare_source and compare_metric
                        and series != (source, metric)
                        and series not in comparisons):
                    comparisons.append(series)
            if comparisons:
                normalised[(source, metric)] = comparisons
        return normalised

    def _available_source_series(self):
        """Return checked (table, parameter) pairs in Ref/Raw tab order."""
        available = []
        for source in self.selection.get("sources", ()):
            source_name = source["name"]
            for metric in self.metrics:
                if any(
                    group.get("source", {}).get("name") == source_name
                    and (group["key"], metric) in self.cells
                    for group in self.groups
                ):
                    available.append((source_name, metric))
        return available

    def _migrate_source_overlay(self):
        """Use legacy same-table comparisons once when source state is absent."""
        if self._source_overlay_initialised:
            return
        available = set(self._available_source_series())
        for source_name, primary in available:
            comparisons = [
                (source_name, secondary)
                for secondary in self.overlay.get(primary, ())
                if (source_name, secondary) in available
            ]
            if comparisons:
                self.source_overlay[(source_name, primary)] = comparisons
        self._source_overlay_initialised = True

    def _prune_overlay(self, metrics):
        self.overlay = self._normalise_overlay(self.overlay)
        available = set(metrics)
        checked = {metric for _key, metric in self.cells}
        self.overlay = {
            primary: [secondary for secondary in secondaries
                      if secondary in available and secondary in checked
                      and secondary != primary]
            for primary, secondaries in self.overlay.items()
            if primary in available and primary in checked
        }
        self.overlay = {primary: values for primary, values in self.overlay.items()
                        if values}
        if self.selection.get("sources"):
            self._migrate_source_overlay()
            available_series = set(self._available_source_series())
            self.source_overlay = {
                base: [series for series in comparisons
                       if series in available_series and series != base]
                for base, comparisons in self.source_overlay.items()
                if base in available_series
            }
            self.source_overlay = {
                base: comparisons
                for base, comparisons in self.source_overlay.items()
                if comparisons
            }

    def _persist_overlay(self):
        if getattr(self, "document_scoped", False):
            return
        try:
            save_settings({
                "trend_overlay": {
                    primary: list(secondaries)
                    for primary, secondaries in self.overlay.items()
                },
                "trend_source_overlay": {
                    "version": 1,
                    "panels": [
                        {
                            "source": source,
                            "metric": metric,
                            "comparisons": [
                                {"source": compare_source,
                                 "metric": compare_metric}
                                for compare_source, compare_metric in comparisons
                            ],
                        }
                        for (source, metric), comparisons
                        in self.source_overlay.items()
                    ],
                },
            })
        except OSError as error:
            self.status.setText(f"Could not save Trend comparison: {error}")

    def set_overlay(self, primary, secondary, primary_source=None,
                    secondary_source=None):
        """Add one comparison curve without removing either parameter panel."""
        primary, secondary = str(primary), str(secondary)
        if primary_source is not None:
            base = (str(primary_source), primary)
            comparison = (str(secondary_source or primary_source), secondary)
            available = set(self._available_source_series())
            if base not in available or comparison not in available or base == comparison:
                self.status.setText("Choose another checked table and parameter.")
                return False
            comparisons = self.source_overlay.setdefault(base, [])
            if comparison not in comparisons:
                comparisons.append(comparison)
            self._source_overlay_initialised = True
            self._persist_overlay()
            self.draw_plot()
            return True
        if primary == secondary or primary not in self.metrics or secondary not in self.metrics:
            self.status.setText("Choose two different selected parameters.")
            return False
        comparisons = self.overlay.setdefault(primary, [])
        if secondary in comparisons:
            return True
        comparisons.append(secondary)
        self._persist_overlay()
        self.draw_plot()
        return True

    def unlink_overlay(self, metric):
        """Compatibility helper: remove every comparison from one base panel."""
        metric = str(metric)
        if metric not in self.overlay:
            return False
        self.overlay.pop(metric, None)
        self._persist_overlay()
        self.draw_plot()
        return True

    def remove_overlay(self, primary, secondary):
        comparisons = self.overlay.get(str(primary), [])
        if str(secondary) not in comparisons:
            return False
        comparisons.remove(str(secondary))
        if not comparisons:
            self.overlay.pop(str(primary), None)
        self._persist_overlay()
        self.draw_plot()
        return True

    def _overlay_candidates(self, metric, current=None, source=None):
        if source is not None:
            base = (str(source), str(metric))
            selected = set(self.source_overlay.get(base, ()))
            return [
                series for series in self._available_source_series()
                if series != base
                and (series == current or series not in selected)
            ]
        checked = {name for _key, name in self.cells}
        selected = set(self.overlay.get(metric, ()))
        return [name for name in self.metrics
                if name != metric and name in checked
                and (name == current or name not in selected)]

    def add_compare(self, metric, source=None):
        candidates = self._overlay_candidates(metric, source=source)
        if not candidates:
            self.status.setText(
                "No other checked table and parameter is available for comparison."
                if source is not None
                else "No other checked parameter is available for comparison."
            )
            return False
        if source is not None:
            compare_source, compare_metric = candidates[0]
            return self.set_overlay(
                metric, compare_metric, source, compare_source
            )
        return self.set_overlay(metric, candidates[0])

    def replace_overlay(self, primary, index, selected, source=None):
        if source is not None:
            base = (str(source), str(primary))
            comparisons = self.source_overlay.get(base, [])
            selected = tuple(selected) if selected is not None else ()
            if (not 0 <= int(index) < len(comparisons)
                    or len(selected) != 2 or selected == base):
                return False
            index = int(index)
            if selected in comparisons and comparisons[index] != selected:
                comparisons.pop(index)
            else:
                comparisons[index] = selected
            self.compare_timer.start()
            return True
        primary, selected = str(primary), str(selected)
        comparisons = self.overlay.get(primary, [])
        if not 0 <= int(index) < len(comparisons) or selected == primary:
            return False
        index = int(index)
        if selected in comparisons and comparisons[index] != selected:
            comparisons.pop(index)
        else:
            comparisons[index] = selected
        self.compare_timer.start()
        return True

    def remove_overlay_at(self, primary, index, source=None):
        if source is not None:
            base = (str(source), str(primary))
            comparisons = self.source_overlay.get(base, [])
            if not 0 <= int(index) < len(comparisons):
                return False
            comparisons.pop(int(index))
            if not comparisons:
                self.source_overlay.pop(base, None)
            self._persist_overlay()
            self.draw_plot()
            return True
        comparisons = self.overlay.get(str(primary), [])
        if not 0 <= int(index) < len(comparisons):
            return False
        comparisons.pop(int(index))
        if not comparisons:
            self.overlay.pop(str(primary), None)
        self._persist_overlay()
        self.draw_plot()
        return True

    def _apply_compare_changes(self):
        self._persist_overlay()
        if self.ready:
            self.draw_plot()

    def build_overlay_control(self, metric, comparisons, source=None):
        """Build the Add Compare button and zero or more wheelable selectors."""
        control = QFrame(objectName="compareControls")
        control.setFrameShape(QFrame.Shape.StyledPanel)
        control.setFixedWidth(COMPARE_CONTROL_WIDTH)
        control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(control)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        add = QPushButton("Add Compare", objectName="subtle")
        add.setFixedHeight(28)
        source_name = source["name"] if source is not None else None
        available = bool(self._overlay_candidates(metric, source=source_name))
        add.setEnabled(available)
        add.setToolTip(
            "Add another selected parameter. Scroll a selector to switch quickly."
            if available else "No other selected parameter is available."
        )
        add.clicked.connect(
            lambda _checked=False, name=metric, table=source_name:
            self.add_compare(name, table)
        )
        layout.addWidget(add)
        for compare_index, comparison in enumerate(comparisons):
            if source_name is None:
                compare_source, secondary = None, comparison
            else:
                compare_source, secondary = comparison
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(3)
            combo = CompareComboBox()
            combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            combo.setMinimumWidth(0)
            combo.setToolTip("Scroll to switch the comparison parameter.")
            current = comparison if source_name is not None else secondary
            for candidate in self._overlay_candidates(
                    metric, current, source_name):
                if source_name is None:
                    combo.addItem(str(candidate), candidate)
                else:
                    candidate_source, candidate_metric = candidate
                    combo.addItem(
                        f"{candidate_source} · {candidate_metric}", candidate
                    )
            current_index = next((
                index for index in range(combo.count())
                if combo.itemData(index) == current
            ), -1)
            combo.setCurrentIndex(current_index)
            combo.currentIndexChanged.connect(
                lambda _choice, selector=combo, primary=metric,
                index=compare_index, table=source_name:
                self.replace_overlay(primary, index, selector.currentData(), table)
            )
            remove = QPushButton("×", objectName="subtle")
            remove.setFixedSize(28, 28)
            remove.setToolTip(
                f"Remove {self._legend_label(self._source(compare_source), secondary)} "
                "from this comparison."
            )
            remove.clicked.connect(
                lambda _checked=False, primary=metric, index=compare_index,
                table=source_name: self.remove_overlay_at(primary, index, table)
            )
            row_layout.addWidget(combo, 1)
            row_layout.addWidget(remove)
            layout.addWidget(row)
        # The frame stretches to the plot's height; keep the controls together
        # at the top instead of spreading them down the column.
        layout.addStretch(1)
        return control

    def draw_plot(self, *_):
        self.input_refresh_timer.stop()
        try:
            metrics = self.selection.get("metrics", [])
            wafers = self.selection.get("wafers", [])
            if self.frame.empty:
                raise ValueError("Load or paste a table in Data first.")
            if not wafers or not metrics:
                raise ValueError("Select at least one measurement set and one numeric parameter in Data.")
            if len(metrics) > MAX_SEQUENCE_PLOTS:
                raise ValueError(f"Select up to {MAX_SEQUENCE_PLOTS} numeric parameters for Die Seq plots.")
            if not self.wafer_column:
                raise ValueError("A Wafer ID column is required for this plot.")
            if not self.die_column:
                raise ValueError("A Die Seq column is required for this plot.")
            cells = self.selector.selected_cells()
            if not cells:
                raise ValueError("Select at least one curve box before drawing.")
            groups, extent = self._sequence_groups(cells)
            if not groups:
                raise ValueError("The selected measurement sets contain no valid Die Seq values.")

            drawn_wafers, drawn_metrics = drawn_axes(wafers, metrics, cells)
            if not drawn_metrics:
                raise ValueError("Select at least one curve box before drawing.")
            self.cells = set(cells)
            self.groups, self.metrics = groups, list(drawn_metrics)
            self._prune_overlay(self.metrics)
            self.panel_specs = self._panel_specs(self.metrics, groups)
            # Keep every panel on the same X frame, but shrink it to the spans
            # that actually carry a drawn curve instead of reserving blank
            # space for measurement sets the user left out.
            used = [group for group in groups
                    if any((group["key"], metric) in cells for metric in self.metrics)]
            self.view_groups = used or groups
            axis_groups = {}
            for group in self.view_groups:
                key = group["key"][1] if group["source"] is not None else group["key"]
                axis_groups.setdefault(key, group)
            self.axis_groups = sorted(axis_groups.values(), key=lambda group: group["start"])
            self.x_range = (
                min(group["start"] for group in self.axis_groups) - .5,
                max(group["stop"] for group in self.axis_groups) + .5,
            )
            total_points = sum(len(group["frame"]) for group in groups)
            columns = min(int(self.columns.currentText()), len(self.panel_specs))
            rows = ceil(len(self.panel_specs) / columns)
            panel_width = max(900, min(1900, 180 + 6 * total_points))
            self.base_size = (columns * panel_width, rows * 350 + 30)
            self.panel_pixels = max(320, panel_width - 150)
            self._export_dirty = True
            self._copy_image = None
            self._copy_dpi = None
            self.render_interactive(self.panel_specs, groups, columns, rows)
            self.ready = True
            self.has_drawn_once = True
            self.selector.pending_draw = False
            self.export_button.setEnabled(True)
            self.copy_button.setEnabled(True)
            self.stack.setCurrentWidget(self.interactive_scroll)
            comparison_state = (
                self.source_overlay
                if self.selection.get("sources") else self.overlay
            )
            comparison_count = sum(map(len, comparison_state.values()))
            comparison = (f" · {comparison_count} comparison"
                          if comparison_count else "")
            self.status.setText(f"{len(self.metrics)} of {len(metrics)} parameters · "
                                f"{len(drawn_wafers)} of {len(wafers)} measurement sets · "
                                f"{total_points} Die Seq positions{comparison}.")
            if self._uses_second_axis():
                self.status.setText(
                    self.status.text()
                    + " 已使用第二根 Y 轴，交叉点无物理含义。"
                )
            if self._has_mixed_units():
                self.status.setText(
                    self.status.text()
                    + " 单 Y 轴包含不同单位，仅供查看，不可直接比较数值。"
                )
            missing = self._missing_overlay_metrics()
            if missing:
                self.status.setText(
                    self.status.text()
                    + f" No valid values for: {', '.join(missing)}."
                )
        except (ValueError, KeyError) as error:
            self.invalidate()
            self.status.setText(str(error))

    def _metric_values(self, metric, groups):
        values = [number(group["frame"][metric]).to_numpy(float) for group in groups]
        return np.concatenate(values) if values else np.asarray([], dtype=float)

    def _overlay_specs(self):
        for panel in self.panel_specs:
            chosen = self._chosen_groups(panel, self.groups)
            for comparison in panel.get("comparisons", ()):
                compare_source, secondary = self._comparison_series(
                    panel, comparison
                )
                secondary_groups = self._series_groups(
                    compare_source, secondary, self.groups
                )
                spec = overlay_spec(
                    panel["metric"], secondary,
                    self._metric_values(panel["metric"], chosen),
                    self._metric_values(secondary, secondary_groups),
                    ratio_limit=self.axis_ratio_limit(),
                    axis_mode=self.axis_mode_value(),
                )
                yield spec

    def _uses_second_axis(self):
        return any(spec["kind"] == "second-axis"
                   for spec in self._overlay_specs())

    def _has_mixed_units(self):
        return any(spec["mixed_units"] for spec in self._overlay_specs())

    def _missing_overlay_metrics(self):
        missing = []
        for panel in self.panel_specs:
            for comparison in panel.get("comparisons", ()):
                compare_source, secondary = self._comparison_series(
                    panel, comparison
                )
                groups = self._series_groups(
                    compare_source, secondary, self.groups
                )
                values = self._metric_values(secondary, groups)
                label = self._legend_label(compare_source, secondary)
                if not np.isfinite(values).any() and label not in missing:
                    missing.append(label)
        return missing

    def _chosen_groups(self, panel, groups):
        source = panel.get("source")
        source_name = (source or {}).get("name")
        metric = panel["metric"]
        return [
            group for group in groups
            if (group["key"], metric) in self.cells
            and (source is None
                 or group.get("source", {}).get("name") == source_name)
        ]

    def _source(self, source):
        """Resolve a source name to the metadata supplied by Ref/Raw tabs."""
        if source is None or isinstance(source, dict):
            return source
        return next((
            candidate for candidate in self.selection.get("sources", ())
            if candidate.get("name") == str(source)
        ), {"name": str(source)})

    def _series_groups(self, source, metric, groups):
        source = self._source(source)
        source_name = (source or {}).get("name")
        return [
            group for group in groups
            if (group["key"], metric) in self.cells
            and (source is None
                 or group.get("source", {}).get("name") == source_name)
        ]

    def _comparison_series(self, panel, comparison):
        if panel.get("source") is None:
            return None, str(comparison)
        source_name, metric = comparison
        return self._source(source_name), str(metric)

    @staticmethod
    def _compare_color(index):
        return COMPARE_COLOURS[index % len(COMPARE_COLOURS)]

    @staticmethod
    def _legend_label(source, metric):
        return f"{source['name']} · {metric}" if source is not None else str(metric)

    @staticmethod
    def _source_line_style(source, qt=False):
        raw = source is not None and source.get("name") == "Raw Data"
        if qt:
            return Qt.PenStyle.DashLine if raw else Qt.PenStyle.SolidLine
        return "--" if raw else "-"

    @staticmethod
    def _axis_label(metric, unit):
        if unit is None:
            return f"{metric} (unit?)"
        return str(metric) if parse_unit(metric) == unit else f"{metric} [{unit}]"

    def ensure_export_figure(self):
        """Build the Matplotlib export mirror only when Export / Copy needs it."""
        if self._export_dirty or not self.figure.axes:
            self.build_export_figure(self.panel_specs or [], self.view_groups or self.groups)
            self._export_dirty = False

    def build_export_figure(self, panels, groups):
        """Matplotlib mirror of the on-screen grid, used for Export / Copy PNG."""
        columns = min(int(self.columns.currentText()), len(panels))
        rows = ceil(len(panels) / columns)
        width, height = self.base_size
        base = int(self.font_size.currentText())
        total_points = sum(len(group["frame"]) for group in groups)
        visible = self.x_range[1] - self.x_range[0]
        tick_step = tick_spacing(visible, self.panel_pixels)
        self.figure.clear()
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        axes = self.figure.subplots(rows, columns, squeeze=False)
        max_secondary_axes = 0
        for ax, panel in zip(axes.flat, panels):
            metric, panel_source = panel["metric"], panel["source"]
            comparisons = panel.get("comparisons", ())
            chosen = self._chosen_groups(panel, groups)
            source_mode = bool(self.selection.get("sources"))
            wafer_texts = []
            tick_positions, tick_labels = sampled_ticks(
                self.axis_groups, tick_step, visible, self.panel_pixels
            )
            for group_index, group in enumerate(self.axis_groups):
                wafer_texts.append(ax.text(group["center"], -.18, group["wafer"],
                                            transform=ax.get_xaxis_transform(), ha="center", va="top",
                                            fontsize=max(6, base - 2), color="#5f6368", clip_on=False))
                if group_index:
                    ax.axvline(group["start"] - .5, color=BOUNDARY_COLOR, linewidth=.8, zorder=0)

            def plot_metric(target, name, color, label, curve_groups, marker="o"):
                if not curve_groups:
                    return [], np.asarray([])
                positions = np.concatenate([group["positions"] for group in curve_groups])
                values = self._metric_values(name, curve_groups)
                lines = target.plot(
                    positions, values, color=color,
                    linestyle=self._source_line_style(curve_groups[0].get("source")),
                    linewidth=1.35, marker=marker, markersize=3.8,
                    markerfacecolor=color, label=label,
                )
                return lines, values

            primary_color = (panel_source["color"]
                             if source_mode and panel_source is not None else LINE_COLOR)
            primary_label = self._legend_label(panel_source, metric)
            primary_lines, values = plot_metric(
                ax, metric, primary_color, primary_label, chosen
            )
            legend_lines = list(primary_lines[:1])
            secondary_axes = []
            mixed_units = set()
            for compare_index, comparison in enumerate(comparisons):
                compare_source, secondary = self._comparison_series(
                    panel, comparison
                )
                secondary_groups = self._series_groups(
                    compare_source, secondary, groups
                )
                secondary_values = self._metric_values(
                    secondary, secondary_groups
                )
                spec = overlay_spec(
                    metric, secondary, values, secondary_values,
                    ratio_limit=self.axis_ratio_limit(),
                    axis_mode=self.axis_mode_value(),
                )
                if spec["mixed_units"]:
                    mixed_units.update((spec["unit"], spec["secondary_unit"]))
                secondary_color = self._compare_color(compare_index)
                target = ax
                if spec["kind"] == "second-axis":
                    twin = ax.twinx()
                    twin.spines.right.set_position(
                        ("axes", 1.02 + .08 * len(secondary_axes))
                    )
                    twin.set_ylabel(
                        self._axis_label(secondary, spec["secondary_unit"]),
                        color=secondary_color, fontsize=max(7, base - 1),
                    )
                    twin.tick_params(axis="y", colors=secondary_color,
                                     labelsize=max(6, base - 2))
                    target = twin
                    secondary_axes.append(twin)
                secondary_label = self._legend_label(compare_source, secondary)
                secondary_lines, _secondary_values = plot_metric(
                    target, secondary, secondary_color, secondary_label,
                    secondary_groups,
                    MATPLOTLIB_MARKERS[compare_index % len(MATPLOTLIB_MARKERS)],
                )
                legend_lines.extend(secondary_lines[:1])
            if comparisons or source_mode:
                ax.legend(
                    legend_lines, [line.get_label() for line in legend_lines],
                    fontsize=max(6, base - 2), frameon=False,
                    ncol=min(3, len(legend_lines)),
                )
            if not np.isfinite(values).any():
                ax.text(.5, .5, "No valid numeric values", transform=ax.transAxes,
                        ha="center", va="center", fontsize=max(11, base))
            title = self._legend_label(panel_source, metric)
            ax.set_title(title, fontsize=base + 1, fontweight="semibold", pad=8)
            ylabel_options = {"fontsize": max(7, base - 1)}
            if comparisons:
                ylabel_options["color"] = primary_color
            ax.set_ylabel(
                ("Mixed units (" + " / ".join(sorted(mixed_units)) + ")"
                 if mixed_units else
                 self._axis_label(metric, parse_unit(metric)) if comparisons else "Value"),
                **ylabel_options,
            )
            if comparisons:
                ax.tick_params(axis="y", colors=primary_color)
            ax.set_xlabel("Die Seq", fontsize=max(7, base - 1), labelpad=30)
            ax.set_xlim(*self.x_range)
            ax.set_xticks(tick_positions, tick_labels, fontsize=max(6, base - 2))
            ax.tick_params(axis="y", labelsize=max(6, base - 2))
            ax.grid(axis="y", color="#d6d8dc", linewidth=.7)
            ax.set_axisbelow(True)
            ax._wafer_group_labels = wafer_texts
            ax._die_sequence_values = [group["frame"]["__die"].tolist() for group in groups]
            ax._wafer_ids = [group["wafer"] for group in groups]
            for spine in ax.spines.values():
                spine.set_color("#c9ccd1")
            for twin in secondary_axes:
                twin.set_xlim(*self.x_range)
                twin._wafer_group_labels = wafer_texts
                twin._die_sequence_values = ax._die_sequence_values
                twin._wafer_ids = ax._wafer_ids
            max_secondary_axes = max(max_secondary_axes, len(secondary_axes))
        for ax in axes.flat[len(panels):]:
            ax.set_axis_off()
        right = max(.72, .985 - .075 * max_secondary_axes)
        # Reserve physical space for Die Seq and the wafer labels, including
        # short one-panel exports where a percentage margin is too small.
        bottom = min(.35, (95 + 3 * max(0, base - 10)) / height)
        self.figure.subplots_adjust(left=.065, right=right, top=.965, bottom=bottom,
                                    hspace=.64, wspace=.18)

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

    def render_interactive(self, panels, groups, columns, rows):
        """Render every base panel plus any explicit comparison curves."""
        # Read the offset before the old grid is detached; replacing the grid
        # resets the scroll bar.
        previous_scroll = self.interactive_scroll.verticalScrollBar().value()
        self.clear_interactive()
        base = int(self.font_size.currentText())
        panel_height = 320
        grid = PanelGrid(columns)
        grid.set_minimum_row_height(rows, panel_height)
        self.wafer_ticks = [(group["center"], group["wafer"]) for group in self.axis_groups]
        for panel in panels:
            metric, panel_source = panel["metric"], panel["source"]
            comparisons = panel.get("comparisons", ())
            widget = InteractivePlotWidget(background="w", auto_x_range=self.x_range)
            widget.setMinimumSize(360, 280)
            widget.setToolTip("Ctrl+scroll to zoom · Drag a box to zoom · Right-drag to pan · "
                              "Ordinary scrolling moves the page · "
                              "Double-click to fit this curve · Reset views restores all curves")
            plot = widget.getPlotItem()
            plot.setTitle(None)   # the QLabel above the plot owns the heading
            plot.showGrid(x=False, y=True, alpha=.18)
            plot.setLabel("left", "Value", color="#30343b", size=f"{max(7, base - 1)}pt")
            plot.setLabel("bottom", "Die Seq", color="#30343b",
                          size=f"{max(7, base - 1)}pt")
            title = self._legend_label(panel_source, metric)
            heading = panel_title_label(f"<b>{escape(title)}</b>", base + 1)
            container = PlotPanel(
                heading, widget,
                side_widget=self.build_overlay_control(
                    metric, comparisons, panel_source
                ),
            )
            chosen = self._chosen_groups(panel, groups)
            axis = plot.getAxis("bottom")
            source_mode = bool(self.selection.get("sources"))

            def curve(target, name, color, legend, label, curve_groups, symbol="o"):
                if not curve_groups:
                    return None
                positions = np.concatenate([group["positions"] for group in curve_groups])
                values = self._metric_values(name, curve_groups)
                pen = pg.mkPen(
                    color, width=1.6,
                    style=self._source_line_style(curve_groups[0].get("source"), qt=True),
                )
                item = pg.PlotDataItem(
                    positions, values, connect="finite", pen=pen,
                    symbol=symbol, symbolSize=5, symbolPen=pg.mkPen(color),
                    symbolBrush=pg.mkBrush(color), name=label,
                )
                target.addItem(item)
                if legend is not None and target is not plot:
                    legend.addItem(item, label)
                return item

            if comparisons:
                primary_color = (panel_source["color"]
                                 if source_mode and panel_source is not None
                                 else LINE_COLOR)
                primary_values = self._metric_values(metric, chosen)
                plot.setLabel(
                    "left", self._axis_label(metric, parse_unit(metric)),
                    color=primary_color, size=f"{max(7, base - 1)}pt",
                )
                left = plot.getAxis("left")
                left.setPen(pg.mkPen(primary_color))
                left.setTextPen(pg.mkPen(primary_color))
                legend = plot.addLegend(offset=(10, 8), colCount=3)
                mixed_units = set()
                curve(
                    plot, metric, primary_color, legend,
                    self._legend_label(panel_source, metric), chosen,
                )
                for compare_index, comparison in enumerate(comparisons):
                    compare_source, secondary = self._comparison_series(
                        panel, comparison
                    )
                    secondary_groups = self._series_groups(
                        compare_source, secondary, groups
                    )
                    secondary_color = self._compare_color(compare_index)
                    secondary_values = self._metric_values(
                        secondary, secondary_groups
                    )
                    spec = overlay_spec(
                        metric, secondary, primary_values, secondary_values,
                        ratio_limit=self.axis_ratio_limit(),
                        axis_mode=self.axis_mode_value(),
                    )
                    if spec["mixed_units"]:
                        mixed_units.update((spec["unit"], spec["secondary_unit"]))
                    target = plot
                    if spec["kind"] == "second-axis":
                        target = widget.add_secondary_axis(
                            self._axis_label(secondary, spec["secondary_unit"]),
                            secondary_color,
                        )
                    secondary_label = self._legend_label(compare_source, secondary)
                    curve(
                        target, secondary, secondary_color, legend,
                        secondary_label, secondary_groups,
                        COMPARE_SYMBOLS[compare_index % len(COMPARE_SYMBOLS)],
                    )
                if mixed_units:
                    plot.setLabel(
                        "left", "Mixed units (" + " / ".join(sorted(mixed_units)) + ")",
                        color="#30343b", size=f"{max(7, base - 1)}pt",
                    )
            elif source_mode:
                legend = plot.addLegend(offset=(10, 8))
                color = panel_source["color"] if panel_source else LINE_COLOR
                curve(
                    plot, metric, color, legend,
                    self._legend_label(panel_source, metric), chosen,
                )
            else:
                drawn = np.concatenate([group["positions"] for group in chosen])
                values = self._metric_values(metric, chosen)
                plot.plot(
                    drawn, values, connect="finite",
                    pen=pg.mkPen(LINE_COLOR, width=1.6), symbol="o", symbolSize=4,
                    symbolPen=pg.mkPen(LINE_COLOR), symbolBrush=pg.mkBrush(LINE_COLOR),
                )

            if self.axis_groups:
                for group in self.axis_groups[1:]:
                    plot.addItem(pg.InfiniteLine(pos=group["start"] - .5, angle=90,
                                                 pen=pg.mkPen(BOUNDARY_COLOR, width=1,
                                                              style=Qt.PenStyle.DashLine)))
                visible = self.x_range[1] - self.x_range[0]
                tick_step = tick_spacing(visible, self.panel_pixels)
                tick_positions, tick_labels = sampled_ticks(
                    self.axis_groups, tick_step, visible, self.panel_pixels
                )
                axis.setTicks([list(zip(tick_positions, tick_labels))])
            axis.setStyle(tickFont=widget.font(), tickTextOffset=0)
            axis.setPen(pg.mkPen("#30343b"))
            axis.setTextPen(pg.mkPen("#30343b"))
            if self.axis_groups:
                # A second, linked axis carries the wafer name under each span,
                # so the curve itself stays one continuous line.
                wafer_axis = pg.AxisItem(orientation="bottom")
                wafer_axis.setTicks([list(self.wafer_ticks)])
                wafer_axis.setStyle(tickLength=0, tickTextOffset=4, tickFont=widget.font())
                wafer_axis.setPen(pg.mkPen(QColor(0, 0, 0, 0)))
                wafer_axis.setTextPen(pg.mkPen("#5f6368"))
                plot.layout.addItem(wafer_axis, 4, 1)
                wafer_axis.linkToView(plot.getViewBox())
                wafer_axis.setHeight(max(18, base + 8))
            left = plot.getAxis("left")
            if not comparisons:
                left.setPen(pg.mkPen("#30343b"))
                left.setTextPen(pg.mkPen("#30343b"))
            left.setStyle(tickFont=widget.font())
            view = plot.getViewBox()
            # Left drag selects a region to zoom into; right drag pans.
            view.setMouseMode(pg.ViewBox.RectMode)
            view.setDefaultPadding(HOME_PADDING)
            view.autoRange(padding=HOME_PADDING)
            # The concatenated curves fill the axis in the export too; without
            # this the auto-range padding left a wide blank on both sides.
            view.setXRange(*self.x_range, padding=0)
            for secondary_view in widget.secondary_views:
                secondary_view.setMouseMode(pg.ViewBox.RectMode)
                secondary_view.setDefaultPadding(HOME_PADDING)
                secondary_view.autoRange(padding=HOME_PADDING)
                secondary_view.setXRange(*self.x_range, padding=0)
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            grid.add_panel(container)
            self.plot_widgets.append(widget)
            self.panel_hosts.append(container)
        self.plot_host = grid
        # Swapping the grid resets the scroll bar. Rebuild with painting off and
        # put the offset back before anything is drawn, so the panel list never
        # visibly jumps to the top and returns.
        self.interactive_scroll.setUpdatesEnabled(False)
        try:
            self.interactive_scroll.setWidget(grid)
            self.restore_page_scroll(previous_scroll)
        finally:
            self.interactive_scroll.setUpdatesEnabled(True)
        QTimer.singleShot(0, self.remember_home_views)

    def restore_page_scroll(self, value):
        """Put the panel list back where the engineer left it."""
        self.interactive_scroll.verticalScrollBar().setValue(int(value))

    def remember_home_views(self):
        """Store the view each curve was drawn with, so Reset views can restore it."""
        self.home_views = [
            {
                "primary": widget.getPlotItem().getViewBox().viewRange(),
                "secondary": [view.viewRange() for view in widget.secondary_views],
            }
            for widget in self.plot_widgets
        ]

    def reset_views(self):
        """Restore every curve to the exact range it was drawn with."""
        if not self.plot_widgets:
            return
        if len(self.home_views) != len(self.plot_widgets):
            for widget in self.plot_widgets:
                widget.getPlotItem().getViewBox().autoRange(padding=HOME_PADDING)
                for view in widget.secondary_views:
                    view.autoRange(padding=HOME_PADDING)
            self.remember_home_views()
        else:
            for widget, home in zip(self.plot_widgets, self.home_views):
                widget.getPlotItem().getViewBox().setRange(
                    xRange=home["primary"][0], yRange=home["primary"][1], padding=0
                )
                for view, secondary_home in zip(
                    widget.secondary_views, home["secondary"]
                ):
                    view.setRange(
                        xRange=secondary_home[0], yRange=secondary_home[1], padding=0
                    )
        self.status.setText(f"Reset {len(self.plot_widgets)} curve views.")

    def relayout(self, *_):
        if self.ready:
            columns = min(int(self.columns.currentText()), len(self.panel_specs))
            rows = ceil(len(self.panel_specs) / columns)
            self.base_size = (columns * max(900, min(1900, 180 + 6 * sum(
                len(group["frame"]) for group in self.groups))), rows * 350 + 30)
            self._export_dirty = True
            self._copy_image = None
            self._copy_dpi = None
            self.render_interactive(self.panel_specs, self.groups, columns, rows)

    def restyle(self, *_):
        if not self.ready:
            for text in self.figure.texts:
                text.set_fontsize(max(15, int(self.font_size.currentText()) + 3))
            if self.metrics:
                self.clear_interactive()
            return
        self.relayout()

    def change_resolution(self, *_):
        if self.ready:
            _scale, dpi = resolution_settings(self.resolution)
            effective = export_dpi(self.figure, dpi, MAX_EXPORT_PIXELS)
            note = (f" · capped to {effective} dpi for this {len(self.metrics)}-plot size"
                    if effective < dpi else "")
            self.status.setText(f"PNG output: {dpi} dpi{note}. "
                                "This setting does not change the on-screen curves.")

    def export_png(self):
        if not self.ready:
            return
        self.ensure_export_figure()
        path, _ = QFileDialog.getSaveFileName(self, "Export Die Seq plots", "die_seq_plots.png", "PNG (*.png)")
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
            self.status.setText(f"Exported ({dpi} dpi{note}): {path}")
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
        repaint = self._copy_image is None or self._copy_dpi != cache_key
        controls = [host.side_widget for host in self.panel_hosts
                    if host.side_widget is not None]
        if repaint:
            # The clipboard receives the figure, not the window chrome.
            for control in controls:
                control.setVisible(False)
        try:
            QApplication.processEvents()
            if repaint:
                self._copy_image, scale = widget_to_qimage(
                    self.plot_host, requested / 100, MAX_COPY_PIXELS)
                self._copy_dpi = (requested, self.plot_host.width(), self.plot_host.height())
            else:
                scale = self._copy_image.width() / max(1, self.plot_host.width())
            image = self._copy_image
            dpi = round(scale * 100)
            note = f" · capped from {requested} dpi" if dpi < requested else ""
            QApplication.clipboard().setImage(image)
            self.status.setText(f"Copied Die Seq plots ({dpi} dpi{note}) · "
                                f"{image.width()} × {image.height()} px")
        except Exception as error:
            self.status.setText(f"Copy failed: {error}")
        finally:
            for control in controls:
                control.setVisible(True)
            QApplication.restoreOverrideCursor()


__all__ = ["SequencePage", "find_column", "normalized_name"]
