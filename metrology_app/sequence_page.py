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
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .appearance import (MAX_COPY_PIXELS, MAX_EXPORT_PIXELS, configure_resolution_combo,
                         export_dpi, panel_title_label, resolution_settings)
from .appearance import widget_to_qimage
from .array_plot import drawn_axes
from .data import number
from .map_selector import MapSelector
from .plotting import InteractivePlotWidget, PanelGrid, PlotPanel
from .settings import get_settings


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
            "Scroll to zoom · Drag a box to zoom · Right-drag to pan.\n"
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
        self.selector.set_array(selection.get("wafers", []), selection.get("metrics", []),
                                selection.get("labels"))
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
        for key, part in self._parts():
            if part.empty:
                continue
            ordered = part.assign(__die=number(part[self.die_column])).dropna(subset=["__die"])
            ordered = ordered.sort_values("__die", kind="stable")
            if ordered.empty:
                continue
            positions = np.arange(cursor, cursor + len(ordered), dtype=float)
            wafer_values = ordered[self.wafer_column].fillna("").astype(str).str.strip()
            wafer_id = next((value for value in wafer_values if value), "")
            if not wafer_id:
                wafer_id = str(labels.get(key, key)).splitlines()[0]
            groups.append({"key": key, "wafer": wafer_id, "frame": ordered,
                           "positions": positions, "center": float(positions.mean()),
                           "start": float(cursor), "stop": float(cursor + len(ordered))})
            cursor += len(ordered)
        return groups, cursor

    @staticmethod
    def _format_die(value):
        return f"{value:g}" if np.isfinite(value) else ""

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
            # Keep every panel on the same X frame, but shrink it to the spans
            # that actually carry a drawn curve instead of reserving blank
            # space for measurement sets the user left out.
            used = [group for group in groups
                    if any((group["key"], metric) in cells for metric in self.metrics)]
            self.view_groups = used or groups
            self.x_range = (min(group["start"] for group in self.view_groups) - 1,
                            max(group["stop"] for group in self.view_groups) + 1)
            total_points = sum(len(group["frame"]) for group in groups)
            columns = min(int(self.columns.currentText()), len(self.metrics))
            rows = ceil(len(self.metrics) / columns)
            panel_width = max(900, min(1900, 180 + 6 * total_points))
            self.base_size = (columns * panel_width, rows * 350 + 30)
            self.panel_pixels = max(320, panel_width - 150)
            self._export_dirty = True
            self._copy_image = None
            self._copy_dpi = None
            self.render_interactive(self.metrics, groups, columns, rows)
            self.ready = True
            self.export_button.setEnabled(True)
            self.copy_button.setEnabled(True)
            self.stack.setCurrentWidget(self.interactive_scroll)
            self.status.setText(f"{len(self.metrics)} of {len(metrics)} parameters · "
                                f"{len(drawn_wafers)} of {len(wafers)} measurement sets · "
                                f"{total_points} Die Seq positions.")
        except (ValueError, KeyError) as error:
            self.invalidate()
            self.status.setText(str(error))

    def ensure_export_figure(self):
        """Build the Matplotlib export mirror only when Export / Copy needs it."""
        if self._export_dirty or not self.figure.axes:
            self.build_export_figure(self.metrics or [], self.view_groups or self.groups)
            self._export_dirty = False

    def build_export_figure(self, metrics, groups):
        """Matplotlib mirror of the on-screen grid, used for Export / Copy PNG."""
        columns = min(int(self.columns.currentText()), len(metrics))
        rows = ceil(len(metrics) / columns)
        width, height = self.base_size
        base = int(self.font_size.currentText())
        total_points = sum(len(group["frame"]) for group in groups)
        visible = self.x_range[1] - self.x_range[0]
        tick_step = tick_spacing(visible, self.panel_pixels)
        self.figure.clear()
        self.figure.set_size_inches(width / 100, height / 100, forward=False)
        axes = self.figure.subplots(rows, columns, squeeze=False)
        for ax, metric in zip(axes.flat, metrics):
            chosen = [group for group in groups if (group["key"], metric) in self.cells]
            positions = np.concatenate([group["positions"] for group in chosen])
            values = np.concatenate([number(group["frame"][metric]).to_numpy(float)
                                     for group in chosen])
            ax.plot(positions, values, color=LINE_COLOR, linewidth=1.35,
                    marker="o", markersize=3.8, markerfacecolor=LINE_COLOR)
            tick_positions, tick_labels = sampled_ticks(self.view_groups, tick_step, visible,
                                                        self.panel_pixels)
            wafer_texts = []
            for group_index, group in enumerate(self.view_groups):
                wafer_texts.append(ax.text(group["center"], -.18, group["wafer"],
                                            transform=ax.get_xaxis_transform(), ha="center", va="top",
                                            fontsize=max(6, base - 2), color="#5f6368", clip_on=False))
                if group_index:
                    ax.axvline(group["start"] - .5, color=BOUNDARY_COLOR, linewidth=.8, zorder=0)
            if not np.isfinite(values).any():
                ax.text(.5, .5, "No valid numeric values", transform=ax.transAxes,
                        ha="center", va="center", fontsize=max(11, base))
            ax.set_title(str(metric), fontsize=base + 1, fontweight="semibold", pad=8)
            ax.set_ylabel("Value", fontsize=max(7, base - 1))
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
        for ax in axes.flat[len(metrics):]:
            ax.set_axis_off()
        self.figure.subplots_adjust(left=.065, right=.985, top=.965, bottom=.09,
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

    def render_interactive(self, metrics, groups, columns, rows):
        """One zoomable PyQtGraph curve per numeric parameter, in a resizable grid."""
        self.clear_interactive()
        base = int(self.font_size.currentText())
        panel_height = 320
        grid = PanelGrid(columns)
        grid.set_minimum_row_height(rows, panel_height)
        positions = np.concatenate([group["positions"] for group in groups])
        self.wafer_ticks = [(group["center"], group["wafer"]) for group in self.view_groups]
        for rank, metric in enumerate(metrics):
            widget = InteractivePlotWidget(background="w", auto_x_range=self.x_range)
            widget.setMinimumSize(360, 280)
            widget.setToolTip("Scroll to zoom · Drag a box to zoom · Right-drag to pan · "
                              "Double-click to fit this curve · Reset views restores all curves")
            plot = widget.getPlotItem()
            plot.setTitle(None)   # the QLabel above the plot owns the heading
            plot.showGrid(x=False, y=True, alpha=.18)
            plot.setLabel("left", "Value", color="#30343b", size=f"{max(7, base - 1)}pt")
            heading = panel_title_label(f"<b>{escape(str(metric))}</b>", base + 1)
            container = PlotPanel(heading, widget)
            chosen = [group for group in groups if (group["key"], metric) in self.cells]
            drawn = np.concatenate([group["positions"] for group in chosen])
            values = np.concatenate([number(group["frame"][metric]).to_numpy(float)
                                     for group in chosen])
            plot.plot(drawn, values, connect="finite", pen=pg.mkPen(LINE_COLOR, width=1.6),
                      symbol="o", symbolSize=4, symbolPen=pg.mkPen(LINE_COLOR),
                      symbolBrush=pg.mkBrush(LINE_COLOR))
            for group in self.view_groups[1:]:
                plot.addItem(pg.InfiniteLine(pos=group["start"] - .5, angle=90,
                                             pen=pg.mkPen(BOUNDARY_COLOR, width=1,
                                                          style=Qt.PenStyle.DashLine)))
            axis = plot.getAxis("bottom")
            visible = self.x_range[1] - self.x_range[0]
            tick_step = tick_spacing(visible, self.panel_pixels)
            tick_positions, tick_labels = sampled_ticks(self.view_groups, tick_step, visible,
                                                        self.panel_pixels)
            detail = list(zip(tick_positions, tick_labels))
            axis.setTicks([detail])
            axis.setStyle(tickFont=widget.font(), tickTextOffset=0)
            axis.setPen(pg.mkPen("#30343b"))
            axis.setTextPen(pg.mkPen("#30343b"))
            # A second, linked axis carries the wafer name under each span, so the
            # curve itself stays one continuous line.
            wafer_axis = pg.AxisItem(orientation="bottom")
            wafer_axis.setTicks([list(self.wafer_ticks)])
            wafer_axis.setStyle(tickLength=0, tickTextOffset=4, tickFont=widget.font())
            wafer_axis.setPen(pg.mkPen(QColor(0, 0, 0, 0)))
            wafer_axis.setTextPen(pg.mkPen("#5f6368"))
            plot.layout.addItem(wafer_axis, 4, 1)
            wafer_axis.linkToView(plot.getViewBox())
            wafer_axis.setHeight(max(18, base + 8))
            left = plot.getAxis("left")
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
            grid.add_panel(container)
            self.plot_widgets.append(widget)
            self.panel_hosts.append(container)
        self.plot_host = grid
        self.interactive_scroll.setWidget(grid)
        QTimer.singleShot(0, self.remember_home_views)

    def remember_home_views(self):
        """Store the view each curve was drawn with, so Reset views can restore it."""
        self.home_views = [widget.getPlotItem().getViewBox().viewRange()
                           for widget in self.plot_widgets]

    def reset_views(self):
        """Restore every curve to the exact range it was drawn with."""
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
        self.status.setText(f"Reset {len(self.plot_widgets)} curve views.")

    def relayout(self, *_):
        if self.ready:
            columns = min(int(self.columns.currentText()), len(self.metrics))
            rows = ceil(len(self.metrics) / columns)
            self.base_size = (columns * max(900, min(1900, 180 + 6 * sum(
                len(group["frame"]) for group in self.groups))), rows * 350 + 30)
            self._export_dirty = True
            self._copy_image = None
            self._copy_dpi = None
            self.render_interactive(self.metrics, self.groups, columns, rows)

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
            self.status.setText(f"Copied Die Seq plots ({dpi} dpi{note}) · "
                                f"{image.width()} × {image.height()} px")
        except Exception as error:
            self.status.setText(f"Copy failed: {error}")
        finally:
            QApplication.restoreOverrideCursor()


__all__ = ["SequencePage", "find_column", "normalized_name"]
