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
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QInputDialog, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .appearance import (MAX_COPY_PIXELS, MAX_EXPORT_PIXELS, configure_resolution_combo,
                         export_dpi, panel_title_label, resolution_settings)
from .appearance import widget_to_qimage
from .array_plot import drawn_axes
from .data import number
from .dynamic_page import SERIES_COLOURS
from .map_selector import MapSelector
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel
from .settings import get_settings, save_settings
from .trend import overlay_spec, parse_unit


MAX_SEQUENCE_PLOTS = 30
HOME_PADDING = 0.06
LINE_COLOR = "#4472c4"
BOUNDARY_COLOR = "#d4d7dc"
MIN_LABEL_GAP_PIXELS = 30


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
        self.groups = []
        self.metrics = []
        self.panel_specs = []
        stored_overlay = settings.get("trend_overlay", {})
        self.overlay = (dict(stored_overlay)
                        if isinstance(stored_overlay, dict) else {})
        self.overlay_units = {}
        self.wafer_ticks = []
        self.home_views = []
        self.cells = set()
        self._export_dirty = True
        self._copy_image = None
        self._copy_dpi = None
        self.base_size = (1100, 650)
        self.wafer_column = None
        self.die_column = None

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
        self.selector.changed.connect(self.invalidate)
        self.invalidate()

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

    def show_selector(self):
        """Return to the box grid so another set of curves can be chosen."""
        available = bool(self.selector.rowCount() and self.selector.columnCount())
        self.empty.setText("Select measurement sets and numeric parameters in the Data tab "
                           "to create boxes.")
        self.stack.setCurrentWidget(self.selector_panel if available else self.empty)

    def invalidate(self):
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

    def _sequence_groups(self):
        """Append every measurement set to one axis; nothing is split off."""
        groups, cursor = [], 0
        labels = self.selection.get("labels", {})
        sources = self.selection.get("sources", ())
        for key, part in self._parts():
            if part.empty:
                continue
            ordered = part.assign(__die=number(part[self.die_column])).dropna(subset=["__die"])
            ordered = ordered.sort_values("__die", kind="stable")
            if ordered.empty:
                continue
            source = next((
                item for item in sources if key in item.get("keys", ())
            ), None)
            positions = (
                ordered["__die"].to_numpy(float)
                if source is not None
                else np.arange(cursor, cursor + len(ordered), dtype=float)
            )
            wafer_values = ordered[self.wafer_column].fillna("").astype(str).str.strip()
            wafer_id = next((value for value in wafer_values if value), "")
            if not wafer_id:
                wafer_id = str(labels.get(key, key)).splitlines()[0]
            if source is not None:
                wafer_id = source["name"]
            groups.append({"key": key, "wafer": wafer_id, "frame": ordered,
                           "positions": positions, "center": float(positions.mean()),
                           "start": float(np.min(positions)),
                           "stop": float(np.max(positions)),
                           "source": source})
            if source is None:
                cursor += len(ordered)
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
        available = {
            ((panel["source"] or {}).get("name"), panel["metric"])
            for panel in base
        }
        reverse = {secondary: primary for primary, secondary in self.overlay.items()}
        panels = []
        for panel in base:
            source_name = (panel["source"] or {}).get("name")
            metric = panel["metric"]
            primary = reverse.get(metric)
            if primary and (source_name, primary) in available:
                continue
            secondary = self.overlay.get(metric)
            panels.append({**panel, "secondary": secondary})
        return panels

    def _prune_overlay(self, metrics):
        available = set(metrics)
        checked = {metric for _key, metric in self.cells}
        self.overlay = {
            primary: secondary
            for primary, secondary in self.overlay.items()
            if primary in available and secondary in available
            and primary in checked and secondary in checked and primary != secondary
        }
        self.overlay_units = {
            metric: parse_unit(metric)
            for pair in self.overlay.items() for metric in pair
        }

    def _persist_overlay(self):
        try:
            save_settings({"trend_overlay": dict(self.overlay)})
        except OSError as error:
            self.status.setText(f"Could not save Trend comparison: {error}")

    def _participants(self):
        return set(self.overlay) | set(self.overlay.values())

    def set_overlay(self, primary, secondary):
        """Merge two checked metrics; a metric cannot join a third curve."""
        primary, secondary = str(primary), str(secondary)
        if primary == secondary or primary not in self.metrics or secondary not in self.metrics:
            self.status.setText("Choose two different selected parameters.")
            return False
        participants = self._participants()
        existing = self.overlay.get(primary)
        if existing == secondary:
            return True
        if primary in participants or secondary in participants:
            self.status.setText("仅支持两个参数叠加对比；请先解除当前对比。")
            return False
        self.overlay[primary] = secondary
        self.overlay_units.update({primary: parse_unit(primary), secondary: parse_unit(secondary)})
        self._persist_overlay()
        self.draw_plot()
        return True

    def unlink_overlay(self, metric):
        primary = metric if metric in self.overlay else next(
            (key for key, value in self.overlay.items() if value == metric), None
        )
        if primary is None:
            return False
        self.overlay.pop(primary, None)
        self._persist_overlay()
        self.draw_plot()
        return True

    def _overlay_candidates(self, metric):
        checked = {name for _key, name in self.cells}
        participants = self._participants()
        return [name for name in self.metrics
                if name != metric and name in checked and name not in participants]

    def choose_overlay(self, metric):
        candidates = self._overlay_candidates(metric)
        if not candidates:
            self.status.setText("No other checked parameter is available for comparison.")
            return
        selected, accepted = QInputDialog.getItem(
            self, "叠加对比", "选择第二个参数：", candidates, 0, False
        )
        if accepted:
            self.set_overlay(metric, selected)

    def build_overlay_control(self, metric, secondary):
        """Compare control that sits beside the plot instead of inside a menu.

        Overlay comparison used to hide in the plot's right-click menu, which
        overlapped PyQtGraph's own menu and made a primary action undiscoverable.
        The button therefore carries both states: start a comparison, or remove
        the one this panel is part of.
        """
        control = QPushButton(objectName="subtle")
        control.setFixedHeight(26)
        control.setFixedWidth(92)
        if secondary is None:
            control.setText("叠加对比…")
            available = bool(self._overlay_candidates(metric))
            control.setEnabled(available)
            control.setToolTip(
                "把另一个已勾选的参数叠加到这张图上：同单位共用左轴，"
                "不同或无法识别的单位自动增加着色右轴。" if available
                else "没有其它已勾选的参数可以叠加。"
            )
            control.clicked.connect(
                lambda _checked=False, name=metric: self.choose_overlay(name)
            )
        else:
            control.setText("解除对比")
            control.setToolTip("解除对比，恢复一个参数一张图。")
            control.clicked.connect(
                lambda _checked=False, name=metric: self.unlink_overlay(name)
            )
        return control

    def draw_plot(self, *_):
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
            groups, extent = self._sequence_groups()
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
            if self.selection.get("sources"):
                start = min(group["start"] for group in self.view_groups)
                stop = max(group["stop"] for group in self.view_groups)
                padding = max(.5, (stop - start) * .03)
                self.x_range = (start - padding, stop + padding)
            else:
                self.x_range = (
                    min(group["start"] for group in self.view_groups) - 1,
                    max(group["stop"] for group in self.view_groups) + 1,
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
            self.export_button.setEnabled(True)
            self.copy_button.setEnabled(True)
            self.stack.setCurrentWidget(self.interactive_scroll)
            comparison = (f" · {len(self.overlay)} comparison"
                          if self.overlay else "")
            self.status.setText(f"{len(self.metrics)} of {len(metrics)} parameters · "
                                f"{len(drawn_wafers)} of {len(wafers)} measurement sets · "
                                f"{total_points} Die Seq positions{comparison}.")
            if self._has_magnitude_warning():
                self.status.setText(
                    self.status.text()
                    + " 已使用第二根 Y 轴，交叉点无物理含义。"
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

    def _has_magnitude_warning(self):
        for panel in self.panel_specs:
            secondary = panel.get("secondary")
            if secondary is None:
                continue
            chosen = self._chosen_groups(panel, self.groups)
            spec = overlay_spec(
                panel["metric"], secondary,
                self._metric_values(panel["metric"], chosen),
                self._metric_values(secondary, chosen),
            )
            if spec["magnitude_warning"]:
                return True
        return False

    def _missing_overlay_metrics(self):
        missing = []
        for panel in self.panel_specs:
            secondary = panel.get("secondary")
            if secondary is None:
                continue
            chosen = self._chosen_groups(panel, self.groups)
            values = self._metric_values(secondary, chosen)
            if not np.isfinite(values).any() and secondary not in missing:
                missing.append(secondary)
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

    def _metric_color(self, metric):
        try:
            index = self.metrics.index(metric)
        except ValueError:
            index = 0
        return SERIES_COLOURS[index % len(SERIES_COLOURS)]

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
        for ax, panel in zip(axes.flat, panels):
            metric, panel_source = panel["metric"], panel["source"]
            secondary = panel.get("secondary")
            chosen = self._chosen_groups(panel, groups)
            source_mode = bool(self.selection.get("sources"))
            wafer_texts = []
            tick_positions = sorted({
                float(position) for group in chosen
                for position in group["positions"]
            }) if source_mode else None
            tick_labels = ([format_die(value) for value in tick_positions]
                           if source_mode else None)
            if not source_mode:
                tick_positions, tick_labels = sampled_ticks(
                    self.view_groups, tick_step, visible, self.panel_pixels
                )
                for group_index, group in enumerate(self.view_groups):
                    wafer_texts.append(ax.text(group["center"], -.18, group["wafer"],
                                                transform=ax.get_xaxis_transform(), ha="center", va="top",
                                                fontsize=max(6, base - 2), color="#5f6368", clip_on=False))
                    if group_index:
                        ax.axvline(group["start"] - .5, color=BOUNDARY_COLOR, linewidth=.8, zorder=0)

            def plot_metric(target, name, color, label):
                lines, value_sets = [], []
                if source_mode:
                    for group in chosen:
                        values = number(group["frame"][name]).to_numpy(float)
                        value_sets.append(values)
                        source = group["source"]
                        lines.extend(target.plot(
                            group["positions"], values,
                            color=color, linestyle=self._source_line_style(source),
                            linewidth=1.35, marker="o", markersize=3.8,
                            markerfacecolor=color, label=label,
                        ))
                else:
                    positions = np.concatenate([group["positions"] for group in chosen])
                    values = self._metric_values(name, chosen)
                    value_sets.append(values)
                    lines.extend(target.plot(
                        positions, values, color=color, linewidth=1.35,
                        marker="o", markersize=3.8, markerfacecolor=color,
                        label=label,
                    ))
                values = np.concatenate(value_sets) if value_sets else np.asarray([])
                return lines, values

            normal_color = (panel_source["color"]
                            if source_mode and panel_source is not None else LINE_COLOR)
            primary_color = self._metric_color(metric) if secondary else normal_color
            primary_label = (metric if secondary else
                             (panel_source["name"] if panel_source else None))
            primary_lines, values = plot_metric(
                ax, metric, primary_color, primary_label
            )
            twin = None
            legend_lines = list(primary_lines[:1])
            if secondary:
                secondary_values = self._metric_values(secondary, chosen)
                spec = overlay_spec(metric, secondary, values, secondary_values)
                secondary_color = self._metric_color(secondary)
                target = ax
                if spec["kind"] == "second-axis":
                    twin = ax.twinx()
                    twin.spines.right.set_position(("axes", 1.06))
                    twin.set_ylabel(
                        self._axis_label(secondary, spec["secondary_unit"]),
                        color=secondary_color, fontsize=max(7, base - 1),
                    )
                    twin.tick_params(axis="y", colors=secondary_color,
                                     labelsize=max(6, base - 2))
                    target = twin
                secondary_label = self._axis_label(
                    secondary, spec["secondary_unit"]
                ) if spec["secondary_unit"] is None else secondary
                secondary_lines, _secondary_values = plot_metric(
                    target, secondary, secondary_color, secondary_label
                )
                legend_lines.extend(secondary_lines[:1])
                if legend_lines:
                    ax.legend(
                        legend_lines, [line.get_label() for line in legend_lines],
                        fontsize=max(6, base - 2), frameon=False, ncol=2,
                    )
            elif source_mode:
                ax.legend(fontsize=max(6, base - 2), frameon=False)
            if not np.isfinite(values).any():
                ax.text(.5, .5, "No valid numeric values", transform=ax.transAxes,
                        ha="center", va="center", fontsize=max(11, base))
            if secondary:
                title = f"{metric} + {secondary}"
            else:
                title = (f"{panel_source['name']} · {metric}"
                         if panel_source is not None else str(metric))
            ax.set_title(title, fontsize=base + 1, fontweight="semibold", pad=8)
            ylabel_options = {"fontsize": max(7, base - 1)}
            if secondary:
                ylabel_options["color"] = primary_color
            ax.set_ylabel(
                self._axis_label(metric, parse_unit(metric)) if secondary else "Value",
                **ylabel_options,
            )
            if secondary:
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
            if twin is not None:
                twin.set_xlim(*self.x_range)
                twin._wafer_group_labels = wafer_texts
                twin._die_sequence_values = ax._die_sequence_values
                twin._wafer_ids = ax._wafer_ids
        for ax in axes.flat[len(panels):]:
            ax.set_axis_off()
        right = .90 if any(panel.get("secondary") for panel in panels) else .985
        self.figure.subplots_adjust(left=.065, right=right, top=.965, bottom=.09,
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
        """Render ordinary panels or explicit two-parameter comparisons."""
        self.clear_interactive()
        base = int(self.font_size.currentText())
        panel_height = 320
        grid = PanelGrid(columns)
        grid.set_minimum_row_height(rows, panel_height)
        self.wafer_ticks = [(group["center"], group["wafer"]) for group in self.view_groups]
        for panel in panels:
            metric, panel_source = panel["metric"], panel["source"]
            secondary = panel.get("secondary")
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
            if secondary:
                title = f"{metric} + {secondary}（对比）"
            else:
                title = (f"{panel_source['name']} · {metric}"
                         if panel_source is not None else str(metric))
            heading = panel_title_label(f"<b>{escape(title)}</b>", base + 1)
            container = PlotPanel(
                heading, widget, side_widget=self.build_overlay_control(metric, secondary)
            )
            chosen = self._chosen_groups(panel, groups)
            axis = plot.getAxis("bottom")
            source_mode = bool(self.selection.get("sources"))

            def curve(target, name, color, legend, label):
                first_item = None
                for group in chosen:
                    source = group.get("source")
                    values = number(group["frame"][name]).to_numpy(float)
                    pen = pg.mkPen(
                        color, width=1.6,
                        style=self._source_line_style(source, qt=True),
                    )
                    item = pg.PlotDataItem(
                        group["positions"], values, connect="finite", pen=pen,
                        symbol="o", symbolSize=4, symbolPen=pg.mkPen(color),
                        symbolBrush=pg.mkBrush(color),
                        name=label if first_item is None else None,
                    )
                    target.addItem(item)
                    first_item = first_item or item
                if (legend is not None and first_item is not None
                        and target is not plot):
                    legend.addItem(first_item, label)
                return first_item

            if secondary:
                primary_color = self._metric_color(metric)
                secondary_color = self._metric_color(secondary)
                primary_values = self._metric_values(metric, chosen)
                secondary_values = self._metric_values(secondary, chosen)
                spec = overlay_spec(
                    metric, secondary, primary_values, secondary_values
                )
                plot.setLabel(
                    "left", self._axis_label(metric, spec["unit"]),
                    color=primary_color, size=f"{max(7, base - 1)}pt",
                )
                left = plot.getAxis("left")
                left.setPen(pg.mkPen(primary_color))
                left.setTextPen(pg.mkPen(primary_color))
                legend = plot.addLegend(offset=(10, 8), colCount=2)
                curve(plot, metric, primary_color, legend, metric)
                target = plot
                if spec["kind"] == "second-axis":
                    target = widget.add_secondary_axis(
                        self._axis_label(secondary, spec["secondary_unit"]),
                        secondary_color,
                    )
                secondary_label = (secondary if spec["secondary_unit"] is not None
                                   else f"{secondary} (unit?)")
                curve(target, secondary, secondary_color, legend, secondary_label)
            elif source_mode:
                legend = plot.addLegend(offset=(10, 8))
                color = panel_source["color"] if panel_source else LINE_COLOR
                curve(plot, metric, color, legend,
                      panel_source["name"] if panel_source else metric)
            else:
                drawn = np.concatenate([group["positions"] for group in chosen])
                values = self._metric_values(metric, chosen)
                plot.plot(
                    drawn, values, connect="finite",
                    pen=pg.mkPen(LINE_COLOR, width=1.6), symbol="o", symbolSize=4,
                    symbolPen=pg.mkPen(LINE_COLOR), symbolBrush=pg.mkBrush(LINE_COLOR),
                )

            if not source_mode:
                for group in self.view_groups[1:]:
                    plot.addItem(pg.InfiniteLine(pos=group["start"] - .5, angle=90,
                                                 pen=pg.mkPen(BOUNDARY_COLOR, width=1,
                                                              style=Qt.PenStyle.DashLine)))
                visible = self.x_range[1] - self.x_range[0]
                tick_step = tick_spacing(visible, self.panel_pixels)
                tick_positions, tick_labels = sampled_ticks(
                    self.view_groups, tick_step, visible, self.panel_pixels
                )
                axis.setTicks([list(zip(tick_positions, tick_labels))])
            axis.setStyle(tickFont=widget.font(), tickTextOffset=0)
            axis.setPen(pg.mkPen("#30343b"))
            axis.setTextPen(pg.mkPen("#30343b"))
            if not source_mode:
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
            if not secondary:
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
        self.interactive_scroll.setWidget(grid)
        QTimer.singleShot(0, self.remember_home_views)

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
